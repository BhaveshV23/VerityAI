# VerityAI local development

This repository contains the VerityAI demo application: a FastAPI backend, React frontend, tenant-scoped relational foundation, document ingestion, submission analysis, evidence lifecycle, human review, and governance metrics. Identity resolution remains a local development mechanism; no external AI provider is called.

## Prerequisites

- Python 3.12 or newer
- Node.js 22.12 or newer and npm
- Docker Desktop with Docker Compose available and running

## Configure local environment

From the repository root, create your local environment file:

```powershell
Copy-Item .env.example .env
```

The example contains local-only credentials. `.env` is ignored by Git. Replace them before any non-local use; do not use the sample values in a hosted environment.

## Start PostgreSQL

```powershell
docker compose up -d postgres
docker compose ps
```

PostgreSQL listens on `127.0.0.1:5432` by default and stores data in a named local Docker volume. To stop the service while retaining data, run `docker compose down`. Use `docker compose down -v` only when you intend to delete the local database volume.

## Start the backend

Create the virtual environment if needed and install pinned dependencies:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.lock.txt
```

Use Python 3.12 or newer. The direct dependency pins live in `backend/requirements.txt`; `backend/requirements.lock.txt` records the resolved set for repeatable local setup. To refresh the lock after intentionally changing dependencies, install the updated direct requirements and regenerate the lock from the environment.

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.\.venv\Scripts\python.exe -m pip freeze | Set-Content -Encoding utf8 backend\requirements.lock.txt
```

Run FastAPI from the repository root so `.env` is loaded:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

Check liveness at `http://127.0.0.1:8000/health/live` and database readiness at `http://127.0.0.1:8000/health/ready`. Readiness runs `SELECT 1` against PostgreSQL and returns HTTP 503 if the database is not available.

## Database migrations and backend tests

Apply all Alembic migrations from the repository root after PostgreSQL is running and `.env` points to it:

```powershell
.\.venv\Scripts\alembic.exe -c backend\alembic.ini upgrade head
```

Run PostgreSQL-backed tests only after creating and migrating a dedicated database named `verityai_test`. The test fixture requires `TEST_DATABASE_URL` and rejects any database name other than `verityai_test`; it never falls back to `DATABASE_URL`.

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -c backend\pytest.ini backend\tests -q
```

The integration tests require a migrated PostgreSQL database and create synthetic rows inside rollback-isolated transactions. Set `TEST_DATABASE_URL` in the current PowerShell process to the dedicated test database URL. For migration commands, temporarily set `DATABASE_URL` to that same test URL; never point tests or test migrations at the development database.

## Submission analysis behavior

Creating a pasted-text or PDF/DOCX submission persists the immutable source/version first, then runs the four required analysis stages synchronously in the API process: claim extraction, evidence retrieval, policy evaluation, and finding composition. The response includes the submission ID, version ID, analysis run ID, and actual run status. For documents, extraction status is also returned and extracted text is retained as a derived artifact for the exact version and run. A failed required stage returns an `Incomplete` run with the failed stage and downstream stages recorded as `Not run`; the submitted source remains persisted for traceability. Claim extraction defaults to the deterministic local provider. When explicitly configured for Gemini, extracted text is sent to the Gemini API for structured claim extraction; all later verification stages remain local and deterministic.

## Gemini claim extraction

The default `AI_PROVIDER=deterministic` keeps local development and tests offline. To enable genuine Gemini claim extraction, create an API key in [Google AI Studio](https://aistudio.google.com/app/apikey) and place it in the ignored repository-root `.env` file. Set `AI_PROVIDER=gemini`, `GEMINI_API_KEY`, `GEMINI_MODEL` (defaults to `gemini-3.8-flash`), and optionally `GEMINI_TIMEOUT_SECONDS` (defaults to 30). Never put the key in `frontend/.env*` or commit it. Restart FastAPI after changing `.env`.

In Gemini mode, the claim-extraction stage sends the submitted text (or the existing document extraction output) to Google. Use this mode only for synthetic/demo content or data you are authorized to transmit to that provider. A missing key, API error/timeout, invalid response, or claim not found verbatim in the source marks claim extraction failed; there is no deterministic fallback reported as Gemini success. The adapter validates the structured response and derives offsets from exact source substrings. Evidence retrieval, tenant/lifecycle filters, policy evaluation, and finding composition continue to use the existing implementation; Gemini does not approve evidence or decide payment status.

The project venv setup from the repository root is `py -3 -m venv .venv` followed by `\.venv\Scripts\python.exe -m pip install -r backend\requirements.lock.txt -r backend\requirements-dev.txt`. Run focused, mocked Gemini tests without an API key using `\.venv\Scripts\python.exe -m pytest -c backend\pytest.ini backend\tests\test_ai_adapter.py -q`. Run the PostgreSQL-backed integration and regression tests with `\.venv\Scripts\python.exe -m pytest -c backend\pytest.ini backend\tests\test_analysis_orchestrator.py backend\tests\test_evidence_retrieval.py -q` after setting `TEST_DATABASE_URL` to a migrated PostgreSQL test database.

## PDF/DOCX submission intake

Creators can submit pasted text or upload a PDF/DOCX from the intake page. The document endpoint validates the filename extension, file signature/container, and configured byte limit; saves the original with a generated private storage key; extracts and normalizes readable text; then creates an immutable submission version and runs the same four required analysis stages synchronously. Binary source bytes are retained as the version source, while extracted text is stored as a derived artifact associated with that exact version and analysis run. An extraction failure returns a structured 4xx response and creates no submission, version, analysis run, or stored file. If analysis fails after extraction, the original and derived artifact remain traceable and the response reports the actual `Incomplete` analysis status.

The configured default upload limit is `DOCUMENT_MAX_UPLOAD_BYTES=10485760` (10 MiB), and it can be changed through the environment. This is an implementation default, not a resolution of the PRD's **OPEN** maximum file size, page-count, and processing-time decisions. No page-count cap is currently enforced. PDF/DOCX parsing is text extraction only; scanned-image OCR is unsupported. Corrupt, encrypted/unreadable, or text-empty documents are rejected. Originals are stored outside the application source tree at `DOCUMENT_STORAGE_PATH/submissions` (default root `var/knowledge-documents`) with random keys; there is no public file-serving route.

Start the local backend and frontend as described above, then choose **Upload PDF/DOCX** on the intake page. For a direct local API request, use PowerShell with the configured development tenant IDs:

```powershell
$orgId = '<organization-uuid>'
$workspaceId = '<workspace-uuid>'
$userId = '<user-uuid>'
$headers = @{
  'X-Organization-ID' = $orgId
  'X-Workspace-ID' = $workspaceId
  'X-User-ID' = $userId
}
$filePath = 'C:\path\to\synthetic-campaign.pdf' # or .docx
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/organizations/$orgId/workspaces/$workspaceId/submissions/documents" `
  -Headers $headers `
  -Form @{ file = Get-Item $filePath }
```

The response includes submission/version/run IDs, extraction status, and the actual analysis status. The intake UI passes the extracted text to the review workspace for display; analysis stage results and findings are loaded from the existing read APIs.

## Review approval readiness

`Approved` and `Approved with documented exceptions` are available only when the exact submission version has a latest analysis run in its tenant and every required stage (`claim_extraction`, `evidence_retrieval`, `policy_evaluation`, and `finding_composition`) succeeded and the run is `Succeeded`. The review API enforces this rule; the review screen also shows stage status and disables approval while the analysis is missing or incomplete. Clean `Approved` additionally requires no unresolved findings. Approval with documented exceptions still requires a rationale and a disposition with a non-empty rationale for every unresolved finding; those findings remain unresolved. `Changes requested` and `Rejected` retain their existing rationale requirements and do not require a completed analysis run.

The implementation records audit events for successful review decisions in the same transaction as their state change. Audit events for denied review attempts remain an open audit-policy question and are not recorded by this change. The supported decisions remain `Approved`, `Approved with documented exceptions`, `Changes requested`, and `Rejected`.

## Evidence lifecycle

The Evidence Repository supports the explicit `Uploaded` → `Reviewed` → `Approved` sequence, records each transition with its actor and time, and shows version and transition history. Validity edits create a new immutable evidence version; the new current version remains ineligible until explicitly re-approved. As confirmed for this implementation, superseded versions remain available to explain historical analyses and are not candidates in new analyses. Inactive is a separate condition that blocks eligibility and does not change the primary lifecycle. Only the existing `evidence.manage` permission is used; this change does not add role grants. The PRD leaves authority to clear Inactive and to create/resolve manual conflicts OPEN, so the UI does not offer those actions. Existing conflict records are visible in history and continue to block evidence eligibility while open.

## Report foundation (Milestone 1)

The backend can create an immutable, versioned report snapshot only for an exact submission version and analysis run whose overall state is `Succeeded` and whose required analysis stages all succeeded. Reviewer approval is not required; the review workflow remains independent. The snapshot preserves claims, composed findings, related evidence and policy version references, stage status, and explicit limitations. Contradictory-finding counts and calibrated confidence are not reported because the current analysis records do not provide those classifications or scores. A limited preview is projected from the stored snapshot and includes at most two finding summaries without evidence details.

The server-owned fixed price defaults to `REPORT_PRICE_AMOUNT=5.00` and `REPORT_CURRENCY=USD`. The amount is parsed as `Decimal`, must be positive and limited to cents, and only USD is currently accepted. These settings do not enable payment: this milestone adds persistence and service boundaries only. No PayPal calls, checkout API, webhook listener, entitlement-gated report endpoint, or frontend checkout are enabled yet. Any future entitlement is user-scoped and must follow independently verified PayPal capture; a pending transaction or browser redirect cannot grant access.

## Synthetic Apex demo data

After applying migrations, provision the local Apex Financial Services workspace, development member and role grants, two active example policies, and two evidence versions. The seed is idempotent and refuses to run unless `APP_ENV=development` is explicitly set in the current PowerShell process. It never runs during application startup.

From the repository root:

```powershell
$env:APP_ENV = 'development'
Push-Location backend
..\.venv\Scripts\python.exe -m app.db.seed_demo
Pop-Location
```

The command prints the synthetic record IDs as JSON. The user model has no login or email field yet, so `dev-user@apex.com` is stored as the seeded development user's display name; this does not add authentication.

## Knowledge document ingestion (Milestone 3)

The backend accepts English-language PDF, DOCX, and UTF-8 TXT documents. English is the supported input expectation; automatic language identification is not performed. It validates the extension and file contents, stores the original in a private local directory outside the application source tree, extracts text, normalizes it, and creates ordered character-offset chunks. The current pipeline runs synchronously in the API process. Document metadata, processing status, extracted text, chunk rows, and audit events are tenant-scoped in PostgreSQL. This provides an adapter boundary for replacing local storage with private object storage later. OCR, embeddings, semantic retrieval, AI, and policy/claim processing are not included.

### Local configuration

Configure these values in the ignored `.env` file:

| Variable | Purpose | Example/default |
|---|---|---|
| `DOCUMENT_STORAGE_PATH` | Private local document root; relative paths resolve from the repository root | `var/knowledge-documents` |
| `DOCUMENT_MAX_UPLOAD_BYTES` | Maximum request file size | `10485760` (10 MiB technical default; configurable) |
| `DOCUMENT_CHUNK_SIZE` | Maximum chunk width in characters | `1200` |
| `DOCUMENT_CHUNK_OVERLAP` | Character overlap between adjacent chunks | `150` |
| `DOCUMENT_TENANT_ORGANIZATION_ID` | Server-bound organization UUID | Existing local organization |
| `DOCUMENT_TENANT_WORKSPACE_ID` | Server-bound workspace UUID | Existing local workspace |
| `DOCUMENT_TENANT_MEMBERSHIP_ID` | Server-bound uploader/audit membership UUID | Existing local membership |

The development tenant bootstrap creates one local organization, workspace, operator membership, and user in a single transaction. It can be run repeatedly without creating duplicates. It refuses to run unless `APP_ENV` is explicitly set to `development` in the PowerShell process; setting it only inside `.env` is not enough. It never runs at application startup and never seeds production data.

From the repository root, run it and retain the JSON identifiers:

```powershell
$env:APP_ENV = 'development'
Push-Location backend
$tenant = ..\.venv\Scripts\python.exe -m app.scripts.bootstrap_development_tenant | ConvertFrom-Json
Pop-Location
$tenant | Format-List
```

Open the local `.env` without printing its existing values:

```powershell
notepad.exe .env
```

Add or update these lines using the corresponding values printed in `$tenant`:

```dotenv
DOCUMENT_TENANT_ORGANIZATION_ID=<organization_id>
DOCUMENT_TENANT_WORKSPACE_ID=<workspace_id>
DOCUMENT_TENANT_MEMBERSHIP_ID=<membership_id>
```

Save `.env`, then restart FastAPI so it reloads the configured tenant. From the repository root, stop the running server with Ctrl+C and start it again:

```powershell
$env:APP_ENV = 'development'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Because authentication is not part of this milestone, ingestion routes require `APP_ENV=development`, require a loopback client, and fail closed when the environment mode is unset. Tenant IDs are server-configured and are never accepted from callers. Do not expose the unauthenticated development API to a network or public deployment. The supplied upload and chunk defaults are implementation settings and do not close the PRD's OPEN product decisions about upload limits, retention, or processing targets.

After configuring those values and applying migrations, verify database/API readiness and upload synthetic documents from the repository root:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/ready
curl.exe -F "file=@C:\path\to\synthetic.txt" http://127.0.0.1:8000/api/v1/knowledge-documents
curl.exe -F "file=@C:\path\to\synthetic.pdf" http://127.0.0.1:8000/api/v1/knowledge-documents
curl.exe -F "file=@C:\path\to\synthetic.docx" http://127.0.0.1:8000/api/v1/knowledge-documents
```

Each upload returns a document ID, metadata, and processing status. Use that ID to retrieve metadata, extracted text, or ordered chunks:

```powershell
$documentId = '<document-id-from-upload-response>'
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/knowledge-documents/$documentId"
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/knowledge-documents/$documentId/content"
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/knowledge-documents/$documentId/chunks"
Invoke-RestMethod http://127.0.0.1:8000/api/v1/knowledge-documents
```

Upload errors use HTTP 413 for configured size limits, 415 for unsupported formats, and 422 for invalid or unreadable content. Processing failures retain a failed status and safe error message, clear the storage reference, and remove the original file. DOCX archive expansion is also bounded relative to the configured upload size. PDF/DOCX files without extractable text fail processing; scanned-image OCR is not supported.

To check an invalid-format failure, try a synthetic unsupported file and inspect the returned status/code:

```powershell
Set-Content -NoNewline .\unsupported.csv 'synthetic test content'
curl.exe -i -F "file=@.\unsupported.csv" http://127.0.0.1:8000/api/v1/knowledge-documents
Remove-Item .\unsupported.csv
```

The pinned ingestion dependencies are `python-multipart` for request uploads, `pypdf` for PDF text extraction, and `python-docx` for DOCX extraction. Install all runtime and development dependencies using `backend/requirements-dev.txt` as shown above.

## Start the frontend

In another terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open the local URL printed by Vite (normally `http://127.0.0.1:5173`). Build the static frontend with `npm run build` from `frontend/`.

## Local secret handling

- Keep actual values in `.env` or your shell environment; never commit secrets.
- `.env.example` is a template with local-only values, not a hosted configuration.
- Do not put credentials in frontend source or build-time variables.
- The API has no authentication; ingestion routes are disabled outside development and tenant identity is server-configured. Do not expose the unauthenticated API to a public network.
