import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import ReviewWorkspace from '../src/features/review/ReviewWorkspace';
import ReportDetail from '../src/features/reports/ReportDetail';

const api = vi.hoisted(() => ({
  getAnalysisFindings: vi.fn(),
  getAnalysisRuns: vi.fn(),
  getReviewEligibility: vi.fn(),
  createReportSnapshot: vi.fn(),
  getReportAccess: vi.fn(),
}));

vi.mock('../src/api/client', () => ({
  ApiError: class ApiError extends Error {
    constructor(message: string, readonly status: number) { super(message); }
  },
  getAnalysisFindings: api.getAnalysisFindings,
  getAnalysisRuns: api.getAnalysisRuns,
  getReviewEligibility: api.getReviewEligibility,
  createReportSnapshot: api.createReportSnapshot,
  getReportAccess: api.getReportAccess,
}));

vi.mock('../src/features/review/DocumentViewer', () => ({ default: () => <div /> }));
vi.mock('../src/features/review/FindingsList', () => ({ default: () => <div /> }));
vi.mock('../src/features/review/DecisionPanel', () => ({
  default: ({ onDecisionSaved }: { onDecisionSaved: () => Promise<void> }) => (
    <button type="button" onClick={() => void onDecisionSaved()}>Submit decision</button>
  ),
}));

const reportPreview = {
  report_id: 'report-1', report_version: 1, submission_version_id: 'version-1', analysis_run_id: 'run-1',
  generated_at: '2026-11-11T00:00:00Z', overall_analysis_status: 'Succeeded' as const,
  executive_summary: 'The submitted claims were reviewed.',
  counts: { claims_analyzed: 1, findings: 1, supported_findings: 0, unverified_findings: 1, policy_findings: 0 },
  finding_sample: [], is_limited_preview: true as const,
};

function renderReviewWorkspace() {
  return render(
    <MemoryRouter initialEntries={['/review/submission-1/version-1']}>
      <Routes>
        <Route path="/review/:submissionId/:versionId" element={<ReviewWorkspace />} />
        <Route path="/reports/:reportId" element={<ReportDetail redirect={() => undefined} />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('Review Workspace report flow', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.sessionStorage.clear();
    api.getAnalysisRuns.mockResolvedValue([{
      id: 'run-1', submission_version_id: 'version-1', run_number: 1, overall_state: 'Succeeded',
      started_at: '2026-11-11T00:00:00Z', completed_at: '2026-11-11T00:00:01Z', stage_results: [],
    }]);
    api.getReviewEligibility.mockResolvedValue({
      submission_version_id: 'version-1', analysis_run_id: 'run-1', analysis_status: 'Succeeded',
      can_clean_approve: true, can_approve_with_exceptions: true,
      clean_approval_reason: null, exception_approval_reason: null, blocking_finding_ids: [],
    });
    api.getAnalysisFindings.mockResolvedValue([]);
    api.createReportSnapshot.mockResolvedValue({ report_id: 'report-1', preview: reportPreview });
    api.getReportAccess.mockResolvedValue({ preview: reportPreview, is_entitled: false, report: null });
  });

  afterEach(() => cleanup());

  it('creates the report without submitting a reviewer decision and navigates to checkout', async () => {
    renderReviewWorkspace();

    const viewReport = await screen.findByRole('link', { name: 'View report' });
    expect(api.createReportSnapshot).toHaveBeenCalledWith('version-1', 'run-1');
    fireEvent.click(viewReport);

    expect(await screen.findByRole('heading', { name: 'Verification report' })).toBeTruthy();
    expect(await screen.findByRole('button', { name: 'Continue to PayPal Sandbox' })).toBeTruthy();
    expect(api.getReportAccess).toHaveBeenCalledWith('report-1');
  });

  it('keeps the report action available after a reviewer decision refresh', async () => {
    renderReviewWorkspace();
    expect(await screen.findByRole('link', { name: 'View report' })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Submit decision' }));

    await waitFor(() => expect(api.getAnalysisRuns).toHaveBeenCalledTimes(2));
    expect(screen.getByRole('link', { name: 'View report' })).toBeTruthy();
    expect(api.createReportSnapshot).toHaveBeenCalledTimes(1);
  });

  it('shows the report API error and offers retry when snapshot creation fails', async () => {
    api.createReportSnapshot.mockRejectedValueOnce(new Error('Every required analysis stage must succeed.'));
    renderReviewWorkspace();

    expect((await screen.findByRole('alert')).textContent).toContain('Every required analysis stage must succeed.');
    fireEvent.click(screen.getByRole('button', { name: 'Retry report creation' }));

    expect(await screen.findByRole('link', { name: 'View report' })).toBeTruthy();
    expect(api.createReportSnapshot).toHaveBeenCalledTimes(2);
  });
});
