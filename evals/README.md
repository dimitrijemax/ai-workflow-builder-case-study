# Evaluation Evidence (v0.2)

This directory holds versioned, synthetic evaluation evidence for the public kernel.
It documents two **deliberately separate** contracts and never blends them into a single
headline score.

- **Suite A — pipeline conformance** (`pipeline_cases.json`): does the untouched deterministic
  provider plus the untouched validators reproduce the expected, human-labelled category,
  sentiment, and validation-issue set for each synthetic operations note?
- **Suite B — validator-rubric behavior** (`rubric_cases.json`): does the untouched validator
  raise exactly the expected issue codes for each synthetic `OpsInsight` fixture, independent of
  any provider?

The two suites live in separate files, use disjoint ID namespaces (`A-*` vs `B-*`), have
independent denominators, and are reported separately. There is intentionally **no combined
cross-suite score** and no blended "review F1".

Corpus version: **`v1`** (the locked `Literal["v1"]` value in the gates/output schema; fixture
bytes are accepted and frozen — see the fixture hashes below). Gate thresholds were approved by
the owner (Issue #9 approval record) and are materialized in `evals/gates.json`.

> Phase status: **Phase 2 is implemented and owner-approved.** `evals/gates.json` exists and
> holds the approved corpus version, fixture hashes, gate values, and rationales — it is the
> only runtime gate source. The pure evaluator, deterministic Markdown/JSON rendering, the
> `awb eval` CLI (`--format`, `--output`, `--check`), the `0/1/2/3` exit-code contract, and the
> generic privacy scanner are all implemented in `src/ai_workflow_builder/evaluation.py` and
> `src/ai_workflow_builder/cli.py`. `evaluate()` verifies the loaded corpus against the approved
> fixture hashes before scoring it, and only reports `deterministic_rerun_equal` as true after
> comparing two independent evaluation passes.

## Conformance terminology (read this first)

"Conformance" here means **the deterministic pipeline reproduced the expected output for a
synthetic input constructed to be unambiguous.** It is **not** model accuracy, model quality, or
a benchmark of a learned system. The provider is a fixed rule engine, so 100% conformance is the
correct and expected contract, not an achievement. A conformance miss means the pipeline contract
regressed, not that a model "scored lower".

## Provenance and public safety

- Every case is **synthetic and clean-room**: authored for this case study, not derived from any
  private prompt, label, output, benchmark, transcript, or dataset.
- All timestamps are fixed synthetic `day_DD_HH` tokens; no runtime clock, host name, local path,
  credential, or private-source reference appears in any fixture.
- Suite A inputs are real `OpsNote` objects (strict `extra="forbid"` schema). No parallel
  string-only input contract is introduced.
- Suite B inputs are real `OpsInsight` objects (strict `extra="forbid"` schema).
- Each Suite A note carries its own note ID (`OPS-30xx`) distinct from its `case_id`; each
  Suite B insight carries its own note ID (`INS-40xx`) distinct from its `case_id`.

## Label rules

Labels are assigned by reading each note or insight on its operational meaning, independently of
how any tool is implemented.

- **Category** is the single dominant operational topic. When several topics appear together, the
  label is the item the note itself emphasises.
- **Sentiment** is the stakeholder tone: negative when the note expresses a block, failure, or
  urgency; positive when it expresses satisfaction; otherwise neutral.
- **Validator issue codes** are the canonical, ordered set the rubric should raise:
  `low_confidence` (confidence below the 0.65 auto-pass threshold, strict `<`),
  `negative_without_action` (negative tone with no action item),
  `overconfident_summary` (summary asserts an absolute, unqualified correctness claim).
- **`expected_review_required`** is recorded on every case and must equal
  `bool(expected_issue_codes)` — a case needs human review exactly when it raises at least one
  issue. The strict models enforce this equality.

`overconfident_summary` is exercised only in Suite B, because the deterministic provider emits a
fixed, safe summary and never produces an overconfident claim inside the pipeline. This is exactly
why the validator-rubric contract is tested separately from the pipeline contract.

## Fixture file shape and corpus rules

Each fixture file is a JSON **array** of case objects in **canonical ascending `case_id` order**.
The `load_corpus` loader validates each case against its strict model and then **rejects** (never
repairs) a corpus that violates any structural rule:

- non-canonical / non-ascending `case_id` order;
- a `case_id` missing its suite prefix (`A-` for Suite A, `B-` for Suite B);
- duplicate `case_id`s, or a `case_id` reused across the two suites;
- duplicate note IDs within a suite, or a note ID reused across the two suites;
- unknown, duplicated, or non-canonically ordered issue codes (per-case model);
- a `expected_review_required` value inconsistent with `bool(expected_issue_codes)`;
- a note ID equal to its own `case_id`.

Suite A case fields: `case_id`, `note` (strict `OpsNote`), `expected_category`,
`expected_sentiment`, `expected_issue_codes`, `expected_review_required`, `label_rationale`,
`tags`. Suite B case fields: `case_id`, `insight` (strict `OpsInsight`), `expected_issue_codes`,
`expected_review_required`, `label_rationale`, `tags`.

## Suite A — case inventory

| case | note id | category | sentiment | expected issue codes | review? |
|---|---|---|---|---|---|
| A-01 | OPS-3001 | data_quality | neutral | — | no |
| A-02 | OPS-3002 | access | neutral | — | no |
| A-03 | OPS-3003 | integration | neutral | — | no |
| A-04 | OPS-3004 | bug | negative | — | no |
| A-05 | OPS-3005 | feature_request | positive | — | no |
| A-06 | OPS-3006 | documentation | neutral | — | no |
| A-07 | OPS-3007 | performance | neutral | — | no |
| A-08 | OPS-3008 | process_gap | neutral | — | no |
| A-09 | OPS-3009 | other | neutral | `low_confidence` | yes |
| A-10 | OPS-3010 | other | negative | `low_confidence`, `negative_without_action` | yes |
| A-11 | OPS-3011 | access | neutral | — | no |
| A-12 | OPS-3012 | documentation | neutral | `low_confidence` | yes |

Special cases: **A-10** is the reachable multi-issue case
(`low_confidence + negative_without_action`). **A-11** is the independently labelled collision
case (a request that names account access as its primary item alongside a routine data sync;
labelled access from the note's own emphasis). **A-12** is the confidence-boundary case (a
tentative, hedged note whose low certainty raises `low_confidence` while its tone stays neutral).

### Suite A support

Per-category support (all 9 provider categories covered):

| category | count | | category | count |
|---|---|---|---|---|
| access | 2 | | integration | 1 |
| bug | 1 | | other | 2 |
| data_quality | 1 | | performance | 1 |
| documentation | 2 | | process_gap | 1 |
| feature_request | 1 | | | |

Sentiment balance: positive 1, neutral 9, negative 2.
In-pipeline validator issues: `low_confidence` ×3 (A-09, A-10, A-12), `negative_without_action` ×1
(A-10). `overconfident_summary` is not reachable in-pipeline by design.

## Suite B — case inventory

| case | note id | expected issue codes | review? | kind |
|---|---|---|---|---|
| B-01 | INS-4001 | — | no | clean |
| B-02 | INS-4002 | `low_confidence` | yes | positive support |
| B-03 | INS-4003 | `negative_without_action` | yes | positive support |
| B-04 | INS-4004 | `overconfident_summary` | yes | positive support |
| B-05 | INS-4005 | — | no | boundary + lexical near-boundary |
| B-06 | INS-4006 | `low_confidence`, `negative_without_action`, `overconfident_summary` | yes | multi-issue |

**B-05** serves two purposes at once: confidence is exactly `0.65` (the auto-pass line; strict `<`
keeps it clean) and the summary describes a single checked example and a routine peer review
without making an absolute, unqualified claim, so it stays clean on both counts.

### Suite B support

| code | positive cases | count |
|---|---|---|
| low_confidence | B-02, B-06 | 2 |
| negative_without_action | B-03, B-06 | 2 |
| overconfident_summary | B-04, B-06 | 2 |

Structural coverage: 1 clean case (B-01), 1 boundary case (B-05), 1 multi-issue case (B-06).

## Corpus budget and balance

| suite | count |
|---|---|
| Suite A | 12 |
| Suite B | 6 |
| **total** | **18** |

Suite A is inside the 12–14 target; the total is inside the accepted 17–20 budget. No case
duplicates another merely to inflate support.

## Baseline result (untouched provider and validators)

- **Suite A:** 12 / 12 conformant (category, sentiment, and validator-issue set all match).
- **Suite B:** 6 / 6 conformant (validator issue set matches).
- **Challenge / collision case A-11:** conformant — the independent human label (access) matches
  the untouched provider output while the note still carries a competing data-sync detail.
- No permanent failing cases; no assertion that conformance must stay below 100%.

## Strict contract models and implementation

`src/ai_workflow_builder/evaluation.py` defines:

- **fixture models** `PipelineCase`, `RubricCase` (strict; enforce canonical issue order,
  `expected_review_required` equality, distinct note IDs);
- **corpus validation** `load_corpus`, `validate_pipeline_corpus`, `validate_rubric_corpus`,
  `validate_cross_suite`, and `CorpusError` (structural rejection, enforced at the full
  corpus-list/file level, not only on a lone case object);
- the **locked nested gates schema** `GatesFile` → `schema_version` (`Literal[1]`, integer),
  `corpus_version` (`Literal["v1"]`), `corpus` / `pipeline` / `rubric` / `hard_invariants`, with
  `RateGate` (fields `denominator`, `minimum_correct`, `min_rate` as a four-decimal string,
  `max_errors`, `rationale`), `BooleanInvariant` (`required`, `rationale`), and `MaxCountGate`
  (`max_count`, `rationale`). `rubric.critical_overconfidence_false_negatives` and
  `hard_invariants.generic_privacy_pattern_violations` are `MaxCountGate`, **not** `RateGate` — a
  tolerated absolute count, not a rate over a denominator;
- the **Section 7.8/7.9 output contract** `EvaluationOutput` → `schema_version` (`Literal[1]`),
  `corpus_version` (`Literal["v1"]`), `provider` (`Literal["deterministic_rule_provider"]`),
  separate `pipeline` / `rubric` objects, `hard_invariants`, `all_gates_passed`, and the four
  mandatory `limitations` in fixed order. `pipeline` = `case_count`, `metrics` (`schema_valid`,
  `category_conformance`, `sentiment_conformance` report-only, `review_routing_conformance`,
  `issue_exact_set_conformance`, `deterministic_rerun_equal`), `failure_count`, `failures`.
  `rubric` = `case_count`, `metrics` (`review_routing_conformance`, `issue_exact_set_conformance`,
  `micro_precision`, `micro_recall`, `micro_f1` — the three micro-averages are report-only, no
  gate is defined over them), `per_code` (`PerCodeConfusion`: `code`, `support`, TP/FP/FN; must
  list every canonical code exactly once, in canonical order — never empty, never a subset),
  `failure_count`, `failures`. Each rendered metric is a `MetricValue`: `correct`, `total`,
  `errors`, `rate` (`"1.0000"` or `"not_applicable"`), `gate_passed` (`bool | None`) —
  deliberately no `name`, `minimum_rate`, or `denominator`. The model self-enforces
  `correct + errors == total`; a zero-`total` metric must have `correct = errors = 0` and
  `rate = "not_applicable"`; a nonzero-`total` metric's `rate` must be the exact
  `ROUND_HALF_UP` (ties away from zero, not Python's banker's rounding) four-decimal rendering
  of `correct / total`, and a malformed rate string is rejected. Every gated metric's
  `gate_passed` must be a concrete `bool`; every report-only metric's (`sentiment_conformance`,
  the three micro-averages) must be `null`. `PerCodeConfusion.support` must equal
  `true_positives + false_negatives`. `hard_invariants` output =
  `critical_overconfidence_false_negatives`, `generic_privacy_pattern_violations`,
  `deterministic_rerun_equal`. `failures` is bounded to `MAX_FAILURE_ROWS` entries and can never
  exceed `failure_count`, which is always the true, unbounded total. `FailureRow` is bounded:
  `case_id`, `failure_kind` (`schema`/`category`/`routing`/`issue_set`/`critical_false_negative`),
  `expected`, `observed`, `missing_issue_codes`, `unexpected_issue_codes` (each validated against
  the canonical codes: no unknown code, no duplicates, canonical order), `explanation`.
  `BooleanInvariant.required` is pinned `Literal[True]` — the one approved invariant of this
  shape is never optional.

The pure evaluator (`conformance_metric`, `confusion_for_code`, `evaluate`), deterministic
Markdown/JSON rendering (`render_markdown`, `render_json`), the generic privacy scanner
(`scan_privacy_violations`), and the `awb eval` CLI (`src/ai_workflow_builder/cli.py`) are all
implemented and owner-approved. `evaluate()` rejects a corpus whose fixture bytes do not match the
hashes recorded in `evals/gates.json` (which also rejects a corpus with a different case count,
since that necessarily changes the hash), and reports `deterministic_rerun_equal` only after
comparing two independent evaluation passes for byte-for-byte equality — not as an assumed
constant. `tests/test_evaluation.py` and `tests/test_eval_cli.py` hold the full contract and
behavioral test suite; no strict-xfail markers remain. The only approved `awb eval` CLI surface is
`awb eval`, `--format markdown|json`, `--output PATH`, and `--check`; there is no `--pipeline` or
`--gates` override. `--output` writes are atomic (temp file + rename); expected-error messages and
the exit-3 diagnostic are sanitized (a fixed category message or exception type name only, never
raw exception text, which can embed absolute local paths or raw internal field values).

### Mandatory limitations (fixed order, validated)

Every `EvaluationOutput.limitations` must equal, in this exact order:

1. Pipeline metrics measure a deterministic rule provider against authored synthetic
   expectations, not a learned model or generalization.
2. The corpus is intentionally small and public-safe; rates are accompanied by absolute counts.
3. Overconfidence is exercised at the validator boundary because the current rule provider
   cannot emit that behavior.
4. The case study does not establish production, live-user, deployment, or domain-specific
   quality.

Suite separation (no combined cross-suite score, independent denominators) and the
`sentiment_conformance` report-only status remain documented elsewhere in this README and in the
output contract above; they are not among the four mandatory limitations and are not restated
here.

## Approved gates (materialized in `evals/gates.json`)

Owner-approved (Issue #9 approval record) and materialized in `evals/gates.json`, the only
runtime gate source. Comparisons use exact counts / unrounded ratios; `min_rate` below is the
fixed four-decimal display string.

`schema_version` = `1` (integer); `corpus_version` = `"v1"`;
`corpus.pipeline_sha256` / `corpus.rubric_sha256` = the fixture hashes below.

Rate gates (`RateGate`):

| gates path | denominator | minimum_correct | min_rate | max_errors | baseline passes | rationale (and why not merely baseline-fitted) |
|---|---|---|---|---|---|---|
| pipeline.schema_valid | 12 | 12 | 1.0000 | 0 | yes (12/12) | Every provider payload must satisfy the public `OpsInsight` contract; a schema-invalid prediction remains in the denominator and counts as incorrect. |
| pipeline.category_conformance | 12 | 12 | 1.0000 | 0 | yes (12/12) | Category is deterministic on unambiguous inputs; exact reproduction is the only correct contract. |
| pipeline.review_routing_conformance | 12 | 12 | 1.0000 | 0 | yes (12/12) | Whether a note is routed to review must match `bool(expected_issue_codes)` on every case. |
| pipeline.issue_exact_set_conformance | 12 | 12 | 1.0000 | 0 | yes (12/12) | The exact validator-in-pipeline issue set (incl. reachable A-10) is deterministic. |
| rubric.review_routing_conformance | 6 | 6 | 1.0000 | 0 | yes (6/6) | Review routing on insight fixtures must match the golden `review?` flag. |
| rubric.issue_exact_set_conformance | 6 | 6 | 1.0000 | 0 | yes (6/6) | The pure rubric's exact issue set per fixture is deterministic. |

Max-count gate (`MaxCountGate` — an absolute tolerance, not a rate over a denominator):

| gates path | max_count | baseline passes | rationale |
|---|---|---|---|
| rubric.critical_overconfidence_false_negatives | 0 | yes (0 FN) | A missed overconfident summary is the highest-risk error; zero false negatives is required over the 2 positive cases (B-04, B-06). Expressed as a tolerated count, not a rate, because any nonzero miss is unacceptable regardless of the ratio it represents. |

Hard invariants:

| gates path | shape | value | rationale |
|---|---|---|---|
| hard_invariants.deterministic_rerun_equality | `BooleanInvariant` | required: true | Two isolated runs must produce byte-identical Markdown and JSON. |
| hard_invariants.generic_privacy_pattern_violations | `MaxCountGate` | max_count: 0 | No generic email/phone/credential pattern may appear in fixtures or generated evidence. |

Report-only measure (**not** a gate; appears in output with `gate_passed = null`):

| measure | suite | denominator | baseline | note |
|---|---|---|---|---|
| sentiment_conformance | A | 12 | 12/12 | Reported for transparency; not enforced per review direction. |

Frozen corpus invariants (composition, enforced by the fixture/corpus contract, not run metrics):
every category ≥ 1 (A); every code positive support ≥ 1 (B); ≥ 1 reachable
`low_confidence + negative_without_action` (A-10); ≥ 1 independently labelled collision (A-11);
≥ 1 confidence-boundary (A-12); ≥ 1 clean + boundary + multi-issue (B).

Thresholds were **not** chosen because the current baseline happens to pass. They follow from the
deterministic nature of the pipeline and rubric on unambiguous synthetic inputs: any value below
100% (or any nonzero critical false-negative / privacy tolerance) would license silent regressions.

## Fixture hashes (accepted and frozen `corpus.*_sha256`)

```
pipeline_cases.json  bed0243bf42705fd45e3d07cb53812ac37b91bfbd1867990ac9593abbf33158b
rubric_cases.json    331e40592f15e1fcb656aa7a4171dbfee8cd889c56d3b7f4c6ce32d5954425fa
```

## Phase 2 status

Implemented and owner-approved: `evals/gates.json` (materializing the approved nested schema
above with the corpus version, fixture hashes, gate values, and rationales); the pure evaluator
and stable Markdown/JSON rendering; the `awb eval` / `--format json` / output-file / `--check`
CLI and exit-code contract (`0/1/2/3`); fixture and generated-artifact privacy scanning with a
poison self-test; and deterministic, byte-stable evidence generation, verified via two
independent evaluation passes rather than assumed.

Deferred to **Pilot Issue 3**: final public-facing metrics/narrative in the root `README.md`, CI
evidence publication, and the release version bump.
