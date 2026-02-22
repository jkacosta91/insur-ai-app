from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

# ── Configuración ─────────────────────────────────────────────────────────────

DATASET_CANDIDATES = [
    Path("data/raw/proveedores_riesgo_snapshots.csv"),
    Path("data/raw/suppliers_risk_snapshots.csv"),
    Path("data/raw/supplier_risk_dataset.csv"),
]

# KPI → dirección de riesgo
_KPI_FIELDS: Dict[str, str] = {
    "incidents":            "higher_is_worse",
    "avg_delay_days":       "higher_is_worse",
    "dependency_pct":       "higher_is_worse",
    "estimated_margin_pct": "lower_is_worse",
    "annual_volume_eur":    "neutral",
    "orders":               "neutral",
}

_PERCENTILES = [1, 10, 25, 50, 75, 90, 95, 99]


# ── Stats cache (lazy) ────────────────────────────────────────────────────────

class _StatsCache:
    """Carga el dataset una sola vez y cachea estadísticas globales y por categoría."""

    def __init__(self) -> None:
        self._loaded = False
        self.n_rows: int = 0
        self.n_suppliers: int = 0
        self.categories: List[str] = []
        self.global_stats: Dict[str, Dict] = {}
        self.category_stats: Dict[str, Dict[str, Dict]] = {}

    def load(self) -> bool:
        if self._loaded:
            return True
        dataset_path = next((p for p in DATASET_CANDIDATES if p.exists()), None)
        if dataset_path is None:
            return False
        try:
            df = pd.read_csv(dataset_path)
            self.n_rows = len(df)
            self.n_suppliers = df["supplier_name"].nunique()
            self.categories = sorted(df["category"].dropna().unique().tolist())

            self.global_stats = {
                field: _compute_stats(df[field].dropna().values)
                for field in _KPI_FIELDS
                if field in df.columns
            }
            self.category_stats = {}
            for cat in self.categories:
                cat_df = df[df["category"] == cat]
                self.category_stats[cat] = {
                    field: _compute_stats(cat_df[field].dropna().values)
                    for field in _KPI_FIELDS
                    if field in cat_df.columns
                }
            self._loaded = True
            return True
        except Exception:
            return False


_cache = _StatsCache()


# ── Punto de entrada público ──────────────────────────────────────────────────

def benchmark_suppliers(
    suppliers: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Compara los KPIs de cada proveedor contra la distribución del dataset de entrenamiento.
    Devuelve percentiles, z-scores y etiquetas interpretables.
    """
    available = _cache.load()

    if not available:
        return {
            "available": False,
            "reason": "Dataset de entrenamiento no encontrado. Ejecuta data/generate_dataset.py primero.",
            "suppliers_benchmark": [],
        }

    rows = [_benchmark_one(s) for s in suppliers]

    # Resumen global
    critical_counts = [r["summary"]["kpis_critical"] for r in rows]
    all_kpi_labels = [
        kpi
        for r in rows
        for kpi, data in r["kpis"].items()
        if data.get("label", "").startswith("Crítico")
    ]
    most_critical = _most_common(all_kpi_labels)

    return {
        "available": True,
        "dataset_rows": _cache.n_rows,
        "dataset_suppliers": _cache.n_suppliers,
        "dataset_categories": _cache.categories,
        "suppliers_benchmark": rows,
        "global_summary": {
            "suppliers_with_critical_kpis": sum(1 for c in critical_counts if c > 0),
            "most_critical_kpi": most_critical,
            "out_of_distribution_count": sum(
                1 for r in rows if r["summary"]["has_outlier"]
            ),
        },
    }


# ── Benchmark individual ──────────────────────────────────────────────────────

def _benchmark_one(supplier: Dict[str, Any]) -> Dict[str, Any]:
    name = supplier.get("supplier_name", "unknown")
    category = str(supplier.get("category") or "").lower().strip()

    kpis: Dict[str, Any] = {}
    for field, direction in _KPI_FIELDS.items():
        raw = supplier.get(field)
        if raw is None:
            kpis[field] = {"value": None, "available": False}
            continue

        value = float(raw)
        g_stats = _cache.global_stats.get(field)
        c_stats = _cache.category_stats.get(category, {}).get(field)

        if g_stats is None:
            kpis[field] = {"value": value, "available": False}
            continue

        p_global = _percentile_rank(g_stats["sorted"], value)
        p_cat = _percentile_rank(c_stats["sorted"], value) if c_stats else None
        z = _z_score(value, g_stats["mean"], g_stats["std"])
        outlier = _is_outlier(z, value, g_stats["p1"], g_stats["p99"])

        kpis[field] = {
            "value": value,
            "available": True,
            "direction": direction,
            "dataset_mean": g_stats["mean"],
            "dataset_median": g_stats["p50"],
            "dataset_p25": g_stats["p25"],
            "dataset_p75": g_stats["p75"],
            "percentile_rank_global": p_global,
            "percentile_rank_category": p_cat,
            "z_score": z,
            "is_outlier": outlier,
            "label": _label(p_global, direction, outlier),
        }

    # Resumen por proveedor
    available_kpis = [v for v in kpis.values() if v.get("available")]
    critical = sum(1 for v in available_kpis if v.get("label", "").startswith("Crítico"))
    above = sum(1 for v in available_kpis if v.get("label", "").startswith("Elevado"))
    below = sum(1 for v in available_kpis if v.get("label", "").startswith("Buena"))
    outlier_count = sum(1 for v in available_kpis if v.get("is_outlier"))

    return {
        "supplier_name": name,
        "category": category,
        "kpis": kpis,
        "summary": {
            "kpis_critical": critical,
            "kpis_elevated": above,
            "kpis_normal": len(available_kpis) - critical - above - below,
            "kpis_good": below,
            "has_outlier": outlier_count > 0,
        },
    }


# ── Helpers estadísticos ──────────────────────────────────────────────────────

def _compute_stats(arr: np.ndarray) -> Dict[str, Any]:
    if len(arr) == 0:
        return {}
    sorted_arr = np.sort(arr)
    pcts = np.percentile(arr, _PERCENTILES)
    return {
        "sorted": sorted_arr,
        "mean": round(float(np.mean(arr)), 2),
        "std": round(float(np.std(arr)), 2),
        **{f"p{p}": round(float(v), 2) for p, v in zip(_PERCENTILES, pcts)},
    }


def _percentile_rank(sorted_arr: np.ndarray, value: float) -> float:
    n = len(sorted_arr)
    if n == 0:
        return 50.0
    pos = int(np.searchsorted(sorted_arr, value, side="right"))
    return round(float(pos / n * 100), 1)


def _z_score(value: float, mean: float, std: float) -> float:
    if std == 0:
        return 0.0
    return round((value - mean) / std, 2)


def _is_outlier(z: float, value: float, p1: float, p99: float) -> bool:
    return abs(z) > 2.5 or value > p99 or value < p1


def _label(percentile: float, direction: str, is_outlier: bool) -> str:
    suffix = " ⚠️ outlier" if is_outlier else ""
    p = int(percentile)
    if direction == "higher_is_worse":
        if percentile >= 90:
            return f"Crítico (p{p} global){suffix}"
        if percentile >= 75:
            return f"Elevado (p{p} global){suffix}"
        if percentile >= 25:
            return f"Normal (p{p} global){suffix}"
        return f"Buena señal (p{p} global){suffix}"
    if direction == "lower_is_worse":
        if percentile <= 10:
            return f"Crítico (p{p} global){suffix}"
        if percentile <= 25:
            return f"Bajo (p{p} global){suffix}"
        if percentile <= 75:
            return f"Normal (p{p} global){suffix}"
        return f"Buena señal (p{p} global){suffix}"
    return f"p{p}{suffix}"


def _most_common(items: List[str]) -> Optional[str]:
    if not items:
        return None
    return max(set(items), key=items.count)
