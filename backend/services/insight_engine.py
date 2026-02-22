from __future__ import annotations

from typing import Any, Dict, List


def build_fundamentals(
    normalized: Dict[str, Any],
    segmentation_output: Dict[str, Any] | None = None,
    behavior_output: Dict[str, Any] | None = None,
    forecast_output: Dict[str, Any] | None = None,
    commercial_output: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    doc_type = normalized.get("document_type")
    if doc_type == "supplier_report":
        return _supplier_fundamentals(
            normalized=normalized,
            segmentation_output=segmentation_output or {},
            behavior_output=behavior_output or {},
            forecast_output=forecast_output or {},
        )
    if doc_type == "commercial_report":
        return _commercial_fundamentals(
            normalized=normalized,
            commercial_output=commercial_output or {},
        )
    if doc_type == "real_estate_generic":
        return _generic_real_estate_fundamentals(normalized=normalized)
    return {
        "document_type": doc_type,
        "fundamental_metrics": [],
        "improvement_plan": [],
        "summary": {"message": "No fundamentals available for this document type"},
    }


def _supplier_fundamentals(
    normalized: Dict[str, Any],
    segmentation_output: Dict[str, Any],
    behavior_output: Dict[str, Any],
    forecast_output: Dict[str, Any],
) -> Dict[str, Any]:
    seg_summary = (segmentation_output.get("output") or {}).get("summary", {})
    beh_summary = (behavior_output.get("output") or {}).get("summary", {})
    for_summary = (forecast_output.get("output") or {}).get("summary", {})

    total = max(int(seg_summary.get("total_suppliers", 0)), 1)
    high = int(seg_summary.get("high_risk", 0))
    critical = int(beh_summary.get("critical", 0))
    forecast_high = int(for_summary.get("high_risk_forecast", 0))

    high_risk_ratio = high / total
    critical_ratio = critical / total
    forecast_high_ratio = forecast_high / total

    metrics = [
        _metric(
            "supplier_high_risk_ratio",
            round(high_risk_ratio, 4),
            "Proporción de proveedores en riesgo HIGH",
            "lower_is_better",
            target=0.20,
            status=_status_lower_better(high_risk_ratio, warn=0.20, critical=0.35),
            why="Condiciona continuidad operativa y exposición de la cadena de suministro.",
        ),
        _metric(
            "supplier_critical_behavior_ratio",
            round(critical_ratio, 4),
            "Proporción con comportamiento operativo crítico",
            "lower_is_better",
            target=0.15,
            status=_status_lower_better(critical_ratio, warn=0.15, critical=0.30),
            why="Anticipa incumplimientos recurrentes y fallos de servicio.",
        ),
        _metric(
            "supplier_forecast_high_ratio",
            round(forecast_high_ratio, 4),
            "Proporción con riesgo proyectado HIGH",
            "lower_is_better",
            target=0.20,
            status=_status_lower_better(forecast_high_ratio, warn=0.20, critical=0.35),
            why="Permite actuar antes de que el riesgo impacte en plazos y costes.",
        ),
    ]

    plan: List[Dict[str, Any]] = []
    if high_risk_ratio >= 0.35:
        plan.append(
            _action(
                "alta",
                "Reducir concentración de proveedores HIGH en 8 semanas",
                "Lanzar sourcing alternativo y limitar nuevas órdenes en proveedores HIGH dependientes.",
                ["supplier_high_risk_ratio"],
            )
        )
    if critical_ratio >= 0.30:
        plan.append(
            _action(
                "alta",
                "Estabilizar proveedores críticos en 30 días",
                "Implantar comité semanal de incidencias y cláusulas de SLA/penalización.",
                ["supplier_critical_behavior_ratio"],
            )
        )
    if forecast_high_ratio >= 0.35:
        plan.append(
            _action(
                "media",
                "Mitigar riesgo proyectado antes del próximo trimestre",
                "Rebalancear cargas y reforzar controles preventivos de retraso/incidencias.",
                ["supplier_forecast_high_ratio"],
            )
        )
    if not plan:
        plan.append(
            _action(
                "baja",
                "Mantener gobierno de proveedores",
                "Monitoreo quincenal y revisión de umbrales de riesgo para mejora continua.",
                ["supplier_high_risk_ratio", "supplier_critical_behavior_ratio", "supplier_forecast_high_ratio"],
            )
        )

    return {
        "document_type": "supplier_report",
        "fundamental_metrics": metrics,
        "improvement_plan": plan,
        "summary": {
            "focus": "resilience_supply_chain",
            "total_suppliers": int(seg_summary.get("total_suppliers", 0)),
            "priority_level": _overall_priority([m["status"] for m in metrics]),
        },
    }


def _commercial_fundamentals(
    normalized: Dict[str, Any],
    commercial_output: Dict[str, Any],
) -> Dict[str, Any]:
    kpis = (commercial_output.get("output") or {}).get("kpis", {})
    indicators = normalized.get("commercial_indicators", {}) or {}

    conversion = float(kpis.get("conversion_rate", 0.0) or 0.0)
    cancellation = float(kpis.get("cancellation_rate", 0.0) or 0.0)
    sell_through = float(kpis.get("sell_through_rate", 0.0) or 0.0)
    trend = str(kpis.get("trend", "flat"))

    metrics = [
        _metric(
            "commercial_conversion_rate",
            round(conversion, 4),
            "Conversión lead->reserva",
            "higher_is_better",
            target=0.12,
            status=_status_higher_better(conversion, warn=0.12, critical=0.08),
            why="Mide eficacia real del embudo comercial.",
        ),
        _metric(
            "commercial_cancellation_rate",
            round(cancellation, 4),
            "Tasa de cancelación de reservas",
            "lower_is_better",
            target=0.15,
            status=_status_lower_better(cancellation, warn=0.15, critical=0.25),
            why="Impacta directamente en previsión de ingresos y cashflow.",
        ),
        _metric(
            "commercial_sell_through_rate",
            round(sell_through, 4),
            "Sell-through de la promoción",
            "higher_is_better",
            target=0.50,
            status=_status_higher_better(sell_through, warn=0.50, critical=0.35),
            why="Indica velocidad de absorción del producto en mercado.",
        ),
        _metric(
            "commercial_sales_trend",
            trend,
            "Tendencia de ventas mensuales",
            "qualitative",
            target="up",
            status="critical" if trend == "down" else "warning" if trend == "flat" else "ok",
            why="Resume dirección de la tracción comercial del periodo.",
        ),
    ]

    plan: List[Dict[str, Any]] = []
    if conversion < 0.08:
        plan.append(
            _action(
                "alta",
                "Recuperar conversión comercial en 4-6 semanas",
                "Auditar calidad de leads, guion comercial y tiempos de respuesta por canal.",
                ["commercial_conversion_rate"],
            )
        )
    if cancellation >= 0.25:
        plan.append(
            _action(
                "alta",
                "Reducir cancelación por encima de umbral",
                "Analizar causas de cancelación y aplicar plan de retención pre-escritura.",
                ["commercial_cancellation_rate"],
            )
        )
    if sell_through < 0.35:
        plan.append(
            _action(
                "media",
                "Aumentar absorción de stock",
                "Ajustar pricing, segmentación y canales de captación según demanda.",
                ["commercial_sell_through_rate", "commercial_sales_trend"],
            )
        )
    if not plan:
        plan.append(
            _action(
                "baja",
                "Escalar crecimiento comercial sostenible",
                "Mantener seguimiento semanal de funnel y test A/B de campañas.",
                ["commercial_conversion_rate", "commercial_sell_through_rate"],
            )
        )

    return {
        "document_type": "commercial_report",
        "fundamental_metrics": metrics,
        "improvement_plan": plan,
        "summary": {
            "focus": "commercial_performance",
            "leads_generated": int(indicators.get("leads_generated", 0) or 0),
            "priority_level": _overall_priority([m["status"] for m in metrics]),
        },
    }


def _metric(
    key: str,
    value: Any,
    name: str,
    optimization: str,
    target: Any,
    status: str,
    why: str,
) -> Dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "value": value,
        "target": target,
        "optimization": optimization,
        "status": status,
        "why_it_matters": why,
    }


def _action(priority: str, title: str, recommendation: str, metrics: List[str]) -> Dict[str, Any]:
    return {
        "priority": priority,
        "title": title,
        "recommendation": recommendation,
        "linked_metrics": metrics,
    }


def _status_lower_better(value: float, warn: float, critical: float) -> str:
    if value >= critical:
        return "critical"
    if value >= warn:
        return "warning"
    return "ok"


def _status_higher_better(value: float, warn: float, critical: float) -> str:
    if value <= critical:
        return "critical"
    if value <= warn:
        return "warning"
    return "ok"


def _overall_priority(statuses: List[str]) -> str:
    if any(s == "critical" for s in statuses):
        return "high"
    if any(s == "warning" for s in statuses):
        return "medium"
    return "low"


def _generic_real_estate_fundamentals(normalized: Dict[str, Any]) -> Dict[str, Any]:
    interpretation = normalized.get("interpretation") or {}
    risks = interpretation.get("risks", []) or []
    metrics = interpretation.get("metrics", []) or []
    classification = interpretation.get("classification", {}) or {}

    risk_high = sum(1 for r in risks if str(r.get("severity", "")).lower() == "high")
    risk_med = sum(1 for r in risks if str(r.get("severity", "")).lower() == "medium")
    evidence_density = len(metrics) + len(risks)
    confidence = float(interpretation.get("confidence", 0.0) or 0.0)

    metrics_out = [
        _metric(
            "doc_interpretation_confidence",
            round(confidence, 4),
            "Confianza de interpretacion estructurada del documento",
            "higher_is_better",
            target=0.70,
            status=_status_higher_better(confidence, warn=0.70, critical=0.45),
            why="Si la interpretacion es baja, se requieren validaciones manuales antes de decidir.",
        ),
        _metric(
            "detected_high_risks",
            risk_high,
            "Riesgos severidad alta detectados",
            "lower_is_better",
            target=0,
            status="critical" if risk_high > 0 else "ok",
            why="Riesgos legales/financieros altos deben mitigarse antes de comprometer capital.",
        ),
        _metric(
            "document_evidence_density",
            evidence_density,
            "Cantidad de evidencias estructuradas (metricas + riesgos)",
            "higher_is_better",
            target=6,
            status="ok" if evidence_density >= 6 else "warning",
            why="Mayor densidad de evidencia mejora trazabilidad y calidad de recomendacion.",
        ),
    ]

    plan: List[Dict[str, Any]] = []
    if confidence < 0.45:
        plan.append(
            _action(
                "alta",
                "Reforzar extraccion documental",
                "Aplicar OCR/tabla avanzada y validar campos clave (precio, ubicacion, riesgos legales).",
                ["doc_interpretation_confidence"],
            )
        )
    if risk_high > 0:
        plan.append(
            _action(
                "alta",
                "Cerrar brechas de riesgo alto",
                "Resolver riesgos altos detectados con soporte legal/tecnico antes de decision final.",
                ["detected_high_risks"],
            )
        )
    if evidence_density < 6:
        plan.append(
            _action(
                "media",
                "Aumentar evidencia cuantitativa",
                "Solicitar anexos de comparables, costes, rentas y licencias para robustecer analisis.",
                ["document_evidence_density"],
            )
        )
    if not plan:
        plan.append(
            _action(
                "baja",
                "Mantener trazabilidad documental",
                "Continuar validando supuestos y versionando evidencia por corrida.",
                ["doc_interpretation_confidence", "document_evidence_density"],
            )
        )

    return {
        "document_type": "real_estate_generic",
        "fundamental_metrics": metrics_out,
        "improvement_plan": plan,
        "summary": {
            "focus": "document_understanding_and_risk_readiness",
            "classification_label": classification.get("label"),
            "medium_risks": risk_med,
            "priority_level": _overall_priority([m["status"] for m in metrics_out]),
        },
    }
