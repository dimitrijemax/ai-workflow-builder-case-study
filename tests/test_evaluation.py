"""Contract and behavioral tests for the evaluation fixtures, gates, evaluator, and rendering.

Contract tests (fixtures validate against the strict models, the corpus loader rejects malformed
corpora, golden labels conform to the untouched provider/validators, and the gate/output models
enforce their invariants) pass. Phase 2 behavioral tests (metric math, confusion math, JSON/
Markdown rendering, deterministic reruns, the privacy scanner) also pass now that the
owner-approved evaluator is implemented; their former strict-xfail RED-boundary markers were
removed once each test genuinely passed against the real implementation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_workflow_builder.evaluation import (
    CANONICAL_ISSUE_CODES,
    CORPUS_VERSION,
    MANDATORY_LIMITATIONS,
    MAX_FAILURE_ROWS,
    PROVIDER_ID,
    SCHEMA_VERSION,
    CorpusError,
    EvaluationOutput,
    FailureRow,
    GatesFile,
    MetricValue,
    PerCodeConfusion,
    PipelineCase,
    PipelineCasesAdapter,
    RateGate,
    RubricCase,
    RubricCasesAdapter,
    load_corpus,
    load_gates,
    validate_cross_suite,
    validate_pipeline_corpus,
    validate_rubric_corpus,
)
from ai_workflow_builder.providers import DeterministicRuleProvider
from ai_workflow_builder.schemas import InsightCategory, OpsInsight
from ai_workflow_builder.validators import validate_insight

EVALS_DIR = Path(__file__).resolve().parents[1] / "evals"
PIPELINE_PATH = EVALS_DIR / "pipeline_cases.json"
RUBRIC_PATH = EVALS_DIR / "rubric_cases.json"


def load_pipeline_cases() -> list[PipelineCase]:
    payload = json.loads(PIPELINE_PATH.read_text(encoding="utf-8"))
    return PipelineCasesAdapter.validate_python(payload)


def load_rubric_cases() -> list[RubricCase]:
    payload = json.loads(RUBRIC_PATH.read_text(encoding="utf-8"))
    return RubricCasesAdapter.validate_python(payload)


def _pipeline_case(case_id: str, note_id: str, codes: list[str] | None = None) -> PipelineCase:
    codes = codes or []
    return PipelineCase.model_validate(
        {
            "case_id": case_id,
            "note": {
                "id": note_id,
                "channel": "chat",
                "text": "A synthetic note used only to exercise the corpus rules.",
                "created_at": "day_01_09",
            },
            "expected_category": "other",
            "expected_sentiment": "neutral",
            "expected_issue_codes": codes,
            "expected_review_required": bool(codes),
            "label_rationale": "Synthetic case exercising the strict corpus rules.",
            "tags": [],
        }
    )


def _rubric_case(case_id: str, note_id: str, codes: list[str] | None = None) -> RubricCase:
    codes = codes or []
    return RubricCase.model_validate(
        {
            "case_id": case_id,
            "insight": {
                "note_id": note_id,
                "category": "other",
                "sentiment": "neutral",
                "summary": "Synthetic insight exercising the strict corpus rules.",
                "action_items": [],
                "confidence": 0.5,
            },
            "expected_issue_codes": codes,
            "expected_review_required": bool(codes),
            "label_rationale": "Synthetic case exercising the strict corpus rules.",
            "tags": [],
        }
    )


def _raw_pipeline_payload(
    case_id: str, note_id: str, issue_codes: list[str], review_required: bool
) -> dict:
    """Unvalidated Suite A payload, for exercising rejection through corpus-level loading."""
    return {
        "case_id": case_id,
        "note": {
            "id": note_id,
            "channel": "chat",
            "text": "A synthetic note used only to exercise the corpus rules.",
            "created_at": "day_01_09",
        },
        "expected_category": "other",
        "expected_sentiment": "neutral",
        "expected_issue_codes": issue_codes,
        "expected_review_required": review_required,
        "label_rationale": "Synthetic case exercising the strict corpus rules.",
        "tags": [],
    }


def _raw_rubric_payload(
    case_id: str, note_id: str, issue_codes: list[str], review_required: bool
) -> dict:
    """Unvalidated Suite B payload, for exercising rejection through corpus-level loading."""
    return {
        "case_id": case_id,
        "insight": {
            "note_id": note_id,
            "category": "other",
            "sentiment": "neutral",
            "summary": "Synthetic insight exercising the strict corpus rules.",
            "action_items": [],
            "confidence": 0.5,
        },
        "expected_issue_codes": issue_codes,
        "expected_review_required": review_required,
        "label_rationale": "Synthetic case exercising the strict corpus rules.",
        "tags": [],
    }


# --------------------------------------------------------------------------------------------
# Fixture / corpus acceptance tests (pass)
# --------------------------------------------------------------------------------------------


def test_pipeline_cases_valid_and_within_budget() -> None:
    assert 12 <= len(load_pipeline_cases()) <= 14


def test_rubric_cases_valid_count() -> None:
    assert len(load_rubric_cases()) == 6


def test_total_corpus_within_budget() -> None:
    total = len(load_pipeline_cases()) + len(load_rubric_cases())
    assert 17 <= total <= 20


def test_real_corpus_loads_and_validates() -> None:
    pipeline, rubric = load_corpus(PIPELINE_PATH, RUBRIC_PATH)
    assert len(pipeline) == 12
    assert len(rubric) == 6


def test_review_required_equals_bool_issue_codes() -> None:
    for case in load_pipeline_cases():
        assert case.expected_review_required == bool(case.expected_issue_codes)
    for case in load_rubric_cases():
        assert case.expected_review_required == bool(case.expected_issue_codes)


def test_pipeline_covers_every_provider_category() -> None:
    covered = {case.expected_category for case in load_pipeline_cases()}
    assert covered == set(InsightCategory)


def test_rubric_positive_support_for_every_code() -> None:
    cases = load_rubric_cases()
    for code in CANONICAL_ISSUE_CODES:
        assert any(code in c.expected_issue_codes for c in cases), code


def test_suite_a_has_reachable_multi_issue_case() -> None:
    assert any(
        case.expected_issue_codes == ["low_confidence", "negative_without_action"]
        for case in load_pipeline_cases()
    )


def test_suite_a_has_collision_and_confidence_boundary_cases() -> None:
    tags = [tag for case in load_pipeline_cases() for tag in case.tags]
    assert "collision" in tags
    assert "confidence_boundary" in tags


def test_suite_b_has_clean_boundary_and_multi_issue_cases() -> None:
    tags = [tag for case in load_rubric_cases() for tag in case.tags]
    assert "clean" in tags
    assert "boundary" in tags
    assert "multi_issue" in tags


# --------------------------------------------------------------------------------------------
# Corpus-level rejection tests (pass) — malformed corpora must raise, not be repaired
# --------------------------------------------------------------------------------------------


def test_corpus_rejects_non_canonical_order() -> None:
    cases = [_pipeline_case("A-02", "OPS-1"), _pipeline_case("A-01", "OPS-2")]
    with pytest.raises(CorpusError):
        validate_pipeline_corpus(cases)


def test_corpus_rejects_wrong_suite_prefix() -> None:
    cases = [_pipeline_case("B-01", "OPS-1")]
    with pytest.raises(CorpusError):
        validate_pipeline_corpus(cases)


def test_corpus_rejects_duplicate_case_ids() -> None:
    cases = [_pipeline_case("A-01", "OPS-1"), _pipeline_case("A-01", "OPS-2")]
    with pytest.raises(CorpusError):
        validate_pipeline_corpus(cases)


def test_corpus_rejects_duplicate_note_ids() -> None:
    cases = [_pipeline_case("A-01", "OPS-1"), _pipeline_case("A-02", "OPS-1")]
    with pytest.raises(CorpusError):
        validate_pipeline_corpus(cases)


def test_rubric_corpus_rejects_wrong_prefix() -> None:
    cases = [_rubric_case("A-01", "INS-1")]
    with pytest.raises(CorpusError):
        validate_rubric_corpus(cases)


def test_cross_suite_rejects_shared_case_id() -> None:
    pipeline = [_pipeline_case("A-01", "OPS-1")]
    rubric = [_rubric_case("A-01", "INS-1")]
    with pytest.raises(CorpusError):
        validate_cross_suite(pipeline, rubric)


def test_cross_suite_rejects_shared_note_id() -> None:
    pipeline = [_pipeline_case("A-01", "SHARED-1")]
    rubric = [_rubric_case("B-01", "SHARED-1")]
    with pytest.raises(CorpusError):
        validate_cross_suite(pipeline, rubric)


# --------------------------------------------------------------------------------------------
# Corpus-level rejection of issue-code and review-boolean invariants (pass) — a malformed case
# anywhere in a multi-case corpus list must reject the whole load, not just a lone case object.
# --------------------------------------------------------------------------------------------


def test_pipeline_corpus_list_rejects_unknown_issue_code() -> None:
    valid = _raw_pipeline_payload("A-01", "OPS-1", [], False)
    invalid = _raw_pipeline_payload("A-02", "OPS-2", ["not_a_real_code"], True)
    with pytest.raises(ValidationError):
        PipelineCasesAdapter.validate_python([valid, invalid])


def test_pipeline_corpus_list_rejects_duplicate_issue_codes() -> None:
    valid = _raw_pipeline_payload("A-01", "OPS-1", [], False)
    invalid = _raw_pipeline_payload("A-02", "OPS-2", ["low_confidence", "low_confidence"], True)
    with pytest.raises(ValidationError):
        PipelineCasesAdapter.validate_python([valid, invalid])


def test_pipeline_corpus_list_rejects_noncanonical_issue_order() -> None:
    valid = _raw_pipeline_payload("A-01", "OPS-1", [], False)
    invalid = _raw_pipeline_payload(
        "A-02", "OPS-2", ["negative_without_action", "low_confidence"], True
    )
    with pytest.raises(ValidationError):
        PipelineCasesAdapter.validate_python([valid, invalid])


def test_pipeline_corpus_list_rejects_review_boolean_mismatch() -> None:
    valid = _raw_pipeline_payload("A-01", "OPS-1", [], False)
    invalid = _raw_pipeline_payload("A-02", "OPS-2", ["low_confidence"], False)
    with pytest.raises(ValidationError):
        PipelineCasesAdapter.validate_python([valid, invalid])


def test_rubric_corpus_list_rejects_unknown_issue_code() -> None:
    valid = _raw_rubric_payload("B-01", "INS-1", [], False)
    invalid = _raw_rubric_payload("B-02", "INS-2", ["not_a_real_code"], True)
    with pytest.raises(ValidationError):
        RubricCasesAdapter.validate_python([valid, invalid])


def test_rubric_corpus_list_rejects_review_boolean_mismatch() -> None:
    valid = _raw_rubric_payload("B-01", "INS-1", [], False)
    invalid = _raw_rubric_payload("B-02", "INS-2", ["low_confidence"], False)
    with pytest.raises(ValidationError):
        RubricCasesAdapter.validate_python([valid, invalid])


def test_load_corpus_rejects_file_with_malformed_review_boolean(tmp_path) -> None:
    """End-to-end: a real corpus *file* with one bad case must reject through ``load_corpus``."""
    payload = json.loads(PIPELINE_PATH.read_text(encoding="utf-8"))
    assert payload[0]["case_id"] == "A-01"
    assert payload[0]["expected_issue_codes"] == []
    payload[0]["expected_review_required"] = True
    corrupt = tmp_path / "pipeline_cases.json"
    corrupt.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_corpus(corrupt, RUBRIC_PATH)


# --------------------------------------------------------------------------------------------
# Baseline conformance against the untouched provider and validators (pass)
# --------------------------------------------------------------------------------------------


def test_pipeline_baseline_conformance_is_total() -> None:
    provider = DeterministicRuleProvider()
    for case in load_pipeline_cases():
        insight = OpsInsight.model_validate(provider.extract_insight(case.note))
        codes = [issue.code for issue in validate_insight(insight)]
        assert insight.category.value == case.expected_category.value, case.case_id
        assert insight.sentiment.value == case.expected_sentiment.value, case.case_id
        assert codes == case.expected_issue_codes, case.case_id


def test_rubric_baseline_conformance_is_total() -> None:
    for case in load_rubric_cases():
        codes = [issue.code for issue in validate_insight(case.insight)]
        assert codes == case.expected_issue_codes, case.case_id


# --------------------------------------------------------------------------------------------
# Strict fixture-model invariant tests (pass)
# --------------------------------------------------------------------------------------------


def _valid_pipeline_case_payload() -> dict:
    return {
        "case_id": "Z-01",
        "note": {
            "id": "OPS-9001",
            "channel": "chat",
            "text": "A synthetic note used only to exercise the strict case model.",
            "created_at": "day_01_09",
        },
        "expected_category": "other",
        "expected_sentiment": "neutral",
        "expected_issue_codes": ["low_confidence"],
        "expected_review_required": True,
        "label_rationale": "Synthetic case exercising the strict pipeline-case model.",
        "tags": [],
    }


def test_pipeline_case_rejects_review_required_mismatch() -> None:
    payload = _valid_pipeline_case_payload()
    payload["expected_review_required"] = False
    with pytest.raises(ValidationError):
        PipelineCase.model_validate(payload)


def test_pipeline_case_rejects_note_id_equal_case_id() -> None:
    payload = _valid_pipeline_case_payload()
    payload["note"]["id"] = payload["case_id"]
    with pytest.raises(ValidationError):
        PipelineCase.model_validate(payload)


def test_pipeline_case_rejects_non_canonical_issue_order() -> None:
    payload = _valid_pipeline_case_payload()
    payload["expected_issue_codes"] = ["negative_without_action", "low_confidence"]
    payload["expected_review_required"] = True
    with pytest.raises(ValidationError):
        PipelineCase.model_validate(payload)


def test_pipeline_case_rejects_unknown_issue_code() -> None:
    payload = _valid_pipeline_case_payload()
    payload["expected_issue_codes"] = ["not_a_real_code"]
    with pytest.raises(ValidationError):
        PipelineCase.model_validate(payload)


def test_pipeline_case_rejects_duplicate_issue_codes() -> None:
    payload = _valid_pipeline_case_payload()
    payload["expected_issue_codes"] = ["low_confidence", "low_confidence"]
    with pytest.raises(ValidationError):
        PipelineCase.model_validate(payload)


def test_case_model_forbids_extra_fields() -> None:
    payload = _valid_pipeline_case_payload()
    payload["surprise"] = "nope"
    with pytest.raises(ValidationError):
        PipelineCase.model_validate(payload)


# --------------------------------------------------------------------------------------------
# Locked nested gates-schema tests (pass)
# --------------------------------------------------------------------------------------------


def _rate_gate(denominator: int, minimum_correct: int) -> dict:
    return {
        "denominator": denominator,
        "minimum_correct": minimum_correct,
        "min_rate": f"{minimum_correct / denominator:.4f}",
        "max_errors": denominator - minimum_correct,
        "rationale": "Deterministic conformance on unambiguous synthetic inputs.",
    }


def _max_count_gate(max_count: int) -> dict:
    return {
        "max_count": max_count,
        "rationale": "A single miss on this critical check is unacceptable.",
    }


def _valid_gates_payload() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "corpus_version": CORPUS_VERSION,
        "corpus": {"pipeline_sha256": "0" * 64, "rubric_sha256": "1" * 64},
        "pipeline": {
            "schema_valid": _rate_gate(12, 12),
            "category_conformance": _rate_gate(12, 12),
            "review_routing_conformance": _rate_gate(12, 12),
            "issue_exact_set_conformance": _rate_gate(12, 12),
        },
        "rubric": {
            "review_routing_conformance": _rate_gate(6, 6),
            "issue_exact_set_conformance": _rate_gate(6, 6),
            "critical_overconfidence_false_negatives": _max_count_gate(0),
        },
        "hard_invariants": {
            "deterministic_rerun_equality": {
                "required": True,
                "rationale": "Two isolated runs must produce byte-identical evidence.",
            },
            "generic_privacy_pattern_violations": _max_count_gate(0),
        },
    }


def test_nested_gates_file_accepts_valid_payload() -> None:
    gates = GatesFile.model_validate(_valid_gates_payload())
    assert gates.schema_version == 1
    assert gates.corpus_version == "v1"
    assert gates.pipeline.category_conformance.min_rate == "1.0000"
    assert gates.rubric.critical_overconfidence_false_negatives.max_count == 0
    assert gates.hard_invariants.generic_privacy_pattern_violations.max_count == 0


def test_gates_file_rejects_non_integer_schema_version() -> None:
    payload = _valid_gates_payload()
    payload["schema_version"] = "1.0"
    with pytest.raises(ValidationError):
        GatesFile.model_validate(payload)


def test_gates_file_rejects_non_v1_corpus_version() -> None:
    payload = _valid_gates_payload()
    payload["corpus_version"] = "0.2.0-eval-1"
    with pytest.raises(ValidationError):
        GatesFile.model_validate(payload)


def test_critical_overconfidence_gate_rejects_rate_gate_shape() -> None:
    """``rubric.critical_overconfidence_false_negatives`` must not be a RateGate."""
    payload = _valid_gates_payload()
    payload["rubric"]["critical_overconfidence_false_negatives"] = _rate_gate(2, 2)
    with pytest.raises(ValidationError):
        GatesFile.model_validate(payload)


def test_rate_gate_rejects_inconsistent_max_errors() -> None:
    payload = _rate_gate(12, 12)
    payload["max_errors"] = 3
    with pytest.raises(ValidationError):
        RateGate.model_validate(payload)


def test_rate_gate_rejects_wrong_rate_string() -> None:
    payload = _rate_gate(12, 10)
    payload["min_rate"] = "0.83"
    with pytest.raises(ValidationError):
        RateGate.model_validate(payload)


def test_rate_gate_keeps_four_decimal_rate_string() -> None:
    gate = RateGate.model_validate(_rate_gate(12, 10))
    assert gate.min_rate == "0.8333"


def test_gates_file_rejects_bad_sha256() -> None:
    payload = _valid_gates_payload()
    payload["corpus"]["pipeline_sha256"] = "not-a-hash"
    with pytest.raises(ValidationError):
        GatesFile.model_validate(payload)


def test_gates_file_forbids_extra_field() -> None:
    payload = _valid_gates_payload()
    payload["extra"] = "nope"
    with pytest.raises(ValidationError):
        GatesFile.model_validate(payload)


# --------------------------------------------------------------------------------------------
# Output-contract (Section 7.8/7.9) construction tests (pass)
# --------------------------------------------------------------------------------------------


def test_metric_value_supports_rate_and_gate_strings() -> None:
    passed = MetricValue(correct=12, total=12, errors=0, rate="1.0000", gate_passed=True)
    assert passed.rate == "1.0000"

    report_only = MetricValue(correct=12, total=12, errors=0, rate="1.0000", gate_passed=None)
    assert report_only.gate_passed is None

    empty = MetricValue(correct=0, total=0, errors=0, rate="not_applicable", gate_passed=None)
    assert empty.rate == "not_applicable"


def test_metric_value_forbids_name_minimum_rate_and_denominator() -> None:
    base = {"correct": 12, "total": 12, "errors": 0, "rate": "1.0000", "gate_passed": True}
    for banned_field in ("name", "minimum_rate", "denominator"):
        with pytest.raises(ValidationError):
            MetricValue.model_validate({**base, banned_field: "x"})


def _valid_output_payload() -> dict:
    metric = {"correct": 12, "total": 12, "errors": 0, "rate": "1.0000", "gate_passed": True}
    rubric_metric = {**metric, "correct": 6, "total": 6}
    return {
        "schema_version": SCHEMA_VERSION,
        "corpus_version": CORPUS_VERSION,
        "provider": PROVIDER_ID,
        "pipeline": {
            "case_count": 12,
            "metrics": {
                "schema_valid": metric,
                "category_conformance": metric,
                "sentiment_conformance": {**metric, "gate_passed": None},
                "review_routing_conformance": metric,
                "issue_exact_set_conformance": metric,
                "deterministic_rerun_equal": True,
            },
            "failure_count": 0,
            "failures": [],
        },
        "rubric": {
            "case_count": 6,
            "metrics": {
                "review_routing_conformance": rubric_metric,
                "issue_exact_set_conformance": rubric_metric,
                "micro_precision": {**rubric_metric, "gate_passed": None},
                "micro_recall": {**rubric_metric, "gate_passed": None},
                "micro_f1": {**rubric_metric, "gate_passed": None},
            },
            "per_code": [
                {
                    "code": code,
                    "support": 2,
                    "true_positives": 2,
                    "false_positives": 0,
                    "false_negatives": 0,
                }
                for code in CANONICAL_ISSUE_CODES
            ],
            "failure_count": 0,
            "failures": [],
        },
        "hard_invariants": {
            "critical_overconfidence_false_negatives": 0,
            "generic_privacy_pattern_violations": 0,
            "deterministic_rerun_equal": True,
        },
        "all_gates_passed": True,
        "limitations": list(MANDATORY_LIMITATIONS),
    }


def test_evaluation_output_round_trips() -> None:
    output = EvaluationOutput.model_validate(_valid_output_payload())
    assert output.schema_version == 1
    assert output.corpus_version == "v1"
    assert output.provider == "deterministic_rule_provider"
    assert output.all_gates_passed is True
    assert output.pipeline.metrics.sentiment_conformance.gate_passed is None
    assert output.limitations[0] == MANDATORY_LIMITATIONS[0]
    assert [entry.code for entry in output.rubric.per_code] == list(CANONICAL_ISSUE_CODES)


def test_evaluation_output_rejects_non_deterministic_rule_provider() -> None:
    payload = _valid_output_payload()
    payload["provider"] = "DeterministicRuleProvider"
    with pytest.raises(ValidationError):
        EvaluationOutput.model_validate(payload)


def test_evaluation_output_rejects_wrong_limitations_order() -> None:
    payload = _valid_output_payload()
    payload["limitations"] = list(reversed(MANDATORY_LIMITATIONS))
    with pytest.raises(ValidationError):
        EvaluationOutput.model_validate(payload)


def test_evaluation_output_rejects_missing_limitation() -> None:
    payload = _valid_output_payload()
    payload["limitations"] = list(MANDATORY_LIMITATIONS[:3])
    with pytest.raises(ValidationError):
        EvaluationOutput.model_validate(payload)


def test_pipeline_metrics_rejects_non_null_sentiment_gate() -> None:
    payload = _valid_output_payload()
    payload["pipeline"]["metrics"]["sentiment_conformance"]["gate_passed"] = True
    with pytest.raises(ValidationError):
        EvaluationOutput.model_validate(payload)


def test_rubric_report_rejects_non_canonical_per_code_order() -> None:
    payload = _valid_output_payload()
    payload["rubric"]["per_code"] = list(reversed(payload["rubric"]["per_code"]))
    with pytest.raises(ValidationError):
        EvaluationOutput.model_validate(payload)


def test_rubric_metrics_has_no_critical_overconfidence_field() -> None:
    payload = _valid_output_payload()
    payload["rubric"]["metrics"]["critical_overconfidence_false_negatives"] = payload["rubric"][
        "metrics"
    ]["micro_f1"]
    with pytest.raises(ValidationError):
        EvaluationOutput.model_validate(payload)


def test_failure_row_accepts_bounded_shape() -> None:
    row = FailureRow(
        case_id="A-01",
        failure_kind="category",
        expected="data_quality",
        observed="bug",
        missing_issue_codes=[],
        unexpected_issue_codes=[],
        explanation="Category mismatch on an unambiguous synthetic note.",
    )
    assert row.failure_kind == "category"


def test_failure_row_rejects_unknown_failure_kind() -> None:
    with pytest.raises(ValidationError):
        FailureRow(
            case_id="A-01",
            failure_kind="not_a_real_kind",
            expected="x",
            observed="y",
            missing_issue_codes=[],
            unexpected_issue_codes=[],
            explanation="x",
        )


def test_failure_row_forbids_check_field() -> None:
    """The prior, looser ``check: str`` field must not survive onto FailureRow."""
    with pytest.raises(ValidationError):
        FailureRow.model_validate(
            {
                "case_id": "A-01",
                "failure_kind": "category",
                "check": "category",
                "expected": "x",
                "observed": "y",
                "missing_issue_codes": [],
                "unexpected_issue_codes": [],
                "explanation": "x",
            }
        )


# --------------------------------------------------------------------------------------------
# MetricValue self-consistency (pass) — correct+errors==total, zero-total shape, ROUND_HALF_UP
# --------------------------------------------------------------------------------------------


def _metric(correct: int, total: int, errors: int, rate: str, gate_passed: bool | None) -> dict:
    return {
        "correct": correct,
        "total": total,
        "errors": errors,
        "rate": rate,
        "gate_passed": gate_passed,
    }


def test_metric_value_rejects_correct_plus_errors_not_equal_total() -> None:
    with pytest.raises(ValidationError):
        MetricValue.model_validate(_metric(10, 12, 1, "0.8333", True))


def test_metric_value_rejects_nonzero_counts_at_zero_total() -> None:
    with pytest.raises(ValidationError):
        MetricValue.model_validate(_metric(1, 0, 0, "not_applicable", None))
    with pytest.raises(ValidationError):
        MetricValue.model_validate(_metric(0, 0, 1, "not_applicable", None))


def test_metric_value_rejects_wrong_rate_at_zero_total() -> None:
    with pytest.raises(ValidationError):
        MetricValue.model_validate(_metric(0, 0, 0, "0.0000", None))


def test_metric_value_rejects_not_applicable_at_nonzero_total() -> None:
    with pytest.raises(ValidationError):
        MetricValue.model_validate(_metric(12, 12, 0, "not_applicable", True))


def test_metric_value_rejects_malformed_rate_string() -> None:
    for bad_rate in ("0.83", "1.00000", "abc", "83%", "1.0"):
        with pytest.raises(ValidationError):
            MetricValue.model_validate(_metric(10, 12, 2, bad_rate, True))


def test_metric_value_rejects_wrong_rate_value() -> None:
    with pytest.raises(ValidationError):
        MetricValue.model_validate(_metric(10, 12, 2, "0.9999", True))


def test_metric_value_uses_round_half_up_not_banker_rounding() -> None:
    """1/32 == 0.03125, an exact tie at the 4th decimal. ROUND_HALF_UP rounds away from zero to
    0.0313; Python's default banker's rounding (ROUND_HALF_EVEN) would instead give 0.0312."""
    accepted = MetricValue.model_validate(_metric(1, 32, 31, "0.0313", True))
    assert accepted.rate == "0.0313"
    with pytest.raises(ValidationError):
        MetricValue.model_validate(_metric(1, 32, 31, "0.0312", True))


# --------------------------------------------------------------------------------------------
# PipelineMetrics / RubricMetrics gate_passed shape (pass)
# --------------------------------------------------------------------------------------------


def test_pipeline_metrics_rejects_null_gate_passed_on_gated_metrics() -> None:
    for field_name in (
        "schema_valid",
        "category_conformance",
        "review_routing_conformance",
        "issue_exact_set_conformance",
    ):
        payload = _valid_output_payload()
        metrics = payload["pipeline"]["metrics"]
        metrics[field_name] = {**metrics[field_name], "gate_passed": None}
        with pytest.raises(ValidationError):
            EvaluationOutput.model_validate(payload)


def test_rubric_metrics_rejects_null_gate_passed_on_gated_metrics() -> None:
    for field_name in ("review_routing_conformance", "issue_exact_set_conformance"):
        payload = _valid_output_payload()
        metrics = payload["rubric"]["metrics"]
        metrics[field_name] = {**metrics[field_name], "gate_passed": None}
        with pytest.raises(ValidationError):
            EvaluationOutput.model_validate(payload)


def test_rubric_metrics_rejects_non_null_gate_passed_on_micro_averages() -> None:
    for field_name in ("micro_precision", "micro_recall", "micro_f1"):
        payload = _valid_output_payload()
        metrics = payload["rubric"]["metrics"]
        metrics[field_name] = {**metrics[field_name], "gate_passed": True}
        with pytest.raises(ValidationError):
            EvaluationOutput.model_validate(payload)


# --------------------------------------------------------------------------------------------
# PerCodeConfusion / per_code completeness (pass)
# --------------------------------------------------------------------------------------------


def test_per_code_confusion_rejects_support_mismatch() -> None:
    with pytest.raises(ValidationError):
        PerCodeConfusion.model_validate(
            {
                "code": "low_confidence",
                "support": 3,
                "true_positives": 2,
                "false_positives": 0,
                "false_negatives": 0,
            }
        )


def test_rubric_report_rejects_incomplete_per_code() -> None:
    payload = _valid_output_payload()
    payload["rubric"]["per_code"] = payload["rubric"]["per_code"][:2]
    with pytest.raises(ValidationError):
        EvaluationOutput.model_validate(payload)


def test_rubric_report_rejects_empty_per_code() -> None:
    payload = _valid_output_payload()
    payload["rubric"]["per_code"] = []
    with pytest.raises(ValidationError):
        EvaluationOutput.model_validate(payload)


# --------------------------------------------------------------------------------------------
# Bounded failures (pass) — max_length=MAX_FAILURE_ROWS, and never more rows than failure_count
# --------------------------------------------------------------------------------------------


def _failure_row(case_id: str = "A-01") -> dict:
    return {
        "case_id": case_id,
        "failure_kind": "category",
        "expected": "data_quality",
        "observed": "bug",
        "missing_issue_codes": [],
        "unexpected_issue_codes": [],
        "explanation": "Category mismatch on an unambiguous synthetic note.",
    }


def test_pipeline_report_failures_enforces_max_length() -> None:
    payload = _valid_output_payload()
    payload["pipeline"]["failure_count"] = MAX_FAILURE_ROWS + 1
    payload["pipeline"]["failures"] = [_failure_row() for _ in range(MAX_FAILURE_ROWS + 1)]
    with pytest.raises(ValidationError):
        EvaluationOutput.model_validate(payload)


def test_pipeline_report_rejects_failures_exceeding_failure_count() -> None:
    payload = _valid_output_payload()
    payload["pipeline"]["failure_count"] = 0
    payload["pipeline"]["failures"] = [_failure_row()]
    with pytest.raises(ValidationError):
        EvaluationOutput.model_validate(payload)


def test_rubric_report_failures_enforces_max_length() -> None:
    payload = _valid_output_payload()
    payload["rubric"]["failure_count"] = MAX_FAILURE_ROWS + 1
    payload["rubric"]["failures"] = [_failure_row("B-01") for _ in range(MAX_FAILURE_ROWS + 1)]
    with pytest.raises(ValidationError):
        EvaluationOutput.model_validate(payload)


def test_rubric_report_rejects_failures_exceeding_failure_count() -> None:
    payload = _valid_output_payload()
    payload["rubric"]["failure_count"] = 0
    payload["rubric"]["failures"] = [_failure_row("B-01")]
    with pytest.raises(ValidationError):
        EvaluationOutput.model_validate(payload)


# --------------------------------------------------------------------------------------------
# FailureRow issue-code list invariants (pass)
# --------------------------------------------------------------------------------------------


def test_failure_row_rejects_unknown_code_in_missing_issue_codes() -> None:
    with pytest.raises(ValidationError):
        FailureRow.model_validate({**_failure_row(), "missing_issue_codes": ["not_a_real_code"]})


def test_failure_row_rejects_duplicate_code_in_unexpected_issue_codes() -> None:
    with pytest.raises(ValidationError):
        FailureRow.model_validate(
            {**_failure_row(), "unexpected_issue_codes": ["low_confidence", "low_confidence"]}
        )


def test_failure_row_rejects_noncanonical_order_in_missing_issue_codes() -> None:
    with pytest.raises(ValidationError):
        FailureRow.model_validate(
            {
                **_failure_row(),
                "missing_issue_codes": ["negative_without_action", "low_confidence"],
            }
        )


# --------------------------------------------------------------------------------------------
# BooleanInvariant.required is pinned Literal[True] (pass)
# --------------------------------------------------------------------------------------------


def test_boolean_invariant_rejects_required_false() -> None:
    payload = _valid_gates_payload()
    payload["hard_invariants"]["deterministic_rerun_equality"]["required"] = False
    with pytest.raises(ValidationError):
        GatesFile.model_validate(payload)


# --------------------------------------------------------------------------------------------
# Phase 2 invariant (pass) — gates.json now exists and matches the owner-approved values
# --------------------------------------------------------------------------------------------


def test_gates_json_matches_approved_values() -> None:
    gates = load_gates(EVALS_DIR / "gates.json")
    assert gates.schema_version == 1
    assert gates.corpus_version == "v1"
    assert (
        gates.corpus.pipeline_sha256
        == "bed0243bf42705fd45e3d07cb53812ac37b91bfbd1867990ac9593abbf33158b"
    )
    assert (
        gates.corpus.rubric_sha256
        == "331e40592f15e1fcb656aa7a4171dbfee8cd889c56d3b7f4c6ce32d5954425fa"
    )
    for gate in (
        gates.pipeline.schema_valid,
        gates.pipeline.category_conformance,
        gates.pipeline.review_routing_conformance,
        gates.pipeline.issue_exact_set_conformance,
    ):
        assert gate.denominator == 12
        assert gate.minimum_correct == 12
        assert gate.min_rate == "1.0000"
        assert gate.max_errors == 0
    for gate in (gates.rubric.review_routing_conformance, gates.rubric.issue_exact_set_conformance):
        assert gate.denominator == 6
        assert gate.minimum_correct == 6
        assert gate.min_rate == "1.0000"
        assert gate.max_errors == 0
    assert gates.rubric.critical_overconfidence_false_negatives.max_count == 0
    assert gates.hard_invariants.deterministic_rerun_equality.required is True
    assert gates.hard_invariants.generic_privacy_pattern_violations.max_count == 0


# --------------------------------------------------------------------------------------------
# Phase 2 evaluator (pass) — behavioral tests, converted from strict-xfail RED boundary now
# that the owner-approved evaluator, rendering, and privacy scanner are implemented
# --------------------------------------------------------------------------------------------


def test_phase2_metric_perfect() -> None:
    from ai_workflow_builder.evaluation import conformance_metric

    metric = conformance_metric("category_conformance", correct=12, denominator=12)
    assert metric.rate == "1.0000"
    assert metric.errors == 0


def test_phase2_metric_partial() -> None:
    from ai_workflow_builder.evaluation import conformance_metric

    metric = conformance_metric("category_conformance", correct=10, denominator=12)
    assert metric.rate == "0.8333"
    assert metric.errors == 2


def test_phase2_metric_zero_denominator() -> None:
    from ai_workflow_builder.evaluation import conformance_metric

    metric = conformance_metric("empty", correct=0, denominator=0)
    assert metric.rate == "not_applicable"


def _gate(denominator: int, minimum_correct: int) -> RateGate:
    return RateGate.model_validate(_rate_gate(denominator, minimum_correct))


def test_conformance_metric_rejects_denominator_mismatch() -> None:
    """The actual denominator must equal the gate's declared denominator; never inferred from
    a fixture-hash match alone."""
    from ai_workflow_builder.evaluation import conformance_metric

    gate = _gate(denominator=12, minimum_correct=12)
    with pytest.raises(CorpusError, match="does not match the approved gate"):
        conformance_metric("schema_valid", correct=11, denominator=11, gate=gate)


def test_conformance_metric_requires_minimum_correct_and_max_errors() -> None:
    from ai_workflow_builder.evaluation import conformance_metric

    gate = _gate(denominator=10, minimum_correct=8)  # max_errors=2, min_rate="0.8000"
    failing = conformance_metric("m", correct=7, denominator=10, gate=gate)
    assert failing.gate_passed is False  # 7 < minimum_correct=8 and errors=3 > max_errors=2

    passing = conformance_metric("m", correct=8, denominator=10, gate=gate)
    assert passing.gate_passed is True


def test_conformance_metric_min_rate_can_fail_independently_of_minimum_correct() -> None:
    """``min_rate`` is a ROUND_HALF_UP-style *rounded* rendering of ``minimum_correct /
    denominator`` (via RateGate's own ``:.4f`` formatting), not always exactly equal to the
    true fraction. 4/6 = 0.6666... repeating, so min_rate is rounded up to "0.6667" -- a case
    with correct==minimum_correct==4 (satisfying both the minimum_correct and max_errors
    conditions exactly) still has an *exact* ratio of 0.6666... < Decimal("0.6667"), so the
    min_rate condition alone must fail the gate. This proves min_rate is checked as a genuinely
    independent condition, not merely implied by minimum_correct."""
    from ai_workflow_builder.evaluation import conformance_metric

    gate = _gate(denominator=6, minimum_correct=4)
    assert gate.min_rate == "0.6667"

    metric = conformance_metric("m", correct=4, denominator=6, gate=gate)
    assert metric.correct >= gate.minimum_correct
    assert metric.errors <= gate.max_errors
    assert metric.gate_passed is False, "min_rate must independently fail this exact-fraction case"


def test_conformance_metric_gate_passed_true_only_when_all_conditions_hold() -> None:
    from ai_workflow_builder.evaluation import conformance_metric

    gate = _gate(denominator=12, minimum_correct=12)
    assert conformance_metric("m", correct=12, denominator=12, gate=gate).gate_passed is True
    assert conformance_metric("m", correct=11, denominator=12, gate=gate).gate_passed is False


def test_evaluate_rejects_pipeline_gate_denominator_mismatch(tmp_path) -> None:
    """A gates.json that is internally self-consistent but declares the wrong denominator for
    the (hash-verified, otherwise approved) corpus must still be rejected."""
    from ai_workflow_builder.evaluation import evaluate

    gates_payload = json.loads((EVALS_DIR / "gates.json").read_text(encoding="utf-8"))
    gates_payload["pipeline"]["schema_valid"] = _rate_gate(11, 11)
    temp_gates = tmp_path / "gates.json"
    temp_gates.write_text(json.dumps(gates_payload), encoding="utf-8")

    with pytest.raises(CorpusError, match="does not match the approved gate"):
        evaluate(PIPELINE_PATH, RUBRIC_PATH, temp_gates)


def test_evaluate_rejects_rubric_gate_denominator_mismatch(tmp_path) -> None:
    from ai_workflow_builder.evaluation import evaluate

    gates_payload = json.loads((EVALS_DIR / "gates.json").read_text(encoding="utf-8"))
    gates_payload["rubric"]["review_routing_conformance"] = _rate_gate(5, 5)
    temp_gates = tmp_path / "gates.json"
    temp_gates.write_text(json.dumps(gates_payload), encoding="utf-8")

    with pytest.raises(CorpusError, match="does not match the approved gate"):
        evaluate(PIPELINE_PATH, RUBRIC_PATH, temp_gates)


def test_phase2_metric_schema_invalid_counts_as_error(monkeypatch) -> None:
    """A schema-invalid provider prediction stays in the denominator as an incorrect case."""
    from ai_workflow_builder.evaluation import evaluate

    original_extract = DeterministicRuleProvider.extract_insight

    def _corrupt_one_note(self, note):
        payload = original_extract(self, note)
        if note.id == "OPS-3001":
            payload = {**payload, "category": "not_a_real_category"}  # violates OpsInsight
        return payload

    monkeypatch.setattr(DeterministicRuleProvider, "extract_insight", _corrupt_one_note)

    output = evaluate(PIPELINE_PATH, RUBRIC_PATH)
    schema_valid = output.pipeline.metrics.schema_valid
    assert schema_valid.total == 12, "a schema-invalid prediction must not shrink the denominator"
    assert schema_valid.errors == 1
    assert schema_valid.correct == 11


def test_evaluate_rejects_pipeline_corpus_with_different_bytes(tmp_path) -> None:
    """A fixture with different bytes has a different SHA-256, and must be rejected outright,
    never silently evaluated against the approved gates."""
    from ai_workflow_builder.evaluation import evaluate

    cases = json.loads(PIPELINE_PATH.read_text(encoding="utf-8"))
    cases[0]["label_rationale"] += " (tampered)"
    tampered = tmp_path / "pipeline_cases.json"
    tampered.write_text(json.dumps(cases), encoding="utf-8")

    with pytest.raises(CorpusError, match="does not match the approved gates.json"):
        evaluate(tampered, RUBRIC_PATH)


def test_evaluate_rejects_shorter_corpus_instead_of_reporting_all_gates_passed(tmp_path) -> None:
    """An 11-case corpus (one case dropped) must be rejected via the hash check, never silently
    scored as a conformant 11/11 pass."""
    from ai_workflow_builder.evaluation import evaluate

    cases = json.loads(PIPELINE_PATH.read_text(encoding="utf-8"))
    assert len(cases) == 12
    shortened = tmp_path / "pipeline_cases.json"
    shortened.write_text(json.dumps(cases[:-1]), encoding="utf-8")

    with pytest.raises(CorpusError, match="does not match the approved gates.json"):
        evaluate(shortened, RUBRIC_PATH)


def test_evaluate_rejects_rubric_hash_mismatch(tmp_path) -> None:
    from ai_workflow_builder.evaluation import evaluate

    cases = json.loads(RUBRIC_PATH.read_text(encoding="utf-8"))
    cases[0]["label_rationale"] += " (tampered)"
    tampered = tmp_path / "rubric_cases.json"
    tampered.write_text(json.dumps(cases), encoding="utf-8")

    with pytest.raises(CorpusError, match="does not match the approved gates.json"):
        evaluate(PIPELINE_PATH, tampered)


def test_evaluate_detects_nondeterministic_provider(monkeypatch) -> None:
    """``deterministic_rerun_equal`` is a measured comparison of two independent passes, not a
    hardcoded constant: a provider that behaves differently on its second call must flip it to
    false and fail the corresponding hard invariant / overall gate."""
    from ai_workflow_builder.evaluation import evaluate

    original_extract = DeterministicRuleProvider.extract_insight
    call_counts: dict[str, int] = {}

    def _flaky_on_second_call(self, note):
        call_counts[note.id] = call_counts.get(note.id, 0) + 1
        payload = original_extract(self, note)
        if note.id == "OPS-3001" and call_counts[note.id] == 2:
            payload = {**payload, "category": "bug"}
        return payload

    monkeypatch.setattr(DeterministicRuleProvider, "extract_insight", _flaky_on_second_call)

    output = evaluate(PIPELINE_PATH, RUBRIC_PATH)
    assert output.pipeline.metrics.deterministic_rerun_equal is False
    assert output.hard_invariants.deterministic_rerun_equal is False
    assert output.all_gates_passed is False


def test_privacy_scan_would_catch_a_pattern_in_rendered_output() -> None:
    """The scanner, applied to fully rendered Markdown/JSON, catches a privacy pattern that
    only appears inside a rendered field (here, a failure explanation) -- proving the rendered
    text itself is a valid scan target, not only the raw source fixtures."""
    from ai_workflow_builder.evaluation import render_json, render_markdown, scan_privacy_violations

    payload = _valid_output_payload()
    poison = "contact scanner-poison" + chr(64) + "example.invalid for details"
    payload["pipeline"]["failure_count"] = 1
    payload["pipeline"]["failures"] = [
        {
            "case_id": "A-01",
            "failure_kind": "category",
            "expected": "data_quality",
            "observed": "bug",
            "missing_issue_codes": [],
            "unexpected_issue_codes": [],
            "explanation": poison,
        }
    ]
    output = EvaluationOutput.model_validate(payload)
    rendered = render_markdown(output) + render_json(output)

    assert poison not in (
        PIPELINE_PATH.read_text(encoding="utf-8") + RUBRIC_PATH.read_text(encoding="utf-8")
    )
    assert scan_privacy_violations(rendered) > 0


def test_phase2_confusion_false_positive() -> None:
    from ai_workflow_builder.evaluation import confusion_for_code

    confusion = confusion_for_code(
        "low_confidence", expected=[set()], observed=[{"low_confidence"}]
    )
    assert confusion.false_positives == 1
    assert confusion.false_negatives == 0


def test_phase2_confusion_false_negative() -> None:
    from ai_workflow_builder.evaluation import confusion_for_code

    confusion = confusion_for_code(
        "overconfident_summary",
        expected=[{"overconfident_summary"}],
        observed=[set()],
    )
    assert confusion.false_negatives == 1


def test_phase2_confusion_multi_issue() -> None:
    from ai_workflow_builder.evaluation import confusion_for_code

    confusion = confusion_for_code(
        "low_confidence",
        expected=[{"low_confidence", "negative_without_action"}],
        observed=[{"low_confidence", "negative_without_action"}],
    )
    assert confusion.true_positives == 1


def test_phase2_confusion_zero_denominator() -> None:
    from ai_workflow_builder.evaluation import confusion_for_code

    confusion = confusion_for_code("low_confidence", expected=[], observed=[])
    assert confusion.true_positives == 0
    assert confusion.false_positives == 0
    assert confusion.false_negatives == 0


def test_phase2_json_schema_exact_nested_keys() -> None:
    from ai_workflow_builder.evaluation import evaluate, render_json

    output = evaluate(PIPELINE_PATH, RUBRIC_PATH)
    data = json.loads(render_json(output))
    assert list(data.keys()) == [
        "schema_version",
        "corpus_version",
        "provider",
        "pipeline",
        "rubric",
        "hard_invariants",
        "all_gates_passed",
        "limitations",
    ]
    assert data["schema_version"] == 1
    assert data["corpus_version"] == "v1"
    assert data["provider"] == "deterministic_rule_provider"
    assert list(data["pipeline"].keys()) == ["case_count", "metrics", "failure_count", "failures"]
    assert list(data["pipeline"]["metrics"].keys()) == [
        "schema_valid",
        "category_conformance",
        "sentiment_conformance",
        "review_routing_conformance",
        "issue_exact_set_conformance",
        "deterministic_rerun_equal",
    ]
    assert list(data["rubric"].keys()) == [
        "case_count",
        "metrics",
        "per_code",
        "failure_count",
        "failures",
    ]
    assert list(data["rubric"]["metrics"].keys()) == [
        "review_routing_conformance",
        "issue_exact_set_conformance",
        "micro_precision",
        "micro_recall",
        "micro_f1",
    ]
    assert [entry["code"] for entry in data["rubric"]["per_code"]] == list(CANONICAL_ISSUE_CODES)
    assert list(data["hard_invariants"].keys()) == [
        "critical_overconfidence_false_negatives",
        "generic_privacy_pattern_violations",
        "deterministic_rerun_equal",
    ]
    assert data["limitations"] == list(MANDATORY_LIMITATIONS)


# The 10 required Markdown blocks, in fixed sequence. Block 2 (the "deterministic
# authored-synthetic conformance disclaimer") reuses MANDATORY_LIMITATIONS[0] verbatim rather
# than inventing separate wording — that limitation *is* the disclaimer.
_MD_TITLE = "# Public Kernel Evaluation"
_MD_OVERALL = "## Overall"
_MD_PIPELINE_METRICS = "## Suite A — Pipeline Metrics"
_MD_PIPELINE_FAILURES = "## Suite A — Pipeline Failures"
_MD_RUBRIC_METRICS = "## Suite B — Validator Rubric Metrics"
_MD_RUBRIC_PER_CODE = "## Suite B — Per-Code Confusion"
_MD_RUBRIC_FAILURES = "## Suite B — Rubric Failures"
_MD_HARD_INVARIANTS = "## Hard Invariants"
_MD_LIMITATIONS = "## Limitations"
_MD_NO_MISMATCHES = "No observed mismatches."


def test_phase2_markdown_section_order() -> None:
    """The 10 required blocks, in exact sequence: title; disclaimer; overall status (corpus
    version + case counts); pipeline metrics; pipeline failures; rubric metrics; per-code
    confusion; rubric failures; hard invariants; limitations."""
    from ai_workflow_builder.evaluation import evaluate, render_markdown

    markdown = render_markdown(evaluate(PIPELINE_PATH, RUBRIC_PATH))

    title_at = markdown.index(_MD_TITLE)
    disclaimer_at = markdown.index(MANDATORY_LIMITATIONS[0])
    overall_at = markdown.index(_MD_OVERALL)
    pipeline_metrics_at = markdown.index(_MD_PIPELINE_METRICS)
    pipeline_failures_at = markdown.index(_MD_PIPELINE_FAILURES)
    rubric_metrics_at = markdown.index(_MD_RUBRIC_METRICS)
    rubric_per_code_at = markdown.index(_MD_RUBRIC_PER_CODE)
    rubric_failures_at = markdown.index(_MD_RUBRIC_FAILURES)
    hard_invariants_at = markdown.index(_MD_HARD_INVARIANTS)
    limitations_at = markdown.index(_MD_LIMITATIONS)

    assert (
        title_at
        < disclaimer_at
        < overall_at
        < pipeline_metrics_at
        < pipeline_failures_at
        < rubric_metrics_at
        < rubric_per_code_at
        < rubric_failures_at
        < hard_invariants_at
        < limitations_at
    )

    overall_block = markdown[overall_at:pipeline_metrics_at]
    assert CORPUS_VERSION in overall_block
    assert "12" in overall_block  # Suite A case count
    assert "6" in overall_block  # Suite B case count


def test_phase2_zero_failure_sections_render_no_mismatches() -> None:
    from ai_workflow_builder.evaluation import evaluate, render_markdown

    markdown = render_markdown(evaluate(PIPELINE_PATH, RUBRIC_PATH))
    pipeline_block = markdown[
        markdown.index(_MD_PIPELINE_FAILURES) : markdown.index(_MD_RUBRIC_METRICS)
    ]
    rubric_block = markdown[
        markdown.index(_MD_RUBRIC_FAILURES) : markdown.index(_MD_HARD_INVARIANTS)
    ]

    assert "0 of 12" in pipeline_block
    assert _MD_NO_MISMATCHES in pipeline_block
    assert "0 of 6" in rubric_block
    assert _MD_NO_MISMATCHES in rubric_block


def test_phase2_nonzero_failure_section_rendered(tmp_path) -> None:
    import hashlib

    from ai_workflow_builder.evaluation import evaluate, render_markdown

    # Perturb one golden label in an isolated temp copy; tracked fixtures stay untouched.
    cases = json.loads(PIPELINE_PATH.read_text(encoding="utf-8"))
    assert cases[0]["case_id"] == "A-01"
    cases[0]["expected_category"] = "bug"  # provider yields data_quality -> one failure
    perturbed = tmp_path / "pipeline_cases.json"
    perturbed_bytes = json.dumps(cases).encode("utf-8")
    perturbed.write_bytes(perturbed_bytes)

    # evaluate() verifies the corpus against the approved gates.json fixture hash; a perturbed
    # corpus needs its own self-consistent gates file (matching hash), never the real one.
    gates_payload = json.loads((EVALS_DIR / "gates.json").read_text(encoding="utf-8"))
    gates_payload["corpus"]["pipeline_sha256"] = hashlib.sha256(perturbed_bytes).hexdigest()
    temp_gates = tmp_path / "gates.json"
    temp_gates.write_text(json.dumps(gates_payload), encoding="utf-8")

    markdown = render_markdown(evaluate(perturbed, RUBRIC_PATH, temp_gates))
    pipeline_block = markdown[
        markdown.index(_MD_PIPELINE_FAILURES) : markdown.index(_MD_RUBRIC_METRICS)
    ]

    assert "1 of 12" in pipeline_block
    assert "A-01" in pipeline_block
    assert _MD_NO_MISMATCHES not in pipeline_block


def test_phase2_two_run_bytes_identical() -> None:
    from ai_workflow_builder.evaluation import evaluate, render_json

    first = render_json(evaluate(PIPELINE_PATH, RUBRIC_PATH))
    second = render_json(evaluate(PIPELINE_PATH, RUBRIC_PATH))
    assert first == second


def test_phase2_privacy_poison_self_test() -> None:
    from ai_workflow_builder.evaluation import scan_privacy_violations

    # Assembled at runtime so this guard file does not itself trip the generic privacy scan.
    poison = "scanner-poison" + chr(64) + "example.invalid"
    assert scan_privacy_violations(poison) > 0
