# RUNBOOK — Clean Start (Release Candidate)

Application: **IssueTrack Lite** v0.2.0-rc1
Verified by: autonomous agent, 2026-11-19 (UTC)
Environment: Linux, Python 3.12 (micromamba env `openhands`), SQLite 3

---

## 0. Prerequisites

| Tool | Version used at RC verification | Note |
|---|---|---|
| Python | 3.12.x | stdlib `sqlite3`, `secrets`, `datetime` only in app code |
| pip | recent | used to install pinned requirements |
| curl | any | for manual health/login checks |
| git | any | repo is at `/workspace`, branch `master` |

No paid external service is required (NFR-008). No network access is needed at
runtime — all storage is local SQLite.

## 1. Get the source

```bash
cd /workspace          # repository root (contains app/, static/, tests/, run.py)
git status             # optional; repo has zero commits at RC time (see KNOWN-LIMITATIONS.md)
```

## 2. Install pinned dependencies

```bash
cd /workspace
python3 -m pip install -r requirements.txt
```

Pinned versions (reproducibility, constraint "Pin runtimes and dependencies
sufficiently for repeatability"):

```
fastapi==0.165.0     starlette==1.10.0    uvicorn==0.54.0
pydantic==2.14.3     bcrypt==5.0.0        pytest==9.2.0
httpx==0.28.1        flake8==7.5.0        bandit==1.9.4
```

A machine-captured list of the actually-installed versions is in
`evidence/pinned-deps.txt`.

## 3. Environment configuration

```bash
cp .env.example .env          # optional; placeholders only, no secrets
# or simply export:
export IT_DB_PATH=/workspace/data/issuetrack.db
# If unset, run.py defaults to <repo>/data/issuetrack.db.
```

Notes:
- `.env.example` contains **placeholders only** — there are no secrets in the
  repository (SEC-005, verified by the secrets scan in
  `SECURITY-AUDIT-REPORT.md`).
- The bind host/port are fixed by the contract: `0.0.0.0:8000`.
- The application reads `IT_DB_PATH` itself (`app/seed.py` and `run.py`), and
  `app/db.py` creates any missing parent directory for the database file.

## 4. Schema init + seed (schema migration equivalent)

Schema initialisation and seeding are **automatic at startup**:

```bash
python3 - <<'PY'
from app.main import create_app
create_app("/workspace/data/issuetrack.db")   # creates schema, then seeds if empty
PY
```

- **Schema (constraint 5 "migration or equivalent schema setup"):**
  `app/db.py:DB.__init__` runs a fixed `CREATE TABLE IF NOT EXISTS …` script
  plus `CREATE INDEX IF NOT EXISTS …` for every table and index. It is
  idempotent, so "migration" is a no-op on an already-created database and no
  destructive migration path exists.
- **Seed (constraint 6 "deterministic seed-data mechanism"):**
  `app/seed.py:seed()` is now invoked by `create_app()` on a database that has
  zero users (`auto_seed=True` by default). It is a single
  `BEGIN IMMEDIATE` transaction that creates:
  - users `admin@example.com` (`admin12345`, ADMIN of the seed workspace) and
    `member@example.com` (`member12345`, MEMBER);
  - workspace `Seed Workspace`;
  - projects `Seed Project` (active) and `Archived Archive` (`archived=1`,
    to exercise the read-only-archived rule);
  - five issues covering every status and priority, including one issue due
    **yesterday** (overdue) and one due **today** (not overdue), so the
    overdue boundary rule is observable from the seeded data;
  - one comment.

  Seeding is deterministic in content but uses `secrets.token_hex(8)` for IDs
  and the current UTC second for timestamps, so IDs/timestamps differ per
  clean install while the shape of the dataset does not.

### Manual re-seed (optional)

For a full reset, or to re-apply seed users to a database that already has
data:

```bash
export IT_DB_PATH=/workspace/data/issuetrack.db
python3 app/seed.py            # idempotent: no-op if users exist
python3 app/seed.py --force    # re-create/repair seed users + workspace
```

`--force` re-creates the two demo users and the seed workspace, and re-adds
any missing seeded rows. It does **not** delete unrelated user data.

## 5. Run the test suite

```bash
cd /workspace
python3 -m pytest -q
```

Expected at RC: **56 passed, 0 failed, 0 skipped, 0 xfailed** in ~32 s.
Full detail and the honest skip accounting are in
`evidence/TEST-EXECUTION-REPORT.md`.

## 6. Start the service

```bash
cd /workspace
PYTHONPATH=/workspace IT_DB_PATH=/workspace/data/issuetrack.db python3 run.py
```

`run.py` runs `uvicorn.run(app, host="0.0.0.0", port=8000)`. The schema is
created and the seed is applied by `create_app()` before the first request.

## 7. Verify health and login (smoke checks)

```bash
# health (exactly the contract body, no extra fields)
curl -s http://0.0.0.0:8000/api/health
#      {"status":"ok"}

curl -s -o /dev/null -w '%{http_code}\n' http://0.0.0.0:8000/api/health
#      200

# login with a seeded account
curl -s -X POST http://0.0.0.0:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"admin12345"}'
#      {"token":"...","user":{"id":"...","email":"admin@example.com","display_name":"Admin User"}}
```

Second seeded account: `member@example.com` / `member12345`.

These are demo credentials for the seeded dataset only. They are documented
here because the seed data is intentionally reproducible; they are **not**
secrets that grant anything beyond the local SQLite file.

## 8. Open the browser UI

```text
http://localhost:8000/          issue list + workspace/dashboard shell
http://0.0.0.0:8000/            same app, all interfaces (contract bind)
```

Static assets are served by the same process (`/` and `/app.js`). CORS is
restricted to an explicit origin allow-list (`app/main.py:_CORS_ORIGINS`) with
`allow_credentials=False` (SEC-025); the UI is same-origin, so CORS is only
relevant to operator-side tooling.

## 9. Stop and restart (persistence check, NFR-009)

```bash
# find the server PID and stop it (do not use a broad pkill pattern)
ps aux | grep 'python3 run.py' | grep -v grep
kill <PID>

# data survives: the SQLite file (and its -wal/-shm siblings) remain in data/

# restart and confirm previously created rows are still returned
PYTHONPATH=/workspace IT_DB_PATH=/workspace/data/issuetrack.db python3 run.py &
curl -s http://0.0.0.0:8000/api/health
```

`app/db.py` opens SQLite in WAL mode with a 30 s busy timeout, so a file-based
database survives process restarts; a writer holding the DB will not corrupt
it (WAL), and readers never block on the WAL file.

## 10. One-command clean-start sequence (as verified)

```bash
cd /workspace
rm -rf data/
PYTHONPATH=/workspace IT_DB_PATH=/workspace/data/issuetrack.db python3 run.py &
sleep 5
curl -sS http://0.0.0.0:8000/api/health && echo           # {"status":"ok"}
curl -sS -X POST http://0.0.0.0:8000/api/auth/login \
     -H 'Content-Type: application/json' \
     -d '{"email":"admin@example.com","password":"admin12345"}'
```

Actual RC output:

```
{"status":"ok"}
HTTP=200  {"token":"8507d8ba2bf98cf13e81bf2395ac98d4567aa882c0320ba659e658f2e87417ed",
           "user":{"id":"b8fe70393c097aad","email":"admin@example.com","display_name":"Admin User"}}
{"items":[{"id":"4238246e0b3b815c","name":"Seed Workspace","role":"ADMIN"}]}
```

## 11. Related documents

- `evidence/ARCHITECTURE-DECISIONS.md` — stack and design decisions
- `evidence/TRACEABILITY-MATRIX.md` — requirement → test mapping
- `evidence/TEST-EXECUTION-REPORT.md` — test results and skip accounting
- `evidence/SECURITY-AUDIT-REPORT.md` — secrets scan, dependency check, findings
- `evidence/CODE-REVIEW-DISPOSITION.md` — review findings and dispositions
- `evidence/KNOWN-LIMITATIONS.md` — residual risks and known gaps
