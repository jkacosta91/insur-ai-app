from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def build_extraction_summary(payload: Any) -> dict:
    extraction = payload.extraction.model_dump() if getattr(payload, "extraction", None) else {}
    return {
        "engine": extraction.get("extraction_engine"),
        "page_count": extraction.get("page_count"),
        "char_count": extraction.get("char_count"),
        "token_count": extraction.get("token_count"),
        "has_tables": extraction.get("has_tables"),
        "quality_status": extraction.get("quality_status"),
        "usable_for_analysis": extraction.get("usable_for_analysis"),
    }


def empty_supplier_outputs(horizon_days: int) -> Dict[str, dict]:
    empty_seg = {
        "model": "segmentation_suppliers",
        "engine": "rules",
        "output": {"suppliers_segmented": [], "summary": {"total_suppliers": 0, "high_risk": 0, "med_risk": 0, "low_risk": 0}},
    }
    empty_beh = {
        "model": "behavior_suppliers",
        "engine": "rules",
        "output": {"supplier_behavior": [], "summary": {"total_suppliers": 0, "stable": 0, "warning": 0, "critical": 0, "avg_reliability_index": 0}},
    }
    empty_for = {
        "model": "forecast_suppliers",
        "engine": "rules",
        "output": {"supplier_forecast": [], "summary": {"horizon_days": horizon_days, "total_suppliers": 0, "high_risk_forecast": 0, "med_risk_forecast": 0, "low_risk_forecast": 0}},
    }
    return {"segmentation": empty_seg, "behavior": empty_beh, "forecast": empty_for}


def merge_decisions(primary: dict, secondary: dict) -> dict:
    return {
        "strategic_decisions": [
            *(primary.get("strategic_decisions", []) or []),
            *(secondary.get("strategic_decisions", []) or []),
        ],
        "risk_alerts": [
            *(primary.get("risk_alerts", []) or []),
            *(secondary.get("risk_alerts", []) or []),
        ],
        "inputs": {"primary": primary.get("inputs", {}), "secondary": secondary.get("inputs", {})},
    }


def build_traceability(
    normalized: dict,
    segmentation: dict | None = None,
    behavior: dict | None = None,
    forecast: dict | None = None,
    commercial: dict | None = None,
    real_estate: dict | None = None,
) -> dict:
    interpretation = normalized.get("interpretation", {}) if isinstance(normalized, dict) else {}
    classification = interpretation.get("classification", {}) if isinstance(interpretation, dict) else {}
    evidence_keywords = classification.get("evidence_keywords", []) if isinstance(classification, dict) else []

    models = []
    if segmentation:
        models.append({"name": segmentation.get("model"), "engine": segmentation.get("engine")})
    if behavior:
        models.append({"name": behavior.get("model"), "engine": behavior.get("engine")})
    if forecast:
        models.append({"name": forecast.get("model"), "engine": forecast.get("engine")})
    if commercial:
        models.append({"name": commercial.get("model"), "engine": commercial.get("engine")})
    if real_estate:
        models.append({"name": real_estate.get("model"), "engine": real_estate.get("engine")})

    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "document_type": normalized.get("document_type"),
        "classification": classification,
        "evidence_keywords_count": len(evidence_keywords),
        "models_executed": models,
        "rules_engine": "decision_engine_v2",
    }


def build_pipeline_summary(
    normalized: dict,
    decisions: dict,
    segmentation: dict | None = None,
    behavior: dict | None = None,
    forecast: dict | None = None,
    commercial: dict | None = None,
    real_estate: dict | None = None,
) -> dict:
    doc_type = normalized.get("document_type")
    alerts = len((decisions or {}).get("risk_alerts", []))
    strategic = len((decisions or {}).get("strategic_decisions", []))

    if doc_type == "supplier_report":
        seg_sum = ((segmentation or {}).get("output") or {}).get("summary", {})
        beh_sum = ((behavior or {}).get("output") or {}).get("summary", {})
        for_sum = ((forecast or {}).get("output") or {}).get("summary", {})
        total = max(1, int(seg_sum.get("total_suppliers", 0)))
        high = int(seg_sum.get("high_risk", 0))
        med = int(seg_sum.get("med_risk", 0))
        critical = int(beh_sum.get("critical", 0))
        forecast_high = int(for_sum.get("high_risk_forecast", 0))

        high_ratio = high / total
        med_ratio = med / total
        critical_ratio = critical / total
        forecast_high_ratio = forecast_high / total
        alert_pressure = min(1.0, alerts / total)
        risk_penalty = (
            45.0 * high_ratio
            + 20.0 * med_ratio
            + 25.0 * critical_ratio
            + 20.0 * forecast_high_ratio
            + 20.0 * alert_pressure
        )
        score = int(clamp(100 - risk_penalty, 0, 100))
        return {
            "high_risk": high,
            "score": score,
            "forecast_high": forecast_high,
            "alerts": alerts,
            "critical": critical,
            "strategic_decisions": strategic,
            "score_label": _score_label(score),
            "risk_status": "Bajo" if high == 0 and alerts <= 2 else "Medio" if high <= 1 and alerts <= 5 else "Alto",
            "executive_message": _executive_message(score, "supplier"),
            "friendly_labels": {
                "high_risk": "Proveedores criticos",
                "score": "Estado general",
                "forecast_high": "Riesgo proyectado",
                "alerts": "Alertas activas",
            },
        }

    if doc_type == "commercial_report":
        kpis = ((commercial or {}).get("output") or {}).get("kpis", {})
        re_out = ((real_estate or {}).get("output") or {})
        trend = str(kpis.get("trend", "flat"))
        conversion = float(kpis.get("conversion_rate", 0.0) or 0.0)
        cancellation = float(kpis.get("cancellation_rate", 0.0) or 0.0)
        sell_through = float(kpis.get("sell_through_rate", 0.0) or 0.0)
        invest_score_raw = re_out.get("investment_score_0_100")
        liquidity_raw = re_out.get("liquidity_days_p50")
        model_conf_raw = re_out.get("model_confidence_0_100")
        conservative = (re_out.get("scenario_analysis") or {}).get("conservative", {})
        cons_invest_raw = conservative.get("investment_score_0_100")
        cons_liq_raw = conservative.get("liquidity_days_p50")
        invest_score = float(invest_score_raw) if invest_score_raw is not None else None
        liquidity_days = float(liquidity_raw) if liquidity_raw is not None else None
        model_conf = float(model_conf_raw) if model_conf_raw is not None else None
        cons_invest = float(cons_invest_raw) if cons_invest_raw is not None else None
        cons_liq = float(cons_liq_raw) if cons_liq_raw is not None else None
        trend_bonus = 10 if trend == "up" else -10 if trend == "down" else 0
        conf_adjust = (model_conf - 60.0) * 0.08 if model_conf is not None else 0.0
        conservative_penalty = (
            max(0.0, (55.0 - cons_invest) * 0.45) if cons_invest is not None else 0.0
        ) + (
            max(0.0, (cons_liq - 180.0) * 0.06) if cons_liq is not None else 0.0
        )
        score = int(
            clamp(
                42
                + trend_bonus
                + conversion * 120
                + sell_through * 45
                + (invest_score * 0.20 if invest_score is not None else 0)
                + conf_adjust
                - cancellation * 60
                - (max(0.0, (liquidity_days - 120.0) * 0.08) if liquidity_days is not None else 0)
                - conservative_penalty
                - alerts * 3.5,
                0,
                100,
            )
        )
        _invest_pts = round(invest_score * 0.20, 1) if invest_score is not None else 0.0
        _liq_pts = round(max(0.0, (liquidity_days - 120.0) * 0.08), 1) if liquidity_days is not None else 0.0
        _cons_pen = round(conservative_penalty, 1)
        _conf_adj = round(conf_adjust, 1)
        score_breakdown = {
            "base": 42,
            "trend_bonus": trend_bonus,
            "conversion_points": round(conversion * 120, 1),
            "sell_through_points": round(sell_through * 45, 1),
            "invest_points": _invest_pts,
            "model_confidence_adjustment": _conf_adj,
            "cancellation_penalty": round(cancellation * 60, 1),
            "liquidity_penalty": _liq_pts,
            "conservative_penalty": _cons_pen,
            "alerts_penalty": round(alerts * 3.5, 1),
            "total": score,
        }
        return {
            "high_risk": int(alerts >= 2),
            "score": score,
            "forecast_high": 0,
            "alerts": alerts,
            "critical": int(cancellation >= 0.25),
            "strategic_decisions": strategic,
            "trend": trend,
            "score_label": _score_label(score),
            "risk_status": "Alto" if alerts >= 3 else "Medio" if alerts >= 1 else "Bajo",
            "executive_message": _executive_message(score, "commercial"),
            "score_breakdown": score_breakdown,
            "friendly_labels": {
                "high_risk": "Riesgo comercial",
                "score": "Estado general",
                "forecast_high": "Riesgo proyectado",
                "alerts": "Alertas activas",
            },
        }

    interpretation = normalized.get("interpretation", {}) if isinstance(normalized, dict) else {}
    risks = interpretation.get("risks", []) if isinstance(interpretation, dict) else []
    re_out = ((real_estate or {}).get("output") or {})
    high_risk = sum(1 for r in risks if str(r.get("severity", "")).lower() == "high")
    med_risk = sum(1 for r in risks if str(r.get("severity", "")).lower() == "medium")
    confidence = float(interpretation.get("confidence", 0.0) or 0.0)
    invest_score = float(re_out.get("investment_score_0_100", 50.0) or 50.0)
    liquidity_days = float(re_out.get("liquidity_days_p50", 140.0) or 140.0)
    model_confidence = float(re_out.get("model_confidence_0_100", 65.0) or 65.0)
    conservative = (re_out.get("scenario_analysis") or {}).get("conservative", {})
    cons_invest = float(conservative.get("investment_score_0_100", invest_score) or invest_score)
    cons_liq = float(conservative.get("liquidity_days_p50", liquidity_days) or liquidity_days)
    score = int(
        clamp(
            26
            + confidence * 45
            + invest_score * 0.28
            + (model_confidence - 60.0) * 0.10
            - max(0.0, (liquidity_days - 120.0) * 0.09)
            - max(0.0, (55.0 - cons_invest) * 0.40)
            - max(0.0, (cons_liq - 180.0) * 0.07)
            - high_risk * 15
            - med_risk * 7
            - alerts * 3.5,
            0,
            100,
        )
    )
    return {
        "high_risk": high_risk,
        "score": score,
        "forecast_high": 0,
        "alerts": alerts,
        "critical": high_risk,
        "strategic_decisions": strategic,
        "score_label": _score_label(score),
        "risk_status": "Alto" if high_risk > 0 else "Medio" if med_risk > 0 else "Bajo",
        "executive_message": _executive_message(score, "generic"),
        "friendly_labels": {
            "high_risk": "Riesgos altos",
            "score": "Estado general",
            "forecast_high": "Riesgo proyectado",
            "alerts": "Alertas activas",
        },
    }


def _score_label(score: int) -> str:
    if score >= 80:
        return "Muy favorable"
    if score >= 60:
        return "Favorable con seguimiento"
    if score >= 40:
        return "Riesgo relevante"
    return "Riesgo alto"


def _executive_message(score: int, kind: str) -> str:
    if kind == "supplier":
        if score >= 70:
            return "Escenario estable; mantener monitoreo."
        if score >= 40:
            return "Hay senales de riesgo; conviene aplicar mitigacion."
        return "Escenario comprometido; priorizar medidas inmediatas."
    if kind == "commercial":
        if score >= 70:
            return "Traccion comercial saludable."
        if score >= 40:
            return "Rendimiento mixto; ajustar embudo y seguimiento."
        return "Desempeno comercial debil; revisar estrategia."
    if score >= 70:
        return "Documento bien interpretado y con bajo riesgo."
    if score >= 40:
        return "Interpretacion util, pero requiere validaciones adicionales."
    return "Informacion y/o riesgos insuficientes para una decision segura."
