import { Navigate, Route, Routes } from 'react-router-dom';
import SubmissionForm from './features/intake/SubmissionForm';
import ReviewWorkspace from './features/review/ReviewWorkspace';
import MetricsDashboard from './features/governance/MetricsDashboard';
import EvidenceManager from './features/evidence/EvidenceManager';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<SubmissionForm />} />
      <Route path="/review/:submissionId/:versionId" element={<ReviewWorkspace />} />
      <Route path="/governance" element={<MetricsDashboard />} />
      <Route path="/evidence" element={<EvidenceManager />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
