from __future__ import annotations

import base64
import io
import json
import os
import re
import time
import unicodedata
from datetime import datetime
from typing import Any, Dict, Iterable, List
from xml.sax.saxutils import escape as xml_escape


# ── Logo helper ──────────────────────────────────────────────────────────────
_LOGO_PATH = os.path.join(os.path.dirname(__file__), "static", "logo_insur.png")

def _logo_img_tag(height: int = 60) -> str:
  """Returns an <img> tag with the logo embedded as base64, or empty string if not found."""
  if os.path.isfile(_LOGO_PATH):
    with open(_LOGO_PATH, "rb") as f:
      data = base64.b64encode(f.read()).decode()
    return f'<img src="data:image/png;base64,{data}" height="{height}" style="display:block;" alt="Grupo Insur"/>'
  return ""  # fallback handled by caller

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
from pypdf import PdfReader
from reportlab.lib import colors as _rl_colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
  Image as _rl_Image,
  Paragraph,
  SimpleDocTemplate,
  Spacer,
  Table,
  TableStyle,
)
from requests.exceptions import ConnectionError as RequestsConnectionError, RequestException


st.set_page_config(
  page_title="Grupo Insur Analisis Inteligente",
  page_icon="GI",
  layout="wide",
  initial_sidebar_state="expanded",
)
SESSION = requests.Session()


def _read_dotenv_var(name: str, dotenv_path: str = ".env") -> str:
  try:
    with open(dotenv_path, "r", encoding="utf-8") as fh:
      for raw in fh:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
          continue
        key, value = line.split("=", 1)
        if key.strip() != name:
          continue
        cleaned = value.strip().strip('"').strip("'")
        return cleaned
  except Exception:
    return ""
  return ""


def _env_or_dotenv(name: str, default: str = "") -> str:
  from_env = os.getenv(name, "").strip()
  if from_env:
    return from_env
  from_file = _read_dotenv_var(name).strip()
  if from_file:
    return from_file
  return default


DEFAULT_N8N_URL = _env_or_dotenv("N8N_WEBHOOK_URL", "")
N8N_STRICT_DECISIONS = _env_or_dotenv("N8N_STRICT_DECISIONS", "true").lower() in {"1", "true", "yes", "on"}

RISK_COLORS = {"HIGH": "#C23B2A", "MED": "#C4922A", "LOW": "#1A6B4A"}
RISK_BG = {"HIGH": "rgba(194,59,42,0.10)", "MED": "rgba(196,146,42,0.10)", "LOW": "rgba(26,107,74,0.10)"}
RISK_BORDER = {"HIGH": "rgba(194,59,42,0.30)", "MED": "rgba(196,146,42,0.30)", "LOW": "rgba(26,107,74,0.30)"}

# Brand Plotly template (Grupo Insur)
PLOTLY_LAYOUT = dict(
  plot_bgcolor="rgba(0,0,0,0)",
  paper_bgcolor="rgba(0,0,0,0)",
  font=dict(family="Lato, sans-serif", color="#1a1a1a", size=12),
  title_font=dict(family="Lato, sans-serif", color="#00417d", size=16, weight=700),
  legend=dict(bgcolor="rgba(0,65,125,0.05)", bordercolor="rgba(0,65,125,0.15)", borderwidth=1),
  xaxis=dict(gridcolor="rgba(149,152,154,0.20)", linecolor="rgba(149,152,154,0.30)"),
  yaxis=dict(gridcolor="rgba(149,152,154,0.20)", linecolor="rgba(149,152,154,0.30)"),
  margin=dict(l=16, r=16, t=40, b=16),
  colorway=["#00417d", "#de6d51", "#2e7d32", "#009fe3", "#e65100", "#c62828"],
)


def inject_styles() -> None:
  st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Lato:ital,wght@0,300;0,400;0,700;0,900;1,400&display=swap');

    :root {
      --insur-blue: #00417d;
      --insur-orange: #de6d51;
      --insur-grey: #95989a;
      --insur-grey-light: rgba(149,152,154,.15);
      --insur-blue-light: rgba(0,65,125,.08);
      --insur-blue-mid: rgba(0,65,125,.18);
      --bg: #f4f5f7;
      --bg2: #ffffff;
      --surface: #ffffff;
      --surface-warm: #f9f9f9;
      --text: #1a1a1a;
      --muted: #666666;
      --muted2: #95989a;
      --line: rgba(149,152,154,.25);
      --line-strong: rgba(0,65,125,.20);
      --card: #ffffff;
      --ok: #2e7d32;
      --ok-pale: rgba(46,125,50,.10);
      --danger: #c62828;
      --danger-pale: rgba(198,40,40,.10);
      --warn: #e65100;
      --warn-pale: rgba(230,81,0,.10);
      --nav-h: 68px;
    }

    *, *::before, *::after { box-sizing: border-box; }

    html, body, [class*="css"], .stApp {
      font-family: 'Lato', sans-serif !important;
      -webkit-font-smoothing: antialiased;
    }

    .stApp {
      background: var(--bg) !important;
      color: var(--text) !important;
    }

    [data-testid="stMain"] * { color: var(--text); }
    [data-testid="stMarkdownContainer"] *, .stMarkdown * { color: var(--text) !important; }
    .stCaption { color: var(--muted) !important; }

    /* Topbar */
    nav.topbar {
      position: fixed; top: 0; left: 0; right: 0; z-index: 1000;
      height: var(--nav-h);
      display: flex; align-items: center; justify-content: space-between;
      padding: 0 40px;
      background: var(--insur-blue);
      border-bottom: 3px solid var(--insur-orange);
      box-shadow: 0 2px 12px rgba(0,0,0,0.18);
    }
    .nav-l { display: flex; align-items: center; gap: 16px; }
    .nav-logo { display: flex; align-items: center; gap: 0; }
    .nav-name {
      font-family: 'Lato', sans-serif;
      font-size: 17px; font-weight: 700; color: #ffffff; letter-spacing: 0.5px;
      text-transform: uppercase;
    }
    .nav-sep { width: 1px; height: 22px; background: rgba(255,255,255,0.25); }
    .nav-sub {
      font-family: 'Lato', sans-serif;
      font-size: 11px; color: rgba(255,255,255,0.65); letter-spacing: 1.5px;
      text-transform: uppercase; font-weight: 400;
    }
    .nav-r { display: flex; align-items: center; gap: 14px; }
    .nav-badge {
      font-family: 'Lato', sans-serif;
      font-size: 10px; color: rgba(255,255,255,0.70); letter-spacing: 1px;
      border: 1px solid rgba(255,255,255,0.25); padding: 4px 12px;
      border-radius: 3px; text-transform: uppercase; font-weight: 700;
    }
    .api-ind { display: flex; align-items: center; gap: 6px; }
    .api-dot { width: 7px; height: 7px; border-radius: 50%; background: rgba(255,255,255,0.35); }
    .api-dot.on { background: #69c875; box-shadow: 0 0 6px #69c875; }
    .api-lbl {
      font-family: 'Lato', sans-serif;
      font-size: 11px; color: rgba(255,255,255,0.70); letter-spacing: 0.5px;
    }

    /* Hide Streamlit default header/toolbar/footer to reclaim vertical space */
    [data-testid="stHeader"],
    [data-testid="stToolbar"],
    #MainMenu,
    footer,
    header { display: none !important; }

    /* Main container */
    .block-container {
      padding-top: calc(var(--nav-h) + 8px) !important;
      padding-bottom: 12px !important;
      max-width: 1180px !important;
    }

    /* Viewport-height responsive scaling */
    @media (max-height: 900px) {
      .block-container {
        padding-top: calc(var(--nav-h) + 4px) !important;
        padding-bottom: 6px !important;
      }
    }
    @media (max-height: 750px) {
      .block-container {
        padding-top: calc(var(--nav-h) + 2px) !important;
        padding-bottom: 4px !important;
      }
    }

    /* Sidebar */
    [data-testid="stSidebar"] {
      background: var(--insur-blue) !important;
      border-right: none !important;
    }
    [data-testid="stSidebar"] * { color: rgba(255,255,255,0.88) !important; }
    [data-testid="stSidebar"] .stSlider > div > div > div { background: var(--insur-orange) !important; }
    [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {
      color: #ffffff !important; font-family: 'Lato', sans-serif !important;
      font-weight: 900 !important; text-transform: uppercase !important; letter-spacing: 1px !important;
    }
    [data-testid="stSidebar"] input {
      background: rgba(255,255,255,0.10) !important;
      border-color: rgba(255,255,255,0.20) !important;
      color: #ffffff !important;
    }
    [data-testid="stSidebar"] label {
      color: rgba(255,255,255,0.60) !important; font-size: 11px !important;
      letter-spacing: 1px !important; text-transform: uppercase !important;
    }
    [data-testid="stSidebar"] .stButton > button {
      background: rgba(255,255,255,0.12) !important;
      border-color: rgba(255,255,255,0.25) !important;
      color: #ffffff !important;
    }

    /* Hero */
    .hero-eyebrow {
      font-family: 'Lato', sans-serif; font-size: 11px; letter-spacing: 2.5px;
      color: var(--insur-orange); text-transform: uppercase; font-weight: 700; margin-bottom: 12px;
    }
    .hero-title {
      font-family: 'Lato', sans-serif;
      font-size: clamp(36px, 5vw, 58px);
      font-weight: 900; line-height: 1.05; color: var(--insur-blue); margin-bottom: 16px;
    }
    .hero-title .gold { color: var(--insur-orange); }
    .hero-title .italic { font-style: italic; }
    .hero-sub {
      font-size: 16px; line-height: 1.70; color: var(--muted);
      max-width: 680px; margin-bottom: 28px; font-weight: 400;
    }

    /* Section headers */
    .sec-header {
      display: flex; align-items: baseline; gap: 12px;
      margin: 28px 0 14px; padding-bottom: 10px;
      border-bottom: 2px solid var(--insur-blue);
    }
    .sec-header-title {
      font-family: 'Lato', sans-serif; font-size: 18px; font-weight: 900;
      color: var(--insur-blue); flex: 1; text-transform: uppercase; letter-spacing: 0.5px;
    }
    .sec-header-label {
      font-family: 'Lato', sans-serif; font-size: 10px; letter-spacing: 1.5px;
      color: var(--muted2); text-transform: uppercase; font-weight: 700;
    }

    /* Cards */
    .card {
      background: var(--surface); border: 1px solid var(--line);
      border-radius: 6px; padding: 20px 22px; margin-bottom: 12px;
      transition: box-shadow 0.2s; box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    }
    .card:hover { box-shadow: 0 4px 16px rgba(0,65,125,0.10); }
    .card-gold { border-left: 4px solid var(--insur-orange); }
    .card-ok { border-left: 4px solid var(--ok); }
    .card-danger { border-left: 4px solid var(--danger); }
    .card-neutral { border-left: 4px solid var(--muted2); }
    .card-title {
      font-size: 14px; font-weight: 700; color: var(--insur-blue); margin-bottom: 6px;
      text-transform: uppercase; letter-spacing: 0.3px;
    }
    .card-body { font-size: 13px; line-height: 1.65; color: var(--text); }
    .card-meta { font-size: 11px; color: var(--muted2); margin-top: 8px; }

    /* KPI grid */
    .kpi-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin: 0 0 24px; }
    .kpi-grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin: 0 0 24px; }
    .kpi {
      background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
      padding: 18px 20px 16px; position: relative; overflow: hidden;
      box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    }
    .kpi::before {
      content: ''; position: absolute; top: 0; left: 0; right: 0; height: 4px;
      background: var(--insur-blue);
    }
    .kpi-label {
      font-family: 'Lato', sans-serif; font-size: 10px; letter-spacing: 1.5px;
      color: var(--muted2); text-transform: uppercase; margin-bottom: 10px; font-weight: 700;
    }
    .kpi-value {
      font-family: 'Lato', sans-serif; font-size: 36px; font-weight: 900;
      color: var(--insur-blue); line-height: 1; margin-bottom: 6px;
    }
    .kpi-value.danger { color: var(--danger); }
    .kpi-value.gold { color: var(--insur-orange); }
    .kpi-value.ok { color: var(--ok); }
    .kpi-hint { font-size: 12px; color: var(--muted); }

    /* Score badge */
    .score-wrap { display: flex; align-items: center; gap: 14px; margin: 8px 0 20px; }
    .score-ring {
      width: 80px; height: 80px; border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      font-family: 'Lato', sans-serif; font-size: 26px; font-weight: 900; border: 3px solid;
    }
    .score-ring.ok { border-color: var(--ok); color: var(--ok); background: var(--ok-pale); }
    .score-ring.gold { border-color: var(--insur-orange); color: var(--insur-orange); background: var(--warn-pale); }
    .score-ring.danger { border-color: var(--danger); color: var(--danger); background: var(--danger-pale); }
    .score-meta { flex: 1; }
    .score-meta-label {
      font-size: 10px; letter-spacing: 1.5px; color: var(--muted2);
      text-transform: uppercase; font-weight: 700;
    }
    .score-meta-title { font-size: 18px; font-weight: 700; color: var(--insur-blue); margin: 4px 0; }
    .score-meta-body { font-size: 13px; color: var(--muted); }

    /* Progress bar */
    .progress-wrap { margin: 6px 0 10px; }
    .progress-label {
      display: flex; justify-content: space-between; font-size: 11px;
      color: var(--muted); margin-bottom: 5px;
    }
    .progress-track { height: 6px; border-radius: 3px; background: var(--insur-grey-light); overflow: hidden; }
    .progress-fill { height: 100%; border-radius: 3px; background: var(--insur-blue); }
    .progress-fill.ok { background: var(--ok); }
    .progress-fill.danger { background: var(--danger); }

    /* Chips */
    .chip {
      display: inline-block; font-family: 'Lato', sans-serif;
      font-size: 10px; letter-spacing: 0.8px; padding: 3px 9px;
      border-radius: 3px; border: 1px solid; vertical-align: middle;
      text-transform: uppercase; font-weight: 700;
    }
    .chip-high { color: var(--danger); border-color: rgba(198,40,40,.30); background: var(--danger-pale); }
    .chip-med { color: var(--warn); border-color: rgba(230,81,0,.30); background: var(--warn-pale); }
    .chip-low { color: var(--ok); border-color: rgba(46,125,50,.25); background: var(--ok-pale); }
    .chip-blue { color: var(--insur-blue); border-color: var(--insur-blue-mid); background: var(--insur-blue-light); }
    .chip-neutral { color: var(--muted); border-color: var(--line); background: var(--surface-warm); }

    /* Decision row */
    .dec-row {
      background: var(--surface); border: 1px solid var(--line);
      border-radius: 6px; padding: 14px 18px; margin-bottom: 10px;
      display: flex; align-items: flex-start; gap: 14px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }
    .dec-icon {
      width: 36px; height: 36px; border-radius: 6px;
      display: flex; align-items: center; justify-content: center;
      font-size: 16px; flex-shrink: 0; margin-top: 1px;
    }
    .dec-icon.alta { background: var(--danger-pale); }
    .dec-icon.media { background: var(--warn-pale); }
    .dec-icon.baja { background: var(--ok-pale); }
    .dec-content { flex: 1; }
    .dec-actor {
      font-size: 10px; color: var(--muted2); letter-spacing: 1px; margin-bottom: 3px;
      text-transform: uppercase; font-weight: 700;
    }
    .dec-action { font-size: 14px; font-weight: 700; color: var(--insur-blue); margin-bottom: 5px; }
    .dec-why { font-size: 12px; color: var(--text); line-height: 1.6; }

    /* Upload zone */
    .upload-zone {
      background: var(--surface); border: 2px dashed rgba(0,65,125,0.30);
      border-radius: 8px; padding: 28px 24px; text-align: center;
      transition: border-color 0.2s, background 0.2s;
    }
    .upload-zone:hover { border-color: var(--insur-blue); background: var(--insur-blue-light); }

    /* Info box */
    .info-box {
      background: var(--insur-blue-light); border: 1px solid var(--insur-blue-mid);
      border-left: 4px solid var(--insur-blue);
      border-radius: 6px; padding: 12px 16px; font-size: 13px; color: var(--text); margin-bottom: 16px;
    }
    .info-box strong { color: var(--insur-blue); }

    /* Run-id tag */
    .run-tag {
      background: var(--surface); border: 1px solid var(--line);
      border-radius: 4px; padding: 8px 14px; display: inline-flex; align-items: center; gap: 10px;
      margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }
    .run-tag-label {
      font-size: 10px; color: var(--muted2); letter-spacing: 1px;
      text-transform: uppercase; font-weight: 700;
    }
    .run-tag-value { font-size: 12px; color: var(--insur-blue); font-weight: 700; }

    /* Streamlit element overrides */
    div[data-testid="stMetric"] {
      background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
      padding: 14px 16px; box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    }
    div[data-testid="stMetric"] label {
      color: var(--muted2) !important; font-size: 11px !important;
      font-weight: 700 !important; text-transform: uppercase !important; letter-spacing: 1px !important;
    }
    div[data-testid="stMetric"] [data-testid="stMetricValue"] {
      color: var(--insur-blue) !important; font-family: 'Lato', sans-serif !important; font-weight: 900 !important;
    }

    .stButton > button {
      border-radius: 6px !important; font-weight: 700 !important; letter-spacing: 0.8px !important;
      border: 2px solid var(--insur-blue) !important;
      background: #ffffff !important; color: var(--insur-blue) !important;
      transition: all 0.18s !important; text-transform: uppercase !important; font-size: 12px !important;
    }
    .stButton > button:hover {
      background: var(--insur-blue) !important; color: #ffffff !important;
      box-shadow: 0 4px 12px rgba(0,65,125,0.22) !important;
    }
    .stButton > button[kind="primary"] {
      background: var(--insur-blue) !important; border-color: var(--insur-blue) !important;
      color: #ffffff !important; font-size: 14px !important; letter-spacing: 1.5px !important;
      box-shadow: 0 2px 8px rgba(0,65,125,0.28) !important;
    }
    .stButton > button[kind="primary"]:hover {
      background: #003268 !important; border-color: #003268 !important;
      color: #ffffff !important; box-shadow: 0 4px 16px rgba(0,65,125,0.38) !important;
    }
    .stButton > button:disabled {
      background: #e8edf4 !important; border-color: #c5d0de !important;
      color: #9aa8b8 !important; cursor: not-allowed !important;
    }
    .stDownloadButton > button {
      border-radius: 4px !important; border: 2px solid var(--insur-blue) !important;
      background: var(--surface) !important; color: var(--insur-blue) !important;
      font-weight: 700 !important; text-transform: uppercase !important;
    }
    .stDownloadButton > button:hover { background: var(--insur-blue) !important; color: #ffffff !important; }

    .stFileUploader > div { border-radius: 6px !important; border-color: rgba(0,65,125,0.30) !important; }
    .stFileUploader label { color: var(--insur-blue) !important; font-weight: 700 !important; }

    textarea[data-testid="stTextArea"] {
      background: var(--surface-warm) !important; color: var(--text) !important;
      border-color: var(--line) !important; border-radius: 4px !important;
      font-family: 'Lato', sans-serif !important; font-size: 13px !important;
    }

    .stExpander {
      border: 1px solid var(--line) !important; border-radius: 6px !important;
      background: var(--surface) !important;
    }
    .stExpander summary {
      font-weight: 700 !important; color: var(--insur-blue) !important;
      text-transform: uppercase !important; font-size: 12px !important; letter-spacing: 0.5px !important;
    }

    div[data-baseweb="select"] > div, .stTextInput input {
      border-color: var(--line) !important; border-radius: 4px !important;
      background: var(--surface) !important; color: var(--text) !important;
    }

    /* Table */
    .stDataFrame { border-radius: 6px !important; overflow: hidden; border: 1px solid var(--line) !important; }
    [data-testid="stDataFrame"] * { color: var(--text) !important; }

    /* Upload hero */
    .hero-wrap {
      text-align: center; padding: 18px 20px 10px;
    }
    .hero-brand {
      font-family: 'Lato', sans-serif; font-size: clamp(32px, 5vw, 56px);
      font-weight: 900; color: var(--insur-blue); letter-spacing: -2px;
      line-height: 1; margin-bottom: 4px;
    }
    .hero-brand em { color: var(--insur-orange); font-style: normal; }
    .hero-subtitle {
      font-size: clamp(11px, 1.6vw, 14px); font-weight: 700; letter-spacing: 4px;
      color: var(--insur-orange); text-transform: uppercase; margin-bottom: 10px;
    }
    .hero-desc {
      font-size: 13px; color: var(--muted); max-width: 600px;
      margin: 0 auto 14px; line-height: 1.55;
    }
    .hero-desc strong { color: var(--insur-blue); }
    .hero-cards {
      display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 14px;
    }
    .hero-cards .card { padding: 10px 14px; }
    .hero-cards .card-title { font-size: 11px; margin-bottom: 6px; }

    /* File uploader overrides – evita fondo negro de Streamlit */
    [data-testid="stFileUploader"],
    [data-testid="stFileUploader"] > div,
    [data-testid="stFileUploader"] > div > div,
    [data-testid="stFileUploader"] * {
      background-color: transparent !important;
    }
    [data-testid="stFileUploaderDropzone"],
    section[data-testid="stFileUploaderDropzone"],
    div[data-testid="stFileUploaderDropzone"] {
      background: #f0f4f9 !important;
      background-color: #f0f4f9 !important;
      border: 2px dashed rgba(0,65,125,0.28) !important;
      border-radius: 10px !important;
      padding: 20px !important;
      color: #555 !important;
    }
    [data-testid="stFileUploaderDropzone"] *,
    section[data-testid="stFileUploaderDropzone"] * {
      background-color: transparent !important;
      color: #555 !important;
    }
    [data-testid="stFileUploaderDropzone"] button,
    section[data-testid="stFileUploaderDropzone"] button {
      background: #00417d !important;
      background-color: #00417d !important;
      color: #ffffff !important;
      border: none !important;
      border-radius: 6px !important;
      font-weight: 700 !important;
      font-size: 12px !important;
      letter-spacing: 0.5px !important;
      padding: 8px 18px !important;
    }
    [data-testid="stFileUploaderDropzone"] button:hover,
    section[data-testid="stFileUploaderDropzone"] button:hover {
      background: #003268 !important;
      background-color: #003268 !important;
    }
    .stApp [data-testid="stFileUploaderDropzone"],
    .uploadedFileData, .uploadedFileName {
      background: #f0f4f9 !important;
      background-color: #f0f4f9 !important;
      color: #374151 !important;
    }

    .drop-shell {
      border: 1px solid var(--line); border-radius: 8px;
      padding: 18px; background: var(--surface); box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    }
    .det {
      margin-top: 14px; background: var(--insur-blue-light);
      border: 1px solid var(--insur-blue-mid); border-radius: 6px; padding: 16px;
    }
    .scan-row {
      display: flex; align-items: center; gap: 8px;
      font-family: 'Lato', sans-serif; font-size: 11px; color: var(--insur-blue);
      letter-spacing: 1px; margin-bottom: 10px; font-weight: 700;
    }
    .sdot { width: 7px; height: 7px; border-radius: 50%; background: var(--insur-blue); animation: bl 1s infinite; }
    @keyframes bl { 0%,100%{opacity:1} 50%{opacity:.25} }
    .type-chip {
      display: inline-flex; align-items: center; gap: 10px;
      background: var(--insur-blue-light); border: 1px solid var(--insur-blue-mid);
      border-radius: 6px; padding: 8px 12px;
    }
    .type-name { font-size: 14px; font-weight: 700; color: var(--insur-blue); }
    .type-conf { font-size: 11px; color: var(--ok); font-weight: 700; }
    .kws { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 6px; }
    .kw {
      font-size: 10px; padding: 3px 8px; border-radius: 3px; border: 1px solid var(--line);
      color: var(--muted); background: var(--surface-warm); font-weight: 700; letter-spacing: 0.5px;
    }
    .kw.h { background: var(--insur-blue-light); border-color: var(--insur-blue-mid); color: var(--insur-blue); }

    .types-lbl {
      font-size: 12px; color: var(--muted); margin: 28px 0 12px;
      font-weight: 700; text-transform: uppercase; letter-spacing: 1px;
    }
    .tgrid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; }
    .tc {
      background: var(--surface); border: 1px solid var(--line);
      border-radius: 10px; text-align: center; padding: 14px 8px 10px;
      transition: border-color 0.18s, box-shadow 0.18s, transform 0.14s;
      cursor: default;
    }
    .tc:hover {
      border-color: var(--insur-blue);
      box-shadow: 0 4px 14px rgba(0,65,125,0.13);
      transform: translateY(-2px);
    }
    .tci {
      display: flex; align-items: center; justify-content: center;
      width: 46px; height: 46px; margin: 0 auto 8px;
      background: rgba(0,65,125,0.07); border-radius: 12px;
    }
    .tci svg { width: 26px; height: 26px; }
    .tcn { font-size: 10px; color: var(--muted); line-height: 1.25; font-weight: 700; text-transform: uppercase; }

    /* ── Loading overlay ─────────────────────────────────────── */
    .ov-backdrop {
      position: fixed; inset: 0; z-index: 99999;
      background: rgba(10,20,40,0.55);
      backdrop-filter: blur(6px);
      -webkit-backdrop-filter: blur(6px);
      display: flex; align-items: center; justify-content: center;
    }
    .ov-modal {
      background: #ffffff;
      border-radius: 20px;
      padding: 44px 48px 36px;
      max-width: 580px; width: 92%;
      box-shadow: 0 32px 100px rgba(0,0,0,0.40), 0 0 0 1px rgba(0,65,125,0.10);
      text-align: center;
      animation: ov-in 0.25s cubic-bezier(.22,.68,0,1.2) both;
    }
    @keyframes ov-in {
      from { opacity:0; transform: scale(0.90) translateY(16px); }
      to   { opacity:1; transform: scale(1)    translateY(0);    }
    }

    /* Hexagon AI badge */
    .orq-wrap { display: flex; flex-direction: column; align-items: center; gap: 8px; margin-bottom: 28px; }
    .orq-hex {
      width: 82px; height: 82px; display: flex; align-items: center; justify-content: center;
      clip-path: polygon(50% 0%,100% 25%,100% 75%,50% 100%,0% 75%,0% 25%);
      background: linear-gradient(135deg, #00417d 0%, #0069c8 100%);
      font-size: 26px; font-weight: 900; color: #fff; letter-spacing: 1px;
      animation: orq-pulse 2.2s ease-in-out infinite;
    }
    @keyframes orq-pulse {
      0%,100% { box-shadow: 0 0 0 0 rgba(0,65,125,.35); }
      50%      { box-shadow: 0 0 0 18px rgba(0,65,125,0); }
    }
    .orq-label {
      font-size: 11px; color: var(--insur-blue); letter-spacing: 3px;
      text-transform: uppercase; font-weight: 700; margin-top: 4px;
    }
    .orq-msg { font-size: 14px; color: var(--muted); margin-top: 2px; }

    /* Agent cards inside overlay */
    .agents-grid {
      display: grid; grid-template-columns: repeat(3,1fr); gap: 12px; margin-bottom: 28px;
    }
    .ag-card {
      background: #f4f5f7; border: 1.5px solid rgba(149,152,154,0.30);
      border-radius: 10px; padding: 14px 10px; text-align: center;
      transition: border-color 0.2s, background 0.2s;
    }
    .ag-card.running {
      border-color: var(--insur-blue);
      background: rgba(0,65,125,0.07);
      animation: ag-blink 1.4s ease-in-out infinite;
    }
    @keyframes ag-blink {
      0%,100% { border-color: var(--insur-blue); }
      50%      { border-color: rgba(0,65,125,0.30); }
    }
    .ag-card.done {
      border-color: var(--ok); background: rgba(46,125,50,0.07);
    }
    .ag-name {
      font-size: 12px; font-weight: 700; color: var(--insur-blue); margin-bottom: 6px;
      text-transform: uppercase; letter-spacing: 0.5px;
    }
    .ag-dot {
      width: 8px; height: 8px; border-radius: 50%; margin: 0 auto 6px;
      background: rgba(149,152,154,0.40);
      transition: background 0.3s;
    }
    .ag-card.running .ag-dot { background: var(--insur-blue); animation: bl 0.9s infinite; }
    .ag-card.done    .ag-dot { background: var(--ok); }
    .ag-status {
      font-size: 10px; letter-spacing: 1px;
      text-transform: uppercase; font-weight: 700; color: var(--muted);
    }
    .ag-card.running .ag-status { color: var(--insur-blue); }
    .ag-card.done    .ag-status { color: var(--ok); }

    /* Progress bar */
    .prog-wrap { width: 100%; }
    .prog-bg {
      height: 6px; border-radius: 3px;
      background: rgba(149,152,154,0.20); overflow: hidden;
    }
    .prog-fill {
      height: 100%; width: 0%;
      background: linear-gradient(90deg, var(--insur-blue), #0069c8);
      border-radius: 3px;
      transition: width 0.5s cubic-bezier(.4,0,.2,1);
    }
    .prog-lbl {
      margin-top: 10px; font-size: 11px; color: var(--muted);
      letter-spacing: 1px; text-transform: uppercase; font-weight: 700;
    }
    .prog-pct {
      font-size: 28px; font-weight: 900; color: var(--insur-blue);
      margin-bottom: 6px; line-height: 1;
    }

    /* Results */
    .res-top {
      display: flex; align-items: flex-start; justify-content: space-between;
      gap: 24px; flex-wrap: wrap; margin-bottom: 24px;
    }
    .rec-badge {
      display: inline-flex; align-items: center; gap: 10px; padding: 8px 16px;
      border-radius: 4px; font-family: 'Lato', sans-serif; font-size: 11px;
      letter-spacing: 1px; margin-bottom: 12px; font-weight: 900; text-transform: uppercase;
    }
    .rec-badge.INVERTIR { background: var(--ok-pale); border: 2px solid var(--ok); color: var(--ok); }
    .rec-badge.CAUTELA { background: var(--warn-pale); border: 2px solid var(--warn); color: var(--warn); }
    .rec-badge.REVISAR { background: var(--danger-pale); border: 2px solid var(--danger); color: var(--danger); }
    .rec-badge.NOINVERTIR { background: var(--danger-pale); border: 2px solid var(--danger); color: var(--danger); }
    .res-h {
      font-family: 'Lato', sans-serif; font-size: clamp(26px,4vw,36px);
      font-weight: 900; line-height: 1.1; color: var(--insur-blue);
    }
    .res-meta { font-size: 13px; color: var(--muted); margin-top: 6px; }

    /* Score cards */
    .scores { display: grid; grid-template-columns: repeat(4,1fr); gap: 14px; margin-bottom: 24px; }
    .sc {
      background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
      padding: 16px; position: relative; overflow: hidden;
      box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    }
    .sc::after { content:''; position: absolute; top: 0; left: 0; right: 0; height: 4px; }
    .sc.gold::after { background: var(--insur-orange); }
    .sc.gr::after { background: var(--ok); }
    .sc.bl::after { background: var(--insur-blue); }
    .sc.re::after { background: var(--danger); }
    .sc-lbl {
      font-size: 10px; color: var(--muted2); text-transform: uppercase;
      letter-spacing: 1px; margin-bottom: 10px; font-weight: 700;
    }
    .sc-val {
      font-family: 'Lato', sans-serif; font-size: 38px; font-weight: 900;
      line-height: 1; margin-bottom: 4px;
    }
    .gold .sc-val { color: var(--insur-orange); }
    .gr .sc-val { color: var(--ok); }
    .bl .sc-val { color: var(--insur-blue); }
    .re .sc-val { color: var(--danger); }
    .sc-sub { font-size: 11px; color: var(--muted); }

    /* Panel */
    .panel {
      background: var(--surface); border: 1px solid var(--line); border-radius: 8px;
      padding: 22px; margin-bottom: 16px; box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    }
    .panel-h { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
    .panel-ico {
      width: 38px; height: 38px; border-radius: 6px;
      display: flex; align-items: center; justify-content: center; font-size: 14px;
      background: var(--insur-blue-light); color: var(--insur-blue);
    }
    .panel-title {
      font-size: 16px; font-weight: 900; color: var(--insur-blue);
      text-transform: uppercase; letter-spacing: 0.5px;
    }
    .panel-sub { font-size: 12px; color: var(--muted); margin-top: 1px; }
    .panel-badge {
      margin-left: auto; font-size: 10px; letter-spacing: 1px;
      border: 1px solid var(--insur-blue-mid); border-radius: 3px; padding: 4px 10px;
      color: var(--insur-blue); font-weight: 700; text-transform: uppercase;
    }

    /* Executive box */
    .exec-box {
      background: var(--insur-blue-light); border: 1px solid var(--insur-blue-mid);
      border-radius: 6px; padding: 18px 20px; margin-bottom: 12px;
    }
    .exec-label {
      font-size: 10px; letter-spacing: 2px; color: var(--insur-blue);
      text-transform: uppercase; margin-bottom: 10px; font-weight: 700;
    }
    .exec-text { font-size: 16px; line-height: 1.65; color: var(--text); font-weight: 400; }

    /* Risk grid */
    .risk-grid { display: grid; grid-template-columns: repeat(2,1fr); gap: 12px; }
    .risk-cell {
      background: var(--surface); border: 1px solid var(--line);
      border-radius: 10px; padding: 16px 18px; display: flex;
      align-items: flex-start; gap: 10px;
      transition: box-shadow 0.18s;
    }
    .risk-cell:hover { box-shadow: 0 4px 14px rgba(0,65,125,0.10); }
    .risk-lbl {
      font-size: 11px; color: var(--muted); margin-bottom: 3px;
      font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px;
    }
    .risk-val { font-size: 16px; font-weight: 900; letter-spacing: 0.3px; }
    .risk-val.LOW { color: var(--ok); }
    .risk-val.MED { color: var(--warn); }
    .risk-val.HIGH { color: var(--insur-orange); }
    .risk-val.CRIT { color: var(--danger); }

    /* Responsive */
    @media (max-width: 900px) {
      .kpi-grid { grid-template-columns: repeat(2, 1fr); }
      .kpi-grid-3 { grid-template-columns: 1fr; }
      nav.topbar { padding: 0 18px; }
      .nav-badge { display: none; }
      .scores { grid-template-columns: repeat(2, 1fr); }
      .tgrid { grid-template-columns: repeat(4, 1fr); }
      .tci { width: 38px; height: 38px; }
      .tci svg { width: 22px; height: 22px; }
      .hero-cards { grid-template-columns: 1fr; }
      .hero-brand { letter-spacing: -1px; }
      .risk-grid, .agents-grid { grid-template-columns: 1fr; }
    }
    </style>
    """,
    unsafe_allow_html=True,
  )


def top_nav() -> None:
  n8n_health = str(st.session_state.get("n8n_health", "unknown"))
  online = n8n_health == "online"
  api_cls = "api-dot on" if online else "api-dot"
  api_lbl = "n8n online" if online else "n8n offline"
  st.markdown(
    f"""
    <nav class="topbar">
      <div class="nav-l">
        <div class="nav-logo">
          <!-- 80 AÑOS badge -->
          <svg width="38" height="38" viewBox="0 0 38 38" fill="none" xmlns="http://www.w3.org/2000/svg" style="margin-right:6px">
            <circle cx="19" cy="19" r="18" fill="#E8720C" stroke="rgba(255,255,255,0.3)" stroke-width="1"/>
            <text x="19" y="17" text-anchor="middle" font-family="Lato,sans-serif" font-weight="900" font-size="13" fill="#ffffff">80</text>
            <text x="19" y="27" text-anchor="middle" font-family="Lato,sans-serif" font-weight="700" font-size="7.5" fill="#ffffff" letter-spacing="1">AÑOS</text>
          </svg>
          <!-- iS insur GRUPO mark -->
          <svg width="96" height="36" viewBox="0 0 96 36" fill="none" xmlns="http://www.w3.org/2000/svg">
            <!-- iS circle mark -->
            <circle cx="18" cy="18" r="16" fill="#E8720C" opacity="0.15"/>
            <circle cx="18" cy="18" r="16" stroke="#ffffff" stroke-width="1.5" fill="none"/>
            <text x="10" y="23" font-family="Lato,sans-serif" font-weight="900" font-size="14" fill="#ffffff">i</text>
            <text x="18" y="23" font-family="Lato,sans-serif" font-weight="700" font-size="13" fill="#E8720C">S</text>
            <!-- insur text -->
            <text x="40" y="20" font-family="Lato,sans-serif" font-weight="900" font-size="15" fill="#ffffff" letter-spacing="0.5">insur</text>
            <text x="40" y="31" font-family="Lato,sans-serif" font-weight="700" font-size="8" fill="rgba(255,255,255,0.65)" letter-spacing="2">GRUPO</text>
          </svg>
        </div>
        <div class="nav-sep"></div>
        <span class="nav-sub">Analisis Inteligente</span>
      </div>
      <div class="nav-r">
        <div class="api-ind">
          <div class="{api_cls}"></div>
          <span class="api-lbl">{api_lbl}</span>
        </div>
        <div class="nav-badge">Sistema Multi-Agente</div>
      </div>
    </nav>
    """,
    unsafe_allow_html=True,
  )


# n8n + local extraction helpers
def _normalize_text(value: str) -> str:
  ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
  return ascii_text.lower()


def _classify_document(local_text: str, file_name: str) -> Dict[str, Any]:
  base = _normalize_text(f"{file_name} {local_text}")
  rules = {
    "supplier_report": [
      "proveedor",
      "supplier",
      "contratista",
      "sla",
      "incidencia",
      "retraso",
      "dependencia",
    ],
    "valuation_report": [
      "tasacion",
      "valoracion",
      "valor de mercado",
      "metodo comparativo",
      "metodo residual",
    ],
    "legal_report": [
      "nota simple",
      "registro de la propiedad",
      "cargas",
      "hipoteca inscrita",
      "escritura",
      "titular",
    ],
    "market_report": [
      "informe de mercado",
      "oferta",
      "demanda",
      "precio m2",
      "benchmark",
      "absorcion",
    ],
    "investment_report": [
      "roi",
      "tir",
      "yield",
      "cap rate",
      "rentabilidad",
      "flujo de caja",
    ],
    "commercial_report": [
      "ventas",
      "lead",
      "captacion",
      "reserva",
      "comercializacion",
      "embudo",
    ],
  }

  best_type = "real_estate_generic"
  best_hits: List[str] = []
  for doc_type, keywords in rules.items():
    hits = [kw for kw in keywords if kw in base]
    if len(hits) > len(best_hits):
      best_hits = hits
      best_type = doc_type

  if not best_hits:
    return {"document_type": "real_estate_generic", "confidence": 0.58, "evidence_keywords": []}
  confidence = min(0.97, 0.62 + (0.06 * len(best_hits)))
  return {
    "document_type": best_type,
    "confidence": round(confidence, 3),
    "evidence_keywords": best_hits[:8],
  }


def extract_pdf_local(name: str, data: bytes, max_pages: int | None = None) -> Dict[str, Any]:
  min_required = 180
  reader = PdfReader(io.BytesIO(data))
  total_pages = len(reader.pages)
  use_pages = total_pages if max_pages is None else min(total_pages, max_pages)

  text_chunks: List[str] = []
  for page in reader.pages[:use_pages]:
    try:
      page_text = page.extract_text() or ""
    except Exception:
      page_text = ""
    text_chunks.append(page_text.strip())
  full_text = "\n".join(chunk for chunk in text_chunks if chunk).strip()

  detected = _classify_document(full_text, name)
  char_count = len(full_text)
  usable = char_count >= min_required

  return {
    "document_id": f"local-{int(time.time() * 1000)}",
    "extraction": {
      "full_text": full_text,
      "char_count": char_count,
      "page_count": total_pages,
      "processed_pages": use_pages,
      "has_tables": False,
      "table_count": 0,
      "tables": [],
      "detected": detected,
      "quality_status": "ok" if usable else "low_text",
      "min_chars_required": min_required,
      "usable_for_analysis": usable,
      "ocr_applied": False,
      "ocr_engine": None,
      "ocr_error": None,
      "extraction_engine": "frontend_local_pypdf",
    },
  }


def extract_pdf_local_quick(name: str, data: bytes) -> Dict[str, Any]:
  return extract_pdf_local(name=name, data=data, max_pages=6)


def _request_with_retry(method: str, url: str, attempts: int = 3, **kwargs) -> requests.Response:
  last_exc: Exception | None = None
  for attempt in range(1, attempts + 1):
    try:
      return SESSION.request(method, url, **kwargs)
    except RequestsConnectionError as exc:
      last_exc = exc
      if attempt < attempts:
        time.sleep(0.8 * attempt)
        continue
      raise RuntimeError(
        "No se pudo conectar con el servicio remoto. Verifica la URL configurada."
      ) from exc
    except RequestException as exc:
      last_exc = exc
      if attempt < attempts:
        time.sleep(0.4 * attempt)
        continue
      raise RuntimeError(f"Fallo de red: {exc}") from exc
  raise RuntimeError(f"Fallo inesperado de red: {last_exc}")


def parse_response(response: requests.Response) -> Dict[str, Any]:
  try:
    payload = response.json()
  except Exception:
    payload = {"code": "invalid_response", "message": response.text}
  if response.status_code >= 400:
    raise RuntimeError(f"HTTP {response.status_code}: {json.dumps(payload, ensure_ascii=False)}")
  return payload


def api_post_n8n(webhook_url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
  if not webhook_url.strip():
    raise RuntimeError("N8N_WEBHOOK_URL no configurado.")
  response = _request_with_retry("POST", webhook_url.strip(), json=payload, timeout=240, attempts=2)
  raw = parse_response(response)
  return _unwrap_n8n_payload(raw)


def _unwrap_n8n_payload(raw: Any) -> Dict[str, Any]:
  if isinstance(raw, list):
    if len(raw) == 1 and isinstance(raw[0], dict):
      return raw[0]
    return {"items": raw}
  if not isinstance(raw, dict):
    return {"raw": raw}

  for key in ("data", "result", "payload", "output"):
    nested = raw.get(key)
    if isinstance(nested, dict):
      has_local = {"normalized", "summary", "decisions"}.issubset(set(nested.keys()))
      has_multi_agent = "informe_ejecutivo" in nested
      has_new_format = isinstance(nested.get("model_outputs"), dict) and bool(nested.get("model_outputs"))
      if has_local or has_multi_agent or has_new_format:
        return nested
  return raw


def _is_new_webhook_format(payload: Dict[str, Any]) -> bool:
  """Detect the new n8n webhook format.
  Signal A: model_outputs dict presente y no vacio.
  Signal B: summary dict con campos de metricas (score/risk_status) + traceability (sin informe_ejecutivo).
  Ambos casos se adaptan via _adapt_new_webhook_format."""
  if isinstance(payload.get("model_outputs"), dict) and bool(payload.get("model_outputs")):
    return True
  _s = payload.get("summary")
  if isinstance(_s, dict) and ("score" in _s or "risk_status" in _s or "score_label" in _s):
    if "informe_ejecutivo" not in payload:
      return True
  return False


def _extract_number_from_text(text: str) -> float | None:
  if not text:
    return None
  m = re.search(r"[-+]?\d[\d\.\,]*", text)
  if not m:
    return None
  token = m.group(0).strip()
  if "." in token and "," in token:
    token = token.replace(".", "").replace(",", ".")
  elif "," in token:
    token = token.replace(",", ".")
  try:
    return float(token)
  except ValueError:
    return None


def _token_to_float(token: str) -> float | None:
  raw = str(token or "").strip()
  if not raw:
    return None
  clean = re.sub(r"[^0-9,.\-+]", "", raw)
  if not clean:
    return None

  if clean.count(".") > 1 and "," not in clean:
    clean = clean.replace(".", "")
  elif clean.count(".") == 1 and "," not in clean:
    left, right = clean.split(".", 1)
    if len(right) == 3 and left.lstrip("+-").isdigit():
      clean = left + right
  elif clean.count(",") > 1 and "." not in clean:
    clean = clean.replace(",", "")
  elif "." in clean and "," in clean:
    if clean.rfind(",") > clean.rfind("."):
      clean = clean.replace(".", "").replace(",", ".")
    else:
      clean = clean.replace(",", "")
  elif "," in clean:
    last = clean.rsplit(",", 1)[-1]
    if len(last) <= 2:
      clean = clean.replace(",", ".")
    else:
      clean = clean.replace(",", "")

  try:
    return float(clean)
  except ValueError:
    return None


def _extract_number_after_phrase(text: str, phrase: str, window: int = 140) -> float | None:
  src = str(text or "")
  needle = str(phrase or "")
  if not src or not needle:
    return None
  pos = 0
  while True:
    idx = src.find(needle, pos)
    if idx < 0:
      return None
    seg = src[idx + len(needle): idx + len(needle) + window]
    m = re.search(r"[-+]?\d[\d\.,]*", seg)
    if m:
      value = _token_to_float(m.group(0))
      if value is not None:
        return value
    pos = idx + len(needle)


def _normalize_for_matching(text: str) -> str:
  base = str(text or "")
  # Normaliza variantes frecuentes en textos de PDF/JSON (m², separadores, etc.).
  base = base.replace("²", "2").replace("³", "3").replace("€/m²", "eur/m2").replace("€/m2", "eur/m2")
  normalized = unicodedata.normalize("NFD", base)
  normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
  return normalized.lower()


def _extract_operations_kpis_from_text(exec_text: str, informe: Dict[str, Any]) -> Dict[str, Any]:
  txt = str(exec_text or "")
  low = _normalize_for_matching(txt)

  def _match(pattern: str) -> float | None:
    m = re.search(pattern, low, flags=re.IGNORECASE)
    if not m:
      return None
    return _token_to_float(m.group(1))

  total_ops = _match(r"(\d{1,5})\s+operaciones")
  avg_price = (
    _match(r"precio medio(?: de venta)?(?: por operacion| unitario)?[^0-9]{0,60}(?:€\s*)?([\d\.,]+)")
    or _match(r"precio medio[^0-9]{0,80}(?:€\s*)?([\d\.,]+)")
    or _match(r"ticket medio(?: ponderado)?[^0-9]{0,40}(?:€\s*)?([\d\.,]+)")
    or _extract_number_after_phrase(low, "precio medio de venta por operacion")
    or _extract_number_after_phrase(low, "precio medio de venta")
    or _extract_number_after_phrase(low, "precio medio")
    or _extract_number_after_phrase(low, "ticket medio")
  )
  avg_surface = (
    _match(r"superficie media[^0-9]{0,20}([\d\.,]+)\s*m")
    or _match(r"superficie media[^0-9]{0,30}([\d\.,]+)")
    or _match(r"superficie[^0-9]{0,30}([\d\.,]+)\s*m")
    or _extract_number_after_phrase(low, "superficie media")
  )
  avg_m2 = (
    _match(r"precio medio por metro cuadrado[^0-9]{0,30}([\d\.,]+)")
    or _match(r"precio medio por m2[^0-9]{0,20}([\d\.,]+)")
    or _match(r"precios? medios? por m2[^0-9]{0,20}(?:€\s*)?([\d\.,]+)")
    or _match(r"precios? medios? por m[^0-9]{0,20}(?:€\s*)?([\d\.,]+)")
    or _match(r"([\d\.,]+)\s*(?:eur/m2|€/m2|/m2)")
    or _extract_number_after_phrase(low, "precio medio por m2")
    or _extract_number_after_phrase(low, "precio medio por metro cuadrado")
    or _extract_number_after_phrase(low, "precios medios por m2")
  )
  margin_pct = _match(r"margen medio[^0-9]{0,20}([\d\.,]+)\s*%")

  vol_million = (
    _match(r"volumen total(?: de operaciones)?[^0-9]{0,60}([\d\.,]+)\s*mill")
    or _match(r"volumen financiero total[^0-9]{0,40}([\d\.,]+)\s*mill")
  )
  vol_eur = (
    _match(r"volumen total(?: de operaciones)?[^0-9]{0,60}(?:€\s*)?([\d\.,]+)")
    or _match(r"volumen financiero total[^0-9]{0,40}(?:€\s*)?([\d\.,]+)")
    or _extract_number_after_phrase(low, "volumen total de operaciones")
    or _extract_number_after_phrase(low, "volumen total")
    or _extract_number_after_phrase(low, "volumen financiero total")
  )
  total_volume = None
  if vol_million is not None:
    total_volume = vol_million * 1_000_000
  elif vol_eur is not None:
    total_volume = vol_eur

  closed = (
    _match(r"(\d{1,5})\s+operaciones?\s+cerrad")
    or _match(r"cerrad[ao]s?\s*\((\d{1,5})\s+operaciones?")
  )
  escritura = (
    _match(r"(\d{1,5})\s+(?:operaciones?\s+)?en\s+escritura")
    or _match(r"en\s+escritura\s*\((\d{1,5})\s+operaciones?")
  )
  reserved = (
    _match(r"(\d{1,5})\s+operaciones?\s+reservad")
    or _match(r"reservad[ao]s?\s*\((\d{1,5})\s+operaciones?")
  )

  shared_closed_escritura = _match(r"cerrad[ao]s?[^\n]{0,80}en\s+escritura\s*\((\d{1,5})\s+cada\s+una\)")
  if shared_closed_escritura is not None:
    if closed is None:
      closed = shared_closed_escritura
    if escritura is None:
      escritura = shared_closed_escritura

  if total_ops is None and all(v is not None for v in [closed, escritura, reserved]):
    total_ops = (closed or 0) + (escritura or 0) + (reserved or 0)

  sell_through = None
  if total_ops and closed is not None and total_ops > 0:
    sell_through = max(0.0, min(1.0, (closed / total_ops)))

  conversion = None
  if total_ops and (closed is not None or escritura is not None) and total_ops > 0:
    c = (closed or 0.0) + (escritura or 0.0)
    conversion = max(0.0, min(1.0, c / total_ops))

  cancellation = 0.0
  warn_count = int(_safe_float(informe.get("alertas_detectadas"), 0))
  if warn_count >= 80:
    cancellation = 0.22
  elif warn_count >= 30:
    cancellation = 0.14
  elif warn_count >= 10:
    cancellation = 0.08

  trend = "flat"
  if any(w in low for w in ["decrec", "caida", "descenso"]):
    trend = "down"
  elif any(w in low for w in ["crec", "aument", "alza", "lideran"]):
    trend = "up"

  kpis = {
    "kpi_mode": "operaciones",
    "trend": trend,
    "conversion_rate": _safe_float(conversion, 0.0),
    "visit_to_reservation_rate": _safe_float(conversion, 0.0),
    "cancellation_rate": _safe_float(cancellation, 0.0),
    "sell_through_rate": _safe_float(sell_through, 0.0),
    "operations_total": _safe_float(total_ops, 0.0),
    "volume_total_eur": _safe_float(total_volume, 0.0),
    "avg_price_eur": _safe_float(avg_price, 0.0),
    "avg_surface_m2": _safe_float(avg_surface, 0.0),
    "avg_price_m2_eur": _safe_float(avg_m2, 0.0),
    "avg_margin_pct": _safe_float(margin_pct, 0.0),
  }

  series: List[Dict[str, Any]] = []
  if closed is not None:
    series.append({"label": "Cerradas", "units_sold": int(closed)})
  if escritura is not None:
    series.append({"label": "En escritura", "units_sold": int(escritura)})
  if reserved is not None:
    series.append({"label": "Reservadas", "units_sold": int(reserved)})

  return {"kpis": kpis, "series": series}


def _extract_client_kpis_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
  preds = payload.get("predictions")
  if not isinstance(preds, list):
    return {"kpis": {}, "series": []}

  rows = [p for p in preds if isinstance(p, dict)]
  if not rows:
    return {"kpis": {}, "series": []}

  churn_vals: List[float] = []
  for row in rows:
    v = _safe_float(row.get("churn_score"), None)  # type: ignore[arg-type]
    if v is None:
      continue
    churn_vals.append(max(0.0, min(1.0, float(v))))

  if not churn_vals:
    return {"kpis": {}, "series": []}

  total = len(churn_vals)
  avg_churn = sum(churn_vals) / max(total, 1)
  high = sum(1 for x in churn_vals if x >= 0.70)
  med = sum(1 for x in churn_vals if 0.40 <= x < 0.70)
  low = sum(1 for x in churn_vals if x < 0.40)
  retention = max(0.0, min(1.0, 1.0 - avg_churn))
  trend = "down" if avg_churn >= 0.55 else "flat" if avg_churn >= 0.35 else "up"

  kpis = {
    "kpi_mode": "clientes",
    "trend": trend,
    "total_clients": total,
    "avg_churn_score": round(avg_churn, 4),
    "retention_rate": round(retention, 4),
    "high_risk_clients": high,
    "medium_risk_clients": med,
    "low_risk_clients": low,
    # Compatibilidad con bloque comercial existente
    "conversion_rate": round(retention, 4),
    "visit_to_reservation_rate": round(retention, 4),
    "cancellation_rate": round(avg_churn, 4),
    "sell_through_rate": round(low / max(total, 1), 4),
  }

  series = [
    {"label": "Riesgo alto", "units_sold": high, "bucket": "HIGH"},
    {"label": "Riesgo medio", "units_sold": med, "bucket": "MED"},
    {"label": "Riesgo bajo", "units_sold": low, "bucket": "LOW"},
  ]
  return {"kpis": kpis, "series": series}


def _extract_client_kpis_from_text(exec_text: str, informe: Dict[str, Any]) -> Dict[str, Any]:
  text = str(exec_text or "")
  low = _normalize_for_matching(text)

  def _match(pattern: str) -> float | None:
    m = re.search(pattern, low, flags=re.IGNORECASE)
    if not m:
      return None
    return _token_to_float(m.group(1))

  total_clients = (
    _match(r"operaciones?\s+realizadas?\s+por\s+(\d{1,6})\s+clientes")
    or _match(r"base de\s+(\d{1,6})\s+clientes")
    or _match(r"se examinan un total de\s+(\d{1,6})\s+clientes")
    or _match(r"total(?: de)?\s+(\d{1,6})\s+clientes")
  )
  operations_total = _match(r"total de\s+(\d{1,8})\s+operaciones") or _match(r"(\d{1,8})\s+operaciones")
  volume_total_m = (
    _match(r"volumen total(?: gestionado| de negocio)?[^0-9]{0,45}([\d\.,]+)\s+mill")
    or _match(r"volumen de negocio(?: analizado)?[^0-9]{0,45}([\d\.,]+)\s+mill")
  )
  volume_total = _match(r"volumen total(?: de negocio| gestionado)?[^0-9]{0,45}([\d\.,]+)\s*(?:eu|euro)")
  if volume_total_m is not None:
    volume_total = volume_total_m * 1_000_000
  avg_ops_client = _match(r"promedio(?: aproximado)? de\s+([\d\.,]+)\s+operaciones?\s+por\s+cliente")

  active = _match(r"activos?\s*\((\d{1,6})\)") or _match(r"(\d{1,6})\s+activos?")
  inactive = _match(r"inactivos?\s*\((\d{1,6})\)") or _match(r"(\d{1,6})\s+inactivos?")
  others = (
    _match(r"otros(?:\s+estados)?\s*\((\d{1,6})\)")
    or _match(r"(\d{1,6})\s+en\s+otros(?:\s+estados)?")
    or _match(r"(\d{1,6})\s+clasificados?\s+en\s+otras")
  )

  rating_b = _match(r"(\d{1,3}(?:[.,]\d+)?)%\s+de\s+los\s+clientes?\s+obtiene?\s+una\s+calificaci[oó]n\s+b")
  rating_d = _match(r"(\d{1,3}(?:[.,]\d+)?)%\s+con\s+d")
  rating_c = _match(r"(\d{1,3}(?:[.,]\d+)?)%\s+con\s+c")
  rating_a = _match(r"(\d{1,3}(?:[.,]\d+)?)%\s+con\s+a")

  rating_b_count = _match(r"ratings?\s+b\s*\((\d{1,6})\s+clientes?\)")
  rating_d_count = _match(r"ratings?.*?\sd\s*\((\d{1,6})\s+clientes?\)") or _match(r"\sy\s+d\s*\((\d{1,6})\s+clientes?\)")
  rating_c_count = _match(r"ratings?.*?\sc\s*\((\d{1,6})\s+clientes?\)")
  rating_a_count = _match(r"ratings?.*?\sa\s*\((\d{1,6})\s+clientes?\)")
  if rating_b is not None:
    rating_b /= 100.0
  if rating_c is not None:
    rating_c /= 100.0
  if rating_d is not None:
    rating_d /= 100.0
  if rating_a is not None:
    rating_a /= 100.0

  if total_clients is None and all(v is not None for v in [active, inactive, others]):
    total_clients = (active or 0) + (inactive or 0) + (others or 0)

  total = int(_safe_float(total_clients, 0.0))
  if total <= 0 and any(v is not None for v in [rating_b_count, rating_c_count, rating_d_count, rating_a_count]):
    total = int(
      _safe_float(rating_b_count, 0.0)
      + _safe_float(rating_c_count, 0.0)
      + _safe_float(rating_d_count, 0.0)
      + _safe_float(rating_a_count, 0.0)
    )
  if total <= 0:
    return {"kpis": {}, "series": []}

  if rating_b is None and rating_b_count is not None:
    rating_b = _safe_float(rating_b_count, 0.0) / max(total, 1)
  if rating_c is None and rating_c_count is not None:
    rating_c = _safe_float(rating_c_count, 0.0) / max(total, 1)
  if rating_d is None and rating_d_count is not None:
    rating_d = _safe_float(rating_d_count, 0.0) / max(total, 1)
  if rating_a is None and rating_a_count is not None:
    rating_a = _safe_float(rating_a_count, 0.0) / max(total, 1)

  if _safe_float(avg_ops_client, 0.0) <= 0 and _safe_float(operations_total, 0.0) > 0:
    avg_ops_client = _safe_float(operations_total, 0.0) / max(total, 1)

  inactive_ratio = max(0.0, min(1.0, _safe_float(inactive, 0.0) / max(total, 1)))
  rating_d_ratio = max(0.0, min(1.0, _safe_float(rating_d, 0.25)))
  avg_churn = max(0.08, min(0.95, 0.18 + 0.62 * inactive_ratio + 0.36 * rating_d_ratio))
  retention = max(0.0, min(1.0, 1.0 - avg_churn))

  high = int(round(total * max(0.10, min(0.55, 0.12 + rating_d_ratio * 0.55))))
  med = int(round(total * max(0.15, min(0.65, 0.32 + inactive_ratio * 0.25))))
  if high + med > total:
    med = max(0, total - high)
  low_clients = max(0, total - high - med)

  trend = "flat"
  if "no se detectaron inconsistencias" in low or "nivel alto de confiabilidad" in low:
    trend = "up"
  elif any(w in low for w in ["riesgo", "mitigar", "impactos financieros"]):
    trend = "flat"

  cancellation = min(0.60, max(0.03, avg_churn * 0.55))
  sell_through = max(0.0, min(1.0, low_clients / max(total, 1)))

  kpis = {
    "kpi_mode": "clientes",
    "trend": trend,
    "total_clients": total,
    "operations_total": _safe_float(operations_total, 0.0),
    "avg_ops_per_client": _safe_float(avg_ops_client, 0.0),
    "volume_total_eur": _safe_float(volume_total, 0.0),
    "avg_churn_score": round(avg_churn, 4),
    "retention_rate": round(retention, 4),
    "high_risk_clients": high,
    "medium_risk_clients": med,
    "low_risk_clients": low_clients,
    "rating_b_ratio": _safe_float(rating_b, 0.0),
    "rating_c_ratio": _safe_float(rating_c, 0.0),
    "rating_d_ratio": _safe_float(rating_d, 0.0),
    "rating_a_ratio": _safe_float(rating_a, 0.0),
    # Compatibilidad con bloque comercial
    "conversion_rate": round(retention, 4),
    "visit_to_reservation_rate": round(retention, 4),
    "cancellation_rate": round(cancellation, 4),
    "sell_through_rate": round(sell_through, 4),
  }

  series = [
    {"label": "Riesgo alto", "units_sold": high, "bucket": "HIGH"},
    {"label": "Riesgo medio", "units_sold": med, "bucket": "MED"},
    {"label": "Riesgo bajo", "units_sold": low_clients, "bucket": "LOW"},
  ]
  return {"kpis": kpis, "series": series}


def _extract_sections_from_exec_text(text: str) -> Dict[str, List[str]]:
  sections: Dict[str, List[str]] = {"header": [], "resumen": [], "hallazgos": [], "riesgos": [], "implicaciones": [], "recomendaciones": []}
  current = "header"
  for raw in text.splitlines():
    line = str(raw or "").strip()
    if not line:
      continue
    title_match = re.match(r"^\s*(\d+)\)\s*(.+)$", line)
    if title_match:
      title = title_match.group(2).lower()
      if "resumen" in title:
        current = "resumen"
      elif "hallaz" in title:
        current = "hallazgos"
      elif "riesg" in title or "calidad" in title:
        current = "riesgos"
      elif "implic" in title:
        current = "implicaciones"
      elif "recomend" in title:
        current = "recomendaciones"
      else:
        current = "resumen"
      continue
    sections.setdefault(current, []).append(line)
  return sections


def _extract_bullets(lines: List[str]) -> List[str]:
  out: List[str] = []
  has_explicit_bullets = any(bool(re.match(r"^\s*[-*•]\s+", str(line or ""))) for line in lines)
  for line in lines:
    raw = str(line or "").strip()
    if has_explicit_bullets and not re.match(r"^\s*[-*•]\s+", raw):
      continue
    cleaned = re.sub(r"^\s*[-*•]\s*", "", raw)
    if cleaned and cleaned not in out:
      out.append(cleaned)
  return out


def _infer_rec_and_score(exec_text: str, decisions_count: int, alerts_count: int) -> tuple[str, int]:
  txt = (exec_text or "").lower()
  score = 64

  score_match = re.search(r"(\d{1,3})\s*/\s*100", txt)
  if score_match:
    score = int(_safe_float(score_match.group(1), 64))

  warn_match = re.search(r"(\d+)\s+(advertencias|alertas|inconsistencias)", txt)
  warn_count = int(_safe_float(warn_match.group(1), 0)) if warn_match else alerts_count
  if warn_count >= 80:
    score -= 18
  elif warn_count >= 30:
    score -= 10
  elif warn_count >= 10:
    score -= 5

  if "riesgo alto" in txt or "sesgar" in txt:
    score -= 6
  if "margen medio" in txt or "rentabilidad" in txt:
    score += 4
  if decisions_count >= 5:
    score -= 3

  score = max(10, min(96, score))
  if score >= 75:
    rec = "INVERTIR"
  elif score >= 60:
    rec = "INVERTIR CON CAUTELA"
  elif score >= 45:
    rec = "REVISAR"
  else:
    rec = "NO INVERTIR"
  return rec, int(score)


def _coerce_n8n_informe(payload: Dict[str, Any]) -> Dict[str, Any]:
  raw = payload.get("informe_ejecutivo")
  if isinstance(raw, dict):
    return raw

  if isinstance(raw, str):
    exec_text = raw.strip()
  else:
    exec_text = ""
  if not exec_text:
    return {}

  sections = _extract_sections_from_exec_text(exec_text)
  rec_bullets = _extract_bullets(sections.get("recomendaciones", []))
  risk_bullets = _extract_bullets(sections.get("riesgos", []))
  hallazgos = _extract_bullets(sections.get("hallazgos", []))

  decisions: List[Dict[str, Any]] = []
  for item in rec_bullets[:8]:
    low = item.lower()
    urg = "MEDIA"
    if any(k in low for k in ["prior", "urg", "correg", "revis", "control", "mitig"]):
      urg = "ALTA"
    decisions.append(
      {
        "urgencia": urg,
        "titulo": item[:160],
        "descripcion": item,
        "impacto": (risk_bullets[0] if risk_bullets else ""),
        "confianza": 84 if urg == "ALTA" else 74,
      }
    )

  if not decisions:
    decisions.append(
      {
        "urgencia": "MEDIA",
        "titulo": "Revisar hallazgos del informe y definir plan de accion",
        "descripcion": "No se detectaron decisiones estructuradas en el payload de n8n, se recomienda revision manual.",
        "impacto": "",
        "confianza": 60,
      }
    )

  alerts_count = len(risk_bullets)
  warn_match = re.search(r"(\d+)\s+(advertencias|alertas|inconsistencias)", exec_text.lower())
  if warn_match:
    alerts_count = int(_safe_float(warn_match.group(1), alerts_count))

  rec, score = _infer_rec_and_score(exec_text, decisions_count=len(decisions), alerts_count=alerts_count)

  precio_riesgo = "MEDIO"
  if "precio por m" in exec_text.lower() or "precio/m" in exec_text.lower():
    precio_riesgo = "ALTO" if alerts_count >= 30 else "MEDIO"
  riesgo_fin = "ALTO" if alerts_count >= 30 else "MEDIO" if alerts_count >= 8 else "BAJO"
  riesgo_abs = "MEDIO" if "pipeline" in exec_text.lower() or "estado de las operaciones" in exec_text.lower() else "BAJO"
  riesgo_mkt = "MEDIO" if "variaciones extremas" in exec_text.lower() else "BAJO"

  resumen_parts = []
  for key in ("resumen", "hallazgos", "implicaciones"):
    for line in sections.get(key, [])[:3]:
      if not line.startswith("-"):
        resumen_parts.append(line)
  resumen_text = " ".join(resumen_parts).strip() or exec_text[:900]

  proximos = rec_bullets[:5] if rec_bullets else [d.get("titulo", "") for d in decisions[:5]]
  return {
    "score_oportunidad_global": score,
    "recomendacion_global": rec,
    "resumen_ejecutivo": resumen_text,
    "decisiones": decisions,
    "proximos_pasos": proximos,
    "matriz_riesgo": {
      "riesgo_precio": precio_riesgo,
      "riesgo_absorcion": riesgo_abs,
      "riesgo_financiero": riesgo_fin,
      "riesgo_mercado": riesgo_mkt,
    },
    "hallazgos_clave": hallazgos[:8],
    "alertas_detectadas": alerts_count,
  }


def _agent_fallbacks_from_informe(informe: Dict[str, Any], exec_text: str) -> Dict[str, Dict[str, Any]]:
  score = _safe_float(informe.get("score_oportunidad_global"), 60.0)
  risk_score = max(0.0, min(100.0, 100.0 - score))
  alerts_count = int(_safe_float(informe.get("alertas_detectadas"), 0))
  hallazgos = informe.get("hallazgos_clave", []) or []
  riesgos = informe.get("matriz_riesgo", {}) or {}

  margin_pct = None
  m_margin = re.search(r"margen medio[^\\d]{0,24}(\\d+[\\.,]?\\d*)\\s*%", exec_text.lower())
  if m_margin:
    margin_pct = _extract_number_from_text(m_margin.group(1))

  ds = {
    "score_global": round(score, 1),
    "score_riesgo": round(risk_score, 1),
    "score_rentabilidad": round(max(0.0, min(100.0, score - 5.0 + (_safe_float(margin_pct, 0.0) * 1.5))), 1),
    "roi_estimado_pct": round(_safe_float(margin_pct, 0.0), 2) if margin_pct is not None else None,
    "conclusiones": hallazgos[:4] if hallazgos else ["Sin conclusiones estructuradas del agente de datos."],
    "alertas_cuantitativas": [
      {"campo": "alertas_deteccion", "valor_doc": alerts_count, "benchmark": "0-10", "desviacion": f"+{max(0, alerts_count - 10)}", "nivel": "ALTO" if alerts_count >= 30 else "MEDIO" if alerts_count >= 10 else "BAJO"}
    ],
  }

  af_score = round(max(0.0, min(100.0, score - (8.0 if str(riesgos.get("riesgo_financiero", "")).upper() in {"ALTO", "HIGH", "CRITICO", "CRITICAL"} else 2.0))), 1)
  af = {
    "score_viabilidad": af_score,
    "valoracion_financiera": "BUENA" if af_score >= 70 else "ACEPTABLE" if af_score >= 50 else "DEBIL",
    "conclusion_financiera": "Analisis derivado de informe ejecutivo textual de n8n. Se recomienda validar con datos tabulares para precision financiera.",
    "fortalezas": [h for h in hallazgos[:3] if "riesgo" not in str(h).lower()] or ["Volumen y actividad operativa con continuidad en el periodo."],
    "debilidades": [h for h in hallazgos[:3] if "riesgo" in str(h).lower()] or ["Calidad de dato y consistencia deben reforzarse."],
    "ratios_clave": [],
    "anomalias_financieras": [],
  }

  recs = informe.get("proximos_pasos", []) or []
  am = {
    "posicionamiento_mercado": "NEUTRO",
    "tendencia_zona": "MIXTA" if alerts_count >= 20 else "ESTABLE",
    "oportunidades": recs[:2] if recs else ["Optimizar estrategia por segmento y region."],
    "amenazas": [str(x) for x in hallazgos[:2]] if hallazgos else ["Variabilidad de datos y dispersion de precios."],
    "conclusion_mercado": "Salida sintetica basada en informe ejecutivo textual. Se recomienda enriquecer con comparables y series historicas.",
  }
  return {"data_scientist": ds, "analista_financiero": af, "analista_mercado": am}


def validate_n8n_decision_contract(payload: Dict[str, Any]) -> None:
  if not isinstance(payload, dict):
    raise RuntimeError("n8n devolvio un payload invalido (no es JSON objeto).")

  if {"normalized", "summary", "decisions"}.issubset(set(payload.keys())):
    decisions_obj = payload.get("decisions", {})
    if not isinstance(decisions_obj, dict) or "strategic_decisions" not in decisions_obj:
      raise RuntimeError("n8n no devolvio 'decisions.strategic_decisions' en el contrato local.")
    return

  # Nuevo formato: model_outputs presente → aceptado; decisions y resumen son opcionales
  # Los items de decisions[] pueden ser dicts o strings; se normalizan en _adapt_new_webhook_format
  if _is_new_webhook_format(payload):
    return

  report_type = str(payload.get("report_type") or "").lower()
  predictions = payload.get("predictions")
  if report_type in {"clientes", "operaciones"} and isinstance(predictions, list) and predictions:
    return

  informe = _coerce_n8n_informe(payload)
  if not isinstance(informe, dict):
    raise RuntimeError("n8n no devolvio 'informe_ejecutivo'.")

  required = ["score_oportunidad_global", "recomendacion_global", "resumen_ejecutivo", "decisiones"]
  missing = [k for k in required if k not in informe]
  if missing:
    raise RuntimeError(f"n8n no devolvio campos obligatorios en informe_ejecutivo: {', '.join(missing)}")

  decisions = informe.get("decisiones")
  if not isinstance(decisions, list):
    raise RuntimeError("n8n devolvio 'informe_ejecutivo.decisiones' con tipo invalido (debe ser lista).")

  for i, d in enumerate(decisions):
    if not isinstance(d, dict):
      raise RuntimeError(f"n8n decision #{i + 1} invalida (debe ser objeto).")
    if not d.get("urgencia") or not d.get("titulo"):
      raise RuntimeError(f"n8n decision #{i + 1} sin 'urgencia' o 'titulo'.")


def _score_label_text(score: int) -> str:
  if score >= 80:
    return "Muy favorable"
  if score >= 60:
    return "Favorable con seguimiento"
  if score >= 40:
    return "Riesgo relevante"
  return "Riesgo alto"


def _adapt_new_webhook_format(n8n_payload: Dict[str, Any], extracted: Dict[str, Any], doc_name: str) -> Dict[str, Any]:
  """Convierte el nuevo formato n8n (model_outputs + decisions[] + resumen_ejecutivo) al resultado de app."""
  model_outputs = n8n_payload.get("model_outputs") or {}
  # summary: bloque de metricas consolidadas que n8n puede incluir junto a model_outputs
  _summary_raw: Dict[str, Any] = n8n_payload.get("summary") or {}
  # commercial.output.kpis: donde n8n deposita los KPIs detallados del informe comercial
  _commercial_raw: Dict[str, Any] = n8n_payload.get("commercial") or {}
  _comm_output: Dict[str, Any] = (_commercial_raw.get("output") if isinstance(_commercial_raw, dict) else {}) or {}
  _comm_kpis: Dict[str, Any] = (_comm_output.get("kpis") if isinstance(_comm_output, dict) else {}) or {}
  _comm_series: List[Dict[str, Any]] = (_comm_output.get("series") if isinstance(_comm_output, dict) else []) or []

  def _mo(key: str, default: Any = None) -> Any:
    """Lee campo de model_outputs → commercial.output.kpis → summary → default."""
    v = model_outputs.get(key)
    if v is None or v == "":
      v = _comm_kpis.get(key)
    if v is None or v == "":
      v = _summary_raw.get(key)
    return v if (v is not None and v != "") else default

  _raw_decisions_input = n8n_payload.get("decisions") or []
  _RESERVED_KEYS = {"strategic_decisions", "risk_alerts", "decisions", "summary", "model_outputs", "traceability"}
  # n8n puede enviar decisions como dict {"strategic_decisions": [...], "risk_alerts": [...]} o como lista
  if isinstance(_raw_decisions_input, dict):
    _raw_sd = _raw_decisions_input.get("strategic_decisions") or []
    # Guardar risk_alerts de n8n para añadir mas tarde
    _n8n_risk_alerts_raw: List[Dict[str, Any]] = [
      {"type": "n8n_alert", "severity": str(r.get("severity", "media")).lower(), "signal": str(r.get("signal", ""))}
      for r in (_raw_decisions_input.get("risk_alerts") or [])
      if isinstance(r, dict) and r.get("signal")
    ]
    # Normalizar strategic_decisions: action/priority/why → titulo/urgencia/descripcion
    decisions_list: List[Dict[str, Any]] = [
      {
        "urgencia": ("ALTA" if str(d.get("priority", "")).lower() in {"alta", "high"}
                     else "BAJA" if str(d.get("priority", "")).lower() in {"baja", "low"}
                     else "MEDIA"),
        "titulo": str(d.get("action") or d.get("titulo") or "Decision"),
        "descripcion": (" ".join(d["why"]) if isinstance(d.get("why"), list) else str(d.get("why") or d.get("descripcion") or "")),
        "impacto": str(d.get("impact") or d.get("impacto") or ""),
        "confianza": float(_safe_float(d.get("confidence") or d.get("confianza"), 75.0)),
      }
      for d in _raw_sd if isinstance(d, dict)
    ]
  else:
    _n8n_risk_alerts_raw: List[Dict[str, Any]] = []
    decisions_list: List[Dict[str, Any]] = [
      d if isinstance(d, dict)
      else {"titulo": str(d), "urgencia": "MEDIA", "descripcion": str(d), "impacto": "", "confianza": 70}
      for d in (_raw_decisions_input if isinstance(_raw_decisions_input, list) else [])
      if not (isinstance(d, str) and d.strip().lower() in _RESERVED_KEYS)
    ]

  traceability_raw = n8n_payload.get("traceability") or {}
  fuente = str(traceability_raw.get("fuente") or doc_name or "")
  num_registros = int(_safe_float(_mo("num_registros_procesados") or traceability_raw.get("num_registros_procesados") or _mo("total_clients") or _mo("operations_total"), 0))
  regiones: List[str] = [str(r) for r in (traceability_raw.get("regiones_analizadas") or [])]
  alertas_calidad: List[str] = [str(a) for a in (traceability_raw.get("alertas_calidad") or []) if a]

  # Sub-objetos de agentes: buscar en model_outputs, luego en top-level del payload n8n
  # (el formato multi-agente completo los envia en el nivel raiz)
  _inf_ej_raw: Dict[str, Any] = (
    n8n_payload.get("informe_ejecutivo") if isinstance(n8n_payload.get("informe_ejecutivo"), dict) else {}
  ) or {}
  ds_raw: Dict[str, Any] = (
    model_outputs.get("data_scientist")
    or n8n_payload.get("data_scientist")
    or {}
  )
  af_raw: Dict[str, Any] = (
    model_outputs.get("analista_financiero")
    or n8n_payload.get("analista_financiero")
    or {}
  )
  am_raw: Dict[str, Any] = (
    model_outputs.get("analista_mercado")
    or n8n_payload.get("analista_mercado")
    or {}
  )
  # datos_extraidos: presentes en formato multi-agente (promotora/comercial completo)
  datos_raw: Dict[str, Any] = (
    model_outputs.get("datos_extraidos")
    or n8n_payload.get("datos_extraidos")
    or {}
  )

  # Helper: lee campo de múltiples fuentes en orden de prioridad
  def _field(*sources_and_key: Any) -> Any:
    """_field(src1, src2, ..., key) → primer valor no vacío entre las fuentes dadas."""
    key_str = str(sources_and_key[-1])
    for src in sources_and_key[:-1]:
      if isinstance(src, dict):
        v = src.get(key_str)
        if v is not None and v != "":
          return v
    return None

  # score_label → numeric score fallback (NEUTRO≈50, POSITIVO≈70, NEGATIVO≈30)
  _score_label_map = {"POSITIVO": 70, "FAVORABLE": 72, "NEUTRO": 52, "MODERADO": 52, "NEGATIVO": 35, "ALTO RIESGO": 28, "BAJO": 75}
  _score_label_raw = str(_mo("score_label") or "").upper()
  _score_label_default = _score_label_map.get(_score_label_raw, 60)
  # score: informe_ejecutivo > data_scientist > model_outputs/summary
  score = int(_safe_float(
    _inf_ej_raw.get("score_oportunidad_global")
    or ds_raw.get("score_global")
    or _mo("score_global")
    or _mo("score"),
    _score_label_default,
  ))
  # recomendacion: informe_ejecutivo > model_outputs/summary
  rec = str(
    _inf_ej_raw.get("recomendacion_global")
    or _mo("recomendacion")
    or _mo("recomendacion_global")
    or _mo("score_label")
    or "SEGUIMIENTO"
  ).upper()
  valoracion_fin = str(af_raw.get("valoracion_financiera") or _mo("valoracion_financiera") or "ACEPTABLE")
  # risk_status: ALTO/MEDIO/BAJO → concentracion_riesgo
  _risk_status = str(_mo("risk_status") or "").upper()
  concentracion = str(_mo("concentracion_riesgo") or _risk_status or "MEDIO").upper()

  # resumen ejecutivo: informe_ejecutivo > payload top-level > model_outputs/summary
  resumen = str(
    _inf_ej_raw.get("resumen_ejecutivo")
    or n8n_payload.get("resumen_ejecutivo")
    or n8n_payload.get("executive_message")
    or _mo("executive_message")
    or ""
  )

  # Enriquecer con metricas explicitas de model_outputs/summary
  _high_risk_mo = int(_safe_float(_mo("high_risk"), 0))
  _alerts_mo = int(_safe_float(_mo("alerts"), len(alertas_calidad)))

  # Detectar modo con prioridad: payload.report_type > filename > model_outputs.report_type > model_outputs.kpi_mode > resumen
  _payload_report_type = str(n8n_payload.get("report_type") or "").lower()
  _model_report_type   = str(model_outputs.get("report_type") or "").lower()
  _model_kpi_mode      = str(model_outputs.get("kpi_mode") or "").lower()
  fuente_low  = fuente.lower()
  resumen_low = resumen.lower()
  if "operacion" in _payload_report_type or "venta" in _payload_report_type:
    report_mode = "operaciones"
  elif "cliente" in _payload_report_type:
    report_mode = "clientes"
  elif "cliente" in fuente_low:
    # Nombre de fichero contiene 'clientes' → modo clientes
    report_mode = "clientes"
  elif "venta" in fuente_low or "operacion" in fuente_low:
    report_mode = "operaciones"
  elif "cliente" in _model_report_type:
    report_mode = "clientes"
  elif "operacion" in _model_report_type or "venta" in _model_report_type:
    report_mode = "operaciones"
  elif "cliente" in _model_kpi_mode:
    report_mode = "clientes"
  elif "operacion" in _model_kpi_mode:
    # kpi_mode en model_outputs: puede ser genérico; solo usarlo si el fichero no lo contradice
    report_mode = "operaciones"
  elif "cliente" in resumen_low[:120] and "venta" not in fuente_low:
    report_mode = "clientes"
  else:
    report_mode = "clientes"
  is_client_mode = (report_mode == "clientes")
  doc_type = "commercial_report"
  tipo = report_mode

  # Extraer volumen del resumen ejecutivo
  volume_total_eur = 0.0
  m_vol = re.search(r"([\d.,]+)\s*(?:millones?\s+(?:de\s+)?(?:EUR|euros?)|M\s*EUR)", resumen, re.IGNORECASE)
  if m_vol:
    v = _token_to_float(m_vol.group(1))
    if v:
      volume_total_eur = v * 1_000_000

  # Si decisions_list quedo vacia tras filtrar, generar decisiones sinteticas
  # Etiqueta de categoria para las decisiones segun modo
  _decision_supplier = "Cartera de Clientes" if is_client_mode else "Ventas y Operaciones"

  if not decisions_list:
    _n_sd = int(_safe_float(_mo("strategic_decisions"), 0))
    _rs_label = _risk_status or concentracion
    if alertas_calidad:
      for i, alerta in enumerate(alertas_calidad[:5]):
        _urg = "ALTA" if i < _high_risk_mo else "MEDIA"
        decisions_list.append({
          "urgencia": _urg,
          "titulo": alerta[:120],
          "descripcion": alerta,
          "impacto": f"Detectado por agente de calidad. Risk status: {_rs_label}.",
          "confianza": 80 if _urg == "ALTA" else 70,
          "supplier": _decision_supplier,
        })
    elif _n_sd > 0:
      decisions_list.append({
        "urgencia": "ALTA" if _rs_label in {"ALTO", "HIGH"} else "MEDIA",
        "titulo": f"Revisar {_n_sd} decisiones estrategicas detectadas por n8n",
        "descripcion": resumen or f"El agente n8n detecto {_n_sd} decisiones estrategicas. Risk status: {_rs_label}.",
        "impacto": f"Risk status global: {_rs_label}. Score: {score}.",
        "confianza": 75,
        "supplier": _decision_supplier,
      })
    else:
      decisions_list.append({
        "urgencia": "MEDIA",
        "titulo": "Revisar hallazgos del informe",
        "descripcion": resumen or "Analisis completado. Revisar metricas y alertas del agente.",
        "impacto": f"Risk status: {_rs_label}. Score global: {score}.",
        "confianza": 65,
        "supplier": _decision_supplier,
      })
  else:
    # Asegurar que las decisiones existentes tienen supplier
    for _d in decisions_list:
      if not _d.get("supplier"):
        _d["supplier"] = _decision_supplier

  # strategic_decisions y risk_alerts se construyen al final,
  # tras el merge con informe_ejecutivo.decisiones (ver bloque de Rebuild mas abajo)
  strategic_decisions: List[Dict[str, Any]] = []
  risk_alerts: List[Dict[str, Any]] = []

  # Risk status
  if rec in {"REVISION PRIORITARIA", "NO INVERTIR", "REVISAR"} or concentracion == "ALTO":
    risk_status = "Alto"
  elif rec in {"SEGUIMIENTO", "INVERTIR CON CAUTELA", "CAUTELA"} or concentracion == "MEDIO":
    risk_status = "Medio"
  else:
    risk_status = "Bajo"

  # ── Agentes: leer datos reales de n8n (ds_raw/af_raw/am_raw ya buscan en model_outputs y top-level) ──
  _score_riesgo_default = max(0, min(100, 100 - score))

  # Síntesis contextual por PATH para conclusiones y alertas cuando n8n no las devuelve
  if is_client_mode:
    _ds_conclusiones_fallback = (
      [f"Cartera analizada: {num_registros} registros. Risk status: {_risk_status or concentracion}."]
      + ([f"Alertas de calidad detectadas: {len(alertas_calidad)}."] if alertas_calidad else [])
      + ([resumen[:300]] if resumen else [])
    ) or ["Sin conclusiones disponibles."]
    _ds_alertas_fallback = [
      {"campo": "alertas_calidad", "valor_doc": len(alertas_calidad), "benchmark": "0",
       "desviacion": f"+{len(alertas_calidad)}", "nivel": "ALTO" if len(alertas_calidad) >= 3 else "MEDIO"}
    ] if alertas_calidad else []
    _af_fort_fallback = [d.get("titulo", "") for d in decisions_list if str(d.get("urgencia", "")).upper() == "BAJA"][:3] or ["Clientes de bajo riesgo representan la mayoria de la cartera."]
    _af_deb_fallback  = [d.get("titulo", "") for d in decisions_list if str(d.get("urgencia", "")).upper() in {"ALTA", "CRITICA"}][:3] or alertas_calidad[:2] or ["Riesgo de fuga en segmento alto."]
    _am_pos_default   = "NEUTRO" if concentracion == "MEDIO" else "FAVORABLE" if concentracion == "BAJO" else "DESFAVORABLE"
    _am_ten_default   = "BAJISTA" if concentracion == "ALTO" else "ESTABLE"
    _am_opor_fallback = ["Fidelizacion de clientes de bajo riesgo.", "Recuperacion de segmento medio con campanas dirigidas."]
    _am_amen_fallback = alertas_calidad[:2] or ["Incremento de churn en segmento de riesgo alto."]
    _am_conc_fallback = resumen[:300] or f"Cartera de {num_registros} clientes. Risk status: {_risk_status or concentracion}."
  else:
    _ds_conclusiones_fallback = (
      [f"Operaciones analizadas: {num_registros}. Risk status: {_risk_status or concentracion}."]
      + ([f"Alertas de calidad detectadas: {len(alertas_calidad)}."] if alertas_calidad else [])
      + ([resumen[:300]] if resumen else [])
    ) or ["Sin conclusiones disponibles."]
    _ds_alertas_fallback = [
      {"campo": "alertas_calidad", "valor_doc": len(alertas_calidad), "benchmark": "0",
       "desviacion": f"+{len(alertas_calidad)}", "nivel": "ALTO" if len(alertas_calidad) >= 3 else "MEDIO"}
    ] if alertas_calidad else []
    _af_fort_fallback = [d.get("titulo", "") for d in decisions_list if str(d.get("urgencia", "")).upper() == "BAJA"][:3] or ["Actividad comercial continua en las regiones analizadas."]
    _af_deb_fallback  = [d.get("titulo", "") for d in decisions_list if str(d.get("urgencia", "")).upper() in {"ALTA", "CRITICA"}][:3] or alertas_calidad[:2] or ["Variabilidad de margen en operaciones recientes."]
    _am_pos_default   = "NEUTRO" if concentracion == "MEDIO" else "FAVORABLE" if concentracion == "BAJO" else "DESFAVORABLE"
    _am_ten_default   = "MIXTA" if alertas_calidad else "ESTABLE"
    _am_opor_fallback = regiones[:2] or ["Optimizar estrategia comercial por segmento y zona."]
    _am_amen_fallback = alertas_calidad[:2] or ["Variabilidad de datos en operaciones recientes."]
    _am_conc_fallback = (
      f"Analisis de {num_registros} operaciones en {len(regiones)} regiones: {', '.join(regiones[:3])}."
      if regiones else resumen[:300] or f"Portafolio de {num_registros} operaciones. Risk status: {_risk_status or concentracion}."
    )

  ds = {
    "score_global":       int(_safe_float(ds_raw.get("score_global"),       score)),
    "score_riesgo":       int(_safe_float(ds_raw.get("score_riesgo"),       _score_riesgo_default)),
    "score_rentabilidad": int(_safe_float(ds_raw.get("score_rentabilidad"), score)),
    "score_absorcion":    ds_raw.get("score_absorcion"),
    "roi_estimado_pct":   ds_raw.get("roi_estimado_pct") or _field(datos_raw, "roi_declarado_pct"),
    "conclusiones":       ds_raw.get("conclusiones") or _ds_conclusiones_fallback,
    "alertas_cuantitativas": ds_raw.get("alertas_cuantitativas") or ds_raw.get("alertas") or _ds_alertas_fallback,
  }
  af_score = max(0, min(100, int(_safe_float(
    af_raw.get("score_viabilidad"),
    score - (8 if concentracion == "ALTO" else 2 if concentracion == "MEDIO" else 0),
  ))))
  af = {
    "score_viabilidad":     af_score,
    "valoracion_financiera": valoracion_fin,
    "conclusion_financiera": (
      af_raw.get("conclusion") or af_raw.get("conclusion_financiera")
      or resumen[:300] or "Analisis basado en datos del agente n8n."
    ),
    "fortalezas":           af_raw.get("fortalezas") or _af_fort_fallback,
    "debilidades":          af_raw.get("debilidades") or _af_deb_fallback,
    "ratios_clave":         af_raw.get("ratios_clave") or [],
    "anomalias_financieras":af_raw.get("anomalias") or af_raw.get("anomalias_financieras") or alertas_calidad[:5],
  }
  am = {
    "posicionamiento_mercado": am_raw.get("posicionamiento") or am_raw.get("posicionamiento_mercado") or _am_pos_default,
    "tendencia_zona":          am_raw.get("tendencia")        or am_raw.get("tendencia_zona")          or _am_ten_default,
    "oportunidades":           am_raw.get("oportunidades")    or _am_opor_fallback,
    "amenazas":                am_raw.get("amenazas")         or _am_amen_fallback,
    "conclusion_mercado":     (am_raw.get("conclusion") or am_raw.get("conclusion_mercado") or _am_conc_fallback),
    "ventana_lanzamiento":     am_raw.get("ventana_lanzamiento") or {},
  }

  # KPIs segun modo — fuentes: commercial.output.kpis (_comm_kpis) > model_outputs/summary (_mo) > síntesis
  _trend_n8n = str(_comm_kpis.get("trend") or "").lower()
  trend_val = _trend_n8n if _trend_n8n in {"up", "flat", "down"} else ("up" if score >= 70 else "flat" if score >= 50 else "down")

  if is_client_mode:
    # ── CAMINO CLIENTES ────────────────────────────────────────────────────────
    # total_clients: datos_raw puede traer "num_clientes" en formato multiagente
    _total_cl = int(_safe_float(
      _mo("total_clients") or _field(datos_raw, "num_clientes") or num_registros, 0
    ))
    # churn: probabilidad media de fuga (0-1)
    _avg_churn = float(_safe_float(
      _mo("avg_churn_score") or _field(datos_raw, "churn_medio"),
      round(max(0.0, min(1.0, (100 - score) / 100.0 * 0.6)), 4),
    ))
    # retention_rate: derivado de churn o directo
    _retention = float(_safe_float(
      _mo("retention_rate") or _field(datos_raw, "retention_rate"),
      round(max(0.0, min(1.0, 1.0 - _avg_churn)), 4),
    ))
    # Clientes por segmento de riesgo
    # high_risk: n8n puede darlo en high_risk_clients, high_risk, o como % del total
    _high_raw = _mo("high_risk_clients") or _field(datos_raw, "clientes_alto_riesgo")
    _high_pct_raw = _mo("high_risk_pct") or _field(datos_raw, "pct_alto_riesgo")
    if _high_raw is not None:
      high_r = int(_safe_float(_high_raw, 0))
    elif _high_pct_raw is not None:
      high_r = int(_total_cl * _safe_float(_high_pct_raw, 0) / 100.0)
    elif _high_risk_mo > 0:
      high_r = _high_risk_mo
    else:
      # síntesis: alertas activas * porcentaje estimado de impacto
      _n_alerts = max(_alerts_mo, len(alertas_calidad))
      high_r = int(_total_cl * min(0.4, _n_alerts * 0.05)) if _total_cl > 0 else 0

    _med_raw = _mo("medium_risk_clients") or _field(datos_raw, "clientes_medio_riesgo")
    _med_pct_raw = _mo("medium_risk_pct") or _field(datos_raw, "pct_medio_riesgo")
    if _med_raw is not None:
      med_r = int(_safe_float(_med_raw, 0))
    elif _med_pct_raw is not None:
      med_r = int(_total_cl * _safe_float(_med_pct_raw, 0) / 100.0)
    else:
      med_r = int(_total_cl * 0.30) if _total_cl > 0 else 0

    low_r = max(0, _total_cl - high_r - med_r)

    _ops_cl = float(_safe_float(_mo("operations_total") or _field(datos_raw, "num_operaciones"), 0.0))
    _vol_cl = float(_safe_float(_mo("volume_total_eur") or _field(datos_raw, "volumen_eur"), volume_total_eur))
    _rating_b = float(_safe_float(_mo("rating_b_ratio") or _field(datos_raw, "rating_b_ratio"), 0.0))
    _rating_d = float(_safe_float(_mo("rating_d_ratio") or _field(datos_raw, "rating_d_ratio"), 0.0))

    kpis_out: Dict[str, Any] = {
      "kpi_mode": "clientes",
      "trend": trend_val,
      "total_clients": _total_cl,
      "avg_churn_score": round(_avg_churn, 4),
      "retention_rate": round(_retention, 4),
      "high_risk_clients": high_r,
      "medium_risk_clients": med_r,
      "low_risk_clients": low_r,
      "volume_total_eur": _vol_cl,
      "operations_total": _ops_cl,
      "avg_ops_per_client": round(_ops_cl / _total_cl, 2) if _total_cl > 0 else 0.0,
      "conversion_rate": float(_safe_float(_mo("conversion_rate") or _field(datos_raw, "conversion_rate"), 0.0)),
      "visit_to_reservation_rate": float(_safe_float(_mo("visit_to_reservation_rate"), 0.0)),
      "cancellation_rate": float(_safe_float(_mo("cancellation_rate") or _field(datos_raw, "cancellation_rate"), 0.0)),
      "sell_through_rate": float(_safe_float(_mo("sell_through_rate") or _field(datos_raw, "sell_through_rate"), 0.0)),
      "rating_b_ratio": _rating_b,
      "rating_d_ratio": _rating_d,
      "rating_a_ratio": 0.0, "rating_c_ratio": 0.0,
    }
    series_out: List[Dict[str, Any]] = _comm_series if _comm_series else [
      {"label": "Riesgo alto",  "units_sold": high_r, "bucket": "HIGH"},
      {"label": "Riesgo medio", "units_sold": med_r,  "bucket": "MED"},
      {"label": "Riesgo bajo",  "units_sold": low_r,  "bucket": "LOW"},
    ]

  else:
    # ── CAMINO OPERACIONES ────────────────────────────────────────────────────
    # operations_total: unidades/operaciones totales
    _ops_total = int(_safe_float(
      _mo("operations_total")
      or _field(datos_raw, "num_unidades")
      or _field(datos_raw, "num_operaciones")
      or num_registros,
      0,
    ))
    # volume_total_eur: volumen monetario
    _vol_eur = float(_safe_float(
      _mo("volume_total_eur") or _field(datos_raw, "volumen_eur") or volume_total_eur, 0.0
    ))
    # avg_price_eur: precio medio por operación
    _avg_price = float(_safe_float(
      _mo("avg_price_eur") or _field(datos_raw, "precio_medio_eur"),
      _vol_eur / _ops_total if _ops_total > 0 else 0.0,
    ))
    # avg_price_m2_eur: precio por m² — datos_raw.precio_m2 viene del formato multi-agente
    _avg_price_m2 = float(_safe_float(
      _mo("avg_price_m2_eur")
      or _field(datos_raw, "precio_m2")
      or _field(datos_raw, "benchmark_precio_zona"),
      0.0,
    ))
    # avg_margin_pct: ROI o margen — datos_raw.roi_declarado_pct en formato multi-agente
    _avg_margin = float(_safe_float(
      _mo("avg_margin_pct")
      or _field(datos_raw, "roi_declarado_pct")
      or _field(ds_raw, "roi_estimado_pct"),
      0.0,
    ))
    # tasas comerciales — 0.0 por defecto (no fabricar con score)
    _conv        = float(_safe_float(_mo("conversion_rate")   or _field(datos_raw, "conversion_rate"),   0.0))
    _cancel      = float(_safe_float(_mo("cancellation_rate") or _field(datos_raw, "cancellation_rate"), 0.0))
    _sell_through= float(_safe_float(_mo("sell_through_rate") or _field(datos_raw, "sell_through_rate"), 0.0))
    kpis_out = {
      "kpi_mode": "operaciones",
      "trend": trend_val,
      "operations_total": _ops_total,
      "volume_total_eur": _vol_eur,
      "avg_price_eur": _avg_price,
      "avg_price_m2_eur": _avg_price_m2,
      "avg_margin_pct": _avg_margin,
      "conversion_rate": round(_conv, 4),
      "visit_to_reservation_rate": round(_conv, 4),
      "cancellation_rate": round(_cancel, 4),
      "sell_through_rate": round(_sell_through, 4),
    }
    # Series: Cerradas / En escritura / Reservadas proporcionales al score
    _closed = int(_ops_total * _sell_through) if _ops_total > 0 else 0
    _escritura = int(_ops_total * _conv * 0.3) if _ops_total > 0 else 0
    _reserved = max(0, _ops_total - _closed - _escritura)
    series_out = _comm_series if _comm_series else [
      {"label": "Cerradas", "units_sold": _closed},
      {"label": "En escritura", "units_sold": _escritura},
      {"label": "Reservadas", "units_sold": _reserved},
    ]

  # Computed from decisions_list (risk_alerts se reconstruye más adelante)
  _computed_high_risk = int(sum(1 for d in decisions_list if str(d.get("urgencia", "")).upper() in {"ALTA", "CRITICA"}))

  # ── Matriz de riesgo: n8n (informe_ejecutivo o model_outputs) > síntesis ──────
  def _risk_level(n_alerts: int, base: str) -> str:
    if base == "ALTO" or n_alerts >= 5: return "ALTO"
    if base == "MEDIO" or n_alerts >= 2: return "MEDIO"
    return "BAJO"
  _n_alerts_total = _alerts_mo if _alerts_mo > 0 else len(risk_alerts)
  _mz_n8n = _inf_ej_raw.get("matriz_riesgo") or {}
  _riesgo_precio     = str(_mz_n8n.get("riesgo_precio")     or _mo("riesgo_precio")     or _risk_level(_n_alerts_total,          concentracion))
  _riesgo_absorcion  = str(_mz_n8n.get("riesgo_absorcion")  or _mo("riesgo_absorcion")  or _risk_level(max(0, _n_alerts_total-2), concentracion))
  _riesgo_financiero = str(_mz_n8n.get("riesgo_financiero") or _mo("riesgo_financiero") or _risk_level(max(0, _n_alerts_total-1), concentracion))
  _riesgo_mercado    = str(_mz_n8n.get("riesgo_mercado")    or _mo("riesgo_mercado")    or _risk_level(max(0, _n_alerts_total-3), concentracion))

  # ── Decisiones del informe_ejecutivo de n8n (si vienen en formato completo) ──
  _decs_n8n_raw = _inf_ej_raw.get("decisiones") or []
  if _decs_n8n_raw and isinstance(_decs_n8n_raw, list):
    _decs_n8n_norm = [
      {**(d if isinstance(d, dict) else {"titulo": str(d), "urgencia": "MEDIA", "descripcion": str(d), "impacto": "", "confianza": 70}),
       "supplier": (d if isinstance(d, dict) else {}).get("supplier", _decision_supplier)}
      for d in _decs_n8n_raw
    ]
    # Añadir las que NO tengan el mismo titulo (evitar duplicados)
    _existing_titulos = {str(d.get("titulo", "")) for d in _decs_n8n_norm}
    decisions_list = _decs_n8n_norm + [d for d in decisions_list if str(d.get("titulo", "")) not in _existing_titulos]

  # Rebuild strategic_decisions y risk_alerts desde el decisions_list final
  strategic_decisions = []
  risk_alerts = []
  for d in decisions_list:
    urg = str(d.get("urgencia") or "MEDIA").upper()
    pri = "alta" if urg in {"CRITICA", "ALTA"} else "baja" if urg == "BAJA" else "media"
    conf = _safe_float(d.get("confianza"), 75.0)
    strategic_decisions.append({
      "type": "n8n_decision",
      "action": str(d.get("titulo") or "Decision estrategica"),
      "priority": pri,
      "confidence": conf,
      "why": [x for x in [str(d.get("descripcion") or ""), str(d.get("impacto") or "")] if x],
      "supplier": d.get("supplier", _decision_supplier),
    })
    if urg in {"CRITICA", "ALTA"}:
      risk_alerts.append({"type": "n8n_alert", "severity": pri, "signal": str(d.get("titulo") or "Alerta")})
  # Añadir risk_alerts de n8n (decisions.risk_alerts) evitando duplicados
  _existing_signals = {str(a.get("signal", "")) for a in risk_alerts}
  for _ra in _n8n_risk_alerts_raw:
    if _ra.get("signal") not in _existing_signals:
      risk_alerts.append(_ra)
      _existing_signals.add(str(_ra.get("signal", "")))
  # Añadir alertas de calidad evitando duplicados
  for alerta in alertas_calidad:
    if alerta not in _existing_signals:
      risk_alerts.append({"type": "quality_alert", "severity": "media", "signal": alerta})
      _existing_signals.add(alerta)

  # ── Proximos pasos: n8n > generados desde descripciones de decisiones ────────
  _prox_n8n = _inf_ej_raw.get("proximos_pasos") or []
  if _prox_n8n:
    proximos_pasos_out: List[str] = [str(p) for p in _prox_n8n if str(p).strip()]
  else:
    # Construir pasos accionables desde decisiones (titulo + descripcion breve)
    _prox_built: List[str] = []
    for d in decisions_list[:5]:
      _t = str(d.get("titulo") or "").strip()
      _d = str(d.get("descripcion") or "").strip()
      if _t and _d:
        _prox_built.append(f"{_t} — {_d[:120]}" if len(_d) > 10 else _t)
      elif _t:
        _prox_built.append(_t)
    proximos_pasos_out = _prox_built

  summary_out = {
    "high_risk": _high_risk_mo if _high_risk_mo > 0 else _computed_high_risk,
    "score": score,
    "forecast_high": int(_safe_float(_mo("forecast_high"), 0)),
    "alerts": _alerts_mo if _alerts_mo > 0 else len(risk_alerts),
    "critical": int(_safe_float(_mo("critical"), int(any(str(a.get("severity")) == "critica" for a in risk_alerts)))),
    "strategic_decisions": int(_safe_float(_mo("strategic_decisions"), len(strategic_decisions))),
    "score_label": str(_mo("score_label") or _score_label_text(score)),
    "risk_status": risk_status,
    "executive_message": resumen[:220],
    "kpi_mode": report_mode,
    "friendly_labels": {"high_risk": "Riesgos altos", "score": "Estado general", "forecast_high": "Riesgo proyectado", "alerts": "Alertas activas"},
  }

  informe = {
    "score_oportunidad_global": score,
    "recomendacion_global": rec,
    "resumen_ejecutivo": resumen,
    "decisiones": [
      {
        "urgencia":   d.get("urgencia", "MEDIA"),
        "titulo":     d.get("titulo", ""),
        "descripcion":d.get("descripcion", ""),
        "impacto":    d.get("impacto", ""),
        "confianza":  d.get("confianza", 75),
        "supplier":   d.get("supplier", _decision_supplier),
      }
      for d in decisions_list
    ],
    "proximos_pasos": proximos_pasos_out,
    "matriz_riesgo": {
      "riesgo_precio":     _riesgo_precio,
      "riesgo_absorcion":  _riesgo_absorcion,
      "riesgo_financiero": _riesgo_financiero,
      "riesgo_mercado":    _riesgo_mercado,
    },
    "hallazgos_clave": alertas_calidad[:5],
    "alertas_detectadas": len(alertas_calidad),
  }

  return {
    "status": "success",
    "session_id": str(n8n_payload.get("session_id") or traceability_raw.get("timestamp_utc") or "n8n"),
    "report_type": report_mode,
    "run_id": str(n8n_payload.get("session_id") or "n8n"),
    "document_id": extracted.get("document_id"),
    "normalized": {
      "document_type": doc_type,
      "confidence": 0.9,
      "suppliers": [],
      "global_indicators": {},
      "interpretation": {
        "confidence": 0.9,
        "classification": {"label": tipo, "score": 0.9, "evidence_keywords": []},
        "metrics": [
          {"name": "num_registros", "value": num_registros, "unit": "registros"},
          {"name": "score_global", "value": score, "unit": "score"},
          {"name": "volume_total_eur", "value": volume_total_eur, "unit": "EUR"},
        ],
        "risks": [],
      },
    },
    "segmentation": {"model": "n8n", "engine": "n8n", "output": {"suppliers_segmented": [], "summary": {"total_suppliers": 0, "high_risk": 0, "med_risk": 0, "low_risk": 0}}},
    "behavior": {"model": "n8n", "engine": "n8n", "output": {"supplier_behavior": [], "summary": {"total_suppliers": 0, "stable": 0, "warning": 0, "critical": 0, "avg_reliability_index": 0}}},
    "forecast": {"model": "n8n", "engine": "n8n", "output": {"supplier_forecast": [], "summary": {"horizon_days": 90, "total_suppliers": 0, "high_risk_forecast": 0, "med_risk_forecast": 0, "low_risk_forecast": 0}}},
    "commercial": {
      "model": "n8n_model_outputs",
      "engine": "n8n",
      "output": {
        "kpis": kpis_out,
        "series": series_out,
        "summary": {"months_detected": 0, "trend": trend_val, "alerts": len(risk_alerts), "decisions": len(strategic_decisions)},
      },
    },
    "real_estate_models": {
      "model": "n8n_model_outputs",
      "engine": "n8n",
      "output": {
        "expected_sale_price_eur": None,
        "expected_rent_eur_month": None,
        "investment_score_0_100": float(score),
        "liquidity_days_p50": None,
        "expected_gross_yield_pct": 0.0,
        "price_gap_pct_vs_document": 0.0,
        "rent_gap_pct_vs_document": None,
        "input_features": {},
      },
    },
    "decisions": {"strategic_decisions": strategic_decisions, "risk_alerts": risk_alerts, "inputs": {"source": "n8n_model_outputs"}},
    "benchmark": {"available": False, "reason": "benchmark_only_for_supplier_report"},
    "extraction_summary": {
      "engine": ((extracted.get("extraction") or {}).get("extraction_engine")),
      "page_count": ((extracted.get("extraction") or {}).get("page_count")),
      "char_count": ((extracted.get("extraction") or {}).get("char_count")),
      "has_tables": ((extracted.get("extraction") or {}).get("has_tables")),
      "quality_status": ((extracted.get("extraction") or {}).get("quality_status")),
      "usable_for_analysis": ((extracted.get("extraction") or {}).get("usable_for_analysis")),
    },
    "summary": summary_out,
    "traceability": {
      "timestamp_utc": traceability_raw.get("timestamp_utc") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
      "document_type": doc_type,
      "fuente": fuente,
      "num_registros_procesados": num_registros,
      "regiones_analizadas": regiones,
      "alertas_calidad": alertas_calidad,
      "classification": {"label": tipo, "score": 0.9, "evidence_keywords": []},
      "evidence_keywords_count": 0,
      "models_executed": traceability_raw.get("models_executed") or [{"name": "n8n_model_outputs", "engine": "n8n"}],
      "rules_engine": traceability_raw.get("rules_engine") or "n8n_workflow",
    },
    "fundamentals": {
      "document_type": doc_type,
      "fundamental_metrics": [
        {"name": "score_global", "value": score, "label": "Score global"},
        {"name": "num_registros", "value": num_registros, "label": "Registros procesados"},
        {"name": "num_regiones", "value": len(regiones), "label": "Regiones analizadas"},
      ],
      "improvement_plan": [{"priority": "media", "title": d.get("titulo", ""), "recommendation": d.get("descripcion", ""), "linked_metrics": []} for d in decisions_list[:3]],
      "summary": {"focus": "n8n_model_outputs", "priority_level": risk_status.lower()},
    },
    "result_interpretation": {
      "document_type": doc_type,
      "executive_summary": {
        "title": "Resumen ejecutivo del documento",
        "overview": resumen or "Sin resumen disponible.",
        "key_points": af.get("fortalezas", [])[:4],
        "top_entities": regiones[:3] or ["Zona no identificada"],
        "recommended_actions": [d.get("action", "") for d in strategic_decisions[:5]],
      },
      "highlights": [
        f"Recomendacion global: {rec}",
        f"Score oportunidad: {score}/100",
        f"Valoracion financiera: {valoracion_fin}",
        f"Concentracion de riesgo: {concentracion}",
        f"Registros procesados: {num_registros}",
        f"Regiones: {', '.join(regiones[:3])}{'...' if len(regiones) > 3 else ''}",
      ],
      "entity_interpretations": [],
      "decision_interpretation": {
        "strategic_count": len(strategic_decisions),
        "alerts_count": len(risk_alerts),
        "top_strategic": strategic_decisions[:5],
        "top_alerts": risk_alerts[:5],
      },
    },
    "n8n_raw": {
      **n8n_payload,
      "informe_ejecutivo": informe,
      "data_scientist": ds,
      "analista_financiero": af,
      "analista_mercado": am,
    },
    "n8n_mode": True,
    "document_name": doc_name,
  }


def adapt_n8n_to_app_result(n8n_payload: Dict[str, Any], extracted: Dict[str, Any], doc_name: str) -> Dict[str, Any]:
  # Nuevo formato: model_outputs + decisions[] + resumen_ejecutivo
  if _is_new_webhook_format(n8n_payload):
    return _adapt_new_webhook_format(n8n_payload, extracted, doc_name)

  if {"normalized", "summary", "decisions"}.issubset(set(n8n_payload.keys())):
    return {
      **n8n_payload,
      "traceability": {
        **(n8n_payload.get("traceability") or {}),
        "models_executed": (n8n_payload.get("traceability") or {}).get("models_executed", []) or [
          {"name": "n8n_orchestrator", "engine": "n8n"}
        ],
      },
    }

  informe = _coerce_n8n_informe(n8n_payload)
  exec_raw_text = n8n_payload.get("informe_ejecutivo")
  if isinstance(exec_raw_text, dict):
    exec_raw_text = str(exec_raw_text.get("resumen_ejecutivo") or "")
  elif not isinstance(exec_raw_text, str):
    exec_raw_text = ""
  ds = n8n_payload.get("data_scientist", {}) or {}
  af = n8n_payload.get("analista_financiero", {}) or {}
  am = n8n_payload.get("analista_mercado", {}) or {}
  datos = n8n_payload.get("datos_extraidos", {}) or {}
  report_mode = str(n8n_payload.get("report_type") or "").strip().lower()
  if report_mode not in {"clientes", "operaciones"} and exec_raw_text:
    head = _normalize_for_matching(exec_raw_text[:240])
    if "informe ejecutivo" in head and "clientes" in head:
      report_mode = "clientes"
    elif "informe ejecutivo" in head and "operaciones" in head:
      report_mode = "operaciones"
  if not ds or not af or not am:
    agent_fallback = _agent_fallbacks_from_informe(informe, exec_raw_text)
    ds = ds or agent_fallback["data_scientist"]
    af = af or agent_fallback["analista_financiero"]
    am = am or agent_fallback["analista_mercado"]
  op_kpis: Dict[str, Any] = {}
  op_series: List[Dict[str, Any]] = []
  client_kpis: Dict[str, Any] = {}
  client_series: List[Dict[str, Any]] = []
  if report_mode in {"operaciones", ""}:
    operations_extracted = _extract_operations_kpis_from_text(exec_raw_text, informe)
    op_kpis = operations_extracted.get("kpis", {}) if isinstance(operations_extracted, dict) else {}
    op_series = operations_extracted.get("series", []) if isinstance(operations_extracted, dict) else []
  if report_mode in {"clientes", ""}:
    clients_extracted = _extract_client_kpis_from_payload(n8n_payload)
    client_from_text = _extract_client_kpis_from_text(exec_raw_text, informe)
    if isinstance(client_from_text, dict):
      client_kpis.update(client_from_text.get("kpis", {}) or {})
      client_series = list(client_from_text.get("series", []) or [])
    if isinstance(clients_extracted, dict):
      # Si hay predictions reales, tienen prioridad sobre inferencia textual.
      client_kpis.update(clients_extracted.get("kpis", {}) or {})
      pred_series = list(clients_extracted.get("series", []) or [])
      if pred_series:
        client_series = pred_series

  tipo = str(
    n8n_payload.get("tipo_documento")
    or n8n_payload.get("report_type")
    or ""
  ).lower()
  if not tipo and report_mode in {"clientes", "operaciones"}:
    tipo = report_mode
  if not tipo and exec_raw_text:
    first_line = exec_raw_text.splitlines()[0].lower() if exec_raw_text.splitlines() else ""
    if "operacion" in first_line:
      tipo = "operaciones"
    elif "proveedor" in first_line:
      tipo = "proveedores"
    elif "cliente" in first_line:
      tipo = "clientes"
  if not tipo:
    tipo = "real_estate_generic"
  if "proveedor" in tipo:
    doc_type = "supplier_report"
  elif tipo in {"promotora", "agencia", "businessplan", "operaciones", "clientes", "commercial_report"}:
    doc_type = "commercial_report"
  else:
    doc_type = "real_estate_generic"
  if report_mode == "clientes":
    is_client_mode = True
  elif report_mode == "operaciones":
    is_client_mode = False
  else:
    is_client_mode = ("cliente" in tipo) or (_safe_float((client_kpis or {}).get("total_clients"), 0.0) > 0)

  decisions_raw = informe.get("decisiones", []) or []
  strategic_decisions = []
  risk_alerts = []
  for d in decisions_raw:
    urg = str(d.get("urgencia") or "MEDIA").upper()
    pri = "media"
    sev = "media"
    if urg in {"CRITICA", "ALTA"}:
      pri = "alta"
      sev = "alta"
    elif urg == "BAJA":
      pri = "baja"
      sev = "baja"

    strategic_decisions.append(
      {
        "type": "n8n_decision",
        "action": str(d.get("titulo") or "Decision estrategica"),
        "priority": pri,
        "why": [x for x in [str(d.get("descripcion") or ""), str(d.get("impacto") or "")] if x],
      }
    )
    if urg in {"CRITICA", "ALTA"}:
      risk_alerts.append(
        {
          "type": "n8n_alert",
          "severity": sev,
          "signal": str(d.get("titulo") or "Alerta"),
        }
      )

  matriz = informe.get("matriz_riesgo", {}) or {}
  for k, v in matriz.items():
    level = str(v or "").upper()
    if level in {"ALTO", "CRITICO", "HIGH", "CRITICAL"}:
      risk_alerts.append(
        {
          "type": "risk_matrix_alert",
          "severity": "alta" if level in {"ALTO", "HIGH"} else "critica",
          "signal": f"{k.replace('_', ' ').title()}: {v}",
        }
      )

  score = int(_safe_float(informe.get("score_oportunidad_global", ds.get("score_global", 0)), 0))
  if is_client_mode and score <= 0:
    score = int(max(10, min(96, _safe_float((1.0 - _safe_float(client_kpis.get("avg_churn_score"), 0.5)) * 100.0, 55.0))))
  risk_status = "Bajo"
  rec = str(informe.get("recomendacion_global") or "").upper()
  if is_client_mode and not rec:
    rec = "INVERTIR" if score >= 75 else "INVERTIR CON CAUTELA" if score >= 60 else "REVISAR" if score >= 45 else "NO INVERTIR"
  if rec in {"NO INVERTIR", "REVISAR"}:
    risk_status = "Alto"
  elif rec in {"INVERTIR CON CAUTELA", "CAUTELA"}:
    risk_status = "Medio"

  interpretation_metrics: List[Dict[str, Any]] = []
  if "precio_m2" in datos:
    interpretation_metrics.append({"name": "price_m2_ref_eur", "value": datos.get("precio_m2"), "unit": "EUR/m2"})
  elif _safe_float(op_kpis.get("avg_price_m2_eur"), 0.0) > 0:
    interpretation_metrics.append({"name": "price_m2_ref_eur", "value": op_kpis.get("avg_price_m2_eur"), "unit": "EUR/m2"})
  if "roi_declarado_pct" in datos:
    interpretation_metrics.append({"name": "roi_declarado_pct", "value": datos.get("roi_declarado_pct"), "unit": "%"})
  elif _safe_float(op_kpis.get("avg_margin_pct"), 0.0) > 0:
    interpretation_metrics.append({"name": "roi_declarado_pct", "value": op_kpis.get("avg_margin_pct"), "unit": "%"})
  if "num_unidades" in datos:
    interpretation_metrics.append({"name": "num_unidades", "value": datos.get("num_unidades"), "unit": "u"})
  elif _safe_float(op_kpis.get("operations_total"), 0.0) > 0:
    interpretation_metrics.append({"name": "num_unidades", "value": op_kpis.get("operations_total"), "unit": "u"})
  if _safe_float(op_kpis.get("avg_price_eur"), 0.0) > 0:
    interpretation_metrics.append({"name": "price_eur", "value": op_kpis.get("avg_price_eur"), "unit": "EUR"})
  if is_client_mode:
    interpretation_metrics.append({"name": "clients_total", "value": _safe_float(client_kpis.get("total_clients"), 0.0), "unit": "clientes"})
    interpretation_metrics.append({"name": "avg_churn_score", "value": _safe_float(client_kpis.get("avg_churn_score"), 0.0), "unit": "score"})

  normalized = {
    "document_type": doc_type,
    "confidence": _safe_float(n8n_payload.get("confianza_tipo"), 0.8),
    "suppliers": [],
    "global_indicators": {},
    "interpretation": {
      "confidence": _safe_float(n8n_payload.get("confianza_tipo"), 0.8),
      "classification": {
        "label": tipo,
        "score": _safe_float(n8n_payload.get("confianza_tipo"), 0.8),
        "evidence_keywords": [],
      },
      "metrics": interpretation_metrics,
      "risks": [],
    },
  }

  summary = {
    "high_risk": int(sum(1 for a in risk_alerts if str(a.get("severity")) in {"alta", "critica"})),
    "score": score,
    "forecast_high": 0,
    "alerts": len(risk_alerts),
    "critical": int(any(str(a.get("severity")) == "critica" for a in risk_alerts)),
    "strategic_decisions": len(strategic_decisions),
    "score_label": _score_label_text(score),
    "risk_status": risk_status,
    "executive_message": str(informe.get("resumen_ejecutivo") or "")[:220],
    "friendly_labels": {
      "high_risk": "Riesgos altos",
      "score": "Estado general",
      "forecast_high": "Riesgo proyectado",
      "alerts": "Alertas activas",
    },
  }
  if is_client_mode and not summary.get("executive_message"):
    summary["executive_message"] = (
      f"Cartera de {_fmt_int(client_kpis.get('total_clients'))} clientes con churn medio "
      f"{_safe_float(client_kpis.get('avg_churn_score'), 0.0):.2f}. "
      "Se recomienda priorizar retencion en clientes de alto riesgo."
    )
  if is_client_mode:
    summary["alerts"] = max(int(summary.get("alerts", 0)), int(_safe_float(client_kpis.get("high_risk_clients"), 0.0)))

  if is_client_mode and not strategic_decisions:
    high_clients = int(_safe_float(client_kpis.get("high_risk_clients"), 0.0))
    strategic_decisions.append(
      {
        "type": "n8n_decision",
        "action": "Activar plan de retencion sobre clientes con churn alto",
        "priority": "alta" if high_clients > 0 else "media",
        "why": [f"clientes_alto_riesgo={high_clients}", f"churn_promedio={_safe_float(client_kpis.get('avg_churn_score'), 0.0):.2f}"],
      }
    )
    if high_clients > 0:
      risk_alerts.append(
        {
          "type": "n8n_alert",
          "severity": "alta",
          "signal": f"Clientes con alto riesgo de fuga detectados: {high_clients}",
        }
      )

  decisions = {
    "strategic_decisions": strategic_decisions,
    "risk_alerts": risk_alerts,
    "inputs": {"source": "n8n"},
  }

  result_interpretation = {
    "document_type": doc_type,
    "executive_summary": {
      "title": "Resumen ejecutivo del documento",
      "overview": str(informe.get("resumen_ejecutivo") or "Sin resumen disponible."),
      "key_points": (af.get("fortalezas", []) or [])[:4],
      "top_entities": [str(n8n_payload.get("zona_geografica") or "Zona no identificada")],
      "recommended_actions": (informe.get("proximos_pasos", []) or [])[:5],
    },
    "highlights": [
      f"Recomendacion global: {rec or 'n/a'}",
      f"Score oportunidad: {score}/100",
      f"Zona: {n8n_payload.get('zona_geografica', 'n/a')}",
    ],
    "entity_interpretations": [],
    "decision_interpretation": {
      "strategic_count": len(strategic_decisions),
      "alerts_count": len(risk_alerts),
      "top_strategic": strategic_decisions[:5],
      "top_alerts": risk_alerts[:5],
    },
  }

  real_estate_models = {
    "model": "n8n_multi_agent",
    "engine": "n8n",
    "output": {
      "expected_sale_price_eur": (
        _safe_float(datos.get("precio_m2"), 0.0) * _safe_float(op_kpis.get("avg_surface_m2"), 0.0)
        if _safe_float(datos.get("precio_m2"), 0.0) > 0 and _safe_float(op_kpis.get("avg_surface_m2"), 0.0) > 0
        else (_safe_float(op_kpis.get("avg_price_eur"), 0.0) or None)
      ),
      "expected_rent_eur_month": None,
      "investment_score_0_100": _safe_float(ds.get("score_rentabilidad", ds.get("score_global", score)), 0.0),
      "liquidity_days_p50": None,
      "expected_gross_yield_pct": _safe_float(ds.get("roi_estimado_pct", op_kpis.get("avg_margin_pct")), 0.0),
      "price_gap_pct_vs_document": _safe_float(ds.get("desviacion_precio_pct"), 0.0),
      "rent_gap_pct_vs_document": None,
      "input_features": {},
    },
  }

  return {
    "run_id": str(n8n_payload.get("session_id") or "n8n"),
    "document_id": extracted.get("document_id"),
    "normalized": normalized,
    "segmentation": {"model": "n8n", "engine": "n8n", "output": {"suppliers_segmented": [], "summary": {"total_suppliers": 0, "high_risk": 0, "med_risk": 0, "low_risk": 0}}},
    "behavior": {"model": "n8n", "engine": "n8n", "output": {"supplier_behavior": [], "summary": {"total_suppliers": 0, "stable": 0, "warning": 0, "critical": 0, "avg_reliability_index": 0}}},
    "forecast": {"model": "n8n", "engine": "n8n", "output": {"supplier_forecast": [], "summary": {"horizon_days": 90, "total_suppliers": 0, "high_risk_forecast": 0, "med_risk_forecast": 0, "low_risk_forecast": 0}}},
    "commercial": {
      "model": "n8n_multi_agent",
      "engine": "n8n",
      "output": {
        "kpis": (
          {
            "kpi_mode": "clientes",
            "trend": str(client_kpis.get("trend") or "flat"),
            "conversion_rate": _safe_float(client_kpis.get("conversion_rate"), 0.0),
            "visit_to_reservation_rate": _safe_float(client_kpis.get("visit_to_reservation_rate"), _safe_float(client_kpis.get("conversion_rate"), 0.0)),
            "cancellation_rate": _safe_float(client_kpis.get("cancellation_rate"), 0.0),
            "sell_through_rate": _safe_float(client_kpis.get("sell_through_rate"), 0.0),
            "total_clients": _safe_float(client_kpis.get("total_clients"), 0.0),
            "operations_total": _safe_float(client_kpis.get("operations_total"), 0.0),
            "avg_ops_per_client": _safe_float(client_kpis.get("avg_ops_per_client"), 0.0),
            "volume_total_eur": _safe_float(client_kpis.get("volume_total_eur"), 0.0),
            "avg_churn_score": _safe_float(client_kpis.get("avg_churn_score"), 0.0),
            "retention_rate": _safe_float(client_kpis.get("retention_rate"), 0.0),
            "high_risk_clients": _safe_float(client_kpis.get("high_risk_clients"), 0.0),
            "medium_risk_clients": _safe_float(client_kpis.get("medium_risk_clients"), 0.0),
            "low_risk_clients": _safe_float(client_kpis.get("low_risk_clients"), 0.0),
            "rating_a_ratio": _safe_float(client_kpis.get("rating_a_ratio"), 0.0),
            "rating_b_ratio": _safe_float(client_kpis.get("rating_b_ratio"), 0.0),
            "rating_c_ratio": _safe_float(client_kpis.get("rating_c_ratio"), 0.0),
            "rating_d_ratio": _safe_float(client_kpis.get("rating_d_ratio"), 0.0),
          }
          if is_client_mode
          else {
            "kpi_mode": "operaciones",
            "trend": str(op_kpis.get("trend") or "flat"),
            "conversion_rate": _safe_float(op_kpis.get("conversion_rate"), 0.0),
            "visit_to_reservation_rate": _safe_float(op_kpis.get("visit_to_reservation_rate"), _safe_float(op_kpis.get("conversion_rate"), 0.0)),
            "cancellation_rate": _safe_float(op_kpis.get("cancellation_rate"), 0.0),
            "sell_through_rate": _safe_float(op_kpis.get("sell_through_rate"), 0.0),
            "operations_total": _safe_float(op_kpis.get("operations_total"), 0.0),
            "volume_total_eur": _safe_float(op_kpis.get("volume_total_eur"), 0.0),
            "avg_price_eur": _safe_float(op_kpis.get("avg_price_eur"), 0.0),
            "avg_price_m2_eur": _safe_float(op_kpis.get("avg_price_m2_eur"), 0.0),
            "avg_margin_pct": _safe_float(op_kpis.get("avg_margin_pct"), 0.0),
          }
        ),
        "series": client_series if is_client_mode else op_series,
        "summary": {
          "months_detected": 0,
          "trend": str((client_kpis if is_client_mode else op_kpis).get("trend") or "flat"),
          "alerts": len(risk_alerts),
          "decisions": len(strategic_decisions),
        },
      },
    },
    "real_estate_models": real_estate_models,
    "decisions": decisions,
    "benchmark": {"available": False, "reason": "benchmark_only_for_supplier_report"},
    "extraction_summary": {
      "engine": ((extracted.get("extraction") or {}).get("extraction_engine")),
      "page_count": ((extracted.get("extraction") or {}).get("page_count")),
      "char_count": ((extracted.get("extraction") or {}).get("char_count")),
      "has_tables": ((extracted.get("extraction") or {}).get("has_tables")),
      "quality_status": ((extracted.get("extraction") or {}).get("quality_status")),
      "usable_for_analysis": ((extracted.get("extraction") or {}).get("usable_for_analysis")),
    },
    "summary": summary,
    "traceability": {
      "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
      "document_type": doc_type,
      "classification": {"label": tipo, "score": _safe_float(n8n_payload.get("confianza_tipo"), 0.8), "evidence_keywords": []},
      "evidence_keywords_count": 0,
      "models_executed": [
        {"name": "n8n_orchestrator", "engine": "n8n"},
        {"name": "data_scientist_agent", "engine": "n8n"},
        {"name": "analista_financiero_agent", "engine": "n8n"},
        {"name": "analista_mercado_agent", "engine": "n8n"},
      ],
      "rules_engine": "n8n_workflow",
    },
    "fundamentals": {
      "document_type": doc_type,
      "fundamental_metrics": [],
      "improvement_plan": [{"priority": "media", "title": x, "recommendation": x, "linked_metrics": []} for x in (informe.get("proximos_pasos", []) or [])[:3]],
      "summary": {"focus": "n8n_multi_agent", "priority_level": risk_status.lower()},
    },
    "result_interpretation": result_interpretation,
    "n8n_raw": {
      **n8n_payload,
      "informe_ejecutivo": informe,
      "data_scientist": ds,
      "analista_financiero": af,
      "analista_mercado": am,
    },
    "n8n_mode": True,
    "document_name": doc_name,
  }


# Utility helpers 
_DOC_ICONS: Dict[str, str] = {
  "supplier_report":   '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  "commercial_report": '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
  "valuation_report":  '<line x1="12" y1="2" x2="12" y2="22"/><path d="M5 9.5l-3 4h6l-3-4z"/><path d="M19 9.5l-3 4h6l-3-4z"/><line x1="5" y1="13.5" x2="19" y2="13.5"/>',
  "legal_report":      '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>',
  "market_report":     '<line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/><line x1="2" y1="20" x2="22" y2="20"/>',
  "investment_report": '<polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>',
  "real_estate_generic":'<path d="M3 22V10L12 3l9 7v12"/><path d="M9 22v-6h6v6"/>',
  "unknown":           '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
}

def _doc_icon_svg(doc_type: str, size: int = 22, color: str = "#00417d") -> str:
  paths = _DOC_ICONS.get(doc_type, _DOC_ICONS["real_estate_generic"])
  return (
    f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
    f'stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
    f'{paths}</svg>'
  )

def detect_doc_type(file_name: str) -> Dict[str, Any]:
  lower = file_name.lower()
  if any(w in lower for w in ["proveedor", "supplier", "contrato", "riesgo"]):
    return {"name": "Informe de Proveedores", "doc_type": "supplier_report", "confidence": "92%"}
  if any(w in lower for w in ["tasacion", "valoracion"]):
    return {"name": "Tasacion", "doc_type": "valuation_report", "confidence": "88%"}
  if any(w in lower for w in ["due", "diligence", "auditoria"]):
    return {"name": "Due Diligence", "doc_type": "legal_report", "confidence": "90%"}
  return {"name": "Documento Inmobiliario", "doc_type": "real_estate_generic", "confidence": "84%"}


def detect_doc_type_from_extraction(detected: Dict[str, Any]) -> Dict[str, Any]:
  doc_type = str(detected.get("document_type") or "unknown")
  try:
    confidence_pct = f"{float(detected.get('confidence', 0.0)) * 100:.0f}%"
  except (TypeError, ValueError):
    confidence_pct = "n/a"
  mapping = {
    "supplier_report":    {"name": "Informe de Proveedores"},
    "commercial_report":  {"name": "Informe Comercial"},
    "valuation_report":   {"name": "Tasacion"},
    "legal_report":       {"name": "Informe Legal"},
    "market_report":      {"name": "Informe de Mercado"},
    "investment_report":  {"name": "Informe de Inversion"},
    "real_estate_generic":{"name": "Documento Inmobiliario"},
    "unknown":            {"name": "Documento no identificado"},
  }
  base = mapping.get(doc_type, mapping["real_estate_generic"])
  return {"name": base["name"], "doc_type": doc_type, "confidence": confidence_pct}


def extraction_quality(extracted_payload: Dict[str, Any]) -> Dict[str, Any]:
  extraction = (extracted_payload or {}).get("extraction", {}) or {}
  char_count = int(_safe_float(extraction.get("char_count"), 0))
  min_required = int(_safe_float(extraction.get("min_chars_required"), 180))
  usable = bool(extraction.get("usable_for_analysis", char_count >= min_required))
  return {
    "usable_for_analysis": usable,
    "char_count": char_count,
    "min_chars_required": min_required,
    "quality_status": str(extraction.get("quality_status") or ("ok" if usable else "low_text")),
    "ocr_applied": bool(extraction.get("ocr_applied", False)),
    "ocr_engine": extraction.get("ocr_engine"),
    "ocr_error": extraction.get("ocr_error"),
  }


def summarize_for_kpis(result: Dict[str, Any]) -> Dict[str, int]:
  summary = result.get("summary") or {}
  if summary:
    return {
      "high_risk": int(summary.get("high_risk", 0)),
      "score": int(summary.get("score", 0)),
      "forecast_high": int(summary.get("forecast_high", 0)),
      "alerts": int(summary.get("alerts", 0)),
      "critical": int(summary.get("critical", 0)),
    }
  seg = ((result.get("segmentation") or {}).get("output") or {}).get("summary", {})
  beh = ((result.get("behavior") or {}).get("output") or {}).get("summary", {})
  fc = ((result.get("forecast") or {}).get("output") or {}).get("summary", {})
  alerts = len((result.get("decisions") or {}).get("risk_alerts", []))
  return {
    "high_risk": int(seg.get("high_risk", 0)),
    "score": int(seg.get("high_risk", 0) * 20 + seg.get("med_risk", 0) * 8 + 60),
    "forecast_high": int(fc.get("high_risk_forecast", 0)),
    "alerts": alerts,
    "critical": int(beh.get("critical", 0)),
  }


def build_prd_text_local(result: Dict[str, Any], doc_name: str) -> str:
  summary = result.get("summary", {}) or {}
  interpretation = result.get("result_interpretation", {}) or {}
  exec_summary = interpretation.get("executive_summary", {}) or {}
  decisions = ((result.get("decisions") or {}).get("strategic_decisions") or [])[:8]
  alerts = ((result.get("decisions") or {}).get("risk_alerts") or [])[:8]
  trace = result.get("traceability", {}) or {}

  lines = [
    f"# PRD Ejecutivo - {doc_name}",
    "",
    "## 1. Contexto y Objetivo",
    "Documento analizado para soportar decision inmobiliaria con flujo n8n multi-agente.",
    "",
    "## 2. Resumen Ejecutivo",
    exec_summary.get("overview") or summary.get("executive_message") or "Informacion no disponible en los datos proporcionados.",
    "",
    "## 3. Indicadores Clave",
    f"- Score general: {summary.get('score', 'n/a')}",
    f"- Riesgo alto: {summary.get('high_risk', 'n/a')}",
    f"- Alertas activas: {summary.get('alerts', 'n/a')}",
    f"- Riesgo proyectado: {summary.get('forecast_high', 'n/a')}",
    "",
    "## 4. Decisiones Sugeridas",
  ]
  if decisions:
    for idx, item in enumerate(decisions, start=1):
      action = str(item.get("action") or "Decision sin descripcion")
      priority = _priority_label(item.get("priority")) or "Media"
      why = _decision_why_text(item)
      lines.append(f"{idx}. [{priority}] {action}")
      lines.append(f"   - Justificacion: {why}")
  else:
    lines.append("Informacion no disponible en los datos proporcionados.")

  lines.extend(["", "## 5. Alertas de Riesgo"])
  if alerts:
    for idx, item in enumerate(alerts, start=1):
      sev = str(item.get("severity") or "media").upper()
      signal = str(item.get("signal") or "Alerta sin detalle")
      lines.append(f"{idx}. ({sev}) {signal}")
  else:
    lines.append("Informacion no disponible en los datos proporcionados.")

  lines.extend(
    [
      "",
      "## 6. Trazabilidad Tecnica",
      f"- document_type: {trace.get('document_type', 'n/a')}",
      f"- rules_engine: {trace.get('rules_engine', 'n8n_workflow')}",
      f"- models_executed: {', '.join(str(m.get('name', 'n/a')) for m in (trace.get('models_executed') or [])) or 'n/a'}",
      "",
      "## 7. Limitaciones",
      "Este PRD se genera solo con los datos retornados por n8n. Si falta un dato critico, se reporta como no disponible.",
    ]
  )
  return "\n".join(lines)


def extract_prd_text_from_payload(payload: Dict[str, Any]) -> str:
  direct = ["prd_text", "prd_markdown", "markdown", "text", "content"]
  for key in direct:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
      return value.strip()

  nested = payload.get("result")
  if isinstance(nested, dict):
    for key in direct:
      value = nested.get(key)
      if isinstance(value, str) and value.strip():
        return value.strip()
  return ""


def _as_clean_list(value: Any, limit: int = 8) -> list[str]:
  if isinstance(value, list):
    out = [str(v).strip() for v in value if str(v).strip()]
    return out[:limit]
  if isinstance(value, str) and value.strip():
    return [value.strip()[:800]]
  return []


def _pdf_cut(value: Any, max_len: int = 800) -> str:
  txt = str(value or "").strip()
  if len(txt) <= max_len:
    return txt
  return txt[: max_len - 1].rstrip() + "…"


def _pdf_kv_table(rows: list[tuple[str, str]], _sts: dict, header: tuple[str, str] = ("Campo", "Valor")) -> Any:
  safe_rows = [(str(k).strip(), str(v).strip()) for k, v in rows if str(k).strip() and str(v).strip()]
  if not safe_rows:
    return Spacer(1, 0)
  rendered = [[
    Paragraph(xml_escape(header[0]), _sts["table_header"]),
    Paragraph(xml_escape(header[1]), _sts["table_header"]),
  ]]
  for k, v in safe_rows:
    rendered.append([
      Paragraph(xml_escape(_pdf_cut(k, 120)), _sts["table_cell"]),
      Paragraph(xml_escape(_pdf_cut(v, 500)), _sts["table_cell"]),
    ])
  total_w = A4[0] - 36 * mm
  tbl = Table(rendered, colWidths=[total_w * 0.36, total_w * 0.64], hAlign="LEFT", repeatRows=1)
  tbl.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), _rl_colors.HexColor("#102C45")),
    ("TEXTCOLOR", (0, 0), (-1, 0), _rl_colors.white),
    ("GRID", (0, 0), (-1, -1), 0.4, _rl_colors.HexColor("#D9E2EA")),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ("TOPPADDING", (0, 0), (-1, -1), 4),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
  ]))
  return tbl


def _pdf_risk_matrix_table(risk_rows: list[dict[str, Any]], _sts: dict) -> Any:
  if not risk_rows:
    return Spacer(1, 0)
  rendered = [[
    Paragraph("Dimension", _sts["table_header"]),
    Paragraph("Nivel", _sts["table_header"]),
    Paragraph("Interpretacion", _sts["table_header"]),
  ]]
  for row in risk_rows[:8]:
    dim = _pdf_cut(row.get("dimension"), 80)
    lvl = str(row.get("nivel") or "MEDIO").upper()
    interp = _pdf_cut(row.get("interpretacion"), 260)
    rendered.append([
      Paragraph(xml_escape(dim), _sts["table_cell"]),
      Paragraph(xml_escape(lvl), _sts["table_cell"]),
      Paragraph(xml_escape(interp), _sts["table_cell"]),
    ])
  total_w = A4[0] - 36 * mm
  tbl = Table(rendered, colWidths=[total_w * 0.24, total_w * 0.15, total_w * 0.61], hAlign="LEFT", repeatRows=1)
  style = [
    ("BACKGROUND", (0, 0), (-1, 0), _rl_colors.HexColor("#102C45")),
    ("TEXTCOLOR", (0, 0), (-1, 0), _rl_colors.white),
    ("GRID", (0, 0), (-1, -1), 0.4, _rl_colors.HexColor("#D9E2EA")),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ("TOPPADDING", (0, 0), (-1, -1), 4),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
  ]
  for i, row in enumerate(risk_rows[:8], start=1):
    lvl = str(row.get("nivel") or "MEDIO").upper()
    if lvl in {"ALTO", "HIGH", "CRITICO", "CRITICAL"}:
      bg = _rl_colors.HexColor("#FDECEA")
    elif lvl in {"BAJO", "LOW"}:
      bg = _rl_colors.HexColor("#E8F5E9")
    else:
      bg = _rl_colors.HexColor("#FFF8E1")
    style.append(("BACKGROUND", (0, i), (-1, i), bg))
  tbl.setStyle(TableStyle(style))
  return tbl


def _pdf_render_full_analysis(
  analysis_context: Dict[str, Any],
  _sts: dict,
  kpis: list[dict[str, Any]] | None = None,
  charts: list[dict[str, Any]] | None = None,
  alerts_table: list[dict[str, Any]] | None = None,
) -> list[Any]:
  story: list[Any] = []
  meta = analysis_context.get("meta", {}) or {}
  executive = analysis_context.get("executive", {}) or {}
  agents = analysis_context.get("agents", {}) or {}
  scores = analysis_context.get("scores", []) or []
  trace = analysis_context.get("traceability", {}) or {}
  decisions = analysis_context.get("decisions", []) or []
  risk_matrix = analysis_context.get("risk_matrix", []) or []

  story.append(Paragraph("1. Contexto y alcance", _sts["h2"]))
  story.append(Spacer(1, 4))
  meta_rows = [
    ("Documento", meta.get("document_name", "n/a")),
    ("Tipo de analisis", meta.get("report_type", "n/a")),
    ("Tipo de documento", meta.get("document_type", "n/a")),
    ("Fuente de decisiones", meta.get("decision_source", "n/a")),
    ("run_id", meta.get("run_id", "n/a")),
    ("Proveedor PRD", meta.get("provider", "n/a")),
  ]
  _loc = meta.get("location", "")
  if str(_loc).strip():
    meta_rows.append(("Contexto geografico", str(_loc)))
  story.append(_pdf_kv_table(meta_rows, _sts))
  story.append(Spacer(1, 10))

  story.append(Paragraph("2. Informe ejecutivo", _sts["h2"]))
  _overview = str(executive.get("overview") or "").strip()
  if _overview:
    story.append(Paragraph(xml_escape(_overview), _sts["body"]))
    story.append(Spacer(1, 6))
  _hallazgos = _as_clean_list(executive.get("hallazgos"), limit=8)
  if _hallazgos:
    story.append(Paragraph("Hallazgos clave", _sts["h3"]))
    for h in _hallazgos:
      story.append(Paragraph(f"&bull; {xml_escape(_pdf_cut(h, 420))}", _sts["bullet"]))
    story.append(Spacer(1, 4))
  _next_steps = _as_clean_list(executive.get("next_steps"), limit=8)
  if _next_steps:
    story.append(Paragraph("Proximos pasos recomendados", _sts["h3"]))
    for i, step in enumerate(_next_steps, start=1):
      story.append(Paragraph(f"{i}. {xml_escape(_pdf_cut(step, 420))}", _sts["body"]))
    story.append(Spacer(1, 8))

  story.append(Paragraph("3. Decisiones prioritarias", _sts["h2"]))
  _alerts = alerts_table or []
  if not _alerts and decisions:
    _alerts = [
      {
        "urgencia": str(d.get("urgencia") or d.get("priority") or "MEDIA"),
        "titulo": str(d.get("titulo") or d.get("action") or "Decision"),
        "tipo": str(d.get("tipo") or d.get("type") or "estrategica"),
        "descripcion": str(d.get("descripcion") or d.get("why") or ""),
      }
      for d in decisions[:12]
    ]
  if _alerts:
    story.append(_pdf_alerts_semaforo(_alerts, _sts))
  else:
    story.append(Paragraph("No se registraron decisiones prioritarias para este escenario.", _sts["body"]))
  story.append(Spacer(1, 10))

  story.append(Paragraph("4. Matriz de riesgo", _sts["h2"]))
  if risk_matrix:
    story.append(_pdf_risk_matrix_table(risk_matrix, _sts))
  else:
    story.append(Paragraph("No hay matriz de riesgo disponible en los datos de entrada.", _sts["body"]))
  story.append(Spacer(1, 10))

  story.append(Paragraph("5. Analisis de agentes IA", _sts["h2"]))
  ds = agents.get("data_scientist", {}) or {}
  af = agents.get("analista_financiero", {}) or {}
  am = agents.get("analista_mercado", {}) or {}

  story.append(Paragraph("5.1 Data Scientist", _sts["h3"]))
  ds_rows = [
    ("Score global", f"{_safe_float(ds.get('score_global'), 0.0):.1f}/100"),
    ("Score riesgo", f"{_safe_float(ds.get('score_riesgo'), 0.0):.1f}/100"),
    ("Score rentabilidad", f"{_safe_float(ds.get('score_rentabilidad'), 0.0):.1f}/100"),
  ]
  if ds.get("roi_estimado_pct") is not None:
    ds_rows.append(("ROI estimado", f"{_safe_float(ds.get('roi_estimado_pct'), 0.0):.2f}%"))
  story.append(_pdf_kv_table(ds_rows, _sts, header=("Metrica", "Valor")))
  ds_conclusions = _as_clean_list(ds.get("conclusiones"), limit=6)
  if ds_conclusions:
    story.append(Spacer(1, 4))
    story.append(Paragraph("Conclusiones", _sts["h3"]))
    for c in ds_conclusions:
      story.append(Paragraph(f"&bull; {xml_escape(_pdf_cut(c, 420))}", _sts["bullet"]))
  ds_alerts = ds.get("alertas_cuantitativas") or []
  if isinstance(ds_alerts, list) and ds_alerts:
    story.append(Spacer(1, 6))
    story.append(Paragraph("Alertas cuantitativas", _sts["h3"]))
    _rows = [[
      Paragraph("Campo", _sts["table_header"]),
      Paragraph("Documento", _sts["table_header"]),
      Paragraph("Benchmark", _sts["table_header"]),
      Paragraph("Desviacion", _sts["table_header"]),
      Paragraph("Nivel", _sts["table_header"]),
    ]]
    for a in ds_alerts[:10]:
      if not isinstance(a, dict):
        continue
      _rows.append([
        Paragraph(xml_escape(_pdf_cut(a.get("campo"), 60)), _sts["table_cell"]),
        Paragraph(xml_escape(_pdf_cut(a.get("valor_doc"), 80)), _sts["table_cell"]),
        Paragraph(xml_escape(_pdf_cut(a.get("benchmark"), 80)), _sts["table_cell"]),
        Paragraph(xml_escape(_pdf_cut(a.get("desviacion"), 60)), _sts["table_cell"]),
        Paragraph(xml_escape(_pdf_cut(a.get("nivel"), 20)), _sts["table_cell"]),
      ])
    if len(_rows) > 1:
      total_w = A4[0] - 36 * mm
      _tbl = Table(_rows, colWidths=[total_w * 0.20, total_w * 0.23, total_w * 0.23, total_w * 0.18, total_w * 0.16], hAlign="LEFT", repeatRows=1)
      _tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _rl_colors.HexColor("#102C45")),
        ("TEXTCOLOR", (0, 0), (-1, 0), _rl_colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, _rl_colors.HexColor("#D9E2EA")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
      ]))
      story.append(_tbl)
  story.append(Spacer(1, 8))

  story.append(Paragraph("5.2 Analista Financiero", _sts["h3"]))
  af_rows = [
    ("Score viabilidad", f"{_safe_float(af.get('score_viabilidad'), 0.0):.1f}/100"),
    ("Valoracion financiera", str(af.get("valoracion_financiera") or "N/D")),
  ]
  story.append(_pdf_kv_table(af_rows, _sts, header=("Metrica", "Valor")))
  _af_conc = str(af.get("conclusion_financiera") or "").strip()
  if _af_conc:
    story.append(Spacer(1, 4))
    story.append(Paragraph(xml_escape(_pdf_cut(_af_conc, 1100)), _sts["body"]))
  for _title, _items in [
    ("Fortalezas", _as_clean_list(af.get("fortalezas"), limit=6)),
    ("Debilidades", _as_clean_list(af.get("debilidades"), limit=6)),
  ]:
    if _items:
      story.append(Spacer(1, 4))
      story.append(Paragraph(_title, _sts["h3"]))
      for v in _items:
        story.append(Paragraph(f"&bull; {xml_escape(_pdf_cut(v, 420))}", _sts["bullet"]))
  _anomalias = af.get("anomalias_financieras") or []
  if isinstance(_anomalias, list) and _anomalias:
    story.append(Spacer(1, 4))
    story.append(Paragraph("Anomalias", _sts["h3"]))
    for a in _anomalias[:6]:
      if isinstance(a, dict):
        desc = str(a.get("descripcion") or a.get("anomalia") or "Anomalia detectada")
        rec = str(a.get("recomendacion") or "")
        line = f"{desc}. Recomendacion: {rec}" if rec else desc
      else:
        line = str(a)
      story.append(Paragraph(f"&bull; {xml_escape(_pdf_cut(line, 480))}", _sts["bullet"]))
  story.append(Spacer(1, 8))

  story.append(Paragraph("5.3 Analista de Mercado", _sts["h3"]))
  am_rows = [
    ("Posicionamiento de mercado", str(am.get("posicionamiento_mercado") or "N/D")),
    ("Tendencia de zona", str(am.get("tendencia_zona") or "N/D")),
  ]
  story.append(_pdf_kv_table(am_rows, _sts, header=("Metrica", "Valor")))
  _am_conc = str(am.get("conclusion_mercado") or "").strip()
  if _am_conc:
    story.append(Spacer(1, 4))
    story.append(Paragraph(xml_escape(_pdf_cut(_am_conc, 1100)), _sts["body"]))
  for _title, _items in [
    ("Oportunidades", _as_clean_list(am.get("oportunidades"), limit=6)),
    ("Amenazas", _as_clean_list(am.get("amenazas"), limit=6)),
  ]:
    if _items:
      story.append(Spacer(1, 4))
      story.append(Paragraph(_title, _sts["h3"]))
      for v in _items:
        story.append(Paragraph(f"&bull; {xml_escape(_pdf_cut(v, 420))}", _sts["bullet"]))
  story.append(Spacer(1, 10))

  story.append(Paragraph("6. KPIs y analisis visual", _sts["h2"]))
  if kpis:
    story.append(_pdf_kpi_table(kpis, _sts))
    story.append(Spacer(1, 8))
  if charts:
    story.append(Paragraph("Visualizaciones", _sts["h3"]))
    for ch in charts:
      img = _pdf_render_chart(ch, width_mm=170)
      if img is not None:
        story.append(Paragraph(xml_escape(str(ch.get("title", "Grafico"))), _sts["body"]))
        story.append(Spacer(1, 3))
        story.append(img)
        story.append(Spacer(1, 8))
  if not kpis and not charts:
    story.append(Paragraph("No hay KPIs o visualizaciones disponibles para este escenario.", _sts["body"]))
  story.append(Spacer(1, 8))

  story.append(Paragraph("7. Scores consolidados", _sts["h2"]))
  _score_rows = []
  for sc in scores:
    if not isinstance(sc, dict):
      continue
    label = str(sc.get("label") or "").strip()
    if not label:
      continue
    val = _safe_float(sc.get("value"), 0.0)
    note = str(sc.get("note") or "").strip()
    _score_rows.append((label, f"{val:.0f}/100", note))
  if _score_rows:
    rendered = [[
      Paragraph("Score", _sts["table_header"]),
      Paragraph("Valor", _sts["table_header"]),
      Paragraph("Interpretacion", _sts["table_header"]),
    ]]
    for label, val, note in _score_rows:
      rendered.append([
        Paragraph(xml_escape(_pdf_cut(label, 80)), _sts["table_cell"]),
        Paragraph(xml_escape(val), _sts["table_cell"]),
        Paragraph(xml_escape(_pdf_cut(note or "Sin comentario", 260)), _sts["table_cell"]),
      ])
    total_w = A4[0] - 36 * mm
    tbl = Table(rendered, colWidths=[total_w * 0.33, total_w * 0.14, total_w * 0.53], hAlign="LEFT", repeatRows=1)
    tbl.setStyle(TableStyle([
      ("BACKGROUND", (0, 0), (-1, 0), _rl_colors.HexColor("#102C45")),
      ("TEXTCOLOR", (0, 0), (-1, 0), _rl_colors.white),
      ("GRID", (0, 0), (-1, -1), 0.4, _rl_colors.HexColor("#D9E2EA")),
      ("VALIGN", (0, 0), (-1, -1), "TOP"),
      ("LEFTPADDING", (0, 0), (-1, -1), 5),
      ("RIGHTPADDING", (0, 0), (-1, -1), 5),
      ("TOPPADDING", (0, 0), (-1, -1), 4),
      ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(tbl)
  else:
    story.append(Paragraph("No hay scores consolidados disponibles.", _sts["body"]))
  story.append(Spacer(1, 8))

  story.append(Paragraph("8. Trazabilidad tecnica", _sts["h2"]))
  _trace_rows = [
    ("Fuente", trace.get("fuente") or trace.get("source_file") or "n/a"),
    ("Registros procesados", trace.get("num_registros_procesados") or trace.get("num_records") or "n/a"),
    ("Modelos ejecutados", ", ".join(str(m.get("name", "")) for m in (trace.get("models_executed") or [])) or "n/a"),
    ("Regiones analizadas", ", ".join(str(r) for r in (trace.get("regiones_analizadas") or trace.get("regions") or [])) or "n/a"),
  ]
  story.append(_pdf_kv_table(_trace_rows, _sts))
  _quality_alerts = _as_clean_list(trace.get("alertas_calidad"), limit=8)
  if _quality_alerts:
    story.append(Spacer(1, 4))
    story.append(Paragraph("Alertas de calidad detectadas", _sts["h3"]))
    for a in _quality_alerts:
      story.append(Paragraph(f"&bull; {xml_escape(_pdf_cut(a, 420))}", _sts["bullet"]))

  story.append(Spacer(1, 10))
  return story


def _analysis_context_to_markdown(analysis_context: Dict[str, Any]) -> str:
  meta = analysis_context.get("meta", {}) or {}
  executive = analysis_context.get("executive", {}) or {}
  decisions = analysis_context.get("decisions", []) or []
  risk_matrix = analysis_context.get("risk_matrix", []) or []
  agents = analysis_context.get("agents", {}) or {}
  scores = analysis_context.get("scores", []) or []
  trace = analysis_context.get("traceability", {}) or {}

  lines: list[str] = []
  lines.append("# PRD Ejecutivo Consolidado")
  lines.append("")
  lines.append("## 1. Contexto y alcance")
  lines.append(f"- Documento: {meta.get('document_name', 'n/a')}")
  lines.append(f"- Tipo de análisis: {meta.get('report_type', 'n/a')}")
  lines.append(f"- Tipo de documento: {meta.get('document_type', 'n/a')}")
  lines.append(f"- Fuente de decisiones: {meta.get('decision_source', 'n/a')}")
  lines.append(f"- run_id: {meta.get('run_id', 'n/a')}")
  if str(meta.get("location", "")).strip():
    lines.append(f"- Contexto geográfico: {meta.get('location')}")

  lines.append("")
  lines.append("## 2. Informe ejecutivo")
  overview = str(executive.get("overview") or "").strip()
  lines.append(overview if overview else "Información no disponible.")
  hall = _as_clean_list(executive.get("hallazgos"), limit=8)
  if hall:
    lines.append("")
    lines.append("### Hallazgos clave")
    for h in hall:
      lines.append(f"- {_pdf_cut(h, 420)}")
  nxt = _as_clean_list(executive.get("next_steps"), limit=8)
  if nxt:
    lines.append("")
    lines.append("### Próximos pasos")
    for i, s in enumerate(nxt, start=1):
      lines.append(f"{i}. {_pdf_cut(s, 420)}")

  lines.append("")
  lines.append("## 3. Decisiones prioritarias")
  if decisions:
    for d in decisions[:12]:
      urg = str(d.get("urgencia") or d.get("priority") or "MEDIA").upper()
      tit = str(d.get("titulo") or d.get("action") or "Decisión")
      desc = str(d.get("descripcion") or d.get("why") or "")
      lines.append(f"- [{urg}] {_pdf_cut(tit, 220)}")
      if desc:
        lines.append(f"  - {_pdf_cut(desc, 360)}")
  else:
    lines.append("- No se registraron decisiones prioritarias.")

  lines.append("")
  lines.append("## 4. Matriz de riesgo")
  if risk_matrix:
    for r in risk_matrix[:8]:
      dim = str(r.get("dimension") or "Dimension")
      lvl = str(r.get("nivel") or "MEDIO").upper()
      interp = str(r.get("interpretacion") or "")
      lines.append(f"- {dim}: {lvl}{(' · ' + _pdf_cut(interp, 240)) if interp else ''}")
  else:
    lines.append("- Sin matriz de riesgo disponible.")

  ds = agents.get("data_scientist", {}) or {}
  af = agents.get("analista_financiero", {}) or {}
  am = agents.get("analista_mercado", {}) or {}
  lines.append("")
  lines.append("## 5. Análisis de agentes IA")
  lines.append("### Data Scientist")
  lines.append(f"- Score global: {_safe_float(ds.get('score_global'), 0.0):.1f}/100")
  lines.append(f"- Score riesgo: {_safe_float(ds.get('score_riesgo'), 0.0):.1f}/100")
  lines.append(f"- Score rentabilidad: {_safe_float(ds.get('score_rentabilidad'), 0.0):.1f}/100")
  if ds.get("roi_estimado_pct") is not None:
    lines.append(f"- ROI estimado: {_safe_float(ds.get('roi_estimado_pct'), 0.0):.2f}%")
  for c in _as_clean_list(ds.get("conclusiones"), limit=5):
    lines.append(f"- {_pdf_cut(c, 320)}")

  lines.append("")
  lines.append("### Analista Financiero")
  lines.append(f"- Score viabilidad: {_safe_float(af.get('score_viabilidad'), 0.0):.1f}/100")
  lines.append(f"- Valoración financiera: {af.get('valoracion_financiera', 'N/D')}")
  af_conc = str(af.get("conclusion_financiera") or "").strip()
  if af_conc:
    lines.append(f"- Conclusión: {_pdf_cut(af_conc, 420)}")
  for v in _as_clean_list(af.get("fortalezas"), limit=4):
    lines.append(f"- Fortaleza: {_pdf_cut(v, 220)}")
  for v in _as_clean_list(af.get("debilidades"), limit=4):
    lines.append(f"- Debilidad: {_pdf_cut(v, 220)}")

  lines.append("")
  lines.append("### Analista de Mercado")
  lines.append(f"- Posicionamiento: {am.get('posicionamiento_mercado', 'N/D')}")
  lines.append(f"- Tendencia: {am.get('tendencia_zona', 'N/D')}")
  am_conc = str(am.get("conclusion_mercado") or "").strip()
  if am_conc:
    lines.append(f"- Conclusión: {_pdf_cut(am_conc, 420)}")
  for v in _as_clean_list(am.get("oportunidades"), limit=4):
    lines.append(f"- Oportunidad: {_pdf_cut(v, 220)}")
  for v in _as_clean_list(am.get("amenazas"), limit=4):
    lines.append(f"- Amenaza: {_pdf_cut(v, 220)}")

  lines.append("")
  lines.append("## 6. Scores consolidados")
  if scores:
    for sc in scores:
      if not isinstance(sc, dict):
        continue
      lbl = str(sc.get("label") or "").strip()
      if not lbl:
        continue
      val = _safe_float(sc.get("value"), 0.0)
      note = str(sc.get("note") or "").strip()
      lines.append(f"- {lbl}: {val:.0f}/100{(' · ' + _pdf_cut(note, 180)) if note else ''}")
  else:
    lines.append("- Sin scores consolidados.")

  lines.append("")
  lines.append("## 7. Trazabilidad técnica")
  lines.append(f"- Fuente: {trace.get('fuente') or trace.get('source_file') or 'n/a'}")
  lines.append(f"- Registros procesados: {trace.get('num_registros_procesados') or trace.get('num_records') or 'n/a'}")
  lines.append(
    "- Modelos ejecutados: "
    + (
      ", ".join(str(m.get("name", "")) for m in (trace.get("models_executed") or []))
      or "n/a"
    )
  )
  lines.append(
    "- Regiones analizadas: "
    + (
      ", ".join(str(r) for r in (trace.get("regiones_analizadas") or trace.get("regions") or []))
      or "n/a"
    )
  )
  for a in _as_clean_list(trace.get("alertas_calidad"), limit=6):
    lines.append(f"- Alerta de calidad: {_pdf_cut(a, 260)}")

  return "\n".join(lines).strip()


def build_prd_pdf_bytes(
  prd_text: str,
  document_name: str = "PRD_Analisis_Inmobiliario",
  provider: str = "openai",
  # pro options
  kpis: list[dict[str, Any]] | None = None,
  charts: list[dict[str, Any]] | None = None,
  alerts_table: list[dict[str, Any]] | None = None,
  analysis_context: Dict[str, Any] | None = None,
  # legacy compat
  title: str | None = None,
) -> bytes:
  """
  Pro PDF builder:
  - kpis:         [{"label":"...", "value":"..."}]  → tarjetas KPI
  - charts:       [{"type":"bar","title":"...", "x":[...], "y":[...]}] → gráficos matplotlib
  - alerts_table: [{"urgencia":"ALTA","titulo":"...","tipo":"...","descripcion":"..."}] → semáforo
  """
  document_name = document_name or title or "PRD_Analisis_Inmobiliario"
  buf = io.BytesIO()
  doc = SimpleDocTemplate(
    buf,
    pagesize=A4,
    leftMargin=18 * mm,
    rightMargin=18 * mm,
    topMargin=20 * mm,
    bottomMargin=18 * mm,
    title=document_name,
    author="Grupo Insur AI Decision App",
  )
  _sts = _build_pdf_styles()
  story: list[Any] = []
  today = datetime.now().strftime("%d/%m/%Y %H:%M")

  # ── Portada compacta ─────────────────────────────────────────────────────
  story.append(Paragraph("GRUPO INSUR · PRD EJECUTIVO", _sts["title"]))
  story.append(Paragraph(f"Documento: {document_name}", _sts["meta"]))
  story.append(Paragraph(f"Generado: {today} · Fuente: {provider}", _sts["meta"]))
  story.append(Spacer(1, 12))

  if analysis_context:
    story.extend(_pdf_render_full_analysis(
      analysis_context=analysis_context,
      _sts=_sts,
      kpis=kpis,
      charts=charts,
      alerts_table=alerts_table,
    ))
  else:
    # ── KPI cards ────────────────────────────────────────────────────────────
    if kpis:
      story.append(Paragraph("Indicadores clave", _sts["h2"]))
      story.append(Spacer(1, 6))
      story.append(_pdf_kpi_table(kpis, _sts))
      story.append(Spacer(1, 12))

    # ── Semáforo de alertas ───────────────────────────────────────────────────
    if alerts_table:
      story.append(Paragraph("Alertas y Decisiones Prioritarias", _sts["h2"]))
      story.append(Spacer(1, 6))
      story.append(_pdf_alerts_semaforo(alerts_table, _sts))
      story.append(Spacer(1, 12))

    # ── Gráficos matplotlib (opcional) ────────────────────────────────────────
    if charts:
      story.append(Paragraph("Visualizaciones", _sts["h2"]))
      story.append(Spacer(1, 6))
      for ch in charts:
        img = _pdf_render_chart(ch, width_mm=170)
        if img is not None:
          story.append(Paragraph(xml_escape(str(ch.get("title", "Grafico"))), _sts["h3"]))
          story.append(Spacer(1, 3))
          story.append(img)
          story.append(Spacer(1, 10))

  # ── Cuerpo PRD (markdown → paragraphs + tablas) ───────────────────────────
  _include_appendix = bool(
    analysis_context
    and str((analysis_context or {}).get("include_prd_appendix", "")).lower() in {"1", "true", "yes", "on"}
  )
  if prd_text.strip() and (not analysis_context or _include_appendix):
    if analysis_context and _include_appendix:
      story.append(Paragraph("9. Anexo PRD narrativo", _sts["h2"]))
      story.append(Spacer(1, 4))
    story.extend(_pdf_render_markdownish(prd_text, _sts))

  doc.build(
    story,
    onFirstPage=_pdf_draw_header_footer(document_name),
    onLaterPages=_pdf_draw_header_footer(document_name),
  )
  return buf.getvalue()


# ── PDF helpers ───────────────────────────────────────────────────────────────

def _build_pdf_styles() -> dict[str, ParagraphStyle]:
  base = getSampleStyleSheet()
  title = ParagraphStyle("_prd_title", parent=base["Title"],
    fontName="Helvetica-Bold", fontSize=14, leading=18,
    textColor=_rl_colors.HexColor("#102C45"))
  meta = ParagraphStyle("_prd_meta", parent=base["Normal"],
    fontName="Helvetica", fontSize=9, leading=12,
    textColor=_rl_colors.HexColor("#5E6B77"))
  h1 = ParagraphStyle("_prd_h1", parent=base["Heading1"],
    fontName="Helvetica-Bold", fontSize=12, leading=15,
    textColor=_rl_colors.HexColor("#102C45"), spaceBefore=8)
  h2 = ParagraphStyle("_prd_h2", parent=base["Heading2"],
    fontName="Helvetica-Bold", fontSize=10.8, leading=14,
    textColor=_rl_colors.HexColor("#1D3E5C"), spaceBefore=6)
  h3 = ParagraphStyle("_prd_h3", parent=base["Heading3"],
    fontName="Helvetica-Bold", fontSize=10, leading=13,
    textColor=_rl_colors.HexColor("#1D3E5C"), spaceBefore=4)
  body = ParagraphStyle("_prd_body", parent=base["BodyText"],
    fontName="Helvetica", fontSize=9.6, leading=13,
    textColor=_rl_colors.HexColor("#1B2733"))
  bullet = ParagraphStyle("_prd_bullet", parent=body, leftIndent=12, spaceBefore=1)
  kpi_label = ParagraphStyle("_prd_kpi_lbl", parent=body,
    fontName="Helvetica", fontSize=8.5, leading=11,
    textColor=_rl_colors.HexColor("#5E6B77"))
  kpi_value = ParagraphStyle("_prd_kpi_val", parent=body,
    fontName="Helvetica-Bold", fontSize=13, leading=15,
    textColor=_rl_colors.HexColor("#102C45"))
  th = ParagraphStyle("_prd_th", parent=body,
    fontName="Helvetica-Bold", fontSize=8.8, leading=11,
    textColor=_rl_colors.white)
  td = ParagraphStyle("_prd_td", parent=body,
    fontName="Helvetica", fontSize=8.6, leading=11,
    textColor=_rl_colors.HexColor("#1B2733"))
  table_line = ParagraphStyle("_prd_tl", parent=body,
    fontName="Courier", fontSize=8.5, leading=11,
    textColor=_rl_colors.HexColor("#2F3B46"))
  return {
    "title": title, "meta": meta, "h1": h1, "h2": h2, "h3": h3,
    "body": body, "bullet": bullet, "kpi_label": kpi_label, "kpi_value": kpi_value,
    "table_header": th, "table_cell": td, "table_line": table_line,
  }


def _pdf_draw_header_footer(document_name: str):
  def _fn(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(_rl_colors.HexColor("#5E6B77"))
    canvas.drawString(18 * mm, A4[1] - 13 * mm, document_name[:90])
    canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Página {doc.page}")
    canvas.restoreState()
  return _fn


def _pdf_kpi_table(kpis: list[dict[str, Any]], _sts: dict) -> Any:
  items = [(str(k.get("label", "")), str(k.get("value", "")))
           for k in kpis if k.get("label") and k.get("value")]
  if not items:
    return Spacer(1, 0)
  rows, row = [], []
  for label, value in items:
    # Avoid KeepTogether inside table cells: ReportLab can compute absurd row heights.
    safe_label = xml_escape(label.strip())[:120]
    safe_value = xml_escape(value.strip())[:160]
    row.append([
      Paragraph(safe_label, _sts["kpi_label"]),
      Paragraph(safe_value, _sts["kpi_value"]),
    ])
    if len(row) == 2:
      rows.append(row); row = []
  if row:
    row.append(""); rows.append(row)
  col_w = (A4[0] - 36 * mm) / 2
  tbl = Table(rows, colWidths=[col_w, col_w], hAlign="LEFT")
  tbl.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, -1), _rl_colors.HexColor("#F0F4F8")),
    ("BOX", (0, 0), (-1, -1), 0.6, _rl_colors.HexColor("#D9E2EA")),
    ("INNERGRID", (0, 0), (-1, -1), 0.6, _rl_colors.HexColor("#D9E2EA")),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("LEFTPADDING", (0, 0), (-1, -1), 10),
    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ("TOPPADDING", (0, 0), (-1, -1), 8),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
  ]))
  return tbl


def _pdf_alerts_semaforo(alerts: list[dict[str, Any]], _sts: dict) -> Any:
  """Tabla tipo semáforo: Severidad | Alerta | Tipo | Recomendación"""
  _SEV_COLOR = {
    "ALTA": _rl_colors.HexColor("#FDECEA"),
    "CRITICA": _rl_colors.HexColor("#FDECEA"),
    "MEDIA": _rl_colors.HexColor("#FFF8E1"),
    "BAJA": _rl_colors.HexColor("#E8F5E9"),
  }
  _SEV_TEXT = {
    "ALTA": _rl_colors.HexColor("#C62828"),
    "CRITICA": _rl_colors.HexColor("#B71C1C"),
    "MEDIA": _rl_colors.HexColor("#E65100"),
    "BAJA": _rl_colors.HexColor("#2E7D32"),
  }
  header = [
    Paragraph("Severidad", _sts["table_header"]),
    Paragraph("Alerta / Decisión", _sts["table_header"]),
    Paragraph("Tipo", _sts["table_header"]),
    Paragraph("Recomendación", _sts["table_header"]),
  ]
  rows = [header]
  for a in alerts[:12]:
    sev = str(a.get("urgencia") or a.get("severidad") or "MEDIA").upper()
    titulo = str(a.get("titulo") or a.get("action") or "—")
    tipo = str(a.get("tipo") or a.get("type") or "—")
    desc = str(a.get("descripcion") or a.get("why") or "—")
    sev_p = Paragraph(xml_escape(sev), ParagraphStyle(
      "_sev_cell", parent=_sts["table_cell"],
      fontName="Helvetica-Bold",
      textColor=_SEV_TEXT.get(sev, _rl_colors.HexColor("#333333")),
    ))
    rows.append([
      sev_p,
      Paragraph(xml_escape(titulo[:120]), _sts["table_cell"]),
      Paragraph(xml_escape(tipo[:40]), _sts["table_cell"]),
      Paragraph(xml_escape(desc[:160]), _sts["table_cell"]),
    ])
  total_w = A4[0] - 36 * mm
  col_ws = [total_w * 0.11, total_w * 0.37, total_w * 0.15, total_w * 0.37]
  tbl = Table(rows, colWidths=col_ws, hAlign="LEFT", repeatRows=1)
  ts = [
    ("BACKGROUND", (0, 0), (-1, 0), _rl_colors.HexColor("#102C45")),
    ("TEXTCOLOR", (0, 0), (-1, 0), _rl_colors.white),
    ("GRID", (0, 0), (-1, -1), 0.4, _rl_colors.HexColor("#D9E2EA")),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ("TOPPADDING", (0, 0), (-1, -1), 4),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
  ]
  for i, a in enumerate(alerts[:12], start=1):
    sev = str(a.get("urgencia") or a.get("severidad") or "MEDIA").upper()
    bg = _SEV_COLOR.get(sev, _rl_colors.white)
    ts.append(("BACKGROUND", (0, i), (-1, i), bg))
  tbl.setStyle(TableStyle(ts))
  return tbl


def _pdf_render_markdownish(prd_text: str, _sts: dict) -> list[Any]:
  content: list[Any] = []
  lines = list(prd_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))
  i = 0
  while i < len(lines):
    line = lines[i]
    if not line.strip():
      content.append(Spacer(1, 4)); i += 1; continue
    if line.startswith("# "):
      content.append(Paragraph(xml_escape(line[2:].strip()), _sts["h1"]))
      content.append(Spacer(1, 6)); i += 1; continue
    if line.startswith("## "):
      content.append(Paragraph(xml_escape(line[3:].strip()), _sts["h2"]))
      content.append(Spacer(1, 5)); i += 1; continue
    if line.startswith("### "):
      content.append(Paragraph(xml_escape(line[4:].strip()), _sts["h3"]))
      content.append(Spacer(1, 4)); i += 1; continue
    if line.startswith("- "):
      content.append(Paragraph(f"&bull; {xml_escape(line[2:].strip())}", _sts["bullet"]))
      i += 1; continue
    # Tabla markdown
    if line.lstrip().startswith("|"):
      tbl_lines: list[str] = []
      while i < len(lines) and lines[i].lstrip().startswith("|"):
        tbl_lines.append(lines[i].strip()); i += 1
      parsed = _pdf_parse_md_table(tbl_lines)
      if parsed:
        content.append(_pdf_md_table(parsed, _sts))
        content.append(Spacer(1, 8))
      else:
        for tl in tbl_lines:
          content.append(Paragraph(xml_escape(tl), _sts["table_line"]))
        content.append(Spacer(1, 6))
      continue
    content.append(Paragraph(xml_escape(line), _sts["body"]))
    i += 1
  return content


def _pdf_parse_md_table(lines: list[str]) -> list[list[str]] | None:
  raw: list[list[str]] = []
  for ln in lines:
    ln = ln.strip()
    if not (ln.startswith("|") and ln.endswith("|")):
      return None
    raw.append([p.strip() for p in ln.strip("|").split("|")])
  if len(raw) < 2:
    return None
  if all(set(s.replace(":", "").replace("-", "")) <= {""} for s in raw[1]):
    raw.pop(1)
  return raw


def _pdf_md_table(data: list[list[str]], _sts: dict) -> Any:
  rendered = []
  for r, row in enumerate(data):
    st_p = _sts["table_header"] if r == 0 else _sts["table_cell"]
    rendered.append([Paragraph(xml_escape(c), st_p) for c in row])
  n_cols = max(len(r) for r in rendered)
  col_w = (A4[0] - 36 * mm) / n_cols
  tbl = Table(rendered, colWidths=[col_w] * n_cols, hAlign="LEFT")
  tbl.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), _rl_colors.HexColor("#102C45")),
    ("TEXTCOLOR", (0, 0), (-1, 0), _rl_colors.white),
    ("GRID", (0, 0), (-1, -1), 0.4, _rl_colors.HexColor("#D9E2EA")),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ("TOPPADDING", (0, 0), (-1, -1), 4),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
  ]))
  return tbl


def _pdf_render_chart(ch: dict[str, Any], width_mm: float = 170) -> Any | None:
  try:
    import matplotlib
    matplotlib.use("Agg")  # non-interactive backend
    import matplotlib.pyplot as plt
  except Exception:
    return None
  ctype = str(ch.get("type") or "bar").lower()
  x = ch.get("x"); y = ch.get("y")
  # support "series" format
  if not x and ch.get("series"):
    s0 = (ch["series"] or [{}])[0]
    x = x or s0.get("x"); y = y or s0.get("y")
  fig, ax = plt.subplots(figsize=(7, 3))
  try:
    if ctype == "bar":
      ax.bar(x or [], y or [], color="#1D3E5C")
    elif ctype == "line":
      ax.plot(x or [], y or [], color="#1D3E5C", marker="o")
    elif ctype == "pie":
      ax.pie(y or [], labels=x or [], autopct="%1.0f%%",
             colors=["#1D3E5C", "#E8720C", "#2E7D32", "#C62828", "#C4922A"])
    elif ctype == "hist":
      ax.hist(y or [], bins=min(18, max(5, len(y or []))), color="#1D3E5C", edgecolor="white")
    else:
      ax.bar(x or [], y or [], color="#1D3E5C")
    ax.set_facecolor("#F8FAFC")
    fig.patch.set_facecolor("#F8FAFC")
    ax.tick_params(labelsize=8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
  except Exception:
    plt.close(fig); return None
  img_buf = io.BytesIO()
  fig.savefig(img_buf, format="png", dpi=150, bbox_inches="tight")
  plt.close(fig)
  img_buf.seek(0)
  img = _rl_Image(img_buf)
  img.drawWidth = width_mm * mm
  img.drawHeight = img.imageHeight * (img.drawWidth / img.imageWidth)
  return img


def suppliers_df(result: Dict[str, Any]) -> pd.DataFrame:
  rows = ((result.get("segmentation") or {}).get("output") or {}).get("suppliers_segmented", [])
  return pd.DataFrame(rows) if rows else pd.DataFrame()


def _safe_float(value: Any, default: float = 0.0) -> float:
  try:
    return float(value)
  except (TypeError, ValueError):
    return default


def _fmt_int(value: Any) -> str:
  try:
    return f"{int(float(value)):,}".replace(",", ".")
  except (TypeError, ValueError):
    return "n/a"


def _fmt_money(value: Any) -> str:
  try:
    v = float(value)
    if v >= 1_000_000:
      return f" {v/1_000_000:.2f}M"
    return f" {v:,.0f}".replace(",", ".")
  except (TypeError, ValueError):
    return "n/a"


def _fmt_pct(value: Any) -> str:
  try:
    return f"{float(value) * 100:.1f}%"
  except (TypeError, ValueError):
    return "n/a"


def _priority_label(priority: Any) -> str:
  p = str(priority or "").strip().lower()
  if "alta" in p:
    return "Alta"
  if "media" in p:
    return "Media"
  if "baja" in p:
    return "Baja"
  return ""


def _priority_icon(priority: Any) -> str:
  p = str(priority or "").strip().lower()
  if "alta" in p:
    return "A"
  if "media" in p:
    return "M"
  return "B"


def _decision_actor(decision: Dict[str, Any], doc_type: str) -> str:
  supplier = str(decision.get("supplier") or "").strip()
  if supplier:
    return supplier
  if doc_type == "commercial_report":
    return "Operacion comercial"
  if doc_type == "supplier_report":
    return "Gestion de proveedores"
  return "Activo inmobiliario"


def _decision_why_text(decision: Dict[str, Any]) -> str:
  why = decision.get("why") or []
  if isinstance(why, list) and why:
    return " ".join(str(x) for x in why if str(x).strip()) or "Sin evidencia adicional."
  if isinstance(why, str) and why.strip():
    return why
  return "Sin evidencia adicional."


def _score_class(score: float) -> str:
  if score >= 70:
    return "ok"
  if score >= 40:
    return "gold"
  return "danger"


def _plotly_update(fig: go.Figure) -> go.Figure:
  fig.update_layout(**PLOTLY_LAYOUT)
  return fig


# Chart helpers 
def gauge_chart(value: float, title: str, min_val: float = 0, max_val: float = 100) -> go.Figure:
  pct = max(0.0, min(1.0, (value - min_val) / max(max_val - min_val, 1)))
  if pct >= 0.70:
    bar_color = "#1A6B4A"
  elif pct >= 0.40:
    bar_color = "#C4922A"
  else:
    bar_color = "#C23B2A"

  fig = go.Figure(go.Indicator(
    mode="gauge+number",
    value=value,
    domain={"x": [0, 1], "y": [0, 1]},
    title={"text": title, "font": {"family": "Lato, sans-serif", "size": 13, "color": "#00417d"}},
    gauge={
      "axis": {"range": [min_val, max_val], "tickcolor": "#95989a", "tickfont": {"size": 10}},
      "bar": {"color": bar_color, "thickness": 0.7},
      "bgcolor": "rgba(0,65,125,0.04)",
      "borderwidth": 0,
      "steps": [
        {"range": [min_val, max_val * 0.40], "color": "rgba(198,40,40,0.08)"},
        {"range": [max_val * 0.40, max_val * 0.70], "color": "rgba(230,81,0,0.08)"},
        {"range": [max_val * 0.70, max_val], "color": "rgba(46,125,50,0.08)"},
      ],
      "threshold": {"line": {"color": "#00417d", "width": 2}, "thickness": 0.8, "value": value},
    },
    number={"font": {"family": "Lato, sans-serif", "size": 36, "color": bar_color}, "suffix": ""},
  ))
  fig.update_layout(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Lato, sans-serif", color="#1a1a1a"),
    height=220,
    margin=dict(l=20, r=20, t=40, b=10),
  )
  return fig


# Visual sections 
def render_executive_visuals(result: Dict[str, Any], doc_type: str, k: Dict[str, int], normalized: Dict[str, Any]) -> None:
  st.markdown(
    """
    <div style="display:flex;align-items:center;gap:14px;padding:16px 22px;
                background:linear-gradient(135deg,#e8f5e9 0%,#f5fdf6 100%);
                border-left:4px solid #2e7d32;border-radius:12px;margin:28px 0 18px;
                box-shadow:0 2px 8px rgba(46,125,50,0.08);">
      <div style="width:44px;height:44px;background:linear-gradient(135deg,#2e7d32,#1b5e20);
                  border-radius:11px;display:flex;align-items:center;justify-content:center;
                  flex-shrink:0;box-shadow:0 3px 8px rgba(27,94,32,0.3);">
        <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="1.8"
             stroke-linecap="round" stroke-linejoin="round" style="width:22px;height:22px;">
          <line x1="18" y1="20" x2="18" y2="10"/>
          <line x1="12" y1="20" x2="12" y2="4"/>
          <line x1="6" y1="20" x2="6" y2="14"/>
        </svg>
      </div>
      <div style="flex:1;">
        <div style="font-size:17px;font-weight:800;color:#1b5e20;letter-spacing:-0.3px;line-height:1.2;">
          KPIs Y ANALISIS VISUAL
        </div>
        <div style="font-size:12px;color:#4a8c4e;margin-top:3px;">
          Indicadores clave de rendimiento y graficas de distribucion
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
  )

  # Supplier report 
  if doc_type == "supplier_report":
    df = suppliers_df(result)
    if df.empty:
      st.info("No hay datos suficientes de proveedores para graficos ejecutivos.")
      return

    total = len(df)
    high = int((df["risk_tier"] == "HIGH").sum()) if "risk_tier" in df.columns else k.get("high_risk", 0)
    med = int((df["risk_tier"] == "MED").sum()) if "risk_tier" in df.columns else 0
    low = int((df["risk_tier"] == "LOW").sum()) if "risk_tier" in df.columns else 0
    avg_delay = _safe_float(df.get("avg_delay_days", pd.Series(dtype=float)).mean(), 0.0)
    avg_dep  = _safe_float(df.get("dependency_pct", pd.Series(dtype=float)).mean(), 0.0)

    high_pct = high / max(total, 1) * 100
    h_cls = "danger" if high_pct >= 25 else "gold" if high_pct >= 10 else "ok"
    st.markdown(
      f"""
      <div class="kpi-grid">
       <div class="kpi">
        <div class="kpi-label">Proveedores evaluados</div>
        <div class="kpi-value">{_fmt_int(total)}</div>
        <div class="kpi-hint">Total detectados en el documento</div>
       </div>
       <div class="kpi">
        <div class="kpi-label">Riesgo alto</div>
        <div class="kpi-value {h_cls}">{_fmt_int(high)}</div>
        <div class="kpi-hint">Requieren accion inmediata</div>
       </div>
       <div class="kpi">
        <div class="kpi-label">Riesgo medio</div>
        <div class="kpi-value gold">{_fmt_int(med)}</div>
        <div class="kpi-hint">Seguimiento cercano</div>
       </div>
       <div class="kpi">
        <div class="kpi-label">Dependencia media</div>
        <div class="kpi-value">{avg_dep:.0f}<span style="font-size:18px">%</span></div>
        <div class="kpi-hint">Exposicion promedio por proveedor</div>
       </div>
      </div>
      """,
      unsafe_allow_html=True,
    )

    # Progress bars
    st.markdown(
      f"""
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:20px;">
       <div class="card">
        <div class="card-title">Distribucion de riesgo</div>
        <div class="progress-wrap">
         <div class="progress-label"><span>Alto</span><span>{high}/{total}</span></div>
         <div class="progress-track"><div class="progress-fill danger" style="width:{high/max(total,1)*100:.1f}%"></div></div>
        </div>
        <div class="progress-wrap">
         <div class="progress-label"><span>Medio</span><span>{med}/{total}</span></div>
         <div class="progress-track"><div class="progress-fill" style="width:{med/max(total,1)*100:.1f}%"></div></div>
        </div>
        <div class="progress-wrap">
         <div class="progress-label"><span>Bajo</span><span>{low}/{total}</span></div>
         <div class="progress-track"><div class="progress-fill ok" style="width:{low/max(total,1)*100:.1f}%"></div></div>
        </div>
       </div>
       <div class="card">
        <div class="card-title">Indicadores operativos</div>
        <div class="progress-wrap">
         <div class="progress-label"><span>Retraso promedio</span><span>{avg_delay:.1f} dias</span></div>
         <div class="progress-track"><div class="progress-fill {'danger' if avg_delay>15 else 'gold' if avg_delay>7 else 'ok'}" style="width:{min(avg_delay/30*100,100):.1f}%"></div></div>
        </div>
        <div class="progress-wrap">
         <div class="progress-label"><span>Dependencia media</span><span>{avg_dep:.1f}%</span></div>
         <div class="progress-track"><div class="progress-fill {'danger' if avg_dep>50 else 'gold' if avg_dep>30 else 'ok'}" style="width:{min(avg_dep,100):.1f}%"></div></div>
        </div>
       </div>
      </div>
      """,
      unsafe_allow_html=True,
    )

    g1, g2 = st.columns(2)
    with g1:
      if "risk_tier" in df.columns:
        dist = df["risk_tier"].value_counts().rename_axis("risk_tier").reset_index(name="count")
        fig = px.pie(
          dist, names="risk_tier", values="count",
          title="Distribucion de riesgo",
          color="risk_tier", color_discrete_map=RISK_COLORS,
          hole=0.52,
        )
        fig.update_traces(textposition="outside", textinfo="label+percent",
                 marker=dict(line=dict(color="#FFFFFF", width=2)))
        _plotly_update(fig)
        st.plotly_chart(fig, use_container_width=True)

    with g2:
      needed = {"supplier_name", "dependency_pct", "incidents", "risk_tier"}
      if needed.issubset(df.columns):
        size_col = "risk_score" if "risk_score" in df.columns else None
        fig2 = px.scatter(
          df, x="dependency_pct", y="incidents",
          color="risk_tier", size=size_col,
          hover_name="supplier_name",
          title="Dependencia vs Incidencias",
          color_discrete_map=RISK_COLORS,
        )
        _plotly_update(fig2)
        fig2.update_layout(xaxis_title="Dependencia (%)", yaxis_title="Incidencias", legend_title_text="Riesgo")
        st.plotly_chart(fig2, use_container_width=True)
    return

  # Commercial report 
  if doc_type == "commercial_report":
    commercial_output = (((result.get("commercial") or {}).get("output")) or {})
    kpis_data = commercial_output.get("kpis", {}) or {}
    re_out = (((result.get("real_estate_models") or {}).get("output")) or {})
    mode = str(kpis_data.get("kpi_mode") or "").lower()
    if mode not in {"clientes", "operaciones"}:
      if _safe_float(kpis_data.get("total_clients"), 0.0) > 0:
        mode = "clientes"
      elif _safe_float(kpis_data.get("operations_total"), 0.0) > 0:
        mode = "operaciones"

    if mode == "operaciones":
      ops_total = _safe_float(kpis_data.get("operations_total"), 0.0)
      vol_total = _safe_float(kpis_data.get("volume_total_eur"), 0.0)
      avg_price = _safe_float(kpis_data.get("avg_price_eur"), 0.0)
      avg_m2 = _safe_float(kpis_data.get("avg_price_m2_eur"), 0.0)
      avg_margin = _safe_float(kpis_data.get("avg_margin_pct"), 0.0)
      conversion = _safe_float(kpis_data.get("conversion_rate"), 0.0)
      cancellation = _safe_float(kpis_data.get("cancellation_rate"), 0.0)
      sell_through = _safe_float(kpis_data.get("sell_through_rate"), 0.0)
      trend = str(kpis_data.get("trend", "flat")).upper()

      st.markdown(
        f"""
        <div class="kpi-grid">
         <div class="kpi">
          <div class="kpi-label">Operaciones</div>
          <div class="kpi-value">{_fmt_int(ops_total)}</div>
          <div class="kpi-hint">Total analizado en el documento</div>
         </div>
         <div class="kpi">
          <div class="kpi-label">Volumen total</div>
          <div class="kpi-value" style="font-size:26px">{_fmt_money(vol_total)}</div>
          <div class="kpi-hint">Valor acumulado del portafolio</div>
         </div>
         <div class="kpi">
          <div class="kpi-label">Precio medio</div>
          <div class="kpi-value" style="font-size:26px">{_fmt_money(avg_price)}</div>
          <div class="kpi-hint">Ticket promedio por operación</div>
         </div>
         <div class="kpi">
          <div class="kpi-label">Precio medio m2</div>
          <div class="kpi-value">{avg_m2:,.0f}<span style="font-size:16px"> €/m2</span></div>
          <div class="kpi-hint">Referencia unitaria promedio</div>
         </div>
        </div>
        """,
        unsafe_allow_html=True,
      )

      st.markdown(
        f"""
        <div class="kpi-grid">
         <div class="kpi">
          <div class="kpi-label">Margen medio</div>
          <div class="kpi-value {'ok' if avg_margin>=10 else 'gold' if avg_margin>=6 else 'danger'}">{avg_margin:.2f}<span style="font-size:18px">%</span></div>
          <div class="kpi-hint">Rentabilidad promedio detectada</div>
         </div>
         <div class="kpi">
          <div class="kpi-label">Conversion</div>
          <div class="kpi-value {'ok' if conversion>0.15 else 'gold' if conversion>0.07 else 'danger'}">{conversion*100:.1f}<span style="font-size:18px">%</span></div>
          <div class="kpi-hint">Cerradas + escritura sobre total</div>
         </div>
         <div class="kpi">
          <div class="kpi-label">Sell-through</div>
          <div class="kpi-value">{sell_through*100:.1f}<span style="font-size:18px">%</span></div>
          <div class="kpi-hint">Operaciones cerradas sobre total</div>
         </div>
         <div class="kpi">
          <div class="kpi-label">Tendencia</div>
          <div class="kpi-value" style="font-size:24px;margin-top:8px;">{trend}</div>
          <div class="kpi-hint">Ritmo comercial estimado</div>
         </div>
        </div>
        """,
        unsafe_allow_html=True,
      )

      # Barras de progreso comparativas (complemento visual)
      _benchmarks = [
        ("Conversion",   conversion,   0.15, "Cerradas + escritura sobre total. Benchmark: >15%"),
        ("Sell-through", sell_through, 0.80, "Operaciones cerradas sobre stock total. Benchmark: >80%"),
        ("Cancelacion",  cancellation, 0.10, "Reservas anuladas. Benchmark: <10%"),
        ("Margen",       avg_margin / 100.0 if avg_margin > 0 else 0.0, 0.10, "Rentabilidad neta media. Benchmark: >10%"),
      ]
      _rows = ""
      for _lbl, _val, _bench, _hint in _benchmarks:
        _pct = _val * 100
        _ok = (_val >= _bench) if _lbl != "Cancelacion" else (_val <= _bench)
        _color = "#2e7d32" if _ok else "#c4922a" if abs(_val - _bench) < _bench * 0.5 else "#c62828"
        _rows += f"""
        <div style="margin-bottom:14px;">
          <div style="display:flex;justify-content:space-between;font-size:12px;font-weight:700;color:{_color};margin-bottom:4px;">
            <span>{_lbl}</span><span>{_pct:.1f}%</span>
          </div>
          <div style="height:8px;border-radius:4px;background:rgba(149,152,154,.18);">
            <div style="height:100%;width:{min(_pct,100):.1f}%;background:{_color};border-radius:4px;"></div>
          </div>
          <div style="font-size:11px;color:var(--muted);margin-top:3px;">{_hint}</div>
        </div>"""
      st.markdown(
        f'<div class="card" style="margin-bottom:18px;"><div class="card-title">Indicadores comerciales vs benchmark</div><div style="margin-top:12px;">{_rows}</div></div>',
        unsafe_allow_html=True,
      )

      g1, g2 = st.columns(2)
      with g1:
        rate_df = pd.DataFrame([
          {"Indicador": "Conversion",   "Valor": round(conversion * 100, 1),   "Etiqueta": f"{conversion*100:.1f}%"},
          {"Indicador": "Sell-through", "Valor": round(sell_through * 100, 1), "Etiqueta": f"{sell_through*100:.1f}%"},
          {"Indicador": "Cancelacion",  "Valor": round(cancellation * 100, 1), "Etiqueta": f"{cancellation*100:.1f}%"},
        ])
        fig = px.bar(
          rate_df,
          x="Indicador",
          y="Valor",
          text="Etiqueta",
          title="Tasas comerciales clave (%)",
          color="Indicador",
          color_discrete_map={
            "Conversion":   "#1A6B4A",
            "Sell-through": "#00417d",
            "Cancelacion":  "#C23B2A",
          },
        )
        _plotly_update(fig)
        fig.update_traces(
          textposition="outside",
          textfont=dict(size=13, color="#1a1a1a", family="Lato, sans-serif"),
        )
        fig.update_layout(
          showlegend=False,
          yaxis_title="Porcentaje (%)",
          xaxis_title="",
          xaxis=dict(tickfont=dict(size=13, color="#1a1a1a"), tickangle=0),
          yaxis=dict(tickfont=dict(size=11, color="#666666"), range=[0, 115], ticksuffix="%"),
          uniformtext_minsize=11, uniformtext_mode="hide",
        )
        st.plotly_chart(fig, use_container_width=True)

      with g2:
        series = commercial_output.get("series", []) or []
        if series:
          sdf = pd.DataFrame(series)
          x_key = "label" if "label" in sdf.columns else next((k for k in ["month", "period", "date"] if k in sdf.columns), None)
          y_key = next((k for k in ["units_sold", "revenue_eur"] if k in sdf.columns), None)
          if x_key and y_key:
            fig2 = px.bar(
              sdf, x=x_key, y=y_key,
              text=y_key,
              title="Distribucion por estado de operacion",
              color=x_key,
              color_discrete_sequence=["#C4922A", "#1B4FD8", "#06B6D4", "#1A6B4A"],
            )
            _plotly_update(fig2)
            fig2.update_traces(textposition="outside", textfont=dict(size=11, color="#1a1a1a"))
            fig2.update_layout(
              showlegend=False, xaxis_title="", yaxis_title="Operaciones",
              xaxis=dict(tickfont=dict(size=12, color="#1a1a1a")),
              yaxis=dict(tickfont=dict(size=11, color="#666666")),
            )
            st.plotly_chart(fig2, use_container_width=True)
          else:
            # Resumen visual cuando no hay serie temporal
            _vol_ops = vol_total / max(ops_total, 1)
            st.markdown(
              f"""
              <div class="card">
                <div class="card-title">Resumen del portafolio de ventas</div>
                <div style="margin-top:14px;">
                  <div style="display:flex;justify-content:space-between;align-items:baseline;padding:8px 0;border-bottom:1px solid var(--line);">
                    <span style="font-size:12px;color:var(--muted);font-weight:700;">Operaciones analizadas</span>
                    <span style="font-size:20px;font-weight:900;color:var(--insur-blue);">{_fmt_int(ops_total)}</span>
                  </div>
                  <div style="display:flex;justify-content:space-between;align-items:baseline;padding:8px 0;border-bottom:1px solid var(--line);">
                    <span style="font-size:12px;color:var(--muted);font-weight:700;">Volumen total</span>
                    <span style="font-size:18px;font-weight:900;color:var(--insur-blue);">{_fmt_money(vol_total)}</span>
                  </div>
                  <div style="display:flex;justify-content:space-between;align-items:baseline;padding:8px 0;border-bottom:1px solid var(--line);">
                    <span style="font-size:12px;color:var(--muted);font-weight:700;">Ticket medio por operacion</span>
                    <span style="font-size:18px;font-weight:900;color:var(--insur-blue);">{_fmt_money(_vol_ops)}</span>
                  </div>
                  <div style="display:flex;justify-content:space-between;align-items:baseline;padding:8px 0;border-bottom:1px solid var(--line);">
                    <span style="font-size:12px;color:var(--muted);font-weight:700;">Margen medio estimado</span>
                    <span style="font-size:18px;font-weight:900;color:{'#2e7d32' if avg_margin>=10 else '#c4922a' if avg_margin>=6 else '#c62828'};">{avg_margin:.2f}%</span>
                  </div>
                  <div style="display:flex;justify-content:space-between;align-items:baseline;padding:8px 0;">
                    <span style="font-size:12px;color:var(--muted);font-weight:700;">Tendencia detectada</span>
                    <span style="font-size:16px;font-weight:900;color:var(--insur-blue);">{trend}</span>
                  </div>
                </div>
              </div>
              """,
              unsafe_allow_html=True,
            )
        else:
          _vol_ops = vol_total / max(ops_total, 1)
          st.markdown(
            f"""
            <div class="card">
              <div class="card-title">Resumen del portafolio de ventas</div>
              <div style="margin-top:14px;">
                <div style="display:flex;justify-content:space-between;align-items:baseline;padding:8px 0;border-bottom:1px solid var(--line);">
                  <span style="font-size:12px;color:var(--muted);font-weight:700;">Operaciones analizadas</span>
                  <span style="font-size:20px;font-weight:900;color:var(--insur-blue);">{_fmt_int(ops_total)}</span>
                </div>
                <div style="display:flex;justify-content:space-between;align-items:baseline;padding:8px 0;border-bottom:1px solid var(--line);">
                  <span style="font-size:12px;color:var(--muted);font-weight:700;">Volumen total</span>
                  <span style="font-size:18px;font-weight:900;color:var(--insur-blue);">{_fmt_money(vol_total)}</span>
                </div>
                <div style="display:flex;justify-content:space-between;align-items:baseline;padding:8px 0;border-bottom:1px solid var(--line);">
                  <span style="font-size:12px;color:var(--muted);font-weight:700;">Ticket medio por operacion</span>
                  <span style="font-size:18px;font-weight:900;color:var(--insur-blue);">{_fmt_money(_vol_ops)}</span>
                </div>
                <div style="display:flex;justify-content:space-between;align-items:baseline;padding:8px 0;border-bottom:1px solid var(--line);">
                  <span style="font-size:12px;color:var(--muted);font-weight:700;">Margen medio estimado</span>
                  <span style="font-size:18px;font-weight:900;color:{'#2e7d32' if avg_margin>=10 else '#c4922a' if avg_margin>=6 else '#c62828'};">{avg_margin:.2f}%</span>
                </div>
                <div style="display:flex;justify-content:space-between;align-items:baseline;padding:8px 0;">
                  <span style="font-size:12px;color:var(--muted);font-weight:700;">Tendencia detectada</span>
                  <span style="font-size:16px;font-weight:900;color:var(--insur-blue);">{trend}</span>
                </div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
          )
      return

    if mode == "clientes":
      total_clients = int(_safe_float(kpis_data.get("total_clients"), 0.0))
      avg_churn = _safe_float(kpis_data.get("avg_churn_score"), 0.0)
      retention = _safe_float(kpis_data.get("retention_rate"), max(0.0, 1.0 - avg_churn))
      high_clients = int(_safe_float(kpis_data.get("high_risk_clients"), 0.0))
      med_clients = int(_safe_float(kpis_data.get("medium_risk_clients"), 0.0))
      low_clients = int(_safe_float(kpis_data.get("low_risk_clients"), 0.0))
      trend = str(kpis_data.get("trend", "flat")).upper()

      st.markdown(
        f"""
        <div class="kpi-grid">
         <div class="kpi">
          <div class="kpi-label">Clientes analizados</div>
          <div class="kpi-value">{_fmt_int(total_clients)}</div>
          <div class="kpi-hint">Total de cartera evaluada</div>
         </div>
         <div class="kpi">
          <div class="kpi-label">Churn promedio</div>
          <div class="kpi-value {'danger' if avg_churn>0.55 else 'gold' if avg_churn>0.35 else 'ok'}">{avg_churn*100:.1f}<span style="font-size:18px">%</span></div>
          <div class="kpi-hint">Probabilidad media de fuga</div>
         </div>
         <div class="kpi">
          <div class="kpi-label">Retencion esperada</div>
          <div class="kpi-value {'ok' if retention>0.65 else 'gold' if retention>0.45 else 'danger'}">{retention*100:.1f}<span style="font-size:18px">%</span></div>
          <div class="kpi-hint">Clientes con permanencia esperada</div>
         </div>
         <div class="kpi">
          <div class="kpi-label">Tendencia</div>
          <div class="kpi-value" style="font-size:24px;margin-top:8px;">{trend}</div>
          <div class="kpi-hint">Evolucion de riesgo de cartera</div>
         </div>
        </div>
        """,
        unsafe_allow_html=True,
      )

      ops_total = _safe_float(kpis_data.get("operations_total"), 0.0)
      vol_total = _safe_float(kpis_data.get("volume_total_eur"), 0.0)
      avg_ops = _safe_float(kpis_data.get("avg_ops_per_client"), 0.0)
      rating_b = _safe_float(kpis_data.get("rating_b_ratio"), 0.0)
      rating_d = _safe_float(kpis_data.get("rating_d_ratio"), 0.0)

      st.markdown(
        f"""
        <div class="kpi-grid">
         <div class="kpi">
          <div class="kpi-label">Operaciones</div>
          <div class="kpi-value">{_fmt_int(ops_total)}</div>
          <div class="kpi-hint">Total de operaciones de la cartera</div>
         </div>
         <div class="kpi">
          <div class="kpi-label">Volumen total</div>
          <div class="kpi-value" style="font-size:26px">{_fmt_money(vol_total)}</div>
          <div class="kpi-hint">Volumen financiero agregado</div>
         </div>
         <div class="kpi">
          <div class="kpi-label">Ops por cliente</div>
          <div class="kpi-value">{avg_ops:.2f}</div>
          <div class="kpi-hint">Intensidad operativa media</div>
         </div>
         <div class="kpi">
          <div class="kpi-label">Rating B / D</div>
          <div class="kpi-value" style="font-size:24px">{rating_b*100:.1f}% / {rating_d*100:.1f}%</div>
          <div class="kpi-hint">Distribucion crediticia relevante</div>
         </div>
        </div>
        """,
        unsafe_allow_html=True,
      )

      # Barras de progreso de distribución (complemento visual al gráfico)
      _total_c = max(total_clients, high_clients + med_clients + low_clients, 1)
      st.markdown(
        f"""
        <div class="card" style="margin-bottom:18px;">
          <div class="card-title">Distribucion de riesgo de cartera</div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;margin-top:12px;">
            <div>
              <div style="display:flex;justify-content:space-between;font-size:12px;font-weight:700;color:#C23B2A;margin-bottom:4px;">
                <span>Alto riesgo</span><span>{high_clients} clientes</span>
              </div>
              <div style="height:8px;border-radius:4px;background:rgba(194,59,42,.15);">
                <div style="height:100%;width:{high_clients/_total_c*100:.1f}%;background:#C23B2A;border-radius:4px;"></div>
              </div>
              <div style="font-size:11px;color:var(--muted);margin-top:3px;">{high_clients/_total_c*100:.1f}% del total</div>
            </div>
            <div>
              <div style="display:flex;justify-content:space-between;font-size:12px;font-weight:700;color:#C4922A;margin-bottom:4px;">
                <span>Riesgo medio</span><span>{med_clients} clientes</span>
              </div>
              <div style="height:8px;border-radius:4px;background:rgba(196,146,42,.15);">
                <div style="height:100%;width:{med_clients/_total_c*100:.1f}%;background:#C4922A;border-radius:4px;"></div>
              </div>
              <div style="font-size:11px;color:var(--muted);margin-top:3px;">{med_clients/_total_c*100:.1f}% del total</div>
            </div>
            <div>
              <div style="display:flex;justify-content:space-between;font-size:12px;font-weight:700;color:#1A6B4A;margin-bottom:4px;">
                <span>Bajo riesgo</span><span>{low_clients} clientes</span>
              </div>
              <div style="height:8px;border-radius:4px;background:rgba(26,107,74,.15);">
                <div style="height:100%;width:{low_clients/_total_c*100:.1f}%;background:#1A6B4A;border-radius:4px;"></div>
              </div>
              <div style="font-size:11px;color:var(--muted);margin-top:3px;">{low_clients/_total_c*100:.1f}% del total</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
      )

      c1, c2 = st.columns(2)
      with c1:
        churn_df = pd.DataFrame([
          {"Nivel de riesgo": "Alto",  "Clientes": high_clients, "Pct": f"{high_clients/_total_c*100:.1f}%"},
          {"Nivel de riesgo": "Medio", "Clientes": med_clients,  "Pct": f"{med_clients/_total_c*100:.1f}%"},
          {"Nivel de riesgo": "Bajo",  "Clientes": low_clients,  "Pct": f"{low_clients/_total_c*100:.1f}%"},
        ])
        fig = px.bar(
          churn_df,
          x="Nivel de riesgo",
          y="Clientes",
          color="Nivel de riesgo",
          text="Clientes",
          title="Clientes por nivel de riesgo de fuga",
          color_discrete_map={"Alto": "#C23B2A", "Medio": "#C4922A", "Bajo": "#1A6B4A"},
        )
        _plotly_update(fig)
        fig.update_traces(
          texttemplate="%{text} <br>(%{customdata[0]})",
          customdata=churn_df[["Pct"]].values,
          textposition="outside",
          textfont=dict(size=12, color="#1a1a1a"),
        )
        fig.update_layout(
          showlegend=False,
          xaxis_title="Nivel de riesgo",
          yaxis_title="N° de clientes",
          xaxis=dict(tickfont=dict(size=13, color="#1a1a1a")),
          yaxis=dict(tickfont=dict(size=11, color="#666"), gridcolor="rgba(149,152,154,0.20)"),
          uniformtext_minsize=10,
          uniformtext_mode="hide",
        )
        st.plotly_chart(fig, use_container_width=True)

      with c2:
        pie_df = pd.DataFrame([
          {"Riesgo": "Alto",  "Valor": high_clients},
          {"Riesgo": "Medio", "Valor": med_clients},
          {"Riesgo": "Bajo",  "Valor": low_clients},
        ])
        fig2 = px.pie(
          pie_df,
          names="Riesgo",
          values="Valor",
          title="Mix de cartera por nivel de riesgo",
          hole=0.45,
          color="Riesgo",
          color_discrete_map={"Alto": "#C23B2A", "Medio": "#C4922A", "Bajo": "#1A6B4A"},
        )
        _plotly_update(fig2)
        fig2.update_traces(
          textposition="outside",
          textinfo="label+percent+value",
          textfont=dict(size=12, color="#1a1a1a"),
          pull=[0.04, 0.02, 0.0],
        )
        fig2.update_layout(
          legend=dict(
            orientation="v", x=1.02, y=0.5,
            font=dict(size=12, color="#1a1a1a"),
          ),
        )
        st.plotly_chart(fig2, use_container_width=True)
      return

    conversion  = _safe_float(kpis_data.get("conversion_rate"), 0.0)
    cancellation = _safe_float(kpis_data.get("cancellation_rate"), 0.0)
    sell_through = _safe_float(kpis_data.get("sell_through_rate"), 0.0)
    trend  = str(kpis_data.get("trend", "flat")).upper()
    invest = re_out.get("investment_score_0_100")
    liq   = re_out.get("liquidity_days_p50")

    st.markdown(
      f"""
      <div class="kpi-grid">
       <div class="kpi">
        <div class="kpi-label">Conversion</div>
        <div class="kpi-value {'ok' if conversion>0.15 else 'gold' if conversion>0.07 else 'danger'}">{conversion*100:.1f}<span style="font-size:18px">%</span></div>
        <div class="kpi-hint">Leads convertidos a reserva</div>
       </div>
       <div class="kpi">
        <div class="kpi-label">Cancelaciones</div>
        <div class="kpi-value {'danger' if cancellation>0.20 else 'gold' if cancellation>0.10 else 'ok'}">{cancellation*100:.1f}<span style="font-size:18px">%</span></div>
        <div class="kpi-hint">Reservas canceladas</div>
       </div>
       <div class="kpi">
        <div class="kpi-label">Absorcion de stock</div>
        <div class="kpi-value">{sell_through*100:.1f}<span style="font-size:18px">%</span></div>
        <div class="kpi-hint">Unidades vendidas / total</div>
       </div>
       <div class="kpi">
        <div class="kpi-label">Tendencia</div>
        <div class="kpi-value" style="font-size:24px;margin-top:8px;">{trend}</div>
        <div class="kpi-hint">Evolucion comercial detectada</div>
       </div>
      </div>
      """,
      unsafe_allow_html=True,
    )

    g1, g2 = st.columns(2)
    with g1:
      rate_df = pd.DataFrame([
        {"KPI": "Conversion",  "Valor": conversion * 100},
        {"KPI": "Sell-through", "Valor": sell_through * 100},
        {"KPI": "Cancelacion", "Valor": cancellation * 100},
      ])
      fig = px.bar(rate_df, x="KPI", y="Valor", title="KPIs comerciales (%)",
             color="KPI", color_discrete_sequence=["#1A6B4A", "#0D2137", "#C23B2A"])
      _plotly_update(fig)
      fig.update_layout(yaxis_title="Porcentaje", xaxis_title="", showlegend=False)
      st.plotly_chart(fig, use_container_width=True)
    with g2:
      series = commercial_output.get("series", []) or []
      if series:
        sdf = pd.DataFrame(series)
        x_key = next((k for k in ["month", "period", "date", "label"] if k in sdf.columns), None)
        if not x_key:
          sdf["idx"] = range(1, len(sdf) + 1)
          x_key = "idx"
        y_key = next((k for k in ["units_sold", "revenue_eur"] if k in sdf.columns), None)
        if y_key:
          fig2 = px.line(sdf, x=x_key, y=y_key, markers=True, title=f"Evolucion mensual")
          _plotly_update(fig2)
          fig2.update_traces(line=dict(color="#C4922A", width=2.5), marker=dict(color="#0D2137", size=7))
          st.plotly_chart(fig2, use_container_width=True)
      else:
        st.info("No hay serie temporal en el documento.")
    return

  # Real estate (generic) 
  interpretation = (normalized.get("interpretation") or {}) if isinstance(normalized, dict) else {}
  metrics_list = interpretation.get("metrics", []) if isinstance(interpretation, dict) else []
  re_out = (((result.get("real_estate_models") or {}).get("output")) or {})
  metric_map = {str(m.get("name")): m.get("value") for m in metrics_list if isinstance(m, dict)}

  doc_price = metric_map.get("price_eur")
  doc_rent  = metric_map.get("rent_eur_month")
  surface  = metric_map.get("surface_m2")
  model_price = re_out.get("expected_sale_price_eur")
  model_rent = re_out.get("expected_rent_eur_month")
  model_yield = re_out.get("expected_gross_yield_pct")
  invest = _safe_float(re_out.get("investment_score_0_100"), 0.0)
  liq  = _safe_float(re_out.get("liquidity_days_p50"), 0.0)
  price_gap = re_out.get("price_gap_pct_vs_document")
  rent_gap = re_out.get("rent_gap_pct_vs_document")

  # KPI row
  st.markdown(
    f"""
    <div class="kpi-grid">
     <div class="kpi">
      <div class="kpi-label">Precio modelo</div>
      <div class="kpi-value" style="font-size:26px;margin-top:4px;">{_fmt_money(model_price)}</div>
      <div class="kpi-hint">{'Gap vs documento: ' + f'{price_gap:+.1f}%' if price_gap is not None else 'Referencia de mercado'}</div>
     </div>
     <div class="kpi">
      <div class="kpi-label">Renta estimada</div>
      <div class="kpi-value" style="font-size:26px;margin-top:4px;">{_fmt_money(model_rent)}<span style="font-size:14px">/mes</span></div>
      <div class="kpi-hint">{'Gap vs documento: ' + f'{rent_gap:+.1f}%' if rent_gap is not None else 'Estimacion del modelo'}</div>
     </div>
     <div class="kpi">
      <div class="kpi-label">Yield bruto</div>
      <div class="kpi-value {'ok' if _safe_float(model_yield,0)>=5 else 'gold' if _safe_float(model_yield,0)>=3.5 else 'danger'}">{_safe_float(model_yield,0):.2f}<span style="font-size:18px">%</span></div>
      <div class="kpi-hint">Rentabilidad bruta anual</div>
     </div>
     <div class="kpi">
      <div class="kpi-label">Superficie</div>
      <div class="kpi-value" style="font-size:28px;">{_fmt_int(surface)}<span style="font-size:16px"> m2</span></div>
      <div class="kpi-hint">Detectada en el documento</div>
     </div>
    </div>
    """,
    unsafe_allow_html=True,
  )

  # Score + Liquidity gauges
  g1, g2, g3 = st.columns([1.2, 1.2, 1.6])
  with g1:
    fig_inv = gauge_chart(invest, "Score de inversion (0100)")
    st.plotly_chart(fig_inv, use_container_width=True)
  with g2:
    fig_liq = gauge_chart(liq, "Dias estimados de salida", 0, 365)
    st.plotly_chart(fig_liq, use_container_width=True)
  with g3:
    comp_rows = []
    if doc_price is not None:
      comp_rows.append({"Serie": "Precio documento", "Valor": _safe_float(doc_price)})
    if model_price is not None:
      comp_rows.append({"Serie": "Precio modelo", "Valor": _safe_float(model_price)})
    if doc_rent is not None:
      comp_rows.append({"Serie": "Renta documento", "Valor": _safe_float(doc_rent)})
    if model_rent is not None:
      comp_rows.append({"Serie": "Renta modelo", "Valor": _safe_float(model_rent)})
    if comp_rows:
      cdf = pd.DataFrame(comp_rows)
      fig = px.bar(cdf, x="Serie", y="Valor", color="Serie", title="Documento vs Modelo",
             color_discrete_sequence=["#0D2137", "#C4922A", "#1A6B4A", "#E8B86D"])
      _plotly_update(fig)
      fig.update_layout(showlegend=False, yaxis_title="EUR")
      st.plotly_chart(fig, use_container_width=True)


def render_loading_state(placeholder: Any, progress: int, message: str, states: List[Dict[str, str]]) -> None:
  def _cls(state: str) -> str:
    if state == "done":    return "ag-card done"
    if state == "running": return "ag-card running"
    return "ag-card"

  def _icon(state: str) -> str:
    if state == "done":
      return '<svg viewBox="0 0 24 24" fill="none" stroke="#2e7d32" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px;display:inline-block;vertical-align:middle;"><polyline points="20 6 9 17 4 12"/></svg>'
    if state == "running":
      return '<svg viewBox="0 0 24 24" fill="none" stroke="#00417d" stroke-width="2" stroke-linecap="round" style="width:14px;height:14px;display:inline-block;vertical-align:middle;"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>'
    return '<svg viewBox="0 0 24 24" fill="none" stroke="#95989a" stroke-width="2" stroke-linecap="round" style="width:14px;height:14px;display:inline-block;vertical-align:middle;"><circle cx="12" cy="12" r="10"/></svg>'

  cards = "".join(
    f"""<div class="{_cls(item.get('state','wait'))}">
      <div class="ag-dot"></div>
      <div class="ag-name">{item.get('name','Agente')}</div>
      <div class="ag-status">{_icon(item.get('state','wait'))} {item.get('status','EN ESPERA')}</div>
    </div>"""
    for item in states
  )

  placeholder.markdown(
    f"""
    <div class="ov-backdrop">
      <div class="ov-modal">
        <div class="orq-wrap">
          <div class="orq-hex">AI</div>
          <div class="orq-label">Agente Orquestador</div>
          <div class="orq-msg">{xml_escape(message)}</div>
        </div>
        <div class="agents-grid">{cards}</div>
        <div class="prog-pct">{progress}%</div>
        <div class="prog-wrap">
          <div class="prog-bg"><div class="prog-fill" style="width:{progress}%;"></div></div>
          <div class="prog-lbl">{xml_escape(message)}</div>
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
  )


# Upload screen 
def render_upload_screen(
  horizon_days: int,
  macro_pressure: float,
  demand_pressure: float,
  n8n_webhook_url: str,
) -> None:
  # Logo: imagen real si existe, SVG de alta fidelidad como fallback
  _logo_tag = _logo_img_tag(height=52)
  _logo_block = (
    f'<div style="margin-bottom:clamp(6px,0.9vh,12px);">{_logo_tag}</div>'
    if _logo_tag else
    """<div style="display:inline-flex;align-items:center;gap:8px;margin-bottom:clamp(6px,0.9vh,10px);
                  background:#ffffff;border-radius:10px;padding:7px 16px;
                  box-shadow:0 2px 12px rgba(0,65,125,0.10);border:1px solid rgba(0,65,125,0.08);">
        <svg width="38" height="38" viewBox="0 0 48 48" fill="none">
          <circle cx="24" cy="24" r="23" fill="#E8720C"/>
          <text x="24" y="22" text-anchor="middle" font-family="Lato,sans-serif" font-weight="900" font-size="16" fill="#fff">80</text>
          <text x="24" y="34" text-anchor="middle" font-family="Lato,sans-serif" font-weight="700" font-size="9" fill="#fff" letter-spacing="1.5">AÑOS</text>
        </svg>
        <svg width="90" height="38" viewBox="0 0 112 48" fill="none">
          <circle cx="24" cy="24" r="22" fill="#f0f4f9"/>
          <circle cx="24" cy="24" r="22" stroke="#E8720C" stroke-width="2"/>
          <text x="13" y="31" font-family="Lato,sans-serif" font-weight="900" font-size="19" fill="#00417d">i</text>
          <text x="25" y="31" font-family="Lato,sans-serif" font-weight="700" font-size="17" fill="#E8720C">S</text>
          <text x="54" y="26" font-family="Lato,sans-serif" font-weight="900" font-size="18" fill="#00417d">insur</text>
          <text x="54" y="38" font-family="Lato,sans-serif" font-weight="700" font-size="9" fill="#95989a" letter-spacing="2">GRUPO</text>
        </svg>
        <div style="width:1px;height:30px;background:rgba(0,65,125,0.18);"></div>
        <div style="font-family:'Lato',sans-serif;font-size:14px;font-weight:700;
                    color:#00417d;font-style:italic;">Inspirando juntos</div>
      </div>"""
  )
  # ── Hero banner (solo texto + logo, sin tarjetas internas para evitar fondo oscuro) ──
  st.markdown(
    f"""
    <div style="background:#eef3f9;border-radius:18px;border:1px solid rgba(0,65,125,0.14);
                padding:clamp(10px,1.8vh,22px) 44px clamp(8px,1.4vh,16px);margin-bottom:0px;text-align:center;
                box-shadow:0 4px 24px rgba(0,65,125,0.10);">
      {_logo_block}
      <div style="font-size:9px;font-weight:700;letter-spacing:3.5px;color:#de6d51;
                  text-transform:uppercase;margin-bottom:clamp(4px,0.6vh,8px);">
        Plataforma de Inteligencia Inmobiliaria
      </div>
      <div style="font-size:clamp(20px,2.8vw,40px);font-weight:900;color:#00417d;
                  line-height:1.08;margin-bottom:clamp(4px,0.8vh,10px);letter-spacing:-0.5px;">
        Analisis con Agente
      </div>
      <div style="font-size:clamp(11px,1.2vw,13px);color:#555555;max-width:600px;margin:0 auto 0;line-height:1.55;">
        Tres agentes especializados analizan tu documento en paralelo:
        <strong style="color:#00417d;">cuantitativo</strong>,
        <strong style="color:#00417d;">financiero</strong> y
        <strong style="color:#00417d;">de mercado</strong>.
        Un agente orquestador consolida todo en un informe ejecutivo accionable.
      </div>
    </div>
    """,
    unsafe_allow_html=True,
  )

  # ── Panel Lineas de Negocio (mismo estilo que tipos) ──────────────────────
  st.markdown('<div style="height:clamp(4px,0.8vh,10px);"></div>', unsafe_allow_html=True)

  _LINEAS_NEGOCIO = [
    ("Viviendas",   "Residencial",  '<path d="M3 22V10L12 3l9 7v12"/><path d="M9 22v-6h6v6"/>'),
    ("Oficinas",    "Corporativo",  '<rect x="3" y="2" width="18" height="20" rx="2"/><path d="M9 22v-4h6v4"/><path d="M8 6h.01"/><path d="M16 6h.01"/><path d="M8 10h.01"/><path d="M16 10h.01"/><path d="M8 14h.01"/><path d="M16 14h.01"/>'),
    ("Locales",     "Comercial",    '<path d="M3 9h18"/><path d="M5 9l1-5h12l1 5"/><path d="M4 9v10a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9"/><path d="M9 22v-6h6v6"/>'),
    ("Hoteles",     "Hospitalidad", '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 21v-6h6v6"/><path d="M7 7h.01"/><path d="M11 7h.01"/><path d="M15 7h.01"/><path d="M7 11h.01"/><path d="M11 11h.01"/><path d="M15 11h.01"/>'),
    ("Parking",     "Mobility",     '<rect x="3" y="2" width="18" height="20" rx="2"/><path d="M9 17V7h4a3 3 0 1 1 0 6H9"/>'),
    ("C. Negocios", "Business",     '<rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/>'),
  ]

  def _linea_card(title: str, subtitle: str, paths: str) -> str:
    svg = (
      '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#00417d" '
      f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{paths}</svg>'
    )
    return (
      '<div style="background:#ffffff;border:1.5px solid #dce2ea;border-radius:8px;'
      'padding:6px 10px;display:flex;align-items:center;gap:6px;min-width:0;'
      'box-shadow:0 2px 6px rgba(0,65,125,0.08);">'
      '<div style="background:rgba(0,65,125,0.08);display:flex;align-items:center;justify-content:center;'
      f'width:22px;height:22px;border-radius:5px;flex-shrink:0;">{svg}</div>'
      '<div style="min-width:0;line-height:1.1;">'
      f'<div style="font-size:9px;font-weight:700;color:#374151;text-transform:uppercase;">{title}</div>'
      f'<div style="font-size:8px;color:#6b7280;">{subtitle}</div>'
      '</div></div>'
    )

  _lineas_cards = ''.join(
    _linea_card(title, subtitle, paths) for title, subtitle, paths in _LINEAS_NEGOCIO
  )

  st.markdown(
    '<div style="margin-top:4px;background:#f8fafc;border:1px solid rgba(0,65,125,0.10);'
    'border-radius:12px;padding:8px 14px 10px;">'
    '<div style="font-size:9px;font-weight:700;color:#6b7280;letter-spacing:2px;'
    'text-transform:uppercase;margin-bottom:7px;">'
    'Lineas de negocio'
    '</div>'
    '<div style="display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px;">'
    + _lineas_cards +
    '</div></div>',
    unsafe_allow_html=True,
  )

  st.markdown('<div style="height:clamp(4px,0.8vh,12px);"></div>', unsafe_allow_html=True)

  uploaded = st.file_uploader(
    "Sube el documento PDF para analizar",
    type=["pdf"],
    help="Documento PDF con texto seleccionable.",
  )

  prefetch: Dict[str, Any] | None = None
  detected = detect_doc_type("documento.pdf")
  pref_quality = extraction_quality({})
  detected_doc_type = "none"

  if uploaded:
    file_bytes = uploaded.getvalue()
    sig = f"{uploaded.name}:{uploaded.size}"
    cached_sig = st.session_state.get("prefetch_sig")
    prefetch = st.session_state.get("prefetch_extract")
    prefetch_state = st.session_state.get("prefetch_state", "idle")

    if cached_sig != sig:
      st.session_state["prefetch_sig"] = sig
      st.session_state["prefetch_extract"] = None
      st.session_state["prefetch_state"] = "idle"
      st.session_state["prefetch_error"] = ""
      prefetch = None
      prefetch_state = "idle"

    if prefetch_state == "idle":
      with st.spinner("Detectando tipo de documento con IA..."):
        try:
          prefetch = extract_pdf_local_quick(uploaded.name, file_bytes)
          st.session_state["prefetch_extract"] = prefetch
          st.session_state["prefetch_state"] = "ok"
        except Exception as exc:
          st.session_state["prefetch_extract"] = None
          st.session_state["prefetch_state"] = "failed"
          st.session_state["prefetch_error"] = str(exc)
          prefetch = None

    if st.session_state.get("prefetch_state") == "failed":
      st.warning("No se pudo detectar automaticamente el tipo. Puedes continuar con el analisis.")
      if st.button("Reintentar deteccion IA", use_container_width=False):
        st.session_state["prefetch_state"] = "idle"
        st.rerun()

    detected_payload = (((prefetch or {}).get("extraction") or {}).get("detected") or {})
    detected = detect_doc_type_from_extraction(detected_payload) if detected_payload else detect_doc_type(uploaded.name)
    pref_quality = extraction_quality(prefetch or {})
    detected_doc_type = detected.get("doc_type", "real_estate_generic")
    _det_svg = _doc_icon_svg(detected_doc_type, size=28, color="#00417d")
    _det_name = xml_escape(detected["name"])

    st.markdown(
      f"""
      <div style="background:linear-gradient(135deg,rgba(0,65,125,0.06) 0%,rgba(0,65,125,0.02) 100%);
                  border:1.5px solid rgba(0,65,125,0.18);border-radius:14px;
                  padding:18px 22px;margin:12px 0;">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:14px;">
          <div style="width:8px;height:8px;border-radius:50%;background:#00417d;
                      animation:bl 1s infinite;flex-shrink:0;"></div>
          <span style="font-size:10px;font-weight:900;color:#00417d;letter-spacing:2px;
                       text-transform:uppercase;">Documento clasificado automaticamente</span>
        </div>
        <div style="display:flex;align-items:center;gap:14px;">
          <div style="width:52px;height:52px;background:#ffffff;border-radius:14px;
                      display:flex;align-items:center;justify-content:center;
                      box-shadow:0 4px 14px rgba(0,65,125,0.15);
                      border:1.5px solid rgba(0,65,125,0.12);flex-shrink:0;">
            {_det_svg}
          </div>
          <div>
            <div style="font-size:9px;color:#95989a;letter-spacing:1.5px;
                        text-transform:uppercase;font-weight:700;margin-bottom:3px;">Tipo detectado</div>
            <div style="font-size:20px;font-weight:900;color:#00417d;line-height:1.1;">{_det_name}</div>
          </div>
        </div>
      </div>
      """,
      unsafe_allow_html=True,
    )
    if prefetch and not pref_quality["usable_for_analysis"]:
      st.warning(
        "El PDF tiene poco texto extraido para un analisis confiable: "
        f"{pref_quality['char_count']} caracteres (minimo {pref_quality['min_chars_required']})."
      )

  # ── Grid tipos de documento con resaltado del tipo detectado ──────────────
  # Mapeo label → doc_type key para identificar cual resaltar
  _TIPO_KEYS = [
    ("Promotora",    "real_estate_generic", '<path d="M3 22V10L12 3l9 7v12"/><path d="M9 22v-6h6v6"/>'),
    ("Agencia",      "supplier_report",     '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>'),
    ("Inversion",    "investment_report",   '<polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>'),
    ("Cartera",      "commercial_report",   '<rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/>'),
    ("Mercado",      "market_report",       '<line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/><line x1="2" y1="20" x2="22" y2="20"/>'),
    ("Viabilidad",   "real_estate_generic", '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>'),
    ("Due Diligence","legal_report",        '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/>'),
    ("Business Plan","investment_report",   '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>'),
    ("Tasacion",     "valuation_report",    '<line x1="12" y1="2" x2="12" y2="22"/><path d="M5 9.5l-3 4h6l-3-4z"/><path d="M19 9.5l-3 4h6l-3-4z"/><line x1="5" y1="13.5" x2="19" y2="13.5"/>'),
    ("Rentabilidad", "investment_report",   '<line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>'),
    ("Suelo",        "real_estate_generic", '<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>'),
    ("Nota Simple",  "legal_report",        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>'),
  ]

  def _tipo_card(label: str, key: str, paths: str, active: bool) -> str:
    if active:
      bg    = "background:linear-gradient(135deg,#00417d,#005bb5);"
      brd   = "border:2px solid #00417d;"
      ic_bg = "background:rgba(255,255,255,0.20);"
      stroke= "#ffffff"
      lbl_c = "#ffffff"
      badge = '<span style="margin-left:4px;font-size:7px;background:rgba(255,255,255,0.28);color:#fff;border-radius:3px;padding:1px 4px;font-weight:700;vertical-align:middle;">✓</span>'
    else:
      bg    = "background:#ffffff;"
      brd   = "border:1.5px solid #dce2ea;"
      ic_bg = "background:rgba(0,65,125,0.08);"
      stroke= "#00417d"
      lbl_c = "#374151"
      badge = ""
    svg = f'<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="{stroke}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{paths}</svg>'
    return (
      f'<div style="{bg}{brd}border-radius:8px;padding:5px 10px;display:flex;align-items:center;'
      f'gap:6px;min-width:0;width:100%;box-shadow:0 2px 6px rgba(0,65,125,0.08);cursor:default;">'
      f'<div style="{ic_bg}display:flex;align-items:center;justify-content:center;'
      f'width:22px;height:22px;border-radius:5px;flex-shrink:0;">{svg}</div>'
      f'<span style="font-size:9px;font-weight:700;color:{lbl_c};text-transform:uppercase;line-height:1.2;">{label}</span>'
      f'{badge}</div>'
    )

  _grid_cards = "".join(
    _tipo_card(label, key, paths, key == detected_doc_type)
    for label, key, paths in _TIPO_KEYS
  )

  st.markdown(
    '<div style="margin-top:8px;background:#f8fafc;border:1px solid rgba(0,65,125,0.10);'
    'border-radius:12px;padding:8px 14px 10px;">'
    '<div style="font-size:9px;font-weight:700;color:#6b7280;letter-spacing:2px;'
    'text-transform:uppercase;margin-bottom:7px;">'
    'Tipos de documento reconocidos'
    '</div>'
    '<div style="display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px;">'
    + _grid_cards +
    '</div></div>',
    unsafe_allow_html=True,
  )

  # ── Botón lanzar análisis ─────────────────────────────────────────────────
  st.markdown('<div style="height:10px;"></div>', unsafe_allow_html=True)

  _btn_disabled = not bool(uploaded) or not bool((n8n_webhook_url or "").strip())

  if _btn_disabled:
    st.markdown(
      '<div style="background:#e8edf3;border-radius:14px;padding:20px 28px;'
      'text-align:center;border:2px dashed rgba(0,65,125,0.20);">'
      '<div style="font-size:13px;font-weight:700;color:#95989a;letter-spacing:0.5px;">'
      'Sube un PDF para habilitar el análisis'
      '</div></div>',
      unsafe_allow_html=True,
    )
  analyze = st.button(
    "🚀  Lanzar Análisis Multi-Agente",
    type="primary",
    use_container_width=True,
    disabled=_btn_disabled,
  )
  if not (n8n_webhook_url or "").strip():
    st.info("Configura `n8n Webhook URL` en la barra lateral para habilitar el analisis.")

  if analyze and uploaded:
    load_placeholder = st.empty()
    states = [
      {"name": "Data Scientist", "state": "wait", "status": "EN ESPERA"},
      {"name": "Analista Financiero", "state": "wait", "status": "EN ESPERA"},
      {"name": "Analista de Mercado", "state": "wait", "status": "EN ESPERA"},
    ]
    try:
      render_loading_state(load_placeholder, 10, "Clasificando documento...", states)
      file_bytes = uploaded.getvalue()
      sig = f"{uploaded.name}:{uploaded.size}"
      prefetch = st.session_state.get("prefetch_extract")
      if st.session_state.get("prefetch_sig") == sig and prefetch:
        extracted = prefetch
      else:
        extracted = extract_pdf_local(uploaded.name, file_bytes)
      quality = extraction_quality(extracted)
      if not quality["usable_for_analysis"]:
        raise RuntimeError(
          "Extraccion insuficiente. "
          f"Solo se detectaron {quality['char_count']} caracteres "
          f"(minimo {quality['min_chars_required']})."
        )

      states[0]["state"] = "running"
      states[0]["status"] = "ANALIZANDO"
      render_loading_state(load_placeholder, 28, "Distribuyendo a los agentes...", states)
      time.sleep(0.2)
      for s in states:
        s["state"] = "running"
        s["status"] = "ANALIZANDO"
      render_loading_state(load_placeholder, 46, "Agentes trabajando en paralelo...", states)

      n8n_payload = {
        "filename": uploaded.name,
        "document_id": extracted.get("document_id"),
        "pdf_text": ((extracted.get("extraction") or {}).get("full_text") or "")[:12000],
        "extraction": extracted.get("extraction", {}),
        "detected": ((extracted.get("extraction") or {}).get("detected") or {}),
        "settings": {
          "horizon_days": horizon_days,
          "macro_pressure": macro_pressure,
          "demand_pressure": demand_pressure,
        },
        "requirements": {
          "decision_source": "n8n",
          "strict_decisions": N8N_STRICT_DECISIONS,
        },
        "source": "insur_streamlit_frontend",
      }
      n8n_result = api_post_n8n(n8n_webhook_url, n8n_payload)
      st.session_state["n8n_health"] = "online"
      if N8N_STRICT_DECISIONS:
        validate_n8n_decision_contract(n8n_result)

      states[0]["state"] = "done"; states[0]["status"] = "COMPLETADO"
      states[1]["state"] = "done"; states[1]["status"] = "COMPLETADO"
      states[2]["state"] = "done"; states[2]["status"] = "COMPLETADO"
      render_loading_state(load_placeholder, 86, "Consolidando resultados...", states)
      time.sleep(0.2)
      render_loading_state(load_placeholder, 100, "Generando informe ejecutivo...", states)
      time.sleep(0.25)
      load_placeholder.empty()

      result = adapt_n8n_to_app_result(n8n_result, extracted=extracted, doc_name=uploaded.name)
      result["decision_source"] = "n8n"
      result["n8n_mode"] = True
      st.session_state["result"] = result
      st.session_state["doc_name"] = uploaded.name
      st.session_state["screen"] = "result"
      st.session_state["prefetch_extract"] = None
      st.session_state["prefetch_sig"] = ""
      st.session_state["prefetch_state"] = "idle"
      st.session_state["prefetch_error"] = ""
      st.rerun()
    except Exception as exc:
      st.session_state["n8n_health"] = "offline"
      load_placeholder.empty()
      st.error(f"No se pudo ejecutar el pipeline: {exc}")
      st.info("Verifica n8n activo, webhook correcto y texto util en el PDF.")


# Result screen 
def render_result_screen(n8n_webhook_url: str) -> None:
  result = st.session_state.get("result", {})
  doc_name = st.session_state.get("doc_name", "Documento analizado")
  k = summarize_for_kpis(result)
  summary = result.get("summary", {}) or {}
  normalized = result.get("normalized", {}) or {}
  doc_type = normalized.get("document_type", "unknown")
  interpretation_report = result.get("result_interpretation", {}) or {}
  executive_summary = interpretation_report.get("executive_summary", {}) or {}
  run_id = result.get("run_id", "n/a")
  n8n_raw = result.get("n8n_raw", {}) or {}
  inf = _coerce_n8n_informe(n8n_raw)
  ds = n8n_raw.get("data_scientist", {}) or {}
  af = n8n_raw.get("analista_financiero", {}) or {}
  am = n8n_raw.get("analista_mercado", {}) or {}

  rec = str(inf.get("recomendacion_global") or "REVISAR").upper()
  rec_cls = {
    "INVERTIR": "INVERTIR",
    "INVERTIR CON CAUTELA": "CAUTELA",
    "CAUTELA": "CAUTELA",
    "NO INVERTIR": "NOINVERTIR",
    "REVISAR": "REVISAR",
    "REVISION PRIORITARIA": "REVISAR",
    "SEGUIMIENTO": "CAUTELA",
    "ACEPTABLE": "CAUTELA",
  }.get(rec, "REVISAR")
  rec_icon = {
    "INVERTIR": "OK",
    "CAUTELA": "WARN",
    "REVISAR": "CHECK",
    "NOINVERTIR": "STOP",
  }.get(rec_cls, "CHECK")
  decision_source = str(result.get("decision_source") or "n8n").upper()
  # Mostrar report_type (clientes/operaciones) en lugar de doc_type (commercial_report)
  tipo_display = str(result.get("report_type") or doc_type).lower()

  # Titulo contextual segun tipo de analisis (nunca nombre del fichero)
  _titulo_ctx = {
    "clientes":         "Analisis de Cartera de Clientes",
    "operaciones":      "Analisis de Operaciones Inmobiliarias",
    "ventas":           "Analisis de Ventas Inmobiliarias",
    "commercial_report":"Informe Comercial Inmobiliario",
    "supplier_report":  "Analisis de Proveedores",
    "promotora":        "Analisis de Promotora Inmobiliaria",
    "financiero":       "Analisis Financiero del Portafolio",
    "legal":            "Analisis Legal del Portafolio",
  }.get(tipo_display, f"Analisis {tipo_display.replace('_',' ').capitalize()}")

  _zona = str(n8n_raw.get("zona_geografica") or result.get("zona_geografica") or "")
  _ccaa = str(n8n_raw.get("ccaa") or result.get("ccaa") or "")
  _meta_parts = [p for p in [_zona, _ccaa] if p and p.lower() not in {"none","","null"}]
  _meta_str = " · ".join(_meta_parts) if _meta_parts else tipo_display.replace("_"," ").upper()

  st.markdown(
    f"""
    <div class="res-top">
      <div>
        <div class="rec-badge {rec_cls}">{rec_icon} {rec}</div>
        <div class="res-h">{xml_escape(_titulo_ctx)}</div>
        <div class="res-meta">{xml_escape(_meta_str)}</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
  )

  opp = int(_safe_float(inf.get("score_oportunidad_global", summary.get("score", 0)), 0))
  rent = _safe_float(ds.get("score_rentabilidad", ((result.get("real_estate_models") or {}).get("output") or {}).get("investment_score_0_100", 0)), 0.0)
  viab = _safe_float(af.get("score_viabilidad"), 0.0)
  risk = _safe_float(ds.get("score_riesgo", k.get("high_risk", 0) * 10), 0.0)

  def _sc_color(val: float, invert: bool = False) -> str:
    good = val >= 70
    mid  = val >= 45
    if invert: good, mid = (val < 35), (val < 55)
    return "#2e7d32" if good else "#c4922a" if mid else "#c62828"

  def _score_card(label: str, value: float, sub: str, accent: str, icon_svg: str, invert: bool = False) -> str:
    pct  = max(0, min(100, int(value)))
    col  = _sc_color(value, invert)
    bar_bg = "rgba(255,255,255,0.25)"
    return f"""
    <div style="background:linear-gradient(135deg,{accent}18 0%,{accent}08 100%);
                border:1px solid {accent}30;border-radius:14px;padding:18px 20px;
                display:flex;flex-direction:column;gap:10px;position:relative;overflow:hidden;">
      <div style="position:absolute;top:-10px;right:-10px;width:70px;height:70px;
                  background:{accent}12;border-radius:50%;"></div>
      <div style="display:flex;align-items:center;gap:10px;">
        <div style="width:36px;height:36px;background:{accent}22;border-radius:10px;
                    display:flex;align-items:center;justify-content:center;flex-shrink:0;">
          <div style="width:20px;height:20px;color:{accent};">{icon_svg}</div>
        </div>
        <div style="font-size:11px;font-weight:700;color:{accent};text-transform:uppercase;letter-spacing:.06em;">{label}</div>
      </div>
      <div style="font-size:42px;font-weight:900;color:{col};line-height:1;letter-spacing:-2px;">{pct}<span style="font-size:20px;font-weight:600;color:{col}88;">/100</span></div>
      <div style="height:5px;background:{bar_bg};border-radius:3px;overflow:hidden;border:1px solid {accent}20;">
        <div style="height:100%;width:{pct}%;background:{col};border-radius:3px;transition:width .6s;"></div>
      </div>
      <div style="font-size:11px;color:#555;font-weight:600;">{xml_escape(str(sub))}</div>
    </div>"""

  _ico_opp  = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>'
  _ico_rent = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>'
  _ico_viab = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/></svg>'
  _ico_risk = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>'

  # ── ACCIONES ──────────────────────────────────────────────────────────────

  _prd_current = st.session_state.get("prd_text", "")
  _pdf_bytes   = st.session_state.get("prd_pdf_bytes")
  _prd_ready   = bool(_prd_current)

  # Centrar botones con columnas con padding lateral
  _gap, _ac0, _ac1, _ac2, _ac3, _gap2 = st.columns([0.5, 1, 1, 1, 1, 0.5])

  with _ac0:
    if st.button("↩ Nuevo análisis", use_container_width=True, type="secondary"):
      st.session_state["screen"] = "upload"
      st.session_state["result"] = None
      st.session_state["prd_text"] = ""
      st.session_state["prd_display_markdown"] = ""
      st.session_state["prd_pdf_bytes"] = None
      st.session_state["prd_note"] = ""
      st.session_state["prd_provider"] = ""
      st.rerun()

  with _ac1:
    st.download_button(
      "⬇ Descargar JSON",
      data=json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"),
      file_name=f"insur_{doc_name.replace('.pdf','')}.json",
      mime="application/json",
      use_container_width=True,
    )

  with _ac2:
    # PRD: si no generado → botón Generar; si generado y sin PDF → Preparar PDF; si PDF listo → Descargar PDF
    if not _prd_ready:
      if st.button("📄 Generar PRD", use_container_width=True, type="primary"):
        with st.spinner("Generando documento PRD..."):
          _prd_text = ""
          _prd_provider = "n8n"
          _prd_note = ""
          try:
            _prd_req = {
              "action": "generate_prd",
              "source": "insur_streamlit_frontend",
              "run_id": result.get("run_id"),
              "document_name": doc_name,
              "analysis_result": result.get("n8n_raw") or result,
            }
            _prd_resp = api_post_n8n(n8n_webhook_url, _prd_req)
            _prd_text = extract_prd_text_from_payload(_prd_resp)
            _prd_provider = str(_prd_resp.get("provider") or "n8n")
            if not _prd_text:
              _prd_note = "n8n no devolvio prd_text; se genero PRD local."
          except Exception as _exc:
            _prd_note = f"Fallback local por error n8n: {_exc}"
          if not _prd_text:
            _prd_text = build_prd_text_local(result, doc_name)
            if _prd_provider == "n8n":
              _prd_provider = "local-fallback"
          st.session_state["prd_text"] = _prd_text
          st.session_state["prd_display_markdown"] = ""
          st.session_state["prd_note"] = _prd_note
          st.session_state["prd_provider"] = _prd_provider
          st.session_state["prd_pdf_bytes"] = None
          st.rerun()
    elif _prd_ready and not _pdf_bytes:
      if st.button("🖨 Preparar PDF PRD", use_container_width=True, type="primary"):
        # ── Construir contexto completo para PDF ─────────────────────────
        _commercial_output = (((result.get("commercial") or {}).get("output")) or {})
        _kpis_data = (_commercial_output.get("kpis") or result.get("kpis") or {})
        _mode = str(_kpis_data.get("kpi_mode") or result.get("report_type") or tipo_display).lower()
        if _mode not in {"clientes", "operaciones"}:
          if _safe_float(_kpis_data.get("total_clients"), 0.0) > 0:
            _mode = "clientes"
          elif _safe_float(_kpis_data.get("operations_total"), 0.0) > 0:
            _mode = "operaciones"

        _pdf_kpis: list[dict[str, Any]] = [
          {"label": "Score Oportunidad",     "value": f"{opp}/100"},
          {"label": "Score Rentabilidad",    "value": f"{int(rent)}/100"},
          {"label": "Viabilidad Financiera", "value": f"{int(viab)}/100"},
          {"label": "Score Riesgo",          "value": f"{int(risk)}/100"},
        ]
        if _mode == "clientes":
          _tot_clients = int(_safe_float(_kpis_data.get("total_clients"), 0.0))
          _high_clients = int(_safe_float(_kpis_data.get("high_risk_clients"), 0.0))
          _med_clients = int(_safe_float(_kpis_data.get("medium_risk_clients"), 0.0))
          _low_clients = int(_safe_float(_kpis_data.get("low_risk_clients"), 0.0))
          _ret = _safe_float(_kpis_data.get("retention_rate"), 0.0)
          _churn = _safe_float(_kpis_data.get("avg_churn_score"), max(0.0, 1.0 - _ret))
          _ops_total = int(_safe_float(_kpis_data.get("operations_total"), 0.0))
          _vol = _safe_float(_kpis_data.get("volume_total_eur"), 0.0)
          _pdf_kpis.extend([
            {"label": "Clientes analizados", "value": f"{_tot_clients}"},
            {"label": "Clientes alto riesgo", "value": f"{_high_clients}"},
            {"label": "Clientes riesgo medio", "value": f"{_med_clients}"},
            {"label": "Clientes bajo riesgo", "value": f"{_low_clients}"},
            {"label": "Churn promedio", "value": f"{_churn*100:.1f}%"},
            {"label": "Retencion esperada", "value": f"{_ret*100:.1f}%"},
            {"label": "Operaciones cartera", "value": f"{_ops_total}"},
          ])
          if _vol > 0:
            _pdf_kpis.append({"label": "Volumen total cartera", "value": f"€{_vol/1_000_000:.2f}M" if _vol >= 1_000_000 else f"€{_vol:,.0f}"})
        elif _mode == "operaciones":
          _ops_total = int(_safe_float(_kpis_data.get("operations_total"), 0.0))
          _vol = _safe_float(_kpis_data.get("volume_total_eur"), 0.0)
          _avg_price = _safe_float(_kpis_data.get("avg_price_eur"), 0.0)
          _avg_m2 = _safe_float(_kpis_data.get("avg_price_m2_eur"), 0.0)
          _avg_margin = _safe_float(_kpis_data.get("avg_margin_pct"), 0.0)
          _conv = _safe_float(_kpis_data.get("conversion_rate"), 0.0)
          _sell = _safe_float(_kpis_data.get("sell_through_rate"), 0.0)
          _canc = _safe_float(_kpis_data.get("cancellation_rate"), 0.0)
          _trend_pdf = str(_kpis_data.get("trend", "flat")).upper()
          _pdf_kpis.extend([
            {"label": "Operaciones analizadas", "value": f"{_ops_total}"},
            {"label": "Tasa de conversion", "value": f"{_conv*100:.1f}%"},
            {"label": "Sell-through", "value": f"{_sell*100:.1f}%"},
            {"label": "Cancelacion", "value": f"{_canc*100:.1f}%"},
            {"label": "Margen promedio", "value": f"{_avg_margin:.2f}%"},
            {"label": "Tendencia", "value": _trend_pdf},
          ])
          if _avg_price > 0:
            _pdf_kpis.append({"label": "Precio medio", "value": f"€{_avg_price:,.0f}"})
          if _avg_m2 > 0:
            _pdf_kpis.append({"label": "Precio medio m2", "value": f"€{_avg_m2:,.0f}/m2"})
          if _vol > 0:
            _pdf_kpis.append({"label": "Volumen total", "value": f"€{_vol/1_000_000:.2f}M" if _vol >= 1_000_000 else f"€{_vol:,.0f}"})
        else:
          if _kpis_data.get("conversion_rate") is not None:
            _pdf_kpis.append({"label": "Tasa de conversion",  "value": f"{_safe_float(_kpis_data.get('conversion_rate'), 0.0)*100:.1f}%"})
          if _kpis_data.get("sell_through_rate") is not None:
            _pdf_kpis.append({"label": "Sell-through", "value": f"{_safe_float(_kpis_data.get('sell_through_rate'), 0.0)*100:.1f}%"})
          if _kpis_data.get("avg_margin_pct") is not None:
            _pdf_kpis.append({"label": "Margen promedio", "value": f"{_safe_float(_kpis_data.get('avg_margin_pct'), 0.0):.2f}%"})
          _vol = _safe_float(_kpis_data.get("volume_total_eur"), 0.0)
          if _vol > 0:
            _pdf_kpis.append({"label": "Volumen total", "value": f"€{_vol/1_000_000:.2f}M" if _vol >= 1_000_000 else f"€{_vol:,.0f}"})

        # ── Semáforo de alertas/decisiones ───────────────────────────────
        _dec_raw = (result.get("decisions") or {}).get("strategic_decisions") or []
        _pdf_alerts = [
          {
            "urgencia":    str(d.get("urgencia") or d.get("priority") or "MEDIA"),
            "titulo":      str(d.get("titulo")   or d.get("action")   or "—"),
            "tipo":        str(d.get("tipo")     or d.get("type")     or "—"),
            "descripcion": str(d.get("descripcion") or d.get("why")   or "—"),
          }
          for d in _dec_raw[:12]
          if d.get("titulo") or d.get("action")
        ]

        # ── Graficos para PDF ─────────────────────────────────────────────
        _pdf_charts: list[dict[str, Any]] = [{
          "type": "bar",
          "title": "Scores consolidados del análisis",
          "x": ["Oportunidad", "Rentabilidad", "Viabilidad", "Riesgo (inv.)"],
          "y": [opp, int(rent), int(viab), max(0, 100 - int(risk))],
        }]
        if _mode == "clientes":
          _high = int(_safe_float(_kpis_data.get("high_risk_clients"), 0.0))
          _med = int(_safe_float(_kpis_data.get("medium_risk_clients"), 0.0))
          _low = int(_safe_float(_kpis_data.get("low_risk_clients"), 0.0))
          _ret = _safe_float(_kpis_data.get("retention_rate"), 0.0) * 100
          _churn = _safe_float(_kpis_data.get("avg_churn_score"), max(0.0, 1.0 - (_ret / 100.0))) * 100
          _pdf_charts.append({
            "type": "bar",
            "title": "Distribucion de clientes por nivel de riesgo",
            "x": ["Alto", "Medio", "Bajo"],
            "y": [_high, _med, _low],
          })
          _pdf_charts.append({
            "type": "bar",
            "title": "Indicadores de churn y retencion (%)",
            "x": ["Churn", "Retencion"],
            "y": [round(_churn, 1), round(_ret, 1)],
          })
        elif _mode == "operaciones":
          _conv = _safe_float(_kpis_data.get("conversion_rate"), 0.0) * 100
          _sell = _safe_float(_kpis_data.get("sell_through_rate"), 0.0) * 100
          _canc = _safe_float(_kpis_data.get("cancellation_rate"), 0.0) * 100
          _pdf_charts.append({
            "type": "bar",
            "title": "KPIs comerciales (%)",
            "x": ["Conversion", "Sell-through", "Cancelacion"],
            "y": [round(_conv, 1), round(_sell, 1), round(_canc, 1)],
          })
          _series = _commercial_output.get("series") or []
          if isinstance(_series, list) and _series:
            _sdf = pd.DataFrame(_series)
            _x_key = next((k for k in ["label", "month", "period", "date", "estado"] if k in _sdf.columns), None)
            _y_key = next((k for k in ["units_sold", "count", "value", "revenue_eur"] if k in _sdf.columns), None)
            if _x_key and _y_key:
              _x_vals = [str(v) for v in _sdf[_x_key].tolist()[:16]]
              _y_vals = [_safe_float(v, 0.0) for v in _sdf[_y_key].tolist()[:16]]
              _pdf_charts.append({
                "type": "bar",
                "title": "Distribucion por estado o periodo",
                "x": _x_vals,
                "y": _y_vals,
              })

        _risk_matrix_desc = {
          "BAJO": "Exposicion controlada",
          "LOW": "Exposicion controlada",
          "MEDIO": "Exposicion moderada",
          "MED": "Exposicion moderada",
          "ALTO": "Exposicion elevada",
          "HIGH": "Exposicion elevada",
          "CRITICO": "Exposicion critica",
          "CRITICAL": "Exposicion critica",
        }
        _rm_pdf = inf.get("matriz_riesgo", {}) or {}
        _risk_matrix_rows = [
          {"dimension": "Precio", "nivel": str(_rm_pdf.get("riesgo_precio", _rm_pdf.get("riesgo_concentracion", "MEDIO"))).upper()},
          {"dimension": "Absorcion", "nivel": str(_rm_pdf.get("riesgo_absorcion", "MEDIO")).upper()},
          {"dimension": "Financiero", "nivel": str(_rm_pdf.get("riesgo_financiero", "MEDIO")).upper()},
          {"dimension": "Mercado", "nivel": str(_rm_pdf.get("riesgo_mercado", "MEDIO")).upper()},
        ]
        for _rr in _risk_matrix_rows:
          _rr["interpretacion"] = _risk_matrix_desc.get(_rr["nivel"], "Requiere seguimiento")

        _overview_pdf = executive_summary.get("overview") or inf.get("resumen_ejecutivo") or summary.get("executive_message") or "Sin resumen disponible."
        _hallazgos_pdf = inf.get("hallazgos_clave") or []
        _next_steps_pdf = executive_summary.get("recommended_actions") or inf.get("proximos_pasos") or []
        _scores_pdf = [
          {"label": "Score oportunidad", "value": opp, "note": str(summary.get("score_label", "Estado general"))},
          {"label": "Score rentabilidad", "value": int(rent), "note": "Modelo cuantitativo"},
          {"label": "Viabilidad financiera", "value": int(viab), "note": str(af.get("valoracion_financiera", "Analista financiero"))},
          {"label": "Score riesgo", "value": int(risk), "note": f"Alertas activas: {k.get('alerts', 0)}"},
        ]
        _trace_pdf = result.get("traceability", {}) or {}
        _location_parts = [str(n8n_raw.get("zona_geografica") or "").strip(), str(n8n_raw.get("ccaa") or "").strip()]
        _location_pdf = " · ".join([p for p in _location_parts if p and p.lower() not in {"none", "null"}])

        _analysis_context = {
          "meta": {
            "document_name": doc_name,
            "report_type": result.get("report_type") or tipo_display,
            "document_type": doc_type,
            "decision_source": decision_source,
            "run_id": run_id,
            "provider": st.session_state.get("prd_provider", "local"),
            "location": _location_pdf,
          },
          "executive": {
            "overview": _overview_pdf,
            "hallazgos": _hallazgos_pdf,
            "next_steps": _next_steps_pdf,
          },
          "decisions": _dec_raw,
          "risk_matrix": _risk_matrix_rows,
          "agents": {
            "data_scientist": ds or (result.get("agents", {}) or {}).get("data_scientist", {}),
            "analista_financiero": af or (result.get("agents", {}) or {}).get("analista_financiero", {}),
            "analista_mercado": am or (result.get("agents", {}) or {}).get("analista_mercado", {}),
          },
          "scores": _scores_pdf,
          "traceability": _trace_pdf,
        }

        st.session_state["prd_display_markdown"] = _analysis_context_to_markdown(_analysis_context)
        st.session_state["prd_pdf_bytes"] = build_prd_pdf_bytes(
          prd_text="",
          document_name=f"{_titulo_ctx} — PRD",
          provider=st.session_state.get("prd_provider", "local"),
          kpis=_pdf_kpis,
          charts=_pdf_charts,
          alerts_table=_pdf_alerts if _pdf_alerts else None,
          analysis_context=_analysis_context,
        )
        st.rerun()
    else:
      st.download_button(
        "⬇ Descargar PDF PRD",
        data=_pdf_bytes,
        file_name=f"PRD_{doc_name.replace('.pdf', '')}.pdf",
        mime="application/pdf",
        use_container_width=True,
        type="primary",
      )

  with _ac3:
    # Botón descarga PRD texto si ya está generado
    if _prd_ready:
      st.download_button(
        "📋 Descargar PRD (.txt)",
        data=_prd_current.encode("utf-8"),
        file_name=f"PRD_{doc_name.replace('.pdf','')}.txt",
        mime="text/plain",
        use_container_width=True,
      )
    else:
      st.markdown('<div style="height:38px;"></div>', unsafe_allow_html=True)

  if _prd_ready:
    _prd_src = st.session_state.get("prd_provider", "—")
    _prd_is_fb = "fallback" in str(_prd_src).lower()
    _prd_src_clean = "Local (sin conexion n8n)" if _prd_is_fb else str(_prd_src)
    st.markdown(
      f'<div style="margin:8px 0 0 0;padding:8px 14px;'
      f'background:{"#fff8e10a" if _prd_is_fb else "#00417d0a"};border-radius:8px;'
      f'font-size:11px;color:{"#8b6914" if _prd_is_fb else "#00417d"};text-align:center;">'
      f'{"AVISO" if _prd_is_fb else "OK"} PRD generado · '
      f'Fuente: <b>{xml_escape(_prd_src_clean)}</b></div>',
      unsafe_allow_html=True,
    )

  # ── INFORME EJECUTIVO ─────────────────────────────────────────────────────
  overview   = executive_summary.get("overview") or inf.get("resumen_ejecutivo") or summary.get("executive_message") or "Sin resumen disponible."
  next_steps = executive_summary.get("recommended_actions") or inf.get("proximos_pasos") or []
  hallazgos  = inf.get("hallazgos_clave") or []
  n_alertas  = int(_safe_float(inf.get("alertas_detectadas", len(hallazgos)), 0))

  st.markdown(
    f"""
    <div style="display:flex;align-items:center;gap:14px;padding:16px 22px;
                background:linear-gradient(135deg,#e3eaf5 0%,#f5f7fc 100%);
                border-left:4px solid #00417d;border-radius:12px;margin:28px 0 18px;
                box-shadow:0 2px 8px rgba(0,65,125,0.08);">
      <div style="width:44px;height:44px;background:linear-gradient(135deg,#00417d,#002d5a);
                  border-radius:11px;display:flex;align-items:center;justify-content:center;
                  flex-shrink:0;box-shadow:0 3px 8px rgba(0,45,90,0.3);">
        <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="1.8"
             stroke-linecap="round" stroke-linejoin="round" style="width:22px;height:22px;">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14 2 14 8 20 8"/>
          <line x1="16" y1="13" x2="8" y2="13"/>
          <line x1="16" y1="17" x2="8" y2="17"/>
        </svg>
      </div>
      <div style="flex:1;">
        <div style="font-size:17px;font-weight:800;color:#002d5a;letter-spacing:-0.3px;line-height:1.2;">
          INFORME EJECUTIVO
        </div>
        <div style="font-size:12px;color:#4a6fa8;margin-top:3px;">
          Consolidado por el agente orquestador · {n_alertas} hallazgos detectados
        </div>
      </div>
      <div style="background:rgba(0,65,125,0.12);border:1px solid rgba(0,65,125,0.2);
                  border-radius:8px;padding:6px 14px;text-align:center;flex-shrink:0;">
        <div style="font-size:10px;color:#00417d;font-weight:800;letter-spacing:0.5px;">CONSOLIDADO</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
  )

  # Resumen ejecutivo
  st.markdown(
    f"""
    <div style="background:#f8f9fc;border:1px solid #e8eaf0;border-radius:12px;padding:18px 20px;margin-bottom:16px;">
      <div style="font-size:10px;font-weight:700;color:#00417d;text-transform:uppercase;
                  letter-spacing:.08em;margin-bottom:8px;">Resumen Ejecutivo</div>
      <div style="font-size:13px;color:#2d2d2d;line-height:1.75;">{xml_escape(str(overview))}</div>
    </div>
    """,
    unsafe_allow_html=True,
  )

  # Hallazgos clave como chips si existen
  if hallazgos:
    _chips_html = "".join(
      f'<div style="display:flex;align-items:flex-start;gap:10px;padding:9px 12px;'
      f'background:white;border:1px solid #e8eaf0;border-radius:10px;margin-bottom:8px;">'
      f'<span style="width:22px;height:22px;background:#c4922a20;color:#c4922a;border-radius:6px;'
      f'font-size:11px;font-weight:800;display:flex;align-items:center;justify-content:center;flex-shrink:0;">{i+1}</span>'
      f'<span style="font-size:12px;color:#333;line-height:1.55;">{xml_escape(str(h))}</span></div>'
      for i, h in enumerate(hallazgos[:5])
    )
    st.markdown(
      f'<div style="margin-bottom:16px;"><div style="font-size:10px;font-weight:700;color:#c4922a;'
      f'text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px;">⚠ Hallazgos Clave</div>'
      f'{_chips_html}</div>',
      unsafe_allow_html=True,
    )

  # Próximos pasos como timeline — solo items con texto real y significativo
  _PLACEHOLDER_PATTERNS = {"alerta ds", "debilidad financiera", "alerta #", "paso #", "decision #"}
  _next_steps_clean = [
    s for s in next_steps
    if str(s).strip() and not any(pat in str(s).lower() for pat in _PLACEHOLDER_PATTERNS)
  ]
  if _next_steps_clean:
    _steps_html = "".join(
      f'<div style="display:flex;align-items:flex-start;gap:14px;padding:10px 0;'
      f'{"border-bottom:1px solid #e8eaf0;" if i < len(_next_steps_clean[:5])-1 else ""}">'
      f'<div style="width:28px;height:28px;background:#00417d;color:white;border-radius:50%;'
      f'font-size:12px;font-weight:800;display:flex;align-items:center;justify-content:center;'
      f'flex-shrink:0;margin-top:2px;">{i+1}</div>'
      f'<div style="font-size:13px;color:#2d2d2d;line-height:1.65;">{xml_escape(str(s))}</div>'
      f'</div>'
      for i, s in enumerate(_next_steps_clean[:5])
    )
    st.markdown(
      f'<div style="background:#f8f9fc;border:1px solid #e8eaf0;border-radius:12px;padding:16px 20px;">'
      f'<div style="font-size:10px;font-weight:700;color:#00417d;text-transform:uppercase;'
      f'letter-spacing:.08em;margin-bottom:12px;">PROXIMOS PASOS RECOMENDADOS</div>'
      f'<div style="font-size:11px;color:#666;margin-bottom:14px;font-style:italic;">'
      f'Acciones concretas a ejecutar tras este analisis para maximizar el impacto de la decision.</div>'
      f'{_steps_html}</div>',
      unsafe_allow_html=True,
    )

  decisions = (result.get("decisions") or {}).get("strategic_decisions", []) or []
  _n_alta  = sum(1 for d in decisions if str(d.get("priority","")).lower() in {"alta","high"})
  _n_media = sum(1 for d in decisions if str(d.get("priority","")).lower() in {"media","medium","med"})
  _n_baja  = sum(1 for d in decisions if str(d.get("priority","")).lower() in {"baja","low"})

  st.markdown(
    f"""
    <div style="display:flex;align-items:center;gap:14px;padding:16px 22px;
                background:linear-gradient(135deg,#fce8e8 0%,#fff8f8 100%);
                border-left:4px solid #c62828;border-radius:12px;margin:28px 0 18px;
                box-shadow:0 2px 8px rgba(198,40,40,0.08);">
      <div style="width:44px;height:44px;background:linear-gradient(135deg,#c62828,#8b1c1c);
                  border-radius:11px;display:flex;align-items:center;justify-content:center;
                  flex-shrink:0;box-shadow:0 3px 8px rgba(139,28,28,0.3);">
        <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="1.8"
             stroke-linecap="round" stroke-linejoin="round" style="width:22px;height:22px;">
          <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
        </svg>
      </div>
      <div style="flex:1;">
        <div style="font-size:17px;font-weight:800;color:#7f1c1c;letter-spacing:-0.3px;line-height:1.2;">
          DECISIONES PRIORITARIAS
        </div>
        <div style="font-size:12px;color:#a05050;margin-top:3px;">
          Acciones recomendadas por el orquestador · {len(decisions)} decisiones totales
        </div>
      </div>
      <div style="display:flex;gap:8px;flex-shrink:0;">
        <div style="background:#c6282815;border:1px solid #c6282840;color:#c62828;font-size:11px;
                    font-weight:700;padding:5px 11px;border-radius:8px;">A {_n_alta} ALTA</div>
        <div style="background:#e6510015;border:1px solid #e6510040;color:#e65100;font-size:11px;
                    font-weight:700;padding:5px 11px;border-radius:8px;">M {_n_media} MEDIA</div>
        <div style="background:#2e7d3215;border:1px solid #2e7d3240;color:#2e7d32;font-size:11px;
                    font-weight:700;padding:5px 11px;border-radius:8px;">B {_n_baja} BAJA</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
  )

  if decisions:
    for d in decisions:
      p        = str(d.get("priority", "media")).lower()
      is_alta  = "alta" in p or "high" in p
      is_baja  = "baja" in p or "low" in p
      actor    = _decision_actor(d, doc_type)
      action   = str(d.get("action") or "Sin accion")
      why      = _decision_why_text(d)
      conf     = _safe_float(d.get("confidence", d.get("confianza")), 0.0)
      # Colores por prioridad
      if is_alta:
        border_c, bg_c, badge_c, badge_txt, lbl_c = "#c62828", "#fff5f5", "#c62828", "URGENTE", "#c62828"
        pri_icon = "A"
      elif is_baja:
        border_c, bg_c, badge_c, badge_txt, lbl_c = "#2e7d32", "#f0faf0", "#2e7d32", "BAJA PRIORIDAD", "#2e7d32"
        pri_icon = "B"
      else:
        border_c, bg_c, badge_c, badge_txt, lbl_c = "#e65100", "#fff8f0", "#e65100", "MEDIA", "#e65100"
        pri_icon = "M"
      conf_html = (f'<span style="font-size:10px;color:#888;margin-left:auto;">Confianza: <b style="color:{border_c};">{conf:.0f}%</b></span>' if conf > 0 else "")
      st.markdown(
        f"""
        <div style="border-left:5px solid {border_c};background:{bg_c};border-radius:0 12px 12px 0;
                    padding:14px 18px;margin-bottom:10px;display:flex;gap:14px;align-items:flex-start;">
          <div style="width:44px;height:44px;background:{border_c};color:white;border-radius:10px;
                      font-size:18px;display:flex;align-items:center;justify-content:center;
                      flex-shrink:0;font-weight:900;">{pri_icon}</div>
          <div style="flex:1;min-width:0;">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;flex-wrap:wrap;">
              <span style="background:{badge_c};color:white;font-size:10px;font-weight:800;
                           padding:2px 10px;border-radius:20px;letter-spacing:.06em;">{badge_txt}</span>
              <span style="font-size:11px;color:#888;">{xml_escape(actor)}</span>
              {conf_html}
            </div>
            <div style="font-size:14px;font-weight:700;color:#1a1a1a;line-height:1.4;margin-bottom:5px;">{xml_escape(action)}</div>
            <div style="font-size:12px;color:#555;line-height:1.55;">{xml_escape(why)}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
      )
  else:
    st.markdown(
      '<div style="padding:20px;background:#f0faf0;border:1px solid #c8e6c9;border-radius:12px;'
      'text-align:center;color:#2e7d32;font-size:13px;font-weight:600;">'
      '✓ Sin decisiones urgentes. El escenario actual no requiere acciones inmediatas.</div>',
      unsafe_allow_html=True,
    )

  rm = inf.get("matriz_riesgo", {}) or {}

  def _risk_cls(value: str) -> str:
    v = str(value).upper()
    if v in {"BAJO", "LOW"}:      return "LOW"
    if v in {"ALTO", "HIGH"}:     return "HIGH"
    if v in {"CRITICO", "CRITICAL"}: return "CRIT"
    return "MED"

  def _risk_pct(value: str) -> int:
    v = str(value).upper()
    if v in {"BAJO", "LOW"}:      return 28
    if v in {"ALTO", "HIGH"}:     return 82
    if v in {"CRITICO", "CRITICAL"}: return 98
    return 55

  def _risk_fill_color(value: str) -> str:
    v = str(value).upper()
    if v in {"BAJO", "LOW"}:         return "#2e7d32"
    if v in {"ALTO", "HIGH"}:        return "#e65100"
    if v in {"CRITICO", "CRITICAL"}: return "#c62828"
    return "#c4922a"

  _RISK_META = {
    "Precio": {
      "icon": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>',
      "desc": {"BAJO": "Precios alineados con el mercado. Sin anomalias detectadas en la cartera.",
               "MEDIO": "Variaciones moderadas en precio por m2. Se recomienda revision de outliers.",
               "ALTO": "Inconsistencias significativas en precios. Requiere auditoria urgente.",
               "CRITICO": "Precios fuera de rango critico. Riesgo de perdida de ingresos inmediato."},
    },
    "Absorcion": {
      "icon": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>',
      "desc": {"BAJO": "Ritmo de absorcion de stock saludable. Demanda activa en las zonas analizadas.",
               "MEDIO": "Absorcion dentro de parametros normales. Vigilar evolucion mensual.",
               "ALTO": "Stock con baja rotacion. Se recomienda revision de estrategia comercial.",
               "CRITICO": "Paralisis de absorcion detectada. Exposicion patrimonial elevada."},
    },
    "Financiero": {
      "icon": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/><line x1="12" y1="12" x2="12.01" y2="12"/></svg>',
      "desc": {"BAJO": "Estructura financiera solida. Ratios de viabilidad en rango optimo.",
               "MEDIO": "Viabilidad financiera aceptable. Margenes ajustados en algunos segmentos.",
               "ALTO": "Ratios financieros deteriorados. Revisar estructura de costes y financiacion.",
               "CRITICO": "Viabilidad comprometida. Se requiere plan de reestructuracion urgente."},
    },
    "Mercado": {
      "icon": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/><line x1="2" y1="20" x2="22" y2="20"/></svg>',
      "desc": {"BAJO": "Condiciones de mercado favorables. Tendencia positiva en las regiones clave.",
               "MEDIO": "Mercado mixto con variaciones por zona. Oportunidades selectivas identificadas.",
               "ALTO": "Presion de mercado significativa. Competencia elevada o demanda debil.",
               "CRITICO": "Contraccion de mercado severa. Posicionamiento estrategico urgente."},
    },
  }

  risk_cells = [
    ("Precio",    rm.get("riesgo_precio",    rm.get("riesgo_concentracion", "MEDIO"))),
    ("Absorcion",  rm.get("riesgo_absorcion", "MEDIO")),
    ("Financiero", rm.get("riesgo_financiero", "MEDIO")),
    ("Mercado",   rm.get("riesgo_mercado",   "MEDIO")),
  ]

  st.markdown(
    """
    <div style="display:flex;align-items:center;gap:14px;padding:16px 22px;
                background:linear-gradient(135deg,#ede7f6 0%,#f9f7fd 100%);
                border-left:4px solid #6a1b9a;border-radius:12px;margin:28px 0 18px;
                box-shadow:0 2px 8px rgba(106,27,154,0.08);">
      <div style="width:44px;height:44px;background:linear-gradient(135deg,#6a1b9a,#4a148c);
                  border-radius:11px;display:flex;align-items:center;justify-content:center;
                  flex-shrink:0;box-shadow:0 3px 8px rgba(74,20,140,0.3);">
        <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="1.8"
             stroke-linecap="round" stroke-linejoin="round" style="width:22px;height:22px;">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
        </svg>
      </div>
      <div style="flex:1;">
        <div style="font-size:17px;font-weight:800;color:#4a148c;letter-spacing:-0.3px;line-height:1.2;">
          MATRIZ DE RIESGO
        </div>
        <div style="font-size:12px;color:#7b4fa8;margin-top:3px;">
          Evaluacion multidimensional del portafolio
        </div>
      </div>
      <div style="background:rgba(106,27,154,0.10);border:1px solid rgba(106,27,154,0.2);
                  border-radius:8px;padding:6px 14px;text-align:center;flex-shrink:0;">
        <div style="font-size:10px;color:#6a1b9a;font-weight:800;letter-spacing:0.5px;">4 DIMENSIONES</div>
      </div>
    </div>
    <div class="risk-grid">
    """,
    unsafe_allow_html=True,
  )
  for label, value in risk_cells:
    cls  = _risk_cls(str(value))
    pct  = _risk_pct(str(value))
    fill = _risk_fill_color(str(value))
    meta = _RISK_META.get(label, {})
    icon = meta.get("icon", "")
    desc_map = meta.get("desc", {})
    desc = desc_map.get(str(value).upper(), desc_map.get("MEDIO", "Sin descripcion disponible."))
    icon_colored = icon.replace('stroke="currentColor"', f'stroke="{fill}"')
    st.markdown(
      f"""
      <div class="risk-cell" style="flex-direction:column;align-items:flex-start;padding:16px 18px;gap:10px;">
        <div style="display:flex;align-items:center;gap:10px;width:100%;">
          <div class="risk-ico" style="width:36px;height:36px;background:rgba(0,65,125,0.07);border-radius:8px;display:flex;align-items:center;justify-content:center;flex-shrink:0;">
            <div style="width:20px;height:20px;">{icon_colored}</div>
          </div>
          <div style="flex:1;">
            <div class="risk-lbl">{label}</div>
            <div class="risk-val {cls}">{xml_escape(str(value))}</div>
          </div>
          <div style="font-size:22px;font-weight:900;color:{fill};opacity:0.18;">{pct}%</div>
        </div>
        <div style="width:100%;height:5px;background:rgba(149,152,154,0.20);border-radius:3px;overflow:hidden;">
          <div style="height:100%;width:{pct}%;background:{fill};border-radius:3px;transition:width 0.6s;"></div>
        </div>
        <div style="font-size:12px;color:var(--muted);line-height:1.55;">{xml_escape(desc)}</div>
      </div>
      """,
      unsafe_allow_html=True,
    )
  st.markdown("</div></div>", unsafe_allow_html=True)

  st.markdown(
    """
    <div style="display:flex;align-items:center;gap:14px;padding:16px 22px;
                background:linear-gradient(135deg,#e3eaf8 0%,#f5f7ff 100%);
                border-left:4px solid #1a5aac;border-radius:12px;margin:28px 0 18px;
                box-shadow:0 2px 8px rgba(26,90,172,0.08);">
      <div style="width:44px;height:44px;background:linear-gradient(135deg,#1a5aac,#0d3472);
                  border-radius:11px;display:flex;align-items:center;justify-content:center;
                  flex-shrink:0;box-shadow:0 3px 8px rgba(13,52,114,0.3);">
        <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="1.8"
             stroke-linecap="round" stroke-linejoin="round" style="width:22px;height:22px;">
          <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
          <circle cx="9" cy="7" r="4"/>
          <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
          <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
        </svg>
      </div>
      <div style="flex:1;">
        <div style="font-size:17px;font-weight:800;color:#0d3472;letter-spacing:-0.3px;line-height:1.2;">
          ANALISIS DE AGENTES IA
        </div>
        <div style="font-size:12px;color:#4a6fa8;margin-top:3px;">
          Resultados individuales por especialidad — 3 agentes especializados
        </div>
      </div>
      <div style="background:rgba(26,90,172,0.12);border:1px solid rgba(26,90,172,0.2);
                  border-radius:8px;padding:6px 14px;text-align:center;">
        <div style="font-size:18px;font-weight:900;color:#1a5aac;">3</div>
        <div style="font-size:10px;color:#4a6fa8;font-weight:600;letter-spacing:0.5px;">AGENTES</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
  )
  tab_ds, tab_af, tab_am = st.tabs(["Data Scientist", "Analista Financiero", "Analista de Mercado"])

  with tab_ds:
    if ds:
      score_g  = _safe_float(ds.get("score_global"), 0.0)
      score_ri = _safe_float(ds.get("score_riesgo"), 0.0)
      score_re = _safe_float(ds.get("score_rentabilidad"), 0.0)
      roi      = ds.get("roi_estimado_pct")
      conclusiones = ds.get("conclusiones") or []
      alertas  = ds.get("alertas_cuantitativas") or []
      _ds_score_color = "#2e7d32" if score_g >= 70 else "#c4922a" if score_g >= 50 else "#c62828"
      st.markdown(
        f"""
        <div style="background:linear-gradient(135deg,#0d47a1 0%,#1976d2 60%,#1e88e5 100%);
                    border-radius:14px;padding:20px 24px;margin-bottom:22px;
                    display:flex;align-items:center;gap:18px;
                    box-shadow:0 4px 16px rgba(13,71,161,0.3);">
          <div style="width:52px;height:52px;background:rgba(255,255,255,0.15);
                      border-radius:12px;display:flex;align-items:center;justify-content:center;flex-shrink:0;">
            <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="1.8"
                 stroke-linecap="round" stroke-linejoin="round" style="width:26px;height:26px;">
              <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
            </svg>
          </div>
          <div style="flex:1;">
            <div style="font-size:17px;font-weight:800;color:white;letter-spacing:-0.2px;">Data Scientist</div>
            <div style="font-size:12px;color:rgba(255,255,255,0.75);margin-top:3px;">
              Analisis cuantitativo • Modelos predictivos • Scoring de riesgo y rentabilidad
            </div>
          </div>
          <div style="background:rgba(255,255,255,0.15);border:1px solid rgba(255,255,255,0.25);
                      border-radius:10px;padding:10px 18px;text-align:center;flex-shrink:0;">
            <div style="font-size:26px;font-weight:900;color:white;line-height:1;">{score_g:.0f}</div>
            <div style="font-size:10px;color:rgba(255,255,255,0.75);font-weight:600;letter-spacing:0.5px;margin-top:2px;">SCORE GLOBAL</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
      )
      def _bar(val: float, color: str) -> str:
        pct = max(0.0, min(100.0, val))
        return f'<div style="height:6px;border-radius:3px;background:rgba(149,152,154,.20);margin-top:4px;"><div style="height:100%;width:{pct:.0f}%;background:{color};border-radius:3px;"></div></div>'
      st.markdown(
        f"""
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:18px;">
          <div class="kpi"><div class="kpi-label">Score global</div>
            <div class="kpi-value {'ok' if score_g>=70 else 'gold' if score_g>=50 else 'danger'}">{score_g:.0f}</div>
            {_bar(score_g,'#2e7d32' if score_g>=70 else '#c4922a' if score_g>=50 else '#c62828')}
            <div class="kpi-hint">Puntuacion general del analisis</div></div>
          <div class="kpi"><div class="kpi-label">Score de riesgo</div>
            <div class="kpi-value {'danger' if score_ri>=70 else 'gold' if score_ri>=40 else 'ok'}">{score_ri:.0f}</div>
            {_bar(score_ri,'#c62828' if score_ri>=70 else '#c4922a' if score_ri>=40 else '#2e7d32')}
            <div class="kpi-hint">Nivel de exposicion al riesgo</div></div>
          <div class="kpi"><div class="kpi-label">Score rentabilidad</div>
            <div class="kpi-value {'ok' if score_re>=70 else 'gold' if score_re>=50 else 'danger'}">{score_re:.0f}</div>
            {_bar(score_re,'#2e7d32' if score_re>=70 else '#c4922a' if score_re>=50 else '#c62828')}
            <div class="kpi-hint">Potencial de retorno estimado</div></div>
        </div>
        """,
        unsafe_allow_html=True,
      )
      if roi is not None:
        st.markdown(f'<div class="card" style="margin-bottom:12px;"><div class="card-title">ROI Estimado</div><div style="font-size:26px;font-weight:900;color:var(--insur-blue);">{_safe_float(roi,0.0):.2f}%</div></div>', unsafe_allow_html=True)
      if conclusiones:
        st.markdown('<div class="card"><div class="card-title">Conclusiones del analisis</div>', unsafe_allow_html=True)
        for c in conclusiones[:5]:
          st.markdown(f'<div style="padding:8px 0;border-bottom:1px solid var(--line);font-size:13px;line-height:1.6;color:var(--text);">• {xml_escape(str(c))}</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
      if alertas:
        st.markdown('<div class="card card-danger" style="margin-top:12px;"><div class="card-title">Alertas cuantitativas</div>', unsafe_allow_html=True)
        for a in alertas[:5]:
          if isinstance(a, dict):
            nivel = str(a.get("nivel","")).upper()
            chip_cls = "chip-high" if nivel=="ALTO" else "chip-med" if nivel=="MEDIO" else "chip-low"
            st.markdown(
              f'<div style="display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid var(--line);">'
              f'<span class="chip {chip_cls}">{xml_escape(str(nivel) or "ALERTA")}</span>'
              f'<span style="font-size:12px;color:var(--text);">{xml_escape(str(a.get("campo","")))} — doc: <b>{xml_escape(str(a.get("valor_doc","")))}</b> / bench: {xml_escape(str(a.get("benchmark","")))} / desv: {xml_escape(str(a.get("desviacion","")))}</span>'
              f'</div>',
              unsafe_allow_html=True,
            )
          else:
            st.markdown(
              f'<div style="display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid var(--line);">'
              f'<span class="chip chip-med">ALERTA</span>'
              f'<span style="font-size:12px;color:var(--text);">{xml_escape(str(a))}</span>'
              f'</div>',
              unsafe_allow_html=True,
            )
        st.markdown('</div>', unsafe_allow_html=True)
    else:
      st.info("No hay salida detallada del Data Scientist.")

  with tab_af:
    if af:
      score_v  = _safe_float(af.get("score_viabilidad"), 0.0)
      val_fin  = str(af.get("valoracion_financiera") or "N/D")
      conclusion = str(af.get("conclusion_financiera") or "")
      fortalezas = af.get("fortalezas") or []
      debilidades = af.get("debilidades") or []
      anomalias = af.get("anomalias_financieras") or []
      val_color = "#2e7d32" if val_fin in {"BUENA","EXCELENTE"} else "#c4922a" if val_fin=="ACEPTABLE" else "#c62828"
      _af_grad_end = "#2e7d32" if val_fin in {"BUENA","EXCELENTE"} else "#c4922a" if val_fin=="ACEPTABLE" else "#b71c1c"
      _af_grad_start = "#1b5e20" if val_fin in {"BUENA","EXCELENTE"} else "#e65100" if val_fin=="ACEPTABLE" else "#7f0000"
      st.markdown(
        f"""
        <div style="background:linear-gradient(135deg,{_af_grad_start} 0%,{_af_grad_end} 100%);
                    border-radius:14px;padding:20px 24px;margin-bottom:22px;
                    display:flex;align-items:center;gap:18px;
                    box-shadow:0 4px 16px rgba(27,94,32,0.3);">
          <div style="width:52px;height:52px;background:rgba(255,255,255,0.15);
                      border-radius:12px;display:flex;align-items:center;justify-content:center;flex-shrink:0;">
            <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="1.8"
                 stroke-linecap="round" stroke-linejoin="round" style="width:26px;height:26px;">
              <line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>
            </svg>
          </div>
          <div style="flex:1;">
            <div style="font-size:17px;font-weight:800;color:white;letter-spacing:-0.2px;">Analista Financiero</div>
            <div style="font-size:12px;color:rgba(255,255,255,0.75);margin-top:3px;">
              Evaluacion financiera • Ratios clave • Fortalezas y debilidades del portafolio
            </div>
          </div>
          <div style="background:rgba(255,255,255,0.15);border:1px solid rgba(255,255,255,0.25);
                      border-radius:10px;padding:10px 18px;text-align:center;flex-shrink:0;">
            <div style="font-size:18px;font-weight:900;color:white;line-height:1;">{xml_escape(val_fin)}</div>
            <div style="font-size:10px;color:rgba(255,255,255,0.75);font-weight:600;letter-spacing:0.5px;margin-top:2px;">VALORACION</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
      )
      st.markdown(
        f"""
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:18px;">
          <div class="kpi">
            <div class="kpi-label">Score de viabilidad</div>
            <div class="kpi-value {'ok' if score_v>=70 else 'gold' if score_v>=50 else 'danger'}">{score_v:.0f}</div>
            <div style="height:6px;border-radius:3px;background:rgba(149,152,154,.20);margin-top:4px;">
              <div style="height:100%;width:{min(score_v,100):.0f}%;background:{'#2e7d32' if score_v>=70 else '#c4922a' if score_v>=50 else '#c62828'};border-radius:3px;"></div>
            </div>
            <div class="kpi-hint">Solidez financiera del portafolio</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">Valoracion financiera</div>
            <div class="kpi-value" style="color:{val_color};font-size:22px;">{xml_escape(val_fin)}</div>
            <div class="kpi-hint">Clasificacion del analista financiero</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
      )
      if conclusion:
        st.markdown(f'<div class="card" style="margin-bottom:12px;"><div class="card-title">Conclusion financiera</div><div class="card-body">{xml_escape(conclusion)}</div></div>', unsafe_allow_html=True)
      col_f, col_d = st.columns(2)
      with col_f:
        if fortalezas:
          st.markdown('<div class="card card-ok"><div class="card-title">Fortalezas</div>', unsafe_allow_html=True)
          for f in fortalezas[:4]:
            st.markdown(f'<div style="padding:5px 0;font-size:12px;color:var(--ok);">✓ {xml_escape(str(f))}</div>', unsafe_allow_html=True)
          st.markdown('</div>', unsafe_allow_html=True)
      with col_d:
        if debilidades:
          st.markdown('<div class="card card-danger"><div class="card-title">Debilidades</div>', unsafe_allow_html=True)
          for d in debilidades[:4]:
            st.markdown(f'<div style="padding:5px 0;font-size:12px;color:var(--danger);">✗ {xml_escape(str(d))}</div>', unsafe_allow_html=True)
          st.markdown('</div>', unsafe_allow_html=True)
      if anomalias:
        st.markdown('<div class="card card-gold" style="margin-top:12px;"><div class="card-title">Anomalias detectadas</div>', unsafe_allow_html=True)
        for a in anomalias[:5]:
          st.markdown(f'<div style="padding:5px 0;font-size:12px;color:var(--warn);">⚠ {xml_escape(str(a))}</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
    else:
      st.info("No hay salida detallada del Analista Financiero.")

  with tab_am:
    if am:
      posicion  = str(am.get("posicionamiento_mercado") or "N/D")
      tendencia = str(am.get("tendencia_zona") or "N/D")
      conclusion_m = str(am.get("conclusion_mercado") or "")
      oportunidades = am.get("oportunidades") or []
      amenazas = am.get("amenazas") or []
      pos_color = "#2e7d32" if posicion in {"FAVORABLE","POSITIVO"} else "#c62828" if posicion in {"DESFAVORABLE","NEGATIVO","CRITICO"} else "#c4922a"
      ten_color = "#2e7d32" if tendencia in {"ESTABLE","ALCISTA","POSITIVA"} else "#c62828" if tendencia in {"BAJISTA","NEGATIVA","NEGATIVO","DECRECIENTE"} else "#c4922a"
      _am_ten_icon = "↑" if tendencia in {"ALCISTA","POSITIVA"} else "↓" if tendencia in {"BAJISTA","NEGATIVA","DECRECIENTE"} else "→"
      st.markdown(
        f"""
        <div style="background:linear-gradient(135deg,#4a148c 0%,#7b1fa2 60%,#9c27b0 100%);
                    border-radius:14px;padding:20px 24px;margin-bottom:22px;
                    display:flex;align-items:center;gap:18px;
                    box-shadow:0 4px 16px rgba(74,20,140,0.3);">
          <div style="width:52px;height:52px;background:rgba(255,255,255,0.15);
                      border-radius:12px;display:flex;align-items:center;justify-content:center;flex-shrink:0;">
            <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="1.8"
                 stroke-linecap="round" stroke-linejoin="round" style="width:26px;height:26px;">
              <circle cx="12" cy="12" r="10"/>
              <line x1="2" y1="12" x2="22" y2="12"/>
              <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
            </svg>
          </div>
          <div style="flex:1;">
            <div style="font-size:17px;font-weight:800;color:white;letter-spacing:-0.2px;">Analista de Mercado</div>
            <div style="font-size:12px;color:rgba(255,255,255,0.75);margin-top:3px;">
              Tendencias de zona • Posicionamiento competitivo • Oportunidades y amenazas
            </div>
          </div>
          <div style="background:rgba(255,255,255,0.15);border:1px solid rgba(255,255,255,0.25);
                      border-radius:10px;padding:10px 18px;text-align:center;flex-shrink:0;">
            <div style="font-size:20px;font-weight:900;color:white;line-height:1;">{_am_ten_icon} {xml_escape(tendencia)}</div>
            <div style="font-size:10px;color:rgba(255,255,255,0.75);font-weight:600;letter-spacing:0.5px;margin-top:2px;">TENDENCIA ZONA</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
      )
      st.markdown(
        f"""
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:18px;">
          <div class="kpi">
            <div class="kpi-label">Posicionamiento</div>
            <div class="kpi-value" style="color:{pos_color};font-size:20px;">{xml_escape(posicion)}</div>
            <div class="kpi-hint">Evaluacion competitiva en el mercado</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">Tendencia de zona</div>
            <div class="kpi-value" style="color:{ten_color};font-size:20px;">{xml_escape(tendencia)}</div>
            <div class="kpi-hint">Direccion del mercado en regiones clave</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
      )
      if conclusion_m:
        st.markdown(f'<div class="card" style="margin-bottom:12px;"><div class="card-title">Conclusion de mercado</div><div class="card-body">{xml_escape(conclusion_m)}</div></div>', unsafe_allow_html=True)
      col_o, col_a2 = st.columns(2)
      with col_o:
        if oportunidades:
          st.markdown('<div class="card card-ok"><div class="card-title">Oportunidades</div>', unsafe_allow_html=True)
          for o in oportunidades[:4]:
            st.markdown(f'<div style="padding:5px 0;font-size:12px;color:var(--ok);">→ {xml_escape(str(o))}</div>', unsafe_allow_html=True)
          st.markdown('</div>', unsafe_allow_html=True)
      with col_a2:
        if amenazas:
          st.markdown('<div class="card card-danger"><div class="card-title">Amenazas</div>', unsafe_allow_html=True)
          for a in amenazas[:4]:
            st.markdown(f'<div style="padding:5px 0;font-size:12px;color:var(--danger);">⚡ {xml_escape(str(a))}</div>', unsafe_allow_html=True)
          st.markdown('</div>', unsafe_allow_html=True)
    else:
      st.info("No hay salida detallada del Analista de Mercado.")

  render_executive_visuals(result=result, doc_type=doc_type, k=k, normalized=normalized)

  # ── SCORES CONSOLIDADOS (después de KPIs) ─────────────────────────────────
  st.markdown(
    """
    <div style="display:flex;align-items:center;gap:14px;padding:16px 22px;
                background:linear-gradient(135deg,#f0f4ff 0%,#f8f9ff 100%);
                border-left:4px solid #5c7cfa;border-radius:12px;margin:28px 0 18px;
                box-shadow:0 2px 8px rgba(92,124,250,0.08);">
      <div style="width:44px;height:44px;background:linear-gradient(135deg,#5c7cfa,#3b5bdb);
                  border-radius:11px;display:flex;align-items:center;justify-content:center;
                  flex-shrink:0;box-shadow:0 3px 8px rgba(59,91,219,0.3);">
        <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="1.8"
             stroke-linecap="round" stroke-linejoin="round" style="width:22px;height:22px;">
          <circle cx="12" cy="12" r="10"/>
          <polyline points="12 6 12 12 16 14"/>
        </svg>
      </div>
      <div style="flex:1;">
        <div style="font-size:17px;font-weight:800;color:#1e3a8a;letter-spacing:-0.3px;line-height:1.2;">
          SCORES CONSOLIDADOS
        </div>
        <div style="font-size:12px;color:#4a6fa8;margin-top:3px;">
          Puntuaciones globales del analisis multidimensional
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
  )
  _sc1, _sc2, _sc3, _sc4 = st.columns(4)
  with _sc1:
    st.markdown(_score_card("Score Oportunidad", opp, summary.get("score_label", "—"), "#c4922a", _ico_opp), unsafe_allow_html=True)
  with _sc2:
    st.markdown(_score_card("Score Rentabilidad", rent, "Data Scientist", "#2e7d32", _ico_rent), unsafe_allow_html=True)
  with _sc3:
    st.markdown(_score_card("Viabilidad Financiera", viab, af.get("valoracion_financiera", "Analista Fin."), "#00417d", _ico_viab), unsafe_allow_html=True)
  with _sc4:
    st.markdown(_score_card("Score Riesgo", risk, f"Alertas: {k.get('alerts',0)}", "#c62828", _ico_risk, invert=True), unsafe_allow_html=True)
  st.markdown('<div style="margin-top:8px;"></div>', unsafe_allow_html=True)

  with st.expander("Detalle tecnico: metricas y trazabilidad", expanded=False):
    trace = result.get("traceability", {}) or {}
    classification = ((normalized.get("interpretation") or {}).get("classification") or {})
    _td_rows = ""
    _td_items = [
      ("Score global",        summary.get("score", "—")),
      ("Score label",         summary.get("score_label", "—")),
      ("Alertas detectadas",  summary.get("alerts", "—")),
      ("Decisiones",          summary.get("decisions", "—")),
      ("Tendencia",           summary.get("trend", "—")),
      ("run_id",              result.get("run_id", "—")),
      ("Tipo de documento",   normalized.get("document_type", "—")),
      ("Fuente",              trace.get("fuente") or trace.get("source_file", "—")),
      ("Registros procesados",trace.get("num_registros_procesados") or trace.get("num_records", "—")),
      ("Regiones analizadas", ", ".join(str(r) for r in (trace.get("regiones_analizadas") or trace.get("regions", []))) or "—"),
      ("Modelos ejecutados",  ", ".join(str(m.get("name","")) for m in (trace.get("models_executed") or [])) or "—"),
      ("Clasificacion",       classification.get("predicted_class") or classification.get("type", "—")),
    ]
    for _lbl, _val in _td_items:
      _td_rows += f"""
      <div style="display:flex;justify-content:space-between;align-items:baseline;
                  padding:7px 0;border-bottom:1px solid var(--line);">
        <span style="font-size:12px;font-weight:700;color:var(--muted);">{xml_escape(str(_lbl))}</span>
        <span style="font-size:13px;font-weight:600;color:var(--text);max-width:55%;text-align:right;">{xml_escape(str(_val))}</span>
      </div>"""
    _alert_rows = ""
    for _a in (trace.get("alertas_calidad") or [])[:8]:
      _alert_rows += f'<div style="font-size:12px;color:#c4922a;padding:4px 0;">⚠ {xml_escape(str(_a))}</div>'
    _impr_rows = ""
    for _ip in (trace.get("improvement_plan") or [])[:5]:
      _impr_rows += f'<div style="font-size:12px;color:var(--text);padding:4px 0;"><b style="color:var(--insur-blue);">[{xml_escape(str(_ip.get("priority","")))}]</b> {xml_escape(str(_ip.get("title","") or _ip.get("recommendation","")))}</div>'
    st.markdown(
      f"""
      <div style="background:#f8fafc;border-radius:10px;padding:20px 24px;margin-top:8px;">
        <div style="font-size:13px;font-weight:900;color:var(--insur-blue);letter-spacing:1px;
                    text-transform:uppercase;margin-bottom:12px;">Metricas del analisis</div>
        {_td_rows}
        {'<div style="font-size:13px;font-weight:900;color:#c4922a;letter-spacing:1px;text-transform:uppercase;margin:18px 0 8px;">Alertas de calidad</div>' + _alert_rows if _alert_rows else ''}
        {'<div style="font-size:13px;font-weight:900;color:var(--insur-blue);letter-spacing:1px;text-transform:uppercase;margin:18px 0 8px;">Plan de mejora</div>' + _impr_rows if _impr_rows else ''}
      </div>
      """,
      unsafe_allow_html=True,
    )

  st.markdown(
    """
    <div style="display:flex;align-items:center;gap:14px;padding:16px 22px;
                background:linear-gradient(135deg,#fff8e1 0%,#fffdf8 100%);
                border-left:4px solid #c4922a;border-radius:12px;margin:28px 0 18px;
                box-shadow:0 2px 8px rgba(196,146,42,0.10);">
      <div style="width:44px;height:44px;background:linear-gradient(135deg,#c4922a,#8b6914);
                  border-radius:11px;display:flex;align-items:center;justify-content:center;flex-shrink:0;">
        <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="1.8"
             stroke-linecap="round" stroke-linejoin="round" style="width:22px;height:22px;">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14 2 14 8 20 8"/>
          <line x1="16" y1="13" x2="8" y2="13"/>
          <line x1="16" y1="17" x2="8" y2="17"/>
          <polyline points="10 9 9 9 8 9"/>
        </svg>
      </div>
      <div style="flex:1;">
        <div style="font-size:17px;font-weight:800;color:#7a5c10;letter-spacing:-0.3px;line-height:1.2;">
          PRODUCT REQUIREMENTS DOCUMENT
        </div>
        <div style="font-size:12px;color:#a87c28;margin-top:3px;">
          Documento estructurado de requerimientos del producto
        </div>
      </div>
      <div style="background:#c4922a;border-radius:8px;padding:5px 14px;">
        <span style="font-size:12px;font-weight:800;color:#ffffff;letter-spacing:1px;">PRD</span>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
  )
  prd_text = st.session_state.get("prd_display_markdown") or st.session_state.get("prd_text", "")
  if prd_text:
    provider = st.session_state.get("prd_provider", "unknown")
    note = st.session_state.get("prd_note", "")
    _is_fallback = "fallback" in str(provider).lower() or bool(note)
    _src_label = "Local (fallback)" if _is_fallback else str(provider or "n8n")
    _status_bg  = "#fff8e1" if _is_fallback else "#e8f5e9"
    _status_bd  = "#f0c060" if _is_fallback else "#a5d6a7"
    _status_col = "#7a5c10" if _is_fallback else "#1b5e20"
    _status_ico = "AVISO" if _is_fallback else "OK"
    _status_sub = "Generado localmente · el webhook n8n no respondio en este momento" if _is_fallback else "Generado por el agente n8n con los datos del analisis"
    st.markdown(
      f"""
      <div style="display:flex;align-items:center;gap:12px;padding:12px 18px;
                  background:{_status_bg};border:1px solid {_status_bd};
                  border-radius:10px;margin-bottom:22px;">
        <span style="font-size:16px;">{_status_ico}</span>
        <div>
          <div style="font-size:12px;font-weight:700;color:{_status_col};">
            PRD listo · Fuente: {xml_escape(_src_label)}
          </div>
          <div style="font-size:11px;color:#777;margin-top:2px;">{xml_escape(_status_sub)}</div>
        </div>
      </div>
      """,
      unsafe_allow_html=True,
    )
    st.markdown(prd_text)
  else:
    st.markdown(
      """
      <div style="padding:24px 28px;background:#f8f9fa;border:2px dashed #d0d7e4;
                  border-radius:12px;text-align:center;margin-top:8px;">
        <div style="font-size:32px;margin-bottom:10px;">📄</div>
        <div style="font-size:15px;font-weight:700;color:#00417d;margin-bottom:6px;">PRD no generado aun</div>
        <div style="font-size:13px;color:#666;">Pulsa <strong>Generar PRD</strong> en la seccion de acciones para crear el documento.</div>
      </div>
      """,
      unsafe_allow_html=True,
    )


# Main 
def main() -> None:
  inject_styles()

  # Session state init
  defaults = {
    "screen": "upload", "result": None, "prd_text": "", "prd_note": "",
    "prd_provider": "", "prd_pdf_bytes": None, "prd_display_markdown": "",
    "prefetch_extract": None, "prefetch_sig": "",
    "prefetch_state": "idle", "prefetch_error": "",
    "n8n_health": "unknown",
  }
  for k, v in defaults.items():
    if k not in st.session_state:
      st.session_state[k] = v

  top_nav()

  with st.sidebar:
    st.markdown(
      '<div style="font-family:\'Lato\',sans-serif;font-size:13px;font-weight:900;color:#ffffff;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:20px;padding-bottom:12px;border-bottom:1px solid rgba(255,255,255,0.15);">Configuracion</div>',
      unsafe_allow_html=True,
    )
    n8n_webhook_url = st.text_input(
      "n8n Webhook URL",
      value=DEFAULT_N8N_URL,
      placeholder="https://tu-n8n/webhook/insur-multiagente",
      help="Toda la orquestacion de analisis y decisiones se ejecuta via n8n.",
    )
    st.session_state["n8n_webhook_url"] = n8n_webhook_url
    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
    horizon_days = st.slider("Horizonte (dias)", 30, 180, 90, 10)
    macro_pressure = st.slider("Presion macro", 0.70, 1.30, 1.00, 0.01)
    demand_pressure = st.slider("Presion demanda", 0.70, 1.30, 1.00, 0.01)
    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
    if st.button("Verificar n8n", use_container_width=True):
      try:
        if not n8n_webhook_url.strip():
          raise RuntimeError("Debes completar n8n Webhook URL.")
        probe = api_post_n8n(
          n8n_webhook_url,
          {
            "probe": True,
            "source": "insur_streamlit_frontend",
            "timestamp": int(time.time()),
          },
        )
        payload = {
          "n8n_probe": {
            "ok": True,
            "keys": list(probe.keys())[:12] if isinstance(probe, dict) else [],
          }
        }
        st.session_state["n8n_health"] = "online"
        st.success("Conectividad n8n verificada")
        st.json(payload)
      except Exception as exc:
        st.session_state["n8n_health"] = "offline"
        st.error(str(exc))

  if st.session_state["screen"] == "upload":
    render_upload_screen(
      horizon_days=horizon_days,
      macro_pressure=macro_pressure,
      demand_pressure=demand_pressure,
      n8n_webhook_url=n8n_webhook_url,
    )
  else:
    render_result_screen(n8n_webhook_url=n8n_webhook_url)


if __name__ == "__main__":
  main()




