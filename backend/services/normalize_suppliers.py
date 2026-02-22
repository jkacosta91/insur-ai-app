from __future__ import annotations

import json
import os
import re
from typing import Any

from backend.services.llm_client import send_openai_prompt

_MAX_CHARS = 8000

_EXTRACTION_PROMPT = """\
Eres un extractor de datos estructurados. Analiza el texto del documento y devuelve SOLO un JSON valido, sin texto adicional ni markdown.

Si el documento contiene un informe de proveedores/contratistas, devuelve:
{
  "document_type": "supplier_report",
  "confidence": <0.0-1.0>,
  "suppliers": [
    {
      "supplier_name": "nombre exacto",
      "category": "categoria",
      "annual_volume_eur": <entero o null>,
      "orders": <entero o null>,
      "incidents": <entero o null>,
      "avg_delay_days": <entero o null>,
      "dependency_pct": <entero o null>,
      "estimated_margin_pct": <entero o null>
    }
  ],
  "global_indicators": {
    "avg_dependency_pct": <numero o null>,
    "high_risk_suppliers": <numero o null>,
    "total_incidents": <numero o null>,
    "weighted_avg_delay_days": <numero o null>
  }
}

Si no puedes identificar el tipo de documento, devuelve exactamente:
{"document_type": "unknown", "confidence": 0.0, "suppliers": [], "global_indicators": {}}

DOCUMENTO:
__DOCUMENT_TEXT__
"""

_KNOWN_CATEGORIES = {
    "cemento",
    "hormigon",
    "acero",
    "electricidad",
    "fontaneria",
    "acabados",
    "logistica",
    "construccion",
    "materiales",
    "servicios",
    "transporte",
    "instalaciones",
    "carpinteria",
    "pintura",
    "climatizacion",
}

_HEADER_HINTS = (
    "proveedor",
    "categoria",
    "volumen",
    "pedidos",
    "incidencias",
    "retraso",
    "dependencia",
    "margen",
)

_ROW_WITH_6_NUMBERS = re.compile(
    r"^(?P<prefix>.+?)\s+"
    r"(?P<n1>\d+(?:[.,]\d+)?)\s+"
    r"(?P<n2>\d+(?:[.,]\d+)?)\s+"
    r"(?P<n3>\d+(?:[.,]\d+)?)\s+"
    r"(?P<n4>\d+(?:[.,]\d+)?)\s+"
    r"(?P<n5>\d+(?:[.,]\d+)?)\s+"
    r"(?P<n6>\d+(?:[.,]\d+)?)$"
)


def normalize_supplier_report(full_text: str) -> dict[str, Any]:
    """
    Normalize supplier PDF text.
    Strategy: OpenAI API -> regex fallback.
    """
    if not full_text or not full_text.strip():
        return {"document_type": "unknown", "confidence": 0.0, "suppliers": [], "global_indicators": {}}

    result = _extract_with_claude(full_text)
    if result is not None:
        return result

    return _extract_with_regex(full_text)


def _extract_with_claude(full_text: str) -> dict[str, Any] | None:
    prompt = _EXTRACTION_PROMPT.replace("__DOCUMENT_TEXT__", full_text[:_MAX_CHARS])
    response = send_openai_prompt(
        prompt=prompt,
        model=os.getenv("OPENAI_EXTRACT_MODEL", "gpt-4.1-mini"),
        max_tokens=1500,
        temperature=0,
        timeout=30,
    )
    if not response.get("ok"):
        return None

    try:
        raw_text = response.get("text", "")
        json_str = _extract_json_block(raw_text)
        if not json_str:
            return None
        parsed = json.loads(json_str)
    except (ValueError, KeyError, IndexError):
        return None

    if "document_type" not in parsed:
        return None

    parsed.setdefault("suppliers", [])
    parsed.setdefault("global_indicators", {})

    parsed["suppliers"] = [_coerce_supplier(s) for s in parsed["suppliers"]]
    parsed["global_indicators"] = _coerce_indicators(parsed["global_indicators"])

    return parsed


def _extract_json_block(text: str) -> str | None:
    match = re.search(r"\{[\s\S]*\}", text)
    return match.group() if match else None


def _extract_with_regex(full_text: str) -> dict[str, Any]:
    normalized_text = full_text.replace("\\n", "\n")
    lines = [ln.strip() for ln in re.split(r"\r?\n", normalized_text) if ln.strip()]

    suppliers = _detect_supplier_rows(lines)
    indicators = _detect_global_indicators(lines)

    if suppliers or indicators:
        confidence = min(0.92, 0.35 + len(suppliers) * 0.08 + (0.07 if indicators else 0.0))
        return {
            "document_type": "supplier_report",
            "confidence": round(confidence, 2),
            "suppliers": suppliers,
            "global_indicators": indicators,
        }

    return {
        "document_type": "unknown",
        "confidence": 0.0,
        "suppliers": [],
        "global_indicators": {},
    }


def _detect_supplier_rows(lines: list[str]) -> list[dict[str, Any]]:
    suppliers: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    # Format A: full row in one line
    for line in lines:
        line_low = line.lower()
        if _is_header_line(line_low):
            continue

        match = _ROW_WITH_6_NUMBERS.match(line)
        if not match:
            continue

        prefix = match.group("prefix").strip()
        tokens = prefix.split()
        if len(tokens) < 2:
            continue

        supplier_name, category = _split_name_and_category(tokens)
        if not supplier_name or not category:
            continue

        nums = [_parse_number(match.group(f"n{i}")) for i in range(1, 7)]
        if not all(n is not None for n in nums):
            continue

        key = supplier_name.lower()
        if key in seen_names:
            continue
        seen_names.add(key)

        suppliers.append(
            {
                "supplier_name": supplier_name,
                "category": category,
                "annual_volume_eur": nums[0],
                "orders": nums[1],
                "incidents": nums[2],
                "avg_delay_days": nums[3],
                "dependency_pct": nums[4],
                "estimated_margin_pct": nums[5],
            }
        )

    if suppliers:
        return suppliers

    # Format B: 8-line legacy block
    i = 0
    while i <= len(lines) - 8:
        name = lines[i].strip()
        category = lines[i + 1].strip()
        name_low = name.lower()
        cat_low = category.lower()

        if _is_header_line(name_low) or _is_header_line(cat_low):
            i += 1
            continue
        if len(name) < 3 or name.replace(".", "").isdigit():
            i += 1
            continue
        if not _is_valid_category(cat_low):
            i += 1
            continue

        numeric_slice = lines[i + 2 : i + 8]
        nums = [_parse_number(token) for token in numeric_slice]
        if not all(n is not None for n in nums):
            i += 1
            continue

        suppliers.append(
            {
                "supplier_name": name,
                "category": category,
                "annual_volume_eur": nums[0],
                "orders": nums[1],
                "incidents": nums[2],
                "avg_delay_days": nums[3],
                "dependency_pct": nums[4],
                "estimated_margin_pct": nums[5],
            }
        )
        i += 8

    return suppliers


def _detect_global_indicators(lines: list[str]) -> dict[str, Any]:
    label_map = {
        "dependencia promedio": "avg_dependency_pct",
        "alto riesgo": "high_risk_suppliers",
        "incidencias totales": "total_incidents",
        "retraso medio": "weighted_avg_delay_days",
        "retraso ponderado": "weighted_avg_delay_days",
    }

    indicators: dict[str, Any] = {}
    for i, line in enumerate(lines):
        line_low = line.lower()
        for label, key in label_map.items():
            if label not in line_low:
                continue

            nums_same_line = re.findall(r"-?\d+(?:[.,]\d+)?", line)
            if nums_same_line:
                value = _parse_number(nums_same_line[-1])
                if value is not None:
                    indicators[key] = value
                    continue

            if i + 1 < len(lines):
                value = _parse_number(lines[i + 1])
                if value is not None:
                    indicators[key] = value

    return indicators


def _parse_number(raw: str) -> int | float | None:
    try:
        cleaned = re.sub(r"[^\d,.\-]", "", raw.strip()).replace(",", ".")
        if not cleaned:
            return None
        return int(float(cleaned))
    except Exception:
        return None


def _coerce_supplier(supplier: dict) -> dict:
    int_fields = (
        "annual_volume_eur",
        "orders",
        "incidents",
        "avg_delay_days",
        "dependency_pct",
        "estimated_margin_pct",
    )
    for field in int_fields:
        value = supplier.get(field)
        if value is not None:
            try:
                supplier[field] = int(float(value))
            except (TypeError, ValueError):
                supplier[field] = None
    return supplier


def _coerce_indicators(indicators: dict) -> dict:
    result: dict[str, Any] = {}
    for key, value in indicators.items():
        if value is not None:
            try:
                result[key] = int(float(value))
            except (TypeError, ValueError):
                result[key] = value
        else:
            result[key] = value
    return result


def _is_header_line(line_low: str) -> bool:
    return any(hint in line_low for hint in _HEADER_HINTS)


def _is_valid_category(category_low: str) -> bool:
    return (category_low in _KNOWN_CATEGORIES) or (category_low.isalpha() and 3 <= len(category_low) <= 25)


def _split_name_and_category(tokens: list[str]) -> tuple[str | None, str | None]:
    for cat_len in (2, 1):
        if len(tokens) <= cat_len:
            continue
        cat_candidate = " ".join(tokens[-cat_len:]).lower()
        if _is_valid_category(cat_candidate):
            supplier_name = " ".join(tokens[:-cat_len]).strip()
            category = " ".join(tokens[-cat_len:]).strip()
            if supplier_name:
                return supplier_name, category

    if len(tokens) >= 2 and tokens[-1].isalpha():
        return " ".join(tokens[:-1]).strip(), tokens[-1].strip()

    return None, None
