from datetime import datetime, timezone
from io import BytesIO

from pypdf import PdfReader

from app.modules.reports.detailed_schemas import DetailedReport
from app.modules.reports.pdf import build_detailed_report_pdf


def test_pdf_contains_all_detailed_report_sections_and_snapshot_facts():
    report = DetailedReport(
        schema_version="1.0",
        report_id="report-pdf-test",
        report_version=1,
        submission_version_id="version-pdf-test",
        analysis_run_id="run-pdf-test",
        snapshot_generated_at=datetime(2026, 11, 11, tzinfo=timezone.utc),
        generated_at=datetime(2026, 11, 11, tzinfo=timezone.utc),
        organization_name="Example Organization",
        workspace_name="Compliance Workspace",
        submission_id="submission-pdf-test",
        executive_summary="The immutable snapshot records a supported result and a material evidence gap.",
        verification_overview="Two claims were reviewed using saved deterministic results.",
        counts={
            "claims_analyzed": 2, "findings": 2, "supported_findings": 1,
            "unverified_findings": 1, "policy_findings": 0,
        },
        policy_evaluation={"stage_state": "Succeeded", "policy_finding_count": 0},
        coverage_limitations=["Evidence freshness is unknown."],
        claim_analyses=[{
            "finding_id": "finding-pdf-test",
            "claim_description": "A return below 4% is <guaranteed>.",
            "verification_status": "Unverified claim",
            "deterministic_explanation": "The source did not establish the guarantee.",
            "ai_analysis": "The available record does not support this promise.",
            "ai_limitations": ["No current evidence was available."],
            "supporting_evidence": [],
            "policy_result": {"status": "Not evaluated"},
        }],
        risk_assessment=["The guarantee requires human review."],
        recommendations=["Request dated source records."],
        methodology="The backend saved deterministic checks; Gemini adds explanatory text.",
        evidence_appendix=[{
            "finding_id": "finding-pdf-test",
            "claim_description": "A return below 4% is <guaranteed>.",
            "verification_status": "Unverified claim",
            "evidence_references": [],
        }],
    )

    pdf_bytes = build_detailed_report_pdf(report)
    reader = PdfReader(BytesIO(pdf_bytes))
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert pdf_bytes.startswith(b"%PDF-")
    assert len(reader.pages) >= 2
    for section in (
        "Executive Summary", "Verification Overview", "Detailed Claim-by-Claim Analysis",
        "Risk and Compliance Assessment", "Recommendations", "Methodology",
        "Evidence and Limitations Appendix", "AI-generated guidance",
    ):
        assert section in extracted
    assert "Unverified claim" in extracted
    assert "Evidence freshness is unknown." in extracted
    assert "Page 1" in extracted
