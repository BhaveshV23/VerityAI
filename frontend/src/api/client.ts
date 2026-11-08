export type SubmissionResult = {
  submission_id: string;
  version_id: string;
  current_status: string;
  analysis_run_id: string;
  analysis_status: 'Running' | 'Succeeded' | 'Incomplete';
  extraction_status: 'Not required' | 'Succeeded';
  extracted_text: string | null;
};

export type ReviewDecision =
  | 'Approved'
  | 'Approved with documented exceptions'
  | 'Changes requested'
  | 'Rejected';

export type FindingDisposition = {
  finding_id: string;
  disposition: FindingDispositionKind;
  rationale: string;
};

export type FindingDispositionKind = 'resolved' | 'not_applicable' | 'acknowledged' | 'disputed';

export type HumanDisposition = {
  id: string;
  organization_id: string;
  workspace_id: string;
  finding_id: string;
  sequence_number: number;
  analysis_run_id: string;
  submission_version_id: string;
  reviewer_membership_id: string;
  disposition: FindingDispositionKind | string;
  rationale: string;
  created_at: string;
};

export type FindingResolution = {
  finding_id: string;
  original_is_unresolved: boolean;
  effective_disposition: string | null;
  resolution_status: 'open' | 'resolved' | 'acknowledged' | 'disputed' | 'legacy_unrecognized';
  blocks_clean_approval: boolean;
  disposition_history: HumanDisposition[];
};

export type FindingDispositionPayload = {
  analysis_run_id: string;
  submission_version_id: string;
  disposition: FindingDispositionKind;
  rationale: string;
};

export type ReviewEligibility = {
  submission_version_id: string;
  analysis_run_id: string | null;
  analysis_status: 'Running' | 'Succeeded' | 'Incomplete' | null;
  can_clean_approve: boolean;
  can_approve_with_exceptions: boolean;
  clean_approval_reason: string | null;
  exception_approval_reason: string | null;
  blocking_finding_ids: string[];
};

export type ReviewDecisionPayload = {
  decision: ReviewDecision;
  rationale?: string;
  dispositions?: FindingDisposition[];
};

export type ReviewDecisionResult = {
  id: string;
  organization_id: string;
  workspace_id: string;
  submission_version_id: string;
  reviewer_membership_id: string;
  decision: ReviewDecision;
  rationale: string | null;
  created_at: string;
};

export type AnalysisStageResult = {
  stage_key: string;
  state: 'Not started' | 'Running' | 'Succeeded' | 'Failed' | 'Not run';
  is_required: boolean;
  safe_error_code: string | null;
  safe_error_message: string | null;
  dependency_reason: string | null;
};

export type AnalysisRunResult = {
  id: string;
  submission_version_id: string;
  run_number: number;
  overall_state: 'Running' | 'Succeeded' | 'Incomplete';
  started_at: string;
  completed_at: string | null;
  stage_results: AnalysisStageResult[];
};

export type AnalysisFinding = {
  id: string;
  analysis_run_id: string;
  submission_version_id: string;
  claim_id: string | null;
  category: string;
  attention_label: string | null;
  explanation: string;
  policy_id: string | null;
  policy_version_id: string | null;
  evidence_record_id: string | null;
  evidence_version_id: string | null;
  is_unresolved: boolean;
  resolution_status: FindingResolution['resolution_status'];
  effective_disposition: string | null;
  blocks_clean_approval: boolean;
  disposition_history: HumanDisposition[];
};

export type GovernanceMetrics = {
  period_days: number;
  submissions_count: number;
  review_decisions_count: number;
  unverified_claims_count: number;
  recurring_policy_findings: { policy_version_id: string; count: number }[];
  review_decision_trends: Record<ReviewDecision, number>;
  evidence_attention: {
    awaiting_review: number;
    inactive: number;
    expired_versions: number;
    conflict_flagged_versions: number;
  };
};

export type EvidenceItem = {
  id: string;
  version_id: string | null;
  title: string | null;
  primary_lifecycle_state: 'Uploaded' | 'Reviewed' | 'Approved';
  is_inactive: boolean;
  valid_from: string | null;
  valid_until: string | null;
  freshness_unknown: boolean;
  is_expired: boolean;
  not_yet_valid: boolean;
  is_eligible: boolean;
  eligibility_reasons: string[];
  created_at: string;
  version_created_at: string | null;
  version_number: number | null;
  is_current_version: boolean;
  pending_reapproval: boolean;
  has_open_manual_conflict: boolean;
  available_actions: ('review' | 'approve' | 'mark_inactive' | 'update_validity')[];
};

export type EvidenceStateEvent = {
  id: string;
  version_id: string | null;
  event_type: string;
  old_value: string | null;
  new_value: string | null;
  reason: string | null;
  actor_membership_id: string;
  occurred_at: string;
};

export type EvidenceConflict = {
  id: string;
  state: 'open' | 'resolved';
  version_ids: string[];
  rationale: string | null;
  resolution_rationale: string | null;
  created_at: string;
  resolved_at: string | null;
};

export type EvidenceHistory = {
  evidence: EvidenceItem;
  versions: EvidenceItem[];
  lifecycle_events: EvidenceStateEvent[];
  conflicts: EvidenceConflict[];
};

export type EvidenceUploadPayload = {
  file: File;
  title: string;
  valid_from?: string;
  valid_until?: string;
};

const env = (import.meta as ImportMeta & { env: Record<string, string | undefined> }).env;

export const demoTenant = {
  organizationId: env.VITE_ORGANIZATION_ID ?? '',
  workspaceId: env.VITE_WORKSPACE_ID ?? '',
  userId: env.VITE_USER_ID ?? '',
};

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

function tenantHeaders(): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (demoTenant.organizationId && demoTenant.workspaceId && demoTenant.userId) {
    headers['X-Organization-ID'] = demoTenant.organizationId;
    headers['X-Workspace-ID'] = demoTenant.workspaceId;
    headers['X-User-ID'] = demoTenant.userId;
  }
  return headers;
}

function identityHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  if (demoTenant.organizationId && demoTenant.workspaceId && demoTenant.userId) {
    headers['X-Organization-ID'] = demoTenant.organizationId;
    headers['X-Workspace-ID'] = demoTenant.workspaceId;
    headers['X-User-ID'] = demoTenant.userId;
  }
  return headers;
}

async function requestJson<TResponse>(path: string, method: 'GET' | 'POST', body?: unknown): Promise<TResponse> {

  const response = await fetch(path, {
    method,
    credentials: 'same-origin',
    headers: tenantHeaders(),
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });

  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    try {
      const payload = (await response.json()) as {
        detail?: { error?: { message?: string } } | string;
      };
      if (typeof payload.detail === 'string') message = payload.detail;
      else if (payload.detail?.error?.message) message = payload.detail.error.message;
    } catch {
      // Keep the HTTP status message when the server response is not JSON.
    }
    throw new ApiError(message, response.status);
  }

  return (await response.json()) as TResponse;
}

function tenantPath(): string {
  if (!demoTenant.organizationId || !demoTenant.workspaceId) {
    throw new ApiError(
      'Set VITE_ORGANIZATION_ID and VITE_WORKSPACE_ID in the frontend environment to use the demo API.',
      0,
    );
  }
  return `/api/v1/organizations/${encodeURIComponent(demoTenant.organizationId)}/workspaces/${encodeURIComponent(demoTenant.workspaceId)}`;
}

export function createSubmission(submittedText: string): Promise<SubmissionResult> {
  return requestJson<SubmissionResult>(`${tenantPath()}/submissions`, 'POST', {
    source_type: 'text',
    submitted_text: submittedText,
  });
}

export async function createDocumentSubmission(file: File): Promise<SubmissionResult> {
  const form = new FormData();
  form.append('file', file);
  const response = await fetch(`${tenantPath()}/submissions/documents`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: identityHeaders(),
    body: form,
  });
  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    try {
      const payload = (await response.json()) as {
        detail?: { error?: { message?: string }; message?: string } | string;
      };
      if (typeof payload.detail === 'string') message = payload.detail;
      else if (payload.detail?.error?.message) message = payload.detail.error.message;
      else if (payload.detail?.message) message = payload.detail.message;
    } catch { /* Keep the HTTP status message when the response is not JSON. */ }
    throw new ApiError(message, response.status);
  }
  return (await response.json()) as SubmissionResult;
}

export function createReviewDecision(
  versionId: string,
  payload: ReviewDecisionPayload,
): Promise<ReviewDecisionResult> {
  return requestJson<ReviewDecisionResult>(
    `${tenantPath()}/submission-versions/${encodeURIComponent(versionId)}/review-decisions`,
    'POST',
    payload,
  );
}

export function recordFindingDisposition(
  findingId: string,
  payload: FindingDispositionPayload,
): Promise<{ disposition: HumanDisposition; finding_resolution: FindingResolution }> {
  return requestJson(
    `${tenantPath()}/findings/${encodeURIComponent(findingId)}/dispositions`,
    'POST',
    payload,
  );
}

export function getReviewEligibility(versionId: string): Promise<ReviewEligibility> {
  return requestJson(
    `${tenantPath()}/submission-versions/${encodeURIComponent(versionId)}/review-eligibility`,
    'GET',
  );
}

export function getAnalysisRuns(versionId: string): Promise<AnalysisRunResult[]> {
  return requestJson<AnalysisRunResult[]>(
    `${tenantPath()}/submission-versions/${encodeURIComponent(versionId)}/analysis-runs`,
    'GET',
  );
}

export function getAnalysisFindings(runId: string): Promise<AnalysisFinding[]> {
  return requestJson<AnalysisFinding[]>(
    `${tenantPath()}/analysis-runs/${encodeURIComponent(runId)}/findings`,
    'GET',
  );
}

export function getGovernanceMetrics(): Promise<GovernanceMetrics> {
  return requestJson<GovernanceMetrics>(`${tenantPath()}/governance-metrics`, 'GET');
}

export async function getEvidence(): Promise<EvidenceItem[]> {
  return requestJson<EvidenceItem[]>(`${tenantPath()}/evidence`, 'GET');
}

export async function uploadEvidence(payload: EvidenceUploadPayload): Promise<EvidenceItem> {
  const form = new FormData();
  form.append('file', payload.file);
  form.append('title', payload.title);
  if (payload.valid_from) form.append('valid_from', payload.valid_from);
  if (payload.valid_until) form.append('valid_until', payload.valid_until);
  const response = await fetch(`${tenantPath()}/evidence`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: identityHeaders(),
    body: form,
  });
  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    try {
      const payload = (await response.json()) as { detail?: { message?: string; error?: { message?: string } } | string };
      if (typeof payload.detail === 'string') message = payload.detail;
      else if (payload.detail && 'message' in payload.detail && payload.detail.message) message = payload.detail.message;
      else if (payload.detail && 'error' in payload.detail && payload.detail.error?.message) message = payload.detail.error.message;
    } catch { /* Keep the HTTP status message when the response is not JSON. */ }
    throw new ApiError(message, response.status);
  }
  return (await response.json()) as EvidenceItem;
}

export function getEvidenceHistory(evidenceId: string): Promise<EvidenceHistory> {
  return requestJson<EvidenceHistory>(`${tenantPath()}/evidence/${encodeURIComponent(evidenceId)}`, 'GET');
}

export function reviewEvidence(evidenceId: string, reason?: string): Promise<EvidenceItem> {
  return requestJson<EvidenceItem>(`${tenantPath()}/evidence/${encodeURIComponent(evidenceId)}/review`, 'POST', { reason });
}

export function approveEvidence(evidenceId: string, reason?: string): Promise<EvidenceItem> {
  return requestJson<EvidenceItem>(`${tenantPath()}/evidence/${encodeURIComponent(evidenceId)}/approve`, 'POST', { reason });
}

export function updateEvidenceValidity(
  evidenceId: string,
  payload: { valid_from?: string | null; valid_until?: string | null },
): Promise<EvidenceItem> {
  return requestJson<EvidenceItem>(`${tenantPath()}/evidence/${encodeURIComponent(evidenceId)}/validity`, 'POST', payload);
}

export function markEvidenceInactive(evidenceId: string, reason: string): Promise<EvidenceItem> {
  return requestJson<EvidenceItem>(`${tenantPath()}/evidence/${encodeURIComponent(evidenceId)}/inactive`, 'POST', { reason });
}
