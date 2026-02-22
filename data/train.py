from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import (
    HistGradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.metrics import accuracy_score, f1_score, mean_absolute_error, r2_score
from sklearn.model_selection import KFold, StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


SUPPLIER_FEATURES = [
    "category",
    "annual_volume_eur",
    "orders",
    "incidents",
    "avg_delay_days",
    "dependency_pct",
    "estimated_margin_pct",
    "macro_pressure",
    "demand_pressure",
]

REAL_ESTATE_FEATURES = [
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


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _base_feature_name(encoded_feature: str) -> str:
    if "__" in encoded_feature:
        prefix, raw = encoded_feature.split("__", 1)
    else:
        prefix, raw = "", encoded_feature
    if prefix == "cat":
        return raw.split("_", 1)[0]
    return raw


def _feature_importance_summary(pipeline: Pipeline, top_n: int = 12) -> list[dict[str, Any]]:
    model = pipeline.named_steps.get("model")
    preprocessor = pipeline.named_steps.get("preprocessor")
    if model is None or preprocessor is None or not hasattr(model, "feature_importances_"):
        return []

    try:
        encoded_names = list(preprocessor.get_feature_names_out())
    except Exception:
        encoded_names = [f"feature_{i}" for i in range(len(model.feature_importances_))]

    grouped: dict[str, float] = {}
    for name, importance in zip(encoded_names, model.feature_importances_):
        base = _base_feature_name(str(name))
        grouped[base] = grouped.get(base, 0.0) + _coerce_float(importance, 0.0)

    ranked = sorted(grouped.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    return [{"feature": key, "importance": round(float(value), 6)} for key, value in ranked]


def _residual_diagnostics(y_true: pd.Series, y_pred: Any) -> dict[str, float]:
    residuals = pd.Series(y_true).reset_index(drop=True) - pd.Series(y_pred)
    abs_residuals = residuals.abs()
    std = float(residuals.std(ddof=1)) if len(residuals) > 1 else 0.0
    return {
        "residual_std": round(std, 6),
        "mae": round(float(abs_residuals.mean()), 6),
        "residual_p10": round(float(np.percentile(residuals, 10)), 6),
        "residual_p50": round(float(np.percentile(residuals, 50)), 6),
        "residual_p90": round(float(np.percentile(residuals, 90)), 6),
    }


def _label_distribution(y: pd.Series) -> dict[str, int]:
    return {str(k): int(v) for k, v in y.value_counts(dropna=False).to_dict().items()}


def _build_preprocessor(features: list[str], categorical: list[str]) -> ColumnTransformer:
    numeric = [f for f in features if f not in categorical]
    return ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), categorical),
            ("num", "passthrough", numeric),
        ],
        remainder="drop",
    )


def _build_classifier(features: list[str], categorical: list[str], seed: int, n_jobs: int) -> Pipeline:
    return Pipeline(
        steps=[
            ("preprocessor", _build_preprocessor(features, categorical)),
            (
                "model",
                RandomForestClassifier(
                    n_estimators=300,
                    random_state=seed,
                    n_jobs=n_jobs,
                    class_weight="balanced",
                ),
            ),
        ]
    )


def _build_regressor(features: list[str], categorical: list[str], seed: int, n_jobs: int) -> Pipeline:
    return Pipeline(
        steps=[
            ("preprocessor", _build_preprocessor(features, categorical)),
            (
                "model",
                RandomForestRegressor(
                    n_estimators=300,
                    random_state=seed,
                    n_jobs=n_jobs,
                ),
            ),
        ]
    )


def _build_hgb_regressor(features: list[str], categorical: list[str], seed: int) -> Pipeline:
    """HistGradientBoostingRegressor — mejor que RandomForest en datasets tabulares medianos."""
    return Pipeline(
        steps=[
            ("preprocessor", _build_preprocessor(features, categorical)),
            (
                "model",
                HistGradientBoostingRegressor(
                    max_iter=400,
                    learning_rate=0.05,
                    max_depth=6,
                    min_samples_leaf=20,
                    l2_regularization=0.1,
                    random_state=seed,
                ),
            ),
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train supplier and/or real-estate models.")
    parser.add_argument("--domain", choices=["suppliers", "real_estate", "all"], default="all")
    parser.add_argument("--suppliers-dataset-path", type=str, default="data/raw/proveedores_riesgo_snapshots.csv")
    parser.add_argument("--raw-dir", type=str, default="data/raw")
    parser.add_argument("--artifacts-dir", type=str, default="artifacts")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--n-jobs", type=int, default=1)
    return parser.parse_args()


def _resolve_supplier_dataset(path: Path) -> Path:
    if path.exists():
        return path
    fallbacks = [
        Path("data/raw/suppliers_risk_snapshots.csv"),
        Path("data/raw/supplier_risk_dataset.csv"),
    ]
    found = next((p for p in fallbacks if p.exists()), None)
    if found is None:
        raise FileNotFoundError(f"Supplier dataset not found at {path}. Run data/generate_dataset.py first.")
    return found


def train_suppliers(
    dataset_path: Path,
    artifacts_dir: Path,
    seed: int,
    test_size: float,
    n_jobs: int,
) -> dict[str, Any]:
    df = pd.read_csv(dataset_path)
    required = SUPPLIER_FEATURES + ["risk_tier", "behavior_state", "forecast_risk_score_90"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Supplier dataset missing required columns: {missing}")

    X = df[SUPPLIER_FEATURES].copy()
    y_seg = df["risk_tier"].copy()
    y_beh = df["behavior_state"].copy()
    y_for = df["forecast_risk_score_90"].copy()

    X_train, X_test, y_seg_train, y_seg_test = train_test_split(
        X,
        y_seg,
        test_size=test_size,
        random_state=seed,
        stratify=y_seg,
    )
    y_beh_train = y_beh.loc[X_train.index]
    y_beh_test = y_beh.loc[X_test.index]
    y_for_train = y_for.loc[X_train.index]
    y_for_test = y_for.loc[X_test.index]

    categorical = ["category"]
    segmentation_model = _build_classifier(SUPPLIER_FEATURES, categorical, seed, n_jobs)
    behavior_model = _build_classifier(SUPPLIER_FEATURES, categorical, seed + 1, n_jobs)
    forecast_model = _build_regressor(SUPPLIER_FEATURES, categorical, seed + 2, n_jobs)

    segmentation_model.fit(X_train, y_seg_train)
    behavior_model.fit(X_train, y_beh_train)
    forecast_model.fit(X_train, y_for_train)

    y_seg_pred = segmentation_model.predict(X_test)
    y_beh_pred = behavior_model.predict(X_test)
    y_for_pred = forecast_model.predict(X_test)

    # 5-fold cross-validation
    cv_seg = cross_val_score(
        _build_classifier(SUPPLIER_FEATURES, categorical, seed, n_jobs),
        X, y_seg, cv=StratifiedKFold(n_splits=5, shuffle=True, random_state=seed),
        scoring="f1_weighted", n_jobs=n_jobs,
    )
    cv_beh = cross_val_score(
        _build_classifier(SUPPLIER_FEATURES, categorical, seed + 1, n_jobs),
        X, y_beh, cv=StratifiedKFold(n_splits=5, shuffle=True, random_state=seed),
        scoring="f1_weighted", n_jobs=n_jobs,
    )
    cv_for = cross_val_score(
        _build_regressor(SUPPLIER_FEATURES, categorical, seed + 2, n_jobs),
        X, y_for, cv=KFold(n_splits=5, shuffle=True, random_state=seed),
        scoring="r2", n_jobs=n_jobs,
    )

    joblib.dump(segmentation_model, artifacts_dir / "segmentation_model.joblib")
    joblib.dump(behavior_model, artifacts_dir / "behavior_model.joblib")
    joblib.dump(forecast_model, artifacts_dir / "forecast_model.joblib")

    seg_diags = {
        "feature_importance_top": _feature_importance_summary(segmentation_model),
        "label_distribution": _label_distribution(y_seg),
    }
    beh_diags = {
        "feature_importance_top": _feature_importance_summary(behavior_model),
        "label_distribution": _label_distribution(y_beh),
    }
    for_diags = {
        "feature_importance_top": _feature_importance_summary(forecast_model),
        **_residual_diagnostics(y_for_test, y_for_pred),
    }

    return {
        "segmentation": {
            "accuracy": round(float(accuracy_score(y_seg_test, y_seg_pred)), 4),
            "f1_weighted": round(float(f1_score(y_seg_test, y_seg_pred, average="weighted")), 4),
            "cv_f1_weighted_mean": round(float(cv_seg.mean()), 4),
            "cv_f1_weighted_std": round(float(cv_seg.std()), 4),
            "diagnostics": seg_diags,
        },
        "behavior": {
            "accuracy": round(float(accuracy_score(y_beh_test, y_beh_pred)), 4),
            "f1_weighted": round(float(f1_score(y_beh_test, y_beh_pred, average="weighted")), 4),
            "cv_f1_weighted_mean": round(float(cv_beh.mean()), 4),
            "cv_f1_weighted_std": round(float(cv_beh.std()), 4),
            "diagnostics": beh_diags,
        },
        "forecast": {
            "mae": round(float(mean_absolute_error(y_for_test, y_for_pred)), 4),
            "r2": round(float(r2_score(y_for_test, y_for_pred)), 4),
            "cv_r2_mean": round(float(cv_for.mean()), 4),
            "cv_r2_std": round(float(cv_for.std()), 4),
            "diagnostics": for_diags,
        },
        "dataset": {"rows": int(df.shape[0]), "dataset_path": str(dataset_path), "features": SUPPLIER_FEATURES},
    }


def _load_real_estate_training_frame(raw_dir: Path) -> pd.DataFrame:
    required = {
        "projects": raw_dir / "inmobiliario_proyectos.csv",
        "units": raw_dir / "inmobiliario_unidades.csv",
        "transactions": raw_dir / "inmobiliario_transacciones.csv",
        "reservations": raw_dir / "inmobiliario_reservas.csv",
        "market": raw_dir / "inmobiliario_mercado_mensual.csv",
        "macro": raw_dir / "inmobiliario_macro_mensual.csv",
    }
    missing = [str(p) for p in required.values() if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Real-estate tables missing: {missing}")

    projects = pd.read_csv(required["projects"])
    units = pd.read_csv(required["units"])
    transactions = pd.read_csv(required["transactions"])
    reservations = pd.read_csv(required["reservations"])
    market = pd.read_csv(required["market"])
    macro = pd.read_csv(required["macro"])

    transactions["period"] = pd.to_datetime(transactions["transaction_date"]).dt.strftime("%Y-%m")
    market = market.rename(
        columns={
            "sale_price_eur_m2": "sale_price_eur_m2_city",
            "rent_price_eur_m2_month": "rent_price_eur_m2_month_city",
            "demand_index": "demand_index_city",
        }
    )

    frame = (
        transactions.merge(units, on=["unit_id", "project_id"], how="left", suffixes=("", "_unit"))
        .merge(projects[["project_id", "city", "zone", "asset_type", "base_eur_m2", "sustainability_index", "complexity_index"]], on="project_id", how="left")
        .merge(market[["period", "city", "sale_price_eur_m2_city", "rent_price_eur_m2_month_city", "demand_index_city", "absorption_units_month", "inventory_index"]], on=["period", "city"], how="left")
        .merge(macro[["period", "euribor_12m_pct", "inflation_yoy_pct"]], on="period", how="left")
        .merge(reservations[["reservation_id", "reservation_date"]], on="reservation_id", how="left")
    )

    frame["days_to_close"] = (
        pd.to_datetime(frame["transaction_date"]) - pd.to_datetime(frame["reservation_date"])
    ).dt.days.clip(lower=5, upper=365)
    # gross_yield_pct viene directamente de la tabla de transacciones
    frame = frame.dropna(subset=["final_price_eur", "expected_rent_eur_month", "days_to_close"])
    frame["absorption_units_month"] = frame["absorption_units_month"].fillna(8.5)
    frame["inventory_index"] = frame["inventory_index"].fillna(100.0)
    return frame


def train_real_estate(
    raw_dir: Path,
    artifacts_dir: Path,
    seed: int,
    test_size: float,
    n_jobs: int,
) -> dict[str, Any]:
    df = _load_real_estate_training_frame(raw_dir)
    missing = [c for c in REAL_ESTATE_FEATURES if c not in df.columns]
    if missing:
        raise ValueError(f"Real-estate training frame missing required features: {missing}")

    X = df[REAL_ESTATE_FEATURES].copy()
    y_sale = df["final_price_eur"].copy()
    y_rent = df["expected_rent_eur_month"].copy()
    y_liquidity = df["days_to_close"].copy()
    # Nota: investment_score se deriva en inference de rent_pred/sale_pred (ratio de los dos modelos).
    # gross_yield_pct en los datos sintéticos es casi puro ruido (corr≈0 con features) por
    # construcción del generador (multiplier aleatorio de precio), por lo que no se entrena modelo separado.

    X_train, X_test, y_sale_train, y_sale_test = train_test_split(
        X, y_sale, test_size=test_size, random_state=seed
    )
    y_rent_train = y_rent.loc[X_train.index]
    y_rent_test = y_rent.loc[X_test.index]
    y_liq_train = y_liquidity.loc[X_train.index]
    y_liq_test = y_liquidity.loc[X_test.index]

    categorical = ["city", "zone", "asset_type", "energy_rating"]
    sale_model = _build_regressor(REAL_ESTATE_FEATURES, categorical, seed + 10, n_jobs)
    rent_model = _build_regressor(REAL_ESTATE_FEATURES, categorical, seed + 11, n_jobs)
    # HGB para el modelo de liquidez (era R²=0.546 con RandomForest)
    liquidity_model = _build_hgb_regressor(REAL_ESTATE_FEATURES, categorical, seed + 13)

    sale_model.fit(X_train, y_sale_train)
    rent_model.fit(X_train, y_rent_train)
    liquidity_model.fit(X_train, y_liq_train)

    sale_pred = sale_model.predict(X_test)
    rent_pred = rent_model.predict(X_test)
    liq_pred = liquidity_model.predict(X_test)

    # 5-fold cross-validation
    cv_kf = KFold(n_splits=5, shuffle=True, random_state=seed)
    cv_sale = cross_val_score(sale_model, X, y_sale, cv=cv_kf, scoring="r2", n_jobs=n_jobs)
    cv_rent = cross_val_score(rent_model, X, y_rent, cv=cv_kf, scoring="r2", n_jobs=n_jobs)
    cv_liq = cross_val_score(liquidity_model, X, y_liquidity, cv=cv_kf, scoring="r2", n_jobs=n_jobs)

    joblib.dump(sale_model, artifacts_dir / "re_sale_price_model.joblib")
    joblib.dump(rent_model, artifacts_dir / "re_rent_model.joblib")
    joblib.dump(liquidity_model, artifacts_dir / "re_liquidity_model.joblib")

    sale_diag = {
        "feature_importance_top": _feature_importance_summary(sale_model),
        **_residual_diagnostics(y_sale_test, sale_pred),
    }
    rent_diag = {
        "feature_importance_top": _feature_importance_summary(rent_model),
        **_residual_diagnostics(y_rent_test, rent_pred),
    }
    liquidity_diag = {
        "feature_importance_top": _feature_importance_summary(liquidity_model),
        **_residual_diagnostics(y_liq_test, liq_pred),
    }

    return {
        "sale_price": {
            "mae": round(float(mean_absolute_error(y_sale_test, sale_pred)), 2),
            "r2": round(float(r2_score(y_sale_test, sale_pred)), 4),
            "cv_r2_mean": round(float(cv_sale.mean()), 4),
            "cv_r2_std": round(float(cv_sale.std()), 4),
            "diagnostics": sale_diag,
        },
        "rent": {
            "mae": round(float(mean_absolute_error(y_rent_test, rent_pred)), 2),
            "r2": round(float(r2_score(y_rent_test, rent_pred)), 4),
            "cv_r2_mean": round(float(cv_rent.mean()), 4),
            "cv_r2_std": round(float(cv_rent.std()), 4),
            "diagnostics": rent_diag,
        },
        "investment_score": {
            "method": "derived_from_rent_sale_ratio",
            "note": "score = clip(predicted_rent*12/predicted_sale/0.08, 0, 1)*100. No se entrena modelo separado.",
        },
        "liquidity": {
            "mae_days": round(float(mean_absolute_error(y_liq_test, liq_pred)), 2),
            "r2": round(float(r2_score(y_liq_test, liq_pred)), 4),
            "cv_r2_mean": round(float(cv_liq.mean()), 4),
            "cv_r2_std": round(float(cv_liq.std()), 4),
            "diagnostics": liquidity_diag,
        },
        "dataset": {"rows": int(df.shape[0]), "features": REAL_ESTATE_FEATURES, "raw_dir": str(raw_dir)},
    }


def main() -> None:
    args = parse_args()
    artifacts_dir = Path(args.artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    output_metrics: dict[str, Any] = {"domain": args.domain}

    if args.domain in ("suppliers", "all"):
        supplier_dataset = _resolve_supplier_dataset(Path(args.suppliers_dataset_path))
        output_metrics["suppliers"] = train_suppliers(
            dataset_path=supplier_dataset,
            artifacts_dir=artifacts_dir,
            seed=args.seed,
            test_size=args.test_size,
            n_jobs=args.n_jobs,
        )

    if args.domain in ("real_estate", "all"):
        output_metrics["real_estate"] = train_real_estate(
            raw_dir=Path(args.raw_dir),
            artifacts_dir=artifacts_dir,
            seed=args.seed,
            test_size=args.test_size,
            n_jobs=args.n_jobs,
        )

    generated_at = datetime.now(timezone.utc).isoformat()
    diagnostics = {
        "generated_at_utc": generated_at,
        "domain": args.domain,
        "suppliers": (output_metrics.get("suppliers") or {}),
        "real_estate": (output_metrics.get("real_estate") or {}),
    }

    (artifacts_dir / "metrics.json").write_text(json.dumps(output_metrics, indent=2), encoding="utf-8")
    (artifacts_dir / "model_diagnostics.json").write_text(
        json.dumps(diagnostics, indent=2),
        encoding="utf-8",
    )
    print("Training completed.")
    print(json.dumps(output_metrics, indent=2))
    print(f"Artifacts saved in: {artifacts_dir.resolve()}")


if __name__ == "__main__":
    main()
