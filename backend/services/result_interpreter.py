from __future__ import annotations

from typing import Any, Dict, List


def build_result_interpretation(
    normalized: Dict[str, Any],
    decisions: Dict[str, Any],
    summary: Dict[str, Any],
    segmentation: Dict[str, Any] | None = None,
    behavior: Dict[str, Any] | None = None,
    forecast: Dict[str, Any] | None = None,
    commercial: Dict[str, Any] | None = None,
    real_estate_models: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    doc_type = normalized.get("document_type")
    if doc_type == "supplier_report":
        return _supplier_interpretation(normalized, decisions, summary, segmentation, behavior, forecast)
    if doc_type == "commercial_report":
        return _commercial_interpretation(normalized, decisions, summary, commercial, real_estate_models)
    return _generic_real_estate_interpretation(normalized, decisions, summary, real_estate_models)


def _supplier_interpretation(
    normalized: Dict[str, Any],
    decisions: Dict[str, Any],
    summary: Dict[str, Any],
    segmentation: Dict[str, Any] | None,
    behavior: Dict[str, Any] | None,
    forecast: Dict[str, Any] | None,
) -> Dict[str, Any]:
    suppliers = ((segmentation or {}).get("output") or {}).get("suppliers_segmented", [])
    behaviors = ((behavior or {}).get("output") or {}).get("supplier_behavior", [])
    forecasts = ((forecast or {}).get("output") or {}).get("supplier_forecast", [])
    behavior_map = {b.get("supplier_name"): b for b in behaviors}
    forecast_map = {f.get("supplier_name"): f for f in forecasts}

    top_risk = sorted(
        suppliers,
        key=lambda x: float(x.get("risk_score", 0.0) or 0.0),
        reverse=True,
    )[:5]
    supplier_insights: List[Dict[str, Any]] = []
    for row in top_risk:
        name = row.get("supplier_name")
        b = behavior_map.get(name, {})
        f = forecast_map.get(name, {})
        evidence = [
            f"risk_tier={row.get('risk_tier')}",
            f"risk_score={row.get('risk_score')}",
            f"dependency_pct={row.get('dependency_pct')}",
            f"incidents={row.get('incidents')}",
            f"avg_delay_days={row.get('avg_delay_days')}",
        ]
        if b:
            evidence.append(f"behavior_state={b.get('behavior_state')}")
            evidence.append(f"reliability_index={b.get('reliability_index')}")
        if f:
            evidence.append(f"forecast_risk_level={f.get('forecast_risk_level')}")
            evidence.append(f"forecast_risk_score={f.get('forecast_risk_score')}")

        supplier_insights.append(
            {
                "entity_type": "supplier",
                "entity_id": name,
                "interpretation": _interpret_supplier_row(row, b, f),
                "evidence": evidence,
            }
        )

    highlights = [
        f"Estado general: {summary.get('score_label', 'n/a')} ({summary.get('score', 'n/a')}/100).",
        f"Proveedores críticos: {summary.get('high_risk', 0)}.",
        f"Alertas activas: {summary.get('alerts', 0)}.",
    ]
    if summary.get("forecast_high", 0):
        highlights.append(f"Riesgo proyectado alto en {summary.get('forecast_high')} proveedores.")

    return {
        "document_type": "supplier_report",
        "executive_summary": _supplier_executive_summary(summary, decisions, top_risk),
        "highlights": highlights,
        "entity_interpretations": supplier_insights,
        "decision_interpretation": _decision_readable(decisions),
    }


def _commercial_interpretation(
    normalized: Dict[str, Any],
    decisions: Dict[str, Any],
    summary: Dict[str, Any],
    commercial: Dict[str, Any] | None,
    real_estate_models: Dict[str, Any] | None,
) -> Dict[str, Any]:
    kpis = ((commercial or {}).get("output") or {}).get("kpis", {})
    re_out = ((real_estate_models or {}).get("output") or {})
    highlights = [
        f"Estado general: {summary.get('score_label', 'n/a')} ({summary.get('score', 'n/a')}/100).",
        f"Tendencia comercial: {kpis.get('trend', 'n/a')}.",
        f"Conversión lead->reserva: {_pct(kpis.get('conversion_rate'))}.",
        f"Cancelación: {_pct(kpis.get('cancellation_rate'))}.",
        f"Sell-through: {_pct(kpis.get('sell_through_rate'))}.",
    ]
    if re_out:
        highlights.append(f"Score inversión modelo inmobiliario: {re_out.get('investment_score_0_100', 'n/a')}.")
        highlights.append(f"Liquidez estimada (P50): {re_out.get('liquidity_days_p50', 'n/a')} días.")
        model_conf = re_out.get("model_confidence_0_100")
        if model_conf is not None:
            highlights.append(f"Confianza del modelo: {model_conf}/100.")
        price_band = (((re_out.get("prediction_intervals") or {}).get("sale_price_eur") or {}))
        if price_band:
            highlights.append(
                f"Rango de precio esperado (P10-P90): {price_band.get('p10', 'n/a')} - {price_band.get('p90', 'n/a')} EUR."
            )
        conservative = ((re_out.get("scenario_analysis") or {}).get("conservative") or {})
        if conservative:
            highlights.append(
                f"Escenario conservador: score inversión {conservative.get('investment_score_0_100', 'n/a')}."
            )

    entity_interpretations = [
        {
            "entity_type": "commercial_funnel",
            "entity_id": "global",
            "interpretation": _interpret_commercial_kpis(kpis, re_out),
            "evidence": [
                f"conversion_rate={kpis.get('conversion_rate')}",
                f"cancellation_rate={kpis.get('cancellation_rate')}",
                f"sell_through_rate={kpis.get('sell_through_rate')}",
                f"trend={kpis.get('trend')}",
                f"investment_score_0_100={re_out.get('investment_score_0_100')}",
                f"liquidity_days_p50={re_out.get('liquidity_days_p50')}",
                f"model_confidence_0_100={re_out.get('model_confidence_0_100')}",
            ],
        }
    ]

    return {
        "document_type": "commercial_report",
        "executive_summary": _commercial_executive_summary(summary, decisions, kpis, re_out),
        "highlights": highlights,
        "entity_interpretations": entity_interpretations,
        "decision_interpretation": _decision_readable(decisions),
    }


def _generic_real_estate_interpretation(
    normalized: Dict[str, Any],
    decisions: Dict[str, Any],
    summary: Dict[str, Any],
    real_estate_models: Dict[str, Any] | None,
) -> Dict[str, Any]:
    interpretation = normalized.get("interpretation", {}) or {}
    risks = interpretation.get("risks", []) or []
    metrics = interpretation.get("metrics", []) or []
    re_out = ((real_estate_models or {}).get("output") or {})
    highlights = [
        f"Estado general: {summary.get('score_label', 'n/a')} ({summary.get('score', 'n/a')}/100).",
        f"Confianza de interpretación documental: {interpretation.get('confidence', 'n/a')}.",
        f"Riesgos detectados: {len(risks)}.",
        f"Métricas detectadas: {len(metrics)}.",
    ]
    if re_out:
        highlights.append(f"Precio esperado: {re_out.get('expected_sale_price_eur', 'n/a')} EUR.")
        highlights.append(f"Renta esperada: {re_out.get('expected_rent_eur_month', 'n/a')} EUR/mes.")
        highlights.append(f"Liquidez estimada: {re_out.get('liquidity_days_p50', 'n/a')} días.")
        model_conf = re_out.get("model_confidence_0_100")
        if model_conf is not None:
            highlights.append(f"Confianza del modelo: {model_conf}/100.")
        price_band = (((re_out.get("prediction_intervals") or {}).get("sale_price_eur") or {}))
        if price_band:
            highlights.append(
                f"Banda de precio P10-P90: {price_band.get('p10', 'n/a')} - {price_band.get('p90', 'n/a')} EUR."
            )
        conservative = ((re_out.get("scenario_analysis") or {}).get("conservative") or {})
        if conservative:
            highlights.append(
                f"Escenario conservador: liquidez {conservative.get('liquidity_days_p50', 'n/a')} días."
            )

    entity_interpretations = [
        {
            "entity_type": "document",
            "entity_id": "global",
            "interpretation": _interpret_generic_doc(interpretation, re_out),
            "evidence": [
                f"classification={((interpretation.get('classification') or {}).get('label'))}",
                f"confidence={interpretation.get('confidence')}",
                f"risk_count={len(risks)}",
                f"metrics_count={len(metrics)}",
                f"investment_score_0_100={re_out.get('investment_score_0_100')}",
                f"model_confidence_0_100={re_out.get('model_confidence_0_100')}",
            ],
        }
    ]

    return {
        "document_type": "real_estate_generic",
        "executive_summary": _generic_executive_summary(summary, decisions, interpretation, re_out),
        "highlights": highlights,
        "entity_interpretations": entity_interpretations,
        "decision_interpretation": _decision_readable(decisions),
    }


def _supplier_executive_summary(
    summary: Dict[str, Any],
    decisions: Dict[str, Any],
    top_risk: List[Dict[str, Any]],
) -> Dict[str, Any]:
    strategic = decisions.get("strategic_decisions", []) or []
    alerts = decisions.get("risk_alerts", []) or []
    score_label = summary.get("score_label", "n/a")

    overview = (
        f"El documento muestra un escenario {score_label.lower()} para la operacion con proveedores. "
        "Hay senales de riesgo que requieren seguimiento para evitar impactos en plazos y costos."
    )

    top_entities = []
    for row in top_risk[:3]:
        top_entities.append(
            f"{row.get('supplier_name', 'n/a')} ({row.get('risk_tier', 'n/a')}, score {row.get('risk_score', 'n/a')})"
        )

    actions = []
    for decision in strategic[:3]:
        supplier = decision.get("supplier", "Proveedor")
        action = decision.get("action", "Revisar")
        actions.append(f"{supplier}: {action}")

    if not actions:
        actions.append("Priorizar revisiones en proveedores de riesgo alto y dependencia elevada.")

    return {
        "title": "Resumen ejecutivo del documento",
        "overview": overview,
        "key_points": _supplier_key_points(summary, decisions, top_risk),
        "top_entities": top_entities,
        "recommended_actions": actions,
    }


def _commercial_executive_summary(
    summary: Dict[str, Any],
    decisions: Dict[str, Any],
    kpis: Dict[str, Any],
    re_out: Dict[str, Any],
) -> Dict[str, Any]:
    strategic = decisions.get("strategic_decisions", []) or []
    alerts = decisions.get("risk_alerts", []) or []
    score_label = summary.get("score_label", "n/a")
    score = summary.get("score", "n/a")
    trend = kpis.get("trend", "n/a")
    bd = summary.get("score_breakdown", {}) or {}

    overview = (
        f"El documento comercial refleja un estado {score_label.lower()} del proceso de ventas. "
        f"La tendencia actual se interpreta como {trend} y sugiere ajustar la ejecucion comercial. "
        f"{_score_breakdown_text(score, bd)}"
    )

    actions = []
    for decision in strategic[:3]:
        supplier = decision.get("supplier", "Unidad")
        action = decision.get("action", "Optimizar")
        actions.append(f"{supplier}: {action}")

    if not actions:
        actions.append("Mejorar conversion comercial y validar causas de friccion del embudo.")

    return {
        "title": "Resumen ejecutivo del documento",
        "overview": overview,
        "key_points": _commercial_key_points(kpis, alerts, re_out),
        "top_entities": [f"Tendencia comercial: {trend}"],
        "recommended_actions": actions,
    }


def _commercial_key_points(kpis: Dict[str, Any], alerts: List[Dict[str, Any]], re_out: Dict[str, Any]) -> List[str]:
    conversion = float(kpis.get("conversion_rate") or 0.0)
    cancellation = float(kpis.get("cancellation_rate") or 0.0)
    sell_through = float(kpis.get("sell_through_rate") or 0.0)
    trend = str(kpis.get("trend") or "flat")
    has_data = any([conversion > 0, cancellation > 0, sell_through > 0])

    points: List[str] = []

    if not has_data:
        points.append("No se detectaron KPIs comerciales en el documento; revisar estructura o formato del PDF.")
        points.append("Sin datos de conversion, absorcion ni cancelacion disponibles para el periodo.")
    else:
        if conversion > 0:
            target_ok = conversion >= 0.12
            points.append(
                f"Conversion lead-reserva: {conversion:.1%} ({'por encima' if target_ok else 'por debajo'} del objetivo 12%)."
            )
        if sell_through > 0:
            points.append(
                f"Sell-through de la promocion: {sell_through:.1%} "
                f"({'objetivo alcanzado' if sell_through >= 0.50 else 'por debajo del 50% objetivo'})."
            )
        if cancellation >= 0.20:
            points.append(f"Tasa de cancelacion elevada ({cancellation:.1%}); impacto directo en prevision de ingresos.")
        if trend == "down":
            points.append("Tendencia de ventas decreciente en el periodo; se requiere revision de estrategia urgente.")
        elif trend == "flat":
            points.append("Tendencia plana; ajustar ejecucion comercial para retomar crecimiento.")

    if alerts:
        points.append(f"{len(alerts)} alerta(s) operativa(s) activa(s) a monitorear en el corto plazo.")

    invest = re_out.get("investment_score_0_100")
    if invest is not None:
        points.append(f"Score de inversion inmobiliario del modelo: {invest}/100.")

    return points[:4]


def _generic_executive_summary(
    summary: Dict[str, Any],
    decisions: Dict[str, Any],
    interpretation: Dict[str, Any],
    re_out: Dict[str, Any],
) -> Dict[str, Any]:
    strategic = decisions.get("strategic_decisions", []) or []
    alerts = decisions.get("risk_alerts", []) or []
    score_label = summary.get("score_label", "n/a")
    classification = (interpretation.get("classification") or {}).get("label", "unknown")
    confidence = interpretation.get("confidence", "n/a")

    overview = (
        f"Se interpreto el documento como {classification} con confianza {confidence}. "
        f"El estado general del escenario es {score_label.lower()} y permite avanzar con analisis tecnico detallado."
    )

    actions = []
    for decision in strategic[:3]:
        action = decision.get("action", "Evaluar")
        priority = decision.get("priority", "")
        actions.append(f"[{priority.upper()}] {action}" if priority else action)

    if not actions:
        actions.append("Validar datos criticos del PDF para aumentar confianza y profundidad del analisis.")

    return {
        "title": "Resumen ejecutivo del documento",
        "overview": overview,
        "key_points": _generic_key_points(interpretation, re_out),
        "top_entities": [f"Clasificacion documental: {classification}"],
        "recommended_actions": actions,
    }


def _interpret_supplier_row(row: Dict[str, Any], b: Dict[str, Any], f: Dict[str, Any]) -> str:
    tier = str(row.get("risk_tier", "LOW"))
    dep = float(row.get("dependency_pct") or 0.0)
    inc = float(row.get("incidents") or 0.0)
    delay = float(row.get("avg_delay_days") or 0.0)
    behavior_state = str(b.get("behavior_state", "stable"))
    forecast_level = str(f.get("forecast_risk_level", "LOW"))

    if tier == "HIGH" or forecast_level == "HIGH":
        return (
            "Proveedor de alta prioridad: combinación de riesgo alto actual/proyectado "
            "y señales operativas exige plan de mitigación inmediato."
        )
    if dep >= 50 and (inc >= 8 or delay >= 15):
        return (
            "Proveedor concentrado con fricción operativa: conviene diversificar dependencia "
            "y corregir retrasos/incidencias."
        )
    if behavior_state == "warning":
        return "Proveedor en observación: estabilidad intermedia, requiere monitoreo cercano."
    return "Proveedor con perfil controlado bajo los umbrales actuales."


def _interpret_commercial_kpis(kpis: Dict[str, Any], re_out: Dict[str, Any]) -> str:
    conversion = float(kpis.get("conversion_rate") or 0.0)
    cancellation = float(kpis.get("cancellation_rate") or 0.0)
    sell = float(kpis.get("sell_through_rate") or 0.0)
    trend = str(kpis.get("trend") or "flat")
    invest = float(re_out.get("investment_score_0_100") or 50.0)
    liq = float(re_out.get("liquidity_days_p50") or 120.0)
    conf = float(re_out.get("model_confidence_0_100") or 70.0)

    if trend == "down" or cancellation >= 0.20:
        return "Embudo comercial tensionado: caída de tracción o cancelación elevada afecta previsión."
    if conf < 55:
        return "El modelo aporta señales útiles, pero con incertidumbre elevada: validar supuestos clave."
    if conversion < 0.10 or sell < 0.50:
        return "Eficiencia comercial mejorable: conversión/absorción por debajo de objetivo."
    if invest >= 70 and liq <= 120:
        return "Escenario comercial-inversión favorable con buena velocidad esperada."
    return "Escenario mixto: sin riesgo extremo, pero requiere optimización táctica."


def _interpret_generic_doc(interpretation: Dict[str, Any], re_out: Dict[str, Any]) -> str:
    conf = float(interpretation.get("confidence") or 0.0)
    invest = float(re_out.get("investment_score_0_100") or 50.0)
    liq = float(re_out.get("liquidity_days_p50") or 140.0)
    model_conf = float(re_out.get("model_confidence_0_100") or 70.0)
    if conf < 0.45:
        return "Interpretación documental débil: reforzar extracción antes de decidir inversión."
    if model_conf < 55:
        return "Predicción con incertidumbre alta: conviene validar precio, renta y comparables antes de decidir."
    if invest < 40:
        return "Modelo sugiere baja conveniencia financiera para el escenario detectado."
    if liq > 180:
        return "Liquidez esperada lenta: posible presión de precio/tiempo de comercialización."
    return "Documento interpretable con señales razonables para análisis técnico."


def _decision_readable(decisions: Dict[str, Any]) -> Dict[str, Any]:
    strategic = decisions.get("strategic_decisions", []) or []
    alerts = decisions.get("risk_alerts", []) or []
    return {
        "strategic_count": len(strategic),
        "alerts_count": len(alerts),
        "top_strategic": strategic[:5],
        "top_alerts": alerts[:5],
    }


def _score_breakdown_text(score: Any, bd: Dict[str, Any]) -> str:
    """Genera una frase que explica de donde viene el score numerico."""
    if not bd:
        return ""
    parts: List[str] = [f"base 42 pts"]
    trend_bonus = bd.get("trend_bonus", 0)
    if trend_bonus > 0:
        parts.append(f"tendencia positiva +{trend_bonus} pts")
    elif trend_bonus < 0:
        parts.append(f"tendencia negativa {trend_bonus} pts")
    conv_pts = bd.get("conversion_points", 0)
    if conv_pts > 0:
        parts.append(f"conversion +{conv_pts:.0f} pts")
    sell_pts = bd.get("sell_through_points", 0)
    if sell_pts > 0:
        parts.append(f"absorcion +{sell_pts:.0f} pts")
    invest_pts = bd.get("invest_points", 0)
    if invest_pts > 0:
        parts.append(f"score inversion +{invest_pts:.0f} pts")
    conf_adj = bd.get("model_confidence_adjustment", 0)
    if conf_adj > 0:
        parts.append(f"confianza modelo +{conf_adj:.0f} pts")
    elif conf_adj < 0:
        parts.append(f"confianza modelo {conf_adj:.0f} pts")
    cancel_pen = bd.get("cancellation_penalty", 0)
    if cancel_pen > 0:
        parts.append(f"cancelacion -{cancel_pen:.0f} pts")
    liq_pen = bd.get("liquidity_penalty", 0)
    if liq_pen > 0:
        parts.append(f"liquidez lenta -{liq_pen:.0f} pts")
    cons_pen = bd.get("conservative_penalty", 0)
    if cons_pen > 0:
        parts.append(f"escenario conservador -{cons_pen:.0f} pts")
    alerts_pen = bd.get("alerts_penalty", 0)
    if alerts_pen > 0:
        parts.append(f"alertas -{alerts_pen:.0f} pts")
    has_kpi_data = any([conv_pts > 0, sell_pts > 0, cancel_pen > 0, invest_pts > 0])
    if not has_kpi_data:
        return f"Score {score}/100: no se detectaron KPIs comerciales en el documento — el score refleja unicamente el punto de partida base sin datos adicionales."
    return f"Score {score}/100 compuesto por: {'; '.join(parts)}."


def _supplier_key_points(
    summary: Dict[str, Any],
    decisions: Dict[str, Any],
    top_risk: List[Dict[str, Any]],
) -> List[str]:
    high_risk = int(summary.get("high_risk", 0) or 0)
    forecast_high = int(summary.get("forecast_high", 0) or 0)
    alerts = decisions.get("risk_alerts", []) or []
    strategic = decisions.get("strategic_decisions", []) or []

    points: List[str] = []

    if high_risk > 0:
        points.append(f"{high_risk} proveedor(es) en riesgo HIGH requieren accion prioritaria.")
    else:
        points.append("Ningun proveedor en riesgo critico detectado en el periodo.")

    if top_risk:
        top_name = top_risk[0].get("supplier_name", "n/a")
        top_score = top_risk[0].get("risk_score", "n/a")
        top_tier = top_risk[0].get("risk_tier", "n/a")
        points.append(f"Proveedor de mayor riesgo: {top_name} (tier {top_tier}, score {top_score}).")

    if forecast_high > 0:
        points.append(f"Riesgo proyectado alto en {forecast_high} proveedor(es) en el horizonte analizado.")

    if alerts:
        points.append(f"{len(alerts)} alerta(s) activa(s) con impacto en continuidad operativa.")
    elif strategic:
        points.append(f"{len(strategic)} decision(es) estrategica(s) propuesta(s) por el motor de analisis.")

    return points[:4]


def _generic_key_points(
    interpretation: Dict[str, Any],
    re_out: Dict[str, Any],
) -> List[str]:
    risks = interpretation.get("risks", []) or []
    metrics = interpretation.get("metrics", []) or []
    confidence = float(interpretation.get("confidence", 0.0) or 0.0)
    high_risks = [r for r in risks if str(r.get("severity", "")).lower() == "high"]

    points: List[str] = []

    if confidence >= 0.70:
        points.append(f"Interpretacion documental con alta confianza ({confidence:.0%}); datos fiables para decision.")
    elif confidence >= 0.45:
        points.append(f"Confianza de extraccion moderada ({confidence:.0%}); validar campos clave antes de decidir.")
    else:
        points.append(f"Confianza de extraccion baja ({confidence:.0%}); reforzar datos fuente antes de comprometer capital.")

    if high_risks:
        points.append(f"{len(high_risks)} riesgo(s) de severidad alta detectado(s); requieren mitigacion previa a decision.")
    elif risks:
        points.append(f"{len(risks)} riesgo(s) de severidad media/baja detectado(s); monitorear en seguimiento.")
    else:
        points.append("Sin riesgos criticos detectados en el documento.")

    invest = re_out.get("investment_score_0_100")
    if invest is not None:
        points.append(f"Score de inversion del modelo: {invest:.1f}/100.")

    price = re_out.get("expected_sale_price_eur")
    liq = re_out.get("liquidity_days_p50")
    if price is not None:
        liq_text = f"; liquidez estimada: {liq:.0f} dias" if liq is not None else ""
        points.append(f"Precio de venta esperado segun modelo: {price:,.0f} EUR{liq_text}.")
    elif not metrics:
        points.append("Documento con escasa informacion cuantitativa; complementar con datos adicionales.")

    return points[:4]


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "n/a"
