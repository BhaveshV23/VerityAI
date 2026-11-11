import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import ReportDetail from '../src/features/reports/ReportDetail';
import type { ReportAccess } from '../src/api/client';

const api = vi.hoisted(() => ({
  getReportAccess: vi.fn(),
  createReportPayment: vi.fn(),
  captureReportPayment: vi.fn(),
}));

vi.mock('../src/api/client', () => ({
  ApiError: class ApiError extends Error {},
  getReportAccess: api.getReportAccess,
  createReportPayment: api.createReportPayment,
  captureReportPayment: api.captureReportPayment,
}));

const preview = {
  report_id: 'report-1', report_version: 1, submission_version_id: 'version-1', analysis_run_id: 'run-1',
  generated_at: '2026-11-10T00:00:00Z', overall_analysis_status: 'Succeeded' as const,
  executive_summary: 'Two claims were reviewed.',
  counts: { claims_analyzed: 2, findings: 2, supported_findings: 1, unverified_findings: 1, policy_findings: 0 },
  finding_sample: [{ category: 'Unverified claim', attention_label: null, explanation_preview: 'The claim needs evidence.' }],
  is_limited_preview: true as const,
};

const fullReport = {
  ...preview,
  findings: [{
    finding_id: 'finding-1', category: 'Unverified claim', attention_label: null,
    explanation: 'Full finding explanation.', claim: { text: 'A claim' }, supporting_evidence: [], policy_result: null,
  }],
  policy_evaluation: { stage_state: 'Succeeded' },
  limitations: ['Automated analysis is not a guarantee.'],
};

const unpaid: ReportAccess = { preview, is_entitled: false, report: null };
const paid: ReportAccess = { preview, is_entitled: true, report: fullReport };

function renderReport(path = '/reports/report-1', redirect = vi.fn()) {
  return {
    redirect,
    ...render(
      <MemoryRouter initialEntries={[path]}>
        <Routes><Route path="/reports/:reportId" element={<ReportDetail redirect={redirect} />} /></Routes>
      </MemoryRouter>,
    ),
  };
}

describe('report payment flow', () => {
  afterEach(() => cleanup());

  beforeEach(() => {
    vi.clearAllMocks();
    window.sessionStorage.clear();
    api.getReportAccess.mockResolvedValue(unpaid);
    api.createReportPayment.mockResolvedValue({
      transaction_id: 'transaction-1', report_id: 'report-1', status: 'pending', amount: '5.00',
      currency: 'USD', paypal_order_id: 'order-1', approval_url: 'https://www.sandbox.paypal.com/checkoutnow?token=order-1',
    });
    api.captureReportPayment.mockResolvedValue({
      transaction_id: 'transaction-1', report_id: 'report-1', entitlement_id: 'entitlement-1', status: 'capture_verified',
    });
  });

  it('starts checkout with server URLs and redirects to the returned Sandbox approval URL', async () => {
    const redirect = vi.fn();
    renderReport(undefined, redirect);
    fireEvent.click(await screen.findByRole('button', { name: 'Continue to PayPal Sandbox' }));

    await waitFor(() => expect(api.createReportPayment).toHaveBeenCalledTimes(1));
    const [reportId, returnUrl, cancelUrl, key] = api.createReportPayment.mock.calls[0];
    expect(reportId).toBe('report-1');
    expect(new URL(returnUrl).searchParams.get('paypal')).toBe('return');
    expect(new URL(cancelUrl).searchParams.get('paypal')).toBe('cancel');
    expect(key).toBeTruthy();
    expect(redirect).toHaveBeenCalledWith('https://www.sandbox.paypal.com/checkoutnow?token=order-1');
    expect(window.sessionStorage.getItem('verityai:report-payment-transaction:report-1')).toBe('transaction-1');
  });

  it('captures on approval return and unlocks only after entitlement refresh', async () => {
    window.sessionStorage.setItem('verityai:report-payment-transaction:report-1', 'transaction-1');
    api.getReportAccess.mockResolvedValueOnce(unpaid).mockResolvedValue(paid);
    renderReport('/reports/report-1?paypal=return&token=untrusted&PayerID=untrusted');

    expect(await screen.findByText('Full finding explanation.')).toBeTruthy();
    expect(api.captureReportPayment).toHaveBeenCalledWith('transaction-1');
    expect(api.getReportAccess).toHaveBeenCalledTimes(2);
    expect(screen.getAllByText('Payment: paid').length).toBeGreaterThan(0);
  });

  it('keeps the report locked when capture returns but entitlement refresh does not confirm access', async () => {
    window.sessionStorage.setItem('verityai:report-payment-transaction:report-1', 'transaction-1');
    api.getReportAccess.mockResolvedValue(unpaid);
    renderReport('/reports/report-1?paypal=return&token=untrusted');

    expect(await screen.findByText('Payment: failed/cancelled')).toBeTruthy();
    expect(screen.queryByText('Full finding explanation.')).toBeNull();
    expect(screen.getByText('The report is still locked because entitlement was not confirmed.')).toBeTruthy();
  });

  it('handles cancellation without calling capture or unlocking the report', async () => {
    renderReport('/reports/report-1?paypal=cancel&token=untrusted');

    expect(await screen.findByText('Payment: failed/cancelled')).toBeTruthy();
    expect(api.captureReportPayment).not.toHaveBeenCalled();
    expect(screen.queryByText('Full finding explanation.')).toBeNull();
  });

  it('shows capture failure and allows an idempotent confirmation retry', async () => {
    window.sessionStorage.setItem('verityai:report-payment-transaction:report-1', 'transaction-1');
    api.getReportAccess.mockResolvedValueOnce(unpaid).mockResolvedValueOnce(unpaid).mockResolvedValue(paid);
    api.captureReportPayment.mockRejectedValueOnce(new Error('Network unavailable'));
    renderReport('/reports/report-1?paypal=return');

    expect(await screen.findByText('Payment: failed/cancelled')).toBeTruthy();
    expect(screen.getByText('Network unavailable')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Retry payment confirmation' }));
    expect((await screen.findAllByText('Full finding explanation.')).length).toBeGreaterThan(0);
    expect(api.captureReportPayment).toHaveBeenCalledTimes(2);
  });

  it('marks a refreshed report paid only from the backend entitlement response', async () => {
    api.getReportAccess.mockResolvedValue(paid);
    renderReport();

    expect((await screen.findAllByText('Payment: paid')).length).toBeGreaterThan(0);
    expect(screen.getByText('Full finding explanation.')).toBeTruthy();
    expect(api.captureReportPayment).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Continue to PayPal Sandbox' })).toBeNull();
  });

  it('shows failed state for initiation network errors and does not redirect', async () => {
    const redirect = vi.fn();
    api.createReportPayment.mockRejectedValue(new Error('Network unavailable'));
    renderReport(undefined, redirect);
    fireEvent.click(await screen.findByRole('button', { name: 'Continue to PayPal Sandbox' }));

    expect(await screen.findByText('Payment: failed/cancelled')).toBeTruthy();
    expect(screen.getByText('Network unavailable')).toBeTruthy();
    expect(redirect).not.toHaveBeenCalled();
  });
});
