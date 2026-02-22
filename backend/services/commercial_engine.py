from __future__ import annotations

from typing import Any, Dict, List


def analyze_commercial_report(normalized: Dict[str, Any]) -> Dict[str, Any]:
    series = normalized.get("sales_timeseries", []) or []
    indicators = normalized.get("commercial_indicators", {}) or {}

    units = [x.get("units_sold", 0) for x in series if isinstance(x.get("units_sold"), (int, float))]
    revenues = [x.get("revenue_eur", 0) for x in series if isinstance(x.get("revenue_eur"), (int, float))]

    trend = "flat"
    if len(units) >= 2:
        if units[-1] > units[0]:
            trend = "up"
        elif units[-1] < units[0]:
            trend = "down"

    leads = _as_number(indicators.get("leads_generated"))
    visits = _as_number(indicators.get("visits_done"))
    reservations = _as_number(indicators.get("reservations"))
    cancellations = _as_number(indicators.get("cancellations"))
    units_sold = _as_number(indicators.get("units_sold"))
    units_available = _as_number(indicators.get("units_available"))
    units_total = _as_number(indicators.get("units_total"))
    if units_total == 0 and (units_sold > 0 or units_available > 0):
        units_total = units_sold + units_available

    conversion_rate = _safe_rate(reservations, leads)
    visit_to_reservation_rate = _safe_rate(reservations, visits)
    cancellation_rate = _safe_rate(cancellations, max(reservations, 1))
    sell_through = _safe_rate(units_sold, max(units_total, 1))

    strategic_decisions: List[Dict[str, Any]] = []
    risk_alerts: List[Dict[str, Any]] = []

    if trend == "down":
        risk_alerts.append(
            {
                "type": "commercial_alert",
                "severity": "alta",
                "signal": "Tendencia de unidades vendidas decreciente en la serie mensual",
            }
        )
        strategic_decisions.append(
            {
                "type": "commercial_action",
                "action": "Reforzar captacion y revisar pricing de la promocion",
                "priority": "alta",
                "why": [f"Tendencia ventas: {trend}"],
            }
        )

    if leads > 0 and conversion_rate < 0.10:
        risk_alerts.append(
            {
                "type": "commercial_alert",
                "severity": "media",
                "signal": f"Baja conversion lead->reserva ({conversion_rate:.1%})",
            }
        )
        strategic_decisions.append(
            {
                "type": "commercial_action",
                "action": "Optimizar embudo comercial y cualificacion de leads",
                "priority": "media",
                "why": [f"Conversion {conversion_rate:.1%}", f"Leads {int(leads)}"],
            }
        )

    if reservations > 0 and cancellation_rate >= 0.20:
        risk_alerts.append(
            {
                "type": "commercial_alert",
                "severity": "alta",
                "signal": f"Tasa de cancelacion elevada ({cancellation_rate:.1%})",
            }
        )

    if units_total > 0 and sell_through < 0.50:
        strategic_decisions.append(
            {
                "type": "commercial_action",
                "action": "Revisar estrategia de comercializacion para acelerar absorcion",
                "priority": "media",
                "why": [f"Sell-through {sell_through:.1%}", f"Stock disponible {int(units_available)}"],
            }
        )

    if not strategic_decisions and not risk_alerts:
        strategic_decisions.append(
            {
                "type": "commercial_action",
                "action": "Mantener estrategia comercial actual y seguimiento semanal de KPI",
                "priority": "baja",
                "why": ["No se detectan señales criticas en el periodo analizado"],
            }
        )

    analysis_output = {
        "model": "commercial_kpi_engine",
        "engine": "rules",
        "output": {
            "kpis": {
                "avg_units_sold": round(sum(units) / len(units), 2) if units else 0,
                "avg_revenue_eur": round(sum(revenues) / len(revenues), 2) if revenues else 0,
                "trend": trend,
                "conversion_rate": round(conversion_rate, 4),
                "visit_to_reservation_rate": round(visit_to_reservation_rate, 4),
                "cancellation_rate": round(cancellation_rate, 4),
                "sell_through_rate": round(sell_through, 4),
            },
            "series": series,
            "summary": {
                "months_detected": len(series),
                "trend": trend,
                "alerts": len(risk_alerts),
                "decisions": len(strategic_decisions),
            },
        },
    }

    decisions_output = {
        "strategic_decisions": strategic_decisions,
        "risk_alerts": risk_alerts,
        "inputs": {
            "document_type": normalized.get("document_type"),
            "commercial_indicators": indicators,
        },
    }

    return {
        "analysis": analysis_output,
        "decisions": decisions_output,
    }


def _safe_rate(num: float, den: float) -> float:
    if den <= 0:
        return 0.0
    return max(0.0, min(1.0, num / den))


def _as_number(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0
