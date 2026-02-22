from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List

from backend.services.llm_client import send_openai_prompt

_MAX_CHARS = 14000

_UNIVERSAL_PROMPT = """\
Eres un analista documental inmobiliario.
Tu trabajo es interpretar el contenido del documento y clasificarlo SOLO por evidencia del texto.
No clasifiques por nombre de archivo. No inventes datos.

Devuelve SOLO JSON valido con esta estructura:
{
  "document_type": "supplier_report|commercial_report|valuation_report|legal_report|market_report|investment_report|real_estate_generic|unknown",
  "confidence": 0.0,
  "classification": {
    "label": "string",
    "why": "explicacion breve basada en evidencia",
    "evidence_keywords": ["k1","k2","k3"]
  },
  "entities": {
    "asset": {
      "asset_type": null,
      "location_text": null,
      "surface_m2": null,
      "rooms": null,
      "energy_rating": null
    },
    "financials": {
      "price_eur": null,
      "rent_eur_month": null,
      "community_fee_eur": null,
      "ibi_eur_year": null,
      "capex_eur": null
    },
    "legal": {
      "encumbrances": [],
      "licenses": [],
      "occupancy_status": null
    },
    "market": {
      "comparable_mentions": [],
      "price_m2_ref_eur": null,
      "demand_signal": null
    }
  },
  "metrics": [
    {
      "name": "string",
      "value": 0,
      "unit": "string",
      "period": null,
      "source_excerpt": "texto corto",
      "confidence": 0.0
    }
  ],
  "risks": [
    {
      "risk": "string",
      "severity": "low|medium|high",
      "evidence": "texto corto",
      "confidence": 0.0
    }
  ],
  "assumptions": [
    {
      "assumption": "string",
      "confidence": 0.0
    }
  ]
}

Reglas:
- Si no hay evidencia suficiente, usa null o arrays vacios.
- confidence debe estar entre 0.0 y 1.0.
- source_excerpt debe ser corto y literal del documento cuando exista.

DOCUMENTO:
__DOCUMENT_TEXT__
"""


def normalize_universal_structure(full_text: str) -> Dict[str, Any]:
    if not full_text or not full_text.strip():
        return _unknown("empty_text")

    llm = _extract_with_openai(full_text)
    if llm is not None:
        return _coerce_universal(llm, extraction_method="llm")

    return _coerce_universal(_extract_with_rules(full_text), extraction_method="rules")


def _extract_with_openai(full_text: str) -> Dict[str, Any] | None:
    prompt = _UNIVERSAL_PROMPT.replace("__DOCUMENT_TEXT__", full_text[:_MAX_CHARS])
    response = send_openai_prompt(
        prompt=prompt,
        model=os.getenv("OPENAI_EXTRACT_MODEL", "gpt-4.1-mini"),
        max_tokens=2200,
        temperature=0,
        timeout=45,
    )
    if not response.get("ok"):
        return None

    try:
        raw_text = response.get("text", "")
        json_str = _extract_json_block(raw_text)
        if not json_str:
            return None
        return json.loads(json_str)
    except (ValueError, KeyError, IndexError):
        return None


def _extract_with_rules(full_text: str) -> Dict[str, Any]:
    text = full_text.replace("\\n", "\n")
    low = text.lower()

    label = "real_estate_generic"
    score = 0.35
    evidence: List[str] = []

    supplier_hits = _count_hits(
        low,
        ["proveedor", "contratista", "incidencias", "retraso", "dependencia", "sla"],
    )
    commercial_hits = _count_hits(
        low,
        ["leads", "reservas", "cancelaciones", "ventas mensuales", "pipeline comercial"],
    )
    valuation_hits = _count_hits(
        low,
        ["tasacion", "valor de mercado", "metodo comparativo", "valoracion"],
    )
    legal_hits = _count_hits(
        low,
        ["nota simple", "registro", "cargas", "hipoteca", "titular", "licencia"],
    )
    market_hits = _count_hits(
        low,
        ["precio m2", "oferta", "demanda", "absorcion", "compraventa", "tendencia"],
    )
    investment_hits = _count_hits(
        low,
        ["roi", "tir", "yield", "cap rate", "flujo de caja", "rentabilidad"],
    )

    buckets = [
        ("supplier_report", supplier_hits),
        ("commercial_report", commercial_hits),
        ("valuation_report", valuation_hits),
        ("legal_report", legal_hits),
        ("market_report", market_hits),
        ("investment_report", investment_hits),
    ]
    best_label, best_hits = max(buckets, key=lambda x: x[1])
    if best_hits >= 2:
        label = best_label
        score = min(0.9, 0.45 + 0.08 * best_hits)

    evidence.extend(_sample_evidence(low, [
        "proveedor", "incidencias", "retraso", "dependencia", "ventas", "reservas",
        "tasacion", "valor", "cargas", "hipoteca", "precio m2", "roi", "tir"
    ]))

    price_eur = _extract_money(low, ["precio", "valor", "importe"])
    rent_eur = _extract_money(low, ["alquiler", "renta"])
    surface = _extract_number(low, [r"m2", r"metros cuadrados"])
    rooms = _extract_number(low, [r"habitaciones", r"dormitorios"])
    price_m2 = _extract_money(low, ["precio m2", "€/m2", "eur/m2"])

    metrics: List[Dict[str, Any]] = []
    if price_eur is not None:
        metrics.append(
            _metric("price_eur", price_eur, "EUR", None, _excerpt(low, "precio"), 0.65)
        )
    if rent_eur is not None:
        metrics.append(
            _metric("rent_eur_month", rent_eur, "EUR/month", None, _excerpt(low, "alquiler"), 0.6)
        )
    if surface is not None:
        metrics.append(
            _metric("surface_m2", surface, "m2", None, _excerpt(low, "m2"), 0.55)
        )
    if price_m2 is not None:
        metrics.append(
            _metric("price_m2_ref_eur", price_m2, "EUR/m2", None, _excerpt(low, "m2"), 0.58)
        )

    risks: List[Dict[str, Any]] = []
    if "cargas" in low or "hipoteca" in low:
        risks.append(_risk("Riesgo legal sobre cargas/hipoteca", "high", _excerpt(low, "cargas"), 0.7))
    if "incidencias" in low or "retraso" in low:
        risks.append(_risk("Riesgo operativo por incidencias/retrasos", "medium", _excerpt(low, "incidencias"), 0.66))
    if "cancelaciones" in low:
        risks.append(_risk("Riesgo comercial por cancelaciones", "medium", _excerpt(low, "cancelaciones"), 0.64))

    assumptions: List[Dict[str, Any]] = []
    if not metrics:
        assumptions.append({"assumption": "Documento con datos cuantitativos limitados o no detectables por reglas.", "confidence": 0.5})

    return {
        "document_type": label if evidence else "unknown",
        "confidence": round(score if evidence else 0.0, 2),
        "classification": {
            "label": label if evidence else "unknown",
            "why": "Clasificacion por patrones semanticos en contenido del PDF.",
            "evidence_keywords": evidence[:8],
        },
        "entities": {
            "asset": {
                "asset_type": _extract_asset_type(low),
                "location_text": _extract_location(low),
                "surface_m2": surface,
                "rooms": rooms,
                "energy_rating": _extract_energy_rating(low),
            },
            "financials": {
                "price_eur": price_eur,
                "rent_eur_month": rent_eur,
                "community_fee_eur": None,
                "ibi_eur_year": None,
                "capex_eur": _extract_money(low, ["capex", "inversion", "rehabilitacion"]),
            },
            "legal": {
                "encumbrances": _list_if_present(low, ["cargas", "hipoteca", "embargo"]),
                "licenses": _list_if_present(low, ["licencia de obra", "licencia", "permiso"]),
                "occupancy_status": _extract_occupancy(low),
            },
            "market": {
                "comparable_mentions": _extract_comparables(low),
                "price_m2_ref_eur": price_m2,
                "demand_signal": _extract_demand_signal(low),
            },
        },
        "metrics": metrics,
        "risks": risks,
        "assumptions": assumptions,
    }


def _coerce_universal(raw: Dict[str, Any], extraction_method: str) -> Dict[str, Any]:
    doc_type = str(raw.get("document_type") or "unknown")
    confidence = _safe_float(raw.get("confidence"), 0.0)
    confidence = max(0.0, min(1.0, confidence))

    classification = raw.get("classification") or {}
    entities = raw.get("entities") or {}
    metrics = raw.get("metrics") or []
    risks = raw.get("risks") or []
    assumptions = raw.get("assumptions") or []

    for m in metrics:
        if isinstance(m, dict):
            m.setdefault("extraction_method", extraction_method)
            m["confidence"] = max(0.0, min(1.0, _safe_float(m.get("confidence"), 0.5)))
    for r in risks:
        if isinstance(r, dict):
            r["confidence"] = max(0.0, min(1.0, _safe_float(r.get("confidence"), 0.5)))
    for a in assumptions:
        if isinstance(a, dict):
            a["confidence"] = max(0.0, min(1.0, _safe_float(a.get("confidence"), 0.5)))

    return {
        "document_type": doc_type,
        "confidence": round(confidence, 2),
        "classification": {
            "label": str(classification.get("label") or doc_type),
            "why": str(classification.get("why") or ""),
            "evidence_keywords": classification.get("evidence_keywords") or [],
        },
        "entities": entities if isinstance(entities, dict) else {},
        "metrics": metrics if isinstance(metrics, list) else [],
        "risks": risks if isinstance(risks, list) else [],
        "assumptions": assumptions if isinstance(assumptions, list) else [],
    }


def _unknown(reason: str) -> Dict[str, Any]:
    return {
        "document_type": "unknown",
        "confidence": 0.0,
        "classification": {
            "label": "unknown",
            "why": reason,
            "evidence_keywords": [],
        },
        "entities": {},
        "metrics": [],
        "risks": [],
        "assumptions": [],
    }


def _extract_json_block(text: str) -> str | None:
    match = re.search(r"\{[\s\S]*\}", text)
    return match.group() if match else None


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _count_hits(low: str, patterns: List[str]) -> int:
    return sum(1 for p in patterns if p in low)


def _sample_evidence(low: str, patterns: List[str]) -> List[str]:
    found: List[str] = []
    for p in patterns:
        if p in low:
            found.append(p)
    return found


def _extract_money(low: str, labels: List[str]) -> int | None:
    for label in labels:
        pattern = rf"{re.escape(label)}[^\\n\\r]{{0,40}}(\d[\d\.\,]{{2,}})"
        m = re.search(pattern, low)
        if m:
            raw = m.group(1).replace(".", "").replace(",", ".")
            try:
                return int(float(raw))
            except ValueError:
                continue
    return None


def _extract_number(low: str, labels: List[str]) -> int | None:
    for label in labels:
        pattern = rf"(\d{{1,4}}(?:[\,\.]\d{{1,2}})?)\s*{label}"
        m = re.search(pattern, low)
        if m:
            raw = m.group(1).replace(",", ".")
            try:
                return int(float(raw))
            except ValueError:
                continue
    return None


def _extract_asset_type(low: str) -> str | None:
    for t in ["vivienda", "piso", "atico", "duplex", "local", "oficina", "suelo", "nave"]:
        if t in low:
            return t
    return None


def _extract_location(low: str) -> str | None:
    m = re.search(r"(madrid|barcelona|sevilla|malaga|valencia|cadiz|zaragoza|bilbao)", low)
    return m.group(1).title() if m else None


def _extract_energy_rating(low: str) -> str | None:
    m = re.search(r"certificaci[oó]n energ[ée]tica\s*([a-g])", low)
    if m:
        return m.group(1).upper()
    return None


def _extract_occupancy(low: str) -> str | None:
    if "ocupado" in low:
        return "ocupado"
    if "libre" in low:
        return "libre"
    return None


def _extract_comparables(low: str) -> List[str]:
    comps: List[str] = []
    for token in ["comparable", "testigo", "oferta similar", "transaccion similar"]:
        if token in low:
            comps.append(token)
    return comps


def _extract_demand_signal(low: str) -> str | None:
    if "demanda alta" in low or "alta demanda" in low:
        return "high"
    if "demanda baja" in low:
        return "low"
    if "demanda" in low:
        return "medium"
    return None


def _list_if_present(low: str, values: List[str]) -> List[str]:
    return [v for v in values if v in low]


def _excerpt(low: str, keyword: str) -> str:
    idx = low.find(keyword)
    if idx < 0:
        return ""
    start = max(0, idx - 50)
    end = min(len(low), idx + 90)
    return low[start:end].strip()


def _metric(name: str, value: Any, unit: str, period: str | None, source_excerpt: str, confidence: float) -> Dict[str, Any]:
    return {
        "name": name,
        "value": value,
        "unit": unit,
        "period": period,
        "source_excerpt": source_excerpt,
        "confidence": confidence,
    }


def _risk(risk: str, severity: str, evidence: str, confidence: float) -> Dict[str, Any]:
    return {
        "risk": risk,
        "severity": severity,
        "evidence": evidence,
        "confidence": confidence,
    }
