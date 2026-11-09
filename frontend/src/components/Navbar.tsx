import { Link, useLocation } from 'react-router-dom';

type PrimarySection = 'intake' | 'evidence' | 'governance';

export default function Navbar() {
  const { pathname } = useLocation();
  const activeSection: PrimarySection = pathname.startsWith('/evidence')
    ? 'evidence'
    : pathname.startsWith('/governance')
      ? 'governance'
      : 'intake';

  return (
    <header className="topbar">
      <Link className="brand" to="/" aria-label="VerityAI home">
        <span className="brand-mark">V</span>
        <span>VerityAI</span>
      </Link>
      <nav className="topbar-nav" aria-label="Primary navigation">
        <Link to="/" aria-current={activeSection === 'intake' ? 'page' : undefined}>Intake</Link>
        <Link to="/evidence" aria-current={activeSection === 'evidence' ? 'page' : undefined}>Evidence Repository</Link>
        <Link to="/governance" aria-current={activeSection === 'governance' ? 'page' : undefined}>Governance Insights</Link>
      </nav>
    </header>
  );
}
