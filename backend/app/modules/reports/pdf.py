"""Private, paginated PDF rendering for validated detailed report data."""

from __future__ import annotations

import io
import json
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from reportlab import __file__ as reportlab_module_path
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.modules.reports.detailed_schemas import DetailedReport


INK = colors.HexColor("#17312D")
TEAL = colors.HexColor("#18766A")
MUTED = colors.HexColor("#53635F")
PALE = colors.HexColor("#EDF4F2")
GOLD = colors.HexColor("#BD9447")


def _register_fonts() -> tuple[str, str]:
    font_dir = Path(reportlab_module_path).parent / "fonts"
    regular_path = font_dir / "Vera.ttf"
    bold_path = font_dir / "VeraBd.ttf"
    if regular_path.exists() and bold_path.exists():
        if "VerityVera" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("VerityVera", str(regular_path)))
            pdfmetrics.registerFont(TTFont("VerityVera-Bold", str(bold_path)))
        return "VerityVera", "VerityVera-Bold"
    return "Helvetica", "Helvetica-Bold"


def _safe_paragraph_text(value: object) -> str:
    text = str(value)
    text = "".join(character for character in text if character in "\n\t" or ord(character) >= 32)
    return xml_escape(text).replace("\n", "<br/>").replace("\t", "&#160;&#160;&#160;&#160;")


def _styles(font: str, bold_font: str):
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="VerityTitle", parent=styles["Title"], fontName=bold_font,
        fontSize=24, leading=30, textColor=INK, alignment=TA_LEFT, spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        name="VeritySubtitle", parent=styles["Normal"], fontName=font,
        fontSize=9, leading=14, textColor=MUTED, spaceAfter=12,
    ))
    styles.add(ParagraphStyle(
        name="VeritySection", parent=styles["Heading1"], fontName=bold_font,
        fontSize=14, leading=19, textColor=TEAL, spaceBefore=8, spaceAfter=9,
        keepWithNext=True,
    ))
    styles.add(ParagraphStyle(
        name="VeritySubsection", parent=styles["Heading2"], fontName=bold_font,
        fontSize=10.5, leading=14, textColor=INK, spaceBefore=7, spaceAfter=5,
        keepWithNext=True,
    ))
    styles.add(ParagraphStyle(
        name="VerityBody", parent=styles["BodyText"], fontName=font,
        fontSize=8.7, leading=13, textColor=INK, spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name="VeritySmall", parent=styles["BodyText"], fontName=font,
        fontSize=7.6, leading=10.5, textColor=MUTED, spaceAfter=4,
        wordWrap="CJK",
    ))
    styles.add(ParagraphStyle(
        name="VerityTag", parent=styles["BodyText"], fontName=bold_font,
        fontSize=8, leading=11, textColor=TEAL, spaceAfter=3,
    ))
    styles.add(ParagraphStyle(
        name="VerityCenter", parent=styles["BodyText"], fontName=font,
        fontSize=8, leading=11, textColor=MUTED, alignment=TA_CENTER,
    ))
    return styles


def _paragraph(value: object, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_safe_paragraph_text(value), style)


def _page_chrome(canvas, document, report: DetailedReport, font: str, bold_font: str) -> None:
    canvas.saveState()
    page_width, page_height = letter
    canvas.setStrokeColor(GOLD)
    canvas.setLineWidth(1.1)
    canvas.line(document.leftMargin, page_height - 0.55 * inch, page_width - document.rightMargin, page_height - 0.55 * inch)
    canvas.setFont(bold_font, 8.5)
    canvas.setFillColor(TEAL)
    canvas.drawString(document.leftMargin, page_height - 0.42 * inch, "VERITYAI  /  DETAILED VERIFICATION REPORT")
    canvas.setStrokeColor(colors.HexColor("#D7E0DD"))
    canvas.setLineWidth(0.5)
    canvas.line(document.leftMargin, 0.53 * inch, page_width - document.rightMargin, 0.53 * inch)
    canvas.setFont(font, 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(document.leftMargin, 0.36 * inch, f"Report {report.report_id}  ·  Snapshot v{report.report_version}")
    canvas.drawRightString(page_width - document.rightMargin, 0.36 * inch, f"Page {document.page}")
    canvas.restoreState()


def build_detailed_report_pdf(report: DetailedReport) -> bytes:
    """Render every detailed-report section from the same validated response model."""
    font, bold_font = _register_fonts()
    styles = _styles(font, bold_font)
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.72 * inch,
        leftMargin=0.72 * inch,
        topMargin=0.82 * inch,
        bottomMargin=0.72 * inch,
        title="VerityAI Detailed Verification Report",
        author="VerityAI",
        subject=f"Paid detailed report for {report.report_id}",
    )
    story = [
        Spacer(1, 0.12 * inch),
        _paragraph("VerityAI Detailed Verification Report", styles["VerityTitle"]),
        _paragraph(
            f"{report.organization_name}  ·  {report.workspace_name}<br/>"
            f"Submission {report.submission_id}  ·  Version {report.submission_version_id}<br/>"
            f"Report {report.report_id}  ·  Generated {report.generated_at.isoformat()}",
            styles["VeritySubtitle"],
        ),
        _paragraph("Executive Summary", styles["VeritySection"]),
        _paragraph(report.executive_summary, styles["VerityBody"]),
        _paragraph("Verification Overview", styles["VeritySection"]),
    ]

    count_rows = [
        ["Claims reviewed", "Findings", "Supported", "Unverified", "Policy findings"],
        [
            str(report.counts.claims_analyzed), str(report.counts.findings),
            str(report.counts.supported_findings), str(report.counts.unverified_findings),
            str(report.counts.policy_findings),
        ],
    ]
    table = Table(count_rows, colWidths=[1.25 * inch] * 5, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PALE),
        ("TEXTCOLOR", (0, 0), (-1, 0), TEAL),
        ("FONTNAME", (0, 0), (-1, 0), bold_font),
        ("FONTNAME", (0, 1), (-1, 1), font),
        ("FONTSIZE", (0, 0), (-1, -1), 7.7),
        ("LEADING", (0, 0), (-1, -1), 11),
        ("TEXTCOLOR", (0, 1), (-1, -1), INK),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D7E0DD")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D7E0DD")),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.extend([table, Spacer(1, 8), _paragraph(report.verification_overview, styles["VerityBody"])])
    if report.coverage_limitations:
        story.append(_paragraph("Coverage and limitations", styles["VeritySubsection"]))
        story.extend(_paragraph(f"• {limitation}", styles["VerityBody"]) for limitation in report.coverage_limitations)

    story.append(PageBreak())
    story.append(_paragraph("Detailed Claim-by-Claim Analysis", styles["VeritySection"]))
    for index, finding in enumerate(report.claim_analyses, start=1):
        story.append(_paragraph(f"{index}. {finding.claim_description}", styles["VeritySubsection"]))
        story.append(_paragraph(f"Deterministic status: {finding.verification_status}", styles["VerityTag"]))
        story.append(_paragraph(f"Verification record: {finding.deterministic_explanation}", styles["VerityBody"]))
        story.append(_paragraph(f"AI-assisted explanation: {finding.ai_analysis}", styles["VerityBody"]))
        if finding.ai_limitations:
            story.append(_paragraph("AI explanation limitations", styles["VeritySubsection"]))
            story.extend(_paragraph(f"• {item}", styles["VeritySmall"]) for item in finding.ai_limitations)
        if finding.supporting_evidence:
            story.append(_paragraph("Supporting evidence references", styles["VeritySubsection"]))
            for evidence in finding.supporting_evidence:
                title = evidence.get("title") or "Untitled evidence"
                details = json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)
                story.append(_paragraph(f"{title}: {details}", styles["VeritySmall"]))
        else:
            story.append(_paragraph("No eligible evidence reference was attached to this finding.", styles["VeritySmall"]))
        if finding.policy_result is not None:
            story.append(_paragraph(
                "Policy result: " + json.dumps(finding.policy_result, ensure_ascii=False, sort_keys=True, default=str),
                styles["VeritySmall"],
            ))
        story.append(Spacer(1, 6))
    if not report.claim_analyses:
        story.append(_paragraph("No findings were recorded in the verified snapshot.", styles["VerityBody"]))

    story.append(PageBreak())
    story.append(_paragraph("Risk and Compliance Assessment", styles["VeritySection"]))
    if report.risk_assessment:
        story.extend(_paragraph(f"• {risk}", styles["VerityBody"]) for risk in report.risk_assessment)
    else:
        story.append(_paragraph("Gemini did not identify additional narrative risks from the saved findings.", styles["VerityBody"]))
    story.append(_paragraph("Recommendations", styles["VeritySection"]))
    story.append(_paragraph(report.recommendation_label, styles["VerityTag"]))
    if report.recommendations:
        story.extend(_paragraph(f"• {recommendation}", styles["VerityBody"]) for recommendation in report.recommendations)
    else:
        story.append(_paragraph("No recommendations were generated.", styles["VerityBody"]))
    story.append(_paragraph("Methodology", styles["VeritySection"]))
    story.append(_paragraph(report.methodology, styles["VerityBody"]))
    story.append(_paragraph(
        "Deterministic policy evaluation: " + json.dumps(report.policy_evaluation, ensure_ascii=False, sort_keys=True, default=str),
        styles["VeritySmall"],
    ))

    story.append(PageBreak())
    story.append(_paragraph("Evidence and Limitations Appendix", styles["VeritySection"]))
    for item in report.evidence_appendix:
        story.append(_paragraph(
            f"Finding {item.get('finding_id')} · {item.get('verification_status')}",
            styles["VeritySubsection"],
        ))
        story.append(_paragraph(str(item.get("claim_description", "")), styles["VerityBody"]))
        references = item.get("evidence_references") or []
        if references:
            story.extend(
                _paragraph(json.dumps(reference, ensure_ascii=False, sort_keys=True, default=str), styles["VeritySmall"])
                for reference in references
            )
        else:
            story.append(_paragraph("No evidence references were attached.", styles["VeritySmall"]))
    story.append(_paragraph("Snapshot limitations", styles["VeritySubsection"]))
    if report.coverage_limitations:
        story.extend(_paragraph(f"• {item}", styles["VerityBody"]) for item in report.coverage_limitations)
    else:
        story.append(_paragraph("No additional snapshot limitations were recorded.", styles["VerityBody"]))
    story.append(Spacer(1, 10))
    story.append(_paragraph(
        "AI-generated narrative and recommendations are explanatory guidance. The deterministic verification "
        "snapshot is authoritative for statuses, counts, evidence references, and policy results.",
        styles["VerityCenter"],
    ))

    chrome = lambda canvas, doc: _page_chrome(canvas, doc, report, font, bold_font)
    document.build(story, onFirstPage=chrome, onLaterPages=chrome)
    return buffer.getvalue()
