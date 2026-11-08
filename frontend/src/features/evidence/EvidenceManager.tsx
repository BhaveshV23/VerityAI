import { useCallback, useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link } from 'react-router-dom';
import {
  ApiError,
  approveEvidence,
  getEvidence,
  getEvidenceHistory,
  markEvidenceInactive,
  reviewEvidence,
  updateEvidenceValidity,
  uploadEvidence,
} from '../../api/client';
import type { EvidenceHistory, EvidenceItem } from '../../api/client';

function validityLabel(item: EvidenceItem) {
  if (item.freshness_unknown) {
    const present = [
      item.valid_from ? `from ${item.valid_from}` : '',
      item.valid_until ? `until ${item.valid_until}` : '',
    ].filter(Boolean).join(' · ');
    return present ? `${present} · freshness unknown` : 'Freshness unknown';
  }
  return `${item.valid_from} – ${item.valid_until}`;
}

export default function EvidenceManager() {
  const [items, setItems] = useState<EvidenceItem[]>([]);
  const [selected, setSelected] = useState<EvidenceHistory | null>(null);
  const [title, setTitle] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [validFrom, setValidFrom] = useState('');
  const [validUntil, setValidUntil] = useState('');
  const [dirtyDates, setDirtyDates] = useState<{ valid_from: boolean; valid_until: boolean }>({ valid_from: false, valid_until: false });
  const [reason, setReason] = useState('');
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [acting, setActing] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [showUpload, setShowUpload] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await getEvidence());
      setError('');
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'Evidence could not be loaded.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
    setUploading(true);
    setError('');
    setSuccess('');
    try {
      await uploadEvidence({
        file,
        title,
        ...(validFrom ? { valid_from: validFrom } : {}),
        ...(validUntil ? { valid_until: validUntil } : {}),
      });
      setTitle('');
      setFile(null);
      setValidFrom('');
      setValidUntil('');
      setSuccess('Evidence uploaded and recorded as Uploaded. It still needs review and approval.');
      setShowUpload(false);
      const input = document.getElementById('evidence-file') as HTMLInputElement | null;
      if (input) input.value = '';
      await refresh();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'Evidence could not be uploaded.');
    } finally {
      setUploading(false);
    }
  }

  async function openHistory(id: string) {
    setError('');
    setSuccess('');
    try {
      const history = await getEvidenceHistory(id);
      setSelected(history);
      setValidFrom(history.evidence.valid_from ?? '');
      setValidUntil(history.evidence.valid_until ?? '');
      setDirtyDates({ valid_from: false, valid_until: false });
      setReason('');
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'Evidence history could not be loaded.');
    }
  }

  async function performAction(action: () => Promise<EvidenceItem>, message: string) {
    if (!selected) return;
    setActing(true);
    setError('');
    setSuccess('');
    try {
      await action();
      await refresh();
      setSelected(await getEvidenceHistory(selected.evidence.id));
      setSuccess(message);
      setReason('');
      setDirtyDates({ valid_from: false, valid_until: false });
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'The evidence change could not be saved.');
    } finally {
      setActing(false);
    }
  }

  async function submitValidity(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || (!dirtyDates.valid_from && !dirtyDates.valid_until)) return;
    const payload: { valid_from?: string | null; valid_until?: string | null } = {};
    if (dirtyDates.valid_from) payload.valid_from = validFrom || null;
    if (dirtyDates.valid_until) payload.valid_until = validUntil || null;
    await performAction(
      () => updateEvidenceValidity(selected.evidence.id, payload),
      'A new immutable version was created. It is ineligible until that exact version is explicitly approved.',
    );
  }

  return (
    <main className="page-shell governance-page">
      <header className="topbar">
        <Link className="brand" to="/" aria-label="VerityAI home"><span className="brand-mark">V</span><span>VerityAI</span></Link>
        <nav className="topbar-nav evidence-nav" aria-label="Primary navigation">
          <Link to="/">Intake</Link><Link to="/evidence" aria-current="page">Evidence Repository</Link><Link to="/governance">Governance insights</Link>
        </nav>
      </header>

      <div className="governance-heading">
        <div><p className="eyebrow">Workspace sources</p><h1>Evidence repository</h1><p className="lead">Manage the documents reviewers can use as approved support.</p></div>
        <button className="button button-primary" type="button" onClick={() => setShowUpload((value) => !value)}>
          {showUpload ? 'Close upload' : 'Upload new evidence'}
        </button>
      </div>

      {error && <p className="inline-error" role="alert">{error}</p>}
      {success && <p className="inline-success" role="status">{success}</p>}

      {showUpload && (
        <form className="panel evidence-upload-form" onSubmit={handleUpload}>
          <h2>Upload evidence document</h2>
          <label htmlFor="evidence-title">Document title</label>
          <input id="evidence-title" value={title} onChange={(event) => setTitle(event.target.value)} required maxLength={300} />
          <label htmlFor="evidence-file">PDF or DOCX file</label>
          <input id="evidence-file" type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={(event) => setFile(event.target.files?.[0] ?? null)} required />
          <div className="evidence-date-fields">
            <div><label htmlFor="valid-from">Valid from</label><input id="valid-from" type="date" value={validFrom} onChange={(event) => setValidFrom(event.target.value)} /></div>
            <div><label htmlFor="valid-until">Valid until</label><input id="valid-until" type="date" value={validUntil} onChange={(event) => setValidUntil(event.target.value)} /></div>
          </div>
          <p className="metric-caption">Uploading does not approve evidence. Missing validity dates are shown as freshness unknown.</p>
          <button className="button button-primary" type="submit" disabled={uploading || !file}>{uploading ? 'Uploading…' : 'Upload evidence'}</button>
        </form>
      )}

      {loading ? <div className="dashboard-state" role="status">Loading evidence…</div> : items.length ? (
        <section className="evidence-grid" aria-label="Evidence documents">
          {items.map((item) => (
            <article className="evidence-card" key={item.id}>
              <div className="evidence-card-heading"><span className="metric-icon icon-blue" aria-hidden="true">▤</span><span className="evidence-state">{item.primary_lifecycle_state}</span></div>
              <h2>{item.title ?? 'Untitled evidence'}</h2>
              <p className="metric-caption">Version {item.version_number ?? '—'}</p>
              <p className="evidence-validity"><strong>Validity</strong><span>{validityLabel(item)}</span></p>
              {item.is_inactive && <p className="evidence-condition">Inactive</p>}
              {item.has_open_manual_conflict && <p className="evidence-condition">Conflict flagged · unresolved</p>}
              {item.is_expired && <p className="evidence-condition">Expired</p>}
              {item.not_yet_valid && <p className="evidence-condition">Not yet effective</p>}
              {item.pending_reapproval && <p className="decision-warning">This version is ineligible until explicitly approved.</p>}
              {!item.is_eligible && item.eligibility_reasons.map((reason) => <p className="metric-caption" key={reason}>{reason}</p>)}
              <p className="metric-caption">Uploaded {new Date(item.created_at).toLocaleDateString()}</p>
              <button className="button button-secondary" type="button" onClick={() => void openHistory(item.id)}>View history and actions</button>
            </article>
          ))}
        </section>
      ) : <div className="dashboard-state">No evidence has been uploaded to this workspace yet.</div>}

      {selected && (
        <section className="panel evidence-history" aria-labelledby="evidence-history-title">
          <div className="panel-heading">
            <div><p className="eyebrow">Evidence governance</p><h2 id="evidence-history-title">{selected.evidence.title} · Version {selected.evidence.version_number}</h2></div>
            <button className="button button-secondary" type="button" onClick={() => setSelected(null)}>Close details</button>
          </div>
          <p>Primary lifecycle: <strong>{selected.evidence.primary_lifecycle_state}</strong>. Validity: {validityLabel(selected.evidence)}.</p>
          {selected.evidence.pending_reapproval && <p className="decision-warning">This exact version is pending explicit re-approval and is not eligible as support.</p>}
          {selected.evidence.is_inactive && <p className="evidence-condition">Inactive evidence is not eligible as support. Clearing Inactive remains unavailable pending product decision.</p>}
          {selected.evidence.has_open_manual_conflict && <p className="evidence-condition">An unresolved manual conflict blocks eligibility. Conflict creation and resolution controls remain unavailable pending product decision.</p>}
          {!selected.evidence.is_eligible && selected.evidence.eligibility_reasons.map((reason) => <p className="metric-caption" key={reason}>{reason}</p>)}
          {selected.evidence.available_actions.length === 0 && <p className="metric-caption">Lifecycle actions are unavailable for this account or current evidence state. The backend enforces workspace permissions.</p>}

          <div className="decision-buttons" aria-label="Available evidence lifecycle actions">
            {selected.evidence.available_actions.includes('review') && <button className="button button-secondary" type="button" disabled={acting} onClick={() => void performAction(() => reviewEvidence(selected.evidence.id, reason || undefined), 'Evidence marked Reviewed.')}>Mark reviewed</button>}
            {selected.evidence.available_actions.includes('approve') && <button className="button button-primary" type="button" disabled={acting} onClick={() => void performAction(() => approveEvidence(selected.evidence.id, reason || undefined), selected.evidence.pending_reapproval ? 'This exact version was explicitly re-approved.' : 'Evidence approved.')}>Approve current version</button>}
            {selected.evidence.available_actions.includes('mark_inactive') && <button className="button button-secondary" type="button" disabled={acting || !reason.trim()} onClick={() => void performAction(() => markEvidenceInactive(selected.evidence.id, reason), 'Evidence marked Inactive.')}>Mark inactive</button>}
          </div>
          {selected.evidence.available_actions.some((action) => action === 'review' || action === 'approve' || action === 'mark_inactive') && (
            <div className="decision-fields"><label htmlFor="evidence-action-reason">Action note or Inactive reason</label><textarea id="evidence-action-reason" value={reason} onChange={(event) => setReason(event.target.value)} rows={2} /></div>
          )}

          {selected.evidence.available_actions.includes('update_validity') && (
            <form className="evidence-date-fields" onSubmit={submitValidity}>
              <div><label htmlFor="revise-valid-from">Revise valid from</label><input id="revise-valid-from" type="date" value={validFrom} onChange={(event) => { setValidFrom(event.target.value); setDirtyDates((state) => ({ ...state, valid_from: true })); }} /></div>
              <div><label htmlFor="revise-valid-until">Revise valid until</label><input id="revise-valid-until" type="date" value={validUntil} onChange={(event) => { setValidUntil(event.target.value); setDirtyDates((state) => ({ ...state, valid_until: true })); }} /></div>
              <button className="button button-secondary" type="submit" disabled={acting || (!dirtyDates.valid_from && !dirtyDates.valid_until)}>Save as new version</button>
            </form>
          )}

          <h3>Version history</h3>
          <ol>{selected.versions.map((version) => (
            <li key={version.version_id ?? version.version_number}>
              Version {version.version_number} · created {version.version_created_at ? new Date(version.version_created_at).toLocaleString() : '—'} · {validityLabel(version)}
              {version.pending_reapproval && ' · Re-approval required'}
              {version.has_open_manual_conflict && ' · Conflict flagged'}
              {!version.is_current_version && ' · Historical only / excluded from new analyses'}
            </li>
          ))}</ol>
          <h3>Transition history</h3>
          {selected.lifecycle_events.length ? <ol>{selected.lifecycle_events.map((event) => (
            <li key={event.id}>
              {event.event_type.replaceAll('_', ' ')} · {new Date(event.occurred_at).toLocaleString()} · actor {event.actor_membership_id.slice(0, 8)}
              {event.version_id && ` · version ${event.version_id.slice(0, 8)}`}
              {event.reason && <p>{event.reason}</p>}
            </li>
          ))}</ol> : <p>No lifecycle events have been recorded.</p>}
          <h3>Manual conflicts</h3>
          {selected.conflicts.length ? <ul>{selected.conflicts.map((conflict) => (
            <li key={conflict.id}>{conflict.state} · versions {conflict.version_ids.map((id) => id.slice(0, 8)).join(', ')}{conflict.rationale && ` · ${conflict.rationale}`}</li>
          ))}</ul> : <p>No manual conflicts are recorded.</p>}
        </section>
      )}
    </main>
  );
}
