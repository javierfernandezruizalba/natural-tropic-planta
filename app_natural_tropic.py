import os
import sqlite3
import json
import numpy as np
import pandas as pd
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
ADMIN_PIN = st.secrets.get("ADMIN_PIN", "1234") if hasattr(st, "secrets") else "1234"

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
    1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
    7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic",
}

DEFAULT_TARGETS = {
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
# 2. BASE DE DATOS SQLITE COMPARTIDA
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
# 3. MOTOR DE LECTURA Y LIMPIEZA (4 PESTAÑAS EXCEL O TXT DIARIOS)
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
        .fillna("").astype(str).str.strip().str.upper()
    )
    df["conf"] = (
        df.get("Confección", pd.Series([""] * len(df), index=df.index))
        .fillna("").astype(str).str.strip().str.upper()
    )
    df["conf"] = np.where(df["conf"] == "", df["emb"], df["conf"])
    pos = df.get("Posición", pd.Series([""] * len(df), index=df.index)).fillna("").astype(str).str.upper()
    cat = df.get("Categoria", pd.Series([""] * len(df), index=df.index)).fillna("").astype(str).str.upper()
    df["isDestrio"] = ((cat == "DX") | pos.str.contains("DESTRIO|BASURA|ACEITE|PODRIDO|GUACAMOLE", regex=True)).astype(int)
    df["isInterno"] = ((df["emb"] == "USOINT") | pos.str.contains("REPASO|USO|SOBRANTE|DESCALIBRADO", regex=True)).astype(int)
    df["cliente"] = df.get("Cliente", pd.Series([""] * len(df), index=df.index)).fillna("").astype(str).str.strip()
    return df[["dISO", "y", "mISO", "wISO", "lReal", "conf", "emb", "cajas", "kgTeo", "kgReal", "isDestrio", "isInterno", "cliente"]]


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
    df["cliente"] = df.get("Cliente", pd.Series([""] * len(df), index=df.index)).fillna("").astype(str).str.strip()
    return df[["dISO", "y", "mISO", "wISO", "lReal", "cajas", "kgTeo", "kgReal", "cliente"]]


def parse_fic_df(df):
    df.columns = [str(c).strip() for c in df.columns]
    date_col = "Fecha (Asignado)" if "Fecha (Asignado)" in df.columns else ("Fecha" if "Fecha" in df.columns else None)
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
    df["operacion"] = df.get("Operación", pd.Series([""] * len(df), index=df.index)).fillna("").astype(str).str.strip().str.upper()
    df["grupoTrab"] = df.get("Grupo TRABAJADOR", pd.Series([""] * len(df), index=df.index)).fillna("").astype(str).str.strip().str.upper()
    return df[["dISO", "y", "mISO", "wISO", "lReal", "horas", "tipoCoste", "operacion", "grupoTrab"]]


def read_single_file(uploaded_file):
    name_low = uploaded_file.name.lower()
    if name_low.endswith((".xlsx", ".xls")):
        xls = pd.ExcelFile(uploaded_file)
        for s_name in xls.sheet_names:
            df_s = pd.read_excel(xls, sheet_name=s_name)
            if not df_s.empty and len(df_s.columns) >= 5:
                return df_s
    else:
        for enc in ["latin1", "utf-8", "cp1252"]:
            try:
                uploaded_file.seek(0)
                df_s = pd.read_csv(uploaded_file, sep=";", encoding=enc, low_memory=False)
                if len(df_s.columns) >= 5:
                    return df_s
            except Exception:
                continue
    return pd.DataFrame()


def process_annual_workbook(uploaded_file):
    xls = pd.ExcelFile(uploaded_file)
    n_m, n_v, n_f = 0, 0, 0
    for s_name in xls.sheet_names:
        s_up = s_name.strip().upper()
        if "RESUMEN" in s_up or "DINAMIC" in s_up or "TABLA" in s_up:
            continue
        df_s = pd.read_excel(xls, sheet_name=s_name)
        if df_s.empty or len(df_s.columns) < 4:
            continue
        cols = [str(c).strip() for c in df_s.columns]

        if "FICHAJ" in s_up or "ID TRABAJADOR" in [c.upper() for c in cols]:
            n_f += save_dataframe_to_db(parse_fic_df(df_s), "fichajes")
        elif "VENTA" in s_up:
            n_v += save_dataframe_to_db(parse_ven_df(df_s), "mov_ventas")
        elif "PARTE" in s_up or "PRODUCCION" in s_up or "ALMACEN" in s_up:
            n_m += save_dataframe_to_db(parse_mov_df(df_s), "mov_almacen")
        else:
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
# 4. BARRA LATERAL: CONFIGURACIÓN Y SUBIDA DE DATOS (EXCEL ANUAL + TXT DIARIO)
# =============================================================================
with st.sidebar:
    st.markdown("## 🥑 Natural Tropic S.L.")
    st.caption("Control de Operaciones, Costes y Diagnóstico IA")

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
    with st.expander("🔐 Panel de Ingeniero (Subir Datos)", expanded=False):
        pin_input = st.text_input("PIN de Ingeniero (1234)", type="password")
        if pin_input == ADMIN_PIN:
            st.success("Modo Ingeniero Activo")
            st.markdown("**A) Subir Libros Excel Anuales (4 pestañas):**")
            up_annual = st.file_uploader(
                "Excel 2024, 2025 o 2026 (.xlsx)", type=["xlsx", "xls"], accept_multiple_files=True, key="ann"
            )
            st.markdown("**B) Subir Archivos Diarios Sueltos (.txt o .xlsx):**")
            up_mov = st.file_uploader("1. Partes Producción (.txt/.xlsx)", type=["txt", "csv", "xlsx"], accept_multiple_files=True, key="d_mov")
            up_ven = st.file_uploader("2. Mov. Ventas (.txt/.xlsx)", type=["txt", "csv", "xlsx"], accept_multiple_files=True, key="d_ven")
            up_fic = st.file_uploader("3. Fichajes Personal (.txt/.xlsx)", type=["txt", "csv", "xlsx"], accept_multiple_files=True, key="d_fic")

            if st.button("🚀 Procesar y Publicar Datos", type="primary", use_container_width=True):
                tot_m, tot_v, tot_f = 0, 0, 0
                with st.spinner("Procesando archivos y actualizando base de datos..."):
                    for f in up_annual or []:
                        nm, nv, nf = process_annual_workbook(f)
                        tot_m += nm; tot_v += nv; tot_f += nf
                    for f in up_mov or []:
                        tot_m += save_dataframe_to_db(parse_mov_df(read_single_file(f)), "mov_almacen")
                    for f in up_ven or []:
                        tot_v += save_dataframe_to_db(parse_ven_df(read_single_file(f)), "mov_ventas")
                    for f in up_fic or []:
                        tot_f += save_dataframe_to_db(parse_fic_df(read_single_file(f)), "fichajes")
                st.cache_data.clear()
                st.success(f"✅ Guardado: +{tot_m} Partes | +{tot_v} Ventas | +{tot_f} Fichajes")
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
# 5. CARGA DE DATOS Y FUNCIONES AUXILIARES DE CÁLCULO
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
    f"### 🥑 NATURAL TROPIC S.L. — Inteligencia Operativa de Planta y Control de Costes  "
    f"<span style='font-size:13px; background:#065f46; color:#a7f3d0; padding:4px 10px; border-radius:99px;'>"
    f"Histórico Activo: {len(all_days)} días ({len(df_mov)+len(df_ven)+len(df_fic):,} registros)</span>",
    unsafe_allow_html=True,
)

if len(all_days) == 0:
    st.info(
        "👈 Abre el **'🔐 Panel de Ingeniero'** en la barra izquierda (PIN: `1234`), "
        "sube tus Excel anuales de 4 pestañas o los `.txt` diarios y pulsa **'🚀 Procesar y Publicar Datos'**."
    )
    st.stop()

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


def compute_period_metrics(sub_m, sub_v, sub_f, line_filter="TODAS"):
    """Calcula todas las métricas operativas y de coste para un subconjunto temporal."""
    if line_filter != "TODAS":
        m_d = sub_m[sub_m["lReal"] == line_filter]
        v_d = sub_v[sub_v["lReal"] == line_filter]
        f_d = sub_f[sub_f["lReal"] == line_filter]
        h_ind = 0.0
    else:
        m_d = sub_m[sub_m["lReal"].isin(LINES_LIST)]
        v_d = sub_ven_lines = sub_v[sub_v["lReal"].isin(LINES_LIST)]
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
# 6. NAVEGACIÓN PRINCIPAL EN 5 PESTAÑAS
# =============================================================================
tab_dash, tab_comp, tab_ai, tab_targ, tab_quad = st.tabs([
    "📊 1. Cuadro de Mando General",
    "⚔️ 2. Comparador de Fechas + Análisis IA",
    "🧠 3. Cuellos de Botella en Planta",
    "🎯 4. Umbrales Objetivos",
    f"⚖️ 5. Cuadre de Kilos (Tolerancia ±{int(tol_kg)} kg)",
])

# -----------------------------------------------------------------------------
# FILTROS RÁPIDOS PARA LAS PESTAÑAS GENERALES (1, 3 y 5)
# -----------------------------------------------------------------------------
with tab_dash:
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

    # KPIs Superiores
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
    k1.metric("Coste MO Directa", f"{imp_dir:,.0f} €", f"{tot_h_dir:,.1f} h ({(tot_h_dir/tot_h_all*100 if tot_h_all>0 else 0):.0f}%)")
    k2.metric("Coste MO Indirecta", f"{imp_ind:,.0f} €", f"{tot_h_ind:,.1f} h ({(tot_h_ind/tot_h_all*100 if tot_h_all>0 else 0):.0f}%)")
    k3.metric("Coste Total Personal", f"{imp_tot:,.0f} €", f"{tot_h_all:,.1f} h totales")
    k4.metric("Movido vs Vendido", f"{tot_kg_mov/1000:,.1f}t / {tot_kg_ven/1000:,.1f}t", f"{(tot_kg_ven/tot_kg_mov*100 if tot_kg_mov>0 else 0):.1f}% vendido")
    k5.metric("€/Kg Vendido (Directo)", f"{eur_ven_dir:.4f} €", f"{kgh_ven_tot:.1f} Kg/H vendido")
    k6.metric("€/Kg Vendido (Total c/Ind)", f"{eur_ven_tot:.4f} €", f"+{eur_ven_ind:.4f} €/kg ind.", delta_color="inverse")

    col_map = {"Línea Real": "lReal", "Año": "y", "Mes": "mISO", "Semana ISO": "wISO", "Día": "dISO"}
    g_col = col_map[group_mode]

    g_f = m_fic[m_fic["lReal"].isin(LINES_LIST)].groupby(g_col)["horas"].sum()
    g_m_real = m_dir.groupby(g_col)["kgReal"].sum()
    g_m_teo = m_dir.groupby(g_col)["kgTeo"].sum()
    g_v_real = v_dir.groupby(g_col)["kgReal"].sum()

    idx_keys = sorted(list(set(g_f.index) | set(g_m_real.index) | set(g_v_real.index)))
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
        fig_prod.add_trace(go.Bar(x=df_summary[group_mode], y=df_summary["Kg/H Movido"], name="Kg/H Movido (Almacén)", marker_color="#2563eb"))
        fig_prod.add_trace(go.Bar(x=df_summary[group_mode], y=df_summary["Kg/H Vendido"], name="Kg/H Vendido (Ventas)", marker_color="#16a34a"))
        if group_mode == "Línea Real":
            fig_prod.add_trace(go.Scatter(
                x=df_summary[group_mode],
                y=[targets.get(k, {}).get("kghVen", 0) for k in df_summary[group_mode]],
                name="Objetivo Kg/H Vendido", mode="lines+markers", line=dict(color="#1d4ed8", width=3, dash="dot"),
            ))
        fig_prod.update_layout(title=f"Productividad Horaria por {group_mode} (Kg/Hora)", barmode="group", height=360, margin=dict(t=40, b=30, l=40, r=20))
        st.plotly_chart(fig_prod, use_container_width=True)

    st.markdown(f"#### 📋 Tabla Ejecutiva Consolidada por **{group_mode}**")
    st.dataframe(df_summary, use_container_width=True, hide_index=True)

    with st.expander("➕ Desplegar Detalle Jerárquico Día a Día por Línea Real (Estilo Tabla Dinámica Excel)"):
        sel_drill_line = st.selectbox("Selecciona Línea para inspeccionar su serie diaria y mensual:", LINES_LIST)
        sub_f_l = m_fic[m_fic["lReal"] == sel_drill_line].groupby(["mISO", "dISO"])["horas"].sum()
        sub_m_l = m_mov[m_mov["lReal"] == sel_drill_line].groupby(["mISO", "dISO"])["kgReal"].sum()
        sub_v_l = m_ven[m_ven["lReal"] == sel_drill_line].groupby(["mISO", "dISO"])["kgReal"].sum()
        drill_idx = sorted(list(set(sub_f_l.index) | set(sub_m_l.index) | set(sub_v_l.index)))
        drill_rows = []
        for m_k, d_k in drill_idx:
            hh = float(sub_f_l.get((m_k, d_k), 0.0))
            mm = float(sub_m_l.get((m_k, d_k), 0.0))
            vv = float(sub_v_l.get((m_k, d_k), 0.0))
            ii = hh * rate_dir
            drill_rows.append({
                "Línea Real": sel_drill_line, "Mes": m_k, "Fecha": d_k,
                "Horas": round(hh, 1), "Importe (€)": round(ii, 2),
                "Kg Movido": round(mm, 0), "Kg Vendido": round(vv, 0),
                "% Vendido/Movido": f"{(vv/mm*100 if mm>0 else 0):.0f}%",
                "€/Kg Volcado": round(ii / mm, 3) if mm > 0 else 0.0,
                "€/Kg Vendido": round(ii / vv, 4) if vv > 0 else 0.0,
                "Kg/H Vendido": round(vv / hh, 2) if hh > 0 else 0.0,
                "Kg/H Movido": round(mm / hh, 2) if hh > 0 else 0.0,
            })
        st.dataframe(pd.DataFrame(drill_rows), use_container_width=True, hide_index=True)


# =============================================================================
# PESTAÑA 2 (NUEVA): COMPARADOR DE FECHAS / PERIODOS + ANÁLISIS IA ESPECÍFICO
# =============================================================================
with tab_comp:
    st.markdown("#### ⚔️ Comparador Cara a Cara de Fechas y Líneas con Análisis IA")
    st.caption(
        "Compara dos años, dos meses, dos semanas, dos días o dos rangos de fechas cualesquiera. "
        "Puedes analizar **Toda la Empresa en bloque** o aislar **una Línea Real concreta**."
    )

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

    # Selección de Periodo A (Base) y Periodo B (Comparado)
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

    # Tarjetas de Variación (Periodo B frente a Periodo A)
    st.markdown(f"##### 📊 Resultado Comparativo: **{label_b}** frente a **{label_a}** ({comp_scope})")
    mc1, mc2, mc3, mc4, mc5 = st.columns(5)

    diff_eur_ven = met_b["eur_ven"] - met_a["eur_ven"]
    pct_eur_ven = (diff_eur_ven / met_a["eur_ven"] * 100.0) if met_a["eur_ven"] > 0 else 0.0
    mc1.metric(
        "€/Kg Vendido (B vs A)",
        f"{met_b['eur_ven']:.4f} €",
        f"{diff_eur_ven:+.4f} € ({pct_eur_ven:+.1f}%)",
        delta_color="inverse",
    )

    diff_eur_vol = met_b["eur_vol"] - met_a["eur_vol"]
    pct_eur_vol = (diff_eur_vol / met_a["eur_vol"] * 100.0) if met_a["eur_vol"] > 0 else 0.0
    mc2.metric(
        "€/Kg Volcado (B vs A)",
        f"{met_b['eur_vol']:.4f} €",
        f"{diff_eur_vol:+.4f} € ({pct_eur_vol:+.1f}%)",
        delta_color="inverse",
    )

    diff_kgh_ven = met_b["kgh_ven"] - met_a["kgh_ven"]
    pct_kgh_ven = (diff_kgh_ven / met_a["kgh_ven"] * 100.0) if met_a["kgh_ven"] > 0 else 0.0
    mc3.metric(
        "Productividad Kg/H Vendido",
        f"{met_b['kgh_ven']:.1f} Kg/h",
        f"{diff_kgh_ven:+.1f} Kg/h ({pct_kgh_ven:+.1f}%)",
    )

    diff_kgh_mov = met_b["kgh_mov"] - met_a["kgh_mov"]
    pct_kgh_mov = (diff_kgh_mov / met_a["kgh_mov"] * 100.0) if met_a["kgh_mov"] > 0 else 0.0
    mc4.metric(
        "Velocidad Kg/H Movido",
        f"{met_b['kgh_mov']:.1f} Kg/h",
        f"{diff_kgh_mov:+.1f} Kg/h ({pct_kgh_mov:+.1f}%)",
    )

    diff_conv = met_b["pct_conv"] - met_a["pct_conv"]
    mc5.metric(
        "% Vendido / Movido",
        f"{met_b['pct_conv']:.1f}%",
        f"{diff_conv:+.1f} pts (vs {met_a['pct_conv']:.1f}%)",
    )

    # Gráficas Comparativas
    cg1, cg2 = st.columns(2)
    if line_arg == "TODAS":
        # Si es Toda la Empresa, comparar línea por línea entre Periodo A y Periodo B
        l_names, a_costs, b_costs, a_kgh, b_kgh = [], [], [], [], []
        for l in LINES_LIST:
            ma = compute_period_metrics(mov_a, ven_a, fic_a, l)
            mb = compute_period_metrics(mov_b, ven_b, fic_b, l)
            if ma["h_dir"] > 0 or mb["h_dir"] > 0 or ma["kg_mov"] > 0 or mb["kg_mov"] > 0:
                l_names.append(l)
                a_costs.append(ma["eur_ven"])
                b_costs.append(mb["eur_ven"])
                a_kgh.append(ma["kgh_ven"])
                b_kgh.append(mb["kgh_ven"])

        with cg1:
            fig_ca = go.Figure()
            fig_ca.add_trace(go.Bar(x=l_names, y=a_costs, name=f"🅰️ {label_a}", marker_color="#94a3b8"))
            fig_ca.add_trace(go.Bar(x=l_names, y=b_costs, name=f"🅱️ {label_b}", marker_color="#dc2626"))
            fig_ca.update_layout(title="Comparativa de Coste €/Kg Vendido por Línea Real", barmode="group", height=360, margin=dict(t=40, b=30, l=40, r=20))
            st.plotly_chart(fig_ca, use_container_width=True)

        with cg2:
            fig_cb = go.Figure()
            fig_cb.add_trace(go.Bar(x=l_names, y=a_kgh, name=f"🅰️ {label_a}", marker_color="#94a3b8"))
            fig_cb.add_trace(go.Bar(x=l_names, y=b_kgh, name=f"🅱️ {label_b}", marker_color="#16a34a"))
            fig_cb.update_layout(title="Comparativa de Velocidad (Kg/H Vendido) por Línea Real", barmode="group", height=360, margin=dict(t=40, b=30, l=40, r=20))
            st.plotly_chart(fig_cb, use_container_width=True)
    else:
        # Si es una Línea Específica, mostrar comparativa de Costes y Productividad de esa línea
        with cg1:
            fig_l1 = go.Figure()
            fig_l1.add_trace(go.Bar(x=["€/Kg Volcado", "€/Kg Vendido"], y=[met_a["eur_vol"], met_a["eur_ven"]], name=f"🅰️ {label_a}", marker_color="#64748b"))
            fig_l1.add_trace(go.Bar(x=["€/Kg Volcado", "€/Kg Vendido"], y=[met_b["eur_vol"], met_b["eur_ven"]], name=f"🅱️ {label_b}", marker_color="#dc2626"))
            fig_l1.update_layout(title=f"Evolución de Costes en {line_arg} ({label_a} vs {label_b})", barmode="group", height=350)
            st.plotly_chart(fig_l1, use_container_width=True)
        with cg2:
            fig_l2 = go.Figure()
            fig_l2.add_trace(go.Bar(x=["Kg/H Movido", "Kg/H Vendido"], y=[met_a["kgh_mov"], met_a["kgh_ven"]], name=f"🅰️ {label_a}", marker_color="#64748b"))
            fig_l2.add_trace(go.Bar(x=["Kg/H Movido", "Kg/H Vendido"], y=[met_b["kgh_mov"], met_b["kgh_ven"]], name=f"🅱️ {label_b}", marker_color="#16a34a"))
            fig_l2.update_layout(title=f"Evolución de Productividad en {line_arg} ({label_a} vs {label_b})", barmode="group", height=350)
            st.plotly_chart(fig_l2, use_container_width=True)

    # -------------------------------------------------------------------------
    # INFORME EJECUTIVO IA ESPECÍFICO DE LA COMPARATIVA (EMPRESA O LÍNEA)
    # -------------------------------------------------------------------------
    impacto_euros_eficiencia = (met_a["eur_ven"] - met_b["eur_ven"]) * met_b["kg_ven"] if met_a["eur_ven"] > 0 and met_b["kg_ven"] > 0 else 0.0
    estado_coste = "MEJORADO (reducido costes)" if diff_eur_ven < 0 else ("EMPEORADO (encarecido costes)" if diff_eur_ven > 0 else "MANTENIDO")
    color_impacto = "#059669" if impacto_euros_eficiencia >= 0 else "#dc2626"

    # Identificar mejor y peor línea si estamos viendo Toda la Empresa
    detalle_lineas_html = ""
    if line_arg == "TODAS":
        cambios_lineas = []
        for l in LINES_LIST:
            ma = compute_period_metrics(mov_a, ven_a, fic_a, l)
            mb = compute_period_metrics(mov_b, ven_b, fic_b, l)
            if ma["eur_ven"] > 0 and mb["eur_ven"] > 0 and mb["kg_ven"] > 500:
                cambios_lineas.append((l, mb["eur_ven"] - ma["eur_ven"], ma["eur_ven"], mb["eur_ven"], mb["kgh_ven"] - ma["kgh_ven"]))
        if cambios_lineas:
            cambios_lineas.sort(key=lambda x: x[1])
            mejor_l = cambios_lineas[0]
            peor_l = cambios_lineas[-1]
            detalle_lineas_html = (
                f"<li><b>Línea con Mayor Mejora en el periodo:</b> <b>{mejor_l[0]}</b> ha pasado de {mejor_l[2]:.4f} €/kg a <b>{mejor_l[3]:.4f} €/kg</b> "
                f"({mejor_l[1]:+.4f} €/kg, variando su velocidad en {mejor_l[4]:+.1f} Kg/h).</li>"
                f"<li><b>Línea con Mayor Deterioro / Cuello de Botella:</b> <b>{peor_l[0]}</b> ha pasado de {peor_l[2]:.4f} €/kg a <b>{peor_l[3]:.4f} €/kg</b> "
                f"({peor_l[1]:+.4f} €/kg, variando su velocidad en {peor_l[4]:+.1f} Kg/h).</li>"
            )

    st.markdown(
        f"""
        <div class='exec-report'>
            <h4 style='margin-top:0; color:#0f172a;'>🧠 Informe de Inteligencia Artificial: Diagnóstico de {comp_scope} ({label_a} ➔ {label_b})</h4>
            <ul style='font-size:14px; line-height:1.7; color:#1e293b;'>
                <li><b>1. Diagnóstico Económico y Céntimos/Kg:</b> En <b>{label_b}</b>, el rendimiento de <b>{comp_scope}</b> ha <b>{estado_coste}</b>.
                El coste por kilo vendido ha pasado de <b>{met_a['eur_ven']:.4f} €/kg</b> en {label_a} a <b>{met_b['eur_ven']:.4f} €/kg</b> en {label_b} (<b>{pct_eur_ven:+.1f}%</b>).
                Para el volumen facturado en {label_b} ({met_b['kg_ven']:,.0f} kg), esta diferencia de eficiencia supone un impacto directo en nómina de
                <b style='color:{color_impacto};'>{impacto_euros_eficiencia:+,.0f} €</b> ({'ahorro neto generado' if impacto_euros_eficiencia >= 0 else 'sobrecoste absorbido'}).</li>
                <li><b>2. Ritmo de Línea y Conversión Comercial:</b> La velocidad bruta de línea (volcado/almacén) ha variado de <b>{met_a['kgh_mov']:.1f} Kg/h</b> a <b>{met_b['kgh_mov']:.1f} Kg/h</b> ({pct_kgh_mov:+.1f}%),
                mientras que la velocidad real de venta facturada ha pasado de <b>{met_a['kgh_ven']:.1f} Kg/h</b> a <b>{met_b['kgh_ven']:.1f} Kg/h</b> ({pct_kgh_ven:+.1f}%).
                El porcentaje de fruta movida que sale directamente a venta ha pasado del <b>{met_a['pct_conv']:.1f}%</b> al <b>{met_b['pct_conv']:.1f}%</b>
                ({'menos retrabajo/uso interno' if diff_conv >= 0 else 'mayor proporción de fruta enviada a repaso/uso interno'}).</li>
                <li><b>3. Estructura de Personal en Planta:</b> Las horas de soporte (Auxiliares, Responsables y Ordenador) han pasado de representar el <b>{met_a['pct_sup']:.1f}%</b>
                en {label_a} al <b>{met_b['pct_sup']:.1f}%</b> en {label_b} ({'mayor carga auxiliar no directa' if met_b['pct_sup'] > met_a['pct_sup'] else 'mejor aprovechamiento en envasado directo'}).</li>
                {detalle_lineas_html}
            </ul>
        </div>
        """,
        unsafe_allow_html=True,
    )


# =============================================================================
# PESTAÑA 3: CUELLOS DE BOTELLA A PIE DE PLANTA (RESPETANDO TOLERANCIA ±500 KG)
# =============================================================================
with tab_ai:
    st.markdown("#### 🧠 Diagnóstico IA a Pie de Planta — Puntos Débiles y Cuellos de Botella")
    st.caption(f"Analiza el periodo filtrado en la Pestaña 1. Los descuadres de báscula dentro del margen asumido de ±{int(tol_kg)} kg se ignoran automáticamente.")

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
                f"La línea ha invertido {h_tot:.1f} h para facturar {kg_v:,.0f} kg ({(kg_v/h_tot if h_tot>0 else 0):.1f} Kg/h frente a {t_obj['kghVen']:.1f} Kg/h objetivo).",
                f"Acción a pie de máquina: Verificar microparadas de alimentación o exceso de confección para stock interno (USOINT) en {l}.",
            ))
        if pct_sup > 42.0 and h_tot > 15.0:
            ai_cards.append((
                "ai-card-high",
                f"⚙️ Sobrecarga de Personal de Soporte en {l} ({pct_sup:.1f}% de las horas no son de Envasado)",
                f"De {h_tot:.1f} h totales en {l}, {h_sup:.1f} h corresponden a Auxiliar/Responsable/Ordenador y solo {h_env:.1f} h ({pct_env:.1f}%) a Envasado directo.",
                f"Acción a pie de máquina: Reequilibrar abastecimiento de cartón/paletizado en {l} y reubicar al menos 1 auxiliar en mesa de envasado.",
            ))
        # SOLO AVISA SI SUPERA LA TOLERANCIA ASUMIDA EN PLANTA (por defecto ±500 kg)
        if abs(give) > tol_kg:
            ai_cards.append((
                "ai-card-crit" if give > 0 else "ai-card-med",
                f"⚖️ Descuadre en Parte de {l} fuera de tolerancia (±{int(tol_kg)} kg): {give:+.0f} kg",
                f"La diferencia entre Neto Real ({kg_m:,.0f} kg) y Neto Teórico ({kg_t:,.0f} kg) supera el margen normal de planta.",
                f"Acción a pie de máquina: Revisar en la Pestaña 5 si hay una ficha de Peso Confección mal parametrizada en Fruttec para {l}.",
            ))
        if pct_ext > 45.0 and h_tot > 20.0:
            ai_cards.append((
                "ai-card-med",
                f"🔄 Alta Rotación de Operarios en {l} ({pct_ext:.0f}% de las horas cubiertas con personal de otras líneas)",
                f"{h_ext:.1f} h realizadas por trabajadores movidos desde otros grupos a mitad de turno.",
                f"Acción a pie de máquina: Fijar dotación titular de {l} a primera hora (07:50) para evitar pérdidas de ritmo en cambios de línea.",
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

    if sup_chart_data:
        df_sc = pd.DataFrame(sup_chart_data)
        b1, b2 = st.columns(2)
        with b1:
            fig_s = go.Figure()
            fig_s.add_trace(go.Bar(x=df_sc["Línea"], y=df_sc["% Envasado Directo"], name="% Envasado Directo", marker_color="#10b981"))
            fig_s.add_trace(go.Bar(x=df_sc["Línea"], y=df_sc["% Soporte (Aux/Resp/Ord)"], name="% Soporte Auxiliar", marker_color="#f59e0b"))
            fig_s.update_layout(title="Equilibrio Operativo: % Envasado vs % Soporte", barmode="stack", height=340, margin=dict(t=40, b=30, l=40, r=20))
            st.plotly_chart(fig_s, use_container_width=True)
        with b2:
            fig_m = go.Figure(go.Bar(x=df_sc["Línea"], y=df_sc["% Personal Prestado"], marker_color="#ef4444"))
            fig_m.update_layout(title="Índice de Trasvase: % Horas con Personal de Otras Líneas", height=340, margin=dict(t=40, b=30, l=40, r=20))
            st.plotly_chart(fig_m, use_container_width=True)


# =============================================================================
# PESTAÑA 4: MATRIZ DE UMBRALES OBJETIVOS
# =============================================================================
with tab_targ:
    st.markdown("#### 🎯 Matriz de Umbrales Objetivos por Línea Real (Histórico vs. Actual)")
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
        st.success("✅ Umbrales guardados.")
        st.rerun()


# =============================================================================
# PESTAÑA 5 (RESUMIDA Y EXPLICADA): CUADRE DE KILOS EN PARTES (TOLERANCIA ±500 KG)
# =============================================================================
with tab_quad:
    st.markdown(f"#### ⚖️ Resumen de Cuadre de Kilos en Partes de Producción (Tolerancia asumida: ±{int(tol_kg)} kg)")
    st.info(
        "💡 **¿Qué mide exactamente esta pestaña?** Compara los **Kilos Reales** pesados en báscula frente a los **Kilos Teóricos** de las cajas en el parte de producción. "
        f"Como en Natural Tropic asumís una variación normal de **±{int(tol_kg)} kg por línea**, todo lo que esté dentro de esa franja aparece en **🟢 VERDE (Normal)** y solo se destacan los desfases que superan los ±{int(tol_kg)} kg."
    )

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
