from __future__ import annotations

import re
from typing import Any, Dict, List


_MONTHS = {
    "enero": "Enero",
    "febrero": "Febrero",
    "marzo": "Marzo",
    "abril": "Abril",
    "mayo": "Mayo",
    "junio": "Junio",
    "julio": "Julio",
    "agosto": "Agosto",
    "septiembre": "Septiembre",
    "octubre": "Octubre",
    "noviembre": "Noviembre",
    "diciembre": "Diciembre",
}

_SALES_ROW = re.compile(
    r"^(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+(\d+)\s+(\d+(?:[.,]\d+)?)$",
    re.IGNORECASE,
)


def normalize_commercial_report(full_text: str) -> Dict[str, Any]:
    if not full_text or not full_text.strip():
        return _unknown()

    text = full_text.replace("\\n", "\n")
    lines = [ln.strip() for ln in re.split(r"\r?\n", text) if ln.strip()]
    lines_low = [ln.lower() for ln in lines]

    has_commercial_signals = any(
        kw in " ".join(lines_low)
        for kw in (
            "informe mensual de ventas",
            "ventas mensuales",
            "pipeline comercial",
            "leads generados",
            "leads",
            "reservas",
            "cancelaciones",
            "unidades vendidas",
            "viviendas vendidas",
            "absorcion",
            "comercializacion",
            "sell-through",
            "conversion comercial",
        )
    )

    sales_rows = _extract_monthly_sales(lines)
    indicators = _extract_commercial_indicators(lines)

    if not has_commercial_signals and not sales_rows and not indicators:
        return _unknown()

    units_total = indicators.get("units_total")
    units_sold = indicators.get("units_sold")
    units_available = indicators.get("units_available")
    if units_total is None and units_sold is not None and units_available is not None:
        units_total = units_sold + units_available

    return {
        "document_type": "commercial_report",
        "confidence": round(min(0.95, 0.45 + len(sales_rows) * 0.07 + (0.08 if indicators else 0.0)), 2),
        "sales_timeseries": sales_rows,
        "commercial_indicators": indicators,
        "summary": {
            "months_detected": len(sales_rows),
            "units_total": units_total,
            "units_sold": units_sold,
            "units_available": units_available,
            "latest_month_units_sold": sales_rows[-1]["units_sold"] if sales_rows else None,
        },
    }


def _extract_monthly_sales(lines: List[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for ln in lines:
        m = _SALES_ROW.match(ln)
        if not m:
            continue
        month_raw = m.group(1).lower()
        month = _MONTHS.get(month_raw, month_raw.title())
        units = int(float(m.group(2).replace(",", ".")))
        revenue = int(float(m.group(3).replace(",", ".")))
        rows.append({"month": month, "units_sold": units, "revenue_eur": revenue})
    return rows


def _extract_commercial_indicators(lines: List[str]) -> Dict[str, Any]:
    # Each key maps to a list of label variants to match (all lowercase)
    label_map: Dict[str, List[str]] = {
        "leads_generated": ["leads generados", "leads generadas", "leads captados", "leads", "contactos generados"],
        "visits_done": ["visitas realizadas", "visitas efectuadas", "visitas", "visitas comerciales"],
        "reservations": ["reservas firmadas", "reservas", "contratos reserva"],
        "cancellations": ["cancelaciones", "cancelados", "desistimientos"],
        "units_sold": ["unidades vendidas", "viviendas vendidas", "vendidas", "unidades entregadas", "escrituradas"],
        "units_available": ["unidades disponibles", "disponibles", "stock disponible", "viviendas disponibles"],
        "units_total": ["viviendas totales", "unidades totales", "viviendas", "total unidades", "total viviendas"],
    }
    out: Dict[str, Any] = {}
    for ln in lines:
        ln_low = ln.lower()
        for key, labels in label_map.items():
            if key in out:
                continue
            for label in labels:
                if label not in ln_low:
                    continue
                nums = re.findall(r"\d+(?:[.,]\d+)?", ln)
                if nums:
                    out[key] = int(float(nums[-1].replace(",", ".")))
                    break
    return out


def _unknown() -> Dict[str, Any]:
    return {
        "document_type": "unknown",
        "confidence": 0.0,
        "sales_timeseries": [],
        "commercial_indicators": {},
        "summary": {},
    }
