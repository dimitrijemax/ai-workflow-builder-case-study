# PyCharm-First Agent Pilot

Status: experimental workflow for the first two portfolio deliverables.

Bootstrap exception: Codex materializes this workflow before the first pilot issue exists. The
exception ends before the first coding task; during the pilot Codex returns to read-only analysis
and review unless the owner separately authorizes a git-only action. The one-time PR exception
requires branch `codex/pilot-agent-workflow`, owner authorship, the marker
`Bootstrap exception: agent-pilot-v1` as its own line, a same-repository head, and the
workflow-infrastructure current/previous filename allowlist; verification, handoff, review-SHA,
and owner gates still apply. Delete the bootstrap branch after merge; do not reuse the exception.

## Goal

Keep PyCharm as the control surface while using one builder, one independent analyst/reviewer,
and deterministic checks. The pilot optimizes completed evidence, not model usage or parallelism.

## Roles

| Role | Default | Responsibility |
|---|---|---|
| Owner | PyCharm | Accept task contract, review diff, run owner-only smoke, authorize git |
| Analyst | Codex | Read-only preflight: risks, dependency order, failure paths, minimum tests |
| Builder | Claude Code | Plan, implement, run targeted checks, and post handoff |
| Helper | Junie Ask | IDE-native read-only exploration and diagnostics |
| Verifier | PyCharm plus WSL | Targeted tests, full checks, offline demo |
| Reviewer | Codex | Read-only review of the stable handoff snapshot |

Junie becomes a writer only when the linked issue explicitly names it as the builder for an L1
task. Claude Code and Junie never edit the same checkout concurrently.

## State Flow

```text
Next
  -> Ready
  -> Codex preflight
  -> Owner plan approval
  -> Builder writing
  -> Builder handoff
  -> Deterministic verification
  -> Codex review
  -> Same-builder fixes, if blocking
  -> Ready for PR
  -> Owner acceptance
```

The issue `Workflow progress` checklist is the visible state. There is no parallel dashboard or
duplicate status document.

## Automated Controls

- The issue form requires outcome, acceptance criteria, scope, non-goals, roles, verification,
  timebox, and public-safety confirmation.
- The `Task state` workflow mirrors state, risk, and builder into labels and rejects a second open
  `Ready` task with `pilot:conflict`. Issue events are queued and current issue state is re-read
  before labels are applied.
- `AGENTS.md` gives every supported agent the same durable rules.
- The pull-request template carries the task contract and builder handoff into review.
- The `PR contract` workflow checks the linked issue, role declarations, stable handoff, and
  required ready-for-review confirmations. Handoff and review SHAs must equal the current PR head,
  so a later commit invalidates stale approval.
- Existing CI runs ruff, pytest, and gitleaks on synthetic material.

Human approval remains mandatory for task scope, writer arbitration, public claims, and any live
or credentialed action. Freeze the issue body after `Ready for PR`. If an exceptional issue edit is
needed later, freeze work and manually re-run `PR contract`; issue edits do not trigger that
pull-request workflow.

## Model Routing

- Claude Code: use the strongest planning tier for ambiguous L2/L3 work, the default coding tier
  for implementation, and a cheap read-only helper only for narrow searches or noisy logs.
- Codex: use the default tier for routine read-heavy scans and the strongest reasoning tier for L3
  analysis or final synthesis.
- Junie: use Ask mode or a cost-efficient model for L1 work with a deterministic oracle. Keep
  Brave Mode disabled.
- Do not use agent teams for routine implementation. Parallelism is read-only and bounded.

## Pickup Procedure

1. Open the only issue whose task state is `Ready`.
2. Ask Codex for a read-only preflight against that exact issue and current branch.
3. Update the progress checklist and approve or correct the proposed implementation plan.
4. Check the branch, `git status`, and `.active_writer.lock`. The named builder writes an `active`
   lease, re-reads it, and stops unless issue, writer, branch, and scope all match.
5. Start the named builder from the repository root in PyCharm. It writes only within issue scope,
   tests incrementally, and refreshes the heartbeat during long work.
6. The builder records changed files, checks, unfinished work, and risks in the lock, changes it to
   `handoff-ready`, posts the same handoff in the task, and stops writing.
7. Run deterministic verification on the stable handoff snapshot.
8. Ask Codex to review that snapshot without editing it.
9. Return blocking findings to the same builder after it reacquires an `active` lease; defer
   optional work. A different builder requires owner arbitration, an updated issue, and release.

## Local Lease

The local lock is intentionally small, ephemeral, and ignored by git:

```yaml
state: active
writer: claude-code
issue: 12
branch: feat/12-provider-selection
scope:
  - src/ai_workflow_builder/providers.py
  - tests/test_providers.py
heartbeat_at: 2026-07-10T09:00:00+02:00
expires_at: 2026-07-10T11:00:00+02:00
handoff:
  changed_files: []
  checks_run: []
  unfinished_work: ""
  known_risks: ""
```

The transition is `absent/released -> active -> handoff-ready -> released`. Treat a lease as stale
only when its expiry is in the past. Takeover is an owner decision recorded in the task. At
handoff, fill the four required handoff fields and stop editing. After the separately authorized
git step, the git actor marks the lease `released` or removes it.

## Baseline Verification

```bash
uv sync --locked --all-extras
uv run --locked ruff check .
uv run --locked pytest -q
uv run --locked awb demo
```

Git commit, push, pull request creation, and external publication require a separate explicit owner
command.

The issue-label workflow cannot run until this file reaches the default branch. After bootstrap
merge, run one real synthetic smoke: task A `Ready`; task B `Ready -> pilot:conflict`; A to `Next`;
then re-edit B to `Ready`. Finally restore the work order by setting B to `Next` and re-editing A
to `Ready`. Until that passes, label automation remains provisionally verified.
