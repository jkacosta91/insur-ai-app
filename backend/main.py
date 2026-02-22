from __future__ import annotations

import io
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from backend.schemas import DecisionsRequest, ForecastRequest, NormalizeRequest
from backend.services.benchmark import benchmark_suppliers
from backend.services.commercial_engine import analyze_commercial_report
from backend.services.decision_engine import generic_real_estate_decisions, supplier_decisions
from backend.services.document_agent import normalize_document
from backend.services.extractor import extract_pdf_text
from backend.services.insight_engine import build_fundamentals
from backend.services.ml_inference import (
    model_registry,
    run_behavior_inference,
    run_forecast_inference,
    run_segmentation_inference,
)
from backend.services.pipeline_orchestrator import (
    build_extraction_summary,
    build_pipeline_summary,
    build_traceability,
    empty_supplier_outputs,
    merge_decisions,
)
from backend.services.prd_generator import generate_prd_with_openai
try:
    from backend.services.prd_pdf import build_prd_pdf_bytes
    _HAS_PRD_PDF = True
except Exception:
    build_prd_pdf_bytes = None  # type: ignore[assignment]
    _HAS_PRD_PDF = False
from backend.services.real_estate_inference import re_model_registry, run_real_estate_inference
from backend.services.result_interpreter import build_result_interpretation
from backend.services.run_store import (
    attach_prd_to_run,
    get_document_pipeline,
    get_run,
    init_db,
    list_runs,
    save_document_upload,
    save_extraction,
    save_run,
    save_structured_doc,
)

load_dotenv()
try:
    import multipart  # type: ignore  # noqa: F401
    _HAS_MULTIPART = True
except Exception:
    _HAS_MULTIPART = False

app = FastAPI(title="INSUR AI Decision App", version="0.1.0")

UPLOADS_DIR = Path("uploads")
UPLOADS_DIR.mkdir(exist_ok=True)
init_db()
_MIN_TEXT_RAW = os.getenv("MIN_EXTRACT_CHARS", "180")
try:
    MIN_TEXT_CHARS_FOR_ANALYSIS = max(40, int(_MIN_TEXT_RAW))
except ValueError:
    MIN_TEXT_CHARS_FOR_ANALYSIS = 180

ML_PREDICT_API_TOKEN = os.getenv("ML_PREDICT_API_TOKEN", "CAMBIA_ESTO_POR_UN_SECRETO_LARGO")


class MLPredictRequest(BaseModel):
    session_id: Optional[str] = None
    report_type: str  # "clientes" | "operaciones"
    filename: Optional[str] = None
    rows: List[Dict[str, Any]]
    kpis: Optional[Dict[str, Any]] = None


class MLPredictResponse(BaseModel):
    status: str
    session_id: Optional[str] = None
    report_type: str
    model_version: str
    predictions: Any
    explanation: Dict[str, Any]


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "code": "unhandled_server_error",
            "message": str(exc),
            "error_type": type(exc).__name__,
            "path": str(request.url.path),
        },
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"message": "INSUR AI Decision App running", "health": "/health", "docs": "/docs"}


@app.get("/ml/status")
def ml_status():
    return {
        **model_registry.status(),
        **re_model_registry.status(),
    }


@app.post("/ml/benchmark")
def ml_benchmark(payload: NormalizeRequest):
    normalized = _resolve_normalized(payload)
    suppliers = normalized.get("suppliers", [])
    if not suppliers:
        return {"available": False, "reason": "No suppliers found in payload"}
    return benchmark_suppliers(suppliers)


@app.post("/ml/predict", response_model=MLPredictResponse)
def ml_predict(req: MLPredictRequest, x_api_key: Optional[str] = Header(default=None)):
    # Auth simple para llamadas externas (n8n / integraciones).
    if x_api_key != ML_PREDICT_API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    report_type = (req.report_type or "").strip().lower()
    if report_type not in ("clientes", "operaciones"):
        raise HTTPException(status_code=400, detail="report_type no soportado")

    if not req.rows:
        raise HTTPException(status_code=400, detail="rows vacío")

    df = pd.DataFrame(req.rows)
    if df.empty:
        raise HTTPException(status_code=400, detail="rows vacío")

    if report_type == "clientes":
        if "id_cliente" not in df.columns:
            df["id_cliente"] = [f"cli_{idx + 1}" for idx in range(len(df))]

        def churn_score(r: pd.Series) -> float:
            s = 0.0
            estado = str(r.get("estado_cliente", "")).lower()
            rating = str(r.get("rating_riesgo", "")).upper()
            fin = float(r.get("financiacion_pct", 0) or 0)
            ops = float(r.get("operaciones", 0) or 0)
            if estado == "inactivo":
                s += 0.6
            if rating == "D":
                s += 0.25
            s += min(fin / 200.0, 0.2)
            s += 0.1 if ops <= 1 else 0.0
            return float(min(max(s, 0.0), 0.99))

        df["churn_score"] = df.apply(churn_score, axis=1)
        preds = df[["id_cliente", "churn_score"]].to_dict(orient="records")
        explanation = {
            "target": "churn_score",
            "top_drivers": ["estado_cliente", "rating_riesgo", "financiacion_pct", "operaciones"],
            "note": "Ejemplo baseline. Reemplazar por tu modelo entrenado.",
        }
    else:
        if "id_operacion" not in df.columns:
            df["id_operacion"] = [f"op_{idx + 1}" for idx in range(len(df))]

        eurm2 = pd.to_numeric(
            df.get("precio_eur_m2", pd.Series([0.0] * len(df))),
            errors="coerce",
        ).fillna(0.0)
        mean_val = float(eurm2[eurm2 > 0].mean()) if (eurm2 > 0).any() else 0.0
        df["pred_precio_eur_m2"] = eurm2.where(eurm2 > 0, mean_val)
        preds = df[["id_operacion", "pred_precio_eur_m2"]].to_dict(orient="records")
        explanation = {
            "target": "pred_precio_eur_m2",
            "top_drivers": ["region", "segmento", "superficie_m2", "margen_pct"],
            "note": "Ejemplo baseline. Reemplazar por tu modelo entrenado.",
        }

    return MLPredictResponse(
        status="success",
        session_id=req.session_id,
        report_type=report_type,
        model_version="0.1.0",
        predictions=preds,
        explanation=explanation,
    )


@app.get("/runs")
def runs(limit: int = Query(default=25, ge=1, le=200)):
    return {"items": list_runs(limit=limit)}


@app.get("/runs/{run_id}")
def run_detail(run_id: str):
    item = get_run(run_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"run_id not found: {run_id}")
    return item


@app.get("/documents/{document_id}")
def document_detail(document_id: str):
    item = get_document_pipeline(document_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"document_id not found: {document_id}")
    return item


def _resolve_normalized(payload: NormalizeRequest | ForecastRequest) -> dict:
    if payload.suppliers:
        indicators = payload.global_indicators or {}
        if payload.macro_pressure is not None:
            indicators["macro_pressure"] = payload.macro_pressure
        if payload.demand_pressure is not None:
            indicators["demand_pressure"] = payload.demand_pressure

        return {
            "document_type": payload.document_type or "supplier_report",
            "suppliers": [s.model_dump() for s in payload.suppliers],
            "global_indicators": indicators,
        }

    full_text = payload.full_text or (payload.extraction.full_text if payload.extraction else "")
    return normalize_document(full_text)


def _payload_text(payload: NormalizeRequest | ForecastRequest) -> str:
    return (payload.full_text or (payload.extraction.full_text if payload.extraction else "") or "").strip()


def _validate_text_quality(payload: NormalizeRequest | ForecastRequest, endpoint: str) -> None:
    if payload.suppliers:
        return
    text = _payload_text(payload)
    char_count = (
        int(payload.extraction.char_count)
        if getattr(payload, "extraction", None) and payload.extraction.char_count is not None
        else len(text)
    )
    if char_count >= MIN_TEXT_CHARS_FOR_ANALYSIS:
        return
    raise HTTPException(
        status_code=422,
        detail={
            "code": "insufficient_extraction_quality",
            "message": "El PDF no contiene suficiente texto extraido para ejecutar analisis confiable.",
            "details": {
                "endpoint": endpoint,
                "char_count": char_count,
                "min_required": MIN_TEXT_CHARS_FOR_ANALYSIS,
                "action": "Usa PDF con texto seleccionable o habilita OCR (OPENAI_API_KEY + pypdfium2).",
            },
        },
    )


def _unsupported_doc_error(endpoint: str, document_type: str | None) -> dict:
    return {
        "code": "unsupported_document_type",
        "message": f"document_type not supported in {endpoint}",
        "details": {
            "document_type": document_type,
            "supported": ["supplier_report", "commercial_report", "real_estate_generic"],
        },
    }


def _model_response(result: dict) -> dict:
    return {
        "model": result["model_name"],
        "engine": result["engine"],
        "output": result["output"],
    }


if _HAS_MULTIPART:
    @app.post("/extract")
    async def extract(file: UploadFile = File(...)):
        if file.content_type not in ["application/pdf"]:
            return {
                "code": "invalid_file_type",
                "message": "Only PDF files are supported",
                "details": {"received_content_type": file.content_type},
            }

        document_id = str(uuid.uuid4())
        out_path = UPLOADS_DIR / f"{document_id}.pdf"

        contents = await file.read()
        out_path.write_bytes(contents)

        extracted = extract_pdf_text(str(out_path))
        detected: dict = {}
        try:
            detected = normalize_document(extracted.get("full_text", ""))
        except Exception:
            pass
        quality = {
            "usable_for_analysis": bool(extracted.get("usable_for_analysis")),
            "quality_status": extracted.get("quality_status", "unknown"),
            "char_count": int(extracted.get("char_count", 0) or 0),
            "min_chars_required": int(extracted.get("min_chars_required", MIN_TEXT_CHARS_FOR_ANALYSIS) or MIN_TEXT_CHARS_FOR_ANALYSIS),
        }

        try:
            save_document_upload(
                document_id=document_id,
                filename=file.filename,
                content_type=file.content_type,
                file_uri=str(out_path),
            )
            save_extraction(
                document_id=document_id,
                extraction={**extracted, "detected": detected},
            )
        except Exception:
            pass

        return {
            "document_id": document_id,
            "filename": file.filename,
            "extraction": {**extracted, "detected": detected},
            "quality": quality,
            "warnings": (
                []
                if quality["usable_for_analysis"]
                else [
                    {
                        "code": "insufficient_extraction_quality",
                        "message": "Extraccion de texto insuficiente para analisis robusto.",
                    }
                ]
            ),
        }
else:
    @app.post("/extract")
    async def extract():
        raise HTTPException(
            status_code=503,
            detail="python-multipart is required for /extract. Install dependencies from requirements.txt.",
        )


@app.post("/normalize")
def normalize(payload: NormalizeRequest):
    return _resolve_normalized(payload)


@app.post("/ml/run")
def ml_run(payload: NormalizeRequest):
    _validate_text_quality(payload, endpoint="/ml/run")
    normalized = _resolve_normalized(payload)
    if normalized.get("document_type") == "supplier_report":
        result = run_segmentation_inference(
            normalized["suppliers"],
            global_indicators=normalized.get("global_indicators", {}),
        )
        return _model_response(result)
    return _unsupported_doc_error("ml_run", normalized.get("document_type"))


@app.post("/ml/behavior")
def ml_behavior(payload: NormalizeRequest):
    _validate_text_quality(payload, endpoint="/ml/behavior")
    normalized = _resolve_normalized(payload)
    if normalized.get("document_type") == "supplier_report":
        result = run_behavior_inference(
            normalized["suppliers"],
            global_indicators=normalized.get("global_indicators", {}),
        )
        return _model_response(result)
    return _unsupported_doc_error("ml_behavior", normalized.get("document_type"))


@app.post("/ml/forecast")
def ml_forecast(payload: ForecastRequest):
    _validate_text_quality(payload, endpoint="/ml/forecast")
    normalized = _resolve_normalized(payload)
    if normalized.get("document_type") == "supplier_report":
        result = run_forecast_inference(
            normalized["suppliers"],
            horizon_days=payload.horizon_days,
            global_indicators=normalized.get("global_indicators", {}),
        )
        return _model_response(result)
    return _unsupported_doc_error("ml_forecast", normalized.get("document_type"))


@app.post("/ml/full")
def ml_full(payload: ForecastRequest):
    _validate_text_quality(payload, endpoint="/ml/full")
    normalized = _resolve_normalized(payload)
    document_id = payload.document_id
    doc_type = normalized.get("document_type")
    horizon_days = payload.horizon_days

    if document_id:
        try:
            save_structured_doc(document_id=document_id, normalized=normalized)
        except Exception:
            pass

    if doc_type == "supplier_report":
        segmentation_result = run_segmentation_inference(
            normalized["suppliers"],
            global_indicators=normalized.get("global_indicators", {}),
        )
        behavior_result = run_behavior_inference(
            normalized["suppliers"],
            global_indicators=normalized.get("global_indicators", {}),
        )
        forecast_result = run_forecast_inference(
            normalized["suppliers"],
            horizon_days=horizon_days,
            global_indicators=normalized.get("global_indicators", {}),
        )
        segmentation_output = _model_response(segmentation_result)
        behavior_output = _model_response(behavior_result)
        forecast_output = _model_response(forecast_result)
        decisions_output = supplier_decisions(
            normalized=normalized,
            model_output=segmentation_output,
            behavior_output=behavior_output,
            forecast_output=forecast_output,
        )
        try:
            benchmark_output = benchmark_suppliers(normalized.get("suppliers", []))
        except Exception as exc:
            benchmark_output = {"available": False, "reason": f"benchmark_failed:{type(exc).__name__}"}
        summary_payload = build_pipeline_summary(
            normalized=normalized,
            decisions=decisions_output,
            segmentation=segmentation_output,
            behavior=behavior_output,
            forecast=forecast_output,
        )

        result_payload = {
            "normalized": normalized,
            "segmentation": segmentation_output,
            "behavior": behavior_output,
            "forecast": forecast_output,
            "decisions": decisions_output,
            "benchmark": benchmark_output,
            "extraction_summary": build_extraction_summary(payload),
            "summary": summary_payload,
            "traceability": build_traceability(
                normalized=normalized,
                segmentation=segmentation_output,
                behavior=behavior_output,
                forecast=forecast_output,
            ),
            "fundamentals": build_fundamentals(
                normalized=normalized,
                segmentation_output=segmentation_output,
                behavior_output=behavior_output,
                forecast_output=forecast_output,
            ),
            "result_interpretation": build_result_interpretation(
                normalized=normalized,
                decisions=decisions_output,
                summary=summary_payload,
                segmentation=segmentation_output,
                behavior=behavior_output,
                forecast=forecast_output,
            ),
        }
        return _persist_run(payload, result_payload)

    if doc_type == "commercial_report":
        commercial = analyze_commercial_report(normalized)
        real_estate_output = _model_response(run_real_estate_inference(normalized))
        re_decisions = generic_real_estate_decisions(
            normalized=normalized,
            real_estate_output=real_estate_output,
        )
        merged_decisions = merge_decisions(commercial["decisions"], re_decisions)
        empty = empty_supplier_outputs(horizon_days)
        summary_payload = build_pipeline_summary(
            normalized=normalized,
            decisions=merged_decisions,
            commercial=commercial["analysis"],
            real_estate=real_estate_output,
        )

        result_payload = {
            "normalized": normalized,
            "segmentation": empty["segmentation"],
            "behavior": empty["behavior"],
            "forecast": empty["forecast"],
            "commercial": commercial["analysis"],
            "real_estate_models": real_estate_output,
            "decisions": merged_decisions,
            "benchmark": {"available": False, "reason": "benchmark_only_for_supplier_report"},
            "extraction_summary": build_extraction_summary(payload),
            "summary": summary_payload,
            "traceability": build_traceability(
                normalized=normalized,
                segmentation=empty["segmentation"],
                behavior=empty["behavior"],
                forecast=empty["forecast"],
                commercial=commercial["analysis"],
                real_estate=real_estate_output,
            ),
            "fundamentals": build_fundamentals(
                normalized=normalized,
                commercial_output=commercial["analysis"],
            ),
            "result_interpretation": build_result_interpretation(
                normalized=normalized,
                decisions=merged_decisions,
                summary=summary_payload,
                commercial=commercial["analysis"],
                real_estate_models=real_estate_output,
            ),
        }
        return _persist_run(payload, result_payload)

    if doc_type == "real_estate_generic":
        real_estate_output = _model_response(run_real_estate_inference(normalized))
        decisions_output = generic_real_estate_decisions(
            normalized=normalized,
            real_estate_output=real_estate_output,
        )
        empty = empty_supplier_outputs(horizon_days)
        summary_payload = build_pipeline_summary(
            normalized=normalized,
            decisions=decisions_output,
            real_estate=real_estate_output,
        )
        result_payload = {
            "normalized": normalized,
            "segmentation": empty["segmentation"],
            "behavior": empty["behavior"],
            "forecast": empty["forecast"],
            "real_estate_models": real_estate_output,
            "decisions": decisions_output,
            "benchmark": {"available": False, "reason": "benchmark_only_for_supplier_report"},
            "extraction_summary": build_extraction_summary(payload),
            "summary": summary_payload,
            "traceability": build_traceability(
                normalized=normalized,
                segmentation=empty["segmentation"],
                behavior=empty["behavior"],
                forecast=empty["forecast"],
                real_estate=real_estate_output,
            ),
            "fundamentals": build_fundamentals(normalized=normalized),
            "result_interpretation": build_result_interpretation(
                normalized=normalized,
                decisions=decisions_output,
                summary=summary_payload,
                real_estate_models=real_estate_output,
            ),
        }
        return _persist_run(payload, result_payload)

    return _unsupported_doc_error("ml_full", doc_type)


def _persist_run(payload: ForecastRequest, result_payload: dict) -> dict:
    run_id = None
    run_store_error = None
    try:
        run_id = save_run(payload=payload.model_dump(), result=result_payload)
    except Exception as exc:
        run_store_error = f"{type(exc).__name__}: {exc}"
    response = {**result_payload, "run_id": run_id, "document_id": payload.document_id}
    if run_store_error:
        response["warnings"] = {"run_store": run_store_error}
    return response


@app.post("/decisions")
def decisions(payload: DecisionsRequest):
    normalized = payload.normalized
    if normalized.get("document_type") == "supplier_report":
        return supplier_decisions(
            normalized=normalized,
            model_output=payload.model_output,
            behavior_output=payload.behavior_output,
            forecast_output=payload.forecast_output,
        )
    return _unsupported_doc_error("decisions", normalized.get("document_type"))


@app.post("/generate-prd")
def generate_prd(payload: dict):
    result = generate_prd_with_openai(payload)
    run_id = payload.get("run_id")
    if run_id:
        try:
            attached = attach_prd_to_run(run_id=run_id, prd_result=result)
            result["run_attached"] = attached
        except Exception as exc:
            result["run_attached"] = False
            result["run_attach_warning"] = f"{type(exc).__name__}: {exc}"
    return result


@app.post("/generate-prd/pdf")
def generate_prd_pdf(payload: dict):
    if not _HAS_PRD_PDF or build_prd_pdf_bytes is None:
        raise HTTPException(
            status_code=503,
            detail="PDF generation unavailable: missing optional dependency 'reportlab'.",
        )

    prd_text = (payload.get("prd_text") or "").strip()
    provider = payload.get("provider", "openai")

    if not prd_text:
        result = generate_prd_with_openai(payload)
        prd_text = (result.get("prd_text") or "").strip()
        provider = result.get("provider", provider)

    if not prd_text:
        raise HTTPException(status_code=422, detail="No PRD text available to render PDF.")

    doc_name = str(payload.get("document_name") or payload.get("doc_name") or "PRD_Analisis_Inmobiliario")
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", doc_name).strip("_") or "PRD_Analisis_Inmobiliario"
    pdf_bytes = build_prd_pdf_bytes(prd_text=prd_text, document_name=safe_name, provider=provider)

    headers = {"Content-Disposition": f'attachment; filename="{safe_name}.pdf"'}
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf", headers=headers)
