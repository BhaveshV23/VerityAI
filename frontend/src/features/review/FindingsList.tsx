import { useState } from 'react';
import type { FormEvent } from 'react';
import {
  ApiError,
  recordFindingDisposition,
} from '../../api/client';
import type {
  AnalysisFinding,
  FindingDispositionKind,
  FindingDispositionPayload,
} from '../../api/client';

export type ReviewFinding = AnalysisFinding;

type FindingsListProps = {
  findings: ReviewFinding[];
  isLoading?: boolean;
  error?: string;
  runNumber?: number;
  runId?: string;
  versionId: string;
  analysisState?: 'Running' | 'Succeeded' | 'Incomplete' | null;
  onDispositionSaved: () => Promise<void>;
};

const dispositionOptions: { value: FindingDispositionKind; label: string }[] = [
  { value: 'resolved', label: 'Resolved — issue addressed' },
  { value: 'not_applicable', label: 'Not applicable' },
  { value: 'acknowledged', label: 'Acknowledged — still unresolved' },
  { value: 'disputed', label: 'Disputed — still unresolved' },
];

function statusLabel(finding: ReviewFinding): string {
  if (finding.resolution_status === 'resolved') return 'Resolved by reviewer';
  if (finding.resolution_status === 'acknowledged') return 'Acknowledged · still unresolved';
  if (finding.resolution_status === 'disputed') return 'Disputed · still unresolved';
  if (finding.resolution_status === 'legacy_unrecognized') return 'Prior disposition · unresolved';
  return finding.is_unresolved ? 'Open / unresolved' : 'Reviewed';
}

export default function FindingsList({
  findings,
  isLoading = false,
  error = '',
  runNumber,
  runId,
  versionId,
  analysisState = null,
  onDispositionSaved,
}: FindingsListProps) {
  const [drafts, setDrafts] = useState<Record<string, { disposition: FindingDispositionKind; rationale: string }>>({});
  const [savingId, setSavingId] = useState<string | null>(null);
  const [actionError, setActionError] = useState('');
  const [actionMessage, setActionMessage] = useState('');

  function draftFor(finding: ReviewFinding) {
    return drafts[finding.id] ?? {
      disposition: (finding.effective_disposition as FindingDispositionKind) || 'resolved',
      rationale: '',
    };
  }

  async function saveDisposition(event: FormEvent<HTMLFormElement>, finding: ReviewFinding) {
    event.preventDefault();
    if (!runId) return;
    const draft = draftFor(finding);
    setSavingId(finding.id);
    setActionError('');
    setActionMessage('');
    try {
      const payload: FindingDispositionPayload = {
        analysis_run_id: runId,
        submission_version_id: versionId,
        disposition: draft.disposition,
        rationale: draft.rationale.trim(),
      };
      await recordFindingDisposition(finding.id, payload);
      setActionMessage(`Disposition saved for finding ${finding.id.slice(-4)}.`);
      await onDispositionSaved();
    } catch (cause) {
      setActionError(cause instanceof ApiError ? cause.message : 'Disposition could not be saved. Refresh and try again.');
    } finally {
      setSavingId(null);
    }
  }

  return (
    <section className="findings-section" aria-labelledby="findings-heading">
      <div className="panel-heading findings-heading">
        <div>
          <p className="eyebrow">Analysis summary</p>
          <h2 id="findings-heading">Findings <span className="count-pill">{findings.length}</span></h2>
        </div>
        <span className={`preview-tag ${analysisState === 'Incomplete' ? 'analysis-incomplete' : ''}`}>
          {runNumber ? `Run ${runNumber} · ${analysisState ?? 'state unavailable'}` : 'No analysis run'}
        </span>
      </div>

      {isLoading ? (
        <div className="empty-findings" role="status">Loading analysis findings...</div>
      ) : error ? (
        <div className="inline-error" role="alert">{error}</div>
      ) : findings.length === 0 ? (
        <div className="empty-findings">No findings were returned for the latest analysis run.</div>
      ) : (
        <div className="finding-list">
          {findings.map((finding) => {
            const draft = draftFor(finding);
            return (
              <article className="finding-card" key={finding.id}>
                <div className="finding-card-top">
                  <span className={`finding-status ${finding.blocks_clean_approval ? 'status-open' : 'status-resolved'}`}>
                    {statusLabel(finding)}
                  </span>
                  <span className="finding-id">Finding {finding.id.slice(-4)}</span>
                </div>
                <h3>{finding.category}</h3>
                <p>{finding.explanation}</p>
                <p className="finding-attention">Original attention label: {finding.attention_label ?? 'not assigned'}</p>
                {(finding.evidence_version_id || finding.policy_version_id) && (
                  <div className="finding-links" aria-label="Related records">
                    {finding.evidence_version_id && (
                      <a href={`#evidence-${finding.evidence_version_id}`}>Evidence · {finding.evidence_version_id.slice(0, 8)}</a>
                    )}
                    {finding.policy_version_id && (
                      <a href={`#policy-${finding.policy_version_id}`}>Policy · {finding.policy_version_id.slice(0, 8)}</a>
                    )}
                  </div>
                )}
                <p className={finding.blocks_clean_approval ? 'decision-warning' : 'inline-success'}>
                  {finding.blocks_clean_approval
                    ? 'This finding currently blocks clean approval.'
                    : finding.resolution_status === 'resolved'
                      ? 'This reviewer disposition clears the clean-approval blocker; it does not verify the claim.'
                      : 'This finding does not currently block clean approval.'}
                </p>
                {finding.disposition_history.length > 0 && (
                  <details className="disposition-history">
                    <summary>Disposition history ({finding.disposition_history.length})</summary>
                    <ol>
                      {finding.disposition_history.map((entry) => (
                        <li key={entry.id}>
                          <strong>{entry.disposition}</strong> · {entry.rationale}
                          <small>Reviewer {entry.reviewer_membership_id.slice(0, 8)} · {new Date(entry.created_at).toLocaleString()}</small>
                        </li>
                      ))}
                    </ol>
                  </details>
                )}
                {runId && finding.is_unresolved && (
                  <form className="finding-disposition-form" onSubmit={(event) => void saveDisposition(event, finding)}>
                    <label htmlFor={`finding-disposition-${finding.id}`}>Reviewer disposition</label>
                    <select
                      id={`finding-disposition-${finding.id}`}
                      value={draft.disposition}
                      disabled={savingId === finding.id}
                      onChange={(event) => setDrafts((current) => ({
                        ...current,
                        [finding.id]: { ...draft, disposition: event.target.value as FindingDispositionKind },
                      }))}
                    >
                      {dispositionOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                    </select>
                    <label htmlFor={`finding-rationale-${finding.id}`}>Required rationale</label>
                    <textarea
                      id={`finding-rationale-${finding.id}`}
                      value={draft.rationale}
                      required
                      minLength={1}
                      rows={2}
                      disabled={savingId === finding.id}
                      placeholder="Explain the reviewer’s assessment..."
                      onChange={(event) => setDrafts((current) => ({
                        ...current,
                        [finding.id]: { ...draft, rationale: event.target.value },
                      }))}
                    />
                    <button className="button button-secondary" type="submit" disabled={savingId === finding.id || !draft.rationale.trim()}>
                      {savingId === finding.id ? 'Saving disposition...' : 'Save disposition'}
                    </button>
                  </form>
                )}
              </article>
            );
          })}
        </div>
      )}
      {actionError && <p className="inline-error" role="alert">{actionError}</p>}
      {actionMessage && <p className="inline-success" role="status">{actionMessage}</p>}
    </section>
  );
}
