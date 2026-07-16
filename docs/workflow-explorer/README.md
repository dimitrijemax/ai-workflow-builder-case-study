# Workflow Explorer Contract

`index.html` is a committed, deterministic, offline view of two bounded public contracts:

- **RUN** traces the ten synthetic demo notes through the existing provider, Pydantic contract,
  validator, human-review gate, and report outcome.
- **BUILD** renders the accepted pilot process and one immutable completed evidence trace,
  Issue #9 to PR #10. It is not a live task tracker.

Open `index.html` directly through `file://`. No web server, external asset, API, model call,
credential, or runtime network connection is required.

## Visual vocabulary

The renderer accepts only this vocabulary. Tests read these documented values and compare them
with `model.py`.

- Node kinds: `input`, `transform`, `contract`, `check`, `gate`, `output`.
- Statuses: `pending`, `passed`, `needs_review`, `approved`, `rejected`, `blocked_owner`.
- Edge kinds: `normal`, `review`, `reject`, `audit`.

Status is always present as text and paired with a shape or border. Color is supplementary.

## Adapter source allowlist

The public adapter reads exactly these committed public-safe sources:

- `examples/synthetic_ops_notes.json`
- the fenced `State Flow` fragment in `docs/AGENT_PILOT.md`
- `docs/workflow-explorer/data/build_trace.json`
- `evals/pipeline_cases.json`
- `evals/rubric_cases.json`
- `evals/gates.json`
- `docs/workflow-explorer/template.html`

The adapter calls the existing deterministic pipeline and evaluator. It scans the exact `State
Flow` fragment it consumes; the full pilot document also contains two public synthetic ISO dates in
its lease example that match the generic phone-pattern heuristic. It does not fetch GitHub or copy
current issue state. `build_trace.json` contains only terminal public identifiers, public URLs, and
accepted SHAs for the completed Issue #9 to PR #10 trace.

## Generated-file policy

`index.html` is generated and committed so it works without a Python runtime. The generator:

- omits `BatchReport.generated_at` rather than freezing or rendering it;
- sorts mapping-derived collections and writes UTF-8 without BOM, LF only, and one final LF;
- embeds local CSS and vanilla JavaScript while retaining all ten traces as semantic `<details>`
  sections when JavaScript is unavailable;
- scans every adapter source and the generated HTML with the repository's generic privacy scanner;
- treats a stale committed artifact as a failed `--check`, without rewriting it.

Rebuild or verify with locked dependencies:

```bash
uv run --locked python docs/workflow-explorer/build.py
uv run --locked python docs/workflow-explorer/build.py --check
uv run --locked python docs/workflow-explorer/build.py --output out/explorer.html
```

## Limits and claim boundary

The baseline is ten synthetic insights: eight auto-pass and two wait for human review. Those counts
are derived from returned pipeline objects during every build, not maintained here as status data.
Suite A and Suite B remain separate with explicit denominators. There is no combined score, learned
model claim, production benchmark, deployment claim, live-data integration, or editable workflow
state in this artifact.
