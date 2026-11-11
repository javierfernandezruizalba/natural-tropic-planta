import os
import re
import gzip
import shutil
import sqlite3
import json
import unicodedata
from datetime import datetime
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# =============================================================================
# 1. CONFIGURACIÓN CORPORATIVA DE LA WEB APP
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
    .ai-card-ok   { background:#ecfdf5; border-left:5px solid #059669; padding:14px; border-radius:8px; margin-bottom:10px; }
    .exec-report  { background:#ffffff; border:1px solid #cbd5e1; border-top:4px solid #0f172a; padding:20px; border-radius:10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    </style>
""",
    unsafe_allow_html=True,
)

DB_FILE = "natural_tropic_planta.db"
DB_GZ_FILE = "natural_tropic_planta.db.gz"
ADMIN_PIN = st.secrets.get("ADMIN_PIN", "1234") if hasattr(st, "secrets") else "1234"

LINES_LIST = [
    "C1 Aguacate",
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

BOX_LINES_LIST = [
    "Mango",
    "Mesa Auxiliar Mango",
    "Multiscan",
    "Mesa Auxiliar",
]

DEFAULT_BOX_TARGETS = {
    "Mango":               {"cajas_dia": 180, "cajas_hora": 24.0},
    "Mesa Auxiliar Mango": {"cajas_dia": 110, "cajas_hora": 22.0},
    "Multiscan":           {"cajas_dia": 160, "cajas_hora": 22.0},
    "Mesa Auxiliar":       {"cajas_dia": 150, "cajas_hora": 20.0},
}

MONTH_NAMES = {
    1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
    7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic",
}

MONTH_NAMES_FULL = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
    7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}

DEFAULT_TARGETS = {
    "C1 Aguacate":  {"eurVen": 0.1374, "eurVol": 0.0750, "kghVen": 96.05,  "kghMov": 176.20},
    "C1 Mango":     {"eurVen": 0.1374, "eurVol": 0.0750, "kghVen": 96.05,  "kghMov": 176.20},
    "C2 Chirimoya": {"eurVen": 0.0650, "eurVol": 0.0550, "kghVen": 210.00, "kghMov": 240.00},
    "Flowpack":     {"eurVen": 0.1600, "eurVol": 0.1500, "kghVen": 82.00,  "kghMov": 88.00},
    "Girsac":       {"eurVen": 0.1150, "eurVol": 0.0800, "kghVen": 115.00, "kghMov": 165.00},
    "Mango":        {"eurVen": 0.1850, "eurVol": 0.1100, "kghVen": 72.00,  "kghMov": 120.00},
    "Multiscan":    {"eurVen": 0.4500, "eurVol": 0.1050, "kghVen": 30.00,  "kghMov": 125.00},
    "Pitaya":       {"eurVen": 0.1600, "eurVol": 0.1200, "kghVen": 82.00,  "kghMov": 110.00},
    "Repaso":       {"eurVen": 0.2100, "eurVol": 0.1500, "kghVen": 62.00,  "kghMov": 88.00},
    "Verde":        {"eurVen": 0.1550, "eurVol": 0.1400, "kghVen": 85.00,  "kghMov": 95.00},
    "Verde 2":      {"eurVen": 0.1950, "eurVol": 0.1500, "kghVen": 68.00,  "kghMov": 88.00},
}

OWN_GROUP_MAP = {
    "C1 Aguacate": ["CALIBRADOR1", "AGUACATE"],
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
# 2. BASE DE DATOS SQLITE, AUTO-DESCOMPRESIÓN Y PERSISTENCIA EN GITHUB
# =============================================================================
def init_db():
    if os.path.exists(DB_GZ_FILE):
        if not os.path.exists(DB_FILE) or os.path.getsize(DB_FILE) < 10000:
            try:
                with gzip.open(DB_GZ_FILE, "rb") as f_in:
                    with open(DB_FILE, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
            except Exception:
                pass

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
        CREATE TABLE IF NOT EXISTS conteo_cajas (
            dISO TEXT, horaDec REAL, usuario TEXT, puesto TEXT, grupo TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS config_store (
            k TEXT PRIMARY KEY, v TEXT
        )
    """)
    conn.commit()
    conn.close()


def create_compressed_backup():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "rb") as f_in:
            with gzip.open(DB_GZ_FILE, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)


def sync_db_to_github():
    create_compressed_backup()
    try:
        if hasattr(st, "secrets") and "GITHUB_TOKEN" in st.secrets and "GITHUB_REPO" in st.secrets:
            from github import Github
            g = Github(st.secrets["GITHUB_TOKEN"])
            repo = g.get_repo(st.secrets["GITHUB_REPO"])
            with open(DB_GZ_FILE, "rb") as f:
                content = f.read()
            try:
                contents = repo.get_contents(DB_GZ_FILE)
                repo.update_file(contents.path, "Auto-backup datos Natural Tropic (.db.gz)", content, contents.sha)
            except Exception:
                repo.create_file(DB_GZ_FILE, "Backup inicial datos Natural Tropic (.db.gz)", content)
            return True, "✅ Sincronizado automáticamente en GitHub (.db.gz) — Nunca se borrará."
    except Exception as e:
        return False, f"⚠️ Guardado local (GitHub Sync error: {e})"
    return False, "ℹ️ Guardado en sesión temporal (Descarga el .db.gz en el panel izquierdo y súbelo a GitHub, o configura GITHUB_TOKEN)"


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
    c.execute("INSERT OR REPLACE INTO config_store (k, v) VALUES (?, ?)", (key, json.dumps(val, ensure_ascii=False)))
    conn.commit()
    conn.close()


init_db()


# =============================================================================
# 3. MOTOR BLINDADO DE LECTURA (PRODUCCIÓN, FICHAJES Y CONTEO DE CAJAS)
# =============================================================================
def norm_str(s):
    if s is None or pd.isna(s):
        return ""
    s = str(s).strip().upper()
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def limpiar_nombre_envasadora(nombre):
    if pd.isna(nombre) or nombre is None:
        return ""
    s = str(nombre).upper().strip()
    s = re.sub(r"\s+", " ", s)
    s = s.replace(" ,", ",").replace(", ", ",").replace(",", ", ")
    return s.strip()


def find_col(df, candidates):
    norm_cols = {norm_str(c): c for c in df.columns}
    for cand in candidates:
        nc = norm_str(cand)
        if nc in norm_cols:
            return norm_cols[nc]
    for col in df.columns:
        c_up = str(col).upper()
        for cand in candidates:
            if cand.upper() == "LÍNEA PRODUCCIÓN" and "PRODUCCI" in c_up and ("L" in c_up):
                return col
            if cand.upper() == "LÍNEA" and c_up.startswith("L") and c_up.endswith("NEA") and "PROD" not in c_up:
                return col
            if cand.upper() == "OPERACIÓN" and "OPERACI" in c_up:
                return col
            if cand.upper() == "POSICIÓN" and "POSICI" in c_up:
                return col
            if cand.upper() == "CONFECCIÓN" and "CONFECCI" in c_up:
                return col
            if cand.upper() == "CATEGORIA" and "CATEGOR" in c_up:
                return col
    return None


def map_linea_real(raw_val, existing_real=None):
    for val in [existing_real, raw_val]:
        if val is None or pd.isna(val):
            continue
        lin = norm_str(val)
        if not lin or lin == "NAN":
            continue
        if "PISTACHO" in lin or lin in ["LIMPIADO", "TOSTADORA", "ENVASADORA", "PARTIDORA", "3UVISION"]:
            continue
        if lin in ["FLOWPACK", "FP"] or lin.startswith("FP") or "FLOWPACK" in lin:
            return "Flowpack"
        if ("C1" in lin or "CA1" in lin or "CALIBRADOR 1" in lin or "CALIBRADOR1" in lin) and ("AGU" in lin or "AVO" in lin):
            return "C1 Aguacate"
        if lin in ["C1 AGUACATE", "C1AGUACATE", "CALIBRADOR AGUACATE"]:
            return "C1 Aguacate"
        if lin in ["C1 MANGO", "C1MANGO", "CALIBRADOR 1", "CALIBRADOR1"] or lin.startswith("CA1") or lin.startswith("C1"):
            return "C1 Mango"
        if lin in ["C2 CHIRIMOYA", "C2CHIRIMOYA", "CHIRIMOYA"] or lin.startswith("CA2") or lin.startswith("C2"):
            return "C2 Chirimoya"
        if "GIRSAC" in lin or lin == "MALLAS":
            return "Girsac"
        if lin in ["MANGO", "MESA AUX B", "MESA AUXILIAR B"]:
            return "Mango"
        if lin in ["REPASO", "MESA AUX", "MESA AUXILIAR", "MANGO REPASO", "CONTROL PRODUCCION AUXILIAR"]:
            return "Repaso"
        if "MULTISCAN" in lin:
            return "Multiscan"
        if "PITAYA" in lin:
            return "Pitaya"
        if lin in ["VERDE 2", "VERDE2", "VERDE2 AGU"] or lin.startswith("VERDE2") or lin.startswith("VERDE 2"):
            return "Verde 2"
        if lin in ["VERDE", "VERDE 1", "VERDE1", "VERDE1 AGU"] or lin.startswith("VERDE1") or lin.startswith("VERDE 1"):
            return "Verde"
    return None


def clean_num_series(s):
    if s is None:
        return 0.0
    if isinstance(s, (int, float)):
        return float(s)
    if pd.api.types.is_numeric_dtype(s):
        return s.fillna(0.0).astype(float)
    s_str = s.astype(str).str.strip().str.replace("€", "", regex=False).str.replace(" ", "", regex=False)
    has_comma = s_str.str.contains(",", regex=False)
    has_dot = s_str.str.contains(".", regex=False)
    s_clean = np.where(
        has_comma & has_dot,
        s_str.str.replace(".", "", regex=False).str.replace(",", ".", regex=False),
        s_str.str.replace(",", ".", regex=False),
    )
    return pd.to_numeric(pd.Series(s_clean, index=s.index), errors="coerce").fillna(0.0).astype(float)


def parse_robust_dates(raw_series):
    if pd.api.types.is_datetime64_any_dtype(raw_series):
        return pd.to_datetime(raw_series, errors="coerce")

    def _parse_val(v):
        if pd.isna(v):
            return pd.NaT
        if isinstance(v, (pd.Timestamp, np.datetime64)):
            return pd.Timestamp(v)
        if isinstance(v, (int, float)) and 35000 < v < 60000:
            return pd.Timestamp("1899-12-30") + pd.Timedelta(days=int(v))
        s = str(v).strip().split(" ")[0]
        if not s or s.upper() == "NAN":
            return pd.NaT
        if len(s) >= 8 and s[:4].isdigit() and s[4] in ["-", "/"]:
            return pd.to_datetime(s, format="%Y-%m-%d" if "-" in s else "%Y/%m/%d", errors="coerce")
        return pd.to_datetime(s, dayfirst=True, errors="coerce")

    return raw_series.apply(_parse_val)


def parse_robust_datetime_with_time(raw_series):
    if pd.api.types.is_datetime64_any_dtype(raw_series):
        return pd.to_datetime(raw_series, errors="coerce")

    def _parse_dt(v):
        if pd.isna(v):
            return pd.NaT
        if isinstance(v, (pd.Timestamp, np.datetime64, datetime)):
            return pd.Timestamp(v)
        if isinstance(v, (int, float)) and 35000 < v < 65000:
            return pd.Timestamp("1899-12-30") + pd.Timedelta(days=float(v))
        s = str(v).strip()
        if not s or s.upper() == "NAN":
            return pd.NaT
        if len(s) >= 10 and s[:4].isdigit() and s[4] in ["-", "/"]:
            return pd.to_datetime(s, dayfirst=False, errors="coerce")
        return pd.to_datetime(s, dayfirst=True, errors="coerce")

    return raw_series.apply(_parse_dt)


def enrich_dates(df, date_col):
    dt = parse_robust_dates(df[date_col])
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
    if df is None or df.empty:
        return pd.DataFrame()
    df.columns = [str(c).strip() for c in df.columns]
    col_fecha = find_col(df, ["Fecha"])
    if not col_fecha:
        return pd.DataFrame()
    df = enrich_dates(df, col_fecha)
    if df.empty:
        return pd.DataFrame()

    col_lin = find_col(df, ["Línea producción", "Linea produccion", "Línea", "Linea"])
    col_real = find_col(df, ["Linea real", "Línea real"])
    df["lReal"] = [
        map_linea_real(
            df[col_lin].iloc[i] if col_lin else None,
            df[col_real].iloc[i] if col_real else None,
        )
        for i in range(len(df))
    ]
    col_cajas = find_col(df, ["Cajas"])
    col_teo = find_col(df, ["Neto teo.", "Neto teo", "Neto teorico"])
    col_real_kg = find_col(df, ["Neto real"])
    col_emb = find_col(df, ["Embalaje"])
    col_conf = find_col(df, ["Confección", "Confeccion"])
    col_pos = find_col(df, ["Posición", "Posicion"])
    col_cat = find_col(df, ["Categoria", "Categoría"])
    col_cli = find_col(df, ["Cliente"])

    df["cajas"] = clean_num_series(df[col_cajas]) if col_cajas else 0.0
    df["kgTeo"] = clean_num_series(df[col_teo]) if col_teo else 0.0
    df["kgReal"] = clean_num_series(df[col_real_kg]) if col_real_kg else 0.0
    df["emb"] = df[col_emb].fillna("").astype(str).str.strip().str.upper() if col_emb else ""
    df["conf"] = df[col_conf].fillna("").astype(str).str.strip().str.upper() if col_conf else ""
    df["conf"] = np.where(df["conf"] == "", df["emb"], df["conf"])
    pos = df[col_pos].fillna("").astype(str).str.upper() if col_pos else pd.Series([""] * len(df), index=df.index)
    cat = df[col_cat].fillna("").astype(str).str.upper() if col_cat else pd.Series([""] * len(df), index=df.index)
    df["isDestrio"] = ((cat == "DX") | pos.str.contains("DESTRIO|BASURA|ACEITE|PODRIDO|GUACAMOLE", regex=True)).astype(int)
    df["isInterno"] = ((df["emb"] == "USOINT") | pos.str.contains("REPASO|USO|SOBRANTE|DESCALIBRADO", regex=True)).astype(int)
    df["cliente"] = df[col_cli].fillna("").astype(str).str.strip() if col_cli else ""
    return df[["dISO", "y", "mISO", "wISO", "lReal", "conf", "emb", "cajas", "kgTeo", "kgReal", "isDestrio", "isInterno", "cliente"]]


def parse_ven_df(df):
    if df is None or df.empty:
        return pd.DataFrame()
    df.columns = [str(c).strip() for c in df.columns]
    col_fecha = find_col(df, ["Fecha"])
    if not col_fecha:
        return pd.DataFrame()
    df = enrich_dates(df, col_fecha)
    if df.empty:
        return pd.DataFrame()

    col_tmov = find_col(df, ["Tipo mov.", "Tipo mov"])
    if col_tmov:
        tmov_s = df[col_tmov].fillna("").astype(str).str.strip().str.upper()
        df = df[~tmov_s.isin(["D", "DEV", "DEVOLUCION"])].copy()

    col_lin = find_col(df, ["Línea producción", "Linea produccion", "Línea", "Linea"])
    col_real = find_col(df, ["Linea real", "Línea real"])
    df["lReal"] = [
        map_linea_real(
            df[col_lin].iloc[i] if col_lin else None,
            df[col_real].iloc[i] if col_real else None,
        )
        for i in range(len(df))
    ]
    col_cajas = find_col(df, ["Cajas"])
    col_teo = find_col(df, ["Neto teo.", "Neto teo", "Neto teorico"])
    col_real_kg = find_col(df, ["Neto real"])
    col_cli = find_col(df, ["Cliente"])

    df["cajas"] = clean_num_series(df[col_cajas]) if col_cajas else 0.0
    df["kgTeo"] = clean_num_series(df[col_teo]) if col_teo else 0.0
    df["kgReal"] = clean_num_series(df[col_real_kg]) if col_real_kg else 0.0
    df["cliente"] = df[col_cli].fillna("").astype(str).str.strip() if col_cli else ""
    return df[["dISO", "y", "mISO", "wISO", "lReal", "cajas", "kgTeo", "kgReal", "cliente"]]


def parse_fic_df(df, is_daily_txt=False):
    if df is None or df.empty:
        return pd.DataFrame()
    df.columns = [str(c).strip() for c in df.columns]
    col_f_asig = find_col(df, ["Fecha (Asignado)", "Fecha Asignado", "Fecha"])
    col_f_fich = find_col(df, ["Fichado a", "Fecha finalización"])

    if not col_f_asig and not col_f_fich:
        return pd.DataFrame()

    dt_asig = parse_robust_dates(df[col_f_asig]) if col_f_asig else pd.Series([pd.NaT] * len(df), index=df.index)
    if col_f_fich:
        dt_fich = parse_robust_dates(df[col_f_fich])
        dt_asig = dt_asig.fillna(dt_fich)
        if is_daily_txt and len(dt_fich.dropna()) > 0:
            main_day = dt_fich.dt.strftime("%Y-%m-%d").mode()
            if len(main_day) > 0:
                m_day_val = main_day.iloc[0]
                mask_fix = (dt_fich.dt.strftime("%Y-%m-%d") == m_day_val) & (dt_asig.dt.strftime("%Y-%m-%d") != m_day_val)
                dt_asig.loc[mask_fix] = dt_fich.loc[mask_fix]

    df = df.loc[dt_asig.notna()].copy()
    dt = dt_asig.loc[dt_asig.notna()]
    df["dISO"] = dt.dt.strftime("%Y-%m-%d")
    df["y"] = dt.dt.strftime("%Y")
    df["mISO"] = dt.dt.strftime("%Y-%m") + " (" + dt.dt.month.map(MONTH_NAMES) + ")"
    iso_cal = dt.dt.isocalendar()
    df["wISO"] = iso_cal["year"].astype(str) + "-W" + iso_cal["week"].apply(lambda x: f"{int(x):02d}")

    col_lin = find_col(df, ["Línea", "Linea", "Línea producción"])
    col_real = find_col(df, ["Linea real", "Línea real"])
    df["lReal"] = [
        map_linea_real(
            df[col_lin].iloc[i] if col_lin else None,
            df[col_real].iloc[i] if col_real else None,
        )
        for i in range(len(df))
    ]
    col_horas = find_col(df, ["Total horas", "Horas"])
    col_tcoste = find_col(df, ["Tipo coste"])
    col_op = find_col(df, ["Operación", "Operacion"])
    col_gtr = find_col(df, ["Grupo TRABAJADOR", "Grupo trabajador"])

    df["horas"] = clean_num_series(df[col_horas]) if col_horas else 0.0
    tc = clean_num_series(df[col_tcoste]).astype(int) if col_tcoste else pd.Series([0] * len(df), index=df.index)
    df["tipoCoste"] = np.where(tc > 0, tc, np.where(df["lReal"].notna(), 1, 2))
    df["operacion"] = df[col_op].fillna("").astype(str).str.strip().str.upper() if col_op else ""
    df["grupoTrab"] = df[col_gtr].fillna("").astype(str).str.strip().str.upper() if col_gtr else ""
    return df[["dISO", "y", "mISO", "wISO", "lReal", "horas", "tipoCoste", "operacion", "grupoTrab"]]


def parse_cajas_df(df):
    if df is None or df.empty:
        return pd.DataFrame()
    df.columns = [str(c).strip() for c in df.columns]

    col_fecha = find_col(df, ["Fecha", "Fecha/Hora", "Hora", "Fecha registro"])
    col_usu = find_col(df, ["Usuario", "Envasadora", "Operario", "Trabajador"])
    col_puesto = find_col(df, ["Puesto", "Lector", "Linea", "Línea"])
    col_grupo = find_col(df, ["Grupo", "Seccion", "Sección"])

    if not col_fecha and len(df.columns) >= 6:
        col_fecha = df.columns[0]
    if not col_usu and len(df.columns) >= 6:
        col_usu = df.columns[5]
    if not col_puesto and len(df.columns) >= 7:
        col_puesto = df.columns[6]
    if not col_grupo and len(df.columns) >= 8:
        col_grupo = df.columns[7]

    if not col_fecha or not col_usu:
        return pd.DataFrame()

    dt = parse_robust_datetime_with_time(df[col_fecha])
    df = df.loc[dt.notna()].copy()
    dt = dt.loc[dt.notna()]

    df["dISO"] = dt.dt.strftime("%Y-%m-%d")
    df["horaDec"] = dt.dt.hour + (dt.dt.minute / 60.0) + (dt.dt.second / 3600.0)
    df["usuario"] = df[col_usu].apply(limpiar_nombre_envasadora)
    df["puesto"] = df[col_puesto].fillna("").astype(str).str.strip().str.upper() if col_puesto else ""
    df["grupo"] = df[col_grupo].fillna("").astype(str).str.strip().str.upper() if col_grupo else ""

    df = df[df["usuario"] != ""].copy()
    return df[["dISO", "horaDec", "usuario", "puesto", "grupo"]]


def read_single_file(uploaded_file):
    name_low = uploaded_file.name.lower()
    if name_low.endswith((".xlsx", ".xls")):
        xls = pd.ExcelFile(uploaded_file)
        if "DATOS" in [s.upper() for s in xls.sheet_names]:
            for s_name in xls.sheet_names:
                if s_name.upper() == "DATOS":
                    return pd.read_excel(xls, sheet_name=s_name), False
        for s_name in xls.sheet_names:
            df_s = pd.read_excel(xls, sheet_name=s_name)
            if not df_s.empty and len(df_s.columns) >= 4:
                return df_s, False
    else:
        for enc in ["utf-8-sig", "utf-8", "cp1252", "latin1"]:
            try:
                uploaded_file.seek(0)
                df_s = pd.read_csv(uploaded_file, sep=";", encoding=enc, low_memory=False)
                if len(df_s.columns) >= 4:
                    return df_s, True
            except Exception:
                continue
    return pd.DataFrame(), False


def save_dataframe_to_db(df, table_name, is_daily_upload=False):
    if df is None or df.empty:
        return 0
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    if is_daily_upload:
        day_counts = df["dISO"].value_counts()
        main_days = day_counts[day_counts >= 15].index.tolist()
        if not main_days and len(day_counts) > 0:
            main_days = [day_counts.index[0]]
        df = df[df["dISO"].isin(main_days)].copy()
        placeholders = ",".join(["?"] * len(main_days))
        c.execute(f"DELETE FROM {table_name} WHERE dISO IN ({placeholders})", main_days)
    else:
        days = df["dISO"].dropna().unique().tolist()
        for i in range(0, len(days), 500):
            chunk = days[i:i+500]
            placeholders = ",".join(["?"] * len(chunk))
            c.execute(f"DELETE FROM {table_name} WHERE dISO IN ({placeholders})", chunk)

    conn.commit()
    df.to_sql(table_name, conn, if_exists="append", index=False)
    conn.close()
    return len(df)


def save_cajas_to_db(df):
    if df is None or df.empty:
        return 0
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    days = df["dISO"].dropna().unique().tolist()
    grupos = df["grupo"].dropna().unique().tolist()

    for d in days:
        for g in grupos:
            c.execute("DELETE FROM conteo_cajas WHERE dISO = ? AND grupo = ?", (d, g))
    conn.commit()
    df.to_sql("conteo_cajas", conn, if_exists="append", index=False)
    conn.close()
    return len(df)


def process_annual_workbook(uploaded_file):
    xls = pd.ExcelFile(uploaded_file)
    n_m, n_v, n_f = 0, 0, 0
    for s_name in xls.sheet_names:
        s_up = norm_str(s_name)
        if "RESUMEN" in s_up or "DINAMIC" in s_up or "TABLA" in s_up:
            continue
        df_s = pd.read_excel(xls, sheet_name=s_name)
        if df_s.empty or len(df_s.columns) < 4:
            continue

        if "FICHAJ" in s_up or find_col(df_s, ["ID trabajador", "Total horas"]):
            n_f += save_dataframe_to_db(parse_fic_df(df_s, is_daily_txt=False), "fichajes", is_daily_upload=False)
        elif "VENTA" in s_up:
            n_v += save_dataframe_to_db(parse_ven_df(df_s), "mov_ventas", is_daily_upload=False)
        elif "PARTE" in s_up or "PRODUCCION" in s_up or "ALMACEN" in s_up:
            n_m += save_dataframe_to_db(parse_mov_df(df_s), "mov_almacen", is_daily_upload=False)
        else:
            if find_col(df_s, ["Neto real"]):
                if "VENTA" in s_up:
                    n_v += save_dataframe_to_db(parse_ven_df(df_s), "mov_ventas", is_daily_upload=False)
                else:
                    n_m += save_dataframe_to_db(parse_mov_df(df_s), "mov_almacen", is_daily_upload=False)
    return n_m, n_v, n_f


@st.cache_data(ttl=2)
def load_all_from_db():
    conn = sqlite3.connect(DB_FILE)
    df_m = pd.read_sql_query("SELECT * FROM mov_almacen", conn)
    df_v = pd.read_sql_query("SELECT * FROM mov_ventas", conn)
    df_f = pd.read_sql_query("SELECT * FROM fichajes", conn)
    try:
        df_c = pd.read_sql_query("SELECT * FROM conteo_cajas", conn)
    except Exception:
        df_c = pd.DataFrame(columns=["dISO", "horaDec", "usuario", "puesto", "grupo"])
    conn.close()
    return df_m, df_v, df_f, df_c


# =============================================================================
# 4. MOTOR DE CONTEO DE CAJAS (MANGO, AUX MANGO, MULTISCAN, AUXILIAR)
# =============================================================================
def str_to_dec_hour(hora_str):
    if not hora_str or pd.isna(hora_str) or str(hora_str).strip() == "":
        return None
    try:
        partes = str(hora_str).strip().split(":")
        return int(partes[0]) + int(partes[1]) / 60.0 + (int(partes[2]) / 3600.0 if len(partes) > 2 else 0.0)
    except Exception:
        return None


def dec_to_str_hour(dec):
    if dec is None or pd.isna(dec):
        return "00:00:00"
    total_sec = int(round(float(dec) * 3600))
    h = total_sec // 3600
    m = (total_sec % 3600) // 60
    s = total_sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def mapear_linea_cajas_origen(puesto_str, grupo_str):
    p = norm_str(puesto_str)
    g = norm_str(grupo_str)
    comb = f"{p} {g}"
    if "MULTISCAN" in comb:
        return "Multiscan"
    if ("AUX" in comb or "REPASO" in comb) and "MANGO" not in comb:
        return "Mesa Auxiliar"
    if "MANGO" in comb:
        return "Mango"
    if "AUX" in comb:
        return "Mesa Auxiliar"
    return "Sin Asignar"


def calcular_reportes_cajas(df_cajas_raw, list_cfg, dict_inactivos):
    if df_cajas_raw is None or df_cajas_raw.empty:
        return pd.DataFrame()

    cfg_gen = {}
    cfg_exc = {}

    for item in list_cfg:
        usu = limpiar_nombre_envasadora(item.get("Envasadora", ""))
        if not usu:
            continue
        f_exc = str(item.get("Fecha_Excepcion", "")).strip()
        lin_asig = str(item.get("Linea", "")).strip()
        tipo_cont = str(item.get("Tipo_Contrato", "")).strip()
        h_in = str_to_dec_hour(item.get("H_Entrada", ""))
        h_out = str_to_dec_hour(item.get("H_Salida", ""))

        desc_raw = item.get("Descanso_Min", "")
        try:
            desc_min = float(desc_raw) if str(desc_raw).strip() not in ["", "None", "nan"] else -1.0
        except Exception:
            desc_min = -1.0

        if tipo_cont in ["Contrato 5h", "Contrato 4h"] and lin_asig in ["", "Mango"]:
            lin_asig = "Mesa Auxiliar Mango"

        info = {
            "linea": lin_asig,
            "contrato": tipo_cont,
            "tiene_manual": (h_in is not None and h_out is not None),
            "h_in": h_in,
            "h_out": h_out,
            "desc_min": desc_min,
        }

        if f_exc != "":
            try:
                f_iso = pd.to_datetime(f_exc, dayfirst=True).strftime("%Y-%m-%d")
                cfg_exc[f"{f_iso}|{usu}"] = info
            except Exception:
                pass
        else:
            cfg_gen[usu] = info

    df = df_cajas_raw.copy()
    dt_series = pd.to_datetime(df["dISO"], format="%Y-%m-%d", errors="coerce")
    df["weekday"] = dt_series.dt.weekday  # 0=Lunes ... 5=Sábado

    registros_filtrados = []
    for row in df.itertuples(index=False):
        d_iso = row.dISO
        usu = row.usuario
        h_dec = float(row.horaDec)
        w_day = int(row.weekday)

        clave_e = f"{d_iso}|{usu}"
        es_excepcion = False
        cfg = None

        if clave_e in cfg_exc:
            cfg = cfg_exc[clave_e]
            es_excepcion = True
        elif usu in cfg_gen:
            cfg = cfg_gen[usu]

        lin_orig = mapear_linea_cajas_origen(row.puesto, row.grupo)
        linea_final = cfg["linea"] if (cfg and cfg["linea"] != "") else lin_orig

        if d_iso in dict_inactivos.get(linea_final, []):
            continue

        aplicar_corte = False
        if cfg and cfg["tiene_manual"]:
            if es_excepcion or w_day < 5:
                aplicar_corte = True

        if aplicar_corte:
            if h_dec < cfg["h_in"] or h_dec > cfg["h_out"]:
                continue

        registros_filtrados.append({
            "dISO": d_iso,
            "Linea": linea_final,
            "Envasadora": usu,
            "horaDec": h_dec,
            "aplicoManual": aplicar_corte,
            "hInCfg": cfg["h_in"] if aplicar_corte else None,
            "hOutCfg": cfg["h_out"] if aplicar_corte else None,
            "descCfg": cfg["desc_min"] if cfg else -1.0,
            "contrato": cfg["contrato"] if cfg else "Abierto",
        })

    if not registros_filtrados:
        return pd.DataFrame()

    df_val = pd.DataFrame(registros_filtrados)

    salida_diaria = []
    for (d_iso, linea, usu), grp in df_val.groupby(["dISO", "Linea", "Envasadora"]):
        cajas_dia = len(grp)
        if cajas_dia < 10:  # Filtro mínimo: 10 cajas/día
            continue

        aplico_m = grp["aplicoManual"].iloc[0]
        desc_c = grp["descCfg"].iloc[0]
        tipo_c = grp["contrato"].iloc[0]

        if aplico_m:
            h_ini = float(grp["hInCfg"].iloc[0])
            h_fin = float(grp["hOutCfg"].iloc[0])
        else:
            h_ini = float(grp["horaDec"].min())
            h_fin = float(grp["horaDec"].max())

        tiempo_bruto = max(0.0, h_fin - h_ini)

        if desc_c >= 0:
            desc_horas = desc_c / 60.0
        elif tipo_c in ["Contrato 5h", "Contrato 4h"]:
            desc_horas = 0.0
        else:
            desc_horas = 0.0
            if h_ini < 9.5 and h_fin > 10.5 and tiempo_bruto > 5.2:
                desc_horas += 0.5
            if h_ini < 12.0 and h_fin > 15.75:
                desc_horas += 1.25
            elif h_ini >= 13.0 and tiempo_bruto >= 6.0:
                desc_horas += 0.5
            if h_ini < 18.0 and h_fin > 18.25:
                desc_horas += 0.25

        horas_reales = max(0.0, tiempo_bruto - desc_horas)
        ratio_ch = (cajas_dia / horas_reales) if horas_reales > 0 else 0.0

        dt_f = pd.to_datetime(d_iso)
        lunes = dt_f - pd.Timedelta(days=dt_f.weekday())
        domingo = lunes + pd.Timedelta(days=6)
        tag_sem = f"{lunes.strftime('%d/%m')} al {domingo.strftime('%d/%m/%Y')}"
        tag_mes = f"{MONTH_NAMES_FULL[dt_f.month]} {dt_f.year}"

        salida_diaria.append({
            "dISO": d_iso,
            "Fecha": dt_f.strftime("%d/%m/%Y"),
            "Semana": tag_sem,
            "Lunes_Sort": lunes.strftime("%Y-%m-%d"),
            "Mes": tag_mes,
            "Mes_Sort": f"{dt_f.year}-{dt_f.month:02d}",
            "Línea": linea,
            "Envasadora": usu,
            "Contrato": tipo_c,
            "Total Cajas": int(cajas_dia),
            "H. Entrada": dec_to_str_hour(h_ini),
            "H. Salida": dec_to_str_hour(h_fin),
            "Horas Reales": round(horas_reales, 2),
            "Cajas/Hora": round(ratio_ch, 2),
        })

    return pd.DataFrame(salida_diaria)


# =============================================================================
# 5. BARRA LATERAL: CONFIGURACIÓN, SUBIDA DIARIA Y PERSISTENCIA PERMANENTE
# =============================================================================
with st.sidebar:
    st.markdown("## 🥑 Natural Tropic S.L.")
    st.caption("Control de Operaciones, Costes y Conteo de Cajas")

    rates_cfg = get_config("RATES", {"dir": 13.20, "ind": 14.00, "tol_kg": 500.0})
    c_r1, c_r2 = st.columns(2)
    rate_dir = c_r1.number_input("€/H Directo", value=float(rates_cfg.get("dir", 13.20)), step=0.10)
    rate_ind = c_r2.number_input("€/H Indirecto", value=float(rates_cfg.get("ind", 14.00)), step=0.10)
    tol_kg = st.number_input(
        "Tolerancia Descuadre Parte (±Kg)",
        value=float(rates_cfg.get("tol_kg", 500.0)),
        step=50.0,
        help="Margen normal asumido en planta entre Kilos Reales y Teóricos (por defecto ±500 kg).",
    )

    if (
        rate_dir != rates_cfg.get("dir", 13.20)
        or rate_ind != rates_cfg.get("ind", 14.00)
        or tol_kg != rates_cfg.get("tol_kg", 500.0)
    ):
        set_config("RATES", {"dir": rate_dir, "ind": rate_ind, "tol_kg": tol_kg})

    st.markdown("---")
    with st.expander("🔐 Panel de Ingeniero (Subir Datos / Fijar Web)", expanded=False):
        pin_input = st.text_input("PIN de Ingeniero (1234)", type="password")
        if pin_input == ADMIN_PIN:
            has_gh_secrets = hasattr(st, "secrets") and "GITHUB_TOKEN" in st.secrets and "GITHUB_REPO" in st.secrets
            if has_gh_secrets:
                st.success("🟢 Auto-Guardado en GitHub: CONECTADO (Persistente 100%)")
            else:
                st.warning("🟡 Para que no se borre al entrar en stand-by: descarga el .db.gz en el apartado C y súbelo a GitHub, o configura GITHUB_TOKEN.")

            st.markdown("**A) Subir Archivos Diarios (.txt en crudo o .xlsx):**")
            up_mov = st.file_uploader("1. Partes Producción (.txt/.xlsx)", type=["txt", "csv", "xlsx"], accept_multiple_files=True, key="d_mov")
            up_ven = st.file_uploader("2. Mov. Ventas (.txt/.xlsx)", type=["txt", "csv", "xlsx"], accept_multiple_files=True, key="d_ven")
            up_fic = st.file_uploader("3. Fichajes Personal (.txt/.xlsx)", type=["txt", "csv", "xlsx"], accept_multiple_files=True, key="d_fic")
            up_caj = st.file_uploader("4. Conteo Cajas Frutec Control (.xlsx/.csv)", type=["xlsx", "xls", "csv", "txt"], accept_multiple_files=True, key="d_caj")

            st.markdown("**B) Subir Libros Excel Anuales (4 pestañas):**")
            up_annual = st.file_uploader(
                "Excel 2024, 2025 o 2026 (.xlsx)", type=["xlsx", "xls"], accept_multiple_files=True, key="ann"
            )

            if st.button("🚀 Procesar y Publicar Datos", type="primary", use_container_width=True):
                tot_m, tot_v, tot_f, tot_c = 0, 0, 0, 0
                with st.spinner("Procesando archivos y actualizando base de datos..."):
                    for f in up_annual or []:
                        nm, nv, nf = process_annual_workbook(f)
                        tot_m += nm; tot_v += nv; tot_f += nf
                    for f in up_mov or []:
                        df_raw, is_txt = read_single_file(f)
                        tot_m += save_dataframe_to_db(parse_mov_df(df_raw), "mov_almacen", is_daily_upload=is_txt)
                    for f in up_ven or []:
                        df_raw, is_txt = read_single_file(f)
                        tot_v += save_dataframe_to_db(parse_ven_df(df_raw), "mov_ventas", is_daily_upload=is_txt)
                    for f in up_fic or []:
                        df_raw, is_txt = read_single_file(f)
                        tot_f += save_dataframe_to_db(parse_fic_df(df_raw, is_daily_txt=is_txt), "fichajes", is_daily_upload=is_txt)
                    for f in up_caj or []:
                        df_raw, _ = read_single_file(f)
                        tot_c += save_cajas_to_db(parse_cajas_df(df_raw))
                ok_gh, msg_gh = sync_db_to_github()
                st.cache_data.clear()
                st.success(f"✅ Guardado: +{tot_m} Partes | +{tot_v} Ventas | +{tot_f} Fichajes | +{tot_c} Cajas Leídas\n\n{msg_gh}")
                st.rerun()

            st.markdown("---")
            st.markdown("**C) Fijar Datos Permanentemente (.db.gz):**")
            if os.path.exists(DB_FILE):
                create_compressed_backup()
                with open(DB_GZ_FILE, "rb") as fp_gz:
                    st.download_button(
                        label="💾 Descargar natural_tropic_planta.db.gz (Subir a GitHub)",
                        data=fp_gz,
                        file_name="natural_tropic_planta.db.gz",
                        mime="application/gzip",
                        use_container_width=True,
                        help="Sube este archivo a tu repositorio de GitHub para que la web jamás amanezca vacía.",
                    )

            up_restore = st.file_uploader("📂 Restaurar Copia (.db o .db.gz)", type=["db", "gz"])
            if up_restore is not None and st.button("⚡ Restaurar Histórico al Instante", use_container_width=True):
                if up_restore.name.endswith(".gz"):
                    with gzip.open(up_restore, "rb") as f_in:
                        with open(DB_FILE, "wb") as f_out:
                            shutil.copyfileobj(f_in, f_out)
                else:
                    with open(DB_FILE, "wb") as f_out:
                        f_out.write(up_restore.getbuffer())
                sync_db_to_github()
                st.cache_data.clear()
                st.success("✅ Histórico completo restaurado en 1 segundo.")
                st.rerun()

            st.markdown("---")
            if st.button("🗑️ Vaciar Base de Datos", use_container_width=True):
                conn = sqlite3.connect(DB_FILE)
                conn.execute("DELETE FROM mov_almacen")
                conn.execute("DELETE FROM mov_ventas")
                conn.execute("DELETE FROM fichajes")
                conn.execute("DELETE FROM conteo_cajas")
                conn.commit()
                conn.close()
                st.cache_data.clear()
                st.rerun()
        elif pin_input != "":
            st.error("PIN incorrecto")


# =============================================================================
# 6. CARGA DE DATOS Y FUNCIONES AUXILIARES DE CÁLCULO
# =============================================================================
df_mov, df_ven, df_fic, df_cajas_db = load_all_from_db()

all_days = sorted(
    list(
        set(df_mov["dISO"].dropna().tolist())
        | set(df_ven["dISO"].dropna().tolist())
        | set(df_fic["dISO"].dropna().tolist())
    )
)

st.markdown(
    f"### 🥑 NATURAL TROPIC S.L. — Inteligencia Operativa de Planta y Control de Costes  "
    f"<span style='font-size:13px; background:#065f46; color:#a7f3d0; padding:4px 10px; border-radius:99px;'>"
    f"Histórico Activo: {len(all_days)} días ({len(df_mov)+len(df_ven)+len(df_fic):,} reg. prod | {len(df_cajas_db):,} cajas leídas)</span>",
    unsafe_allow_html=True,
)

targets = get_config("TARGETS", DEFAULT_TARGETS)
for l_k, l_v in DEFAULT_TARGETS.items():
    if l_k not in targets:
        targets[l_k] = l_v


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


def compute_period_metrics(sub_m, sub_v, sub_f, line_filter="TODAS"):
    if line_filter != "TODAS":
        m_d = sub_m[sub_m["lReal"] == line_filter]
        v_d = sub_v[sub_v["lReal"] == line_filter]
        f_d = sub_f[sub_f["lReal"] == line_filter]
        h_ind = 0.0
    else:
        m_d = sub_m[sub_m["lReal"].isin(LINES_LIST)]
        v_d = sub_v[sub_v["lReal"].isin(LINES_LIST)]
        f_d = sub_f[sub_f["lReal"].isin(LINES_LIST)]
        h_ind = float(sub_f[~sub_f["lReal"].isin(LINES_LIST)]["horas"].sum())

    h_dir = float(f_d["horas"].sum())
    h_env = float(f_d[f_d["operacion"] == "ENVASADO"]["horas"].sum())
    h_bano = float(f_d[f_d["operacion"] == "BAÑO"]["horas"].sum())
    h_sup = max(0.0, h_dir - h_env - h_bano)

    kg_mov = float(m_d["kgReal"].sum())
    kg_teo = float(m_d["kgTeo"].sum())
    kg_ven = float(v_d["kgReal"].sum())
    cajas_mov = float(m_d["cajas"].sum())

    imp_dir = h_dir * rate_dir
    imp_ind = h_ind * rate_ind
    eur_vol = (imp_dir / kg_mov) if kg_mov > 0 else 0.0
    eur_ven = (imp_dir / kg_ven) if kg_ven > 0 else 0.0
    kgh_mov = (kg_mov / h_dir) if h_dir > 0 else 0.0
    kgh_ven = (kg_ven / h_dir) if h_dir > 0 else 0.0
    pct_conv = (kg_ven / kg_mov * 100.0) if kg_mov > 0 else 0.0
    pct_sup = (h_sup / h_dir * 100.0) if h_dir > 0 else 0.0
    descuadre_kg = kg_mov - kg_teo

    return {
        "h_dir": h_dir, "h_ind": h_ind, "h_env": h_env, "h_sup": h_sup,
        "pct_sup": pct_sup, "imp_dir": imp_dir, "imp_ind": imp_ind,
        "kg_mov": kg_mov, "kg_teo": kg_teo, "kg_ven": kg_ven, "cajas": cajas_mov,
        "eur_vol": eur_vol, "eur_ven": eur_ven,
        "kgh_mov": kgh_mov, "kgh_ven": kgh_ven,
        "pct_conv": pct_conv, "descuadre_kg": descuadre_kg,
    }


# =============================================================================
# 7. NAVEGACIÓN PRINCIPAL EN 6 PESTAÑAS
# =============================================================================
tab_dash, tab_comp, tab_ai, tab_targ, tab_quad, tab_boxes = st.tabs([
    "📊 1. Cuadro de Mando General",
    "⚔️ 2. Comparador de Fechas + Análisis IA",
    "🧠 3. Cuellos de Botella en Planta",
    "🎯 4. Umbrales Objetivos",
    f"⚖️ 5. Cuadre de Kilos (±{int(tol_kg)} kg)",
    "📦 6. Conteo de Cajas y Envasadoras",
])

# -----------------------------------------------------------------------------
# PESTAÑA 1: CUADRO DE MANDO GENERAL
# -----------------------------------------------------------------------------
with tab_dash:
    if len(all_days) == 0:
        st.info("👈 Sube tus datos de producción desde el Panel de Ingeniero en la barra lateral.")
    else:
        st.markdown("##### 🔍 Filtros de Consulta Rápida")
        f_c1, f_c2, f_c3, f_c4, f_c5, f_c6 = st.columns(6)

        all_years = sorted(list(set(df_mov["y"].dropna()) | set(df_ven["y"].dropna()) | set(df_fic["y"].dropna())))
        sel_year = f_c1.selectbox("📅 Año", ["TODOS"] + all_years)

        m_mov, m_ven, m_fic = df_mov.copy(), df_ven.copy(), df_fic.copy()
        if sel_year != "TODOS":
            m_mov, m_ven, m_fic = m_mov[m_mov["y"] == sel_year], m_ven[m_ven["y"] == sel_year], m_fic[m_fic["y"] == sel_year]

        all_months = sorted(list(set(m_mov["mISO"].dropna()) | set(m_ven["mISO"].dropna()) | set(m_fic["mISO"].dropna())))
        sel_month = f_c2.selectbox("🗓️ Mes", ["TODOS"] + all_months)
        if sel_month != "TODOS":
            m_mov, m_ven, m_fic = m_mov[m_mov["mISO"] == sel_month], m_ven[m_ven["mISO"] == sel_month], m_fic[m_fic["mISO"] == sel_month]

        all_weeks = sorted(list(set(m_mov["wISO"].dropna()) | set(m_ven["wISO"].dropna()) | set(m_fic["wISO"].dropna())))
        sel_week = f_c3.selectbox("📆 Semana ISO", ["TODAS"] + all_weeks)
        if sel_week != "TODAS":
            m_mov, m_ven, m_fic = m_mov[m_mov["wISO"] == sel_week], m_ven[m_ven["wISO"] == sel_week], m_fic[m_fic["wISO"] == sel_week]

        avail_days = sorted(list(set(m_mov["dISO"].dropna()) | set(m_ven["dISO"].dropna()) | set(m_fic["dISO"].dropna())))
        sel_day = f_c4.selectbox("📍 Día Exacto", ["TODOS"] + avail_days)
        if sel_day != "TODOS":
            m_mov, m_ven, m_fic = m_mov[m_mov["dISO"] == sel_day], m_ven[m_ven["dISO"] == sel_day], m_fic[m_fic["dISO"] == sel_day]

        sel_line = f_c5.selectbox("🏭 Línea Real", ["TODAS"] + LINES_LIST)
        if sel_line != "TODAS":
            m_mov, m_ven, m_fic = m_mov[m_mov["lReal"] == sel_line], m_ven[m_ven["lReal"] == sel_line], m_fic[m_fic["lReal"] == sel_line]

        group_mode = f_c6.selectbox("📊 Agrupar Tabla Por", ["Línea Real", "Año", "Mes", "Semana ISO", "Día"])

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
        kgh_mov_tot = tot_kg_mov / tot_h_dir if tot_h_dir > 0 else 0.0

        k1, k2, k3, k4, k5, k6 = st.columns(6)
        k1.metric("Coste MO Directa", f"{imp_dir:,.0f} €", f"{tot_h_dir:,.1f} h ({(tot_h_dir/tot_h_all*100 if tot_h_all>0 else 0):.0f}%)")
        k2.metric("Coste MO Indirecta", f"{imp_ind:,.0f} €", f"{tot_h_ind:,.1f} h ({(tot_h_ind/tot_h_all*100 if tot_h_all>0 else 0):.0f}%)")
        k3.metric("Coste Total Personal", f"{imp_tot:,.0f} €", f"{tot_h_all:,.1f} h totales")
        k4.metric("Movido vs Vendido", f"{tot_kg_mov/1000:,.1f}t / {tot_kg_ven/1000:,.1f}t", f"{(tot_kg_ven/tot_kg_mov*100 if tot_kg_mov>0 else 0):.1f}% vendido")
        k5.metric("€/Kg Vendido (Directo)", f"{eur_ven_dir:.4f} €", f"{kgh_mov_tot:.1f} Kg/H movido")
        k6.metric("€/Kg Vendido (Total c/Ind)", f"{eur_ven_tot:.4f} €", f"+{eur_ven_ind:.4f} €/kg ind.", delta_color="inverse")

        col_map = {"Línea Real": "lReal", "Año": "y", "Mes": "mISO", "Semana ISO": "wISO", "Día": "dISO"}
        g_col = col_map[group_mode]

        g_f = m_fic[m_fic["lReal"].isin(LINES_LIST)].groupby(g_col)["horas"].sum()
        g_m_real = m_dir.groupby(g_col)["kgReal"].sum()
        g_m_teo = m_dir.groupby(g_col)["kgTeo"].sum()
        g_v_real = v_dir.groupby(g_col)["kgReal"].sum()

        idx_keys = LINES_LIST if (group_mode == "Línea Real" and sel_line == "TODAS") else sorted(list(set(g_f.index) | set(g_m_real.index) | set(g_v_real.index)))
        rows_table = []
        for k in idx_keys:
            h_val = float(g_f.get(k, 0.0))
            mov_val = float(g_m_real.get(k, 0.0))
            teo_val = float(g_m_teo.get(k, 0.0))
            ven_val = float(g_v_real.get(k, 0.0))
            if h_val == 0 and mov_val == 0 and ven_val == 0:
                continue
            imp_val = h_val * rate_dir
            pct_v = (ven_val / mov_val * 100.0) if mov_val > 0 else 0.0
            eur_vol = (imp_val / mov_val) if mov_val > 0 else 0.0
            eur_ven = (imp_val / ven_val) if ven_val > 0 else 0.0
            kgh_v = (ven_val / h_val) if h_val > 0 else 0.0
            kgh_m = (mov_val / h_val) if h_val > 0 else 0.0
            descuadre = mov_val - teo_val

            ref_line = k if group_mode == "Línea Real" else (sel_line if sel_line != "TODAS" else None)
            rows_table.append({
                group_mode: k,
                "Total Horas": round(h_val, 1),
                "Importe MO (€)": round(imp_val, 2),
                "Mov. Partes (Kg)": round(mov_val, 0),
                "Mov. Ventas (Kg)": round(ven_val, 0),
                "% Vendido / Movido": round(pct_v, 1),
                "€/Kg Volcado": round(eur_vol, 3),
                "€/Kg Vendido": round(eur_ven, 4),
                "Estado vs Objetivo": status_badge_str(ref_line, eur_ven) if ref_line else "—",
                "Kg/H Vendido": round(kgh_v, 2),
                "Kg/H Movido": round(kgh_m, 2),
                "Descuadre Parte (Kg)": round(descuadre, 0),
            })

        df_summary = pd.DataFrame(rows_table)

        if not df_summary.empty:
            ch1, ch2 = st.columns(2)
            with ch1:
                fig_cost = go.Figure()
                fig_cost.add_trace(go.Bar(x=df_summary[group_mode], y=df_summary["€/Kg Volcado"], name="€/Kg Volcado (Partes)", marker_color="#f59e0b"))
                fig_cost.add_trace(go.Bar(x=df_summary[group_mode], y=df_summary["€/Kg Vendido"], name="€/Kg Vendido (Facturado)", marker_color="#dc2626"))
                if group_mode == "Línea Real":
                    fig_cost.add_trace(go.Scatter(
                        x=df_summary[group_mode],
                        y=[targets.get(k, {}).get("eurVen", 0) for k in df_summary[group_mode]],
                        name="Umbral Objetivo (€/Kg)", mode="lines+markers", line=dict(color="#059669", width=3, dash="dot"),
                    ))
                fig_cost.update_layout(title=f"Coste Unitario por {group_mode} (€/Kg Volcado vs Vendido)", barmode="group", height=360, margin=dict(t=40, b=30, l=40, r=20))
                st.plotly_chart(fig_cost, use_container_width=True)

            with ch2:
                fig_prod = go.Figure()
                fig_prod.add_trace(go.Bar(x=df_summary[group_mode], y=df_summary["Kg/H Movido"], name="Kg/H Movido (Partes Producción)", marker_color="#2563eb"))
                if group_mode == "Línea Real":
                    fig_prod.add_trace(go.Scatter(
                        x=df_summary[group_mode],
                        y=[targets.get(k, {}).get("kghMov", 0) for k in df_summary[group_mode]],
                        name="Objetivo Kg/H Movido", mode="lines+markers", line=dict(color="#f59e0b", width=3, dash="dot"),
                    ))
                fig_prod.update_layout(title=f"Productividad de Línea en Planta por {group_mode} (Kg/H Movido)", barmode="group", height=360, margin=dict(t=40, b=30, l=40, r=20))
                st.plotly_chart(fig_prod, use_container_width=True)

            st.markdown(f"#### 📋 Tabla Ejecutiva Consolidada por **{group_mode}**")
            st.dataframe(df_summary, use_container_width=True, hide_index=True)


# =============================================================================
# PESTAÑA 2: COMPARADOR DE FECHAS
# =============================================================================
with tab_comp:
    if len(all_days) == 0:
        st.info("👈 Sube tus datos de producción desde el Panel de Ingeniero en la barra lateral.")
    else:
        st.markdown("#### ⚔️ Comparador Cara a Cara de Fechas y Líneas con Análisis IA")
        c_cfg1, c_cfg2 = st.columns([1, 1])
        comp_scope = c_cfg1.selectbox(
            "🏭 Ámbito del Análisis Comparativo:",
            ["TODA LA EMPRESA (Global Planta)"] + LINES_LIST,
            key="comp_scope",
        )
        comp_type = c_cfg2.selectbox(
            "📅 Tipo de Periodo a Comparar:",
            ["Por Mes (ej. Sep vs Oct)", "Por Semana ISO", "Por Año (2024 vs 2025 vs 2026)", "Por Día Exacto", "Por Rango Libre de Fechas"],
            key="comp_type",
        )

        line_arg = "TODAS" if comp_scope.startswith("TODA") else comp_scope

        p_col1, p_col2 = st.columns(2)
        if comp_type == "Por Año (2024 vs 2025 vs 2026)":
            opts = sorted(list(set(df_mov["y"].dropna()) | set(df_ven["y"].dropna()) | set(df_fic["y"].dropna())))
            sel_a = p_col1.selectbox("🅰️ Periodo Base (A):", opts, index=0)
            sel_b = p_col2.selectbox("🅱️ Periodo a Comparar (B):", opts, index=min(1, len(opts)-1))
            mov_a, ven_a, fic_a = df_mov[df_mov["y"] == sel_a], df_ven[df_ven["y"] == sel_a], df_fic[df_fic["y"] == sel_a]
            mov_b, ven_b, fic_b = df_mov[df_mov["y"] == sel_b], df_ven[df_ven["y"] == sel_b], df_fic[df_fic["y"] == sel_b]
            label_a, label_b = f"Año {sel_a}", f"Año {sel_b}"

        elif comp_type == "Por Mes (ej. Sep vs Oct)":
            opts = sorted(list(set(df_mov["mISO"].dropna()) | set(df_ven["mISO"].dropna()) | set(df_fic["mISO"].dropna())))
            sel_a = p_col1.selectbox("🅰️ Mes Base (A):", opts, index=max(0, len(opts)-2))
            sel_b = p_col2.selectbox("🅱️ Mes a Comparar (B):", opts, index=len(opts)-1)
            mov_a, ven_a, fic_a = df_mov[df_mov["mISO"] == sel_a], df_ven[df_ven["mISO"] == sel_a], df_fic[df_fic["mISO"] == sel_a]
            mov_b, ven_b, fic_b = df_mov[df_mov["mISO"] == sel_b], df_ven[df_ven["mISO"] == sel_b], df_fic[df_fic["mISO"] == sel_b]
            label_a, label_b = sel_a, sel_b

        elif comp_type == "Por Semana ISO":
            opts = sorted(list(set(df_mov["wISO"].dropna()) | set(df_ven["wISO"].dropna()) | set(df_fic["wISO"].dropna())))
            sel_a = p_col1.selectbox("🅰️ Semana Base (A):", opts, index=max(0, len(opts)-2))
            sel_b = p_col2.selectbox("🅱️ Semana a Comparar (B):", opts, index=len(opts)-1)
            mov_a, ven_a, fic_a = df_mov[df_mov["wISO"] == sel_a], df_ven[df_ven["wISO"] == sel_a], df_fic[df_fic["wISO"] == sel_a]
            mov_b, ven_b, fic_b = df_mov[df_mov["wISO"] == sel_b], df_ven[df_ven["wISO"] == sel_b], df_fic[df_fic["wISO"] == sel_b]
            label_a, label_b = f"Sem {sel_a}", f"Sem {sel_b}"

        elif comp_type == "Por Día Exacto":
            opts = all_days
            sel_a = p_col1.selectbox("🅰️ Día Base (A):", opts, index=max(0, len(opts)-2))
            sel_b = p_col2.selectbox("🅱️ Día a Comparar (B):", opts, index=len(opts)-1)
            mov_a, ven_a, fic_a = df_mov[df_mov["dISO"] == sel_a], df_ven[df_ven["dISO"] == sel_a], df_fic[df_fic["dISO"] == sel_a]
            mov_b, ven_b, fic_b = df_mov[df_mov["dISO"] == sel_b], df_ven[df_ven["dISO"] == sel_b], df_fic[df_fic["dISO"] == sel_b]
            label_a, label_b = sel_a, sel_b

        else:
            min_dt = pd.to_datetime(all_days[0]).date()
            max_dt = pd.to_datetime(all_days[-1]).date()
            rng_a = p_col1.date_input("🅰️ Rango de Fechas A (Inicio - Fin):", value=(min_dt, max_dt), min_value=min_dt, max_value=max_dt, key="rng_a")
            rng_b = p_col2.date_input("🅱️ Rango de Fechas B (Inicio - Fin):", value=(min_dt, max_dt), min_value=min_dt, max_value=max_dt, key="rng_b")
            d1_a, d2_a = (str(rng_a[0]), str(rng_a[1])) if len(rng_a) == 2 else (str(rng_a[0]), str(rng_a[0]))
            d1_b, d2_b = (str(rng_b[0]), str(rng_b[1])) if len(rng_b) == 2 else (str(rng_b[0]), str(rng_b[0]))
            mov_a = df_mov[(df_mov["dISO"] >= d1_a) & (df_mov["dISO"] <= d2_a)]
            ven_a = df_ven[(df_ven["dISO"] >= d1_a) & (df_ven["dISO"] <= d2_a)]
            fic_a = df_fic[(df_fic["dISO"] >= d1_a) & (df_fic["dISO"] <= d2_a)]
            mov_b = df_mov[(df_mov["dISO"] >= d1_b) & (df_mov["dISO"] <= d2_b)]
            ven_b = df_ven[(df_ven["dISO"] >= d1_b) & (df_ven["dISO"] <= d2_b)]
            fic_b = df_fic[(df_fic["dISO"] >= d1_b) & (df_fic["dISO"] <= d2_b)]
            label_a, label_b = f"{d1_a} a {d2_a}", f"{d1_b} a {d2_b}"

        met_a = compute_period_metrics(mov_a, ven_a, fic_a, line_arg)
        met_b = compute_period_metrics(mov_b, ven_b, fic_b, line_arg)

        st.markdown(f"##### 📊 Resultado Comparativo: **{label_b}** frente a **{label_a}** ({comp_scope})")
        mc1, mc2, mc3, mc4, mc5 = st.columns(5)

        diff_eur_ven = met_b["eur_ven"] - met_a["eur_ven"]
        pct_eur_ven = (diff_eur_ven / met_a["eur_ven"] * 100.0) if met_a["eur_ven"] > 0 else 0.0
        mc1.metric("€/Kg Vendido (B vs A)", f"{met_b['eur_ven']:.4f} €", f"{diff_eur_ven:+.4f} € ({pct_eur_ven:+.1f}%)", delta_color="inverse")

        diff_eur_vol = met_b["eur_vol"] - met_a["eur_vol"]
        pct_eur_vol = (diff_eur_vol / met_a["eur_vol"] * 100.0) if met_a["eur_vol"] > 0 else 0.0
        mc2.metric("€/Kg Volcado (B vs A)", f"{met_b['eur_vol']:.4f} €", f"{diff_eur_vol:+.4f} € ({pct_eur_vol:+.1f}%)", delta_color="inverse")

        diff_kgh_mov = met_b["kgh_mov"] - met_a["kgh_mov"]
        pct_kgh_mov = (diff_kgh_mov / met_a["kgh_mov"] * 100.0) if met_a["kgh_mov"] > 0 else 0.0
        mc3.metric("Productividad Línea (Kg/H Movido)", f"{met_b['kgh_mov']:.1f} Kg/h", f"{diff_kgh_mov:+.1f} Kg/h ({pct_kgh_mov:+.1f}%)")

        diff_kgh_ven = met_b["kgh_ven"] - met_a["kgh_ven"]
        pct_kgh_ven = (diff_kgh_ven / met_a["kgh_ven"] * 100.0) if met_a["kgh_ven"] > 0 else 0.0
        mc4.metric("Kg/H Vendido (Facturado)", f"{met_b['kgh_ven']:.1f} Kg/h", f"{diff_kgh_ven:+.1f} Kg/h ({pct_kgh_ven:+.1f}%)")

        diff_conv = met_b["pct_conv"] - met_a["pct_conv"]
        mc5.metric("% Vendido / Movido", f"{met_b['pct_conv']:.1f}%", f"{diff_conv:+.1f} pts (vs {met_a['pct_conv']:.1f}%)")

        cg1, cg2 = st.columns(2)
        if line_arg == "TODAS":
            l_names, a_costs, b_costs, a_kgh_mov, b_kgh_mov = [], [], [], [], []
            for l in LINES_LIST:
                ma = compute_period_metrics(mov_a, ven_a, fic_a, l)
                mb = compute_period_metrics(mov_b, ven_b, fic_b, l)
                if ma["h_dir"] > 0 or mb["h_dir"] > 0 or ma["kg_mov"] > 0 or mb["kg_mov"] > 0:
                    l_names.append(l)
                    a_costs.append(ma["eur_ven"])
                    b_costs.append(mb["eur_ven"])
                    a_kgh_mov.append(ma["kgh_mov"])
                    b_kgh_mov.append(mb["kgh_mov"])

            with cg1:
                fig_ca = go.Figure()
                fig_ca.add_trace(go.Bar(x=l_names, y=a_costs, name=f"🅰️ {label_a}", marker_color="#94a3b8"))
                fig_ca.add_trace(go.Bar(x=l_names, y=b_costs, name=f"🅱️ {label_b}", marker_color="#dc2626"))
                fig_ca.update_layout(title="1. Comparativa de Costes Unitarios (€/Kg Vendido)", barmode="group", height=360, margin=dict(t=40, b=30, l=40, r=20))
                st.plotly_chart(fig_ca, use_container_width=True)

            with cg2:
                fig_cb = go.Figure()
                fig_cb.add_trace(go.Bar(x=l_names, y=a_kgh_mov, name=f"🅰️ {label_a}", marker_color="#94a3b8"))
                fig_cb.add_trace(go.Bar(x=l_names, y=b_kgh_mov, name=f"🅱️ {label_b}", marker_color="#2563eb"))
                fig_cb.update_layout(title="2. Productividad de Línea en Partes de Producción (Kg/H Movido)", barmode="group", height=360, margin=dict(t=40, b=30, l=40, r=20))
                st.plotly_chart(fig_cb, use_container_width=True)
        else:
            with cg1:
                fig_l1 = go.Figure()
                fig_l1.add_trace(go.Bar(x=["€/Kg Volcado", "€/Kg Vendido"], y=[met_a["eur_vol"], met_a["eur_ven"]], name=f"🅰️ {label_a}", marker_color="#64748b"))
                fig_l1.add_trace(go.Bar(x=["€/Kg Volcado", "€/Kg Vendido"], y=[met_b["eur_vol"], met_b["eur_ven"]], name=f"🅱️ {label_b}", marker_color="#dc2626"))
                fig_l1.update_layout(title=f"1. Costes Unitarios en {line_arg} ({label_a} vs {label_b})", barmode="group", height=350)
                st.plotly_chart(fig_l1, use_container_width=True)
            with cg2:
                fig_l2 = go.Figure()
                fig_l2.add_trace(go.Bar(
                    x=[f"🅰️ {label_a}", f"🅱️ {label_b}"],
                    y=[met_a["kgh_mov"], met_b["kgh_mov"]],
                    marker_color=["#64748b", "#2563eb"],
                    text=[f"{met_a['kgh_mov']:.1f} Kg/h", f"{met_b['kgh_mov']:.1f} Kg/h"],
                    textposition="auto",
                ))
                fig_l2.update_layout(title=f"2. Productividad de Línea en Partes: Kg/H Movido en {line_arg}", height=350)
                st.plotly_chart(fig_l2, use_container_width=True)


# =============================================================================
# PESTAÑA 3: CUELLOS DE BOTELLA A PIE DE PLANTA
# =============================================================================
with tab_ai:
    if len(all_days) == 0:
        st.info("👈 Sube tus datos de producción desde el Panel de Ingeniero en la barra lateral.")
    else:
        st.markdown("#### 🧠 Diagnóstico IA a Pie de Planta — Puntos Débiles y Cuellos de Botella")
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
            h_ext = float(sub_f[(sub_f["grupoTrab"] != "") & (~sub_f["grupoTrab"].isin(own_grps))]["horas"].sum())

            pct_env = (h_env / h_tot * 100.0) if h_tot > 0 else 0.0
            pct_sup = (h_sup / h_tot * 100.0) if h_tot > 0 else 0.0
            pct_ext = (h_ext / h_tot * 100.0) if h_tot > 0 else 0.0

            kg_m = float(sub_m["kgReal"].sum())
            kg_t = float(sub_m["kgTeo"].sum())
            kg_v = float(sub_v["kgReal"].sum())
            give = kg_m - kg_t
            eur_v = (h_tot * rate_dir / kg_v) if kg_v > 0 else 0.0
            t_obj = targets.get(l, DEFAULT_TARGETS[l])

            sup_chart_data.append({"Línea": l, "% Envasado Directo": pct_env, "% Soporte (Aux/Resp/Ord)": pct_sup, "% Personal Prestado": pct_ext})

            if t_obj and eur_v > t_obj["eurVen"] * 1.10 and kg_v > 1000:
                desv_p = (eur_v - t_obj["eurVen"]) / t_obj["eurVen"] * 100.0
                ai_cards.append((
                    "ai-card-crit",
                    f"🚨 Desviación de Coste en {l}: {eur_v:.4f} €/kg vendido (+{desv_p:.1f}% sobre objetivo {t_obj['eurVen']:.4f} €)",
                    f"La línea ha invertido {h_tot:.1f} h para mover {kg_m:,.0f} kg ({(kg_m/h_tot if h_tot>0 else 0):.1f} Kg/h movido frente a {t_obj['kghMov']:.1f} Kg/h objetivo).",
                    f"Acción a pie de máquina: Verificar microparadas de alimentación o exceso de confección para stock interno (USOINT) en {l}.",
                ))
            if pct_sup > 42.0 and h_tot > 15.0:
                ai_cards.append((
                    "ai-card-high",
                    f"⚙️ Sobrecarga de Personal de Soporte en {l} ({pct_sup:.1f}% de las horas no son de Envasado)",
                    f"De {h_tot:.1f} h totales en {l}, {h_sup:.1f} h corresponden a Auxiliar/Responsable/Ordenador y solo {h_env:.1f} h ({pct_env:.1f}%) a Envasado directo.",
                    f"Acción a pie de máquina: Reequilibrar abastecimiento de cartón/paletizado en {l} y reubicar al menos 1 auxiliar en mesa de envasado.",
                ))
            if abs(give) > tol_kg:
                ai_cards.append((
                    "ai-card-crit" if give > 0 else "ai-card-med",
                    f"⚖️ Descuadre en Parte de {l} fuera de tolerancia (±{int(tol_kg)} kg): {give:+.0f} kg",
                    f"La diferencia entre Neto Real ({kg_m:,.0f} kg) y Neto Teórico ({kg_t:,.0f} kg) supera el margen normal de planta.",
                    f"Acción a pie de máquina: Revisar en la Pestaña 5 si hay una ficha de Peso Confección mal parametrizada en Frutec para {l}.",
                ))

        if not ai_cards:
            st.success("✅ No se detectan cuellos de botella críticos en la selección actual.")
        else:
            c_ai1, c_ai2 = st.columns(2)
            for i, (cls, tit, desc, act) in enumerate(ai_cards):
                (c_ai1 if i % 2 == 0 else c_ai2).markdown(
                    f"<div class='{cls}'><b>{tit}</b><br><span style='font-size:13px; color:#334155;'>{desc}</span><br>"
                    f"<span style='font-size:12.5px; font-weight:700; color:#0f172a;'>🛠️ {act}</span></div>",
                    unsafe_allow_html=True,
                )


# =============================================================================
# PESTAÑA 4: MATRIZ DE UMBRALES OBJETIVOS
# =============================================================================
with tab_targ:
    if len(all_days) == 0:
        st.info("👈 Sube tus datos de producción desde el Panel de Ingeniero en la barra lateral.")
    else:
        st.markdown("#### 🎯 Matriz de Umbrales Objetivos por Línea Real (Incluye C1 Aguacate)")
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
            sync_db_to_github()
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
            disabled=["Línea Real", "Actual_€/Kg_Vendido", "Actual_€/Kg_Volcado", "Actual_Kg/H_Vendido", "Actual_Kg/H_Movido", "Semáforo"],
            use_container_width=True, hide_index=True,
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
            sync_db_to_github()
            st.success("✅ Umbrales guardados.")
            st.rerun()


# =============================================================================
# PESTAÑA 5: CUADRE DE KILOS EN PARTES (TOLERANCIA ±500 KG)
# =============================================================================
with tab_quad:
    if len(all_days) == 0:
        st.info("👈 Sube tus datos de producción desde el Panel de Ingeniero en la barra lateral.")
    else:
        st.markdown(f"#### ⚖️ Resumen de Cuadre de Kilos en Partes de Producción (Tolerancia asumida: ±{int(tol_kg)} kg)")
        quad_rows = []
        for l in LINES_LIST:
            sub_m = m_mov[m_mov["lReal"] == l]
            if sub_m.empty:
                continue
            kg_t = float(sub_m["kgTeo"].sum())
            kg_r = float(sub_m["kgReal"].sum())
            diff = kg_r - kg_t
            if abs(diff) <= tol_kg:
                estado = f"🟢 NORMAL (Dentro de ±{int(tol_kg)} kg)"
            elif diff > tol_kg:
                estado = f"🔴 EXCESO REAL (+{diff - tol_kg:,.0f} kg sobre tolerancia)"
            else:
                estado = f"🟡 DEFECTO / FICHA TARA ({diff + tol_kg:,.0f} kg bajo tolerancia)"

            quad_rows.append({
                "Línea Real": l,
                "Kilos Teóricos Parte (Kg)": round(kg_t, 0),
                "Kilos Reales Báscula (Kg)": round(kg_r, 0),
                "Descuadre (Real - Teórico)": round(diff, 0),
                f"Estado (Tolerancia ±{int(tol_kg)} kg)": estado,
            })

        df_quad = pd.DataFrame(quad_rows)
        st.dataframe(df_quad, use_container_width=True, hide_index=True)


# =============================================================================
# PESTAÑA 6: CONTEO DE CAJAS, OBJETIVOS DIARIOS Y LUPA DE ENVASADORAS
# =============================================================================
with tab_boxes:
    st.markdown("#### 📦 Control de Cajas, Objetivos por Línea y Seguimiento Individual de Envasadoras")
    st.caption(
        "Consulta por **Día, Semana, Mes o Rango de Fechas**. Mide tanto **Total de Cajas físicas** como **Cajas/Hora**, "
        "compara frente al **Objetivo Diario de cada línea** y analiza la evolución individual de cualquier envasadora."
    )

    cfg_env_list = get_config("BOX_WORKER_CFG", [])
    dias_inactivos_dict = get_config("BOX_INACTIVE_DAYS", {l: [] for l in BOX_LINES_LIST})
    box_targets_dict = get_config("BOX_LINE_TARGETS", DEFAULT_BOX_TARGETS)
    for bl in BOX_LINES_LIST:
        if bl not in box_targets_dict:
            box_targets_dict[bl] = DEFAULT_BOX_TARGETS[bl]

    with st.expander("⚙️ Configurar Envasadoras, Objetivos Diarios por Línea, Horarios y Flowpack", expanded=False):
        t_c1, t_c_obj, t_c2, t_c3 = st.tabs([
            "👩‍🌾 1. Envasadoras y Horarios (L-V / Excepciones)",
            "🎯 2. Límite Objetivo Diario por Línea",
            "🚫 3. Días Inactivos / Apagado Flowpack",
            "📥 4. Subir Excel Frutec Control",
        ])

        with t_c1:
            st.markdown(
                """
                * **Separación Mango vs Mesa Auxiliar Mango:** Asigna quién está en **Mango** y quién en **Mesa Auxiliar Mango** (contratos de 4h/5h).
                * **Excepción de un día:** Si alguien cambia de línea o horario un día concreto, añade una fila con esa fecha en **`Fecha_Excepcion`** (`DD/MM/YYYY`).
                """
            )
            df_cfg_env = pd.DataFrame(cfg_env_list) if cfg_env_list else pd.DataFrame(columns=[
                "Fecha_Excepcion", "Linea", "Envasadora", "Tipo_Contrato", "H_Entrada", "H_Salida", "Descanso_Min"
            ])

            if not df_cajas_db.empty:
                usuarios_detectados = sorted(df_cajas_db["usuario"].dropna().unique().tolist())
                usuarios_en_cfg = set(df_cfg_env["Envasadora"].apply(limpiar_nombre_envasadora).tolist()) if not df_cfg_env.empty else set()
                nuevas_env = [u for u in usuarios_detectados if u not in usuarios_en_cfg]
                if nuevas_env:
                    with st.popover(f"✨ Detectadas {len(nuevas_env)} envasadoras sin configurar (Clic para añadir en bloque)"):
                        sel_nuevas = st.multiselect("Selecciona trabajadoras:", nuevas_env)
                        c_n1, c_n2, c_n3, c_n4 = st.columns(4)
                        lin_bloque = c_n1.selectbox("Asignar Línea:", BOX_LINES_LIST)
                        cont_bloque = c_n2.selectbox("Tipo Contrato:", ["Jornada 8:00-15:30", "Contrato 5h", "Contrato 4h", "Turno Tarde", "Abierto (1ª a última caja)"])
                        hin_def = "08:00" if cont_bloque == "Jornada 8:00-15:30" else ("08:30" if "Contrato" in cont_bloque else "")
                        hout_def = "15:30" if cont_bloque == "Jornada 8:00-15:30" else ("13:30" if cont_bloque == "Contrato 5h" else ("12:30" if cont_bloque == "Contrato 4h" else ""))
                        hin_b = c_n3.text_input("H. Entrada (L-V):", value=hin_def)
                        hout_b = c_n4.text_input("H. Salida (L-V):", value=hout_def)
                        if st.button("➕ Añadir Seleccionadas a la Tabla") and sel_nuevas:
                            nuevas_rows = [{
                                "Fecha_Excepcion": "",
                                "Linea": "Mesa Auxiliar Mango" if ("Contrato" in cont_bloque and lin_bloque == "Mango") else lin_bloque,
                                "Envasadora": u_n,
                                "Tipo_Contrato": cont_bloque,
                                "H_Entrada": hin_b,
                                "H_Salida": hout_b,
                                "Descanso_Min": "0" if "Contrato" in cont_bloque else "",
                            } for u_n in sel_nuevas]
                            df_cfg_env = pd.concat([df_cfg_env, pd.DataFrame(nuevas_rows)], ignore_index=True)
                            set_config("BOX_WORKER_CFG", df_cfg_env.fillna("").to_dict(orient="records"))
                            sync_db_to_github()
                            st.rerun()

            df_cfg_edited = st.data_editor(
                df_cfg_env,
                num_rows="dynamic",
                use_container_width=True,
                column_config={
                    "Fecha_Excepcion": st.column_config.TextColumn("Fecha Excepción (Opcional)", help="Vacío = Lunes a Viernes. Pon DD/MM/YYYY para un día puntual."),
                    "Linea": st.column_config.SelectboxColumn("Línea Asignada", options=BOX_LINES_LIST, required=True),
                    "Envasadora": st.column_config.TextColumn("Envasadora (APELLIDOS, NOMBRE)", required=True),
                    "Tipo_Contrato": st.column_config.SelectboxColumn(
                        "Tipo Turno / Contrato",
                        options=["Jornada 8:00-15:30", "Contrato 5h", "Contrato 4h", "Turno Tarde", "Abierto (1ª a última caja)"],
                    ),
                    "H_Entrada": st.column_config.TextColumn("H. Entrada (HH:MM)"),
                    "H_Salida": st.column_config.TextColumn("H. Salida (HH:MM)"),
                    "Descanso_Min": st.column_config.TextColumn("Descanso Manual (Min)", help="Vacío = Automático. Pon 0 para contratos de 4h/5h."),
                },
                key="editor_cajas_env",
            )

            if st.button("💾 Guardar Tabla de Envasadoras", type="primary"):
                clean_list = df_cfg_edited.dropna(how="all").fillna("").to_dict(orient="records")
                set_config("BOX_WORKER_CFG", clean_list)
                sync_db_to_github()
                st.success("✅ Configuración de envasadoras guardada.")
                st.rerun()

        with t_c_obj:
            st.markdown("Define el **Objetivo Diario de Cajas por Envasadora** y el **Objetivo de Cajas/Hora** para cada línea (se dibuja como línea roja/verde de referencia en los gráficos):")
            rows_obj_box = []
            for bl in BOX_LINES_LIST:
                rows_obj_box.append({
                    "Línea": bl,
                    "Objetivo Cajas / Día": int(box_targets_dict.get(bl, {}).get("cajas_dia", 150)),
                    "Objetivo Cajas / Hora": float(box_targets_dict.get(bl, {}).get("cajas_hora", 22.0)),
                })
            df_obj_box_edit = st.data_editor(
                pd.DataFrame(rows_obj_box),
                disabled=["Línea"],
                use_container_width=True,
                hide_index=True,
                key="ed_box_targets",
            )
            if st.button("💾 Guardar Objetivos de Cajas por Línea", type="primary"):
                for _, r_ob in df_obj_box_edit.iterrows():
                    box_targets_dict[r_ob["Línea"]] = {
                        "cajas_dia": int(r_ob["Objetivo Cajas / Día"]),
                        "cajas_hora": float(r_ob["Objetivo Cajas / Hora"]),
                    }
                set_config("BOX_LINE_TARGETS", box_targets_dict)
                sync_db_to_github()
                st.success("✅ Objetivos de cajas por línea actualizados.")
                st.rerun()

        with t_c2:
            st.markdown("Bloquea los días en los que **Mesa Auxiliar Mango** (o cualquier otra línea) se usó para **Flowpack** para descartar lecturas de planchetas:")
            cb1, cb2, cb3 = st.columns([1.5, 1.5, 1])
            lin_block = cb1.selectbox("Línea a bloquear:", BOX_LINES_LIST, index=1)
            dt_block = cb2.date_input("Fecha a bloquear:", value=datetime.today())
            if cb3.button("🚫 Bloquear Día"):
                d_str = dt_block.strftime("%Y-%m-%d")
                lista_act = dias_inactivos_dict.get(lin_block, [])
                if d_str not in lista_act:
                    lista_act.append(d_str)
                    dias_inactivos_dict[lin_block] = sorted(lista_act, reverse=True)
                    set_config("BOX_INACTIVE_DAYS", dias_inactivos_dict)
                    sync_db_to_github()
                    st.success(f"Día {d_str} bloqueado en {lin_block}.")
                    st.rerun()

            fechas_bloq = dias_inactivos_dict.get(lin_block, [])
            fechas_keep = st.multiselect(
                f"Días bloqueados en {lin_block} (desmarca para reactivar):",
                options=fechas_bloq,
                default=fechas_bloq,
            )
            if set(fechas_keep) != set(fechas_bloq):
                dias_inactivos_dict[lin_block] = fechas_keep
                set_config("BOX_INACTIVE_DAYS", dias_inactivos_dict)
                sync_db_to_github()
                st.rerun()

        with t_c3:
            up_direct_caj = st.file_uploader("Subir Excel de Conteo de Cajas (Frutec Control)", type=["xlsx", "xls", "csv"], accept_multiple_files=True, key="up_dir_caj")
            if up_direct_caj and st.button("🚀 Guardar Cajas en Base de Datos"):
                n_ins = 0
                for fc in up_direct_caj:
                    df_r, _ = read_single_file(fc)
                    n_ins += save_cajas_to_db(parse_cajas_df(df_r))
                sync_db_to_github()
                st.cache_data.clear()
                st.success(f"✅ Se han importado {n_ins:,} cajas correctamente.")
                st.rerun()

    if df_cajas_db.empty:
        st.info("👆 Sube tu archivo Excel de Frutec Control en el desplegable superior ('📥 4. Subir Excel Frutec Control') o desde el Panel de Ingeniero lateral.")
    else:
        df_rep_cajas = calcular_reportes_cajas(df_cajas_db, cfg_env_list, dias_inactivos_dict)

        if df_rep_cajas.empty:
            st.warning("No hay registros que superen las 10 cajas/día o las fechas están bloqueadas por Flowpack.")
        else:
            # --- CONTROLES PRINCIPALES DE CONSULTA ---
            f_b1, f_b2, f_b3 = st.columns([2, 2, 1.5])
            lineas_disp = BOX_LINES_LIST + (["Sin Asignar"] if "Sin Asignar" in df_rep_cajas["Línea"].values else [])
            sel_box_line = f_b1.radio("🏭 1. Línea:", lineas_disp, horizontal=True)
            sel_box_period = f_b2.radio("📅 2. Periodo:", ["Diario", "Semanal", "Mensual", "Rango de Fechas"], horizontal=True)
            sel_box_metric = f_b3.radio("📊 3. Métrica Principal:", ["Total Cajas", "Cajas/Hora"], horizontal=True)

            df_sub_l = df_rep_cajas[df_rep_cajas["Línea"] == sel_box_line].copy()
            obj_cajas_dia_linea = int(box_targets_dict.get(sel_box_line, {"cajas_dia": 150}).get("cajas_dia", 150))
            obj_cajas_hora_linea = float(box_targets_dict.get(sel_box_line, {"cajas_hora": 22.0}).get("cajas_hora", 22.0))

            if df_sub_l.empty:
                st.info(f"No hay datos registrados para **{sel_box_line}**. Si pertenecen a esta línea (ej. contratos de 4h/5h en Mesa Auxiliar Mango), asígnalas en el desplegable superior.")
            else:
                # --- FILTRADO TEMPORAL Y AGREGACIÓN ---
                if sel_box_period == "Diario":
                    fechas_disp = df_sub_l.sort_values("dISO", ascending=False)["Fecha"].unique()
                    sel_p_val = st.selectbox("📌 Selecciona el Día:", fechas_disp)
                    df_filtered_raw = df_sub_l[df_sub_l["Fecha"] == sel_p_val].copy()
                    df_view = df_filtered_raw.copy()
                    df_view["Días Trab."] = 1
                    df_view["Cajas/Día Media"] = df_view["Total Cajas"]
                    df_view["Obj. Cajas Periodo"] = obj_cajas_dia_linea
                    df_view["% Cumpl. Cajas"] = (df_view["Total Cajas"] / obj_cajas_dia_linea * 100.0).round(1)
                    cols_table = ["Fecha", "Envasadora", "Contrato", "Total Cajas", "Obj. Cajas Periodo", "% Cumpl. Cajas", "H. Entrada", "H. Salida", "Horas Reales", "Cajas/Hora"]
                    chart_title = f"Rendimiento Diario ({sel_p_val}) — {sel_box_line}"

                elif sel_box_period == "Semanal":
                    semanas_disp = df_sub_l.sort_values("Lunes_Sort", ascending=False)["Semana"].unique()
                    sel_p_val = st.selectbox("📌 Selecciona la Semana (Lunes a Domingo):", semanas_disp)
                    df_filtered_raw = df_sub_l[df_sub_l["Semana"] == sel_p_val].copy()
                    df_agg = df_filtered_raw.groupby(["Semana", "Línea", "Envasadora", "Contrato"], as_index=False).agg(
                        **{
                            "Días Trab.": ("dISO", "nunique"),
                            "Total Cajas": ("Total Cajas", "sum"),
                            "Horas Reales": ("Horas Reales", "sum"),
                        }
                    )
                    df_agg = df_agg[df_agg["Total Cajas"] >= 50].copy()
                    df_agg["Horas Reales"] = df_agg["Horas Reales"].round(2)
                    df_agg["Cajas/Día Media"] = (df_agg["Total Cajas"] / df_agg["Días Trab."]).round(1)
                    df_agg["Obj. Cajas Periodo"] = df_agg["Días Trab."] * obj_cajas_dia_linea
                    df_agg["% Cumpl. Cajas"] = (df_agg["Total Cajas"] / df_agg["Obj. Cajas Periodo"] * 100.0).round(1)
                    df_agg["Cajas/Hora"] = (df_agg["Total Cajas"] / df_agg["Horas Reales"]).round(2)
                    df_view = df_agg
                    cols_table = ["Semana", "Envasadora", "Contrato", "Días Trab.", "Total Cajas", "Cajas/Día Media", "Obj. Cajas Periodo", "% Cumpl. Cajas", "Horas Reales", "Cajas/Hora"]
                    chart_title = f"Rendimiento Semanal ({sel_p_val}) — {sel_box_line}"

                elif sel_box_period == "Mensual":
                    meses_disp = df_sub_l.sort_values("Mes_Sort", ascending=False)["Mes"].unique()
                    sel_p_val = st.selectbox("📌 Selecciona el Mes:", meses_disp)
                    df_filtered_raw = df_sub_l[df_sub_l["Mes"] == sel_p_val].copy()
                    df_agg = df_filtered_raw.groupby(["Mes", "Línea", "Envasadora", "Contrato"], as_index=False).agg(
                        **{
                            "Días Trab.": ("dISO", "nunique"),
                            "Total Cajas": ("Total Cajas", "sum"),
                            "Horas Reales": ("Horas Reales", "sum"),
                        }
                    )
                    df_agg = df_agg[df_agg["Total Cajas"] >= 200].copy()
                    df_agg["Horas Reales"] = df_agg["Horas Reales"].round(2)
                    df_agg["Cajas/Día Media"] = (df_agg["Total Cajas"] / df_agg["Días Trab."]).round(1)
                    df_agg["Obj. Cajas Periodo"] = df_agg["Días Trab."] * obj_cajas_dia_linea
                    df_agg["% Cumpl. Cajas"] = (df_agg["Total Cajas"] / df_agg["Obj. Cajas Periodo"] * 100.0).round(1)
                    df_agg["Cajas/Hora"] = (df_agg["Total Cajas"] / df_agg["Horas Reales"]).round(2)
                    df_view = df_agg
                    cols_table = ["Mes", "Envasadora", "Contrato", "Días Trab.", "Total Cajas", "Cajas/Día Media", "Obj. Cajas Periodo", "% Cumpl. Cajas", "Horas Reales", "Cajas/Hora"]
                    chart_title = f"Rendimiento Mensual ({sel_p_val}) — {sel_box_line}"

                else:  # Rango de Fechas
                    min_b_dt = pd.to_datetime(df_sub_l["dISO"].min()).date()
                    max_b_dt = pd.to_datetime(df_sub_l["dISO"].max()).date()
                    rng_box = st.date_input(
                        "📌 Selecciona el Rango de Fechas (Inicio - Fin):",
                        value=(min_b_dt, max_b_dt),
                        min_value=min_b_dt,
                        max_value=max_b_dt,
                        key="rng_box_sel",
                    )
                    d1_b, d2_b = (str(rng_box[0]), str(rng_box[1])) if len(rng_box) == 2 else (str(rng_box[0]), str(rng_box[0]))
                    df_filtered_raw = df_sub_l[(df_sub_l["dISO"] >= d1_b) & (df_sub_l["dISO"] <= d2_b)].copy()
                    df_agg = df_filtered_raw.groupby(["Línea", "Envasadora", "Contrato"], as_index=False).agg(
                        **{
                            "Días Trab.": ("dISO", "nunique"),
                            "Total Cajas": ("Total Cajas", "sum"),
                            "Horas Reales": ("Horas Reales", "sum"),
                        }
                    )
                    min_cajas_rng = 10 if d1_b == d2_b else 30
                    df_agg = df_agg[df_agg["Total Cajas"] >= min_cajas_rng].copy()
                    df_agg["Horas Reales"] = df_agg["Horas Reales"].round(2)
                    df_agg["Cajas/Día Media"] = (df_agg["Total Cajas"] / df_agg["Días Trab."]).round(1)
                    df_agg["Obj. Cajas Periodo"] = df_agg["Días Trab."] * obj_cajas_dia_linea
                    df_agg["% Cumpl. Cajas"] = (df_agg["Total Cajas"] / df_agg["Obj. Cajas Periodo"] * 100.0).round(1)
                    df_agg["Cajas/Hora"] = (df_agg["Total Cajas"] / df_agg["Horas Reales"]).round(2)
                    df_view = df_agg
                    cols_table = ["Envasadora", "Contrato", "Días Trab.", "Total Cajas", "Cajas/Día Media", "Obj. Cajas Periodo", "% Cumpl. Cajas", "Horas Reales", "Cajas/Hora"]
                    chart_title = f"Rendimiento del {d1_b} al {d2_b} — {sel_box_line}"

                # --- FILTRO / LUPA DE ENVASADORAS ESPECÍFICAS ---
                env_disponibles = sorted(df_view["Envasadora"].unique().tolist()) if not df_view.empty else []
                sel_env_filter = st.multiselect(
                    "🔍 Filtrar o Comparar Envasadoras concretas (vacío = muestra toda la línea completa):",
                    options=env_disponibles,
                    default=[],
                )
                if sel_env_filter:
                    df_view = df_view[df_view["Envasadora"].isin(sel_env_filter)].copy()
                    df_filtered_raw = df_filtered_raw[df_filtered_raw["Envasadora"].isin(sel_env_filter)].copy()

                if df_view.empty:
                    st.warning("Ninguna envasadora supera el umbral mínimo en este periodo o selección.")
                else:
                    df_view = df_view.sort_values(sel_box_metric, ascending=False)

                    # KPIs Superiores con Comparativa de Objetivo
                    kb1, kb2, kb3, kb4, kb5 = st.columns(5)
                    tot_cajas_per = int(df_view["Total Cajas"].sum())
                    media_cajas_dia = float(df_view["Cajas/Día Media"].mean())
                    media_ch = float(df_view["Cajas/Hora"].mean())
                    cumpl_global = float((df_view["Total Cajas"] >= df_view["Obj. Cajas Periodo"]).mean() * 100.0)

                    kb1.metric("📦 Total Cajas", f"{tot_cajas_per:,}".replace(",", "."), f"{len(df_view)} envasadoras")
                    kb2.metric(
                        "🎯 Media Cajas / Día",
                        f"{media_cajas_dia:.0f} cajas",
                        f"{media_cajas_dia - obj_cajas_dia_linea:+.0f} vs Obj ({obj_cajas_dia_linea}/día)",
                    )
                    kb3.metric(
                        "⚡ Media Cajas / Hora",
                        f"{media_ch:.2f} cajas/h",
                        f"{media_ch - obj_cajas_hora_linea:+.2f} vs Obj ({obj_cajas_hora_linea}/h)",
                    )
                    kb4.metric("🏆 Top #1 Periodo", f"{df_view.iloc[0]['Envasadora']}", f"{df_view.iloc[0]['Total Cajas']} cajas ({df_view.iloc[0]['Cajas/Hora']}/h)")
                    kb5.metric("✅ Cumplen Objetivo Cajas", f"{cumpl_global:.0f}% de la línea", f"Meta: {obj_cajas_dia_linea} cajas/día")

                    # --- GRÁFICO PRINCIPAL DE RANKING + LÍNEA DE OBJETIVO ---
                    cg_box, ct_box = st.columns([1.15, 1])
                    with cg_box:
                        df_plot = df_view.sort_values(sel_box_metric, ascending=True)
                        fig_b = px.bar(
                            df_plot,
                            x=sel_box_metric,
                            y="Envasadora",
                            orientation="h",
                            text=sel_box_metric,
                            color=sel_box_metric,
                            color_continuous_scale="Emrld" if sel_box_metric == "Cajas/Hora" else "Tealgrn",
                            title=f"{chart_title} ({sel_box_metric})",
                        )
                        fig_b.update_traces(textposition="outside")

                        # Añadir línea vertical de objetivo cuando procede
                        if sel_box_metric == "Cajas/Hora":
                            fig_b.add_vline(
                                x=obj_cajas_hora_linea,
                                line_dash="dash",
                                line_color="#dc2626",
                                line_width=2.5,
                                annotation_text=f"Obj: {obj_cajas_hora_linea} Cajas/h",
                                annotation_position="top right",
                            )
                        elif sel_box_period == "Diario" and sel_box_metric == "Total Cajas":
                            fig_b.add_vline(
                                x=obj_cajas_dia_linea,
                                line_dash="dash",
                                line_color="#dc2626",
                                line_width=2.5,
                                annotation_text=f"Obj Diario: {obj_cajas_dia_linea} Cajas",
                                annotation_position="top right",
                            )

                        fig_b.update_layout(
                            height=max(380, len(df_plot) * 32),
                            yaxis_title="",
                            xaxis_title=sel_box_metric,
                            coloraxis_showscale=False,
                            margin=dict(l=10, r=50, t=45, b=20),
                        )
                        st.plotly_chart(fig_b, use_container_width=True)

                    with ct_box:
                        st.markdown(f"##### 📋 Tabla Detallada — {sel_box_line}")
                        st.dataframe(
                            df_view[cols_table],
                            use_container_width=True,
                            hide_index=True,
                            height=max(380, len(df_view) * 32),
                        )

                    # --- EVOLUCIÓN DÍA A DÍA DE LA ENVASADORA O SELECCIÓN ---
                    st.markdown("---")
                    st.markdown("##### 📈 Seguimiento y Evolución Día a Día por Envasadora (Cajas Diarias vs. Objetivo)")
                    env_evol_list = sel_env_filter if sel_env_filter else [df_view.iloc[0]["Envasadora"]]
                    sel_env_chart = st.multiselect(
                        "👩‍🌾 Selecciona una o varias envasadoras para ver su curva diaria de cajas e historial:",
                        options=sorted(df_sub_l["Envasadora"].unique().tolist()),
                        default=env_evol_list[:3],
                        key="evol_env_sel",
                    )

                    if sel_env_chart:
                        df_hist_env = df_sub_l[df_sub_l["Envasadora"].isin(sel_env_chart)].sort_values("dISO")
                        fig_ev = go.Figure()
                        for u_ev in sel_env_chart:
                            sub_u = df_hist_env[df_hist_env["Envasadora"] == u_ev]
                            fig_ev.add_trace(go.Scatter(
                                x=sub_u["Fecha"],
                                y=sub_u[sel_box_metric],
                                mode="lines+markers+text",
                                name=u_ev,
                                text=sub_u[sel_box_metric],
                                textposition="top center",
                            ))

                        ref_y = obj_cajas_dia_linea if sel_box_metric == "Total Cajas" else obj_cajas_hora_linea
                        ref_label = f"Objetivo Diario Línea ({obj_cajas_dia_linea} cajas)" if sel_box_metric == "Total Cajas" else f"Objetivo Hora ({obj_cajas_hora_linea} cajas/h)"
                        fig_ev.add_hline(
                            y=ref_y,
                            line_dash="dot",
                            line_color="#dc2626",
                            line_width=2.5,
                            annotation_text=ref_label,
                            annotation_position="bottom right",
                        )
                        fig_ev.update_layout(
                            title=f"Evolución Diaria de {sel_box_metric} — {', '.join(sel_env_chart)}",
                            height=380,
                            xaxis_title="Fecha",
                            yaxis_title=sel_box_metric,
                            margin=dict(t=45, b=30, l=40, r=20),
                        )
                        st.plotly_chart(fig_ev, use_container_width=True)
