"""Renders a compiled AssessmentReport (or just its final migration plan) to a
downloadable PDF via ReportLab (pure-Python, no native/system libraries -
unlike WeasyPrint, which needs Pango/Cairo present on the host - so it
installs the same way on a Windows dev box and the Ubuntu Lightsail deploy
target)."""

from __future__ import annotations

import io
import re
from typing import List, Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.entities.assessment import Assessment
from app.entities.report import AssessmentReport

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_CODE_RE = re.compile(r"`([^`]+)`")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)([^*]+?)(?<!\*)\*(?!\*)")
_HEADER_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^[-*+]\s+(.*)$")
_NUMBERED_RE = re.compile(r"^(\d+)\.\s+(.*)$")


def _inline_markdown(text: str) -> str:
    """Converts common inline markdown (bold/italic/code) to ReportLab's small
    built-in Paragraph markup subset. Escapes first so literal &/</> in the
    source text can't be misread as markup, then injects our own safe tags -
    order matters: bold before italic, so a consumed `**pair**` never leaves
    behind single `*`s for the italic regex to mis-match."""
    escaped = escape(text)
    escaped = _BOLD_RE.sub(r"<b>\1</b>", escaped)
    escaped = _CODE_RE.sub(r'<font face="Courier">\1</font>', escaped)
    escaped = _ITALIC_RE.sub(r"<i>\1</i>", escaped)
    return escaped


def _markdown_flowables(text: str, style: ParagraphStyle, bullet_style: ParagraphStyle) -> List[Flowable]:
    """Converts a small, LLM-typical markdown subset (headers, bold/italic/
    code, bullet/numbered lists, plain paragraphs) into ReportLab flowables.
    Paragraph only supports *inline* markup - block structure (headings,
    list items) has to become separate Paragraph flowables, not tags."""
    flowables: List[Flowable] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        header_match = _HEADER_RE.match(line)
        bullet_match = _BULLET_RE.match(line)
        numbered_match = _NUMBERED_RE.match(line)
        if header_match:
            flowables.append(Paragraph(f"<b>{_inline_markdown(header_match.group(2))}</b>", style))
        elif bullet_match:
            flowables.append(Paragraph(_inline_markdown(bullet_match.group(1)), bullet_style, bulletText="•"))
        elif numbered_match:
            flowables.append(
                Paragraph(_inline_markdown(numbered_match.group(2)), bullet_style, bulletText=f"{numbered_match.group(1)}.")
            )
        else:
            flowables.append(Paragraph(_inline_markdown(line), style))
    return flowables or [Paragraph("", style)]


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    """Single-line/no-markdown-structure text - just inline formatting."""
    return Paragraph(_inline_markdown(text), style)


def _header_block(assessment: Assessment, report: AssessmentReport, styles) -> List[Flowable]:
    return [
        _p("Migration Assessment Report", styles["Title"]),
        _p(f"{assessment.customer_name} — {assessment.project_name} (target: {assessment.target_cloud})", styles["Normal"]),
        Spacer(1, 6),
        _p(
            f"Generated {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')} · Version "
            f"{report.current_version} · Readiness score {report.readiness_score}/100",
            styles["Normal"],
        ),
        Spacer(1, 16),
    ]


def build_report_pdf(assessment: Assessment, report: AssessmentReport) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        title=f"Migration Assessment Report - {assessment.project_name}",
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )
    styles = getSampleStyleSheet()
    bullet_style = ParagraphStyle("BulletBody", parent=styles["BodyText"], leftIndent=14, bulletIndent=0)
    story: List[Flowable] = []

    story.extend(_header_block(assessment, report, styles))

    story.append(_p("Executive Summary", styles["Heading2"]))
    story.extend(_markdown_flowables(report.executive_summary, styles["BodyText"], bullet_style))
    story.append(Spacer(1, 14))

    story.append(_p("Risk Summary", styles["Heading2"]))
    if report.risk_summary:
        rows = [[_p(str(key), styles["BodyText"]), _p(str(value), styles["BodyText"])] for key, value in report.risk_summary.items()]
        table = Table([["Field", "Value"]] + rows, colWidths=[180, 300])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                ]
            )
        )
        story.append(table)
    else:
        story.append(_p("No risk summary available.", styles["BodyText"]))
    story.append(Spacer(1, 14))

    story.append(_p("Migration Waves", styles["Heading2"]))
    if report.migration_waves:
        for wave in report.migration_waves:
            components = ", ".join(wave.get("components") or [])
            story.append(_p(f"Wave {wave.get('wave_number')}: {components}", styles["Heading4"]))
            story.append(_p(f"Rationale: {wave.get('rationale') or 'n/a'}", styles["BodyText"]))
            story.append(_p(f"Risk: {wave.get('risk_summary') or 'n/a'}", styles["BodyText"]))
            story.append(Spacer(1, 6))
    else:
        story.append(_p("No migration waves recorded.", styles["BodyText"]))
    story.append(Spacer(1, 14))

    story.append(_p("Recommendations", styles["Heading2"]))
    if report.recommendations:
        for rec in report.recommendations:
            story.append(Paragraph(_inline_markdown(rec), bullet_style, bulletText="•"))
    else:
        story.append(_p("No recommendations recorded.", styles["BodyText"]))

    if report.final_migration_plan:
        story.append(Spacer(1, 14))
        story.append(_p("Final Migration Plan", styles["Heading2"]))
        story.extend(_markdown_flowables(report.final_migration_plan.get("strategy", ""), styles["BodyText"], bullet_style))

    if report.feedback_rating or report.feedback_comment:
        story.append(Spacer(1, 14))
        story.append(_p("Human Feedback", styles["Heading2"]))
        story.append(_p(f"Rating: {report.feedback_rating or 'n/a'}", styles["BodyText"]))
        if report.feedback_comment:
            story.append(_p(report.feedback_comment, styles["BodyText"]))

    doc.build(story)
    return buffer.getvalue()


def build_migration_plan_pdf(assessment: Assessment, report: AssessmentReport) -> Optional[bytes]:
    """Renders just the final migration plan (not the whole report) - for the
    dedicated 'Download plan PDF' action. Returns None if no plan has been
    generated yet; the caller is responsible for turning that into a 400."""
    if not report.final_migration_plan:
        return None

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        title=f"Final Migration Plan - {assessment.project_name}",
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )
    styles = getSampleStyleSheet()
    bullet_style = ParagraphStyle("BulletBody", parent=styles["BodyText"], leftIndent=14, bulletIndent=0)
    story: List[Flowable] = []

    story.append(_p("Final Migration Plan", styles["Title"]))
    story.extend(_header_block(assessment, report, styles)[1:])  # skip the generic report title above
    story.extend(_markdown_flowables(report.final_migration_plan.get("strategy", ""), styles["BodyText"], bullet_style))

    doc.build(story)
    return buffer.getvalue()
