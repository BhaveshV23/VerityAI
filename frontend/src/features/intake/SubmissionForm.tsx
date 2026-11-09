import { useState } from 'react';
import type { FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { ApiError, createDocumentSubmission, createSubmission, demoTenant } from '../../api/client';
import Navbar from '../../components/Navbar';

type SourceMode = 'text' | 'document';

export default function SubmissionForm() {
  const [text, setText] = useState('');
  const [sourceMode, setSourceMode] = useState<SourceMode>('text');
  const [file, setFile] = useState<File | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');
  const navigate = useNavigate();

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setIsSubmitting(true);
    try {
      const result = sourceMode === 'text'
        ? await createSubmission(text)
        : await createDocumentSubmission(file as File);
      const submittedText = result.extracted_text ?? text;
      sessionStorage.setItem(`verityai:submission:${result.version_id}`, submittedText);
      sessionStorage.setItem(`verityai:extraction:${result.version_id}`, result.extraction_status);
      navigate(`/review/${result.submission_id}/${result.version_id}`, {
        state: {
          submittedText,
          analysisStatus: result.analysis_status,
          extractionStatus: result.extraction_status,
        },
      });
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'The submission could not be saved. Try again.');
      setIsSubmitting(false);
    }
  }

  return (
    <main className="page-shell intake-page">
      <Navbar />

      <section className="intake-content">
        <div className="page-heading">
          <p className="eyebrow">New review</p>
          <h1>Check a marketing claim</h1>
          <p className="lead">Paste English copy or upload a PDF/DOCX. Each submission is saved as an immutable version.</p>
        </div>

        <form className="panel submission-form" onSubmit={handleSubmit}>
          <div className="intake-mode" role="group" aria-label="Submission source">
            <button type="button" className={sourceMode === 'text' ? 'button button-secondary' : 'button'} onClick={() => setSourceMode('text')} disabled={isSubmitting}>Paste text</button>
            <button type="button" className={sourceMode === 'document' ? 'button button-secondary' : 'button'} onClick={() => setSourceMode('document')} disabled={isSubmitting}>Upload PDF/DOCX</button>
          </div>
          {sourceMode === 'text' ? <>
            <label htmlFor="submission-text">Content to review</label>
            <textarea
              id="submission-text"
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder="Paste a product description, campaign, or claim here..."
              rows={12}
              minLength={1}
              required
              disabled={isSubmitting}
            />
          </> : <>
            <label htmlFor="submission-file">Choose a PDF or DOCX document</label>
            <input
              id="submission-file"
              type="file"
              accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              required
              disabled={isSubmitting}
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
            <p className="helper-text">Text extraction only; scanned-image OCR is not supported. Current configurable upload default: 10 MiB.</p>
          </>}
          <div className="form-footer">
            <span className="helper-text">{sourceMode === 'text' ? `${text.length.toLocaleString()} characters` : file?.name ?? 'PDF or DOCX, up to the configured limit'}</span>
            <button className="button button-primary" type="submit" disabled={isSubmitting || (sourceMode === 'text' ? !text.trim() : !file)}>
              {isSubmitting ? 'Submitting...' : 'Start review'}
              {!isSubmitting && <span aria-hidden="true">→</span>}
            </button>
          </div>
          {error && <p className="inline-error" role="alert">{error}</p>}
          {isSubmitting && (
            <div className="loading-state" role="status" aria-live="polite">
              <span className="spinner" aria-hidden="true" />
              <span>
                <strong>{sourceMode === 'document' ? 'Uploading and extracting document...' : 'Submitting text and analyzing...'}</strong>
                <small>Analysis runs in this request. The review workspace shows the returned stage status.</small>
              </span>
            </div>
          )}
        </form>

        {(!demoTenant.organizationId || !demoTenant.workspaceId) && (
          <p className="setup-note">
            Add <code>VITE_ORGANIZATION_ID</code> and <code>VITE_WORKSPACE_ID</code> to <code>frontend/.env.local</code>, then restart Vite. Add <code>VITE_USER_ID</code> when using a specific development member.
          </p>
        )}
      </section>
    </main>
  );
}
