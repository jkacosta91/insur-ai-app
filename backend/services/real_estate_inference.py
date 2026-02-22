from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import joblib
import pandas as pd

from backend.models.real_estate_liquidity import predict_liquidity_days
from backend.models.real_estate_rent import predict_rent
from backend.models.real_estate_sale_price import predict_sale_price

ARTIFACTS_DIR = Path("artifacts")
SALE_MODEL_PATH = ARTIFACTS_DIR / "re_sale_price_model.joblib"
RENT_MODEL_PATH = ARTIFACTS_DIR / "re_rent_model.joblib"
INVEST_MODEL_PATH = ARTIFACTS_DIR / "re_investment_score_model.joblib"
LIQ_MODEL_PATH = ARTIFACTS_DIR / "re_liquidity_model.joblib"
DIAGNOSTICS_PATH = ARTIFACTS_DIR / "model_diagnostics.json"


class RealEstateModelRegistry:
    def __init__(self) -> None:
        self.sale_model = None
        self.rent_model = None
        self.invest_model = None
        self.liquidity_model = None
        self.diagnostics: Dict[str, Any] = {}
        self.load_errors: Dict[str, str] = {}
        self.refresh()

    def refresh(self) -> None:
        self.load_errors = {}
        self.sale_model = self._safe_load(SALE_MODEL_PATH, "sale")
        self.rent_model = self._safe_load(RENT_MODEL_PATH, "rent")
        self.invest_model = self._safe_load(INVEST_MODEL_PATH, "investment")
        self.liquidity_model = self._safe_load(LIQ_MODEL_PATH, "liquidity")
        self.diagnostics = self._load_diagnostics()

    def _safe_load(self, path: Path, key: str):
        if not path.exists():
            self.load_errors[key] = f"missing_file:{path.name}"
            return None
        try:
            return joblib.load(path)
        except Exception as exc:
            self.load_errors[key] = f"{type(exc).__name__}: {str(exc)[:240]}"
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
            "sale_model_loaded": self.sale_model is not None,
            "rent_model_loaded": self.rent_model is not None,
            "investment_model_loaded": self.invest_model is not None,
            "liquidity_model_loaded": self.liquidity_model is not None,
            "diagnostics_loaded": bool(self.diagnostics),
            "real_estate_model_load_errors": self.load_errors,
        }

    def missing_for_inference(self) -> List[str]:
        missing: List[str] = []
        if self.sale_model is None:
            missing.append("sale_model")
        if self.rent_model is None:
            missing.append("rent_model")
        if self.liquidity_model is None:
            missing.append("liquidity_model")
        return missing


re_model_registry = RealEstateModelRegistry()


FEATURES = [
    "sqm",
    "bedrooms",
    "floor",
    "has_terrace",
    "has_garage",
    "has_storage",
    "base_eur_m2",
    "sustainability_index",
    "complexity_index",
    "sale_price_eur_m2_city",
    "rent_price_eur_m2_month_city",
    "demand_index_city",
    "absorption_units_month",
    "inventory_index",
    "euribor_12m_pct",
    "inflation_yoy_pct",
    "city",
    "zone",
    "asset_type",
    "energy_rating",
]


def run_real_estate_inference(normalized: Dict[str, Any]) -> Dict[str, Any]:
    if re_model_registry.missing_for_inference():
        re_model_registry.refresh()

    row = _build_feature_row(normalized)
    doc_price = row.get("doc_price_eur")
    doc_rent = row.get("doc_rent_eur_month")

    sale_pred, rent_pred, liquidity_days, engine, fallback_reason = _predict_bundle(row)
    price_gap_pct = _gap_pct(doc_price, sale_pred)
    rent_gap_pct = _gap_pct(doc_rent, rent_pred)
    yield_pct = (rent_pred * 12.0 / max(sale_pred, 1.0)) * 100.0
    investment_score = round(min(100.0, max(0.0, (yield_pct / 8.0) * 100.0)), 2)

    diagnostics = re_model_registry.diagnostics if isinstance(re_model_registry.diagnostics, dict) else {}
    re_diags = (diagnostics.get("real_estate") or {}) if diagnostics else {}
    sale_std = _diag_metric(re_diags, "sale_price", "diagnostics", "residual_std")
    rent_std = _diag_metric(re_diags, "rent", "diagnostics", "residual_std")
    liq_std = _diag_metric(re_diags, "liquidity", "diagnostics", "residual_std")

    sale_interval = _interval(value=sale_pred, residual_std=sale_std, fallback_ratio=0.12, lower_bound=40_000.0)
    rent_interval = _interval(value=rent_pred, residual_std=rent_std, fallback_ratio=0.14, lower_bound=250.0)
    liq_interval = _interval(value=max(5.0, liquidity_days), residual_std=liq_std, fallback_ratio=0.18, lower_bound=5.0)

    scenarios = _scenario_analysis(row)
    drivers = _driver_contributions(row, sale_pred, investment_score, liquidity_days)
    confidence = _model_confidence(
        engine=engine,
        sale_width=sale_interval["width_pct"],
        rent_width=rent_interval["width_pct"],
        liq_width=liq_interval["width_pct"],
        has_doc_price=doc_price is not None,
        has_doc_rent=doc_rent is not None,
    )

    return {
        "engine": engine,
        "model_name": "real_estate_multi_model",
        "output": {
            "expected_sale_price_eur": round(sale_pred, 2),
            "expected_rent_eur_month": round(rent_pred, 2),
            "investment_score_0_100": investment_score,
            "liquidity_days_p50": round(max(5.0, liquidity_days), 1),
            "expected_gross_yield_pct": round(yield_pct, 3),
            "price_gap_pct_vs_document": round(price_gap_pct, 3) if price_gap_pct is not None else None,
            "rent_gap_pct_vs_document": round(rent_gap_pct, 3) if rent_gap_pct is not None else None,
            "prediction_intervals": {
                "sale_price_eur": sale_interval,
                "rent_eur_month": rent_interval,
                "liquidity_days": liq_interval,
            },
            "scenario_analysis": scenarios,
            "driver_analysis": drivers,
            "model_confidence_0_100": confidence,
            "diagnostics_reference": {
                "artifact": DIAGNOSTICS_PATH.name,
                "generated_at_utc": diagnostics.get("generated_at_utc"),
                "residual_std": {
                    "sale_price": sale_std,
                    "rent": rent_std,
                    "liquidity_days": liq_std,
                },
            },
            "inference_mode": "ml_models" if engine == "ml" else "rules_fallback",
            "fallback_reason": fallback_reason,
            "input_features": {k: row.get(k) for k in FEATURES},
        },
    }


def _build_feature_row(normalized: Dict[str, Any]) -> Dict[str, Any]:
    interpretation = normalized.get("interpretation", {}) or {}
    entities = interpretation.get("entities", {}) or {}
    metrics = interpretation.get("metrics", []) or []
    asset = entities.get("asset", {}) or {}
    financials = entities.get("financials", {}) or {}

    sqm = _coerce_float(asset.get("surface_m2"), 95.0)
    bedrooms = _coerce_float(asset.get("rooms"), 3.0)
    city = _extract_city(str(asset.get("location_text") or ""))
    energy = str(asset.get("energy_rating") or "C")
    asset_type = str(asset.get("asset_type") or "residencial")
    price_m2_ref = _metric_value(metrics, "price_m2_ref_eur") or 3300.0
    doc_price = _metric_value(metrics, "price_eur") or _coerce_float(financials.get("price_eur"), None)
    doc_rent = _metric_value(metrics, "rent_eur_month") or _coerce_float(financials.get("rent_eur_month"), None)
    if doc_price is None:
        doc_price = max(80_000.0, sqm * price_m2_ref)
    if doc_rent is None:
        doc_rent = max(500.0, doc_price * 0.048 / 12.0)

    floor = _coerce_float(asset.get("floor"), 3.0)
    has_terrace = float(bool(asset.get("has_terrace"))) if asset.get("has_terrace") is not None else 1.0
    has_garage = float(bool(asset.get("has_garage"))) if asset.get("has_garage") is not None else 1.0
    has_storage = float(bool(asset.get("has_storage"))) if asset.get("has_storage") is not None else 1.0
    sustainability_index = _coerce_float(asset.get("sustainability_index"), 0.58)
    complexity_index = _coerce_float(asset.get("complexity_index"), 0.44)

    market_ctx = entities.get("market") or {}
    macro_ctx = entities.get("macro") or {}
    demand_index_city = _coerce_float(market_ctx.get("demand_index"), 102.0)
    absorption_units_month = _coerce_float(market_ctx.get("absorption_units_month"), 8.5)
    inventory_index = _coerce_float(market_ctx.get("inventory_index"), 100.0)
    euribor_12m_pct = _coerce_float(macro_ctx.get("euribor_12m_pct"), 2.9)
    inflation_yoy_pct = _coerce_float(macro_ctx.get("inflation_yoy_pct"), 2.7)

    return {
        "sqm": sqm,
        "bedrooms": bedrooms,
        "floor": floor,
        "has_terrace": has_terrace,
        "has_garage": has_garage,
        "has_storage": has_storage,
        "base_eur_m2": price_m2_ref * 0.93,
        "sustainability_index": sustainability_index,
        "complexity_index": complexity_index,
        "sale_price_eur_m2_city": price_m2_ref,
        "rent_price_eur_m2_month_city": max(9.0, doc_rent / max(sqm, 1.0)),
        "demand_index_city": demand_index_city,
        "absorption_units_month": absorption_units_month,
        "inventory_index": inventory_index,
        "euribor_12m_pct": euribor_12m_pct,
        "inflation_yoy_pct": inflation_yoy_pct,
        "city": city,
        "zone": "general",
        "asset_type": asset_type,
        "energy_rating": energy,
        "doc_price_eur": doc_price,
        "doc_rent_eur_month": doc_rent,
    }


def _extract_city(location_text: str) -> str:
    text = location_text.lower()
    for city in ["madrid", "barcelona", "valencia", "sevilla", "malaga"]:
        if city in text:
            return city.title()
    return "Madrid"


def _metric_value(metrics: List[Dict[str, Any]], name: str) -> float | None:
    for m in metrics:
        if str(m.get("name")) == name:
            return _coerce_float(m.get("value"), None)
    return None


def _coerce_float(value: Any, default: float | None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _gap_pct(base: float | None, estimate: float) -> float | None:
    if base is None or base == 0:
        return None
    return (estimate - base) / base * 100.0


def _predict_bundle(row: Dict[str, Any]) -> tuple[float, float, float, str, str | None]:
    features = pd.DataFrame([row])[FEATURES]
    missing_models = re_model_registry.missing_for_inference()
    if not missing_models and all(
        m is not None
        for m in [
            re_model_registry.sale_model,
            re_model_registry.rent_model,
            re_model_registry.liquidity_model,
        ]
    ):
        sale_pred = float(re_model_registry.sale_model.predict(features)[0])
        rent_pred = float(re_model_registry.rent_model.predict(features)[0])
        liquidity_days = float(re_model_registry.liquidity_model.predict(features)[0])
        return sale_pred, rent_pred, liquidity_days, "ml", None

    sale_pred = predict_sale_price(row)
    rent_pred = predict_rent(row)
    liquidity_days = predict_liquidity_days(row)
    fallback_reason = (
        f"rules_fallback_due_to_missing_models:{','.join(missing_models)}"
        if missing_models
        else "rules_fallback"
    )
    return sale_pred, rent_pred, liquidity_days, "rules", fallback_reason


def _diag_metric(data: Dict[str, Any], section: str, subsection: str, key: str) -> float | None:
    try:
        raw = (((data.get(section) or {}).get(subsection) or {}).get(key))
        return float(raw) if raw is not None else None
    except Exception:
        return None


def _interval(value: float, residual_std: float | None, fallback_ratio: float, lower_bound: float) -> Dict[str, float]:
    z_80 = 1.28155
    if residual_std is not None and residual_std > 0:
        spread = residual_std * z_80
    else:
        spread = abs(value) * fallback_ratio

    p10 = max(lower_bound, value - spread)
    p90 = max(lower_bound, value + spread)
    width_pct = (p90 - p10) / max(abs(value), 1.0)
    return {
        "p10": round(float(p10), 2),
        "p50": round(float(value), 2),
        "p90": round(float(p90), 2),
        "width_pct": round(float(width_pct), 4),
    }


def _scenario_analysis(base_row: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    def _predict_scenario(row: Dict[str, Any]) -> Dict[str, float]:
        sale, rent, liquidity, _, _ = _predict_bundle(row)
        yield_pct = (rent * 12.0 / max(sale, 1.0)) * 100.0
        invest = min(100.0, max(0.0, (yield_pct / 8.0) * 100.0))
        return {
            "expected_sale_price_eur": round(float(sale), 2),
            "expected_rent_eur_month": round(float(rent), 2),
            "liquidity_days_p50": round(float(max(5.0, liquidity)), 1),
            "investment_score_0_100": round(float(invest), 2),
            "expected_gross_yield_pct": round(float(yield_pct), 3),
        }

    base = dict(base_row)

    conservative = dict(base_row)
    conservative["demand_index_city"] = max(60.0, _coerce_float(base_row.get("demand_index_city"), 100.0) - 8.0)
    conservative["euribor_12m_pct"] = _coerce_float(base_row.get("euribor_12m_pct"), 2.9) + 0.6
    conservative["inventory_index"] = _coerce_float(base_row.get("inventory_index"), 100.0) + 8.0

    aggressive = dict(base_row)
    aggressive["demand_index_city"] = _coerce_float(base_row.get("demand_index_city"), 100.0) + 8.0
    aggressive["euribor_12m_pct"] = max(0.1, _coerce_float(base_row.get("euribor_12m_pct"), 2.9) - 0.4)
    aggressive["inventory_index"] = max(10.0, _coerce_float(base_row.get("inventory_index"), 100.0) - 8.0)

    return {
        "conservative": _predict_scenario(conservative),
        "base": _predict_scenario(base),
        "aggressive": _predict_scenario(aggressive),
    }


def _driver_contributions(
    base_row: Dict[str, Any],
    base_sale: float,
    base_invest_score: float,
    base_liquidity: float,
) -> Dict[str, List[Dict[str, Any]]]:
    neutral_values = {
        "demand_index_city": 100.0,
        "euribor_12m_pct": 2.7,
        "inventory_index": 100.0,
        "absorption_units_month": 8.5,
        "complexity_index": 0.45,
        "sustainability_index": 0.55,
        "sale_price_eur_m2_city": 3300.0,
        "rent_price_eur_m2_month_city": 13.0,
    }
    labels = {
        "demand_index_city": "Demanda local",
        "euribor_12m_pct": "Euribor",
        "inventory_index": "Inventario local",
        "absorption_units_month": "Absorcion mensual",
        "complexity_index": "Complejidad del activo",
        "sustainability_index": "Indice de sostenibilidad",
        "sale_price_eur_m2_city": "Benchmark precio por m2",
        "rent_price_eur_m2_month_city": "Benchmark renta por m2",
    }

    sale_effects: List[Dict[str, Any]] = []
    invest_effects: List[Dict[str, Any]] = []
    liquidity_effects: List[Dict[str, Any]] = []

    for feature, neutral in neutral_values.items():
        row_cf = dict(base_row)
        row_cf[feature] = neutral
        sale_cf, rent_cf, liq_cf, _, _ = _predict_bundle(row_cf)
        yield_cf = (rent_cf * 12.0 / max(sale_cf, 1.0)) * 100.0
        invest_cf = min(100.0, max(0.0, (yield_cf / 8.0) * 100.0))

        sale_delta = base_sale - sale_cf
        invest_delta = base_invest_score - invest_cf
        liquidity_delta = liq_cf - base_liquidity

        sale_effects.append(
            {
                "feature": feature,
                "label": labels.get(feature, feature),
                "impact": round(float(sale_delta), 2),
                "direction": "up" if sale_delta >= 0 else "down",
            }
        )
        invest_effects.append(
            {
                "feature": feature,
                "label": labels.get(feature, feature),
                "impact": round(float(invest_delta), 2),
                "direction": "up" if invest_delta >= 0 else "down",
            }
        )
        liquidity_effects.append(
            {
                "feature": feature,
                "label": labels.get(feature, feature),
                "impact_days": round(float(liquidity_delta), 2),
                "direction": "up" if liquidity_delta >= 0 else "down",
            }
        )

    return {
        "sale_price_top_positive": _top_effects(sale_effects, key="impact", sign=1),
        "sale_price_top_negative": _top_effects(sale_effects, key="impact", sign=-1),
        "investment_top_positive": _top_effects(invest_effects, key="impact", sign=1),
        "investment_top_negative": _top_effects(invest_effects, key="impact", sign=-1),
        "liquidity_top_risk": _top_effects(liquidity_effects, key="impact_days", sign=1),
        "liquidity_top_support": _top_effects(liquidity_effects, key="impact_days", sign=-1),
    }


def _top_effects(rows: List[Dict[str, Any]], key: str, sign: int, n: int = 3) -> List[Dict[str, Any]]:
    if sign > 0:
        ordered = sorted(rows, key=lambda r: float(r.get(key, 0.0) or 0.0), reverse=True)
    else:
        ordered = sorted(rows, key=lambda r: float(r.get(key, 0.0) or 0.0))
    return ordered[:n]


def _model_confidence(
    engine: str,
    sale_width: float,
    rent_width: float,
    liq_width: float,
    has_doc_price: bool,
    has_doc_rent: bool,
) -> int:
    base = 0.78 if engine == "ml" else 0.42
    uncertainty_penalty = min(0.48, 0.45 * sale_width + 0.35 * rent_width + 0.20 * liq_width)
    evidence_bonus = 0.08 if (has_doc_price and has_doc_rent) else 0.03 if (has_doc_price or has_doc_rent) else 0.0
    score = (base - uncertainty_penalty + evidence_bonus) * 100.0
    return int(round(max(5.0, min(98.0, score))))
