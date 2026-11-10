# VerityAI — PayPal AI Hackathon Repository Audit

**Audit date:** 2026-11-09  
**Audited revision:** `4fec4cd` (`main`)  
**Scope:** Read-only implementation audit. The only file created by this audit is this report.

## 1. Executive Summary

VerityAI is a substantial, runnable local modular monolith: a React/Vite client talks to a FastAPI service backed by PostgreSQL; tenant-scoped document/evidence records, immutable versions, deterministic four-stage analysis, reviewer dispositions and decisions, and workspace metrics are implemented. The production frontend build passed. The backend test suite could not be collected in the available interpreter because `python-docx` is missing; no dependencies were installed.

The product direction—sell a real evidence analysis service and unlock its report after a PayPal Sandbox purchase—is a coherent commercial use of the existing workflow. It is **not implemented yet**: there are no PayPal credentials or client, order/capture/webhook APIs, purchase records, entitlements, service packages, or payment-gated report endpoint. Nor is the current analysis genuinely AI-powered: `AI_ENABLED=true` still selects the same local deterministic regular-expression extractor. This is the largest hackathon eligibility gap.

The biggest deployment/security blocker is that user identity is not authenticated. The core app accepts caller-supplied identity headers only in loopback development mode, while knowledge-document access is bound to a server-configured dev tenant and disabled outside development. That is reasonable for a local demo, but not a public multi-user checkout application. Do not expose the current development identity mechanism to judges on a public deployment.

**Recommendation:** Ready for a tightly scoped hackathon implementation, but **not submission-ready today**. Preserve the existing analysis pipeline. First choose one safe hosted identity/data-access path, integrate one genuine AI capability behind the existing stage boundary, and implement one backend-created and captured PayPal order that grants one persisted report entitlement only after server-verified capture. Keep packages, account features, webhooks, refunds, and enterprise RBAC small or deferred as indicated below. With the November 11 build target only two days away, the complete P0 scope is unlikely for one developer unless the demo workflow is cut to a single service, a controlled account/tenant, and one report type.

## 2. Repository Structure

| Area | Observed contents | Status / evidence |
|---|---|---|
| Root | `README.md`, `.env.example`, `.gitignore`, `compose.yaml`, `IMPLEMENTATION_PLAN.md` | Local setup, PostgreSQL Compose service, and project plans exist. |
| Backend | `backend/app/`, `backend/migrations/`, `backend/tests/`, requirements and lock files | FastAPI, SQLAlchemy 2, Alembic, document extraction, tenant-scoped services and PostgreSQL tests. Twelve migration files are present in `backend/migrations/versions/`. |
| Frontend | `frontend/src/`, Vite/TypeScript config, `package.json`, `package-lock.json`, `frontend/vercel.json` | React 19, TypeScript and React Router; Vercel SPA configuration exists. |
| Product docs | `docs/PRD.md`, `docs/PRODUCT_ARCHITECTURE.md`, `docs/TECHNICAL_DESIGN.md` | Product requirements and design direction exist; this audit judges implementation from code. |
| CI/CD | No `.github` workflow files found | No repository CI workflow was found. `frontend/vercel.json` is frontend hosting configuration, not CI. |
| License | No `LICENSE`, `LICENSE.md`, or equivalent root license found | Missing for the requested public open-source submission. |

Git was clean on `main` at `4fec4cd`, with the prior commit `6207a94`. The audit did not inspect a Git remote, because remote URLs can contain credentials; whether the repository is publicly accessible is therefore **unverified**.

## 3. Actual System Architecture

The code is a synchronous modular monolith, not a distributed system. `backend/app/main.py` constructs one FastAPI application and registers the knowledge document, submissions, reviews, analysis, governance and evidence routers. Feature modules hold service logic, while SQLAlchemy models are centralized in `backend/app/models.py`. `backend/app/db/session.py` and the dependency layer provide database sessions. Analysis runs synchronously inside the submission request and persists each stage at explicit transaction boundaries (`backend/app/modules/analysis/orchestrator.py:run_analysis_pipeline`).

The frontend is a single-page React app: `frontend/src/main.tsx` mounts the router, `frontend/src/App.tsx` maps `/`, `/review/:submissionId/:versionId`, `/evidence`, and `/governance`; feature pages use the shared `Navbar` and `frontend/src/api/client.ts`. Browser state/session storage carries submitted text to the review page; durable findings and decisions are fetched from APIs.

This structure is adequate for a small hackathon service. Keep payment, purchase-entitlement, and report delivery as modules in this application. There is no evidence of a workload or team boundary justifying a queue, microservice, vector database, or separate payment service for the demo.

## 4. Backend Implementation Audit

| Feature / entry point | Status | Evidence and next action |
|---|---|---|
| App and health | Implemented | `backend/app/main.py`: `app`, `/health/live`, `/health/ready`; readiness executes PostgreSQL `SELECT 1`. Preserve. |
| Tenant scope and permissions | Partially implemented | `backend/app/core/dependencies.py:get_tenant_scope`, `require_permission`: workspace membership and active role permissions are checked; identity is development headers or seeded fallback, no real authentication. Retain isolation, replace dev identity before public use. |
| Text intake and analysis | Implemented locally | `backend/app/api/v1/submissions.py:create_submission`; `backend/app/modules/submissions/services.py:create_submission_with_analysis`. Persists immutable source version, runs analysis, returns IDs and actual status. |
| PDF/DOCX intake | Implemented locally | `create_document_submission` and `create_document_submission_with_analysis`: validate, extract, store private original, create exact version and run pipeline. OCR not supported; upload/page/time limits remain product decisions despite a 10 MiB default. |
| Evidence lifecycle | Implemented in part | `backend/app/api/v1/evidence.py`: upload/list/history/review/approve/validity/inactive. `backend/app/modules/evidence/lifecycle.py` versions validity edits and requires re-approval. Conflict history/model exists, but manual conflict creation/resolution APIs are absent. |
| Knowledge documents | Implemented separately | `backend/app/documents/api.py` provides upload/list/metadata/content/chunks; `documents/service.py`, `storage.py`, `extraction.py` implement processing. This is a distinct knowledge-document feature and is not the same thing as evidence matching. |
| Analysis APIs | Implemented | `backend/app/api/v1/analysis.py:list_analysis_runs`, `list_analysis_findings`; tenant-scoped read permission. |
| Human review | Implemented | `backend/app/api/v1/reviews.py`; `backend/app/modules/reviews/services.py` validates analysis readiness, dispositions, four decisions, approval blockers, tenant and transactional audit writes. |
| Governance metrics | Implemented | `backend/app/api/v1/governance.py`; `backend/app/modules/governance/services.py:get_workspace_metrics` aggregates activity, unverified claims, recurring policy findings, decision counts, evidence attention. Metrics are workspace-level and not a paid report. |
| Payment and report sale | Missing | No PayPal SDK/client or payment/order/capture/webhook/entitlement/report-purchase routes or models found. Build one narrow flow; do not retrofit payment into unrelated governance metrics. |
| Logging/error handling | Partial | Upload APIs return structured validation errors; orchestrator records safe stage errors. No unified production logging/observability configuration was found in the inspected app. Add request IDs and safe operational logs only as needed; never log document text, tokens, secrets, or payment details. |

The API has a small feature-service structure, but repositories are not a consistent boundary: many business services issue tenant-filtered SQLAlchemy queries directly. This is manageable at present; avoid a repository rewrite under the deadline.

## 5. Frontend Implementation Audit

`frontend/src/App.tsx` has four routes: intake, review, evidence and governance. `frontend/src/components/Navbar.tsx` is shared. `frontend/src/api/client.ts` contains typed fetch wrappers, demo tenant headers, response types, and structured `ApiError` handling. Intake supports text/PDF/DOCX and displays actual extraction/analysis status (`frontend/src/features/intake/SubmissionForm.tsx`). Review fetches the latest run, findings and review eligibility; `FindingsList.tsx` links to evidence and records dispositions; `DecisionPanel.tsx` supports all four reviewer outcomes and disables approval when the API says required stages are incomplete or findings block clean approval. Governance shows five cards and clear loading/error states. Evidence repository supports listing, uploading, history and lifecycle actions.

The visual system is a dark Inkloom-inspired stylesheet in `frontend/src/styles.css`. Responsive layout rules exist, but the app has no frontend test script or component tests. There is no service selection, price/checkout page, PayPal JS SDK, payment result/status screen, report library, or transaction history. Do not redesign; add a small service selection/checkout state and a report route using the current shell and components.

**Verification:** `npm run build` passed after running outside the restricted sandbox because Vite/esbuild subprocess creation initially failed with `EPERM`. Output: TypeScript build and Vite succeeded; 49 modules transformed. No application files were edited by the build (generated `dist` is ignored).

## 6. Database and Data Model Audit

`backend/app/models.py` contains organizations/workspaces/users/memberships/roles/permissions, evidence and policy records/versions, submissions/versions/artifacts, analysis runs/stages/claims/candidates/findings/suggestions, review dispositions/decisions, audit events, and knowledge documents/chunks. Models use UUID identifiers, tenant ownership columns, composite foreign keys, checks, unique constraints, and indexes. Example: `SubmissionVersion` references its parent and membership in the same organization/workspace; `EvidenceMatchCandidate` references an exact run, claim, and evidence version. Migrations are in `backend/migrations/versions/` (12 files); no migration was created by this audit.

The existing schema is a useful base. It has no product catalog/order/payment/event/entitlement/report-access tables. For the minimum payment flow, add only a fixed service-package identifier or simple package table if there must be multiple offerings; a server-created PayPal order mapped to a local purchase; a capture/payment record with unique provider identifiers and status; an idempotently processed provider event record if webhooks are implemented; and an entitlement binding verified purchase to the analysis report/submission. Do not duplicate existing AnalysisRun/Finding data in a new report schema unless report snapshots become necessary. Add tenant-scoped composite constraints and uniqueness for provider order/capture/event identifiers. Define retention and deletion policy before collecting real customer data.

## 7. Evidence Processing Workflow

### Submission-to-finding path

`POST /api/v1/.../submissions` or `/submissions/documents` → `create_submission_with_analysis` / `create_document_submission_with_analysis` → `run_analysis_pipeline` → `extract_claims` → `retrieve_evidence_for_claims` → `evaluate_policies` → `compose_findings`. The run and stage results persist as the pipeline advances; failed stages are marked `Failed`, later stages `Not run`, and the run `Incomplete`. A source version remains durable if analysis fails after source creation.

### Documents and evidence

`backend/app/documents/validation.py:validate_document` validates extension and content signature/container, size and safe display filename. `documents/extraction.py:extract_text` uses pypdf for PDFs and python-docx for DOCX; scanned OCR is unsupported. `LocalDocumentStorage` uses generated random keys under a configured private local filesystem directory and has no public file-serving route. Hosted ephemeral filesystems would not provide reliable persistence; use persistent private storage for a hosted demo or keep the demo data synthetic and seeded. `EvidenceVersion` stores extracted text, validity and immutable version metadata; history and audit/state events are retained.

### Retrieval precision and recall

`backend/app/modules/analysis/stages/retrieval.py:retrieve_evidence_for_claims` queries only the same organization/workspace, the current evidence version, and `primary_lifecycle_state == Approved`; it then runs the deterministic eligibility check for validity, inactive state, pending reapproval and manual conflict. It matches the entire ordered normalized claim word sequence against normalized evidence title or extracted text. `_normalize_match_text` removes punctuation and normalizes case/word spacing, so the previous punctuation/line-break issue is fixed. `backend/tests/test_evidence_retrieval.py:test_relevant_approved_evidence_matches_across_pdf_punctuation_and_line_breaks` demonstrates the resume claim now matches across `259,589` punctuation and line wrapping. Other cases cover unrelated content, unapproved, expired/inactive, empty extraction, foreign tenant, and superseded versions.

This precision-oriented exact-phrase rule does not infer synonyms or partial semantic support. It can miss paraphrased but relevant evidence; it also avoids treating a resume as support for unrelated claims. Genuine AI can improve candidate ranking/interpretation, but must keep exact source/version citations and human review; it must not automatically approve claims. Contradiction detection is not a current capability: manual conflict tables/lifecycle conditions are not automatically detected by the pipeline.

### Report persistence/access

AnalysisRun, AnalysisStageResult, Finding, and candidate rows persist. APIs expose run and finding records, and the review workspace renders them. There is no separate generated report artifact, report library, paid access gate, or access audit tied to a purchase. The existing review page is the obvious initial report presentation to reuse, with entitlement checked server-side before a purchaser-only report endpoint returns it.

## 8. AI Capability Assessment

| Pipeline stage | Actual implementation | Classification / status | Minimal next action |
|---|---|---|---|
| Claim extraction | `analysis/adapters/ai_adapter.py:extract_claims` uses sentence splitting and regex for `%`, `guaranteed`, fee(s), and numbers; `AI_ENABLED` true and false both call `_structured_demo_claims`. | Deterministic/rule-based; no model API or inference; implemented but does **not** satisfy genuine AI requirement. | Connect one provider to claim extraction only, with schema validation, timeout/error-safe stage state, and a local deterministic fallback clearly labeled as fallback. Keep provider credentials server-side. |
| Evidence retrieval | `analysis/stages/retrieval.py:retrieve_evidence_for_claims` performs PostgreSQL normalized whole-phrase matching over evidence title/extracted text. | Deterministic text matching; implemented; no embeddings/vector DB. | Keep as a trusted candidate filter; optionally use AI to interpret/rank candidates after eligibility filtering. |
| Policy evaluation | `analysis/stages/policy_evaluation.py:evaluate_policies` checks active tenant policies and `prohibited_term` text rules. | Deterministic policy rules; implemented. | Preserve deterministic controls; do not delegate hard policy rules to an opaque model. |
| Finding composition | `analysis/stages/finding_composition.py:compose_findings` links claims, eligible matches and policy violations to finding rows. | Deterministic composition; implemented. | Add AI-backed explanation only if it cites the same exact claim/evidence/policy references and never changes eligibility or reviewer decision. |

No provider, prompt templates, embedding model, vector store, or external AI package was found in requirements or source. The smallest meaningful inference is structured AI claim extraction (or evidence interpretation) with a limited prompt and explicit input consent. Verify current provider pricing, quotas, model availability, structured-output support, retention and data-processing terms before choosing one; those details are time-sensitive and deliberately not selected in this audit. Send only synthetic/demo or expressly authorized content to the external provider; do not send customer documents without approval and disclosure.

## 9. Authentication and Authorization Assessment

| Concern | Finding | Action |
|---|---|---|
| Login / registration | No login or registration endpoints, password hash, password verification, session/JWT issuance, OAuth callback, or frontend auth page found. `User` comment in `backend/app/models.py` says login identifiers and credentials are outside this milestone. README states there is no API authentication. | There is no functional login to reuse. For a public app, a minimal secure backend login or a strictly isolated, server-configured single demo account is required; fake/client-only login is unacceptable. |
| Existing authorization | `get_tenant_scope` validates active organization/workspace/user membership and loads workspace permission keys; `require_permission` guards API routes. Core header identity is explicitly development-only and restricted to loopback. | Keep tenant predicates and permission gates. Do not publish the development header identity path. |
| Knowledge documents | `documents/config.py:configured_document_scope` requires `APP_ENV=development` and server-side configured tenant IDs; knowledge-document routes use this separate scope and fail closed outside development. | Public deployment cannot use these routes without replacing their development-only scope with real authenticated identity. |
| Enterprise RBAC | Roles, permissions, role assignments and permission catalogue are implemented in schema/services/seed; five enterprise roles and the approved permission catalogue are not a reason to expand this hackathon scope. | Freeze the existing model; defer administration/invitations/custom role work. Essential tenant isolation and route authorization remain P0. |
| Controlled demo possibility | A fixed tenant is seeded and frontend can use configured tenant IDs; current app has no public-safe guest token or demo identity. | A demo-only public workflow could be restricted to synthetic seeded data and read-only or isolated per-user records, but that needs a deliberate server-side design. Current loopback-only identity is not a hosted guest solution. |

## 10. Security Assessment

| Area | Evidence / status | Risk and action |
|---|---|---|
| Tenant isolation | Composite tenant foreign keys plus scope-filtered service queries and cross-tenant tests exist. | Preserve and add purchase/report tenant-isolation tests. |
| Authentication | Missing; dev identity relies on caller headers only on loopback. | Critical for public deployment. Do not enable `APP_ENV=development` on a public host. Add real authentication or a bounded server-controlled demo identity before public access. |
| File validation/access | `validate_document` strips caller paths, validates extension and PDF signature/DOCX structure, applies configured byte limit; storage uses UUID keys and private local files, no public file endpoint. | Good local controls. Ensure upload/read endpoints remain tenant-authorized; hosted deployment requires durable private storage, not public bucket access. |
| SQL injection | ORM selects and bound SQLAlchemy expressions were inspected in main paths. | No obvious string-built query injection in inspected code. Maintain parameterized SQL. |
| XSS | React renders user content as text; no `dangerouslySetInnerHTML` usage found in feature paths. | Keep rendering escaped; avoid raw HTML report rendering. |
| Secrets | `.env` is ignored; `.env.example` contains local placeholder config only. This audit did not read actual `.env` or print secrets. | Use server-only secret manager/environment variables for PayPal and AI; never put client secrets in Vite-prefixed variables. Rotate any real secret if one was ever committed. |
| CORS | `main.py` rejects `*`, uses explicit origins and no credentialed CORS. | Configure only the deployed frontend origin. CORS is not authentication. |
| Payment | No provider logic exists. | Create/capture from backend; verify capture state server-side; deduplicate IDs/events; unlock only after verified capture. Never trust browser success. |
| Privacy/logging | Safe stage error strings and no document text in orchestrator error records. | Avoid sending customer content to AI until approved; avoid document, auth, and payment secrets/content in logs. Define retention/deletion for actual uploads. |
| Audit | Append-only audit model/service and migration protections exist; review and evidence state paths emit events. No audit-read API was found. | Maintain transactionally coupled payment/entitlement audit events; do not expose audit logs without authorization. |

## 11. Testing and Reliability Assessment

There are 18 backend `test_*.py` files under `backend/tests/`, including PostgreSQL integration coverage for tenant scope/constraints, evidence lifecycle/retrieval, document ingestion, submissions/orchestration, review/dispositions, metrics, seed behavior, and analysis APIs. `backend/tests/conftest.py` requires `TEST_DATABASE_URL` or `DATABASE_URL` pointing to PostgreSQL and wraps test work in rollback-isolated transactions. Test files contain meaningful tenant and failure-path cases. No frontend test files or `test`/`lint` script are declared in `frontend/package.json`; no CI workflow was found.

**Backend execution:** `python -m pytest -q` from `backend/` was attempted. Collection stopped with 13 module import errors because the active global Python 3.14 interpreter does not have `docx` (`python-docx`). The repository setup asks for Python 3.12+ and pinned dependencies, but no project virtual environment was used. No test passed/failed assertions; the PostgreSQL suite therefore remains **unverified**, not failing on product behavior. No package was installed and no database was changed.

**Frontend execution:** `npm run build` initially encountered sandbox `spawn EPERM`; rerun with approval passed (`tsc -b && vite build`, 49 modules). This is a production compile check, not browser end-to-end testing.

Minimum new coverage: payment order creation authorization/price integrity; backend capture verification and duplicate/idempotency behavior; failed/cancelled capture never grants access; webhook signature/idempotency if webhooks ship; entitlement enforcement and cross-tenant report denial; AI structured-output validity, timeout/provider failure and no customer-data call without explicit authorization; frontend checkout cancellation/decline/retry and report locked/unlocked states. Add a repeatable clean PostgreSQL test job before submission.

## 12. PayPal Integration Readiness

### Current state

No PayPal SDK/API calls, credentials, order IDs, transactions, webhook routes, payment tables, entitlement logic, or checkout controls exist. PayPal Sandbox integration is a net-new feature. Official PayPal Checkout uses a backend-created Orders v2 order, browser approval, then backend capture; OAuth client credentials remain server-side. Follow the official [REST API authentication](https://developer.paypal.com/api/rest/authentication), [Checkout integration](https://developer.paypal.com/platforms/checkout/standard/integrate/), and [full integration example](https://developer.paypal.com/checkout/put-it-all-together/) documentation.

### Recommended narrow flow

1. Frontend selects one fixed verification package and requests an order from `POST /api/v1/purchases/orders` (or tenant-scoped equivalent). The backend loads price/package from server configuration, creates a local `PENDING` purchase, then creates the PayPal order. Never accept a browser-supplied amount as authority.
2. PayPal JS SDK presents approval. Its callback sends the provider order ID to `POST /api/v1/purchases/{purchase_id}/capture`; it does not itself unlock a report.
3. Backend validates local purchase/order relationship and captures via Orders v2. Persist provider response/status and idempotency key. Use `PayPal-Request-Id`/provider idempotency as documented in [PayPal API requests](https://developer.paypal.com/api/rest/requests/).
4. Backend independently verifies completed capture amount, currency, merchant, and order association, then atomically marks payment `VERIFIED` and creates one entitlement for the exact submission/analysis report. The report endpoint checks entitlement on every read.
5. Handle cancel/decline as `CANCELLED`/`FAILED` without entitlement. Duplicate capture requests return the durable prior result; they do not create duplicate purchases or entitlements.
6. Webhooks are valuable P1 for asynchronous state reconciliation, not necessary for a narrow synchronous sandbox demo if capture response is verified. If implemented, verify webhook authenticity, store unique event IDs, process idempotently, and return timely 2xx as described in [PayPal webhooks](https://developer.paypal.com/api/rest/webhooks) and [webhook integration](https://developer.paypal.com/api/rest/webhooks/rest/). Refunds require a corresponding reversed/disabled entitlement and audit event.

Suggested lifecycle: `PENDING → APPROVED → CAPTURED → VERIFIED → ENTITLEMENT_GRANTED`; alternatives: `CANCELLED`, `FAILED`, `REFUND_PENDING`, `REFUNDED` (and entitlement revoked). Store order and payment states separately if PayPal's order approval and capture are distinct. Never grant on `APPROVED` alone.

### Suggested code boundaries

- Backend `backend/app/modules/billing/` (or `purchases/`): configuration, PayPal OAuth token client, Orders v2 create/capture adapter, purchase service, webhook verification/processing, entitlement service.
- Routes `backend/app/api/v1/purchases.py` and optionally `webhooks.py`; schemas in the same feature module. Reuse `get_db`, authenticated tenant scope, and permission checks.
- Frontend `frontend/src/features/checkout/` for package choice and checkout state; `frontend/src/features/reports/` for locked/unlocked report route; wrappers/types in `frontend/src/api/client.ts`.
- Do not expose client secret to frontend; publish only the PayPal public client ID if the SDK requires it.

## 13. Features We Can Reuse

- Four-stage analysis, immutable submission versions, safe incomplete-state handling and stage details: `analysis/orchestrator.py`, submission services, analysis APIs.
- Evidence uploads, extraction, versioning, eligibility snapshots, audit trail and precise traceable findings.
- Review workspace and decisions/dispositions as the first useful analysis report surface.
- Existing organization/workspace tenant model, membership permissions and composite FK patterns.
- PostgreSQL models/migrations and rollback-isolated fixture style for purchases and entitlements.
- Shared React layout, dark styles, API error handling, intake/review/evidence pages, loading states.
- README's Docker/PostgreSQL/migration/seed local setup, after adding complete judge run instructions and a license.

## 14. Features That Need Modification

1. Replace development-only identity in hosted paths with safe, server-validated identity or a deliberately isolated synthetic demo mode; preserve tenant scope.
2. Connect a genuine AI provider behind claim extraction or evidence interpretation; rename/clarify `AI_ENABLED` behavior until this is done, because currently both values use the same demo function.
3. Add paid service selection and server-authoritative package/price.
4. Add backend order/capture verification, persistence, idempotency, and an entitlement gate around report APIs.
5. Make hosted original-document storage durable and private or constrain the hosted demo to seeded synthetic records; current local filesystem storage is not durable across ephemeral hosts.
6. Extend setup docs with PayPal Sandbox account/credential setup, AI config/privacy, migrations/seed, frontend config, payment testing and judge instructions.

## 15. Missing Features

- Genuine AI inference; provider settings, bounded prompts, structured-output validation.
- Service packages/pricing UI and server-side price catalog.
- PayPal Sandbox configuration, OAuth, create/approve/capture, verified payment persistence.
- Payment history/status and checkout cancel/failure UI.
- Purchase entitlement model and server-enforced report authorization.
- Optional webhook receipt/signature verification and payment reconciliation.
- Real login/registration or safe hosted demo identity; no fake login.
- Report list/download/access history; analysis findings exist, but a purchased report product flow does not.
- CI automation, frontend tests, root OSS license, and verified public GitHub visibility.
- Public deployment may exist as a plan, but this audit found frontend hosting configuration only; no `render.yaml` or backend deployment file. Actual live deployment was not verified and must not be implied.

## 16. Technical Risks and Blockers

| Priority | Risk | Why it blocks or matters | Mitigation |
|---|---|---|---|
| Critical | No authentication for public customers; current identity headers are development-only and loopback restricted. | A hosted UI cannot securely identify purchasers or isolate their private reports using the current local demo identity. | Implement minimal secure identity or a server-controlled synthetic demo flow with strict data boundaries before public hosting. Never flip development identity on publicly. |
| Critical | AI requirement is unmet. | Current `AI_ENABLED` flag is a deterministic mock, not inference. | Add one narrowly scoped real model call, prove it in a recorded demo, document data handling and safe failure. |
| Critical | No PayPal integration or entitlement gate. | Mandatory central hackathon requirement; payment callback alone must not unlock. | Implement backend order/capture verification and transaction/entitlement persistence before UI polish. |
| High | PostgreSQL test suite unverified in current runtime. | Missing `python-docx` caused 13 collection import errors before tests ran. | Use Python 3.12 project venv, install pinned dev dependencies only after approval, run against a disposable migrated PostgreSQL database. |
| High | Hosted local-file storage durability unknown. | `LocalDocumentStorage` writes to local path; ephemeral host may discard files. | Use a persistent private disk/object store or seed synthetic evidence and avoid user-upload persistence in hosted demo. |
| High | Public repo license absent and visibility unknown. | Submission asks for open-source license/source; no license file exists. | Choose an appropriate license explicitly, add it after approval, verify repo visibility and sanitized history. |
| Medium | No OCR and no page/processing-time cap. | Scanned docs fail; configured default 10 MiB does not settle PRD OPEN constraints. | Keep text PDFs/DOCX and document limits; do not claim OCR. |
| Medium | Exact phrase search favors precision over recall. | Paraphrased relevant evidence may be missed; no semantic matching. | Preserve current eligibility filter; use AI-assisted candidate interpretation with citations, not automatic verification. |
| Medium | No CI or frontend automated tests. | Regressions not caught automatically. | Add at least a minimal build/backend test pipeline if time allows. |

Unverified: deployment/account availability and terms, repository public status, current PayPal Sandbox configuration, selected AI provider and data policy, whether local PostgreSQL is currently running, browser end-to-end behavior, and whether any external secret exists outside tracked files.

## 17. Recommended Hackathon Architecture

Keep the current FastAPI + React + PostgreSQL modular monolith. Add `purchases` and `reports` as modules, with provider adapters isolated from business rules. Keep PayPal calls server-side; keep AI behind the claim-extraction/evidence-interpretation interface. Persist each purchase state and entitlement in PostgreSQL with tenant ownership and unique provider identifiers. Payment success and report entitlement should be one backend state transition, and every report API read should check that durable entitlement.

Use one backend deployment, one PostgreSQL database, and one private durable file store only if user uploads must persist. Avoid Redis, Celery, microservices and vector infrastructure before demonstrated need. A synchronous four-stage pipeline is acceptable for a short controlled demo if timeouts and `Incomplete` statuses are visible; the current approach should not be presented as scalable background processing.

For public judge access, prefer either a minimal real account (server-side password hashing, secure session cookie, CSRF protection, rate limits) or a tightly constrained synthetic demo tenancy with no customer-uploaded sensitive data and no user-selectable tenant IDs. The first is more product-like; the second may be faster but needs explicit server-side purchase/report isolation. The existing development headers are neither option.

## 18. Minimum Database Changes

Add only what the selected checkout requires:

| Structure | Minimum fields/constraints |
|---|---|
| `service_packages` (optional if one immutable server-configured package) | Stable key, display label, currency, amount in minor units, active flag; price always server-authoritative. |
| `purchases` | UUID, tenant and buyer, submission version/analysis run, package key, amount/currency snapshot, local state, unique PayPal order ID, timestamps; composite tenant FKs. |
| `payments` or capture fields on purchase | Unique capture ID, verified amount/currency/status, captured time, safe provider metadata. Separate table if multiple captures/refunds are supported. |
| `payment_events` (P1 if webhooks) | Unique provider event ID, event type, received/processed state/time, safe payload digest/reference, signature verification result. Avoid persisting unnecessary sensitive payload. |
| `report_entitlements` | Tenant, purchase ID, exact report/run/submission version, granted/revoked state/time; unique purchase+report constraint; tenant-consistent FK. |

Use DB uniqueness and transactions to prevent duplicate order/capture processing. No migration is needed for the current audited code; these are proposed future changes, not created schemas.

## 19. Minimum Frontend Changes

1. Keep current intake and review pages; label the generated analysis clearly as preview until payment.
2. Add a single service/price selection card, then PayPal JS SDK button using public client ID and backend order/capture calls.
3. Render pending, approval, capture, cancellation, decline, retry, and verified states from API responses; never infer payment from a browser callback.
4. Add a locked report state and report page/API fetch after server entitlement is confirmed.
5. Add minimal payment history only if time permits; it is P1.
6. Reuse `Navbar`, `styles.css`, loading/error states and typed wrappers in `client.ts`. Add no frontend-only auth and no mock success path.

## 20. P0/P1/P2 Implementation Roadmap

| Priority | Scope | Acceptance evidence |
|---|---|---|
| **P0** | Safe demo identity/deployment boundary; choose one package; server-side PayPal Sandbox order creation and capture; durable purchase/payment/entitlement records; server-side verification; entitlement-protected report; one genuine AI capability; essential payment/AI/tenant tests; judge setup documentation and license. | Fresh local setup succeeds; actual sandbox order captures once; invalid/cancelled/duplicate payment never grants twice; report is inaccessible before verified capture and accessible after; real model inference produces structured output or safe incomplete/error; second tenant cannot read report. |
| **P1** | Webhook reconciliation/signature verification, payment history UI, report presentation improvements, simple secure registration/login if not needed for P0 demo, refunds/revocation, additional AI explanations. | Provider event replay is idempotent; status history matches provider; refund revokes entitlement. |
| **P2** | Five-role/RBAC expansion, complex onboarding/invitations, subscriptions, advanced packages, microservices, vector database, OCR, unrelated product capabilities. | Defer; none is required to show the paid verification service. |

Do not call the checkout demo complete if the backend only trusts the PayPal browser return event or does not persist and enforce entitlement.

## 21. Development Effort Estimates

Estimate for one experienced full-stack developer, excluding provider/account setup delays and review time:

| Work | Estimate |
|---|---:|
| Hosted identity boundary + deployment data safety | 1–2 days |
| One real AI stage, schema checks, timeout/failure handling and focused tests | 0.5–1.5 days |
| PayPal Orders create/capture, verification, transaction/entitlement persistence and tests | 1.5–2.5 days |
| Checkout/report UI and payment states | 0.75–1.5 days |
| Clean database/judge instructions, license, demo rehearsal/video | 0.5–1 day |
| **P0 total** | **4.25–8.5 developer-days** |

This makes November 11 completion from November 9 an aggressive and likely unrealistic target for the full P0. A two-day cut would require an already available provider account, a single fixed package, a tightly controlled synthetic demo identity, no refunds/webhooks/payment history, minimal report presentation, and immediate access to a real AI provider. If secure public access or provider setup is not ready, prioritize a complete reproducible local demonstration rather than exposing development identity publicly. November 12 then remains for verification/video, not first integration.

## 22. Demo Workflow

1. Judge opens the public repository or follows the hosted link; README has exact setup and synthetic demo account instructions.
2. User submits synthetic campaign text or a synthetic PDF/DOCX.
3. App extracts structured claims using a visibly genuine AI capability; evidence retrieval remains tenant- and eligibility-filtered; policy findings and citations are shown.
4. User selects one verification package and sees the server-defined price.
5. PayPal Sandbox opens buyer approval; cancel/decline path is also rehearsed.
6. Backend captures and verifies the payment, shows confirmed status, and grants access to the exact analysis report.
7. User opens the report and sees claims, evidence source/version references, policy findings, analysis status, and reviewer caveat. A second synthetic tenant cannot access it.

For a sub-three-minute video, show one successful flow and one short blocked-before-payment or cancelled-payment state. Do not expose real customer documents, credentials, or payment data.

## 23. Submission Readiness Checklist

- [ ] Public source repository visibility verified without credentials in remote URL/history.
- [ ] Root open-source license selected and present.
- [ ] README includes clean local setup, PostgreSQL, migrations, seed, app startup, tests, Sandbox setup, AI configuration/privacy, and judge instructions.
- [ ] No real credentials or customer files committed; `.env` remains ignored.
- [ ] Public deployment does not enable dev header identity or development-only tenant fallback.
- [ ] Persistent private file storage is configured if uploads persist; otherwise demo is synthetic and limits are clear.
- [ ] Genuine model inference is demonstrated and failure behavior does not claim AI success falsely.
- [ ] PayPal Sandbox order and server-side capture verified; no browser-only success trust.
- [ ] Purchase/payment/entitlement persistence is idempotent and cross-tenant isolated.
- [ ] Report remains locked before verified payment and after failed/cancelled payment.
- [ ] PostgreSQL migrations and complete backend tests pass under supported Python/dependencies.
- [x] Frontend production build passes in this audit.
- [ ] Browser end-to-end flow rehearsed with Sandbox buyer account.
- [ ] Demo video is under three minutes and uses synthetic data.
- [ ] Final submission is prepared by November 13, 2026; November 11 build and November 12 verification targets remain goals, not verified facts.

## 24. Final Engineering Recommendation

**Decision: Not submission-ready yet; suitable for a narrowly scoped hackathon implementation without redesign.** The existing application provides a credible evidence-review core and the earlier retrieval defect is fixed with a regression test. The implementation currently falls short of the two differentiating mandatory requirements: genuine AI inference and central PayPal Sandbox purchase with verified, persisted, payment-gated report access. Public use is also blocked by the absence of real authentication/safe hosted demo identity, and the repository has no license.

Proceed only after agreeing the public identity/demo boundary, AI data handling/provider, and single package/report purchase scope. Implement the P0 flow in the existing modular monolith, test server verification and entitlement isolation, then use November 12 for a clean setup and a rehearsed video. Do not remove tenant boundaries, expose development identity, call deterministic regex AI, or unlock reports based on frontend messages.

**Audit boundary:** No code, dependencies, migrations, database records, application documentation, or configuration were changed. Backend test execution was attempted but is blocked at collection by missing `python-docx` in the active Python 3.14 environment. Frontend production build passed. The only file created is `PAYPAL_HACKATHON_AUDIT.md`.
