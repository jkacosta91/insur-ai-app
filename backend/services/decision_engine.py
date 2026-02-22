from typing import Any, Dict, List


def supplier_decisions(
    normalized: Dict[str, Any],
    model_output: Dict[str, Any],
    behavior_output: Dict[str, Any] | None = None,
    forecast_output: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    suppliers = model_output.get("output", {}).get("suppliers_segmented") or model_output.get(
        "suppliers_segmented", []
    )
    behavior_rows = (
        (behavior_output or {}).get("output", {}).get("supplier_behavior")
        or (behavior_output or {}).get("supplier_behavior", [])
    )
    forecast_rows = (
        (forecast_output or {}).get("output", {}).get("supplier_forecast")
        or (forecast_output or {}).get("supplier_forecast", [])
    )

    behavior_by_name = {x.get("supplier_name"): x for x in behavior_rows}
    forecast_by_name = {x.get("supplier_name"): x for x in forecast_rows}

    decisions: List[Dict[str, Any]] = []
    alerts: List[Dict[str, Any]] = []

    for s in suppliers:
        dep = s.get("dependency_pct", 0)
        inc = s.get("incidents", 0)
        delay = s.get("avg_delay_days", 0)
        tier = s.get("risk_tier", "LOW")
        name = s.get("supplier_name")

        behavior_state = behavior_by_name.get(name, {}).get("behavior_state", "stable")
        reliability = behavior_by_name.get(name, {}).get("reliability_index")
        forecast_level = forecast_by_name.get(name, {}).get("forecast_risk_level", "LOW")
        forecast_score = forecast_by_name.get(name, {}).get("forecast_risk_score")
        forecast_interval = forecast_by_name.get(name, {}).get("forecast_risk_interval", {}) or {}
        forecast_p90 = _to_float(forecast_interval.get("p90"))

        if dep >= 50 and (
            tier in ["HIGH", "MED"] or behavior_state == "critical" or forecast_level == "HIGH"
        ):
            decisions.append(
                {
                    "type": "supplier_action",
                    "supplier": name,
                    "action": "Diversificar proveedor / buscar alternativa",
                    "priority": "alta",
                    "why": [
                        f"Dependencia {dep}%",
                        f"Riesgo actual {tier}",
                        f"Comportamiento {behavior_state}",
                        f"Forecast {forecast_level}",
                    ],
                }
            )

        # Aggregate signals per supplier to avoid alert explosion.
        supplier_signals: List[str] = []
        supplier_severity = "baja"
        if delay >= 15:
            supplier_signals.append(f"Retraso medio {delay} dias")
            supplier_severity = "alta" if delay >= 20 else "media"
        if inc >= 8:
            supplier_signals.append(f"Incidencias {inc}")
            if inc >= 10:
                supplier_severity = "alta"
            elif supplier_severity == "baja":
                supplier_severity = "media"
        if behavior_state == "critical" or (reliability is not None and reliability < 40):
            supplier_signals.append(f"Comportamiento operativo critico (indice {reliability})")
            supplier_severity = "alta"
        if forecast_score is not None and forecast_score >= 120:
            supplier_signals.append(f"Riesgo proyectado alto ({forecast_score})")
            supplier_severity = "alta"
        if forecast_p90 is not None and forecast_p90 >= 130:
            supplier_signals.append(f"Escenario adverso forecast P90 ({forecast_p90:.1f})")
            supplier_severity = "alta"

        if supplier_signals:
            alerts.append(
                {
                    "type": "risk_alert",
                    "severity": supplier_severity,
                    "supplier": name,
                    "signal": " | ".join(supplier_signals),
                }
            )

    return {
        "strategic_decisions": decisions,
        "risk_alerts": alerts,
        "inputs": {
            "document_type": normalized.get("document_type"),
            "global_indicators": normalized.get("global_indicators", {}),
        },
    }


def generic_real_estate_decisions(
    normalized: Dict[str, Any],
    real_estate_output: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    interpretation = normalized.get("interpretation") or {}
    risks = interpretation.get("risks", []) or []
    metrics = interpretation.get("metrics", []) or []
    entities = interpretation.get("entities", {}) or {}

    decisions: List[Dict[str, Any]] = []
    alerts: List[Dict[str, Any]] = []

    for risk in risks:
        severity = str(risk.get("severity") or "medium").lower()
        risk_text = str(risk.get("risk") or "Riesgo identificado")
        evidence = str(risk.get("evidence") or "")
        conf = risk.get("confidence")

        if severity == "high":
            alerts.append(
                {
                    "type": "risk_alert",
                    "severity": "alta",
                    "signal": f"{risk_text}. Evidencia: {evidence}".strip(),
                }
            )
            decisions.append(
                {
                    "type": "strategic_action",
                    "action": "Mitigacion inmediata del riesgo alto detectado",
                    "priority": "alta",
                    "why": [risk_text, f"confianza={conf}"],
                }
            )
        elif severity == "medium":
            alerts.append(
                {
                    "type": "risk_alert",
                    "severity": "media",
                    "signal": f"{risk_text}. Evidencia: {evidence}".strip(),
                }
            )

    price = _metric_value(metrics, "price_eur")
    rent = _metric_value(metrics, "rent_eur_month")
    surface = _metric_value(metrics, "surface_m2")
    if price and rent and price > 0:
        gross_yield = (rent * 12.0) / price
        if gross_yield < 0.035:
            decisions.append(
                {
                    "type": "strategic_action",
                    "action": "Revisar precio o estrategia de alquiler para mejorar yield",
                    "priority": "media",
                    "why": [f"yield_bruta={gross_yield:.2%}", f"precio={price}", f"renta={rent}"],
                }
            )
        elif gross_yield >= 0.06:
            decisions.append(
                {
                    "type": "strategic_action",
                    "action": "Activo con traccion de renta favorable, evaluar aceleracion comercial",
                    "priority": "baja",
                    "why": [f"yield_bruta={gross_yield:.2%}"],
                }
            )

    if surface and surface > 160:
        alerts.append(
            {
                "type": "risk_alert",
                "severity": "media",
                "signal": f"Superficie alta detectada ({surface} m2), validar comparables especificos.",
            }
        )

    legal = (entities.get("legal") or {})
    encumbrances = legal.get("encumbrances") or []
    if encumbrances:
        decisions.append(
            {
                "type": "strategic_action",
                "action": "Realizar revision legal previa a decision economica",
                "priority": "alta",
                "why": [f"cargas_detectadas={', '.join(encumbrances)}"],
            }
        )

    # Incorporate model-driven signals when available.
    re_out = (real_estate_output or {}).get("output", {})
    invest_score = _to_float(re_out.get("investment_score_0_100"))
    liquidity_days = _to_float(re_out.get("liquidity_days_p50"))
    price_gap = _to_float(re_out.get("price_gap_pct_vs_document"))
    rent_gap = _to_float(re_out.get("rent_gap_pct_vs_document"))
    model_confidence = _to_float(re_out.get("model_confidence_0_100"))
    intervals = re_out.get("prediction_intervals", {}) or {}
    sale_interval = intervals.get("sale_price_eur", {}) or {}
    liq_interval = intervals.get("liquidity_days", {}) or {}
    sale_width = _to_float(sale_interval.get("width_pct"))
    liq_p90 = _to_float(liq_interval.get("p90"))
    scenarios = re_out.get("scenario_analysis", {}) or {}
    conservative = scenarios.get("conservative", {}) or {}
    cons_invest = _to_float(conservative.get("investment_score_0_100"))
    cons_liquidity = _to_float(conservative.get("liquidity_days_p50"))

    if invest_score is not None:
        if invest_score < 40:
            alerts.append(
                {
                    "type": "risk_alert",
                    "severity": "alta",
                    "signal": f"Score de inversion bajo ({invest_score:.1f}/100).",
                }
            )
            decisions.append(
                {
                    "type": "strategic_action",
                    "action": "Revisar operacion por baja rentabilidad esperada",
                    "priority": "alta",
                    "why": [f"investment_score={invest_score:.1f}"],
                }
            )
        elif invest_score >= 70:
            decisions.append(
                {
                    "type": "strategic_action",
                    "action": "Escenario atractivo; priorizar cierre de diligencia",
                    "priority": "media",
                    "why": [f"investment_score={invest_score:.1f}"],
                }
            )

    if liquidity_days is not None and liquidity_days > 180:
        alerts.append(
            {
                "type": "risk_alert",
                "severity": "media",
                "signal": f"Liquidez lenta estimada ({liquidity_days:.0f} dias).",
            }
        )
    if liq_p90 is not None and liq_p90 > 220:
        alerts.append(
            {
                "type": "risk_alert",
                "severity": "alta",
                "signal": f"Escenario de liquidez adversa (P90 {liq_p90:.0f} dias).",
            }
        )
    if sale_width is not None and sale_width >= 0.35:
        alerts.append(
            {
                "type": "risk_alert",
                "severity": "media",
                "signal": "Alta incertidumbre en la estimacion de precio (intervalo amplio).",
            }
        )
    if model_confidence is not None and model_confidence < 55:
        alerts.append(
            {
                "type": "risk_alert",
                "severity": "media",
                "signal": f"Confianza del modelo moderada/baja ({model_confidence:.0f}/100).",
            }
        )
    if cons_invest is not None and cons_invest < 50:
        decisions.append(
            {
                "type": "strategic_action",
                "action": "Escenario conservador debil: reforzar supuestos o renegociar condiciones",
                "priority": "alta",
                "why": [f"investment_score_conservative={cons_invest:.1f}"],
            }
        )
    if cons_liquidity is not None and cons_liquidity > 190:
        decisions.append(
            {
                "type": "strategic_action",
                "action": "Plan de salida/lanzamiento para reducir riesgo de iliquidez",
                "priority": "media",
                "why": [f"liquidity_conservative_days={cons_liquidity:.1f}"],
            }
        )
    if price_gap is not None and abs(price_gap) >= 12:
        decisions.append(
            {
                "type": "strategic_action",
                "action": "Ajustar precio objetivo frente a valor esperado del modelo",
                "priority": "media",
                "why": [f"gap_precio={price_gap:.1f}%"],
            }
        )
    if rent_gap is not None and abs(rent_gap) >= 12:
        decisions.append(
            {
                "type": "strategic_action",
                "action": "Revisar supuestos de renta frente a benchmark del modelo",
                "priority": "media",
                "why": [f"gap_renta={rent_gap:.1f}%"],
            }
        )

    if not decisions and not alerts:
        decisions.append(
            {
                "type": "strategic_action",
                "action": "Completar datos criticos para decision (precio, renta, riesgos legales)",
                "priority": "media",
                "why": ["Documento general con evidencia insuficiente para decision fuerte"],
            }
        )

    return {
        "strategic_decisions": decisions,
        "risk_alerts": alerts,
        "inputs": {
            "document_type": normalized.get("document_type"),
            "classification": interpretation.get("classification", {}),
            "real_estate_model": (real_estate_output or {}).get("model_name"),
        },
    }


def _metric_value(metrics: List[Dict[str, Any]], name: str) -> float | None:
    for m in metrics:
        if str(m.get("name")) == name:
            try:
                return float(m.get("value"))
            except (TypeError, ValueError):
                return None
    return None


def _to_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
