from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def clip(values: np.ndarray | float, low: float, high: float):
    return np.minimum(np.maximum(values, low), high)


def random_dates(
    rng: np.random.Generator,
    start: datetime,
    end: datetime,
    size: int,
) -> pd.Series:
    seconds = (end - start).total_seconds()
    rand_seconds = rng.uniform(0, seconds, size=size)
    return pd.Series(pd.to_datetime([start + timedelta(seconds=float(s)) for s in rand_seconds]))


@dataclass
class SupplierConfig:
    seed: int = 42
    n_suppliers: int = 220
    n_snapshots: int = 18
    start_date: str = "2024-01-01"
    output_path: str = "data/raw/proveedores_riesgo_snapshots.csv"


@dataclass
class RealEstateConfig:
    seed: int = 42
    start_date: str = "2021-01-01"
    end_date: str = "2025-12-31"
    n_projects: int = 28
    min_units_per_project: int = 35
    max_units_per_project: int = 130
    n_customers: int = 6500
    avg_leads_per_customer: float = 1.6
    out_dir: str = "data/raw"


SUPPLIER_CATEGORIES = [
    "cemento",
    "hormigon",
    "acero",
    "electricidad",
    "fontaneria",
    "acabados",
    "logistica",
]


REAL_ESTATE_CITIES = {
    "Madrid": ["Valdebebas", "Sanchinarro", "Arganzuela", "Carabanchel", "Las Tablas"],
    "Barcelona": ["Eixample", "Sants", "Sant Marti", "Gracia", "Les Corts"],
    "Valencia": ["Ruzafa", "Campanar", "Patraix", "Benimaclet", "Quatre Carreres"],
    "Sevilla": ["Nervion", "Triana", "Los Remedios", "Sevilla Este", "Cartuja"],
    "Malaga": ["Teatinos", "Centro", "Carretera de Cadiz", "El Limonar", "Martiricos"],
}

REGION_BY_CITY = {
    "Madrid": "Comunidad de Madrid",
    "Barcelona": "Cataluna",
    "Valencia": "Comunitat Valenciana",
    "Sevilla": "Andalucia",
    "Malaga": "Andalucia",
}


def generate_supplier_dataset(cfg: SupplierConfig) -> pd.DataFrame:
    rng = np.random.default_rng(cfg.seed)
    profiles = rng.choice(["stable", "watch", "fragile"], size=cfg.n_suppliers, p=[0.45, 0.35, 0.20])
    profile_factor = np.where(profiles == "fragile", 1.35, np.where(profiles == "watch", 1.10, 0.85))
    categories = rng.choice(SUPPLIER_CATEGORIES, size=cfg.n_suppliers, replace=True)
    suppliers = pd.DataFrame(
        {
            "supplier_id": [f"SUP_{i:04d}" for i in range(1, cfg.n_suppliers + 1)],
            "supplier_name": [f"SUP_{i:04d}" for i in range(1, cfg.n_suppliers + 1)],
            "category": categories,
            "risk_profile": profiles,
            "base_dependency_pct": clip(rng.normal(38, 16, cfg.n_suppliers) * profile_factor, 5, 92),
            "base_incidents": clip(rng.normal(5.2, 2.7, cfg.n_suppliers) * profile_factor, 0, 22),
            "base_delay_days": clip(rng.normal(10.5, 5.0, cfg.n_suppliers) * profile_factor, 0, 42),
            "base_margin_pct": clip(rng.normal(16, 7, cfg.n_suppliers) / profile_factor, 1, 40),
            "base_orders": clip(rng.normal(95, 42, cfg.n_suppliers), 10, 240),
            "base_annual_volume_eur": clip(rng.normal(3_000_000, 1_150_000, cfg.n_suppliers), 250_000, 9_500_000),
        }
    )

    rows: list[dict[str, Any]] = []
    start_date = pd.Timestamp(cfg.start_date)
    for period in range(cfg.n_snapshots):
        snapshot_date = (start_date + pd.DateOffset(months=period)).date().isoformat()
        macro_pressure = float(clip(rng.normal(1.0, 0.08), 0.82, 1.22))
        demand_pressure = float(clip(rng.normal(1.0, 0.10), 0.80, 1.25))
        for _, s in suppliers.iterrows():
            month_shock = float(clip(rng.normal(1.0, 0.12), 0.75, 1.35))
            profile_shock = (
                float(clip(rng.normal(1.08, 0.10), 0.9, 1.35))
                if s["risk_profile"] == "fragile"
                else float(clip(rng.normal(0.95, 0.08), 0.75, 1.1))
                if s["risk_profile"] == "stable"
                else 1.0
            )

            dependency_pct = float(clip(s["base_dependency_pct"] * rng.normal(1.0, 0.13) * profile_shock, 1, 95))
            incidents = float(clip(s["base_incidents"] * macro_pressure * month_shock * rng.normal(1.0, 0.38), 0, 22))
            avg_delay_days = float(
                clip(s["base_delay_days"] * (0.75 + 0.25 * macro_pressure) * month_shock * rng.normal(1.0, 0.32), 0, 45)
            )
            estimated_margin_pct = float(clip(s["base_margin_pct"] * rng.normal(1.0, 0.18) / month_shock, 1, 45))
            orders = float(clip(s["base_orders"] * demand_pressure * rng.normal(1.0, 0.22), 4, 320))
            annual_volume_eur = float(
                clip(s["base_annual_volume_eur"] * demand_pressure * rng.normal(1.0, 0.18), 120_000, 14_000_000)
            )

            risk_score = 0.45 * dependency_pct + 3.0 * incidents + 1.5 * avg_delay_days - 1.0 * estimated_margin_pct
            risk_tier_rule = "HIGH" if risk_score >= 120 else "MED" if risk_score >= 70 else "LOW"
            reliability_index = float(
                clip(
                    100 - (4.0 * incidents + 2.0 * avg_delay_days + 0.45 * dependency_pct + 0.03 * orders - 0.35 * estimated_margin_pct),
                    0,
                    100,
                )
            )
            # behavior_state incorpora variable latente risk_profile (NO está en SUPPLIER_FEATURES)
            # + ruido gaussiano, forzando al modelo ML a aprender en lugar de memorizar la fórmula.
            _profile_bonus = {"stable": 15.0, "watch": 0.0, "fragile": -20.0}[s["risk_profile"]]
            _behavior_noise = float(rng.normal(0.0, 8.0))
            behavior_score = float(
                clip(reliability_index + 0.30 * _profile_bonus + _behavior_noise, 0, 100)
            )
            behavior_state = "critical" if behavior_score < 42 else "warning" if behavior_score < 72 else "stable"
            trend_component = 0.7 * incidents + 0.45 * avg_delay_days + 0.08 * dependency_pct
            forecast_risk_score_90 = float(clip(risk_score + trend_component * 3.0 + rng.normal(0, 6.0), 0, 180))
            forecast_risk_level_90 = "HIGH" if forecast_risk_score_90 >= 120 else "MED" if forecast_risk_score_90 >= 75 else "LOW"

            rows.append(
                {
                    "snapshot_date": snapshot_date,
                    "supplier_id": s["supplier_id"],
                    "supplier_name": s["supplier_name"],
                    "category": s["category"],
                    "risk_profile": s["risk_profile"],
                    "annual_volume_eur": round(annual_volume_eur, 2),
                    "orders": int(round(orders)),
                    "incidents": round(incidents, 2),
                    "avg_delay_days": round(avg_delay_days, 2),
                    "dependency_pct": round(dependency_pct, 2),
                    "estimated_margin_pct": round(estimated_margin_pct, 2),
                    "macro_pressure": round(macro_pressure, 4),
                    "demand_pressure": round(demand_pressure, 4),
                    "risk_score": round(risk_score, 2),
                    "risk_tier_rule": risk_tier_rule,
                    "reliability_index": round(reliability_index, 2),
                    "behavior_state": behavior_state,
                    "forecast_risk_score_90": round(forecast_risk_score_90, 2),
                    "forecast_risk_level_90": forecast_risk_level_90,
                }
            )

    df = pd.DataFrame(rows)
    q_low = df["risk_score"].quantile(0.60)
    q_high = df["risk_score"].quantile(0.85)
    df["risk_tier"] = np.where(df["risk_score"] >= q_high, "HIGH", np.where(df["risk_score"] >= q_low, "MED", "LOW"))
    return df


def generate_real_estate_tables(cfg: RealEstateConfig) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(cfg.seed)
    start = datetime.fromisoformat(cfg.start_date)
    end = datetime.fromisoformat(cfg.end_date)

    projects = _build_projects(rng, cfg, start, end)
    units = _build_units(rng, projects, cfg)
    macro_monthly = _build_macro_monthly(rng, start, end)
    market_monthly = _build_market_monthly(rng, projects, macro_monthly)
    customers = _build_customers(rng, cfg)
    leads, reservations, transactions = _build_funnel(rng, projects, units, customers, macro_monthly, start, end, cfg)
    legal_assets = _build_legal_assets(rng, units, projects)

    return {
        "inmobiliario_proyectos": projects,
        "inmobiliario_unidades": units,
        "inmobiliario_macro_mensual": macro_monthly,
        "inmobiliario_mercado_mensual": market_monthly,
        "inmobiliario_clientes": customers,
        "inmobiliario_leads": leads,
        "inmobiliario_reservas": reservations,
        "inmobiliario_transacciones": transactions,
        "inmobiliario_activos_legales": legal_assets,
    }


def _build_projects(rng: np.random.Generator, cfg: RealEstateConfig, start: datetime, end: datetime) -> pd.DataFrame:
    cities = list(REAL_ESTATE_CITIES.keys())
    project_city = rng.choice(cities, size=cfg.n_projects, replace=True)
    project_zone = [rng.choice(REAL_ESTATE_CITIES[c]) for c in project_city]
    launch = random_dates(rng, start, end - timedelta(days=365), cfg.n_projects).dt.floor("D")
    construction_months = rng.integers(10, 30, size=cfg.n_projects)
    completion = pd.to_datetime([d + pd.DateOffset(months=int(m)) for d, m in zip(launch, construction_months)])
    base_price_city = {"Madrid": 4300, "Barcelona": 4500, "Valencia": 3200, "Sevilla": 2900, "Malaga": 3600}
    base_eur_m2 = np.array([base_price_city[c] for c in project_city], dtype=float) * rng.normal(1.0, 0.08, size=cfg.n_projects)

    return pd.DataFrame(
        {
            "project_id": [f"PRJ_{i:04d}" for i in range(1, cfg.n_projects + 1)],
            "project_name": [f"Project_{i:04d}" for i in range(1, cfg.n_projects + 1)],
            "city": project_city,
            "region": [REGION_BY_CITY[c] for c in project_city],
            "zone": project_zone,
            "launch_date": launch,
            "completion_date": completion,
            "units_total": rng.integers(cfg.min_units_per_project, cfg.max_units_per_project + 1, size=cfg.n_projects),
            "base_eur_m2": base_eur_m2.round(2),
            "sustainability_index": clip(rng.normal(0.58, 0.16, cfg.n_projects), 0.0, 1.0).round(3),
            "complexity_index": clip(rng.normal(0.44, 0.20, cfg.n_projects), 0.0, 1.0).round(3),
            "asset_type": rng.choice(["residencial", "mixto", "build_to_rent"], size=cfg.n_projects, p=[0.72, 0.14, 0.14]),
        }
    )


def _build_units(rng: np.random.Generator, projects: pd.DataFrame, cfg: RealEstateConfig) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    energy_choices = ["A", "B", "C", "D"]
    for _, p in projects.iterrows():
        n = int(p["units_total"])
        beds = rng.choice([1, 2, 3, 4], size=n, p=[0.10, 0.40, 0.38, 0.12])
        sqm = clip(beds * rng.normal(28, 6, size=n) + rng.normal(30, 9, size=n), 35, 180)
        floor = rng.integers(0, 14, size=n)
        terrace = rng.random(size=n) < 0.38
        garage = rng.random(size=n) < 0.66
        storage = rng.random(size=n) < 0.57
        premium = 1 + (floor >= 6) * 0.03 + terrace * 0.04 + garage * 0.02 + storage * 0.015
        list_price = clip(sqm * float(p["base_eur_m2"]) * premium * rng.normal(1.0, 0.05, size=n), 95_000, 1_450_000)
        monthly_rent = clip((list_price * rng.uniform(0.038, 0.065, size=n)) / 12, 550, 4200)

        for i in range(n):
            rows.append(
                {
                    "unit_id": f"{p['project_id']}_U{i+1:03d}",
                    "project_id": p["project_id"],
                    "bedrooms": int(beds[i]),
                    "sqm": round(float(sqm[i]), 2),
                    "floor": int(floor[i]),
                    "has_terrace": int(terrace[i]),
                    "has_garage": int(garage[i]),
                    "has_storage": int(storage[i]),
                    "energy_rating": str(rng.choice(energy_choices, p=[0.18, 0.39, 0.31, 0.12])),
                    "list_price_eur": round(float(list_price[i]), 2),
                    "expected_rent_eur_month": round(float(monthly_rent[i]), 2),
                    "status": "available",
                }
            )
    return pd.DataFrame(rows)


def _build_macro_monthly(rng: np.random.Generator, start: datetime, end: datetime) -> pd.DataFrame:
    periods = pd.date_range(start=start, end=end, freq="MS")
    euribor = clip(2.2 + np.sin(np.linspace(0, 8, len(periods))) * 0.9 + rng.normal(0, 0.12, len(periods)), 1.4, 4.8)
    inflation = clip(2.6 + np.cos(np.linspace(0, 9, len(periods))) * 0.8 + rng.normal(0, 0.20, len(periods)), 1.0, 6.2)
    unemployment = clip(12.2 + np.sin(np.linspace(0, 6, len(periods))) * 1.0 + rng.normal(0, 0.25, len(periods)), 8.5, 16.0)
    employment_growth = clip(1.3 + np.sin(np.linspace(0, 7, len(periods))) * 0.7 + rng.normal(0, 0.15, len(periods)), -0.9, 3.2)

    return pd.DataFrame(
        {
            "period": periods.strftime("%Y-%m"),
            "euribor_12m_pct": np.round(euribor, 3),
            "inflation_yoy_pct": np.round(inflation, 3),
            "unemployment_pct": np.round(unemployment, 3),
            "employment_growth_yoy_pct": np.round(employment_growth, 3),
            "consumer_confidence_idx": np.round(clip(95 + np.sin(np.linspace(0, 5, len(periods))) * 9 + rng.normal(0, 2.0, len(periods)), 75, 120), 2),
        }
    )


def _build_market_monthly(
    rng: np.random.Generator,
    projects: pd.DataFrame,
    macro_monthly: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    city_base_sale = {"Madrid": 4350, "Barcelona": 4520, "Valencia": 3180, "Sevilla": 2920, "Malaga": 3640}
    city_base_rent = {"Madrid": 18.2, "Barcelona": 20.3, "Valencia": 13.5, "Sevilla": 12.1, "Malaga": 14.7}
    periods = macro_monthly["period"].tolist()
    cities = sorted(projects["city"].unique().tolist())
    for city in cities:
        for idx, period in enumerate(periods):
            phase = idx / max(len(periods) - 1, 1)
            sale = city_base_sale[city] * (1 + phase * 0.20 + rng.normal(0, 0.015))
            rent = city_base_rent[city] * (1 + phase * 0.24 + rng.normal(0, 0.02))
            demand_idx = clip(100 + np.sin(phase * 10) * 14 + rng.normal(0, 4.0), 65, 145)
            absorption = clip(8 + np.cos(phase * 8) * 2.0 + rng.normal(0, 0.8), 3, 15)
            rows.append(
                {
                    "period": period,
                    "city": city,
                    "sale_price_eur_m2": round(float(sale), 2),
                    "rent_price_eur_m2_month": round(float(rent), 2),
                    "demand_index": round(float(demand_idx), 2),
                    "absorption_units_month": round(float(absorption), 2),
                    "inventory_index": round(float(clip(100 - (demand_idx - 100) * 0.45 + rng.normal(0, 2.2), 60, 150)), 2),
                }
            )
    return pd.DataFrame(rows)


def _build_customers(rng: np.random.Generator, cfg: RealEstateConfig) -> pd.DataFrame:
    seg = rng.choice(["first_home", "investor", "premium", "upsizer"], size=cfg.n_customers, p=[0.54, 0.24, 0.08, 0.14])
    income = clip(
        np.where(
            seg == "first_home",
            rng.normal(39_000, 12_000, cfg.n_customers),
            np.where(seg == "investor", rng.normal(69_000, 23_000, cfg.n_customers), np.where(seg == "premium", rng.normal(126_000, 46_000, cfg.n_customers), rng.normal(76_000, 19_000, cfg.n_customers))),
        ),
        16_000,
        280_000,
    )
    savings = clip(income * rng.normal(0.43, 0.18, cfg.n_customers), 1_500, 260_000)
    financing_sensitivity = clip(
        np.where(
            seg == "first_home",
            rng.normal(0.74, 0.14, cfg.n_customers),
            np.where(seg == "investor", rng.normal(0.39, 0.16, cfg.n_customers), np.where(seg == "premium", rng.normal(0.24, 0.14, cfg.n_customers), rng.normal(0.56, 0.17, cfg.n_customers))),
        ),
        0,
        1,
    )
    return pd.DataFrame(
        {
            "customer_id": [f"CUS_{i:06d}" for i in range(1, cfg.n_customers + 1)],
            "segment_true": seg,
            "annual_income_eur": income.round(0).astype(int),
            "savings_eur": savings.round(0).astype(int),
            "green_preference": clip(rng.normal(0.56, 0.24, cfg.n_customers), 0, 1).round(3),
            "financing_sensitivity": np.round(financing_sensitivity, 3),
        }
    )


def _build_funnel(
    rng: np.random.Generator,
    projects: pd.DataFrame,
    units: pd.DataFrame,
    customers: pd.DataFrame,
    macro_monthly: pd.DataFrame,
    start: datetime,
    end: datetime,
    cfg: RealEstateConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    n_leads = int(cfg.n_customers * cfg.avg_leads_per_customer)
    leads_customer = rng.choice(customers["customer_id"].values, size=n_leads, replace=True)
    leads_project = rng.choice(projects["project_id"].values, size=n_leads, replace=True)
    lead_dates = random_dates(rng, start, end, n_leads).dt.floor("D")
    channels = rng.choice(["web", "referral", "agency", "campaign", "walk_in"], size=n_leads, p=[0.38, 0.14, 0.22, 0.16, 0.10])
    visits = clip(rng.poisson(2.0, size=n_leads), 0, 13).astype(int)

    customer_map = customers.set_index("customer_id")
    projects_map = projects.set_index("project_id")
    macro_map = macro_monthly.set_index("period").to_dict(orient="index")

    lead_rows: list[dict[str, Any]] = []
    for i in range(n_leads):
        c = customer_map.loc[leads_customer[i]]
        period = pd.Timestamp(lead_dates.iloc[i]).strftime("%Y-%m")
        macro = macro_map.get(period, {})
        euribor = float(macro.get("euribor_12m_pct", 2.5))
        project = projects_map.loc[leads_project[i]]
        score = (
            48
            + 16 * (float(c["annual_income_eur"]) / 100_000)
            + 9 * (float(c["savings_eur"]) / 90_000)
            + 7 * float(c["green_preference"])
            - 12 * float(c["financing_sensitivity"])
            - 1.8 * (euribor - 2.0)
            + visits[i] * 2.4
            + (7 if channels[i] in ("referral", "agency") else 0)
            + (4 if float(project["sustainability_index"]) > 0.65 else 0)
            + rng.normal(0, 8)
        )
        lead_rows.append(
            {
                "lead_id": f"LEAD_{i+1:07d}",
                "customer_id": leads_customer[i],
                "project_id": leads_project[i],
                "lead_date": lead_dates.iloc[i],
                "channel": channels[i],
                "visits": int(visits[i]),
                "lead_score": int(round(float(clip(score, 0, 100)))),
            }
        )
    leads = pd.DataFrame(lead_rows)

    units_pool = units.copy()
    units_pool["taken"] = False
    leads_shuffled = leads.sample(frac=1.0, random_state=cfg.seed).reset_index(drop=True)

    reservations_rows: list[dict[str, Any]] = []
    transactions_rows: list[dict[str, Any]] = []
    reservation_id = 1
    transaction_id = 1

    for _, lead in leads_shuffled.iterrows():
        project_id = lead["project_id"]
        project_units = units_pool[(units_pool["project_id"] == project_id) & (~units_pool["taken"])]
        if project_units.empty:
            continue

        cust = customer_map.loc[lead["customer_id"]]
        project = projects_map.loc[project_id]
        period = pd.Timestamp(lead["lead_date"]).strftime("%Y-%m")
        macro = macro_map.get(period, {})
        euribor = float(macro.get("euribor_12m_pct", 2.5))

        conversion_prob = float(
            clip(
                0.07
                + 0.0045 * lead["lead_score"]
                + 0.035 * lead["visits"]
                + (0.06 if lead["channel"] in ("referral", "agency") else 0.0)
                - 0.08 * float(cust["financing_sensitivity"])
                - 0.04 * float(project["complexity_index"])
                - 0.02 * max(0, euribor - 2.5)
                + rng.normal(0, 0.03),
                0.01,
                0.9,
            )
        )
        if rng.random() > conversion_prob:
            continue

        selected = project_units.sample(n=1, random_state=int(rng.integers(0, 1_000_000_000))).iloc[0]
        units_pool.loc[units_pool["unit_id"] == selected["unit_id"], "taken"] = True

        reserve_date = pd.Timestamp(lead["lead_date"]) + timedelta(days=int(rng.integers(2, 35)))
        deposit = float(selected["list_price_eur"]) * rng.uniform(0.03, 0.08)
        financing_ratio = float(
            clip(0.24 + 0.57 * float(cust["financing_sensitivity"]) + rng.normal(0, 0.08), 0.0, 0.92)
        )
        cancel_prob = float(
            clip(
                0.05
                + 0.11 * financing_ratio
                + 0.07 * float(project["complexity_index"])
                - 0.0028 * lead["lead_score"]
                + rng.normal(0, 0.02),
                0.01,
                0.62,
            )
        )
        status = "cancelled" if rng.random() < cancel_prob else "converted"
        cancel_date = reserve_date + timedelta(days=int(rng.integers(6, 120))) if status == "cancelled" else pd.NaT

        current_reservation_id = f"RES_{reservation_id:07d}"
        reservation_id += 1
        reservations_rows.append(
            {
                "reservation_id": current_reservation_id,
                "lead_id": lead["lead_id"],
                "customer_id": lead["customer_id"],
                "project_id": project_id,
                "unit_id": selected["unit_id"],
                "reservation_date": reserve_date.floor("D"),
                "deposit_eur": round(float(deposit), 2),
                "financing_ratio": round(financing_ratio, 3),
                "status": status,
                "cancel_date": cancel_date if pd.notna(cancel_date) else pd.NaT,
            }
        )

        if status == "converted":
            discount_pct = float(clip(0.018 + rng.normal(0.018, 0.01), 0, 0.09))
            sale_date = pd.Timestamp(project["completion_date"]) + timedelta(days=int(rng.integers(-50, 130)))
            sale_date = max(sale_date, reserve_date + timedelta(days=22))
            final_price = float(selected["list_price_eur"]) * (1 - discount_pct)
            estimated_cost = float(selected["sqm"]) * float(project["base_eur_m2"]) * rng.uniform(0.72, 0.87)
            monthly_rent = float(selected["expected_rent_eur_month"])
            gross_yield_pct = (monthly_rent * 12 / max(final_price, 1)) * 100

            transactions_rows.append(
                {
                    "transaction_id": f"TRX_{transaction_id:07d}",
                    "reservation_id": current_reservation_id,
                    "customer_id": lead["customer_id"],
                    "project_id": project_id,
                    "unit_id": selected["unit_id"],
                    "transaction_date": pd.Timestamp(sale_date).floor("D"),
                    "list_price_eur": round(float(selected["list_price_eur"]), 2),
                    "discount_pct": round(discount_pct, 4),
                    "final_price_eur": round(final_price, 2),
                    "estimated_cost_eur": round(estimated_cost, 2),
                    "estimated_margin_eur": round(final_price - estimated_cost, 2),
                    "expected_rent_eur_month": round(monthly_rent, 2),
                    "gross_yield_pct": round(gross_yield_pct, 3),
                }
            )
            transaction_id += 1

    reservations = pd.DataFrame(reservations_rows)
    transactions = pd.DataFrame(transactions_rows)
    return leads, reservations, transactions


def _build_legal_assets(rng: np.random.Generator, units: pd.DataFrame, projects: pd.DataFrame) -> pd.DataFrame:
    projects_map = projects.set_index("project_id")
    rows: list[dict[str, Any]] = []
    for _, unit in units.iterrows():
        project = projects_map.loc[unit["project_id"]]
        has_encumbrance = rng.random() < 0.16
        encumbrance_type = rng.choice(["hipoteca", "embargo", "servidumbre"]) if has_encumbrance else ""
        legal_risk = (
            "HIGH" if has_encumbrance and encumbrance_type in ("hipoteca", "embargo") else "MED" if has_encumbrance else "LOW"
        )
        rows.append(
            {
                "unit_id": unit["unit_id"],
                "project_id": unit["project_id"],
                "city": project["city"],
                "license_status": rng.choice(["granted", "in_review", "pending"], p=[0.72, 0.18, 0.10]),
                "occupancy_status": rng.choice(["vacant", "reserved", "occupied"], p=[0.62, 0.21, 0.17]),
                "has_encumbrance": int(has_encumbrance),
                "encumbrance_type": encumbrance_type,
                "legal_risk_tier": legal_risk,
                "last_legal_update": pd.Timestamp(project["launch_date"]) + pd.DateOffset(months=int(rng.integers(0, 25))),
            }
        )
    return pd.DataFrame(rows)


def write_table(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate datasets for supplier risk and real estate analysis.")
    parser.add_argument("--domain", choices=["all", "suppliers", "real_estate"], default="all")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--raw-dir", type=str, default="data/raw")
    parser.add_argument("--supplier-output", type=str, default="proveedores_riesgo_snapshots.csv")
    parser.add_argument("--supplier-legacy-output", type=str, default="")
    parser.add_argument("--n-suppliers", type=int, default=220)
    parser.add_argument("--n-snapshots", type=int, default=18)
    parser.add_argument("--n-projects", type=int, default=28)
    parser.add_argument("--n-customers", type=int, default=6500)
    parser.add_argument("--start-date", type=str, default="2021-01-01")
    parser.add_argument("--end-date", type=str, default="2025-12-31")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "domain": args.domain, "files": []}

    if args.domain in ("all", "suppliers"):
        supplier_cfg = SupplierConfig(
            seed=args.seed,
            n_suppliers=args.n_suppliers,
            n_snapshots=args.n_snapshots,
            start_date=max(args.start_date, "2024-01-01"),
            output_path=str(raw_dir / args.supplier_output),
        )
        suppliers = generate_supplier_dataset(supplier_cfg)
        supplier_path = Path(supplier_cfg.output_path)
        write_table(suppliers, supplier_path)
        manifest["files"].append({"name": supplier_path.name, "rows": int(len(suppliers))})

        legacy_output = (args.supplier_legacy_output or "").strip()
        if legacy_output:
            legacy_path = raw_dir / legacy_output
            write_table(suppliers, legacy_path)
            manifest["files"].append({"name": legacy_path.name, "rows": int(len(suppliers)), "legacy": True})

        print(f"[suppliers] {supplier_path} -> shape={suppliers.shape}")

    if args.domain in ("all", "real_estate"):
        re_cfg = RealEstateConfig(
            seed=args.seed,
            start_date=args.start_date,
            end_date=args.end_date,
            n_projects=args.n_projects,
            n_customers=args.n_customers,
            out_dir=str(raw_dir),
        )
        tables = generate_real_estate_tables(re_cfg)
        for table_name, df in tables.items():
            path = raw_dir / f"{table_name}.csv"
            write_table(df, path)
            manifest["files"].append({"name": path.name, "rows": int(len(df))})
            print(f"[real_estate] {path} -> shape={df.shape}")

    manifest_path = raw_dir / "dataset_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
