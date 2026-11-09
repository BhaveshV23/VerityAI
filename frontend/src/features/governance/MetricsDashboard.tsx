import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ApiError, getGovernanceMetrics } from '../../api/client';
import type { GovernanceMetrics } from '../../api/client';
import Navbar from '../../components/Navbar';

function MetricValue({ value }: { value: number }) {
  return <strong className="metric-value">{value.toLocaleString()}</strong>;
}

export default function MetricsDashboard() {
  const [metrics, setMetrics] = useState<GovernanceMetrics | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let isCurrent = true;
    getGovernanceMetrics()
      .then((data) => { if (isCurrent) setMetrics(data); })
      .catch((cause: unknown) => {
        if (isCurrent) setError(cause instanceof ApiError ? cause.message : 'Governance metrics could not be loaded.');
      })
      .finally(() => { if (isCurrent) setIsLoading(false); });
    return () => { isCurrent = false; };
  }, []);

  return (
    <main className="page-shell governance-page">
      <Navbar />

      <div className="governance-heading">
        <div>
          <p className="eyebrow">Workspace overview</p>
          <h1>Governance Insights</h1>
          <p className="lead">A snapshot of submissions, review activity, and evidence requiring attention.</p>
        </div>
        <div className="governance-heading-actions">
          <span className="period-label">Data from the last 30 days</span>
          <Link className="text-link" to="/">← Back to intake</Link>
        </div>
      </div>

      {isLoading ? (
        <div className="dashboard-state" role="status">Loading governance metrics…</div>
      ) : error ? (
        <div className="dashboard-state dashboard-error" role="alert">{error}</div>
      ) : metrics ? (
        <section className="metrics-grid" aria-label="Five workspace governance metrics">
          <article className="metric-card">
            <div className="metric-card-heading"><span className="metric-icon icon-blue">↗</span><span>Activity</span></div>
            <div className="metric-pair">
              <div><MetricValue value={metrics.submissions_count} /><span>Submissions</span></div>
              <div><MetricValue value={metrics.review_decisions_count} /><span>Review decisions</span></div>
            </div>
          </article>

          <article className="metric-card">
            <div className="metric-card-heading"><span className="metric-icon icon-amber">!</span><span>Unverified claims</span></div>
            <MetricValue value={metrics.unverified_claims_count} />
            <p className="metric-caption">Claims without eligible approved evidence matches</p>
          </article>

          <article className="metric-card">
            <div className="metric-card-heading"><span className="metric-icon icon-purple">⌁</span><span>Recurring policy findings</span></div>
            <MetricValue value={metrics.recurring_policy_findings.length} />
            {metrics.recurring_policy_findings.length > 0 ? (
              <ul className="metric-detail-list">
                {metrics.recurring_policy_findings.map((item) => (
                  <li key={item.policy_version_id}>
                    <span>Policy {item.policy_version_id.slice(0, 8)}</span><strong>{item.count} findings</strong>
                  </li>
                ))}
              </ul>
            ) : <p className="metric-caption">No policy findings recurred in this period.</p>}
          </article>

          <article className="metric-card">
            <div className="metric-card-heading"><span className="metric-icon icon-green">✓</span><span>Review decisions</span></div>
            <ul className="metric-detail-list decision-trends">
              {Object.entries(metrics.review_decision_trends).map(([decision, count]) => (
                <li key={decision}><span>{decision}</span><strong>{count}</strong></li>
              ))}
            </ul>
          </article>

          <article className="metric-card">
            <div className="metric-card-heading"><span className="metric-icon icon-rose">◷</span><span>Evidence requiring attention</span></div>
            <ul className="metric-detail-list">
              <li><span>Uploaded or reviewed</span><strong>{metrics.evidence_attention.awaiting_review}</strong></li>
              <li><span>Inactive</span><strong>{metrics.evidence_attention.inactive}</strong></li>
              <li><span>Expired versions</span><strong>{metrics.evidence_attention.expired_versions}</strong></li>
              <li><span>Conflict-flagged versions</span><strong>{metrics.evidence_attention.conflict_flagged_versions}</strong></li>
            </ul>
            <p className="metric-caption">Counts are separate; a record can appear in multiple conditions.</p>
          </article>
        </section>
      ) : null}
    </main>
  );
}
