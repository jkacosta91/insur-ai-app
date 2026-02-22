from __future__ import annotations

import os
import re
from typing import Any

from backend.services.ocr_openai import ocr_pdf_with_openai

try:
    import pdfplumber

    _HAS_PDFPLUMBER = True
except ImportError:
    _HAS_PDFPLUMBER = False

try:
    from pypdf import PdfReader

    _HAS_PYPDF = True
except ImportError:
    PdfReader = None  # type: ignore[assignment]
    _HAS_PYPDF = False

_RE_WINDOWS_NEWLINE = re.compile(r"\r\n?")
_RE_SPACES = re.compile(r"[ \t]+")
_RE_MANY_NEWLINES = re.compile(r"\n{3,}")
_RE_TOKENS = re.compile(r"\S+")


def _min_chars_required() -> int:
    raw = os.getenv("MIN_EXTRACT_CHARS", "180")
    try:
        return max(40, int(raw))
    except ValueError:
        return 180


def extract_pdf(pdf_path: str) -> dict[str, Any]:
    """
    Extract text, tables, and metadata from a PDF.
    Uses pdfplumber first (better text + tables), then pypdf fallback.
    """
    if _HAS_PDFPLUMBER:
        extracted = _extract_pdfplumber(pdf_path)
        if extracted.get("char_count", 0) <= 0:
            extracted = _extract_pypdf(pdf_path)
    elif _HAS_PYPDF:
        extracted = _extract_pypdf(pdf_path)
    else:
        extracted = {
            "page_count": 0,
            "pages": [],
            "tables": [],
            "full_text": "",
            "char_count": 0,
            "has_tables": False,
            "extraction_engine": "missing_dependencies",
            "metadata": {},
        }

    # OCR fallback when textual extraction is too weak.
    if extracted.get("char_count", 0) < _min_chars_required():
        max_pages_raw = os.getenv("OPENAI_OCR_MAX_PAGES", "5")
        try:
            max_pages = max(1, min(12, int(max_pages_raw)))
        except ValueError:
            max_pages = 5

        ocr = ocr_pdf_with_openai(pdf_path=pdf_path, max_pages=max_pages, timeout=75)
        if ocr.get("ok"):
            merged = _clean_text(
                "\n\n".join(
                    part for part in [extracted.get("full_text", ""), ocr.get("text", "")] if part
                ).strip()
            )
            extracted["full_text"] = merged
            extracted["char_count"] = len(merged)
            extracted["extraction_engine"] = f"{extracted.get('extraction_engine', 'unknown')}+openai_vision"
            extracted["ocr_applied"] = True
            extracted["ocr_engine"] = "openai_vision"
            extracted["ocr_pages"] = int(ocr.get("pages_ocrd", 0) or 0)
        else:
            extracted["ocr_applied"] = False
            extracted["ocr_engine"] = None
            extracted["ocr_pages"] = 0
            extracted["ocr_error"] = str(ocr.get("reason") or "ocr_unavailable")
    else:
        extracted["ocr_applied"] = False
        extracted["ocr_engine"] = None
        extracted["ocr_pages"] = 0

    return _attach_quality(extracted)


def _extract_pdfplumber(pdf_path: str) -> dict[str, Any]:
    pages: list[dict] = []
    all_tables: list[dict] = []

    try:
        with pdfplumber.open(pdf_path) as pdf:
            metadata = _read_metadata(dict(pdf.metadata or {}))

            for i, page in enumerate(pdf.pages):
                text = (page.extract_text(x_tolerance=2, y_tolerance=2) or "").strip()
                text = _clean_text(text)

                raw_tables = page.extract_tables() or []
                page_tables = []
                for table in raw_tables:
                    cleaned = _clean_table(table)
                    if cleaned:
                        page_tables.append(cleaned)
                        all_tables.append({"page": i + 1, "rows": cleaned})

                pages.append({"page": i + 1, "text": text, "tables": page_tables})

    except Exception:
        return _extract_pypdf(pdf_path)

    full_text = _join_pages(pages)
    return {
        "page_count": len(pages),
        "pages": pages,
        "tables": all_tables,
        "full_text": full_text,
        "char_count": len(full_text),
        "has_tables": bool(all_tables),
        "extraction_engine": "pdfplumber",
        "metadata": metadata,
    }


def _extract_pypdf(pdf_path: str) -> dict[str, Any]:
    if not _HAS_PYPDF or PdfReader is None:
        return {
            "page_count": 0,
            "pages": [],
            "tables": [],
            "full_text": "",
            "char_count": 0,
            "has_tables": False,
            "extraction_engine": "missing_dependencies",
            "metadata": {},
        }

    try:
        reader = PdfReader(pdf_path)
        pages = [
            {"page": i + 1, "text": _clean_text(page.extract_text() or ""), "tables": []}
            for i, page in enumerate(reader.pages)
        ]
        meta = reader.metadata or {}
        metadata = {
            "title": str(meta.get("/Title", "") or "").strip(),
            "author": str(meta.get("/Author", "") or "").strip(),
            "subject": str(meta.get("/Subject", "") or "").strip(),
        }
    except Exception:
        return {
            "page_count": 0,
            "pages": [],
            "tables": [],
            "full_text": "",
            "char_count": 0,
            "has_tables": False,
            "extraction_engine": "error",
            "metadata": {},
        }

    full_text = _join_pages(pages)
    return {
        "page_count": len(pages),
        "pages": pages,
        "tables": [],
        "full_text": full_text,
        "char_count": len(full_text),
        "has_tables": False,
        "extraction_engine": "pypdf",
        "metadata": metadata,
    }


def _join_pages(pages: list[dict]) -> str:
    return "\n\n".join(p["text"] for p in pages if p.get("text", "").strip())


def _clean_text(text: str) -> str:
    text = _RE_WINDOWS_NEWLINE.sub("\n", text)
    text = _RE_SPACES.sub(" ", text)
    text = _RE_MANY_NEWLINES.sub("\n\n", text)
    return text.strip()


def _clean_table(table: list) -> list[list[str]]:
    cleaned = [[str(cell).strip() if cell is not None else "" for cell in row] for row in table]
    if not any(cell for row in cleaned for cell in row if cell):
        return []
    return cleaned


def _read_metadata(meta: dict) -> dict[str, str]:
    result: dict[str, str] = {}
    for key in ("title", "author", "subject", "creator"):
        raw = meta.get(f"/{key.capitalize()}") or meta.get(key, "")
        result[key] = str(raw).strip() if raw else ""
    return result


def _attach_quality(extracted: dict[str, Any]) -> dict[str, Any]:
    full_text = _clean_text(str(extracted.get("full_text") or ""))
    char_count = len(full_text)
    token_count = len(_RE_TOKENS.findall(full_text))
    min_chars = _min_chars_required()

    extracted["full_text"] = full_text
    extracted["char_count"] = char_count
    extracted["token_count"] = token_count
    extracted["min_chars_required"] = min_chars
    extracted["usable_for_analysis"] = char_count >= min_chars
    extracted["quality_status"] = "ok" if extracted["usable_for_analysis"] else "low_text"
    return extracted


# Backwards-compatible alias

def extract_pdf_text(pdf_path: str) -> dict[str, Any]:
    return extract_pdf(pdf_path)
