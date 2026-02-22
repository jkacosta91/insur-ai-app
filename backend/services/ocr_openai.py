from __future__ import annotations

import base64
import io
import os
from typing import Any, Dict

import requests

try:
    import pypdfium2 as pdfium  # type: ignore
    _HAS_PDFIUM = True
except Exception:
    pdfium = None  # type: ignore[assignment]
    _HAS_PDFIUM = False

try:
    from PIL import Image
    _HAS_PIL = True
except Exception:
    Image = None  # type: ignore[assignment]
    _HAS_PIL = False


OPENAI_URL = "https://api.openai.com/v1/chat/completions"


def ocr_pdf_with_openai(
    pdf_path: str,
    max_pages: int = 4,
    timeout: int = 60,
) -> Dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return {"ok": False, "reason": "missing_openai_api_key", "text": "", "pages_ocrd": 0}
    if not (_HAS_PDFIUM and _HAS_PIL):
        return {
            "ok": False,
            "reason": "missing_ocr_dependencies:pypdfium2_or_pillow",
            "text": "",
            "pages_ocrd": 0,
        }

    model = os.getenv("OPENAI_OCR_MODEL", "gpt-4.1-mini")
    try:
        pdf = pdfium.PdfDocument(pdf_path)
    except Exception as exc:
        return {"ok": False, "reason": f"pdf_open_failed:{type(exc).__name__}", "text": "", "pages_ocrd": 0}

    total_pages = len(pdf)
    pages_to_process = max(0, min(int(max_pages), total_pages))
    chunks: list[str] = []
    ocrd = 0

    for page_index in range(pages_to_process):
        try:
            page = pdf[page_index]
            bitmap = page.render(scale=2.0)
            pil_image = bitmap.to_pil().convert("RGB")
            text = _ocr_image_with_openai(
                image=pil_image,
                api_key=api_key,
                model=model,
                timeout=timeout,
            )
            page.close()
            if text and text.strip():
                ocrd += 1
                chunks.append(f"[PAGE {page_index + 1}]\n{text.strip()}")
        except Exception:
            continue

    merged = "\n\n".join(chunks).strip()
    return {
        "ok": bool(merged),
        "reason": "ok" if merged else "ocr_no_text_detected",
        "text": merged,
        "pages_ocrd": ocrd,
        "pages_processed": pages_to_process,
        "total_pages": total_pages,
        "engine": "openai_vision",
        "model": model,
    }


def _ocr_image_with_openai(
    image: Any,
    api_key: str,
    model: str,
    timeout: int,
) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    data_uri = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")

    body = {
        "model": model,
        "temperature": 0,
        "max_completion_tokens": 1400,
        "messages": [
            {
                "role": "system",
                "content": "Extrae texto literal de imagenes. Responde solo texto plano sin markdown.",
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Extrae todo el texto visible de esta pagina PDF en espanol. "
                            "No resumas. No inventes valores. Conserva numeros y tablas en formato texto."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": data_uri, "detail": "high"},
                    },
                ],
            },
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "content-type": "application/json",
    }
    response = requests.post(OPENAI_URL, headers=headers, json=body, timeout=timeout)
    if response.status_code != 200:
        return ""
    try:
        payload = response.json()
    except ValueError:
        return ""
    return _extract_text(payload)


def _extract_text(payload: Dict[str, Any]) -> str:
    choices = payload.get("choices", [])
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message", {}) if isinstance(first, dict) else {}
    content = message.get("content", "") if isinstance(message, dict) else ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                txt = item.get("text")
                if isinstance(txt, str):
                    texts.append(txt)
        return "\n".join(texts).strip()
    return ""
