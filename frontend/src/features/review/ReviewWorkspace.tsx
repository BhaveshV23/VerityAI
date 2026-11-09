import { useEffect, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import { ApiError, getAnalysisFindings, getAnalysisRuns, getReviewEligibility } from '../../api/client';
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
      try {
        const runs = await getAnalysisRuns(versionId);
        const currentEligibility = await getReviewEligibility(versionId);
        if (!isCurrent) return;
        setEligibility(currentEligibility);
        const latestRun = runs[0];
        if (!latestRun) {
          setFindings([]);
          setAnalysisState(locationState?.analysisStatus ?? null);
          return;
        }
        setRunNumber(latestRun.run_number);
        setAnalysisRunId(latestRun.id);
        setAnalysisState(latestRun.overall_state);
        setAnalysisStages(latestRun.stage_results);
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
