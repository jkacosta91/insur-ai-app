from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict

from backend.services.llm_client import send_openai_prompt


MAX_FULL_TEXT_CHARS = 12000
MAX_PROMPT_CHARS = 24000
DEFAULT_DATASET_VERSION = "dataset_version_no_disponible"

SYSTEM_PROMPT_PRD = """
Actua como un experto en producto con especializacion en analisis de datos,
machine learning aplicado al sector inmobiliario y generacion de documentos
de requisitos de producto (PRD) orientados a la toma de decisiones.

Genera un PRD completo a partir de la informacion estructurada y las
predicciones de modelos de machine learning proporcionadas.

Debes cumplir estas reglas:
1. Seguir la estructura de PRD profesional estandar.
2. No inventar datos ni inferir valores que no esten presentes.
3. Citar siempre el origen de cada cifra o afirmacion
   (Documento Fuente | Dataset Sectorial | Modelo ML X).
4. Priorizar claridad para comite de inversion, producto y equipos tecnicos.
5. Incluir metricas de exito cuantificables y escenarios comparativos.
6. Senalar supuestos, restricciones y riesgos.
""".strip()


def generate_prd_with_openai(payload: Dict[str, Any]) -> Dict[str, Any]:
    prompt = build_prd_prompt(payload)
    response = send_openai_prompt(
        prompt=prompt,
        model=os.getenv("OPENAI_PRD_MODEL", "gpt-4.1"),
        max_tokens=2600,
        temperature=0.2,
        timeout=60,
    )

    if not response.get("ok"):
        details = response.get("error_text", "") or ""
        status_code = response.get("status_code")
        if "insufficient_quota" in details.lower() or "billing" in details.lower():
            return _fallback_result(
                payload,
                warning="OpenAI unavailable: low credits.",
                details=f"status_code={status_code}",
            )
        if response.get("error") == "missing_api_key":
            return _fallback_result(
                payload,
                warning="OpenAI unavailable: missing OPENAI_API_KEY.",
                details="local fallback used",
            )
        return _fallback_result(
            payload,
            warning="OpenAI API error.",
            details=f"status_code={status_code}; details={details[:1000]}",
        )

    prd_text = (response.get("text") or "").strip()
    if not prd_text:
        return _fallback_result(
            payload,
            warning="OpenAI response was empty.",
            details="local fallback used",
        )

    if len(prd_text) < 800:
        return _fallback_result(
            payload,
            warning="OpenAI response too short for PRD quality threshold.",
            details="local rich fallback used",
        )

    return {
        "provider": "openai",
        "prd_text": prd_text,
        "warning": None,
        "details": "Generated with OpenAI.",
        "note": "Generated with OpenAI.",
    }


# Backward compatible alias used by existing imports/routes.
generate_prd_with_claude = generate_prd_with_openai


def build_prd_prompt(payload: Dict[str, Any]) -> str:
    safe_payload = sanitize_payload(payload)
    structured_doc_json = safe_payload.get("normalized", {})
    features_json = _build_features_json(safe_payload)
    model_outputs_json = _build_model_outputs_json(safe_payload)
    decision_engine_json = safe_payload.get("decisions", {})
    metadata = _build_metadata(safe_payload)
    project_title = str(
        safe_payload.get("project_title")
        or safe_payload.get("doc_name")
        or safe_payload.get("document_name")
        or "PRD Analisis Inmobiliario"
    )
    document_version = str(safe_payload.get("document_version") or "v1.0")
    analyst_name = str(safe_payload.get("analyst_name") or "Equipo Analitico Grupo Insur")
    analysis_date = str(metadata.get("analysis_date"))

    user_prompt = f"""
Genera un PRD completo basado en la siguiente informacion estructurada.

1. METADATOS
- Titulo: {project_title}
- Fecha: {analysis_date}
- Version: {document_version}
- Autor(es): {analyst_name}

2. INFORMACION ESTRUCTURADA EXTRAIDA DEL PDF:
{json.dumps(structured_doc_json, ensure_ascii=False, indent=2)}

3. FEATURES SECTORIALES:
{json.dumps(features_json, ensure_ascii=False, indent=2)}

4. MODELOS ML APLICADOS:
{json.dumps(model_outputs_json, ensure_ascii=False, indent=2)}

5. RESULTADO DEL MOTOR DE DECISIONES:
{json.dumps(decision_engine_json, ensure_ascii=False, indent=2)}

6. DATOS DE CALIDAD / CONFIANZA
- extraction_confidence: {metadata.get("extraction_confidence", "dato no disponible")}
- dataset_version: {metadata.get("dataset_version", DEFAULT_DATASET_VERSION)}
- model_versions: {json.dumps(metadata.get("model_versions", {}), ensure_ascii=False)}

Estructura obligatoria del PRD:
1. TITULO Y METADATOS
   - Nombre del proyecto
   - Autor(es)
   - Fecha y version
2. INTRODUCCION Y CONTEXTO
   - Breve descripcion del ambito inmobiliario
   - Por que se analiza este documento PDF
3. PROBLEMA O NECESIDAD
   - Que decision inmobiliaria se quiere tomar
   - Descripcion cuantitativa del objetivo principal
4. OBJETIVOS Y EXITO
   - Objetivos del analisis
   - Indicadores de exito SMART cuantificables
5. STAKEHOLDERS / USUARIOS DEL PRD
   - Definir quien toma decisiones con este PRD
6. REQUISITOS FUNCIONALES
   - Que debe hacer la aplicacion o el analisis
   - Requisitos extraidos del PDF y del contexto
7. REQUISITOS NO FUNCIONALES
   - Rendimiento, confianza minima, trazabilidad, etc.
8. ANALISIS DE DATOS DEL DOCUMENTO
   - Variables extraidas con evidencia y fuente
   - Tablas de metricas
9. RESULTADOS DE MODELOS ML
   - Modelo 1: Prediccion precio venta
   - Modelo 2: Prediccion alquiler
   - Modelo 3: Score de inversion / riesgo
   - Modelo 4: Probabilidad de liquidez / tiempo de comercializacion
   Cada resultado debe incluir:
   - Valor predictivo
   - Intervalos (P10,P50,P90 si aplica)
   - Fuente (Modelo X vY.Y)
10. DECISIONES SUGERIDAS
    - Decision sugerida
    - Justificacion numerica
11. ESCENARIOS ALTERNATIVOS
    - Escenario conservador
    - Escenario agresivo
12. RIESGOS Y LIMITACIONES
    - Riesgos cuantificados
    - Supuestos y restricciones
13. METRICAS DE EXITO
    - KPI esperados
    - Umbrales de aceptacion
14. APPENDICES
    - Citas exactas del PDF
    - Glosario de terminos
    - Versiones de dataset y modelos

Formato:
- Profesional
- Orientado a comite de inversion
- Sin adornos narrativos
- Enfoque analitico
- Incluir tablas resumidas donde aplique.
- Senalar explicitamente si falta informacion critica.
- Si no hay informacion suficiente para completar una seccion: "Informacion no disponible en los datos proporcionados".
""".strip()

    prompt = f"SYSTEM PROMPT\n{SYSTEM_PROMPT_PRD}\n\nUSER PROMPT\n{user_prompt}"
    return prompt[:MAX_PROMPT_CHARS]


def sanitize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    safe_payload = dict(payload)
    extraction = safe_payload.get("extraction")
    if isinstance(extraction, dict):
        full_text = extraction.get("full_text")
        if isinstance(full_text, str) and len(full_text) > MAX_FULL_TEXT_CHARS:
            extraction = dict(extraction)
            extraction["full_text"] = full_text[:MAX_FULL_TEXT_CHARS] + "\n\n[TRUNCATED]"
            safe_payload["extraction"] = extraction

    decisions = safe_payload.get("decisions")
    if isinstance(decisions, dict):
        strategic = decisions.get("strategic_decisions") or []
        alerts = decisions.get("risk_alerts") or []
        decisions = dict(decisions)
        decisions["strategic_decisions"] = strategic[:20]
        decisions["risk_alerts"] = alerts[:30]
        safe_payload["decisions"] = decisions

    interpretation = safe_payload.get("result_interpretation")
    if isinstance(interpretation, dict):
        entities = interpretation.get("entity_interpretations") or []
        interpretation = dict(interpretation)
        interpretation["entity_interpretations"] = entities[:10]
        safe_payload["result_interpretation"] = interpretation

    return safe_payload


def generate_prd_local(payload: Dict[str, Any]) -> str:
    normalized = payload.get("normalized", {}) or {}
    decisions = payload.get("decisions", {}) or {}
    summary = payload.get("summary", {}) or {}
    traceability = payload.get("traceability", {}) or {}
    real_estate_models = payload.get("real_estate_models", {}) or {}
    result_interpretation = payload.get("result_interpretation", {}) or {}
    fundamentals = payload.get("fundamentals", {}) or {}
    extraction_summary = payload.get("extraction_summary", {}) or {}

    doc_type = normalized.get("document_type", "dato no disponible")
    summary_label = summary.get("score_label", "dato no disponible")
    summary_risk = summary.get("risk_status", "dato no disponible")
    executive_message = summary.get("executive_message", "dato no disponible")
    score = summary.get("score", "n/a")

    strategic = decisions.get("strategic_decisions", []) or []
    alerts = decisions.get("risk_alerts", []) or []
    highlights = (result_interpretation.get("highlights") or [])[:5]
    models = (traceability.get("models_executed") or [])[:10]

    model_lines = "\n".join(
        f"- {m.get('name', 'dato no disponible')} (motor: {m.get('engine', 'dato no disponible')})"
        for m in models
    ) or "- dato no disponible"

    top_decisions = "\n".join(
        f"- [Prioridad {d.get('priority', 'media').upper()}] {d.get('action', 'sin accion')} — Motivo: {', '.join(d.get('why', [])) or 'dato no disponible'}"
        for d in strategic[:8]
    ) or "- dato no disponible"

    top_alerts = "\n".join(
        f"- [Severidad {a.get('severity', 'media').upper()}] {a.get('signal', 'sin senal')}"
        for a in alerts[:10]
    ) or "- Sin alertas activas detectadas."

    hallazgos_rows = []
    for item in (result_interpretation.get("entity_interpretations") or [])[:6]:
        hallazgo = item.get("interpretation", "dato no disponible")
        evidence = ", ".join((item.get("evidence") or [])[:3]) or "dato no disponible"
        hallazgos_rows.append(f"| {item.get('entity_type', 'entidad')} | {evidence} | {hallazgo} |")
    hallazgos_table = "\n".join(hallazgos_rows) or "| dato no disponible | dato no disponible | dato no disponible |"

    interpretation = normalized.get("interpretation") or {} if isinstance(normalized, dict) else {}
    metrics = interpretation.get("metrics", []) if isinstance(interpretation, dict) else []
    metrics_count = len(metrics) if isinstance(metrics, list) else 0
    confidence = interpretation.get("confidence", "dato no disponible") if isinstance(interpretation, dict) else "dato no disponible"
    extraction_engine = extraction_summary.get("engine", "dato no disponible")
    page_count = extraction_summary.get("page_count", "dato no disponible")
    char_count = extraction_summary.get("char_count", "dato no disponible")

    executive_simple = "\n".join(f"- {h}" for h in highlights) or f"- {executive_message}"

    re_section = _format_re_model_output(real_estate_models)
    fundamentals_section = _format_fundamentals_text(fundamentals)
    traceability_section = _format_traceability_text(traceability)

    return f"""# PRD - Analisis Inmobiliario

## 1. Titulo y Metadatos
- Nombre del proyecto: {payload.get("project_title", "PRD Analisis Inmobiliario")}
- Autor(es): {payload.get("analyst_name", "Equipo Analitico Grupo Insur")}
- Fecha y version: {payload.get("analysis_date", "dato no disponible")} · {payload.get("document_version", "v1.0")}

## 2. Introduccion y Contexto
- Tipo de documento analizado: {doc_type}.
- Este PRD convierte los datos extraidos del PDF y las predicciones de modelos ML en decisiones accionables para el comite de inversion.

## 3. Problema o Necesidad
- Decision principal a soportar: priorizacion de acciones y recomendacion tecnica sobre la operacion.
- Estado actual: {summary_label} (score {score}/100, riesgo {summary_risk}).
- Mensaje ejecutivo: {executive_message}

## 4. Objetivos y Exito
- Objetivo del analisis: reducir incertidumbre y priorizar decisiones cuantitativas.
- Indicadores de exito: score general >= 70, alertas activas = 0, cumplimiento de acciones 30-60-90 dias.

## 5. Stakeholders / Usuarios del PRD
- Comite de inversion
- Liderazgo de producto
- Equipo tecnico de datos/modelos
- Equipo de operaciones/comercial

## 6. Requisitos Funcionales
- Extraer, normalizar y analizar informacion del PDF con trazabilidad de fuente.
- Ejecutar modelos ML aplicables y motor de decisiones segun tipo de documento.
- Emitir recomendaciones con evidencia cuantitativa y nivel de confianza.

## 7. Requisitos No Funcionales
- Trazabilidad completa de fuentes y decisiones por cada corrida (run_id).
- Confianza de extraccion visible para gobernanza y auditoria.
- Formato legible para usuarios tecnicos y ejecutivos sin ambiguedad.

## 8. Analisis de Datos del Documento
- Motor de extraccion: {extraction_engine}.
- Cobertura: paginas={page_count}, caracteres={char_count}, metricas detectadas={metrics_count}.
- Confianza de interpretacion estructurada: {confidence}.

| Entidad analizada | Evidencia extraida | Interpretacion |
|---|---|---|
{hallazgos_table}

## 9. Resultados de Modelos ML
Modelos ejecutados en esta corrida:
{model_lines}

{re_section}

## 10. Decisiones Sugeridas
Decisiones priorizadas por el motor de analisis:
{top_decisions}

## 11. Escenarios Alternativos
- Escenario conservador: ejecutar unicamente acciones de prioridad alta y validar datos criticos antes de comprometer capital.
- Escenario agresivo: ejecutar todas las decisiones priorizadas, reforzar monitoreo semanal y anticipar accion sobre riesgos medios.

## 12. Riesgos y Limitaciones
Alertas detectadas:
{top_alerts}
- Limitacion: datos incompletos o ambiguos en el PDF reducen la precision de los modelos y la profundidad del analisis.
- Supuesto: valores por defecto aplicados donde el documento no proporciona datos explicitos.

## 13. Metricas de Exito
- KPI esperados: reduccion de alertas activas, mejora del score general y estabilidad operativa/comercial.
- Umbrales de aceptacion: score >= 70 (favorable), alertas <= 1, confianza extraccion >= 0.70.
- Revision recomendada: 30-60-90 dias segun nivel de riesgo ({summary_risk}).

## 14. Appendices
{fundamentals_section}
{traceability_section}
- Mensaje ejecutivo del sistema: {executive_message}
"""


def _format_re_model_output(real_estate_models: Dict[str, Any]) -> str:
    if not real_estate_models:
        return "Modelos inmobiliarios: Informacion no disponible en los datos proporcionados."
    re_out = real_estate_models.get("output") or {}
    engine = real_estate_models.get("engine", "dato no disponible")
    model_name = real_estate_models.get("model", "dato no disponible")
    if not re_out:
        return "Modelos inmobiliarios: Sin salida disponible."

    lines = [f"### Predicciones del modelo inmobiliario ({model_name} · motor: {engine})"]

    sale_price = re_out.get("expected_sale_price_eur")
    rent = re_out.get("expected_rent_eur_month")
    invest = re_out.get("investment_score_0_100")
    liquidity = re_out.get("liquidity_days_p50")
    yield_pct = re_out.get("expected_gross_yield_pct")
    price_gap = re_out.get("price_gap_pct_vs_document")
    rent_gap = re_out.get("rent_gap_pct_vs_document")

    if sale_price is not None:
        lines.append(f"- Precio de venta esperado: {sale_price:,.0f} EUR")
    if rent is not None:
        lines.append(f"- Renta mensual esperada: {rent:,.0f} EUR/mes")
    if yield_pct is not None:
        lines.append(f"- Yield bruto esperado: {yield_pct:.2f}%")
    if invest is not None:
        lines.append(f"- Score de inversion (0-100): {invest:.1f}")
    if liquidity is not None:
        lines.append(f"- Liquidez estimada (P50): {liquidity:.0f} dias de comercializacion")
    if price_gap is not None:
        direction = "superior" if price_gap > 0 else "inferior"
        lines.append(f"- Precio modelo vs documento: {abs(price_gap):.1f}% {direction} al valor del documento")
    if rent_gap is not None:
        direction = "superior" if rent_gap > 0 else "inferior"
        lines.append(f"- Renta modelo vs documento: {abs(rent_gap):.1f}% {direction} al valor del documento")

    if len(lines) == 1:
        lines.append("- Sin predicciones numericas disponibles en la salida del modelo.")

    return "\n".join(lines)


def _format_fundamentals_text(fundamentals: Dict[str, Any]) -> str:
    if not fundamentals:
        return "### Fundamentales del sector\nInformacion no disponible en los datos proporcionados."

    doc_type = fundamentals.get("document_type", "")
    summary_f = fundamentals.get("summary", {}) or {}
    metrics_f = fundamentals.get("fundamental_metrics", []) or []
    plan_f = fundamentals.get("improvement_plan", []) or []

    lines = ["### Fundamentales del sector"]
    if summary_f:
        focus = summary_f.get("focus", "")
        priority = summary_f.get("priority_level", "")
        if focus:
            lines.append(f"- Foco de analisis: {focus}")
        if priority:
            lines.append(f"- Nivel de prioridad global: {priority}")

    if metrics_f:
        lines.append("- Metricas fundamentales:")
        for m in metrics_f[:4]:
            name = m.get("name", "metrica")
            value = m.get("value", "n/a")
            target = m.get("target", "n/a")
            status = m.get("status", "n/a")
            lines.append(f"  · {name}: valor={value}, objetivo={target}, estado={status}")

    if plan_f:
        lines.append("- Plan de mejora recomendado:")
        for p in plan_f[:3]:
            title = p.get("title", "accion")
            priority = p.get("priority", "media")
            rec = p.get("recommendation", "")
            lines.append(f"  · [{priority.upper()}] {title}: {rec}")

    return "\n".join(lines)


def _format_traceability_text(traceability: Dict[str, Any]) -> str:
    if not traceability:
        return "### Trazabilidad tecnica\nInformacion no disponible."

    lines = ["### Trazabilidad tecnica"]
    ts = traceability.get("timestamp_utc", "")
    doc_type = traceability.get("document_type", "")
    evidence_count = traceability.get("evidence_keywords_count", 0)
    rules_engine = traceability.get("rules_engine", "")
    models = traceability.get("models_executed", []) or []

    if ts:
        lines.append(f"- Timestamp UTC: {ts}")
    if doc_type:
        lines.append(f"- Tipo de documento clasificado: {doc_type}")
    if evidence_count:
        lines.append(f"- Palabras clave de evidencia detectadas: {evidence_count}")
    if rules_engine:
        lines.append(f"- Motor de reglas: {rules_engine}")
    if models:
        model_names = ", ".join(
            f"{m.get('name', 'n/a')} ({m.get('engine', 'n/a')})" for m in models
        )
        lines.append(f"- Modelos ejecutados: {model_names}")

    return "\n".join(lines)


def _fallback_result(payload: Dict[str, Any], warning: str, details: str) -> Dict[str, Any]:
    message = f"{warning} Returned local PRD fallback."
    return {
        "provider": "local-fallback",
        "prd_text": generate_prd_local(payload),
        "warning": warning,
        "details": details,
        "note": message,
    }


def _context_note_by_doc_type(doc_type: str) -> str:
    mapping = {
        "supplier_report": (
            "Prioriza continuidad operativa, dependencia de proveedores, retrasos, incidencias y acciones de mitigacion."
        ),
        "commercial_report": (
            "Prioriza embudo comercial, conversion, cancelaciones, absorcion y estrategia de cierre."
        ),
        "real_estate_generic": (
            "Prioriza lectura integral del activo: precio/renta esperada, riesgo, liquidez, cargas y potencial de inversion."
        ),
        "valuation_report": "Prioriza consistencia de valoracion, comparables y sensibilidad de supuestos.",
        "legal_report": "Prioriza riesgos legales, cargas, licencias y condicionantes de cierre.",
        "market_report": "Prioriza mercado, demanda, oferta, competencia y ventana de oportunidad.",
        "investment_report": "Prioriza rentabilidad, riesgo-retorno, liquidez y escenarios.",
    }
    return mapping.get(doc_type, "Prioriza decision accionable y trazable segun evidencia disponible.")


def _build_features_json(payload: Dict[str, Any]) -> Dict[str, Any]:
    re_out = (((payload.get("real_estate_models") or {}).get("output")) or {})
    fundamentals = payload.get("fundamentals", {}) or {}
    input_features = re_out.get("input_features", {})
    return {
        "input_features": input_features,
        "fundamentals": fundamentals,
        "summary": payload.get("summary", {}) or {},
    }


def _build_model_outputs_json(payload: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in ["segmentation", "behavior", "forecast", "commercial", "real_estate_models"]:
        value = payload.get(key)
        if value:
            out[key] = value
    return out


def _build_metadata(payload: Dict[str, Any]) -> Dict[str, Any]:
    trace = payload.get("traceability", {}) or {}
    models = trace.get("models_executed", []) or []
    model_versions = {
        m.get("name", "unknown"): {"engine": m.get("engine", "unknown"), "version": m.get("version", "unknown")}
        for m in models
    }
    normalized = payload.get("normalized", {}) or {}
    interpretation = normalized.get("interpretation", {}) if isinstance(normalized, dict) else {}
    extraction_confidence = interpretation.get("confidence")
    if extraction_confidence is None:
        extraction_confidence = normalized.get("confidence")
    return {
        "model_versions": model_versions,
        "dataset_version": payload.get("dataset_version", DEFAULT_DATASET_VERSION),
        "extraction_confidence": extraction_confidence if extraction_confidence is not None else "dato no disponible",
        "analysis_date": datetime.now(timezone.utc).isoformat(),
    }
