import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import Navbar from '../../components/Navbar';
import {
  ApiError,
  captureReportPayment,
  createReportPayment,
  downloadDetailedReportPdf,
  getDetailedReport,
  getReportAccess,
  startDetailedReport,
} from '../../api/client';
import type { DetailedReportStatus, ReportAccess } from '../../api/client';

type PaymentState = 'not purchased' | 'processing' | 'paid' | 'failed/cancelled';
type Redirect = (url: string) => void;

const paymentStateKey = (reportId: string) => `verityai:report-payment-state:${reportId}`;
const transactionKey = (reportId: string) => `verityai:report-payment-transaction:${reportId}`;
const idempotencyKey = (reportId: string) => `verityai:report-payment-idempotency:${reportId}`;

function readStored(key: string): string | null {
  try { return window.sessionStorage.getItem(key); } catch { return null; }
}

function store(key: string, value: string): void {
  try { window.sessionStorage.setItem(key, value); } catch { /* The backend remains authoritative. */ }
}

function clearCallbackParams(searchParams: URLSearchParams, setSearchParams: (next: URLSearchParams, options?: { replace?: boolean }) => void) {
  const next = new URLSearchParams(searchParams);
  next.delete('paypal');
  next.delete('token');
  next.delete('PayerID');
  setSearchParams(next, { replace: true });
}

function approvalUrlIsSandbox(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && (
      url.hostname === 'sandbox.paypal.com'
      || url.hostname === 'www.sandbox.paypal.com'
      || url.hostname.endsWith('.sandbox.paypal.com')
    );
  } catch {
    return false;
  }
}

function newIdempotencyKey(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

type ReportDetailProps = { redirect?: Redirect };

export default function ReportDetail({ redirect = (url) => window.location.assign(url) }: ReportDetailProps) {
  const { reportId = '' } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const callbackAction = searchParams.get('paypal');
  const [access, setAccess] = useState<ReportAccess | null>(null);
  const [paymentState, setPaymentState] = useState<PaymentState>('not purchased');
  const [isLoading, setIsLoading] = useState(true);
  const [isBusy, setIsBusy] = useState(false);
  const [error, setError] = useState('');
  const [detailedStatus, setDetailedStatus] = useState<DetailedReportStatus | null>(null);
  const [detailedError, setDetailedError] = useState('');
  const [isGeneratingDetailed, setIsGeneratingDetailed] = useState(false);
  const [isDownloadingPdf, setIsDownloadingPdf] = useState(false);
  const [pdfError, setPdfError] = useState('');
  const operationInProgress = useRef(false);
  const detailedOperationInProgress = useRef(false);
  const detailedAutoStartedFor = useRef('');
  const callbackHandled = useRef(false);
  const loadedReportId = useRef('');

  const savePaymentState = useCallback((next: PaymentState) => {
    setPaymentState(next);
    store(paymentStateKey(reportId), next);
  }, [reportId]);

  const refreshAccess = useCallback(async () => {
    const result = await getReportAccess(reportId);
    setAccess(result);
    setError('');
    if (result.is_entitled && result.report) savePaymentState('paid');
    return result;
  }, [reportId, savePaymentState]);

  const captureAndRefresh = useCallback(async (transactionId: string) => {
    if (operationInProgress.current) return;
    operationInProgress.current = true;
    setIsBusy(true);
    setError('');
    savePaymentState('processing');
    try {
      const capture = await captureReportPayment(transactionId);
      if (capture.transaction_id !== transactionId || capture.report_id !== reportId || capture.status !== 'capture_verified') {
        throw new Error('The payment capture could not be confirmed.');
      }
      const current = await refreshAccess();
      if (!current.is_entitled || !current.report) {
        throw new Error('The report is still locked because entitlement was not confirmed.');
      }
      savePaymentState('paid');
    } catch (cause) {
      savePaymentState('failed/cancelled');
      setError(cause instanceof ApiError ? cause.message : cause instanceof Error ? cause.message : 'Payment capture could not be confirmed. Try again.');
    } finally {
      setIsBusy(false);
      operationInProgress.current = false;
    }
  }, [refreshAccess, reportId, savePaymentState]);

  const runDetailedReport = useCallback(async (retry = false) => {
    if (detailedOperationInProgress.current) return;
    detailedOperationInProgress.current = true;
    setIsGeneratingDetailed(true);
    setDetailedError('');
    setDetailedStatus((previous) => previous ?? {
      report_id: reportId, report_version: access?.report?.report_version ?? 1,
      status: 'generating', detailed_report: null, error: null, retryable: false,
    });
    try {
      let current = retry ? await startDetailedReport(reportId) : await getDetailedReport(reportId);
      if (current.report_id !== reportId || current.report_version !== access?.report?.report_version) {
        throw new Error('The detailed report response did not match this verified report snapshot.');
      }
      if (current.status === 'not_started') {
        current = await startDetailedReport(reportId);
        if (current.report_id !== reportId || current.report_version !== access?.report?.report_version) {
          throw new Error('The detailed report response did not match this verified report snapshot.');
        }
      }
      let attempts = 0;
      while ((current.status === 'pending' || current.status === 'generating') && attempts < 80) {
        setDetailedStatus(current);
        await new Promise((resolve) => window.setTimeout(resolve, 1500));
        current = await getDetailedReport(reportId);
        if (current.report_id !== reportId || current.report_version !== access?.report?.report_version) {
          throw new Error('The detailed report response did not match this verified report snapshot.');
        }
        attempts += 1;
      }
      if (current.status === 'completed' && !current.detailed_report) {
        throw new Error('The completed detailed report is unavailable.');
      }
      setDetailedStatus(current);
      if (current.status === 'failed') setDetailedError(current.error ?? 'Detailed report generation failed. Please retry.');
      if (current.status === 'pending' || current.status === 'generating') {
        setDetailedError('Generation is still in progress. Check this report again shortly.');
      }
    } catch (cause) {
      setDetailedError(cause instanceof ApiError ? cause.message : cause instanceof Error ? cause.message : 'The detailed report is temporarily unavailable.');
      setDetailedStatus({
        report_id: reportId,
        report_version: access?.report?.report_version ?? 1,
        status: 'failed', detailed_report: null, error: null, retryable: true,
      });
    } finally {
      setIsGeneratingDetailed(false);
      detailedOperationInProgress.current = false;
    }
  }, [access?.report?.report_version, reportId]);

  useEffect(() => {
    if (!access?.is_entitled || !access.report || detailedAutoStartedFor.current === reportId) return;
    detailedAutoStartedFor.current = reportId;
    void runDetailedReport();
  }, [access?.is_entitled, access?.report, reportId, runDetailedReport]);

  async function downloadPdf() {
    if (isDownloadingPdf || detailedStatus?.status !== 'completed') return;
    setIsDownloadingPdf(true);
    setPdfError('');
    try {
      const file = await downloadDetailedReportPdf(reportId);
      const objectUrl = URL.createObjectURL(file);
      const link = document.createElement('a');
      link.href = objectUrl;
      link.download = 'verityai-detailed-report.pdf';
      link.click();
      URL.revokeObjectURL(objectUrl);
    } catch (cause) {
      setPdfError(cause instanceof ApiError ? cause.message : cause instanceof Error ? cause.message : 'The PDF could not be downloaded.');
    } finally {
      setIsDownloadingPdf(false);
    }
  }

  useEffect(() => {
    let current = true;
    callbackHandled.current = false;

    async function loadReportAndHandleReturn() {
      setIsLoading(true);
      if (loadedReportId.current !== reportId) {
        loadedReportId.current = reportId;
        setError('');
      }
      let loaded: ReportAccess | null = null;
      try {
        loaded = await getReportAccess(reportId);
        if (!current) return;
        setAccess(loaded);
      } catch (cause) {
        if (current) setError(cause instanceof ApiError ? cause.message : 'The report could not be loaded.');
      }

      if (!current) return;
      if (loaded?.is_entitled && loaded.report) {
        savePaymentState('paid');
      } else if (!callbackAction) {
        const storedState = readStored(paymentStateKey(reportId));
        if (storedState === 'processing' || storedState === 'failed/cancelled') {
          setPaymentState(storedState);
        } else {
          setPaymentState('not purchased');
        }
      }

      if (callbackAction === 'cancel') {
        savePaymentState('failed/cancelled');
        setError('Checkout was cancelled. The report remains locked.');
        clearCallbackParams(searchParams, setSearchParams);
      } else if (callbackAction === 'return' && !callbackHandled.current) {
        callbackHandled.current = true;
        const transactionId = readStored(transactionKey(reportId));
        if (!transactionId) {
          savePaymentState('failed/cancelled');
          setError('This checkout could not be matched to a payment attempt. Start checkout again.');
        } else {
          await captureAndRefresh(transactionId);
        }
        if (current) clearCallbackParams(searchParams, setSearchParams);
      }
      if (current) setIsLoading(false);
    }

    void loadReportAndHandleReturn();
    return () => { current = false; };
  }, [callbackAction, captureAndRefresh, reportId, savePaymentState, searchParams, setSearchParams]);

  async function startCheckout() {
    if (operationInProgress.current || isBusy || access?.is_entitled) return;
    operationInProgress.current = true;
    setIsBusy(true);
    setError('');
    savePaymentState('processing');
    try {
      const returnUrl = new URL(`/reports/${encodeURIComponent(reportId)}`, window.location.origin);
      returnUrl.searchParams.set('paypal', 'return');
      const cancelUrl = new URL(`/reports/${encodeURIComponent(reportId)}`, window.location.origin);
      cancelUrl.searchParams.set('paypal', 'cancel');
      let key = readStored(idempotencyKey(reportId));
      if (!key) {
        key = newIdempotencyKey();
        store(idempotencyKey(reportId), key);
      }
      const payment = await createReportPayment(reportId, returnUrl.toString(), cancelUrl.toString(), key);
      if (payment.report_id !== reportId || !payment.transaction_id || !payment.approval_url) {
        throw new Error('The payment service returned an incomplete checkout response.');
      }
      if (!approvalUrlIsSandbox(payment.approval_url)) {
        throw new Error('The payment service returned an invalid Sandbox checkout URL.');
      }
      store(transactionKey(reportId), payment.transaction_id);
      redirect(payment.approval_url);
    } catch (cause) {
      savePaymentState('failed/cancelled');
      setError(cause instanceof ApiError ? cause.message : cause instanceof Error ? cause.message : 'Checkout could not be started. Try again.');
    } finally {
      operationInProgress.current = false;
      setIsBusy(false);
    }
  }

  const transactionId = readStored(transactionKey(reportId));

  return (
    <main className="page-shell report-page">
      <Navbar />
      <div className="report-heading">
        <div>
          <p className="eyebrow">VerityAI report</p>
          <h1>Verification report</h1>
          <p className="lead">Report access is confirmed by VerityAI after PayPal capture.</p>
        </div>
        <Link className="text-link" to="/">Back to intake</Link>
      </div>

      {isLoading && <div className="report-panel" role="status">Loading report…</div>}
      {!isLoading && error && !access && <p className="inline-error" role="alert">{error}</p>}
      {!isLoading && access && <>
        <section className="report-panel" aria-labelledby="report-summary-heading">
          <div className="report-panel-heading">
            <div><p className="eyebrow">Limited preview</p><h2 id="report-summary-heading">Summary</h2></div>
            <span className={`payment-state ${paymentState === 'paid' ? 'payment-state-paid' : ''}`} aria-live="polite">
              Payment: {paymentState}
            </span>
          </div>
          <p>{access.preview.executive_summary}</p>
          <dl className="report-counts">
            <div><dt>Claims analyzed</dt><dd>{access.preview.counts.claims_analyzed}</dd></div>
            <div><dt>Findings</dt><dd>{access.preview.counts.findings}</dd></div>
            <div><dt>Supported</dt><dd>{access.preview.counts.supported_findings}</dd></div>
            <div><dt>Unverified</dt><dd>{access.preview.counts.unverified_findings}</dd></div>
          </dl>
          {access.preview.finding_sample.length > 0 && <div className="report-findings">
            <h3>Preview findings</h3>
            {access.preview.finding_sample.map((finding, index) => (
              <article className="report-finding" key={`${finding.category}-${index}`}>
                <strong>{finding.category}</strong>
                {finding.attention_label && <span>{finding.attention_label}</span>}
                <p>{finding.explanation_preview}</p>
              </article>
            ))}
          </div>}
        </section>

        {error && <p className="inline-error" role="alert">{error}</p>}
        {!access.is_entitled && <section className="report-panel report-checkout" aria-labelledby="checkout-heading">
          <div><p className="eyebrow">Full report</p><h2 id="checkout-heading">Unlock the complete findings</h2>
            <p className="helper-text">The final price is set by VerityAI and confirmed by the payment service. We never use a browser redirect as proof of payment.</p>
          </div>
          <button className="button button-primary" type="button" onClick={() => void startCheckout()} disabled={isBusy || isLoading}>
            {isBusy ? 'Processing…' : paymentState === 'processing' ? 'Continue checkout' : paymentState === 'failed/cancelled' ? 'Try again' : 'Continue to PayPal Sandbox'}
          </button>
          {paymentState === 'failed/cancelled' && transactionId && (
            <button className="button button-secondary" type="button" onClick={() => void captureAndRefresh(transactionId)} disabled={isBusy}>
              Retry payment confirmation
            </button>
          )}
        </section>}

        {access.is_entitled && access.report && <section className="report-panel report-full" aria-labelledby="detailed-report-heading">
          <div className="report-panel-heading">
            <div><p className="eyebrow">Paid detailed report</p><h2 id="detailed-report-heading">Detailed verification report</h2></div>
            {detailedStatus?.status === 'completed' && <button className="button button-secondary" type="button" onClick={() => void downloadPdf()} disabled={isDownloadingPdf}>
              {isDownloadingPdf ? 'Preparing PDF…' : 'Download PDF'}
            </button>}
          </div>
          {isGeneratingDetailed && <p role="status">Generating the detailed report and PDF…</p>}
          {detailedError && <p className="inline-error" role="alert">{detailedError}</p>}
          {pdfError && <p className="inline-error" role="alert">{pdfError}</p>}
          {detailedStatus?.status === 'failed' && <button className="button button-secondary" type="button" onClick={() => void runDetailedReport(true)} disabled={isGeneratingDetailed}>
            Retry detailed report generation
          </button>}
          {detailedStatus?.status === 'completed' && detailedStatus.detailed_report && <>
            <p className="helper-text">{detailedStatus.detailed_report.organization_name} · {detailedStatus.detailed_report.workspace_name} · Submission {detailedStatus.detailed_report.submission_id}</p>
            <h3>Executive Summary</h3>
            <p>{detailedStatus.detailed_report.executive_summary}</p>

            <h3>Verification Overview</h3>
            <p>{detailedStatus.detailed_report.verification_overview}</p>
            <dl className="report-counts">
              <div><dt>Claims reviewed</dt><dd>{detailedStatus.detailed_report.counts.claims_analyzed}</dd></div>
              <div><dt>Findings</dt><dd>{detailedStatus.detailed_report.counts.findings}</dd></div>
              <div><dt>Supported</dt><dd>{detailedStatus.detailed_report.counts.supported_findings}</dd></div>
              <div><dt>Unverified</dt><dd>{detailedStatus.detailed_report.counts.unverified_findings}</dd></div>
              <div><dt>Policy findings</dt><dd>{detailedStatus.detailed_report.counts.policy_findings}</dd></div>
            </dl>
            {detailedStatus.detailed_report.coverage_limitations.map((item, index) => <p className="helper-text" key={`coverage-${index}`}>{item}</p>)}

            <h3>Detailed Claim-by-Claim Analysis</h3>
            {detailedStatus.detailed_report.claim_analyses.map((finding) => <article className="report-full-finding" key={finding.finding_id}>
              <div className="report-panel-heading"><h4>{finding.claim_description}</h4><span className="preview-tag">{finding.verification_status}</span></div>
              <p><strong>Verified finding:</strong> {finding.deterministic_explanation}</p>
              <p><strong>AI-assisted explanation:</strong> {finding.ai_analysis}</p>
              {finding.ai_limitations.map((item, index) => <p className="helper-text" key={`${finding.finding_id}-limitation-${index}`}>{item}</p>)}
              {finding.supporting_evidence.length > 0 && <details><summary>Evidence references</summary><pre>{JSON.stringify(finding.supporting_evidence, null, 2)}</pre></details>}
              {finding.policy_result && <details><summary>Policy result</summary><pre>{JSON.stringify(finding.policy_result, null, 2)}</pre></details>}
            </article>)}

            <h3>Risk and Compliance Assessment</h3>
            {detailedStatus.detailed_report.risk_assessment.length
              ? <ul>{detailedStatus.detailed_report.risk_assessment.map((item, index) => <li key={`risk-${index}`}>{item}</li>)}</ul>
              : <p>No additional narrative risks were generated from the saved findings.</p>}
            <h3>Recommendations</h3>
            <p className="eyebrow">{detailedStatus.detailed_report.recommendation_label}</p>
            {detailedStatus.detailed_report.recommendations.length
              ? <ul>{detailedStatus.detailed_report.recommendations.map((item, index) => <li key={`recommendation-${index}`}>{item}</li>)}</ul>
              : <p>No recommendations were generated.</p>}
            <h3>Methodology</h3>
            <p>{detailedStatus.detailed_report.methodology}</p>
            <details><summary>Evidence and limitations appendix</summary>
              <pre>{JSON.stringify({
                policy_evaluation: detailedStatus.detailed_report.policy_evaluation,
                evidence_appendix: detailedStatus.detailed_report.evidence_appendix,
                limitations: detailedStatus.detailed_report.coverage_limitations,
              }, null, 2)}</pre>
            </details>
          </>}
        </section>}

        {access.is_entitled && access.report && <section className="report-panel report-full" aria-labelledby="full-report-heading">
          <div className="report-panel-heading"><div><p className="eyebrow">Entitlement confirmed</p><h2 id="full-report-heading">Full report</h2></div>
            <span className="payment-state payment-state-paid">Payment: paid</span>
          </div>
          {access.report.findings.map((finding) => (
            <article className="report-full-finding" key={finding.finding_id}>
              <div className="report-panel-heading"><h3>{finding.category}</h3>{finding.attention_label && <span className="preview-tag">{finding.attention_label}</span>}</div>
              <p>{finding.explanation}</p>
              {finding.claim && <details><summary>Claim details</summary><pre>{JSON.stringify(finding.claim, null, 2)}</pre></details>}
              {finding.supporting_evidence.length > 0 && <details><summary>Supporting evidence</summary><pre>{JSON.stringify(finding.supporting_evidence, null, 2)}</pre></details>}
              {finding.policy_result && <details><summary>Policy evaluation</summary><pre>{JSON.stringify(finding.policy_result, null, 2)}</pre></details>}
            </article>
          ))}
          <h3>Policy evaluation</h3><pre>{JSON.stringify(access.report.policy_evaluation, null, 2)}</pre>
          <h3>Limitations</h3><ul>{access.report.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul>
        </section>}
      </>}
    </main>
  );
}
