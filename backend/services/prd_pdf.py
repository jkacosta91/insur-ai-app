from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Iterable

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


def build_prd_pdf_bytes(
    prd_text: str,
    document_name: str = "PRD_Analisis_Inmobiliario",
    provider: str = "openai",
) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=16 * mm,
        title=document_name,
        author="Grupo Insur AI Decision App",
    )

    styles = _build_styles()
    content = []
    today = datetime.now().strftime("%d/%m/%Y %H:%M")

    content.append(Paragraph("GRUPO INSUR · PRD EJECUTIVO", styles["title"]))
    content.append(Paragraph(f"Documento: {document_name}", styles["meta"]))
    content.append(Paragraph(f"Generado: {today} · provider: {provider}", styles["meta"]))
    content.append(Spacer(1, 8))

    for line in _normalize_lines(prd_text):
        if not line.strip():
            content.append(Spacer(1, 3))
            continue
        if line.startswith("# "):
            content.append(Paragraph(_escape(line[2:].strip()), styles["h1"]))
            content.append(Spacer(1, 4))
            continue
        if line.startswith("## "):
            content.append(Paragraph(_escape(line[3:].strip()), styles["h2"]))
            content.append(Spacer(1, 3))
            continue
        if line.startswith("### "):
            content.append(Paragraph(_escape(line[4:].strip()), styles["h3"]))
            content.append(Spacer(1, 2))
            continue
        if line.startswith("- "):
            content.append(Paragraph(f"• {_escape(line[2:].strip())}", styles["bullet"]))
            continue
        if line.startswith("|"):
            content.append(Paragraph(_escape(line), styles["table_line"]))
            continue
        content.append(Paragraph(_escape(line), styles["body"]))

    doc.build(content)
    return buffer.getvalue()


def _build_styles():
    base = getSampleStyleSheet()
    title = ParagraphStyle(
        "title",
        parent=base["Title"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=18,
        textColor=colors.HexColor("#102C45"),
    )
    meta = ParagraphStyle(
        "meta",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#5E6B77"),
    )
    h1 = ParagraphStyle(
        "h1",
        parent=base["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
        textColor=colors.HexColor("#102C45"),
        spaceBefore=4,
    )
    h2 = ParagraphStyle(
        "h2",
        parent=base["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=14,
        textColor=colors.HexColor("#1D3E5C"),
        spaceBefore=3,
    )
    h3 = ParagraphStyle(
        "h3",
        parent=base["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#1D3E5C"),
    )
    body = ParagraphStyle(
        "body",
        parent=base["BodyText"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=13,
        textColor=colors.HexColor("#1B2733"),
    )
    bullet = ParagraphStyle(
        "bullet",
        parent=body,
        leftIndent=8,
    )
    table_line = ParagraphStyle(
        "table_line",
        parent=body,
        fontName="Courier",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#2F3B46"),
    )
    return {
        "title": title,
        "meta": meta,
        "h1": h1,
        "h2": h2,
        "h3": h3,
        "body": body,
        "bullet": bullet,
        "table_line": table_line,
    }


def _normalize_lines(text: str) -> Iterable[str]:
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
