# VerityAI Implementation Plan

## A. Document information

| Field | Value |
|---|---|
| Product | VerityAI |
| Document | Implementation Plan |
| Version | 0.1 |
| Date | 2026-11-05 |
| Status | Draft roadmap; implementation has not begun |
| PRD baseline | v0.4, Draft for product review |
| Product Architecture baseline | v0.3 |
| Technical Design baseline | v0.3, Proposed design for review |
| Intended implementer | One developer using Codex |

This plan sequences implementation under the listed baselines. It does not approve OPEN product decisions or claim the proposed deployment has been provisioned. Where a gate is unresolved, independent work may continue; the affected behavior must remain disabled or visibly incomplete.

## B. Implementation strategy

Build a modular monolith in dependency order: establish a runnable local environment and PostgreSQL persistence, secure tenant-aware domain services, then deliver one complete synthetic-data review journey. Keep backend rules and version integrity ahead of dependent screens. Integrate the React client as soon as the backend journey is stable, then finish the wider MVP requirements that follow the first demo.

The **first demonstrable vertical slice** is deliberately smaller than the complete PRD MVP. It proves one synthetic workspace, approved evidence and deterministic policy rules, pasted-text submission, immutable versioning, claim/evidence/policy analysis, explainable findings, a human decision, and retained history. PDF/DOCX, all governance metrics, broader access cases and production deployment hardening follow as Round 2 completion work; they are not reclassified as optional PRD requirements.

Use only the selected stack: Python 3.12+, FastAPI, Pydantic, synchronous SQLAlchemy 2.x, Alembic, Psycopg 3, PostgreSQL, React, TypeScript, Vite, React Router, CSS Modules/plain CSS, pytest, HTTPX, Vitest, React Testing Library, Playwright, and Docker Compose for local PostgreSQL. Keep one application process, one relational database and modular boundaries. Do not add workers, queues, vector search, OCR, microservices, or integrations in this plan.

Each milestone has a gate. The commands below describe planned verification after implementation exists; adapt exact script names to the repository's eventual package scripts. Passing a build alone is not feature verification. Use synthetic fixtures, focused automated tests, and the stated user-visible checks.

## C. Scope and priority classification

### P0 — Critical path to the first demonstrable slice

- Repository and local environment setup; FastAPI and React/Vite shells; PostgreSQL connectivity and migration path.
- Tenant-aware persistence, core modular services, and a fictional seeded organisation/workspace.
- Minimal authentication and permission grants only after the relevant product decisions are approved; keep any blocked actions disabled.
- Evidence lifecycle, versioning, eligibility and small deterministic policy rules.
- Pasted-text submission, immutable source version, persisted required analysis stages, findings and review decision history.
- A usable React workflow, synthetic-data checks, audit trail and a local end-to-end browser demonstration.

### P1 — Remaining Round 2 MVP coverage

- PDF/DOCX validation, private upload storage, extraction outcomes and limits approved before accepting files.
- Complete workspace/member and policy/evidence management behavior, all four review outcomes, revision history, and all five PRD governance metrics.
- Full tenant-isolation, authorization, database, failure-path, accessibility/usability and security checks.
- Proposed public demo deployment after provider, region, cost, privacy, storage, persistence and account prerequisites are verified.

P1 is still required MVP work. It follows the first demo to reduce integration risk and does not lower the MUST bar.

### P2 — Deferred beyond the current implementation

- Automated evidence conflict detection; automated/general policy ambiguity discovery beyond explicit deterministic collisions and the source-document scope question below; advanced claim taxonomy; disagreement analytics; OCR and additional formats/languages; image analysis; custom-role authoring; background workers/queues; vector embeddings/database; extra AI providers; external APIs, webhooks, CMS, identity integrations, monitoring, predictive analytics, and automatic publication.
- Production service levels, enterprise governance, retention/deletion/export workflows, and scale-stage infrastructure until their decisions and demonstrated need exist.

Do not implement P2 merely because architecture boundaries allow it.

## D. Milestone-based implementation roadmap

### Milestone 1 — Repository and local development foundation (P0)

1. **Objective:** Make a clean checkout reproducibly runnable for backend, frontend, and local PostgreSQL work.
2. **Features and tasks:** Confirm Python/Node/Docker availability; add locked backend and frontend dependencies when authorized; create the FastAPI and Vite React/TypeScript shells; configure Docker Compose for local PostgreSQL; add environment examples without secrets; establish formatting/lint/test commands and a concise local setup guide.
3. **Dependencies:** None. Do not pick replacements for the Technical Design stack.
4. **Expected areas:** `backend/` or the agreed Python package, `frontend/`, `compose.yaml`, lockfiles, environment example, developer README.
5. **Acceptance criteria:** Backend starts locally, frontend renders, PostgreSQL is reachable from the app, settings fail safely when required configuration is missing, no secret is committed.
6. **Tests and verification:** `docker compose config`; start services and check FastAPI health plus the Vite page; run backend import/startup check and `npm run build`.
7. **Definition of done:** A second clean local environment can follow the setup guide and reach the empty app and database health check.
8. **Do not start:** Domain endpoints, auth, uploads or AI calls before the foundation runs and configuration boundaries are reviewed.

### Milestone 2 — Persistence, tenant boundaries, and audit primitives (P0)

1. **Objective:** Establish reliable relational foundations before feature data is added.
2. **Features and tasks:** Implement SQLAlchemy entities and reviewed Alembic migrations for organisations, workspaces, users/memberships, role/permission assignments, evidence and policy records/versions, submission/version, analysis runs/stages, findings, review decisions/dispositions, and audit events as needed by the first slice. Add tenant ownership and composite parent constraints from Technical Design. Implement tenant-scoped repositories, request-scope/service primitives, transaction handling and append-only history rules. Keep schema changes grouped by domain rather than one milestone per table.
3. **Dependencies:** Milestone 1. Authentication details may remain gated; persistence can be built against explicit test tenant scopes.
4. **Expected areas:** `db/`, `models/`, `migrations/`, module repositories/services, common tenant-scope and audit utilities.
5. **Acceptance criteria:** Migrations build a fresh PostgreSQL database; parent/child tenant mismatches fail; prior source/version/event rows are not overwritten; audit writes can share a transaction with material state changes.
6. **Tests and verification:** `alembic upgrade head`; PostgreSQL-backed pytest for migrations, composite constraints, transaction rollback, immutable version references and cross-tenant query scoping.
7. **Definition of done:** Fresh and upgraded databases pass; two synthetic tenant fixtures cannot cross-reference or read one another through repository services.
8. **Do not start:** Feature endpoints that bypass tenant-scoped services or write audit history after the fact in a separate transaction.

### Milestone 3 — Seeded workspace, authentication, and minimum authorization (P0; decision-gated)

1. **Objective:** Make the demo identity and permission boundary explicit and safe.
2. **Features and tasks:** Seed a fictional organisation/workspace and controlled demo users. Implement the gated same-origin server-side session recommendation only after authentication/session decisions are approved, with CSRF for state-changing requests. Implement role-to-permission evaluation and default-deny checks using only the approved minimum grants. Add membership management and attribution where approved.
3. **Dependencies:** Milestones 1–2. Blocks user login, protected write paths, reviewer actions and public access until OPEN auth and permission questions are resolved.
4. **Expected areas:** `auth/`, `authorization/`, membership services/API, demo seed command, frontend session state.
5. **Acceptance criteria:** Unauthenticated and unauthorized requests are denied; approved actors see only their tenant/workspace data; role names are not hard-coded as permission checks; credentials and cookie/session secrets are not exposed.
6. **Tests and verification:** pytest/HTTPX session, CSRF, default-deny, membership and tenant access tests; manual check with authorized, unauthorized and logged-out users.
7. **Definition of done:** Product-approved grants are enforced server-side and all writes identify actor and workspace. If approval is pending, affected routes remain disabled and the first integrated demo is gated.
8. **Do not start:** Reviewer UI/actions or hosted demo accounts until authentication policy, reviewer eligibility and the required role grants are approved.

### Milestone 4 — Evidence lifecycle, versioning, and deterministic policy (P0)

1. **Objective:** Build the trusted inputs and deterministic checks used by the vertical slice.
2. **Features and tasks:** Register/view synthetic evidence and policies; enforce Uploaded → Reviewed → Approved; keep Inactive, Expired and Conflict-flagged independent; implement freshness-unknown disclosure, date eligibility, manual conflict recording, immutable evidence versions and exact-version post-validity-edit re-approval gate using version-linked events. Keep the revised version's pre-approval lifecycle treatment OPEN. Add policy Draft/Active/Retired versions and a small explicit terminology/messaging rule evaluator. Do not add automatic evidence conflict detection.
3. **Dependencies:** Milestones 2–3 for persistence and approved management permissions; evidence and policy core can be exercised through service tests while user grants are gated.
4. **Expected areas:** `evidence/`, `policies/`, evidence/policy APIs, eligibility and deterministic rule services, synthetic fixtures.
5. **Acceptance criteria:** Upload is not approval; only eligible Approved evidence is support; unknown freshness is disclosed but alone is not blocking; future effective, expired, inactive, conflict-flagged and gated versions are excluded with explanations; exact-version approval clears only its gate; old versions/events remain unchanged; retired/draft policies are not applied.
6. **Tests and verification:** PostgreSQL pytest for lifecycle transitions, overlapping conditions, validity boundaries, unknown freshness, exact-version re-approval and preserved history; evaluator tests for triggered/no-trigger rules and version references.
7. **Definition of done:** Eligibility is one deterministic service used by retrieval and UI; each result can be explained from its version and event snapshot.
8. **Do not start:** Claim matching or review screens that treat unapproved/ineligible evidence as approved support, or policy behavior that guesses conflict precedence.

### Milestone 5 — Immutable pasted-text submissions and document adapter (P0 then P1)

1. **Objective:** Preserve the exact submitted source and add safe extraction without mixing derived data into it.
2. **Features and tasks:** First deliver pasted English text as an immutable submission version with submitter, workspace, time and integrity reference. Add new-version resubmission after Changes requested. Then add PDF/DOCX validation and private original-file storage, supported by `pypdf` and `python-docx`; store extracted/normalized text, location and parser status as derived artifacts tied to the exact version and run. Add sensible configurable size/page/text guards only after product chooses the limits. OCR remains out of scope.
3. **Dependencies:** Milestones 1–3. Pasted text can proceed before upload limits; file uploads and deployment of uploads are blocked until limits and retention are decided.
4. **Expected areas:** `submissions/`, `documents/`, private storage adapter, source-version APIs and frontend submission form.
5. **Acceptance criteria:** Source text/file reference and checksum are never overwritten; revisions create linked versions; extracted text/status never mutate source; unsupported, unreadable, empty extraction and size errors are explicit and never reported as successful checks; files cannot be fetched publicly.
6. **Tests and verification:** pytest fixtures for text, valid/invalid PDF and DOCX, malformed/empty files, size boundaries and source checksum; authorized download check; inspect DB to verify derived artifact references exact version/run.
7. **Definition of done:** Pasted-text submission works locally; PDF/DOCX flow passes parser and privacy tests before full-input MVP claims.
8. **Do not start:** Public/non-synthetic uploads until byte/page/extracted-text limits, retention and privacy/processing notices are approved.

### Milestone 6 — Persisted analysis pipeline and findings (P0 for deterministic slice; AI gated)

1. **Objective:** Produce explainable findings while distinguishing successful no-match from incomplete analysis.
2. **Features and tasks:** Implement in-process orchestration with separate required/optional stage records. Normalize text; extract candidate claims; retrieve eligible evidence; run deterministic policies; compose findings and limitation states. Add provider-neutral AI adapter for candidate claims only for explicitly authorized synthetic data. If external AI is not authorized, use only a clearly labelled deterministic demo fallback if the product/technical owner accepts the scope seam; do not represent it as model-backed or as complete PRD claim extraction. Keep failed required stages incomplete, optional suggestion/relevance failure non-blocking, and no-match distinct from retrieval failure. Suggestions remain labelled optional output.
3. **Dependencies:** Milestones 2, 4 and 5. External provider calls are blocked pending explicit synthetic-data authorization, account/budget and privacy review. Claim-extraction completion is blocked if no approved path is available.
4. **Expected areas:** `analysis/`, AI capability adapter, structured-output schemas, document processor contract, findings API and analysis UI status components.
5. **Acceptance criteria:** Each run points to an immutable submission version and exact evidence/policy versions; all required stage outcomes persist; zero claims is a successful explicit empty result; no match is unverified, not false; failed retrieval/required checks cannot look passed; model output is validated and cannot invent source IDs; no tools or write authority are given to AI.
6. **Tests and verification:** pytest/HTTPX for stage success/failure, provider refusal/timeout/malformed output, exact spans/IDs, deterministic policy operation independent of AI when text exists, eligibility snapshots and no-match vs failure; synthetic provider smoke test only if approved.
7. **Definition of done:** A complete required-stage run creates findings and references suitable for human review, or the interface exposes a clear incomplete limitation. Optional AI outputs never determine eligibility or human decisions.
8. **Do not start:** Human approval of an incomplete required run until the PRD OPEN decision allows it; do not add a queue/worker or second provider.

### Milestone 7 — Human review, exceptions, revisions, and audit history (P0)

1. **Objective:** Make human review authoritative and preserve the full decision basis.
2. **Features and tasks:** Implement the four decisions—Approved, Approved with documented exceptions, Rejected, Changes requested. Validate clean approval has no unresolved findings; require each exception disposition and rationale; require rationale for Rejected and Changes requested. Store actor, timestamp, exact submission version/run basis, and atomic audit/disposition/decision history. Support creator resubmission as a new immutable version. Do not add reopen/admin override behavior until its OPEN decision is resolved.
3. **Dependencies:** Milestones 3, 5 and 6; approved reviewer eligibility and permission grants; required-stage completion for ordinary approval unless the OPEN incomplete-analysis rule is resolved otherwise.
4. **Expected areas:** `reviews/`, disposition and decision APIs, review history queries, audit service, creator/reviewer views.
5. **Acceptance criteria:** All four decisions apply to the exact version; exceptions retain unresolved status and rationale; unresolved findings without rationale block clean approval; revision does not alter earlier analysis, findings or decision; approval never publishes content; transaction failures leave no partial decision.
6. **Tests and verification:** PostgreSQL service tests for transitions and atomic rollback; API tests for each decision and unauthorized actors; verify chronological history and exact-version links.
7. **Definition of done:** An authorized reviewer can complete the synthetic run, and a creator can produce a new version after requested changes without erasing the prior record.
8. **Do not start:** Reopen, override, automatic publication or review-after-incomplete behavior without explicit product decisions.

### Milestone 8 — React journey and first demonstrable vertical slice (P0)

1. **Objective:** Connect the working backend into a judge-ready local workflow.
2. **Features and tasks:** Build workspace/session shell, evidence/policy setup views, pasted-text submission, processing state, finding/source/policy detail, review decisions and chronological version history. Display unknown freshness, ineligible-source explanations, missing evidence as unverified, suggestions as suggestions, and incomplete stages. Seed a fictional workspace with synthetic approved sources and deterministic policy rules.
3. **Dependencies:** Milestones 1–7. Demo login and review controls remain gated by Milestone 3 approvals. AI stage depends on Milestone 6 approval/path; otherwise label the deterministic fallback and its limits clearly.
4. **Expected areas:** `frontend/src/` routes/components/API client, responsive styles, seed/demo fixture, Playwright workflow.
5. **Acceptance criteria:** A user can move from seeded workspace through pasted content, findings and one recorded decision; exact versions and actors are visible; a fresh submission cannot be mistaken for a complete analysis; no external publish action exists.
6. **Tests and verification:** `npm run test`; `npm run build`; React Testing Library for core states; one Playwright end-to-end run from sign-in/demo entry through review decision; inspect persisted PostgreSQL history after the run.
7. **Definition of done:** Demonstrate the full vertical slice using only synthetic data, with limitations stated and tests passing. This is a demo subset, not the complete MVP.
8. **Do not start:** Declare Round 2 MVP complete or publish a public link before P1 requirements and deployment gates pass.

### Milestone 9 — Remaining MVP coverage, governance, and hardening (P1)

1. **Objective:** Complete all applicable Round 2 MUST requirements beyond the first workflow.
2. **Features and tasks:** Finish PDF/DOCX support and authorized private upload/download; complete policy/evidence/membership management and permission-aware visibility; display all four review outcomes and retained revisions; complete required findings, limitation and manual conflict experiences; implement all five descriptive governance metrics. For unverified-claim and recurring-finding dates, and evidence-attention date/state semantics, wait for product approval before period filtering. Submission/review count timestamps and review-decision trend timestamps follow PRD §16. Include distinct evidence reason counts without summing overlaps; unknown freshness is disclosed and gets a separate count only if approved. Add review-purpose notice and customer-content privacy rules.
3. **Dependencies:** Milestones 1–8. Metric outputs depending on OPEN event/as-of rules, insight visibility/aggregation permissions, upload limits, retention, data notice and authentication remain blocked until resolved; unrelated metrics and domain work may proceed.
4. **Expected areas:** Governance module/API/UI; remaining evidence, policy, membership and file handling; security/privacy copy and tests.
5. **Acceptance criteria:** FR-001–FR-017, FR-020–FR-024 and FR-027–FR-038 are implemented and acceptance criteria AC-001–AC-031 pass where applicable. All five metrics include period/data context, exact recurrence threshold of two, correct overlap semantics and approved date/state rules. Required extraction/analysis failures are visible; access, privacy, audit and version history meet PRD.
6. **Tests and verification:** Full PostgreSQL migration/integration suite; pytest/HTTPX API and authorization tests; cross-org/workspace isolation tests; stage failure/retry visibility tests; metric fixtures including repeated versions, duplicate matches and overlapping evidence conditions; `npm run test`; Playwright end-to-end for text and document workflows.
7. **Definition of done:** Traceability matrix in Section G has no uncovered MVP MUST or AC; all OPEN-dependent features are approved or explicitly disabled and listed as unresolved before any completeness claim.
8. **Do not start:** Broad availability, accessibility, export/deletion, custom analytics, advanced search, or future integrations; these are next-stage or OPEN and outside this MVP completion milestone.

### Milestone 10 — Proposed public deployment and submission readiness (P1)

1. **Objective:** Make the synthetic demo reachable through the proposed same-origin topology and verify it after deployment.
2. **Features and tasks:** Build one container image with Vite assets served by FastAPI; configure the proposed Render web service, managed PostgreSQL and private R2 upload bucket; set environment secrets; disable public bucket access; run Alembic migrations as a controlled release step; seed/rotate controlled synthetic demo account and data; configure health checks and verify database/object persistence and backup behavior. Do not use local Compose as the deployed demo.
3. **Dependencies:** Milestone 9; approved account access, plan/cost, region, privacy/data-processing terms, storage setup, retention/backup expectations, auth policy, AI authorization and file limits. An equivalent host is allowed only under the Technical Design's same topology/security requirements and after approval.
4. **Expected areas:** Container/deployment configuration, host environment settings, migration/seed release instructions, health checks, deployment checklist.
5. **Acceptance criteria:** Public app and API share one origin; TLS/session/CSRF checks pass; uploads remain private and authorized; no secrets or customer data are present; synthetic demo works after restart/release; migration and backup/persistence behavior are documented. No production-readiness claim.
6. **Tests and verification:** Production frontend build; `alembic upgrade head` against hosted DB as controlled operation; smoke-test health/readiness, login, submit, analyze, review, reload/history, private upload/download and access denial; verify no public object URL; confirm app logs exclude content/secrets.
7. **Definition of done:** A reachable demo link passes the deployed smoke workflow and the Round 2 handoff checklist below is complete. Availability is not claimed beyond the verified demo.
8. **Do not start:** Public exposure until security, access, cost, region, privacy, persistence and provider gates have been reviewed. Do not upload customer content.

## E. First demonstrable vertical slice

The slice is one complete synthetic workflow, not the full MVP:

1. Seed a fictional organisation/workspace with a controlled demo identity and only approved minimum permissions.
2. Register a few synthetic evidence records; move them explicitly through Uploaded → Reviewed → Approved. Include one eligible source and, if useful to the demonstration, one visibly ineligible source.
3. Seed a small deterministic policy set with versioned terminology/messaging rules.
4. Submit pasted English text and preserve its exact contents, checksum/integrity reference, submitter, workspace, timestamp and immutable version.
5. Extract candidate claims through the authorized synthetic-data AI adapter when approved. Otherwise use a visibly labelled deterministic demonstration fallback, if accepted, and disclose that this does not establish the full AI claim-extraction requirement.
6. Retrieve only eligible evidence, record eligibility reasons and snapshots, run deterministic policy checks, and distinguish unverified no-match from failed retrieval.
7. Show explainable findings and analysis state, including incomplete checks, unknown freshness and non-proof caveats. Suggestions are optional, labelled, and not verification.
8. Let an authorized human record one of the four supported decisions; for an exception decision, retain disposition and rationale for each unresolved finding.
9. Show exact content version, analysis run, evidence/policy version references, reviewer, timestamp, decision and audit history after reload.

**The demo can demonstrate:** tenant-scoped synthetic workflow, immutable submission history, evidence eligibility, deterministic checks, visible uncertainty, stage status, human authority and traceable decision history.

**The demo cannot claim:** customer-data readiness; factual or legal certification; automated evidence-conflict discovery; complete AI claim-extraction coverage when using a fallback; complete PDF/DOCX/MVP coverage before Milestone 9; production reliability; or availability beyond the verified demo deployment.

## F. Open decisions and implementation gates

| Decision requiring approval | Blocks | Independent work that can continue |
|---|---|---|
| Authentication/session policy, account bootstrap, identity scope, session/CSRF details (PRD §§11, 19, 24; TD §§3, 18) | Milestone 3 login and protected demo; Milestone 10 public access | Schema, tenant-scoped services under test principals, local UI shells and non-protected development checks |
| Role grants, reviewer eligibility, creator visibility, multi-role behavior, administrator override/reopen/correction policy (PRD §§5, 11, 15, 24; TD §18) | Membership grants, review decisions, visibility rules, public demo account | Permission vocabulary, default-deny service boundaries, UI placeholders and tests for deny behavior |
| Evidence metadata additions, authority to clear Inactive, manual conflict rationale/resolution authority, and revised-version pre-approval lifecycle treatment (PRD §§12, 24; TD §§5–6) | Final evidence edit/condition UI and any lifecycle presentation that depends on the revised version's state | Immutable version/event model, upload lifecycle, deterministic eligibility gate, and explicit post-edit approval; keep the unresolved lifecycle value undisplayed/unspecified |
| MVP policy categories/rule types, applicability/precedence/effective dates and policy approval/conflict ownership (PRD §§13, 24; Architecture §2; TD §§5, 18) | Final policy authoring/evaluation behavior and handling of conflicting configured rules | Generic versioned policy records and evaluator contract; seed only an explicitly approved small demo rule set |
| Finding attention-level meaning; mandatory-human-review content; claim/finding edit, dismiss or reclassify rules (PRD §§14–15, 24; TD §§11, 18) | Final labels, enforcement of mandatory review and any editing/disposition controls | Preserve original automated findings and human notes/dispositions; avoid risk scoring or unapproved edit actions |
| Whether reviewer may proceed when required analysis is incomplete (PRD §15; Architecture §4; TD §§10–11) | Approval of incomplete runs | Successful complete-run path and incomplete-state display |
| External AI use for synthetic demo, notice and provider/data terms; no customer content without authorization (PRD §§17, 19, 24; TD §§3, 8, 18) | Provider-backed claim extraction and any external call | Adapter contracts, deterministic tests, non-provider domain work; fallback only as explicitly labelled demo mode |
| Max upload bytes/pages/text and processing time; retention and deletion/data handling (PRD §§12, 18–19, 24; TD §§9, 12, 18) | Exposed PDF/DOCX upload, hosted file storage and user content | Pasted-text path, parser unit fixtures with bounded synthetic inputs, private storage interface |
| Governance visibility/underlying-record access and unresolved metric date/state semantics (PRD §§11, 16, 24; TD §§13, 18) | Protected insight access; period-filtered unverified claims, recurring findings and evidence-attention metrics | Submission/review counts with defined timestamps, metric query structure and synthetic fixtures |
| Whether unknown freshness has its own attention count (PRD §16; TD §§13, 18) | Final evidence-attention display count | Show unknown freshness in evidence/review context as already required |
| Role eligibility for insight access and underlying records; aggregation privacy (PRD §§11, 16, 24; TD §§13, 18) | Enabling governance screens for user roles whose access is unsettled | Metric calculation tests and approved role-neutral internal query services |
| Product owner, notice wording, security/retention/residency requirements, and demo provider account/plan/region/cost/privacy terms (PRD §§1, 19, 24; TD §§12, 15, 18) | Public demo sign-off and customer-data use | Local synthetic-data work that does not make external calls |

Do not resolve an OPEN item by picking the easiest implementation. Record the decision and its approver before enabling affected behavior. Product decisions that block one milestone do not stop unrelated local development.

## G. Testing and quality gates

### Gates between milestones

- **Persistence gate:** migrations apply to a new PostgreSQL database; constraints and rollback tests pass; tenant ownership is enforced by scoped queries and relational keys.
- **Domain gate:** lifecycle, version, eligibility, deterministic policy, review and audit services pass focused PostgreSQL-backed tests before routers/screens depend on them.
- **Failure gate:** required stages persist Failed/Not run and keep the overall run incomplete; successful empty/no-match is not confused with failure; optional stage failure does not invalidate successful required stages.
- **Security gate:** default-deny authorization, CSRF/session tests once approved, cross-tenant denial, private file authorization, and no content/secrets in logs.
- **UI gate:** React tests cover loading, empty, success, limitation, failure and unauthorized states. Accessibility and understandable error checks remain part of review; no unsupported target is invented.
- **Integration gate:** one Playwright end-to-end workflow covers the P0 slice; later extend coverage to document intake and complete review cycle.
- **Deployment gate:** built assets, controlled migration, health checks, synthetic seed, private object access and deployed review workflow pass before sharing the link.

### Minimum verification set

- Backend unit/service tests with pytest; FastAPI/HTTPX endpoint tests.
- PostgreSQL migration, constraint, transaction and query tests. SQLite-only verification is insufficient for tenant integrity.
- Evidence eligibility/versioning tests including missing freshness, validity boundaries, exact-version re-approval and historical snapshot immutability.
- Analysis-stage tests for success, empty result, dependency skip, parser/provider failure, timeout and safe error display.
- Review workflow tests for all four decisions, exception disposition/rationale, exact-version decisions, revision history and atomic rollback.
- Authorization and tenant-isolation tests across at least two organisations and workspaces, including search, download and metrics.
- Frontend Vitest/React Testing Library tests and one Playwright browser journey.
- Deployment smoke tests against the actual public demo configuration; these verify the demo only, not production service levels.

Do not record a gate as passed until the command/check has actually run and its result is reviewed. Suggested commands after project setup: `pytest`; `alembic upgrade head`; `npm run test`; `npm run build`; and the agreed Playwright test command. Keep exact commands in the development guide when package scripts are created.

### PRD traceability: MVP MUST requirements

| Requirement group | Planned milestone(s) | Coverage note |
|---|---|---|
| FR-001–FR-004 workspace scope, membership, denial, actor/time | 2–3, 7–9 | Tenant structure in M2; approved membership/auth behavior in M3; complete audit coverage in M7/M9. |
| FR-005–FR-008 evidence/policy management, lifecycle, version basis | 2, 4, 9 | P0 evidence/policy path in M4; complete management and retained review snapshots in M9. |
| FR-009–FR-017 intake, claim/evidence/policy analysis, findings/suggestions | 4–6, 8–9 | Pasted-text slice first; PDF/DOCX and full feature coverage complete in M5/M9. |
| FR-020–FR-024 decisions, resubmission, history and governance insights | 7–9 | Review/history P0; all five metrics complete in M9 after metric gates. |
| FR-027–FR-029 authorization, visibility and action audit | 2–3, 7–9 | Permission framework precedes views; OPEN visibility/grants block affected behavior. |
| FR-030–FR-034 decision record, exact version, transitions, no publication | 7–8 | Decision service and workflow tests; no publication endpoint/action. |
| FR-035–FR-038 five metrics, period context, recurrence threshold and no mutation | 9 | Required P1 completion; unresolved date/state semantics explicitly gate dependent outputs. |
| NFR-001–NFR-008 privacy, safety, explainability and failure behavior | 3–9 | Map each to applicable API/UI/security tests; exact source acceptance criteria AC-024, AC-026, AC-029, AC-031 included. |
| NFR-010–NFR-014 tenant separation, audit, stage status, immutability, document errors | 2, 5–7, 9 | Database, analysis, and document validation gates. |
| NFR-017–NFR-023 access, purpose notice, AI/data use, provenance, no certification, human review, no publication | 3, 6–10 | Provider and notice gates remain OPEN; privacy and no-publication UX is tested before release. |

### PRD acceptance-criteria mapping

| Acceptance criteria | Milestone(s) |
|---|---|
| AC-001–AC-002 (pasted source integrity; PDF/DOCX extraction and limitations) | 5, 9 |
| AC-003–AC-005 (matches, unverified, independent conditions, freshness) | 4, 6, 8–9 |
| AC-006–AC-007 (deterministic policy and labelled suggestion) | 4, 6 |
| AC-008 (deny unauthorized evidence/policy edits; audit scope remains gated) | 3–4, 9 |
| AC-009–AC-011 (four decisions, exact version, no publication) | 7–8 |
| AC-012 (period/data context) | 9 |
| AC-013 (ambiguous/conflicting policy basis) | 4, 9; see source-scope seam in Section I |
| AC-014–AC-017 (manual conflicts, version/audit, upload lifecycle, validity gate) | 4, 5, 9 |
| AC-018–AC-019 (documented exceptions and blocked unsupported approval) | 7–8 |
| AC-020–AC-021 (five metrics, period/counting, zero/recurrence threshold) | 9 |
| AC-022–AC-023 (tenant isolation, membership and roles) | 2–3, 9 |
| AC-024–AC-026 (finding quality, policy lifecycle, run/source separation) | 4–6, 9 |
| AC-027–AC-028 (human disposition and editable labelled suggestion) | 6–7, 9 |
| AC-029–AC-031 (role access/notice, complete audit/provenance, customer data/model use) | 3, 7, 9–10 |

No MVP requirement is classified as P2. OPEN decisions are gates rather than exclusions. The traceability check is complete at planning level; implementation and acceptance tests still need to prove each mapping.

## H. Deployment and submission readiness

### Proposed deployed topology

- Build Vite/React static assets into the same FastAPI web-service image and serve the SPA and `/api/v1` from one origin.
- Use the proposed Render web service and managed PostgreSQL, plus private Cloudflare R2 storage for deployed uploads. Verify account access, plan/cost, supported region, persistence/backups, privacy/data-processing terms and file limits before provisioning. Provider selection remains proposed until those checks and approvals are complete.
- Keep Docker Compose for local development only. Do not treat a local URL or local upload directory as the public demonstration deployment.
- Use host-managed environment secrets; never put credentials in Git or frontend build variables. Rotate seeded demo credentials before sharing the link.
- Run reviewed Alembic migrations once as a controlled release operation. Seed only fictional organisation/workspace data and synthetic evidence/content. Disable external AI unless synthetic-data use has explicit authorization.
- Configure liveness/readiness checks; verify app/database restart behavior and object privacy. Do not claim backups or persistence until the selected plans are checked.

### Round 2 submission checklist

- [ ] Public deployed demo link reachable; successful smoke workflow verified and limitations stated.
- [ ] Repository link and a clean, understandable README/setup guide.
- [ ] Supporting Drive link with the required demo/supporting material, if required by the submission format.
- [ ] Completed features listed against the PRD; distinguish complete MVP from any demo-only subset.
- [ ] Technology list matches the implemented stack and Technical Design decisions.
- [ ] Changes from Round 1 summarized accurately.
- [ ] Known issues, OPEN decisions, incomplete requirements and limitations disclosed.
- [ ] Three Round 3 improvements identified without implying they shipped: richer policy authoring/ambiguity workflows; better evidence matching/conflict/freshness handling; expanded governance analysis and integrations/operational controls (choose and describe the actual three delivered as proposals).
- [ ] No customer data, public uploads, exposed secrets, or unapproved AI processing in the demo.

## I. Risks and time management

### Highest risks and likely bottlenecks

- **Unresolved authorization decisions:** account/session setup and reviewer grants can stall end-to-end access. Resolve early; meanwhile continue domain tests under non-production test scopes.
- **AI authorization and output quality:** external calls can add latency, cost and privacy risk; structured output still requires validation. Keep claim spans and candidate IDs validated, never allow the model to make eligibility or review decisions, and keep the provider adapter replaceable.
- **Document safety and limits:** parser behavior, upload size, retention and private storage are separate concerns. Do not expose file upload until limits/privacy/retention gates close; pasted-text P0 can proceed.
- **Exact evidence version re-approval:** keep record lifecycle, version pointer, version-linked events, eligibility gate and historical analysis snapshots distinct. Test the validity-edit case before review screens depend on it.
- **Governance semantics:** all five metrics are MVP MUST, but some event dates/state snapshots are OPEN. Build metric source queries and fixtures, but do not ship period semantics by assumption.
- **Public demo operations:** storage privacy, database persistence, backup behavior, region, account access, cost and secrets need real verification. Keep a deploy smoke checklist and synthetic-only data.
- **Solo integration time:** the complete MVP is materially broader than the vertical slice. Reserve time for end-to-end integration and fixes rather than polishing optional suggestions or styling early.

### Simplify first when time is limited

1. Keep evidence/policy fixtures small and deterministic; reduce seeded examples, not lifecycle rules or required outputs.
2. Defer optional suggestion generation and optional AI relevance selection; preserve their labelled/optional status.
3. Keep the first UI plain and limited to the critical journey; do not remove required states, explanations, or version history.
4. Demonstrate pasted text first; do not claim full input coverage until PDF/DOCX is validated and safe.
5. Keep the public demo synthetic-only and disable external AI if its authorization gate is unresolved. If a deterministic fallback is approved for demonstration, identify it as a fallback and do not call it provider-backed claim extraction.
6. Do not simplify by skipping MUSTs, tenant checks, private uploads, required analysis failure states, audit history, exception rationale, or any governance metric. If one is unfinished, report the MVP as incomplete.

### Source-document scope seams to carry forward

- PRD §8 keeps MVP policy ambiguity handling narrow: manually flagged ambiguity or explicit deterministic rule collisions; FR-019 broad automatic policy ambiguity/conflict identification is next release. AC-013 also describes surfacing an ambiguous/conflicting policy basis as an MVP acceptance criterion. Product/design review should confirm AC-013 is satisfied by only the narrow §8/Technical Design behavior. Until clarified, implement deterministic collisions and manual flags only; do not add general automated ambiguity detection.
- The vertical-slice task allows a clearly identified deterministic claim-extraction fallback when synthetic AI is unauthorized, while Technical Design §§3, 8, and 18 say disable external AI and report dependent stages incomplete if authorization is absent. Treat the fallback as a demo-only exception requiring explicit acceptance; it does not satisfy the full AI claim-extraction requirement or alter the incomplete-stage rule for ordinary MVP operation.
- PRD §12 and Technical Design §5 leave the revised evidence version's primary lifecycle treatment before explicit re-approval OPEN. Preserve the exact-version eligibility gate; do not infer a lifecycle transition.

These seams are not silently resolved by this plan. Record approvals or resulting product-document changes before implementing behavior that would choose beyond the current rules.
