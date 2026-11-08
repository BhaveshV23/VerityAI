import { useState } from 'react';
import type { FormEvent } from 'react';
import { ApiError, createReviewDecision } from '../../api/client';
import type { AnalysisStageResult, FindingDispositionKind, ReviewDecision, ReviewEligibility } from '../../api/client';
import type { ReviewFinding } from './FindingsList';

type DecisionPanelProps = {
  versionId: string;
  findings: ReviewFinding[];
  analysisState: 'Running' | 'Succeeded' | 'Incomplete' | null;
  analysisStages: AnalysisStageResult[];
  eligibility: ReviewEligibility | null;
  onDecisionSaved: () => Promise<void>;
};

const choices: { value: ReviewDecision; label: string }[] = [
  { value: 'Approved', label: 'Approve' },
  { value: 'Approved with documented exceptions', label: 'Approve with Exceptions' },
  { value: 'Changes requested', label: 'Request Changes' },
  { value: 'Rejected', label: 'Reject' },
];
const requiredStageKeys = ['claim_extraction', 'evidence_retrieval', 'policy_evaluation', 'finding_composition'];

export default function DecisionPanel({
  versionId,
  findings,
  analysisState,
  analysisStages,
  eligibility,
  onDecisionSaved,
}: DecisionPanelProps) {
  const [decision, setDecision] = useState<ReviewDecision>('Approved');
  const [rationale, setRationale] = useState('');
  const [dispositions, setDispositions] = useState<Record<string, { disposition: FindingDispositionKind; rationale: string }>>({});
  const [isSaving, setIsSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const unresolvedFindings = findings.filter((finding) => finding.blocks_clean_approval);
  const exceptionApproval = decision === 'Approved with documented exceptions';
  const requiresRationale = decision === 'Rejected' || decision === 'Changes requested';
  const approvalBlockReason = eligibility?.exception_approval_reason ?? 'Checking analysis eligibility...';
  const cleanApprovalReason = eligibility?.clean_approval_reason ?? 'Checking clean-approval eligibility...';

  function updateDisposition(findingId: string, field: 'disposition' | 'rationale', value: string) {
    setDispositions((current) => ({
      ...current,
      [findingId]: {
        disposition: current[findingId]?.disposition ?? 'acknowledged',
        rationale: current[findingId]?.rationale ?? '',
        [field]: value,
      },
    }));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage('');
    setError('');
    setIsSaving(true);
    try {
      const result = await createReviewDecision(versionId, {
        decision,
        ...(rationale.trim() ? { rationale: rationale.trim() } : {}),
        ...(exceptionApproval ? {
          dispositions: unresolvedFindings.map((finding) => ({
            finding_id: finding.id,
            disposition: dispositions[finding.id]?.disposition ?? (finding.effective_disposition as FindingDispositionKind) ?? 'acknowledged',
            rationale: dispositions[finding.id]?.rationale.trim() ?? '',
          })),
        } : {}),
      });
      setMessage(`Decision recorded: ${result.decision}.`);
      await onDecisionSaved();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'The decision could not be recorded. Refresh and try again.');
      if (cause instanceof ApiError && cause.status === 409) await onDecisionSaved();
    } finally {
      setIsSaving(false);
    }
  }

  const exceptionRationalesComplete = unresolvedFindings.every((finding) =>
    Boolean(dispositions[finding.id]?.rationale.trim()),
  );
  const canSubmit = !isSaving && (
    decision === 'Approved'
      ? eligibility?.can_clean_approve === true
      : exceptionApproval
        ? eligibility?.can_approve_with_exceptions === true && Boolean(rationale.trim()) && exceptionRationalesComplete
        : !requiresRationale || Boolean(rationale.trim())
  );

  return (
    <form className="decision-panel" onSubmit={(event) => void handleSubmit(event)}>
      <p className="eyebrow">Reviewer decision</p>
      <h2>Complete review</h2>
      <div className="decision-buttons" role="group" aria-label="Choose a review decision">
        {choices.map((choice) => (
          <button
            className={`decision-choice ${decision === choice.value ? 'is-selected' : ''}`}
            type="button"
            key={choice.value}
            aria-pressed={decision === choice.value}
            disabled={isSaving || (choice.value === 'Approved' && eligibility?.can_clean_approve !== true)
              || (choice.value === 'Approved with documented exceptions' && eligibility?.can_approve_with_exceptions !== true)}
            onClick={() => { setDecision(choice.value); setMessage(''); setError(''); }}
          >
            {choice.label}
          </button>
        ))}
      </div>

      {exceptionApproval && (
        <div className="decision-fields">
          <p className="preview-disclaimer">Every finding still blocking clean approval needs a documented exception. Exceptions keep findings unresolved.</p>
          <label htmlFor="exception-overall-rationale">Overall rationale</label>
          <textarea id="exception-overall-rationale" value={rationale} onChange={(event) => setRationale(event.target.value)} rows={3} required />
          {unresolvedFindings.map((finding) => (
            <fieldset className="disposition-fields" key={finding.id}>
              <legend>{finding.category}</legend>
              <label htmlFor={`exception-disposition-${finding.id}`}>Exception disposition</label>
              <select
                id={`exception-disposition-${finding.id}`}
                value={dispositions[finding.id]?.disposition ?? (finding.effective_disposition as FindingDispositionKind) ?? 'acknowledged'}
                onChange={(event) => updateDisposition(finding.id, 'disposition', event.target.value)}
              >
                <option value="resolved">Resolved — issue addressed</option>
                <option value="not_applicable">Not applicable</option>
                <option value="acknowledged">Acknowledged — remains unresolved</option>
                <option value="disputed">Disputed — remains unresolved</option>
              </select>
              <label htmlFor={`exception-rationale-${finding.id}`}>Disposition rationale</label>
              <textarea
                id={`exception-rationale-${finding.id}`}
                value={dispositions[finding.id]?.rationale ?? ''}
                onChange={(event) => updateDisposition(finding.id, 'rationale', event.target.value)}
                rows={2}
                required
              />
            </fieldset>
          ))}
        </div>
      )}

      {requiresRationale && (
        <div className="decision-fields">
          <label htmlFor="decision-rationale">Rationale</label>
          <textarea
            id="decision-rationale"
            value={rationale}
            onChange={(event) => setRationale(event.target.value)}
            placeholder={decision === 'Rejected' ? 'Explain why this submission is rejected...' : 'Explain the changes required...'}
            rows={3}
            required
          />
        </div>
      )}

      {decision === 'Approved' && eligibility?.can_clean_approve !== true && (
        <div className="decision-warning" role="status">
          <p>{cleanApprovalReason}</p>
          {analysisStages.length > 0 && (
            <ul aria-label="Analysis stage statuses">
              {analysisStages.filter((stage) => requiredStageKeys.includes(stage.stage_key)).map((stage) => (
                <li key={stage.stage_key}>{stage.stage_key.replaceAll('_', ' ')}: {stage.state}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      {exceptionApproval && eligibility?.can_approve_with_exceptions !== true && (
        <p className="decision-warning" role="status">{approvalBlockReason}</p>
      )}
      {decision === 'Approved' && eligibility?.can_clean_approve === true && analysisState === 'Succeeded' && (
        <p className="inline-success" role="status">All current clean-approval blockers have a qualifying reviewer disposition.</p>
      )}
      {error && <p className="inline-error" role="alert">{error}</p>}
      {message && <p className="inline-success" role="status">{message}</p>}
      <button className="button button-primary decision-submit" type="submit" disabled={!canSubmit}>
        {isSaving ? 'Recording decision...' : 'Submit decision'}
      </button>
    </form>
  );
}
