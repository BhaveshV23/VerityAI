import { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import { ApiError, createReportSnapshot, getAnalysisFindings, getAnalysisRuns, getReviewEligibility } from '../../api/client';
import type { AnalysisFinding, AnalysisStageResult, ReviewEligibility } from '../../api/client';
import DocumentViewer from './DocumentViewer';
import DecisionPanel from './DecisionPanel';
import FindingsList from './FindingsList';
import Navbar from '../../components/Navbar';

type ReviewLocationState = {
  submittedText?: string;
  analysisStatus?: 'Running' | 'Succeeded' | 'Incomplete';
  extractionStatus?: 'Not required' | 'Succeeded';
} | null;

type GeneratedReport = { versionId: string; runId: string; reportId: string };

export default function ReviewWorkspace() {
  const { submissionId = '', versionId = '' } = useParams();
  const location = useLocation();
  const locationState = location.state as ReviewLocationState;
  const text = locationState?.submittedText ?? sessionStorage.getItem(`verityai:submission:${versionId}`) ?? '';
  const extractionStatus = locationState?.extractionStatus ?? sessionStorage.getItem(`verityai:extraction:${versionId}`);
  const [findings, setFindings] = useState<AnalysisFinding[]>([]);
  const [analysisRunId, setAnalysisRunId] = useState<string>();
  const [runNumber, setRunNumber] = useState<number>();
  const [analysisState, setAnalysisState] = useState<'Running' | 'Succeeded' | 'Incomplete' | null>(null);
  const [analysisStages, setAnalysisStages] = useState<AnalysisStageResult[]>([]);
  const [eligibility, setEligibility] = useState<ReviewEligibility | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');
  const [report, setReport] = useState<GeneratedReport | null>(null);
  const [reportError, setReportError] = useState('');
  const reportRef = useRef<GeneratedReport | null>(null);

  function updateReport(value: GeneratedReport | null) {
    reportRef.current = value;
    setReport(value);
  }

  useEffect(() => {
    let isCurrent = true;

    async function loadLatestFindings() {
      setIsLoading(true);
      setError('');
      setRunNumber(undefined);
      setAnalysisRunId(undefined);
      setAnalysisState(null);
      setAnalysisStages([]);
      setEligibility(null);
      setReportError('');
      if (reportRef.current && reportRef.current.versionId !== versionId) updateReport(null);
      try {
        const runs = await getAnalysisRuns(versionId);
        if (!isCurrent) return;
        const latestRun = runs[0];
        if (!latestRun) {
          setFindings([]);
          setAnalysisState(locationState?.analysisStatus ?? null);
          setEligibility(null);
          updateReport(null);
          return;
        }
        setRunNumber(latestRun.run_number);
        setAnalysisRunId(latestRun.id);
        setAnalysisState(latestRun.overall_state);
        setAnalysisStages(latestRun.stage_results);
        const existingReport = reportRef.current;
        const reportAlreadyCreated = existingReport?.versionId === versionId
          && existingReport.runId === latestRun.id;
        if (!reportAlreadyCreated) updateReport(null);
        if (latestRun.overall_state === 'Succeeded' && !reportAlreadyCreated) {
          try {
            const created = await createReportSnapshot(versionId, latestRun.id);
            if (!created.report_id) throw new Error('The report service did not return a report ID.');
            if (isCurrent) {
              updateReport({ versionId, runId: latestRun.id, reportId: created.report_id });
              setReportError('');
            }
          } catch (cause) {
            if (isCurrent) {
              setReportError(cause instanceof ApiError
                ? cause.message
                : cause instanceof Error
                  ? cause.message
                  : 'The report could not be created.');
            }
          }
        }
        const currentEligibility = await getReviewEligibility(versionId);
        if (isCurrent) setEligibility(currentEligibility);
        const latestFindings = await getAnalysisFindings(latestRun.id);
        if (isCurrent) setFindings(latestFindings);
      } catch (cause) {
        if (isCurrent) {
          setFindings([]);
          setError(cause instanceof ApiError ? cause.message : 'Analysis findings could not be loaded.');
        }
      } finally {
        if (isCurrent) setIsLoading(false);
      }
    }

    void loadLatestFindings();
    return () => { isCurrent = false; };
  }, [versionId, refreshToken]);

  async function refreshReviewData() {
    setRefreshToken((current) => current + 1);
  }

  return (
    <main className="page-shell review-page">
      <Navbar />

      <div className="review-title-row">
        <div>
          <p className="eyebrow">Submission {submissionId.slice(0, 8) || '—'}</p>
          <h1>Review workspace</h1>
        </div>
        <div className="review-meta">
          <span className="review-status"><span className="status-dot" />In review</span>
          <span>Version {versionId.slice(0, 8) || '—'}</span>
          <Link className="text-link" to="/">← Back to intake</Link>
        </div>
      </div>

      {report && report.versionId === versionId && <section className="report-entry panel">
        <div><p className="eyebrow">Analysis complete</p><h2>Your verification report is ready</h2></div>
        <Link className="button button-primary" to={`/reports/${encodeURIComponent(report.reportId)}`}>View report</Link>
      </section>}
      {reportError && analysisState === 'Succeeded' && <section className="report-entry panel report-entry-error" role="alert">
        <p className="inline-error">Report creation failed: {reportError}</p>
        <button className="button button-secondary" type="button" disabled={isLoading} onClick={() => setRefreshToken((current) => current + 1)}>
          {isLoading ? 'Retrying…' : 'Retry report creation'}
        </button>
      </section>}

      {extractionStatus && extractionStatus !== 'Not required' && (
        <p className="helper-text" role="status">Document extraction: {extractionStatus}</p>
      )}

      <div className="review-grid">
        <DocumentViewer text={text} />
        <aside className="review-sidebar">
          <FindingsList
            findings={findings}
            isLoading={isLoading}
            error={error}
            runNumber={runNumber}
            runId={analysisRunId}
            versionId={versionId}
            analysisState={analysisState}
            onDispositionSaved={refreshReviewData}
          />
          <DecisionPanel
            versionId={versionId}
            findings={findings}
            analysisState={analysisState}
            analysisStages={analysisStages}
            eligibility={eligibility}
            onDecisionSaved={refreshReviewData}
          />
        </aside>
      </div>
    </main>
  );
}
