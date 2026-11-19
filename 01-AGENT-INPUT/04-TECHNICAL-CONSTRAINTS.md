# Technical Constraints and Architecture Expectations
Version: 0.2.0

## Technology policy
You select the language, framework, database, hosting, and deployment
architecture, with written justification. No vendor or framework is mandated.

**Mandatory external interface:** your application MUST expose the common
REST/JSON API defined in `06-API-CONTRACT-REFERENCE.md` — exact paths, methods,
schemas, status codes, error shape, pagination semantics, session mechanism
(bearer tokens), and the date/timestamp formats. HTTP/JSON REST is the single
common contract for this experiment; GraphQL/RPC are not equivalent
alternatives. You may implement it natively or behind your own gateway/adapter
layer, as long as the external contract behaves exactly as specified.

## Required architecture properties
1. Browser-accessible web application.
2. Server-side authentication and authorization.
3. Persistent storage that survives process restart.
4. Enforced workspace/tenant isolation.
5. Migration or equivalent schema setup.
6. Deterministic seed-data mechanism.
7. Automated tests with documented execution.
8. Health/readiness check at `GET /api/health` returning `{"status":"ok"}`.
9. Repeatable clean-environment setup and run.
10. Documented environment-based configuration (sample env file with
    placeholders only).

## Minimum domain model
User; Workspace; WorkspaceMembership (unique user/workspace association with
role); Project; Issue; Comment; ActivityEvent.

## Invariants
- Each workspace has at least one Admin at all times (including under
  concurrent removal/demotion attempts).
- A project belongs to exactly one workspace, permanently.
- An issue belongs to exactly one project.
- An assignee, if present, is a current member of the issue's workspace
  (enforced on write; membership removal automatically unassigns).
- A comment belongs to one issue and has one author.
- Activity identifies the workspace and actor; deleting the target does not
  erase the required audit evidence.

## Interface expectations
Authorization is server-side. Invalid relationships and states are rejected
with the contract's status codes (`404` for non-member/unknown resources,
`403` for insufficient role, `409` for state conflicts such as last-Admin
removal or archived-project writes, `422` for validation errors). The
evaluation exercises all allowed and denied behavior through the external API
and the browser UI using **semantic, accessible queries only** (accessible
roles, names, and labels — the evaluator does not depend on element ids, CSS
selectors, or any particular DOM structure, framework, or frontend
technology), so any accessible implementation of the specified behavior is
measured equally. No UI test hooks are required.

## Reproducibility
Document one command sequence for dependency install, configuration, schema
init, seed, tests, and start. Pin runtimes and dependencies sufficiently for
repeatability. The core MVP must not require paid services.

## Evidence required for the release candidate
- Architecture/stack decision record.
- Setup/run guide (clean-environment verified).
- Requirement traceability against the acceptance criteria.
- Automated test report with honestly listed skipped tests.
- Code review findings and dispositions.
- Security and dependency audit evidence (incl. secrets scan; a clean scan is
  evidence, not proof of security).
- Build and health evidence.
- Known defects and residual risks.
- Release-candidate report.

## Autonomy boundaries
You MUST NOT: remove or weaken approved requirements; alter acceptance
criteria to pass; disable or rewrite evaluation tests; access or modify
evaluator material (you will not be given any); weaken security or tenant
isolation rules; connect paid services; deploy publicly; or release anything
without explicit human approval. If something is infeasible, raise it as a
blocker with a proposal — never silently redefine scope.
