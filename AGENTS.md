# Agent Rules

- Use synthetic data only.
- Do not commit real operational data, credentials, environment files, local databases, or live outputs.
- Keep the demo runnable offline without external APIs.
- Prefer small, readable modules over clever abstractions.
- Add or update tests before changing workflow behavior.
- Keep public documentation honest: this is a case study, not a production system.

## Pilot Task Contract

- Every code or workflow change starts from a GitHub issue created with the `Pilot coding task`
  form. If there is no accepted issue contract, stay read-only.
- Treat the issue as the source of truth for outcome, acceptance criteria, scope, non-goals,
  risk lane, roles, and verification.
- Keep one current deliverable and one builder. Do not expand the task to adjacent roadmap work.
- Complete the issue progress checklist as the task moves through analysis, writing, handoff,
  verification, and review.
- Let the task-state workflow mirror state, risk, and builder into issue labels. Resolve a
  `pilot:conflict` label before implementation; only one open task may be `pilot:ready`. Managed
  pilot, risk, builder, and contract labels are automation-owned; do not edit them manually.

## Pilot Roles

- Owner / PyCharm: accepts the task contract, arbitrates conflicts, reviews diffs, and performs
  owner-only or live actions.
- Codex: read-only analyst before implementation and read-only reviewer after handoff. Codex may
  perform git operations only after a separate explicit owner command.
- Claude Code: default builder for integrated logic and guarded changes.
- Junie: read-only Ask-mode helper unless the issue explicitly names Junie as the builder for a
  bounded, reversible L1 task with a deterministic verification target.
- PyCharm / WSL: deterministic verification through IDE inspections, targeted tests, and the
  repository check commands.

## Single Writer And Handoff

- Only the builder named in the issue may edit the checkout while the task is in progress.
- Owner and all other agents remain read-only through handoff, verification, and review. Only the
  same named builder may reactivate for blocking fixes. A builder transfer requires owner
  arbitration, an updated issue contract, and a released lease.
- `.active_writer.lock` is local and gitignored. Before editing, the builder checks branch and
  `git status`, reads the lock, writes an `active` lease for the issue scope, then re-reads it.
  A mismatch between issue, branch, builder, scope, and lock is a stop condition.
- Writer IDs are `claude-code`, `junie`, and `owner-pycharm`. Do not overwrite another live lease.
- The lease moves `active -> handoff-ready -> released`. Same-builder blocking fixes require a new
  `active` lease and re-read. Reviewers and verifiers never update the lock.
- A handoff must list changed files, checks run, unfinished work, and known risks.
- Blocking review findings return to the same builder. Optional findings do not expand the active
  task.
- Verification uses locked dependency commands so a read-only verifier cannot rewrite `uv.lock`.

## Git Boundary

- Do not commit, push, open a pull request, merge, or publish externally without a separate
  explicit owner command.
- Before commit, verify staged scope against the issue contract and confirm that all material is
  synthetic and public-safe.
