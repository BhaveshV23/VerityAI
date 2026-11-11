import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import Navbar from '../../components/Navbar';
import {
  ApiError,
  captureReportPayment,
  createReportPayment,
  getReportAccess,
} from '../../api/client';
import type { ReportAccess } from '../../api/client';

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
  const operationInProgress = useRef(false);
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
