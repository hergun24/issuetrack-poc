# BLOCKER-ESCALATION-RECORD.md

Application: **IssueTrack Lite** v0.2.0-rc1
Date: 2026-11-19 (UTC)
Status: **No active blockers at release-candidate time.**

---

## 1. Active blockers

**None.** All identified blockers have been resolved or documented as known
limitations in `KNOWN-LIMITATIONS.md`.

## 2. Resolved blockers

| ID | Blocker | Resolution | Resolved at |
|----|---------|------------|-------------|
| BLK-01 | Fresh database had no seed users; both `admin@example.com` and `member@example.com` logins returned 401 on a clean `rm -rf data/` restart. | `create_app()` now calls `seed(db, force=False)` by default (`auto_seed=True`). Tests explicitly disable auto-seeding via `auto_seed=False` to preserve isolation. Verified in m4a clean-setup exercise. | m4 (2026-11-19) |

## 3. Non-blockers documented in KNOWN-LIMITATIONS.md

The following items are **not blockers** (they do not prevent the RC from
being functional and correct) but are tracked for post-RC work:

| Item | Reference |
|------|-----------|
| No automated browser E2E tests | L-F3 |
| No performance benchmark (NFR-004) | L-N1 |
| No automated process-restart persistence test (NFR-009) | L-N3 |
| No automated keyboard accessibility test (FR-062) | L-F1 |
| No automated viewport screenshots (NFR-001) | L-F2 |
| No non-UTC process-TZ test (NFR-005) | TEST-EXECUTION-REPORT sec 3 |
| No token TTL (residual risk) | L-S2 |
| `passlib` in pinned-deps.txt but not installed/imported | L-S8 |

## 4. Escalation policy

If any of the above items (or a new blocker) prevents the RC from being
shipped or causes a test to fail in the final verification run, the agent
must:
1. Record the blocker in this file under "Active blockers".
2. Mark the affected milestone task as blocked in the task tracker.
3. Continue all unblocked milestones.
4. Do **not** weaken scope, skip tests, or remove assertions to work
   around a blocker.
