"""Strict evaluation contracts and Phase 2 evaluator for the v0.2 evaluation evidence.

This module holds the strict fixture models, corpus-level structural validation, the locked
nested gates schema, the Section 7.8/7.9 output contract, and (Phase 2, owner-approved) the pure
evaluator, deterministic Markdown/JSON rendering, and the generic privacy scanner. Metric
functions (``conformance_metric``, ``confusion_for_code``, ``scan_privacy_violations``) are pure
and perform no file I/O; ``evaluate`` is the sole function that reads the corpus and gates files.
"""

from __future__ import annotations

import hashlib
import json
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Literal, NamedTuple, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from ai_workflow_builder.providers import DeterministicRuleProvider
from ai_workflow_builder.schemas import InsightCategory, OpsInsight, OpsNote, Sentiment
from ai_workflow_builder.validators import validate_insight

# Canonical validator issue codes, in the exact order that
# ``ai_workflow_builder.validators.validate_insight`` emits them. Every ``expected_issue_codes``
# list must be a subset in this order.
CANONICAL_ISSUE_CODES: tuple[str, ...] = (
    "low_confidence",
    "negative_without_action",
    "overconfident_summary",
)

# The single validator code whose false negatives are treated as critical.
CRITICAL_OVERCONFIDENCE_CODE = "overconfident_summary"

SUITE_A_PREFIX = "A-"
SUITE_B_PREFIX = "B-"

# Locked literal values for the gates/output schema shape defined in this module.
SCHEMA_VERSION: Literal[1] = 1
CORPUS_VERSION: Literal["v1"] = "v1"
PROVIDER_ID: Literal["deterministic_rule_provider"] = "deterministic_rule_provider"

# Proposed upper bound on rendered failure rows; the true total is always reported separately.
MAX_FAILURE_ROWS = 20

# Sentinel rate string used when a denominator is zero.
RATE_NOT_APPLICABLE = "not_applicable"

# The exact four mandatory limitations, in fixed order, required on every EvaluationOutput.
MANDATORY_LIMITATIONS: tuple[str, ...] = (
    "Pipeline metrics measure a deterministic rule provider against authored synthetic "
    "expectations, not a learned model or generalization.",
    "The corpus is intentionally small and public-safe; rates are accompanied by absolute counts.",
    "Overconfidence is exercised at the validator boundary because the current rule provider "
    "cannot emit that behavior.",
    "The case study does not establish production, live-user, deployment, or domain-specific "
    "quality.",
)


def _validate_issue_codes(case_id: str, codes: list[str]) -> None:
    """Reject unknown codes, duplicates, and non-canonical ordering."""
    for code in codes:
        if code not in CANONICAL_ISSUE_CODES:
            raise ValueError(f"{case_id}: unknown issue code {code!r}")
    if len(set(codes)) != len(codes):
        raise ValueError(f"{case_id}: duplicate issue codes {codes}")
    order = [CANONICAL_ISSUE_CODES.index(code) for code in codes]
    if order != sorted(order):
        raise ValueError(f"{case_id}: issue codes are not in canonical order {codes}")


_RATE_PATTERN = re.compile(r"^\d\.\d{4}$")


def _format_rate_half_up(numerator: int, denominator: int) -> str:
    """Render ``numerator / denominator`` as a four-decimal string, ties rounded away from zero
    (``ROUND_HALF_UP``), not Python's default banker's rounding."""
    quantized = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    return str(quantized)


# ============================================================================================
# Fixture models (Suite A and Suite B cases)
# ============================================================================================


class PipelineCase(BaseModel):
    """Suite A: one synthetic ``OpsNote`` and its independently labelled golden outcome.

    Suite A measures deterministic *pipeline conformance*: whether the untouched provider and
    validators reproduce the expected category, sentiment, and validator issue set.
    """

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=3)
    note: OpsNote
    expected_category: InsightCategory
    expected_sentiment: Sentiment
    expected_issue_codes: list[str] = Field(default_factory=list)
    expected_review_required: bool
    label_rationale: str = Field(min_length=10)
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_case(self) -> Self:
        _validate_issue_codes(self.case_id, self.expected_issue_codes)
        if self.expected_review_required != bool(self.expected_issue_codes):
            raise ValueError(
                f"{self.case_id}: expected_review_required must equal bool(expected_issue_codes)"
            )
        if self.note.id == self.case_id:
            raise ValueError(f"{self.case_id}: note id must be distinct from case_id")
        return self


class RubricCase(BaseModel):
    """Suite B: one synthetic ``OpsInsight`` and its golden validator issue set.

    Suite B measures *validator-rubric behavior* directly on insight fixtures, independent of
    any provider. It is reported separately from Suite A and never blended into a single score.
    """

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=3)
    insight: OpsInsight
    expected_issue_codes: list[str] = Field(default_factory=list)
    expected_review_required: bool
    label_rationale: str = Field(min_length=10)
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_case(self) -> Self:
        _validate_issue_codes(self.case_id, self.expected_issue_codes)
        if self.expected_review_required != bool(self.expected_issue_codes):
            raise ValueError(
                f"{self.case_id}: expected_review_required must equal bool(expected_issue_codes)"
            )
        if self.insight.note_id == self.case_id:
            raise ValueError(f"{self.case_id}: insight note_id must be distinct from case_id")
        return self


PipelineCasesAdapter: TypeAdapter[list[PipelineCase]] = TypeAdapter(list[PipelineCase])
RubricCasesAdapter: TypeAdapter[list[RubricCase]] = TypeAdapter(list[RubricCase])


# ============================================================================================
# Corpus-level structural validation (rejection, not repair)
# ============================================================================================


class CorpusError(ValueError):
    """Raised when a fixture corpus violates a structural invariant."""


def _check_suite(case_ids: list[str], prefix: str, suite: str) -> None:
    if case_ids != sorted(case_ids):
        raise CorpusError(f"{suite}: case_ids are not in canonical ascending order: {case_ids}")
    if len(set(case_ids)) != len(case_ids):
        raise CorpusError(f"{suite}: duplicate case_ids: {case_ids}")
    for case_id in case_ids:
        if not case_id.startswith(prefix):
            raise CorpusError(f"{suite}: case_id {case_id!r} missing suite prefix {prefix!r}")


def validate_pipeline_corpus(cases: list[PipelineCase]) -> None:
    """Reject a malformed Suite A corpus (order, prefix, or duplicate note ids)."""
    _check_suite([case.case_id for case in cases], SUITE_A_PREFIX, "pipeline")
    note_ids = [case.note.id for case in cases]
    if len(set(note_ids)) != len(note_ids):
        raise CorpusError(f"pipeline: duplicate note ids: {note_ids}")


def validate_rubric_corpus(cases: list[RubricCase]) -> None:
    """Reject a malformed Suite B corpus (order, prefix, or duplicate note ids)."""
    _check_suite([case.case_id for case in cases], SUITE_B_PREFIX, "rubric")
    note_ids = [case.insight.note_id for case in cases]
    if len(set(note_ids)) != len(note_ids):
        raise CorpusError(f"rubric: duplicate note ids: {note_ids}")


def validate_cross_suite(pipeline: list[PipelineCase], rubric: list[RubricCase]) -> None:
    """Reject overlap of case ids or note ids across the two suites."""
    case_ids = [case.case_id for case in pipeline] + [case.case_id for case in rubric]
    if len(set(case_ids)) != len(case_ids):
        raise CorpusError("cross-suite: case_id is reused across suites")
    note_ids = [case.note.id for case in pipeline] + [case.insight.note_id for case in rubric]
    if len(set(note_ids)) != len(note_ids):
        raise CorpusError("cross-suite: note id is reused across suites")


def load_corpus(
    pipeline_path: Path,
    rubric_path: Path,
) -> tuple[list[PipelineCase], list[RubricCase]]:
    """Load and fully validate both fixture files; raise on any structural violation."""
    pipeline = PipelineCasesAdapter.validate_python(
        json.loads(Path(pipeline_path).read_text(encoding="utf-8"))
    )
    rubric = RubricCasesAdapter.validate_python(
        json.loads(Path(rubric_path).read_text(encoding="utf-8"))
    )
    validate_pipeline_corpus(pipeline)
    validate_rubric_corpus(rubric)
    validate_cross_suite(pipeline, rubric)
    return pipeline, rubric


# ============================================================================================
# Locked nested gates schema (materialized as evals/gates.json only in Phase 2)
# ============================================================================================


class RateGate(BaseModel):
    """A count-based gate over a complete suite denominator.

    ``min_rate`` is a fixed four-decimal display string; runtime comparison uses exact counts
    and unrounded ratios rather than this string.
    """

    model_config = ConfigDict(extra="forbid")

    denominator: int = Field(gt=0)
    minimum_correct: int = Field(ge=0)
    min_rate: str
    max_errors: int = Field(ge=0)
    rationale: str = Field(min_length=10)

    @model_validator(mode="after")
    def _check_gate(self) -> Self:
        if self.minimum_correct > self.denominator:
            raise ValueError("minimum_correct exceeds denominator")
        if self.max_errors != self.denominator - self.minimum_correct:
            raise ValueError("max_errors must equal denominator - minimum_correct")
        expected_rate = f"{self.minimum_correct / self.denominator:.4f}"
        if self.min_rate != expected_rate:
            raise ValueError(f"min_rate must be the four-decimal string {expected_rate!r}")
        return self


class BooleanInvariant(BaseModel):
    """A hard invariant that must hold (for example, deterministic rerun equality).

    ``required`` is pinned to ``Literal[True]``: the one approved invariant of this shape
    (deterministic rerun equality) is never optional, so an unset or ``False`` value is rejected
    outright rather than merely discouraged.
    """

    model_config = ConfigDict(extra="forbid")

    required: Literal[True]
    rationale: str = Field(min_length=10)


class MaxCountGate(BaseModel):
    """A gate expressed as a maximum tolerated absolute count, with no rate/denominator shape.

    Used where a rate is not the right measure: a single missed overconfident summary, or a
    single generic-privacy-pattern hit, is unacceptable regardless of the ratio it represents.
    """

    model_config = ConfigDict(extra="forbid")

    max_count: int = Field(ge=0)
    rationale: str = Field(min_length=10)


class CorpusRef(BaseModel):
    """Approved fixture hashes bound into the gates file."""

    model_config = ConfigDict(extra="forbid")

    pipeline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rubric_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PipelineGates(BaseModel):
    """Suite A gate set."""

    model_config = ConfigDict(extra="forbid")

    schema_valid: RateGate
    category_conformance: RateGate
    review_routing_conformance: RateGate
    issue_exact_set_conformance: RateGate


class RubricGates(BaseModel):
    """Suite B gate set.

    ``critical_overconfidence_false_negatives`` is a :class:`MaxCountGate`, not a
    :class:`RateGate`: it tolerates zero missed overconfident summaries, an absolute count, not
    a rate over a denominator.
    """

    model_config = ConfigDict(extra="forbid")

    review_routing_conformance: RateGate
    issue_exact_set_conformance: RateGate
    critical_overconfidence_false_negatives: MaxCountGate


class HardInvariants(BaseModel):
    """Cross-cutting hard invariants."""

    model_config = ConfigDict(extra="forbid")

    deterministic_rerun_equality: BooleanInvariant
    generic_privacy_pattern_violations: MaxCountGate


class GatesFile(BaseModel):
    """Strict schema of ``evals/gates.json`` (the only runtime gate source, Phase 2 only)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    corpus_version: Literal["v1"]
    corpus: CorpusRef
    pipeline: PipelineGates
    rubric: RubricGates
    hard_invariants: HardInvariants


# ============================================================================================
# Section 7.8 / 7.9 output contract (produced by the Phase 2 evaluator)
# ============================================================================================


class MetricValue(BaseModel):
    """One rendered count/rate metric.

    ``rate`` is a fixed string such as ``"1.0000"`` or ``"not_applicable"``, rendered with
    ``ROUND_HALF_UP`` (ties away from zero), not Python's default banker's rounding.
    ``gate_passed`` is ``None`` for report-only measures that have no corresponding gate.
    Deliberately excludes ``name`` (implied by the enclosing field), ``minimum_rate``, and
    ``denominator`` (renamed ``total`` here) — those belong to the gate policy object, not the
    rendered report.
    """

    model_config = ConfigDict(extra="forbid")

    correct: int = Field(ge=0)
    total: int = Field(ge=0)
    errors: int = Field(ge=0)
    rate: str
    gate_passed: bool | None

    @model_validator(mode="after")
    def _check_metric(self) -> Self:
        if self.correct + self.errors != self.total:
            raise ValueError("correct + errors must equal total")
        if self.total == 0:
            if self.correct != 0 or self.errors != 0:
                raise ValueError("a zero-total metric must have correct=0 and errors=0")
            if self.rate != RATE_NOT_APPLICABLE:
                raise ValueError(f"a zero-total metric's rate must be {RATE_NOT_APPLICABLE!r}")
            return self
        if self.rate == RATE_NOT_APPLICABLE:
            raise ValueError("a nonzero-total metric's rate must not be 'not_applicable'")
        if not _RATE_PATTERN.fullmatch(self.rate):
            raise ValueError(f"malformed rate string: {self.rate!r}")
        expected_rate = _format_rate_half_up(self.correct, self.total)
        if self.rate != expected_rate:
            raise ValueError(
                f"rate must be the ROUND_HALF_UP four-decimal string {expected_rate!r}"
            )
        return self


class PipelineMetrics(BaseModel):
    """Suite A rendered metrics. ``sentiment_conformance`` is the sole report-only extension;
    every other metric here has a corresponding gate and must carry a concrete pass/fail."""

    model_config = ConfigDict(extra="forbid")

    schema_valid: MetricValue
    category_conformance: MetricValue
    sentiment_conformance: MetricValue
    review_routing_conformance: MetricValue
    issue_exact_set_conformance: MetricValue
    deterministic_rerun_equal: bool

    @model_validator(mode="after")
    def _check_gate_passed_shape(self) -> Self:
        gated_fields = (
            "schema_valid",
            "category_conformance",
            "review_routing_conformance",
            "issue_exact_set_conformance",
        )
        for field_name in gated_fields:
            if getattr(self, field_name).gate_passed is None:
                raise ValueError(f"{field_name}.gate_passed must be bool, not null")
        if self.sentiment_conformance.gate_passed is not None:
            raise ValueError("sentiment_conformance is report-only: gate_passed must be null")
        return self


class RubricMetrics(BaseModel):
    """Suite B rendered metrics, including micro-averaged precision/recall/F1 over the three
    canonical issue codes. ``critical_overconfidence_false_negatives`` is not a rubric metric;
    it is reported once, under ``hard_invariants``. The micro-averages are report-only: no gate
    is defined over them.
    """

    model_config = ConfigDict(extra="forbid")

    review_routing_conformance: MetricValue
    issue_exact_set_conformance: MetricValue
    micro_precision: MetricValue
    micro_recall: MetricValue
    micro_f1: MetricValue

    @model_validator(mode="after")
    def _check_gate_passed_shape(self) -> Self:
        for field_name in ("review_routing_conformance", "issue_exact_set_conformance"):
            if getattr(self, field_name).gate_passed is None:
                raise ValueError(f"{field_name}.gate_passed must be bool, not null")
        for field_name in ("micro_precision", "micro_recall", "micro_f1"):
            if getattr(self, field_name).gate_passed is not None:
                raise ValueError(f"{field_name} is report-only: gate_passed must be null")
        return self


class PerCodeConfusion(BaseModel):
    """Per-code confusion counts for the rubric suite. ``support`` is the golden positive count
    for the code, and must equal the cases the code was actually expected on."""

    model_config = ConfigDict(extra="forbid")

    code: str
    support: int = Field(ge=0)
    true_positives: int = Field(ge=0)
    false_positives: int = Field(ge=0)
    false_negatives: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_support(self) -> Self:
        if self.support != self.true_positives + self.false_negatives:
            raise ValueError("support must equal true_positives + false_negatives")
        return self


FailureKind = Literal["schema", "category", "routing", "issue_set", "critical_false_negative"]


class FailureRow(BaseModel):
    """A single deterministic failure row (the rendered list is bounded by ``MAX_FAILURE_ROWS``;
    ``failure_count`` on the enclosing report is always the true, unbounded total)."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    failure_kind: FailureKind
    expected: str = Field(max_length=200)
    observed: str = Field(max_length=200)
    missing_issue_codes: list[str] = Field(default_factory=list)
    unexpected_issue_codes: list[str] = Field(default_factory=list)
    explanation: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def _check_issue_code_lists(self) -> Self:
        _validate_issue_codes("failure_row.missing_issue_codes", self.missing_issue_codes)
        _validate_issue_codes("failure_row.unexpected_issue_codes", self.unexpected_issue_codes)
        return self


class PipelineReport(BaseModel):
    """Suite A output object. ``failures`` is bounded to ``MAX_FAILURE_ROWS``; ``failure_count``
    is always the true, unbounded total and must be at least the rendered row count."""

    model_config = ConfigDict(extra="forbid")

    case_count: int = Field(ge=0)
    metrics: PipelineMetrics
    failure_count: int = Field(ge=0)
    failures: list[FailureRow] = Field(default_factory=list, max_length=MAX_FAILURE_ROWS)

    @model_validator(mode="after")
    def _check_failures_bounded_by_count(self) -> Self:
        if len(self.failures) > self.failure_count:
            raise ValueError("failures must not exceed failure_count")
        return self


class RubricReport(BaseModel):
    """Suite B output object. ``per_code`` must list every canonical code exactly once, in
    canonical order — never empty, never a subset. ``failures`` is bounded the same way as
    :class:`PipelineReport`."""

    model_config = ConfigDict(extra="forbid")

    case_count: int = Field(ge=0)
    metrics: RubricMetrics
    per_code: list[PerCodeConfusion] = Field(default_factory=list)
    failure_count: int = Field(ge=0)
    failures: list[FailureRow] = Field(default_factory=list, max_length=MAX_FAILURE_ROWS)

    @model_validator(mode="after")
    def _check_per_code_is_complete_and_canonical(self) -> Self:
        codes = [entry.code for entry in self.per_code]
        if codes != list(CANONICAL_ISSUE_CODES):
            raise ValueError(
                f"per_code must list every canonical code exactly once, in canonical order, "
                f"got {codes}"
            )
        return self

    @model_validator(mode="after")
    def _check_failures_bounded_by_count(self) -> Self:
        if len(self.failures) > self.failure_count:
            raise ValueError("failures must not exceed failure_count")
        return self


class HardInvariantsReport(BaseModel):
    """Observed hard-invariant outcomes."""

    model_config = ConfigDict(extra="forbid")

    critical_overconfidence_false_negatives: int = Field(ge=0)
    generic_privacy_pattern_violations: int = Field(ge=0)
    deterministic_rerun_equal: bool


class EvaluationOutput(BaseModel):
    """The full deterministic evaluation report (populated by the Phase 2 evaluator)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    corpus_version: Literal["v1"]
    provider: Literal["deterministic_rule_provider"]
    pipeline: PipelineReport
    rubric: RubricReport
    hard_invariants: HardInvariantsReport
    all_gates_passed: bool
    limitations: list[str]

    @model_validator(mode="after")
    def _check_mandatory_limitations(self) -> Self:
        if self.limitations != list(MANDATORY_LIMITATIONS):
            raise ValueError("limitations must equal the exact mandatory list, in fixed order")
        return self


# ============================================================================================
# Phase 2 evaluator (owner-approved): pure metric functions, evaluation, rendering, privacy
# ============================================================================================

_EVALS_DIR = Path(__file__).resolve().parents[2] / "evals"
DEFAULT_PIPELINE_PATH = _EVALS_DIR / "pipeline_cases.json"
DEFAULT_RUBRIC_PATH = _EVALS_DIR / "rubric_cases.json"
DEFAULT_GATES_PATH = _EVALS_DIR / "gates.json"
DEFAULT_README_PATH = _EVALS_DIR / "README.md"
# Tracked source files scanned as part of the --check evidence-boundary privacy sweep.
_TRACKED_SOURCE_PATHS = (
    Path(__file__).resolve(),
    Path(__file__).resolve().parent / "cli.py",
)


def load_gates(gates_path: Path) -> GatesFile:
    """Load and strictly validate the approved gates file (the only runtime gate source)."""
    return GatesFile.model_validate(json.loads(Path(gates_path).read_text(encoding="utf-8")))


# Generic, public-safe pattern set shared with tests/test_examples_are_synthetic.py so the
# fixture/source-tree scan and the in-report scan below never drift apart.
GENERIC_PRIVACY_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", re.IGNORECASE),
    "phone": re.compile(r"\+?[0-9][0-9 ()-]{8,}"),
    "credential_hint": re.compile(r"(api[_-]?key|secret|token)\s*[:=]", re.IGNORECASE),
}


def scan_privacy_violations(text: str) -> int:
    """Count generic email / phone / credential-hint pattern matches in ``text``. Pure."""
    return sum(len(pattern.findall(text)) for pattern in GENERIC_PRIVACY_PATTERNS.values())


def conformance_metric(
    name: str, correct: int, denominator: int, gate: RateGate | None = None
) -> MetricValue:
    """Build one rendered ``MetricValue`` from raw counts. Pure (raises rather than performing
    I/O); ``name`` is used only in the raised error, not stored on ``MetricValue``. ``gate`` is
    omitted for report-only measures, leaving ``gate_passed`` null.

    When ``gate`` is given, this makes the gate fully operational rather than checking
    ``max_errors`` alone:

    - the actual ``denominator`` must equal ``gate.denominator`` -- never inferred from a
      fixture hash match, checked explicitly here so a corpus/gate mismatch is caught even if
      the hash check is ever bypassed or the gates file is edited independently of the corpus;
    - ``correct >= gate.minimum_correct``;
    - ``errors <= gate.max_errors``;
    - the *exact*, unrounded ``Decimal(correct) / Decimal(denominator)`` ratio must be
      ``>= Decimal(gate.min_rate)`` -- compared as the fixed decimal string, not re-derived,
      since ``min_rate`` can itself be a rounded rendering of ``minimum_correct / denominator``.

    ``gate_passed`` is true only when all three conditions hold.
    """
    errors = denominator - correct
    rate = RATE_NOT_APPLICABLE if denominator == 0 else _format_rate_half_up(correct, denominator)
    if gate is None:
        return MetricValue(
            correct=correct, total=denominator, errors=errors, rate=rate, gate_passed=None
        )

    if denominator != gate.denominator:
        raise CorpusError(
            f"{name}: actual denominator {denominator} does not match the approved gate "
            f"denominator {gate.denominator}"
        )
    meets_minimum_correct = correct >= gate.minimum_correct
    meets_max_errors = errors <= gate.max_errors
    exact_rate = Decimal(correct) / Decimal(denominator) if denominator > 0 else Decimal(0)
    meets_min_rate = exact_rate >= Decimal(gate.min_rate)
    gate_passed = meets_minimum_correct and meets_max_errors and meets_min_rate

    return MetricValue(
        correct=correct, total=denominator, errors=errors, rate=rate, gate_passed=gate_passed
    )


def confusion_for_code(
    code: str, expected: list[set[str]], observed: list[set[str]]
) -> PerCodeConfusion:
    """Aggregate TP/FP/FN (and derived ``support``) for one code across paired case sets. Pure."""
    true_positives = false_positives = false_negatives = 0
    for expected_codes, observed_codes in zip(expected, observed, strict=True):
        expected_has = code in expected_codes
        observed_has = code in observed_codes
        if expected_has and observed_has:
            true_positives += 1
        elif expected_has and not observed_has:
            false_negatives += 1
        elif observed_has and not expected_has:
            false_positives += 1
    return PerCodeConfusion(
        code=code,
        support=true_positives + false_negatives,
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
    )


def _sha256_of_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _pipeline_suite_pass(
    pipeline_cases: list[PipelineCase], provider: DeterministicRuleProvider
) -> dict:
    """One full deterministic pass over Suite A, as plain comparable primitives (not Pydantic
    models) so two independent passes can be checked for equality -- this *proves* determinism
    rather than assuming it."""
    schema_correct = category_correct = sentiment_correct = 0
    routing_correct = issue_set_correct = 0
    failures: list[tuple] = []

    for case in pipeline_cases:
        raw_insight = provider.extract_insight(case.note)
        try:
            insight = OpsInsight.model_validate(raw_insight)
        except ValidationError:
            failures.append(
                (
                    case.case_id,
                    "schema",
                    "valid OpsInsight payload",
                    "schema-invalid provider payload",
                    (),
                    (),
                    "Provider payload failed the public OpsInsight schema.",
                )
            )
            continue  # stays in every pipeline denominator as an error; no correct counters bump

        schema_correct += 1
        observed_codes = tuple(issue.code for issue in validate_insight(insight))
        observed_review_required = bool(observed_codes)

        if insight.category.value == case.expected_category.value:
            category_correct += 1
        else:
            failures.append(
                (
                    case.case_id,
                    "category",
                    case.expected_category.value,
                    insight.category.value,
                    (),
                    (),
                    "Category did not match the golden label.",
                )
            )

        if insight.sentiment.value == case.expected_sentiment.value:
            sentiment_correct += 1

        if observed_review_required == case.expected_review_required:
            routing_correct += 1
        else:
            failures.append(
                (
                    case.case_id,
                    "routing",
                    str(case.expected_review_required),
                    str(observed_review_required),
                    (),
                    (),
                    "Review-routing flag did not match bool(expected_issue_codes).",
                )
            )

        expected_codes = tuple(case.expected_issue_codes)
        if observed_codes == expected_codes:
            issue_set_correct += 1
        else:
            missing = tuple(c for c in expected_codes if c not in observed_codes)
            unexpected = tuple(c for c in observed_codes if c not in expected_codes)
            failures.append(
                (
                    case.case_id,
                    "issue_set",
                    ",".join(expected_codes) or "(none)",
                    ",".join(observed_codes) or "(none)",
                    missing,
                    unexpected,
                    "Validator issue set did not match the golden set.",
                )
            )

    return {
        "schema_correct": schema_correct,
        "category_correct": category_correct,
        "sentiment_correct": sentiment_correct,
        "routing_correct": routing_correct,
        "issue_set_correct": issue_set_correct,
        "failures": tuple(failures),
    }


def _rubric_suite_pass(rubric_cases: list[RubricCase]) -> dict:
    """One full deterministic pass over Suite B, as plain comparable primitives (see
    ``_pipeline_suite_pass``)."""
    routing_correct = issue_set_correct = 0
    failures: list[tuple] = []
    expected_sets: list[set[str]] = []
    observed_sets: list[set[str]] = []

    for case in rubric_cases:
        observed_codes = tuple(issue.code for issue in validate_insight(case.insight))
        expected_sets.append(set(case.expected_issue_codes))
        observed_sets.append(set(observed_codes))
        observed_review_required = bool(observed_codes)

        if observed_review_required == case.expected_review_required:
            routing_correct += 1
        else:
            failures.append(
                (
                    case.case_id,
                    "routing",
                    str(case.expected_review_required),
                    str(observed_review_required),
                    (),
                    (),
                    "Review-routing flag did not match bool(expected_issue_codes).",
                )
            )

        expected_codes = tuple(case.expected_issue_codes)
        if observed_codes == expected_codes:
            issue_set_correct += 1
        else:
            missing = tuple(c for c in expected_codes if c not in observed_codes)
            unexpected = tuple(c for c in observed_codes if c not in expected_codes)
            failures.append(
                (
                    case.case_id,
                    "issue_set",
                    ",".join(expected_codes) or "(none)",
                    ",".join(observed_codes) or "(none)",
                    missing,
                    unexpected,
                    "Validator issue set did not match the golden set.",
                )
            )

    per_code = tuple(
        confusion_for_code(code, expected_sets, observed_sets) for code in CANONICAL_ISSUE_CODES
    )
    critical_confusion = next(c for c in per_code if c.code == CRITICAL_OVERCONFIDENCE_CODE)
    for case, expected_codes_set, observed_codes_set in zip(
        rubric_cases, expected_sets, observed_sets, strict=True
    ):
        if (
            CRITICAL_OVERCONFIDENCE_CODE in expected_codes_set
            and CRITICAL_OVERCONFIDENCE_CODE not in observed_codes_set
        ):
            failures.append(
                (
                    case.case_id,
                    "critical_false_negative",
                    CRITICAL_OVERCONFIDENCE_CODE,
                    "(missing)",
                    (CRITICAL_OVERCONFIDENCE_CODE,),
                    (),
                    "Missed a critical overconfident-summary case.",
                )
            )

    return {
        "routing_correct": routing_correct,
        "issue_set_correct": issue_set_correct,
        "failures": tuple(failures),
        "per_code": per_code,
        "critical_fn_count": critical_confusion.false_negatives,
    }


def _failure_row_from_tuple(row: tuple) -> FailureRow:
    case_id, kind, expected, observed, missing, unexpected, explanation = row
    return FailureRow(
        case_id=case_id,
        failure_kind=kind,
        expected=expected,
        observed=observed,
        missing_issue_codes=list(missing),
        unexpected_issue_codes=list(unexpected),
        explanation=explanation,
    )


def evaluate(
    pipeline_path: Path = DEFAULT_PIPELINE_PATH,
    rubric_path: Path = DEFAULT_RUBRIC_PATH,
    gates_path: Path = DEFAULT_GATES_PATH,
) -> EvaluationOutput:
    """Run the untouched provider/validators against the corpus and score them against the
    approved gates. The only impure function in this module: it reads the corpus and gates
    files, then delegates to the pure helpers above.

    Rejects a corpus whose fixture bytes do not match the hashes recorded in the approved
    ``gates.json`` -- a corpus with a different byte count (e.g. a missing case) necessarily
    has a different hash, so this also rejects a corpus with the wrong case count. Runs each
    suite twice and only reports ``deterministic_rerun_equal`` as true if the two independent
    passes produced byte-for-byte identical results.
    """
    gates = load_gates(gates_path)

    pipeline_hash = _sha256_of_file(pipeline_path)
    if pipeline_hash != gates.corpus.pipeline_sha256:
        raise CorpusError(
            "pipeline corpus does not match the approved gates.json fixture hash "
            f"(expected {gates.corpus.pipeline_sha256}, got {pipeline_hash})"
        )
    rubric_hash = _sha256_of_file(rubric_path)
    if rubric_hash != gates.corpus.rubric_sha256:
        raise CorpusError(
            "rubric corpus does not match the approved gates.json fixture hash "
            f"(expected {gates.corpus.rubric_sha256}, got {rubric_hash})"
        )

    pipeline_cases, rubric_cases = load_corpus(pipeline_path, rubric_path)
    provider = DeterministicRuleProvider()

    first_pipeline = _pipeline_suite_pass(pipeline_cases, provider)
    second_pipeline = _pipeline_suite_pass(pipeline_cases, provider)
    pipeline_rerun_equal = first_pipeline == second_pipeline

    first_rubric = _rubric_suite_pass(rubric_cases)
    second_rubric = _rubric_suite_pass(rubric_cases)
    rubric_rerun_equal = first_rubric == second_rubric

    deterministic_rerun_equal = pipeline_rerun_equal and rubric_rerun_equal

    # ---- Suite A report ----
    pipeline_total = len(pipeline_cases)
    schema_metric = conformance_metric(
        "schema_valid",
        first_pipeline["schema_correct"],
        pipeline_total,
        gate=gates.pipeline.schema_valid,
    )
    category_metric = conformance_metric(
        "category_conformance",
        first_pipeline["category_correct"],
        pipeline_total,
        gate=gates.pipeline.category_conformance,
    )
    sentiment_metric = conformance_metric(
        "sentiment_conformance", first_pipeline["sentiment_correct"], pipeline_total
    )
    routing_metric = conformance_metric(
        "review_routing_conformance",
        first_pipeline["routing_correct"],
        pipeline_total,
        gate=gates.pipeline.review_routing_conformance,
    )
    issue_set_metric = conformance_metric(
        "issue_exact_set_conformance",
        first_pipeline["issue_set_correct"],
        pipeline_total,
        gate=gates.pipeline.issue_exact_set_conformance,
    )
    pipeline_failures = [_failure_row_from_tuple(row) for row in first_pipeline["failures"]]

    pipeline_report = PipelineReport(
        case_count=pipeline_total,
        metrics=PipelineMetrics(
            schema_valid=schema_metric,
            category_conformance=category_metric,
            sentiment_conformance=sentiment_metric,
            review_routing_conformance=routing_metric,
            issue_exact_set_conformance=issue_set_metric,
            deterministic_rerun_equal=pipeline_rerun_equal,
        ),
        failure_count=len(pipeline_failures),
        failures=pipeline_failures[:MAX_FAILURE_ROWS],
    )

    # ---- Suite B report ----
    rubric_total = len(rubric_cases)
    rubric_failures = [_failure_row_from_tuple(row) for row in first_rubric["failures"]]
    per_code = list(first_rubric["per_code"])
    critical_fn_count = first_rubric["critical_fn_count"]
    total_tp = sum(c.true_positives for c in per_code)
    total_fp = sum(c.false_positives for c in per_code)
    total_fn = sum(c.false_negatives for c in per_code)

    routing_metric_b = conformance_metric(
        "review_routing_conformance",
        first_rubric["routing_correct"],
        rubric_total,
        gate=gates.rubric.review_routing_conformance,
    )
    issue_set_metric_b = conformance_metric(
        "issue_exact_set_conformance",
        first_rubric["issue_set_correct"],
        rubric_total,
        gate=gates.rubric.issue_exact_set_conformance,
    )
    micro_precision_metric = conformance_metric("micro_precision", total_tp, total_tp + total_fp)
    micro_recall_metric = conformance_metric("micro_recall", total_tp, total_tp + total_fn)
    micro_f1_metric = conformance_metric(
        "micro_f1", 2 * total_tp, 2 * total_tp + total_fp + total_fn
    )

    rubric_report = RubricReport(
        case_count=rubric_total,
        metrics=RubricMetrics(
            review_routing_conformance=routing_metric_b,
            issue_exact_set_conformance=issue_set_metric_b,
            micro_precision=micro_precision_metric,
            micro_recall=micro_recall_metric,
            micro_f1=micro_f1_metric,
        ),
        per_code=per_code,
        failure_count=len(rubric_failures),
        failures=rubric_failures[:MAX_FAILURE_ROWS],
    )

    # ---- Hard invariants and privacy scan (covers the rendered output, not just source text) ----
    source_text = (
        Path(pipeline_path).read_text(encoding="utf-8")
        + Path(rubric_path).read_text(encoding="utf-8")
        + "\n".join(row.explanation for row in (*pipeline_failures, *rubric_failures))
    )

    def _assemble(privacy_violations: int) -> EvaluationOutput:
        all_gates_passed = all(
            [
                schema_metric.gate_passed,
                category_metric.gate_passed,
                routing_metric.gate_passed,
                issue_set_metric.gate_passed,
                routing_metric_b.gate_passed,
                issue_set_metric_b.gate_passed,
                critical_fn_count <= gates.rubric.critical_overconfidence_false_negatives.max_count,
                deterministic_rerun_equal
                == gates.hard_invariants.deterministic_rerun_equality.required,
                privacy_violations
                <= gates.hard_invariants.generic_privacy_pattern_violations.max_count,
            ]
        )
        return EvaluationOutput(
            schema_version=SCHEMA_VERSION,
            corpus_version=CORPUS_VERSION,
            provider=PROVIDER_ID,
            pipeline=pipeline_report,
            rubric=rubric_report,
            hard_invariants=HardInvariantsReport(
                critical_overconfidence_false_negatives=critical_fn_count,
                generic_privacy_pattern_violations=privacy_violations,
                deterministic_rerun_equal=deterministic_rerun_equal,
            ),
            all_gates_passed=all_gates_passed,
            limitations=list(MANDATORY_LIMITATIONS),
        )

    provisional_violations = scan_privacy_violations(source_text)
    provisional_output = _assemble(provisional_violations)
    rendered_text = render_json(provisional_output) + render_markdown(provisional_output)
    final_violations = scan_privacy_violations(source_text + rendered_text)
    if final_violations == provisional_violations:
        return provisional_output
    return _assemble(final_violations)


def render_json(output: EvaluationOutput) -> str:
    """Stable, deterministically key-ordered JSON (Pydantic field-declaration order)."""
    return output.model_dump_json(indent=2) + "\n"


def _metric_table_markdown(rows: list[tuple[str, MetricValue]]) -> str:
    header = "| metric | correct | total | errors | rate | gate_passed |"
    divider = "|---|---:|---:|---:|---:|---|"
    lines = [header, divider]
    for name, metric in rows:
        gate_cell = (
            "—" if metric.gate_passed is None else ("PASS" if metric.gate_passed else "FAIL")
        )
        lines.append(
            f"| {name} | {metric.correct} | {metric.total} | {metric.errors} | "
            f"{metric.rate} | {gate_cell} |"
        )
    return "\n".join(lines)


def _failure_section_markdown(failures: list[FailureRow], failure_count: int) -> str:
    if failure_count == 0:
        return _MD_NO_OBSERVED_MISMATCHES
    lines = [
        f"- **{row.case_id}** ({row.failure_kind}): expected `{row.expected}`, "
        f"observed `{row.observed}` — {row.explanation}"
        for row in failures
    ]
    if len(failures) < failure_count:
        lines.append(f"- ... ({failure_count - len(failures)} more, bounded rendering)")
    return "\n".join(lines)


_MD_NO_OBSERVED_MISMATCHES = "No observed mismatches."


def render_markdown(output: EvaluationOutput) -> str:
    """Deterministic Markdown evidence in the fixed 10-block section order."""
    lines: list[str] = [
        "# Public Kernel Evaluation",
        "",
        MANDATORY_LIMITATIONS[0],
        "",
        "## Overall",
        "",
        f"- Corpus version: {output.corpus_version}",
        f"- Provider: {output.provider}",
        f"- Suite A case count: {output.pipeline.case_count}",
        f"- Suite B case count: {output.rubric.case_count}",
        f"- All gates passed: {'PASS' if output.all_gates_passed else 'FAIL'}",
        "",
        "## Suite A — Pipeline Metrics",
        "",
        _metric_table_markdown(
            [
                ("schema_valid", output.pipeline.metrics.schema_valid),
                ("category_conformance", output.pipeline.metrics.category_conformance),
                ("sentiment_conformance", output.pipeline.metrics.sentiment_conformance),
                ("review_routing_conformance", output.pipeline.metrics.review_routing_conformance),
                (
                    "issue_exact_set_conformance",
                    output.pipeline.metrics.issue_exact_set_conformance,
                ),
            ]
        ),
        f"- deterministic_rerun_equal: {output.pipeline.metrics.deterministic_rerun_equal}",
        "",
        f"## Suite A — Pipeline Failures: {output.pipeline.failure_count} of "
        f"{output.pipeline.case_count}",
        "",
        _failure_section_markdown(output.pipeline.failures, output.pipeline.failure_count),
        "",
        "## Suite B — Validator Rubric Metrics",
        "",
        _metric_table_markdown(
            [
                ("review_routing_conformance", output.rubric.metrics.review_routing_conformance),
                ("issue_exact_set_conformance", output.rubric.metrics.issue_exact_set_conformance),
                ("micro_precision", output.rubric.metrics.micro_precision),
                ("micro_recall", output.rubric.metrics.micro_recall),
                ("micro_f1", output.rubric.metrics.micro_f1),
            ]
        ),
        "",
        "## Suite B — Per-Code Confusion",
        "",
        "| code | support | TP | FP | FN |",
        "|---|---:|---:|---:|---:|",
        *(
            f"| {entry.code} | {entry.support} | {entry.true_positives} | "
            f"{entry.false_positives} | {entry.false_negatives} |"
            for entry in output.rubric.per_code
        ),
        "",
        f"## Suite B — Rubric Failures: {output.rubric.failure_count} of "
        f"{output.rubric.case_count}",
        "",
        _failure_section_markdown(output.rubric.failures, output.rubric.failure_count),
        "",
        "## Hard Invariants",
        "",
        "| invariant | value |",
        "|---|---|",
        "| critical_overconfidence_false_negatives | "
        f"{output.hard_invariants.critical_overconfidence_false_negatives} |",
        "| generic_privacy_pattern_violations | "
        f"{output.hard_invariants.generic_privacy_pattern_violations} |",
        f"| deterministic_rerun_equal | {output.hard_invariants.deterministic_rerun_equal} |",
        "",
        "## Limitations",
        "",
        *(f"{index}. {text}" for index, text in enumerate(output.limitations, start=1)),
        "",
    ]
    return "\n".join(lines)


class EvidenceVerification(NamedTuple):
    """The result of a full evidence-boundary verification pass, used by ``awb eval --check``.

    ``output``/``markdown``/``json_text`` are from the *first* of two independent evaluation
    passes; when both ``determinism_ok`` and ``privacy_ok`` are true, they are the exact bytes
    that must be emitted -- never re-rendered.
    """

    output: EvaluationOutput
    markdown: str
    json_text: str
    determinism_ok: bool
    privacy_ok: bool


def produce_verified_evidence(
    pipeline_path: Path = DEFAULT_PIPELINE_PATH,
    rubric_path: Path = DEFAULT_RUBRIC_PATH,
    gates_path: Path = DEFAULT_GATES_PATH,
    readme_path: Path = DEFAULT_README_PATH,
) -> EvidenceVerification:
    """Run two fully independent ``evaluate()`` passes and render each to Markdown and JSON,
    comparing the exact UTF-8 bytes of both candidates -- the evidence-boundary determinism
    proof used by ``--check``, stronger than any single pass's self-reported
    ``deterministic_rerun_equal`` field (which compares intermediate Python structures, not the
    bytes that would actually be published).

    Also scans, for generic privacy patterns, the exact pipeline/rubric fixture text,
    ``gates.json``, ``evals/README.md``, the tracked ``evaluation.py``/``cli.py`` source, and
    the exact Markdown/JSON byte candidates that would be emitted -- never a freshly,
    separately rendered copy.

    The returned ``markdown``/``json_text`` are the first pass's already-rendered bytes, reused
    verbatim; the caller must never render the selected artifact a second time.
    """
    first = evaluate(pipeline_path, rubric_path, gates_path)
    first_markdown = render_markdown(first)
    first_json = render_json(first)

    second = evaluate(pipeline_path, rubric_path, gates_path)
    second_markdown = render_markdown(second)
    second_json = render_json(second)

    determinism_ok = first_markdown.encode("utf-8") == second_markdown.encode(
        "utf-8"
    ) and first_json.encode("utf-8") == second_json.encode("utf-8")

    tracked_source_text = "".join(
        path.read_text(encoding="utf-8") for path in _TRACKED_SOURCE_PATHS if path.exists()
    )
    scan_text = (
        Path(pipeline_path).read_text(encoding="utf-8")
        + Path(rubric_path).read_text(encoding="utf-8")
        + Path(gates_path).read_text(encoding="utf-8")
        + Path(readme_path).read_text(encoding="utf-8")
        + tracked_source_text
        + first_markdown
        + first_json
    )
    privacy_ok = scan_privacy_violations(scan_text) == 0

    return EvidenceVerification(
        output=first,
        markdown=first_markdown,
        json_text=first_json,
        determinism_ok=determinism_ok,
        privacy_ok=privacy_ok,
    )
