from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import joblib
import pandas as pd

from backend.models.supplier_behavior import analyze_supplier_behavior
from backend.models.supplier_forecast import forecast_supplier_risk
from backend.models.supplier_segmentation import segment_suppliers

ARTIFACTS_DIR = Path("artifacts")
SEG_MODEL_PATH = ARTIFACTS_DIR / "segmentation_model.joblib"
BEH_MODEL_PATH = ARTIFACTS_DIR / "behavior_model.joblib"
FOR_MODEL_PATH = ARTIFACTS_DIR / "forecast_model.joblib"
DIAGNOSTICS_PATH = ARTIFACTS_DIR / "model_diagnostics.json"

TIER_RANK = {"HIGH": 3, "MED": 2, "LOW": 1}


class ModelRegistry:
    def __init__(self) -> None:
        self.segmentation_model = None
        self.behavior_model = None
        self.forecast_model = None
        self.diagnostics: Dict[str, Any] = {}
        self.load_errors: Dict[str, str] = {}
        self.refresh()

    def refresh(self) -> None:
        self.load_errors = {}
        self.segmentation_model = self._safe_load(SEG_MODEL_PATH)
        self.behavior_model = self._safe_load(BEH_MODEL_PATH)
        self.forecast_model = self._safe_load(FOR_MODEL_PATH)
        self.diagnostics = self._load_diagnostics()

    def _safe_load(self, path: Path):
        if not path.exists():
            return None
        try:
            return joblib.load(path)
        except Exception:
            return None

    def _load_diagnostics(self) -> Dict[str, Any]:
        if not DIAGNOSTICS_PATH.exists():
            return {}
        try:
            return json.loads(DIAGNOSTICS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def status(self) -> Dict[str, Any]:
        return {
            "artifacts_dir": str(ARTIFACTS_DIR.resolve()),
            "segmentation_loaded": self.segmentation_model is not None,
            "behavior_loaded": self.behavior_model is not None,
            "forecast_loaded": self.forecast_model is not None,
            "diagnostics_loaded": bool(self.diagnostics),
        }


model_registry = ModelRegistry()


def run_segmentation_inference(
    suppliers: List[Dict[str, Any]],
    global_indicators: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    if model_registry.segmentation_model is None:
        model_registry.refresh()

    if not suppliers:
        return {
            "engine": "rules" if model_registry.segmentation_model is None else "ml",
            "model_name": "segmentation_suppliers" if model_registry.segmentation_model is None else "segmentation_suppliers_ml",
            "output": {
                "suppliers_segmented": [],
                "summary": {
                    "total_suppliers": 0,
                    "high_risk": 0,
                    "med_risk": 0,
                    "low_risk": 0,
                },
            },
        }

    if model_registry.segmentation_model is None:
        return {
            "engine": "rules",
            "model_name": "segmentation_suppliers",
            "output": segment_suppliers(suppliers),
        }

    features = _build_features_frame(suppliers, global_indicators or {})
    try:
        preds = model_registry.segmentation_model.predict(features)
        probs = model_registry.segmentation_model.predict_proba(features)
        classes = list(model_registry.segmentation_model.classes_)
    except Exception as exc:
        return {
            "engine": "rules",
            "model_name": "segmentation_suppliers",
            "output": {
                **segment_suppliers(suppliers),
                "fallback_reason": f"ml_inference_failed:{type(exc).__name__}",
            },
        }

    rows: List[Dict[str, Any]] = []
    for idx, s in enumerate(suppliers):
        pred = str(preds[idx])
        proba_map = {str(classes[j]): float(probs[idx][j]) for j in range(len(classes))}
        conf = round(max(proba_map.values()), 4)

        # Keep an interpretable score comparable to the rules version.
        dep = s.get("dependency_pct") or 0
        inc = s.get("incidents") or 0
        delay = s.get("avg_delay_days") or 0
        margin = s.get("estimated_margin_pct") or 0
        risk_score = 0.45 * dep + 3.0 * inc + 1.5 * delay - 1.0 * margin

        rows.append(
            {
                **s,
                "risk_score": round(float(risk_score), 2),
                "risk_tier": pred,
                "risk_tier_confidence": conf,
                "risk_tier_uncertainty": (
                    "high" if conf < 0.52 else "medium" if conf < 0.68 else "low"
                ),
                "risk_tier_proba": {k: round(v, 4) for k, v in proba_map.items()},
                "top_risk_drivers": _risk_driver_breakdown(s),
            }
        )

    rows.sort(key=lambda x: (TIER_RANK.get(x["risk_tier"], 0), x["risk_score"]), reverse=True)
    avg_conf = (sum(float(x.get("risk_tier_confidence", 0.0)) for x in rows) / len(rows)) if rows else 0.0

    return {
        "engine": "ml",
        "model_name": "segmentation_suppliers_ml",
        "output": {
            "suppliers_segmented": rows,
            "summary": {
                "total_suppliers": len(rows),
                "high_risk": sum(1 for x in rows if x["risk_tier"] == "HIGH"),
                "med_risk": sum(1 for x in rows if x["risk_tier"] == "MED"),
                "low_risk": sum(1 for x in rows if x["risk_tier"] == "LOW"),
                "avg_confidence": round(float(avg_conf), 4),
                "low_confidence_count": sum(1 for x in rows if float(x["risk_tier_confidence"]) < 0.52),
            },
        },
    }


def run_behavior_inference(
    suppliers: List[Dict[str, Any]],
    global_indicators: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    if model_registry.behavior_model is None:
        model_registry.refresh()

    if not suppliers:
        return {
            "engine": "rules" if model_registry.behavior_model is None else "ml",
            "model_name": "behavior_suppliers" if model_registry.behavior_model is None else "behavior_suppliers_ml",
            "output": {
                "supplier_behavior": [],
                "summary": {
                    "total_suppliers": 0,
                    "stable": 0,
                    "warning": 0,
                    "critical": 0,
                    "avg_reliability_index": 0,
                },
            },
        }

    if model_registry.behavior_model is None:
        return {
            "engine": "rules",
            "model_name": "behavior_suppliers",
            "output": analyze_supplier_behavior(suppliers),
        }

    features = _build_features_frame(suppliers, global_indicators or {})
    try:
        preds = model_registry.behavior_model.predict(features)
        probs = model_registry.behavior_model.predict_proba(features)
        classes = list(model_registry.behavior_model.classes_)
    except Exception as exc:
        return {
            "engine": "rules",
            "model_name": "behavior_suppliers",
            "output": {
                **analyze_supplier_behavior(suppliers),
                "fallback_reason": f"ml_inference_failed:{type(exc).__name__}",
            },
        }

    rows: List[Dict[str, Any]] = []
    for idx, s in enumerate(suppliers):
        pred = str(preds[idx])
        proba_map = {str(classes[j]): float(probs[idx][j]) for j in range(len(classes))}
        conf = round(max(proba_map.values()), 4)

        dep = s.get("dependency_pct") or 0
        inc = s.get("incidents") or 0
        delay = s.get("avg_delay_days") or 0
        margin = s.get("estimated_margin_pct") or 0
        orders = s.get("orders") or 0
        reliability_index = _clamp(
            100 - (4.0 * inc + 2.0 * delay + 0.45 * dep + 0.03 * orders - 0.35 * margin),
            0,
            100,
        )

        rows.append(
            {
                **s,
                "reliability_index": round(float(reliability_index), 2),
                "behavior_state": pred,
                "behavior_confidence": conf,
                "behavior_uncertainty": (
                    "high" if conf < 0.52 else "medium" if conf < 0.68 else "low"
                ),
                "behavior_proba": {k: round(v, 4) for k, v in proba_map.items()},
                "top_risk_drivers": _risk_driver_breakdown(s),
            }
        )

    rows.sort(key=lambda x: x["reliability_index"])
    avg_conf = (sum(float(x.get("behavior_confidence", 0.0)) for x in rows) / len(rows)) if rows else 0.0

    return {
        "engine": "ml",
        "model_name": "behavior_suppliers_ml",
        "output": {
            "supplier_behavior": rows,
            "summary": {
                "total_suppliers": len(rows),
                "stable": sum(1 for x in rows if x["behavior_state"] == "stable"),
                "warning": sum(1 for x in rows if x["behavior_state"] == "warning"),
                "critical": sum(1 for x in rows if x["behavior_state"] == "critical"),
                "avg_reliability_index": round(
                    sum(x["reliability_index"] for x in rows) / len(rows), 2
                )
                if rows
                else 0,
                "avg_confidence": round(float(avg_conf), 4),
                "low_confidence_count": sum(1 for x in rows if float(x["behavior_confidence"]) < 0.52),
            },
        },
    }


def run_forecast_inference(
    suppliers: List[Dict[str, Any]],
    horizon_days: int = 90,
    global_indicators: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    if model_registry.forecast_model is None:
        model_registry.refresh()

    horizon_days = max(30, min(180, int(horizon_days or 90)))
    if not suppliers:
        return {
            "engine": "rules" if model_registry.forecast_model is None else "ml",
            "model_name": "forecast_suppliers" if model_registry.forecast_model is None else "forecast_suppliers_ml",
            "output": {
                "supplier_forecast": [],
                "summary": {
                    "horizon_days": horizon_days,
                    "total_suppliers": 0,
                    "high_risk_forecast": 0,
                    "med_risk_forecast": 0,
                    "low_risk_forecast": 0,
                },
            },
        }

    if model_registry.forecast_model is None:
        return {
            "engine": "rules",
            "model_name": "forecast_suppliers",
            "output": forecast_supplier_risk(suppliers, horizon_days=horizon_days),
        }

    features = _build_features_frame(suppliers, global_indicators or {})
    try:
        pred_90 = model_registry.forecast_model.predict(features)
    except Exception as exc:
        return {
            "engine": "rules",
            "model_name": "forecast_suppliers",
            "output": {
                **forecast_supplier_risk(suppliers, horizon_days=horizon_days),
                "fallback_reason": f"ml_inference_failed:{type(exc).__name__}",
            },
        }
    horizon_factor = horizon_days / 90.0
    residual_std = _forecast_residual_std()

    rows: List[Dict[str, Any]] = []
    for idx, s in enumerate(suppliers):
        forecast_score = _clamp(float(pred_90[idx]) * horizon_factor, 0, 180)
        risk_level = "LOW"
        if forecast_score >= 120:
            risk_level = "HIGH"
        elif forecast_score >= 75:
            risk_level = "MED"

        dep = s.get("dependency_pct") or 0
        inc = s.get("incidents") or 0
        delay = s.get("avg_delay_days") or 0
        expected_incidents = round(inc * (1 + 0.04 * (horizon_days / 30.0) + dep / 400), 2)
        expected_delay_days = round(delay * (1 + 0.06 * (horizon_days / 30.0) + inc / 80), 2)
        interval = _forecast_interval(score=forecast_score, residual_std=residual_std)

        rows.append(
            {
                **s,
                "forecast_horizon_days": horizon_days,
                "forecast_risk_score": round(float(forecast_score), 2),
                "forecast_risk_level": risk_level,
                "forecast_risk_interval": interval,
                "forecast_confidence_0_100": interval["confidence_0_100"],
                "expected_incidents": expected_incidents,
                "expected_avg_delay_days": expected_delay_days,
                "top_risk_drivers": _risk_driver_breakdown(s),
            }
        )

    rows.sort(key=lambda x: x["forecast_risk_score"], reverse=True)
    avg_conf = (
        sum(float(x.get("forecast_confidence_0_100", 0.0)) for x in rows) / len(rows)
        if rows
        else 0.0
    )

    return {
        "engine": "ml",
        "model_name": "forecast_suppliers_ml",
        "output": {
            "supplier_forecast": rows,
            "summary": {
                "horizon_days": horizon_days,
                "total_suppliers": len(rows),
                "high_risk_forecast": sum(1 for x in rows if x["forecast_risk_level"] == "HIGH"),
                "med_risk_forecast": sum(1 for x in rows if x["forecast_risk_level"] == "MED"),
                "low_risk_forecast": sum(1 for x in rows if x["forecast_risk_level"] == "LOW"),
                "avg_confidence_0_100": round(float(avg_conf), 2),
                "model_residual_std": round(float(residual_std), 4) if residual_std is not None else None,
            },
        },
    }


def _build_features_frame(
    suppliers: List[Dict[str, Any]],
    global_indicators: Dict[str, Any],
) -> pd.DataFrame:
    macro_pressure = _coerce_float(global_indicators.get("macro_pressure"), 1.0)
    demand_pressure = _coerce_float(global_indicators.get("demand_pressure"), 1.0)

    rows = []
    for s in suppliers:
        rows.append(
            {
                "category": str(s.get("category") or "unknown"),
                "annual_volume_eur": _coerce_float(s.get("annual_volume_eur"), 0.0),
                "orders": _coerce_float(s.get("orders"), 0.0),
                "incidents": _coerce_float(s.get("incidents"), 0.0),
                "avg_delay_days": _coerce_float(s.get("avg_delay_days"), 0.0),
                "dependency_pct": _coerce_float(s.get("dependency_pct"), 0.0),
                "estimated_margin_pct": _coerce_float(s.get("estimated_margin_pct"), 0.0),
                "macro_pressure": macro_pressure,
                "demand_pressure": demand_pressure,
            }
        )

    return pd.DataFrame(rows)


def _forecast_residual_std() -> float | None:
    diags = model_registry.diagnostics if isinstance(model_registry.diagnostics, dict) else {}
    suppliers = (diags.get("suppliers") or {}) if diags else {}
    try:
        value = (((suppliers.get("forecast") or {}).get("diagnostics") or {}).get("residual_std"))
        return float(value) if value is not None else None
    except Exception:
        return None


def _forecast_interval(score: float, residual_std: float | None) -> Dict[str, float]:
    z_80 = 1.28155  # P10/P90
    spread = (residual_std * z_80) if (residual_std is not None and residual_std > 0) else max(8.0, score * 0.14)
    p10 = _clamp(score - spread, 0, 180)
    p90 = _clamp(score + spread, 0, 180)
    width_pct = (p90 - p10) / max(abs(score), 1.0)
    confidence = int(round(max(5.0, min(98.0, (1.0 - min(1.0, width_pct)) * 100.0))))
    return {
        "p10": round(float(p10), 2),
        "p50": round(float(score), 2),
        "p90": round(float(p90), 2),
        "width_pct": round(float(width_pct), 4),
        "confidence_0_100": confidence,
    }


def _risk_driver_breakdown(supplier: Dict[str, Any]) -> List[Dict[str, Any]]:
    dep = _coerce_float(supplier.get("dependency_pct"), 0.0)
    inc = _coerce_float(supplier.get("incidents"), 0.0)
    delay = _coerce_float(supplier.get("avg_delay_days"), 0.0)
    margin = _coerce_float(supplier.get("estimated_margin_pct"), 0.0)
    volume = _coerce_float(supplier.get("annual_volume_eur"), 0.0)

    drivers = [
        {"driver": "Dependencia", "score": max(0.0, dep * 0.45), "value": dep, "unit": "%"},
        {"driver": "Incidencias", "score": max(0.0, inc * 3.0), "value": inc, "unit": "eventos"},
        {"driver": "Retraso medio", "score": max(0.0, delay * 1.5), "value": delay, "unit": "dias"},
        {"driver": "Margen estimado", "score": max(0.0, -margin * 1.0), "value": margin, "unit": "%"},
        {"driver": "Volumen anual", "score": max(0.0, min(15.0, volume / 120_000.0)), "value": volume, "unit": "EUR"},
    ]
    ranked = sorted(drivers, key=lambda x: float(x["score"]), reverse=True)
    total = sum(float(x["score"]) for x in ranked) or 1.0
    out: List[Dict[str, Any]] = []
    for item in ranked[:3]:
        out.append(
            {
                "driver": item["driver"],
                "weight_pct": round((float(item["score"]) / total) * 100.0, 2),
                "raw_value": round(float(item["value"]), 2),
                "unit": item["unit"],
            }
        )
    return out


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, min_v: float, max_v: float) -> float:
    return max(min_v, min(max_v, value))
