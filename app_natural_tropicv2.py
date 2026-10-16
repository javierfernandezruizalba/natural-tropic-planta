from datetime import datetime
import json
import os
import sqlite3
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# =============================================================================
# CONFIGURACIÓN Y ESTILO CORPORATIVO
# =============================================================================
st.set_page_config(
    page_title="Natural Tropic S.L. — Inteligencia Industrial y Costes",
    page_icon="🥑",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .block-container { padding-top: 1.2rem; padding-bottom: 2rem; }
    div[data-testid="stMetric"] {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-left: 5px solid #059669;
        padding: 12px 16px;
        border-radius: 10px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }
    .ai-card-crit { background:#fef2f2; border-left:5px solid #dc2626; padding:14px; border-radius:8px; margin-bottom:10px; }
    .ai-card-high { background:#fffbeb; border-left:5px solid #d97706; padding:14px; border-radius:8px; margin-bottom:10px; }
    .ai-card-med  { background:#eff6ff; border-left:5px solid #2563eb; padding:14px; border-radius:8px; margin-bottom:10px; }
    </style>
""",
    unsafe_allow_html=True,
)

DB_FILE = "natural_tropic_planta.db"
ADMIN_PIN = (
    st.secrets.get("ADMIN_PIN", "1234") if hasattr(st, "secrets") else "1234"
)

LINES_LIST = [
    "C1 Mango",
    "C2 Chirimoya",
    "Flowpack",
    "Girsac",
    "Mango",
    "Multiscan",
    "Pitaya",
    "Repaso",
    "Verde",
    "Verde 2",
]

MONTH_NAMES = {
    1: "ene",
    2: "feb",
    3: "mar",
    4: "abr",
    5: "may",
    6: "jun",
    7: "jul",
    8: "ago",
    9: "sep",
    10: "oct",
    11: "nov",
    12: "dic",
}

DEFAULT_TARGETS = {
    "C1 Mango": {
        "eurVen": 0.1374,
        "eurVol": 0.0750,
        "kghVen": 96.05,
        "kghMov": 176.20,
    },
    "C2 Chirimoya": {
        "eurVen": 0.0650,
        "eurVol": 0.0550,
        "kghVen": 210.00,
        "kghMov": 240.00,
    },
    "Flowpack": {
        "eurVen": 0.1600,
        "eurVol": 0.1500,
        "kghVen": 82.00,
        "kghMov": 88.00,
    },
    "Girsac": {
        "eurVen": 0.1150,
        "eurVol": 0.0800,
        "kghVen": 115.00,
        "kghMov": 165.00,
    },
    "Mango": {
        "eurVen": 0.1850,
        "eurVol": 0.1100,
        "kghVen": 72.00,
        "kghMov": 120.00,
    },
    "Multiscan": {
        "eurVen": 0.4500,
        "eurVol": 0.1050,
        "kghVen": 30.00,
        "kghMov": 125.00,
    },
    "Pitaya": {
        "eurVen": 0.1600,
        "eurVol": 0.1200,
        "kghVen": 82.00,
        "kghMov": 110.00,
    },
    "Repaso": {
        "eurVen": 0.2100,
        "eurVol": 0.1500,
        "kghVen": 62.00,
        "kghMov": 88.00,
    },
    "Verde": {
        "eurVen": 0.1550,
        "eurVol": 0.1400,
        "kghVen": 85.00,
        "kghMov": 95.00,
    },
    "Verde 2": {
        "eurVen": 0.1950,
        "eurVol": 0.1500,
        "kghVen": 68.00,
        "kghMov": 88.00,
    },
}

OWN_GROUP_MAP = {
    "C1 Mango": ["CALIBRADOR1"],
    "C2 Chirimoya": ["CHIRIMOYA"],
    "Flowpack": ["FLOWPACK"],
    "Girsac": ["GIRSAC"],
    "Mango": ["MANGO"],
    "Multiscan": ["MULTISCAN"],
    "Repaso": ["MULTISCAN", "MANGO"],
    "Verde": ["VERDE1"],
    "Verde 2": ["VERDE2"],
}


# =============================================================================
# BASE DE DATOS Y CONFIGURACIÓN
# =============================================================================
def init_db():
  conn = sqlite3.connect(DB_FILE)
  c = conn.cursor()
  c.execute("""
        CREATE TABLE IF NOT EXISTS mov_almacen (
            dISO TEXT, y TEXT, mISO TEXT, wISO TEXT, lReal TEXT,
            conf TEXT, emb TEXT, cajas REAL, kgTeo REAL, kgReal REAL,
            isDestrio INTEGER, isInterno INTEGER, cliente TEXT
        )
    """)
  c.execute("""
        CREATE TABLE IF NOT EXISTS mov_ventas (
            dISO TEXT, y TEXT, mISO TEXT, wISO TEXT, lReal TEXT,
            cajas REAL, kgTeo REAL, kgReal REAL, cliente TEXT
        )
    """)
  c.execute("""
        CREATE TABLE IF NOT EXISTS fichajes (
            dISO TEXT, y TEXT, mISO TEXT, wISO TEXT, lReal TEXT,
            horas REAL, tipoCoste INTEGER, operacion TEXT, grupoTrab TEXT
        )
    """)
  c.execute("""
        CREATE TABLE IF NOT EXISTS config_store (
            k TEXT PRIMARY KEY, v TEXT
        )
    """)
  conn.commit()
  conn.close()


def get_config(key, default_val):
  conn = sqlite3.connect(DB_FILE)
  c = conn.cursor()
  c.execute("SELECT v FROM config_store WHERE k = ?", (key,))
  row = c.fetchone()
  conn.close()
  if row:
    return json.loads(row[0])
  return default_val


def set_config(key, val):
  conn = sqlite3.connect(DB_FILE)
  c = conn.cursor()
  c.execute(
      "INSERT OR REPLACE INTO config_store (k, v) VALUES (?, ?)",
      (key, json.dumps(val)),
  )
  conn.commit()
  conn.close()


init_db()


# =============================================================================
# MOTOR DE LECTURA DE LAS 4 PESTAÑAS Y LIMPIEZA
# =============================================================================
def map_linea_real(raw_val, existing_real=None):
  if pd.notna(existing_real):
    s_ex = str(existing_real).strip()
    if s_ex in LINES_LIST:
      return s_ex
  if pd.isna(raw_val):
    return None
  lin = str(raw_val).strip().upper()
  if not lin or lin == "NAN":
    return None
  if lin.startswith("FP") or "FLOWPACK" in lin:
    return "Flowpack"
  if lin.startswith("CA1"):
    return "C1 Mango"
  if lin.startswith("CA2"):
    return "C2 Chirimoya"
  if lin.startswith("GIRSAC"):
    return "Girsac"
  if lin in ["MANGO", "MESA AUX B"]:
    return "Mango"
  if lin == "MESA AUX":
    return "Repaso"
  if lin.startswith("MULTISCAN") and "PISTACHO" not in lin:
    return "Multiscan"
  if lin == "PITAYA":
    return "Pitaya"
  if lin in ["VERDE1 AGU", "VERDE"]:
    return "Verde"
  if lin in ["VERDE2 AGU", "VERDE 2"]:
    return "Verde 2"
  return None


def clean_num_series(s):
  if s is None:
    return 0.0
  if pd.api.types.is_numeric_dtype(s):
    return s.fillna(0.0).astype(float)
  return (
      pd.to_numeric(
          s.astype(str).str.strip().str.replace(",", ".", regex=False),
          errors="coerce",
      )
      .fillna(0.0)
      .astype(float)
  )


def enrich_dates(df, date_col):
  raw_s = df[date_col]
  dt = pd.to_datetime(raw_s, dayfirst=True, errors="coerce")
  mask_na = dt.isna()
  if mask_na.any():
    dt_iso = pd.to_datetime(raw_s[mask_na], errors="coerce")
    dt.loc[mask_na] = dt_iso
  df = df.loc[dt.notna()].copy()
  dt = dt.loc[dt.notna()]

  df["dISO"] = dt.dt.strftime("%Y-%m-%d")
  df["y"] = dt.dt.strftime("%Y")
  m_num = dt.dt.month
  df["mISO"] = dt.dt.strftime("%Y-%m") + " (" + m_num.map(MONTH_NAMES) + ")"
  iso_cal = dt.dt.isocalendar()
  df["wISO"] = (
      iso_cal["year"].astype(str)
      + "-W"
      + iso_cal["week"].apply(lambda x: f"{int(x):02d}")
  )
  return df


def parse_mov_df(df):
  df.columns = [str(c).strip() for c in df.columns]
  if "Fecha" not in df.columns:
    return pd.DataFrame()
  df = enrich_dates(df, "Fecha")
  if df.empty:
    return pd.DataFrame()

  col_lin = "Línea producción" if "Línea producción" in df.columns else None
  col_real = "Linea real" if "Linea real" in df.columns else None
  df["lReal"] = [
      map_linea_real(
          df[col_lin].iloc[i] if col_lin else None,
          df[col_real].iloc[i] if col_real else None,
      )
      for i in range(len(df))
  ]
  df["cajas"] = clean_num_series(df.get("Cajas", 0))
  df["kgTeo"] = clean_num_series(df.get("Neto teo.", 0))
  df["kgReal"] = clean_num_series(df.get("Neto real", 0))
  df["emb"] = (
      df.get("Embalaje", pd.Series([""] * len(df), index=df.index))
      .fillna("")
      .astype(str)
      .str.strip()
      .str.upper()
  )
  df["conf"] = (
      df.get("Confección", pd.Series([""] * len(df), index=df.index))
      .fillna("")
      .astype(str)
      .str.strip()
      .str.upper()
  )
  df["conf"] = np.where(df["conf"] == "", df["emb"], df["conf"])
  pos = (
      df.get("Posición", pd.Series([""] * len(df), index=df.index))
      .fillna("")
      .astype(str)
      .str.upper()
  )
  cat = (
      df.get("Categoria", pd.Series([""] * len(df), index=df.index))
      .fillna("")
      .astype(str)
      .str.upper()
  )
  df["isDestrio"] = (
      (cat == "DX")
      | pos.str.contains("DESTRIO|BASURA|ACEITE|PODRIDO|GUACAMOLE", regex=True)
  ).astype(int)
  df["isInterno"] = (
      (df["emb"] == "USOINT")
      | pos.str.contains("REPASO|USO|SOBRANTE|DESCALIBRADO", regex=True)
  ).astype(int)
  df["cliente"] = (
      df.get("Cliente", pd.Series([""] * len(df), index=df.index))
      .fillna("")
      .astype(str)
      .str.strip()
  )
  return df[[
      "dISO",
      "y",
      "mISO",
      "wISO",
      "lReal",
      "conf",
      "emb",
      "cajas",
      "kgTeo",
      "kgReal",
      "isDestrio",
      "isInterno",
      "cliente",
  ]]


def parse_ven_df(df):
  df.columns = [str(c).strip() for c in df.columns]
  if "Fecha" not in df.columns:
    return pd.DataFrame()
  df = enrich_dates(df, "Fecha")
  if df.empty:
    return pd.DataFrame()

  col_lin = "Línea producción" if "Línea producción" in df.columns else None
  col_real = "Linea real" if "Linea real" in df.columns else None
  df["lReal"] = [
      map_linea_real(
          df[col_lin].iloc[i] if col_lin else None,
          df[col_real].iloc[i] if col_real else None,
      )
      for i in range(len(df))
  ]
  df["cajas"] = clean_num_series(df.get("Cajas", 0))
  df["kgTeo"] = clean_num_series(df.get("Neto teo.", 0))
  df["kgReal"] = clean_num_series(df.get("Neto real", 0))
  df["cliente"] = (
      df.get("Cliente", pd.Series([""] * len(df), index=df.index))
      .fillna("")
      .astype(str)
      .str.strip()
  )
  return df[[
      "dISO",
      "y",
      "mISO",
      "wISO",
      "lReal",
      "cajas",
      "kgTeo",
      "kgReal",
      "cliente",
  ]]


def parse_fic_df(df):
  df.columns = [str(c).strip() for c in df.columns]
  date_col = (
      "Fecha (Asignado)"
      if "Fecha (Asignado)" in df.columns
      else ("Fecha" if "Fecha" in df.columns else None)
  )
  if not date_col:
    return pd.DataFrame()
  df = enrich_dates(df, date_col)
  if df.empty:
    return pd.DataFrame()

  col_lin = "Línea" if "Línea" in df.columns else None
  col_real = "Linea real" if "Linea real" in df.columns else None
  df["lReal"] = [
      map_linea_real(
          df[col_lin].iloc[i] if col_lin else None,
          df[col_real].iloc[i] if col_real else None,
      )
      for i in range(len(df))
  ]
  df["horas"] = clean_num_series(df.get("Total horas", 0))
  tc = clean_num_series(df.get("Tipo coste", 0)).astype(int)
  df["tipoCoste"] = np.where(tc > 0, tc, np.where(df["lReal"].notna(), 1, 2))
  df["operacion"] = (
      df.get("Operación", pd.Series([""] * len(df), index=df.index))
      .fillna("")
      .astype(str)
      .str.strip()
      .str.upper()
  )
  df["grupoTrab"] = (
      df.get("Grupo TRABAJADOR", pd.Series([""] * len(df), index=df.index))
      .fillna("")
      .astype(str)
      .str.strip()
      .str.upper()
  )
  return df[[
      "dISO",
      "y",
      "mISO",
      "wISO",
      "lReal",
      "horas",
      "tipoCoste",
      "operacion",
      "grupoTrab",
  ]]


def process_annual_workbook(uploaded_file):
  """Procesa el Excel maestro anual que tiene las 4 pestañas:

  1. Resúmenes/Tablas dinámicas (Se ignora)
  2. Fichajes
  3. Partes de producción
  4. Movimientos de ventas
  """
  xls = pd.ExcelFile(uploaded_file)
  n_m, n_v, n_f = 0, 0, 0

  for s_name in xls.sheet_names:
    s_up = s_name.strip().upper()
    # Ignorar pestañas de resúmenes o tablas dinámicas
    if "RESUMEN" in s_up or "DINAMIC" in s_up or "TABLA" in s_up:
      continue

    df_s = pd.read_excel(xls, sheet_name=s_name)
    if df_s.empty or len(df_s.columns) < 4:
      continue
    cols = [str(c).strip() for c in df_s.columns]

    # Detectar por nombre de pestaña o por columnas clave
    if "FICHAJ" in s_up or "ID TRABAJADOR" in [c.upper() for c in cols]:
      parsed_f = parse_fic_df(df_s)
      n_f += save_dataframe_to_db(parsed_f, "fichajes")
    elif "VENTA" in s_up:
      parsed_v = parse_ven_df(df_s)
      n_v += save_dataframe_to_db(parsed_v, "mov_ventas")
    elif "PARTE" in s_up or "PRODUCCION" in s_up or "ALMACEN" in s_up:
      parsed_m = parse_mov_df(df_s)
      n_m += save_dataframe_to_db(parsed_m, "mov_almacen")
    else:
      # Detección inteligente por columnas si el nombre de la pestaña es genérico
      if "ID trabajador" in cols or "Total horas" in cols:
        n_f += save_dataframe_to_db(parse_fic_df(df_s), "fichajes")
      elif "Neto real" in cols:
        if "VENTA" in s_up:
          n_v += save_dataframe_to_db(parse_ven_df(df_s), "mov_ventas")
        else:
          n_m += save_dataframe_to_db(parse_mov_df(df_s), "mov_almacen")

  return n_m, n_v, n_f


def save_dataframe_to_db(df, table_name):
  if df is None or df.empty:
    return 0
  days = df["dISO"].dropna().unique().tolist()
  conn = sqlite3.connect(DB_FILE)
  c = conn.cursor()
  placeholders = ",".join(["?"] * len(days))
  c.execute(f"DELETE FROM {table_name} WHERE dISO IN ({placeholders})", days)
  conn.commit()
  df.to_sql(table_name, conn, if_exists="append", index=False)
  conn.close()
  return len(df)


@st.cache_data(ttl=2)
def load_all_from_db():
  conn = sqlite3.connect(DB_FILE)
  df_m = pd.read_sql_query("SELECT * FROM mov_almacen", conn)
  df_v = pd.read_sql_query("SELECT * FROM mov_ventas", conn)
  df_f = pd.read_sql_query("SELECT * FROM fichajes", conn)
  conn.close()
  return df_m, df_v, df_f


# =============================================================================
# BARRA LATERAL Y CONTROLES
# =============================================================================
with st.sidebar:
  st.markdown("## 🥑 Natural Tropic S.L.")
  st.caption("Panel Centralizado en Tiempo Real")

  rates_cfg = get_config("RATES", {"dir": 13.20, "ind": 14.00, "fruit": 2.40})
  c_r1, c_r2 = st.columns(2)
  rate_dir = c_r1.number_input(
      "€/H Directo", value=float(rates_cfg["dir"]), step=0.10
  )
  rate_ind = c_r2.number_input(
      "€/H Indirecto", value=float(rates_cfg["ind"]), step=0.10
  )
  fruit_price = st.number_input(
      "Precio Fruta (€/kg)",
      value=float(rates_cfg.get("fruit", 2.40)),
      step=0.10,
  )

  if (
      rate_dir != rates_cfg["dir"]
      or rate_ind != rates_cfg["ind"]
      or fruit_price != rates_cfg.get("fruit", 2.40)
  ):
    set_config("RATES", {"dir": rate_dir, "ind": rate_ind, "fruit": fruit_price})

  st.markdown("---")
  with st.expander("🔐 Panel de Ingeniero (Subir Datos / Admin)", expanded=False):
    pin_input = st.text_input("PIN de Ingeniero (1234)", type="password")
    if pin_input == ADMIN_PIN:
      st.success("Modo Administrador Activo")
      up_annual_excels = st.file_uploader(
          "📗 Subir Excel Maestro Anual (4 pestañas)",
          type=["xlsx", "xls"],
          accept_multiple_files=True,
      )

      if st.button(
          "🚀 Procesar Libros Anuales", type="primary", use_container_width=True
      ):
        tot_m, tot_v, tot_f = 0, 0, 0
        with st.spinner(
            "Leyendo pestañas de Fichajes, Partes y Ventas del Excel..."
        ):
          for f in up_annual_excels or []:
            nm, nv, nf = process_annual_workbook(f)
            tot_m += nm
            tot_v += nv
            tot_f += nf
        st.cache_data.clear()
        st.success(
            f"✅ Importado con éxito: +{tot_m} Partes | +{tot_v} Ventas | +{tot_f}"
            " Fichajes"
        )
        st.rerun()

      if st.button("🗑️ Vaciar Base de Datos", use_container_width=True):
        conn = sqlite3.connect(DB_FILE)
        conn.execute("DELETE FROM mov_almacen")
        conn.execute("DELETE FROM mov_ventas")
        conn.execute("DELETE FROM fichajes")
        conn.commit()
        conn.close()
        st.cache_data.clear()
        st.rerun()
    elif pin_input != "":
      st.error("PIN incorrecto")


# =============================================================================
# CARGA DE DATOS Y RENDERIZADO DE LAS 4 PESTAÑAS
# =============================================================================
df_mov, df_ven, df_fic = load_all_from_db()

all_days = sorted(
    list(
        set(df_mov["dISO"].dropna().tolist())
        | set(df_ven["dISO"].dropna().tolist())
        | set(df_fic["dISO"].dropna().tolist())
    )
)

st.markdown(
    f"### 🥑 NATURAL TROPIC S.L. — Inteligencia Operativa de Planta y Control"
    f" de Costes  <span style='font-size:13px; background:#065f46;"
    f" color:#a7f3d0; padding:4px 10px; border-radius:99px;'>Histórico Activo:"
    f" {len(all_days)} días ({len(df_mov)+len(df_ven)+len(df_fic):,} registros)</span>",
    unsafe_allow_html=True,
)

if len(all_days) == 0:
  st.info(
      "👈 Abre el **'🔐 Panel de Ingeniero'** en la barra izquierda (PIN:"
      " `1234`), sube tus archivos Excel anuales de 2024, 2025 o 2026 y pulsa"
      " **'🚀 Procesar Libros Anuales'**."
  )
  st.stop()

f_c1, f_c2, f_c3, f_c4, f_c5, f_c6 = st.columns(6)

all_years = sorted(
    list(
        set(df_mov["y"].dropna())
        | set(df_ven["y"].dropna())
        | set(df_fic["y"].dropna())
    )
)
sel_year = f_c1.selectbox("📅 Año", ["TODOS"] + all_years)

m_mov, m_ven, m_fic = df_mov.copy(), df_ven.copy(), df_fic.copy()
if sel_year != "TODOS":
  m_mov, m_ven, m_fic = (
      m_mov[m_mov["y"] == sel_year],
      m_ven[m_ven["y"] == sel_year],
      m_fic[m_fic["y"] == sel_year],
  )

all_months = sorted(
    list(
        set(m_mov["mISO"].dropna())
        | set(m_ven["mISO"].dropna())
        | set(m_fic["mISO"].dropna())
    )
)
sel_month = f_c2.selectbox("🗓️ Mes", ["TODOS"] + all_months)
if sel_month != "TODOS":
  m_mov, m_ven, m_fic = (
      m_mov[m_mov["mISO"] == sel_month],
      m_ven[m_ven["mISO"] == sel_month],
      m_fic[m_fic["mISO"] == sel_month],
  )

all_weeks = sorted(
    list(
        set(m_mov["wISO"].dropna())
        | set(m_ven["wISO"].dropna())
        | set(m_fic["wISO"].dropna())
    )
)
sel_week = f_c3.selectbox("📆 Semana ISO", ["TODAS"] + all_weeks)
if sel_week != "TODAS":
  m_mov, m_ven, m_fic = (
      m_mov[m_mov["wISO"] == sel_week],
      m_ven[m_ven["wISO"] == sel_week],
      m_fic[m_fic["wISO"] == sel_week],
  )

avail_days = sorted(
    list(
        set(m_mov["dISO"].dropna())
        | set(m_ven["dISO"].dropna())
        | set(m_fic["dISO"].dropna())
    )
)
sel_day = f_c4.selectbox("📍 Día Exacto", ["TODOS"] + avail_days)
if sel_day != "TODOS":
  m_mov, m_ven, m_fic = (
      m_mov[m_mov["dISO"] == sel_day],
      m_ven[m_ven["dISO"] == sel_day],
      m_fic[m_fic["dISO"] == sel_day],
  )

sel_line = f_c5.selectbox("🏭 Línea Real", ["TODAS"] + LINES_LIST)
if sel_line != "TODAS":
  m_mov, m_ven, m_fic = (
      m_mov[m_mov["lReal"] == sel_line],
      m_ven[m_ven["lReal"] == sel_line],
      m_fic[m_fic["lReal"] == sel_line],
  )

group_mode = f_c6.selectbox(
    "📊 Agrupar Tabla Por",
    ["Línea Real", "Año", "Mes", "Semana ISO", "Día"],
)

targets = get_config("TARGETS", DEFAULT_TARGETS)


def status_badge_str(line_name, eur_ven_val):
  t = targets.get(line_name)
  if not t or eur_ven_val <= 0 or t["eurVen"] <= 0:
    return "—"
  diff_pct = ((eur_ven_val - t["eurVen"]) / t["eurVen"]) * 100
  if diff_pct <= -3:
    return f"🟢 {diff_pct:+.1f}% vs Obj"
  elif diff_pct <= 8:
    return f"🟡 {diff_pct:+.1f}% vs Obj"
  else:
    return f"🔴 {diff_pct:+.1f}% vs Obj"


tab_dash, tab_give, tab_targ, tab_ai = st.tabs([
    "📊 1. Cuadro de Mando y Tabla Dinámica",
    "⚖️ 2. Ranking Sobrepeso (Clientes y Confecciones)",
    "🎯 3. Umbrales Objetivos (Histórico vs Actual)",
    "🧠 4. Diagnóstico IA y Cuellos de Botella en Planta",
])

with tab_dash:
  f_dir_mask = m_fic["lReal"].isin(LINES_LIST)
  tot_h_dir = float(m_fic.loc[f_dir_mask, "horas"].sum())
  tot_h_ind = float(m_fic.loc[~f_dir_mask, "horas"].sum())
  tot_h_all = tot_h_dir + tot_h_ind

  m_dir = m_mov[m_mov["lReal"].isin(LINES_LIST)]
  v_dir = m_ven[m_ven["lReal"].isin(LINES_LIST)]

  tot_kg_mov = float(m_dir["kgReal"].sum())
  tot_kg_teo = float(m_dir["kgTeo"].sum())
  tot_kg_ven = float(v_dir["kgReal"].sum())

  imp_dir = tot_h_dir * rate_dir
  imp_ind = tot_h_ind * rate_ind
  imp_tot = imp_dir + imp_ind

  eur_ven_dir = imp_dir / tot_kg_ven if tot_kg_ven > 0 else 0.0
  eur_ven_ind = imp_ind / tot_kg_ven if tot_kg_ven > 0 else 0.0
  eur_ven_tot = eur_ven_dir + eur_ven_ind
  kgh_ven_tot = tot_kg_ven / tot_h_dir if tot_h_dir > 0 else 0.0

  k1, k2, k3, k4, k5, k6 = st.columns(6)
  k1.metric(
      "Coste MO Directa",
      f"{imp_dir:,.0f} €",
      f"{tot_h_dir:,.1f} h ({(tot_h_dir/tot_h_all*100 if tot_h_all>0 else 0):.0f}%)",
  )
  k2.metric(
      "Coste MO Indirecta",
      f"{imp_ind:,.0f} €",
      f"{tot_h_ind:,.1f} h ({(tot_h_ind/tot_h_all*100 if tot_h_all>0 else 0):.0f}%)",
  )
  k3.metric("Coste Total Personal", f"{imp_tot:,.0f} €", f"{tot_h_all:,.1f} h totales")
  k4.metric(
      "Movido vs Vendido",
      f"{tot_kg_mov/1000:,.1f}t / {tot_kg_ven/1000:,.1f}t",
      f"{(tot_kg_ven/tot_kg_mov*100 if tot_kg_mov>0 else 0):.1f}% vendido",
  )
  k5.metric(
      "€/Kg Vendido (Directo)", f"{eur_ven_dir:.4f} €", f"{kgh_ven_tot:.1f} Kg/H vendido"
  )
  k6.metric(
      "€/Kg Vendido (Total c/Ind)",
      f"{eur_ven_tot:.4f} €",
      f"+{eur_ven_ind:.4f} €/kg ind.",
      delta_color="inverse",
  )

  col_map = {
      "Línea Real": "lReal",
      "Año": "y",
      "Mes": "mISO",
      "Semana ISO": "wISO",
      "Día": "dISO",
  }
  g_col = col_map[group_mode]

  g_f = m_fic[m_fic["lReal"].isin(LINES_LIST)].groupby(g_col)["horas"].sum()
  g_m_real = m_dir.groupby(g_col)["kgReal"].sum()
  g_m_teo = m_dir.groupby(g_col)["kgTeo"].sum()
  g_v_real = v_dir.groupby(g_col)["kgReal"].sum()

  idx_keys = sorted(
      list(set(g_f.index) | set(g_m_real.index) | set(g_v_real.index))
  )
  rows_table = []
  for k in idx_keys:
    h_val = float(g_f.get(k, 0.0))
    mov_val = float(g_m_real.get(k, 0.0))
    teo_val = float(g_m_teo.get(k, 0.0))
    ven_val = float(g_v_real.get(k, 0.0))
    imp_val = h_val * rate_dir
    pct_v = (ven_val / mov_val * 100.0) if mov_val > 0 else 0.0
    eur_vol = (imp_val / mov_val) if mov_val > 0 else 0.0
    eur_ven = (imp_val / ven_val) if ven_val > 0 else 0.0
    kgh_v = (ven_val / h_val) if h_val > 0 else 0.0
    kgh_m = (mov_val / h_val) if h_val > 0 else 0.0
    give_val = mov_val - teo_val

    ref_line = (
        k
        if group_mode == "Línea Real"
        else (sel_line if sel_line != "TODAS" else None)
    )
    rows_table.append({
        group_mode: k,
        "Total Horas": round(h_val, 1),
        "Importe MO (€)": round(imp_val, 2),
        "Mov. Partes (Kg)": round(mov_val, 0),
        "Mov. Ventas (Kg)": round(ven_val, 0),
        "% Vendido / Movido": round(pct_v, 1),
        "€/Kg Volcado": round(eur_vol, 3),
        "€/Kg Vendido": round(eur_ven, 4),
        "Estado vs Objetivo": (
            status_badge_str(ref_line, eur_ven) if ref_line else "—"
        ),
        "Kg/H Vendido": round(kgh_v, 2),
        "Kg/H Movido": round(kgh_m, 2),
        "Sobrepeso (Kg)": round(give_val, 0),
    })

  df_summary = pd.DataFrame(rows_table)

  ch1, ch2 = st.columns(2)
  with ch1:
    fig_cost = go.Figure()
    fig_cost.add_trace(go.Bar(
        x=df_summary[group_mode],
        y=df_summary["€/Kg Volcado"],
        name="€/Kg Volcado (Partes)",
        marker_color="#f59e0b",
    ))
    fig_cost.add_trace(go.Bar(
        x=df_summary[group_mode],
        y=df_summary["€/Kg Vendido"],
        name="€/Kg Vendido (Facturado)",
        marker_color="#dc2626",
    ))
    if group_mode == "Línea Real":
      fig_cost.add_trace(go.Scatter(
          x=df_summary[group_mode],
          y=[targets.get(k, {}).get("eurVen", 0) for k in df_summary[group_mode]],
          name="Umbral Objetivo (€/Kg)",
          mode="lines+markers",
          line=dict(color="#059669", width=3, dash="dot"),
      ))
    fig_cost.update_layout(
        title=f"Coste Unitario por {group_mode} (€/Kg Volcado vs Vendido)",
        barmode="group",
        height=360,
        margin=dict(t=40, b=30, l=40, r=20),
    )
    st.plotly_chart(fig_cost, use_container_width=True)

  with ch2:
    fig_prod = go.Figure()
    fig_prod.add_trace(go.Bar(
        x=df_summary[group_mode],
        y=df_summary["Kg/H Movido"],
        name="Kg/H Movido (Almacén)",
        marker_color="#2563eb",
    ))
    fig_prod.add_trace(go.Bar(
        x=df_summary[group_mode],
        y=df_summary["Kg/H Vendido"],
        name="Kg/H Vendido (Ventas)",
        marker_color="#16a34a",
    ))
    if group_mode == "Línea Real":
      fig_prod.add_trace(go.Scatter(
          x=df_summary[group_mode],
          y=[targets.get(k, {}).get("kghVen", 0) for k in df_summary[group_mode]],
          name="Objetivo Kg/H Vendido",
          mode="lines+markers",
          line=dict(color="#1d4ed8", width=3, dash="dot"),
      ))
    fig_prod.update_layout(
        title=f"Productividad Horaria por {group_mode} (Kg/Hora)",
        barmode="group",
        height=360,
        margin=dict(t=40, b=30, l=40, r=20),
    )
    st.plotly_chart(fig_prod, use_container_width=True)

  st.markdown(f"#### 📋 Tabla Ejecutiva Consolidada por **{group_mode}**")
  st.dataframe(df_summary, use_container_width=True, hide_index=True)

  with st.expander(
      "➕ Desplegar Detalle Jerárquico Día a Día por Línea Real (Estilo Tabla"
      " Dinámica Excel)"
  ):
    sel_drill_line = st.selectbox(
        "Selecciona Línea para inspeccionar su serie diaria y mensual:",
        LINES_LIST,
    )
    sub_f_l = (
        m_fic[m_fic["lReal"] == sel_drill_line]
        .groupby(["mISO", "dISO"])["horas"]
        .sum()
    )
    sub_m_l = (
        m_mov[m_mov["lReal"] == sel_drill_line]
        .groupby(["mISO", "dISO"])["kgReal"]
        .sum()
    )
    sub_v_l = (
        m_ven[m_ven["lReal"] == sel_drill_line]
        .groupby(["mISO", "dISO"])["kgReal"]
        .sum()
    )
    drill_idx = sorted(
        list(set(sub_f_l.index) | set(sub_m_l.index) | set(sub_v_l.index))
    )
    drill_rows = []
    for m_k, d_k in drill_idx:
      hh = float(sub_f_l.get((m_k, d_k), 0.0))
      mm = float(sub_m_l.get((m_k, d_k), 0.0))
      vv = float(sub_v_l.get((m_k, d_k), 0.0))
      ii = hh * rate_dir
      drill_rows.append({
          "Línea Real": sel_drill_line,
          "Mes": m_k,
          "Fecha": d_k,
          "Horas": round(hh, 1),
          "Importe (€)": round(ii, 2),
          "Kg Movido": round(mm, 0),
          "Kg Vendido": round(vv, 0),
          "% Vendido/Movido": f"{(vv/mm*100 if mm>0 else 0):.0f}%",
          "€/Kg Volcado": round(ii / mm, 3) if mm > 0 else 0.0,
          "€/Kg Vendido": round(ii / vv, 4) if vv > 0 else 0.0,
          "Kg/H Vendido": round(vv / hh, 2) if hh > 0 else 0.0,
          "Kg/H Movido": round(mm / hh, 2) if hh > 0 else 0.0,
      })
    st.dataframe(pd.DataFrame(drill_rows), use_container_width=True, hide_index=True)

with tab_give:
  st.markdown(
      "#### ⚖️ Auditoría de Sobrepeso (*Giveaway*) y Errores de Tara por"
      " Confección y Cliente"
  )
  com_mov = m_mov[
      m_mov["lReal"].isin(LINES_LIST)
      & (m_mov["cliente"] != "")
      & (m_mov["cliente"] != "NATURAL TROPIC, S.L.")
  ].copy()

  if com_mov.empty:
    st.warning("No hay movimientos comerciales con cliente asignado en el filtro actual.")
  else:
    com_mov["giveaway"] = com_mov["kgReal"] - com_mov["kgTeo"]
    com_mov["formato_id"] = (
        com_mov["lReal"]
        + " | "
        + com_mov["conf"]
        + " ("
        + com_mov["emb"]
        + ")"
    )

    grp_conf = com_mov.groupby("formato_id", as_index=False).agg(
        Cajas=("cajas", "sum"),
        Kg_Teorico=("kgTeo", "sum"),
        Kg_Real=("kgReal", "sum"),
        Sobrepeso_Kg=("giveaway", "sum"),
    )
    grp_conf["Gramos_Extra_Caja"] = np.where(
        grp_conf["Cajas"] > 0,
        grp_conf["Sobrepeso_Kg"] * 1000.0 / grp_conf["Cajas"],
        0.0,
    )
    grp_conf["Desv_%"] = np.where(
        grp_conf["Kg_Teorico"] > 0,
        grp_conf["Sobrepeso_Kg"] / grp_conf["Kg_Teorico"] * 100.0,
        0.0,
    )
    grp_conf["Valor_Fruta_EUR"] = grp_conf["Sobrepeso_Kg"] * fruit_price
    grp_conf = grp_conf.sort_values("Sobrepeso_Kg", ascending=False)

    grp_cli = com_mov.groupby("cliente", as_index=False).agg(
        Cajas=("cajas", "sum"),
        Kg_Teorico=("kgTeo", "sum"),
        Kg_Real=("kgReal", "sum"),
        Sobrepeso_Kg=("giveaway", "sum"),
    )
    grp_cli["Gramos_Extra_Caja"] = np.where(
        grp_cli["Cajas"] > 0,
        grp_cli["Sobrepeso_Kg"] * 1000.0 / grp_cli["Cajas"],
        0.0,
    )
    grp_cli["Desv_%"] = np.where(
        grp_cli["Kg_Teorico"] > 0,
        grp_cli["Sobrepeso_Kg"] / grp_cli["Kg_Teorico"] * 100.0,
        0.0,
    )
    grp_cli["Valor_Fruta_EUR"] = grp_cli["Sobrepeso_Kg"] * fruit_price
    grp_cli = grp_cli.sort_values("Sobrepeso_Kg", ascending=False)

    g_c1, g_c2 = st.columns(2)
    with g_c1:
      top_c_plot = grp_conf[grp_conf["Sobrepeso_Kg"] > 0].head(10).iloc[::-1]
      fig_cf = go.Figure(go.Bar(
          x=top_c_plot["Sobrepeso_Kg"],
          y=top_c_plot["formato_id"],
          orientation="h",
          marker_color="#dc2626",
          text=[
              f"+{k:.0f} kg (+{g:.0f} g/caja)"
              for k, g in zip(
                  top_c_plot["Sobrepeso_Kg"], top_c_plot["Gramos_Extra_Caja"]
              )
          ],
          textposition="auto",
      ))
      fig_cf.update_layout(
          title="📦 Top 10 Confecciones con Mayor Sobrepeso",
          height=380,
          margin=dict(t=40, b=30, l=180, r=20),
      )
      st.plotly_chart(fig_cf, use_container_width=True)
      st.dataframe(grp_conf.round(1), use_container_width=True, hide_index=True)

    with g_c2:
      top_cl_plot = grp_cli[grp_cli["Sobrepeso_Kg"] > 0].head(10).iloc[::-1]
      fig_cl = go.Figure(go.Bar(
          x=top_cl_plot["Sobrepeso_Kg"],
          y=top_cl_plot["cliente"].str.slice(0, 26),
          orientation="h",
          marker_color="#d97706",
          text=[
              f"+{k:.0f} kg ({p:+.1f}%)"
              for k, p in zip(top_cl_plot["Sobrepeso_Kg"], top_cl_plot["Desv_%"])
          ],
          textposition="auto",
      ))
      fig_cl.update_layout(
          title="🏢 Top 10 Clientes que Reciben Más Sobrepeso",
          height=380,
          margin=dict(t=40, b=30, l=180, r=20),
      )
      st.plotly_chart(fig_cl, use_container_width=True)
      st.dataframe(grp_cli.round(1), use_container_width=True, hide_index=True)

with tab_targ:
  st.markdown(
      "#### 🎯 Matriz de Umbrales Objetivos por Línea Real (Histórico vs. Actual)"
  )
  if st.button("🔄 Autocalcular Objetivos con Media Histórica Total", type="primary"):
    for l in LINES_LIST:
      hh = float(df_fic[df_fic["lReal"] == l]["horas"].sum())
      mm = float(df_mov[df_mov["lReal"] == l]["kgReal"].sum())
      vv = float(df_ven[df_ven["lReal"] == l]["kgReal"].sum())
      if hh > 0 and mm > 0 and vv > 0:
        targets[l] = {
            "eurVen": round((hh * rate_dir) / vv, 4),
            "eurVol": round((hh * rate_dir) / mm, 4),
            "kghVen": round(vv / hh, 2),
            "kghMov": round(mm / hh, 2),
        }
    set_config("TARGETS", targets)
    st.success("✅ Umbrales actualizados con la media histórica global.")
    st.rerun()

  targ_rows = []
  for l in LINES_LIST:
    t = targets.get(l, DEFAULT_TARGETS[l])
    hh = float(m_fic[m_fic["lReal"] == l]["horas"].sum())
    mm = float(m_mov[m_mov["lReal"] == l]["kgReal"].sum())
    vv = float(m_ven[m_ven["lReal"] == l]["kgReal"].sum())
    act_eur_ven = (hh * rate_dir / vv) if vv > 0 else 0.0
    act_eur_vol = (hh * rate_dir / mm) if mm > 0 else 0.0
    act_kgh_ven = (vv / hh) if hh > 0 else 0.0
    act_kgh_mov = (mm / hh) if hh > 0 else 0.0

    targ_rows.append({
        "Línea Real": l,
        "Obj_€/Kg_Vendido": float(t["eurVen"]),
        "Actual_€/Kg_Vendido": round(act_eur_ven, 4),
        "Obj_€/Kg_Volcado": float(t["eurVol"]),
        "Actual_€/Kg_Volcado": round(act_eur_vol, 4),
        "Obj_Kg/H_Vendido": float(t["kghVen"]),
        "Actual_Kg/H_Vendido": round(act_kgh_ven, 2),
        "Obj_Kg/H_Movido": float(t["kghMov"]),
        "Actual_Kg/H_Movido": round(act_kgh_mov, 2),
        "Semáforo": status_badge_str(l, act_eur_ven),
    })

  df_targ_edit = st.data_editor(
      pd.DataFrame(targ_rows),
      disabled=[
          "Línea Real",
          "Actual_€/Kg_Vendido",
          "Actual_€/Kg_Volcado",
          "Actual_Kg/H_Vendido",
          "Actual_Kg/H_Movido",
          "Semáforo",
      ],
      use_container_width=True,
      hide_index=True,
  )

  if st.button("💾 Guardar Cambios Manuales en Objetivos"):
    for _, r in df_targ_edit.iterrows():
      l = r["Línea Real"]
      targets[l] = {
          "eurVen": float(r["Obj_€/Kg_Vendido"]),
          "eurVol": float(r["Obj_€/Kg_Volcado"]),
          "kghVen": float(r["Obj_Kg/H_Vendido"]),
          "kghMov": float(r["Obj_Kg/H_Movido"]),
      }
    set_config("TARGETS", targets)
    st.success("✅ Umbrales guardados.")
    st.rerun()

with tab_ai:
  st.markdown(
      "#### 🧠 Diagnóstico IA a Pie de Planta — Puntos Débiles y Cuellos de"
      " Botella"
  )
  ai_cards, sup_chart_data = [], []

  for l in LINES_LIST:
    sub_f = m_fic[m_fic["lReal"] == l]
    sub_m = m_mov[m_mov["lReal"] == l]
    sub_v = m_ven[m_ven["lReal"] == l]

    h_tot = float(sub_f["horas"].sum())
    if h_tot <= 0 and len(sub_m) == 0:
      continue

    h_env = float(sub_f[sub_f["operacion"] == "ENVASADO"]["horas"].sum())
    h_bano = float(sub_f[sub_f["operacion"] == "BAÑO"]["horas"].sum())
    h_sup = max(0.0, h_tot - h_env - h_bano)
    own_grps = OWN_GROUP_MAP.get(l, [])
    h_ext = float(
        sub_f[
            (sub_f["grupoTrab"] != "")
            & (~sub_f["grupoTrab"].isin(own_grps))
        ]["horas"].sum()
    )

    pct_env = (h_env / h_tot * 100.0) if h_tot > 0 else 0.0
    pct_sup = (h_sup / h_tot * 100.0) if h_tot > 0 else 0.0
    pct_ext = (h_ext / h_tot * 100.0) if h_tot > 0 else 0.0

    kg_m = float(sub_m["kgReal"].sum())
    kg_t = float(sub_m["kgTeo"].sum())
    kg_v = float(sub_v["kgReal"].sum())
    give = kg_m - kg_t
    eur_v = (h_tot * rate_dir / kg_v) if kg_v > 0 else 0.0
    t_obj = targets.get(l, DEFAULT_TARGETS[l])

    sup_chart_data.append({
        "Línea": l,
        "% Envasado Directo": pct_env,
        "% Soporte (Aux/Resp/Ord)": pct_sup,
        "% Personal Prestado": pct_ext,
    })

    if t_obj and eur_v > t_obj["eurVen"] * 1.10 and kg_v > 1000:
      desv_p = (eur_v - t_obj["eurVen"]) / t_obj["eurVen"] * 100.0
      ai_cards.append((
          "ai-card-crit",
          f"🚨 Desviación de Coste en {l}: {eur_v:.4f} €/kg vendido"
          f" (+{desv_p:.1f}% sobre objetivo {t_obj['eurVen']:.4f} €)",
          f"La línea ha invertido {h_tot:.1f} h para facturar {kg_v:,.0f} kg"
          f" ({(kg_v/h_tot if h_tot>0 else 0):.1f} Kg/h frente a"
          f" {t_obj['kghVen']:.1f} Kg/h objetivo).",
          (
              f"Acción a pie de máquina: Verificar si {l} sufre microparadas de"
              " alimentación o exceso de confección para stock interno"
              " (USOINT)."
          ),
      ))
    if pct_sup > 42.0 and h_tot > 15.0:
      ai_cards.append((
          "ai-card-high",
          (
              f"⚙️ Sobrecarga de Personal de Soporte en {l} ({pct_sup:.1f}% de"
              " las horas no son de Envasado)"
          ),
          (
              f"De {h_tot:.1f} h totales en {l}, {h_sup:.1f} h corresponden a"
              f" Auxiliar/Responsable/Ordenador y solo {h_env:.1f} h"
              f" ({pct_env:.1f}%) a Envasado directo."
          ),
          (
              "Acción a pie de máquina: Reequilibrar abastecimiento de"
              f" cartón/paletizado en {l} y reubicar al menos 1 auxiliar en mesa"
              " de envasado."
          ),
      ))
    if abs(give) > 200.0:
      ai_cards.append((
          "ai-card-crit" if give > 0 else "ai-card-med",
          (
              f"⚖️ Anomalía de Pesaje en {l}: {give:+.0f} kg"
              f" ({(give/kg_t*100 if kg_t>0 else 0):+.1f}% sobre teórico)"
          ),
          (
              "Se está entregando fruta gratis por exceso de peso en cierre de"
              " caja/barqueta."
              if give > 0
              else "Peso real de báscula inferior al teórico comercial (posible"
              " error en ficha Peso Confección o tara en Fruttec)."
          ),
          (
              "Acción a pie de máquina: Revisar en la Pestaña 2 las confecciones"
              f" de {l} y recalibrar células de carga/taras en el terminal"
              " Fruttec."
          ),
      ))
    if pct_ext > 45.0 and h_tot > 20.0:
      ai_cards.append((
          "ai-card-med",
          (
              f"🔄 Alta Rotación de Operarios en {l} ({pct_ext:.0f}% de las"
              " horas cubiertas con personal de otras líneas)"
          ),
          (
              f"{h_ext:.1f} h realizadas por trabajadores movidos desde otros"
              " grupos a mitad de turno."
          ),
          (
              f"Acción a pie de máquina: Fijar dotación titular de {l} a primera"
              " hora (07:50) para evitar pérdidas de cadencia en cambios de las"
              " 14:00."
          ),
      ))

  if not ai_cards:
    st.success("✅ No se detectan cuellos de botella críticos en la selección actual.")
  else:
    c_ai1, c_ai2 = st.columns(2)
    for i, (cls, tit, desc, act) in enumerate(ai_cards):
      (c_ai1 if i % 2 == 0 else c_ai2).markdown(
          f"<div class='{cls}'><b>{tit}</b><br><span"
          f" style='font-size:13px; color:#334155;'>{desc}</span><br><span"
          f" style='font-size:12.5px; font-weight:700; color:#0f172a;'>🛠️"
          f" {act}</span></div>",
          unsafe_allow_html=True,
      )

  if sup_chart_data:
    df_sc = pd.DataFrame(sup_chart_data)
    b1, b2 = st.columns(2)
    with b1:
      fig_s = go.Figure()
      fig_s.add_trace(go.Bar(
          x=df_sc["Línea"],
          y=df_sc["% Envasado Directo"],
          name="% Envasado Directo",
          marker_color="#10b981",
      ))
      fig_s.add_trace(go.Bar(
          x=df_sc["Línea"],
          y=df_sc["% Soporte (Aux/Resp/Ord)"],
          name="% Soporte Auxiliar",
          marker_color="#f59e0b",
      ))
      fig_s.update_layout(
          title="Equilibrio Operativo: % Envasado vs % Soporte",
          barmode="stack",
          height=340,
          margin=dict(t=40, b=30, l=40, r=20),
      )
      st.plotly_chart(fig_s, use_container_width=True)
    with b2:
      fig_m = go.Figure(go.Bar(
          x=df_sc["Línea"],
          y=df_sc["% Personal Prestado"],
          marker_color="#ef4444",
      ))
      fig_m.update_layout(
          title="Índice de Trasvase: % Horas con Personal de Otras Líneas",
          height=340,
          margin=dict(t=40, b=30, l=40, r=20),
      )
      st.plotly_chart(fig_m, use_container_width=True)

  st.markdown("---")
  st.markdown(
      "#### 📈 Evolución Histórica Comparativa (Por Día, Semana ISO, Mes o Año)"
  )
  gran_sel = st.radio(
      "Escala temporal de la gráfica:",
      ["Día (dISO)", "Semana ISO (wISO)", "Mes (mISO)", "Año (y)"],
      horizontal=True,
  )
  t_col = gran_sel.split("(")[1].replace(")", "")

  tf = (
      m_fic[m_fic["lReal"].isin(LINES_LIST)].groupby(t_col)["horas"].sum()
  )
  tm = m_dir.groupby(t_col)["kgReal"].sum()
  tv = v_dir.groupby(t_col)["kgReal"].sum()
  t_keys = sorted(list(set(tf.index) | set(tm.index) | set(tv.index)))

  fig_time = go.Figure()
  fig_time.add_trace(go.Scatter(
      x=t_keys,
      y=[
          (tf.get(k, 0) * rate_dir / tv.get(k, 0))
          if tv.get(k, 0) > 0
          else 0
          for k in t_keys
      ],
      name="€/Kg Vendido",
      mode="lines+markers",
      line=dict(color="#dc2626", width=3),
  ))
  fig_time.add_trace(go.Scatter(
      x=t_keys,
      y=[
          (tf.get(k, 0) * rate_dir / tm.get(k, 0))
          if tm.get(k, 0) > 0
          else 0
          for k in t_keys
      ],
      name="€/Kg Volcado",
      mode="lines+markers",
      line=dict(color="#f59e0b", width=3),
  ))
  fig_time.update_layout(
      title=f"Evolución de Costes Unitarios ({gran_sel})",
      height=360,
      margin=dict(t=40, b=30, l=40, r=20),
  )
  st.plotly_chart(fig_time, use_container_width=True)