# Security and Non-Functional Requirements
Version: 0.2.0

Verification method legend: **API-TEST** = external automated API test;
**UI-TEST** = external automated browser test (tool + rule version recorded);
**REVIEW** = documented evaluator source/config review (manual, checklist);
**OBSERVE** = recorded observation, non-gating unless stated.

## Security requirements

| ID | Threat / control statement | Verification | Evidence expected | Scope / limitations |
|---|---|---|---|---|
| SEC-001 | Passwords stored with a modern adaptive hash (bcrypt/scrypt/Argon2); plaintext or reversible storage prohibited. | REVIEW (read-only source/config inspection; legitimate method — this is not black-box observable) | Hashing algorithm + parameters cited from code/config; no plaintext column | Not provable through the public API; no algorithm-level strength test |
| SEC-002 | Generic authentication failures; abuse controls on authentication endpoints. | API-TEST (AUTH-002/003), OBSERVE (TSEC-006) | Identical 401 bodies; valid login still possible after repeated failures | Abuse-control strength not quantified in MVP |
| SEC-003 | Logout invalidates sessions; session IDs/tokens never appear in URLs or logs. | API-TEST (AUTH-004/007) | Token unusable post-logout; no token in any response URL | Log inspection limited to REVIEW |
| SEC-004 | If cookie sessions are used internally: Secure/HttpOnly/SameSite attributes and CSRF protection; if bearer tokens are used on the external contract, token handling risks documented. | REVIEW + API-TEST (contract enforces bearer on external API) | Attribute values from the session config; documented token strategy | External contract is bearer-token; internal UI session cookies are REVIEW scope |
| SEC-005 | Secrets supplied via environment/secret facility; never committed to the repository. | REVIEW (repo secrets scan, evaluator-run scan report) | Clean secrets-scan report; sample env uses placeholders | Scan coverage statement required; clean scan is not proof of security |
| SEC-010 | Every protected server operation authenticates and authorizes the specific workspace/resource. | API-TEST (TEN suite, all cases paired) | 404/403 as specified for every non-member access | Only the tested surface; not exhaustive fuzzing |
| SEC-011 | Membership is checked on every read/write of workspace-owned data. | API-TEST (TEN-001..TEN-009, TEN-010) | Same as above, including list scoping | — |
| SEC-012 | Client-supplied identifiers are not proof of access; resource/workspace relationships are verified server-side. | API-TEST (TEN-003/007, TSEC-004) | 404 for cross-workspace ID confusion | — |
| SEC-013 | Assignee/comment/project/issue relationships validated against the workspace; property-level mass assignment prevented. | API-TEST (ISS-005, PRJ-008, TSEC-003) | 422 for cross-workspace assignee; immutable workspace_id; role fields ignored | — |
| SEC-014 | Server-side role enforcement: Member cannot manage membership, archive projects, or delete issues. | API-TEST (MEM-011, PRJ-003, ISS-008) | 403 responses, paired with admin success controls | — |
| SEC-015 | Last-Admin protection robust under concurrent removal/demotion. | API-TEST (MEM-008/009/010) | 409 under concurrency; workspace always retains ≥1 Admin | Concurrency tested with paired simultaneous requests, not load-level races |
| SEC-020 | Server validates and bounds all inputs per contract limits (lengths, enums, formats, IDs). | API-TEST (ISS-002/010, CON-009) | 422 with contract error shape | — |
| SEC-021 | User content rendered safely; stored/reflected XSS prevented in tested scope. | API-TEST (TSEC-001: JSON content types), UI-TEST (UI-005: payload inert in DOM) | Correct content-type headers; payload not executed in browser | API-level data storage returns payloads as data by design; rendering safety is UI scope |
| SEC-022 | Parameterized queries or safe ORM; unsafe concatenated SQL prohibited. | API-TEST (TSEC-002), REVIEW | SQLi-shaped inputs stored/returned literally; no disclosure or 5xx | Black-box probe is scoped; REVIEW adds code-level confirmation |
| SEC-023 | CSRF protection for cookie-based state-changing operations. | REVIEW (only applies if the internal UI uses cookie sessions) | CSRF token/middleware evidence or documented bearer-only session strategy | External API is bearer-token (CSRF N/A) per contract |
| SEC-024 | Errors disclose no stack traces, secrets, tokens, hashes, or internal details. | API-TEST (TSEC-005/007) | Generic error bodies; no markers | — |
| SEC-025 | Restrictive CORS; wildcard-with-credentials prohibited. | REVIEW + OBSERVE | CORS config from review | Not externally testable without a second origin harness |
| SEC-026 | Dependencies locked; available vulnerability audit run. | REVIEW | Lockfile + audit report + dispositions | Report recency recorded |
| SEC-030 | Activity records actor/action/target/workspace/timestamp. | API-TEST (ACT-001/004, CON-007) | Event shape + all canonical actions | — |
| SEC-031 | Activity not mutable through ordinary application routes. | API-TEST (ACT-003) | No mutation path returns success | — |
| SEC-032 | Business mutation and its activity event commit atomically or expose partial failure safely. | REVIEW + API-TEST (ACT-001 spot checks) | Transaction/atomicity evidence in review | Failure-injection not performed in MVP scope |
| SEC-033 | Logs omit passwords, tokens, session IDs, and unnecessary personal data; security-relevant events (failed auth, denied authz) are logged safely. | REVIEW | Log configuration/sample inspection | Residual enumeration risk documented in the evaluation contract |

## Non-functional requirements

| ID | Requirement | Verification | Evidence expected |
|---|---|---|---|
| NFR-001 | Browser usable at widths 375px and 1280px. | UI-TEST (UI-006) | Screenshots/viewport checks |
| NFR-002 | Loading, empty, success, and error states for primary workflows. | UI-TEST (UI-008) | State observations |
| NFR-003 | Keyboard-operable primary workflows with visible focus and accessible labels. | UI-TEST (UI-001/002/003/007) + manual keyboard review | Journey transcripts |
| NFR-004 | Dashboard p95 SHOULD be ≤2s for a documented dataset (10 workspaces, 50 users, 100 projects, 5,000 issues) in the documented benchmark environment with recorded methodology. | API-TEST (PERF-001) | p95 + environment + methodology metadata. This is a benchmark target, not a production SLA. |
| NFR-005 | Dashboard aggregates consistent with persisted records after successful mutation and refresh; invariant under non-UTC server process timezone. | API-TEST (DSH suite; DSH-007 under operator timezone rerun) | Exact-aggregate test results |
| NFR-006 | Documented health/readiness check. | API-TEST (CON-001, TSEC-008, RST-002) | Health endpoint evidence |
| NFR-007 | Reproducible setup, migration, seed, test, and run instructions. | REVIEW + clean-environment exercise by evaluator | Clean-environment setup log |
| NFR-008 | No paid external service required for core MVP. | REVIEW | Dependency/config review |
| NFR-009 | Data persists across process restart. | API-TEST (RST-001, operator-assisted restart) | Pre/post-restart state evidence |
| NFR-010 | Useful structured logs without secrets. | REVIEW | Log samples |

## Reference standards mapping (scoped, no compliance claim)

The following subset is what the external evaluation and review actually
cover. Citing these standards does **not** constitute compliance or
certification of the candidate.

- **OWASP ASVS 5.0.0, Level 1 subset:** V2 (authentication), V3 (session
  management), V4.2/V4.3 (object- and function-level access control),
  V5 (input validation, sanitization, mass-assignment prevention),
  V7 (error handling and logging).
- **OWASP API Security Top 10 (2023):** API1:2023 object-level authorization
  (TEN suite), API2:2023 authentication (AUTH suite), API3:2023 property-level
  authorization / mass assignment (TSEC-003), API4:2023 resource consumption
  (observed only, TSEC-006), API5:2023 function-level authorization
  (MEM/PRJ/ISS role tests), API7:2023 security misconfiguration (TSEC-005,
  REVIEW), API8:2023 misconfigured CORS (REVIEW scope).
- **NIST SSDF 1.1 (candidate-evidence-relevant practices):** PW.4.2 (secure
  reuse of well-reviewed code/dependencies), PW.5.1 (secure coding), PW.7.1
  (code review), PW.8.1 (security testing), PW.9.2 (debugging/root cause) —
  evidenced through the candidate's test, review, audit, and incident reports.
