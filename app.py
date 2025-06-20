import streamlit as st
import pandas as pd
import google.generativeai as genai
import os
import json
import tempfile
import io
import re

# --- Prompt para Gemini ---
PROMPT_EXTRACTION = """…"""  # (tu prompt completo aquí)

# Configuración Gemini
if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
else:
    st.error("Falta la clave GOOGLE_API_KEY en Secrets.")
    st.stop()

# Estructuras y sinónimos (igual que antes, incluyendo "Capital Variable")
BALANCE_SHEET_STRUCTURE = { … }
BALANCE_SHEET_STANDARD_CONCEPTS_LIST = []
BALANCE_SHEET_SYNONYMS = {}
for cat, items in BALANCE_SHEET_STRUCTURE.items():
    BALANCE_SHEET_STANDARD_CONCEPTS_LIST.append(cat)
    for std, syns in items:
        BALANCE_SHEET_STANDARD_CONCEPTS_LIST.append(f"    {std}")
        for s in syns:
            BALANCE_SHEET_SYNONYMS[s.lower()] = std

PNL_STANDARD_CONCEPTS = [ … ]
PNL_SYNONYMS = { … }

EXCHANGE_RATES_BY_YEAR_TO_USD = {
    2024: {"MXN":0.0482,"USD":1.0},
    # …
}

def get_exchange_rate(code, year):
    return 1.0 if code.upper()=="USD" else EXCHANGE_RATES_BY_YEAR_TO_USD.get(year,{}).get(code.upper(),1.0)

def normalize_numeric_strings(obj):
    if isinstance(obj, dict):
        return {k: normalize_numeric_strings(v) for k,v in obj.items()}
    if isinstance(obj, str):
        s = obj.replace(",","")
        try: return float(s)
        except: return None
    return obj

@st.cache_data
def extract_financial_data(file_obj):
    name = file_obj.name
    st.write(f"Procesando {name}")
    # guarda PDF
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(file_obj.read()); path=tmp.name
    out = {}
    try:
        part = genai.upload_file(path=path, display_name=name)
        resp = genai.GenerativeModel("gemini-1.5-flash")\
                   .generate_content([PROMPT_EXTRACTION, part], stream=False)
        st.text(resp.text)  # debug
        m = re.search(r"(\{.*\})", resp.text, flags=re.DOTALL)
        if not m: return {}
        obj = json.loads(m.group(1))
        for rpt in obj.get("ReportesPorAnio",[]):
            yr = int(rpt.get("Anio",0))
            key = f"{name}_{yr}"
            bg = normalize_numeric_strings(rpt.get("BalanceGeneral",{}))
            er = normalize_numeric_strings(rpt.get("EstadoResultados",{}))
            out[key] = {"Moneda":obj.get("Moneda","USD"),
                        "BalanceGeneral":bg,
                        "EstadoResultados":er,
                        "Año":yr}
    finally:
        os.remove(path)
        if 'part' in locals(): genai.delete_file(part.name)
    return out

def map_and_aggregate_balance(bg_dict):
    agg = {c:0.0 for c in BALANCE_SHEET_STANDARD_CONCEPTS_LIST}
    for acct, val in bg_dict.items():
        std = BALANCE_SHEET_SYNONYMS.get(acct.lower())
        if std in agg and isinstance(val,(int,float)):
            agg[std] += val
    return agg

def map_and_aggregate_pnl(er_dict):
    agg = {c:0.0 for c in PNL_STANDARD_CONCEPTS}
    for acct, val in er_dict.items():
        std = PNL_SYNONYMS.get(acct.lower())
        if std in agg and isinstance(val,(int,float)):
            agg[std] += val
    return agg

def convert_to_usd(d, rate):
    return {k:(v*rate if isinstance(v,(int,float)) else v) for k,v in d.items()}

# Streamlit UI
st.title("Estados Financieros → USD")
files = st.file_uploader("Sube hasta 4 PDFs", type="pdf", accept_multiple_files=True)
if files and st.button("Procesar"):
    results = {}
    for f in files:
        results.update(extract_financial_data(f))
    if not results:
        st.error("No se extrajeron datos."); st.stop()

    # construye DataFrames
    bg_idx = BALANCE_SHEET_STANDARD_CONCEPTS_LIST
    pnl_idx = PNL_STANDARD_CONCEPTS
    df_bg = pd.DataFrame(index=bg_idx)
    df_pnl = pd.DataFrame(index=pnl_idx)

    for key,info in results.items():
        name, yr = key.rsplit("_",1); yr=int(yr)
        rate = get_exchange_rate(info["Moneda"], yr)
        usd_bg = convert_to_usd(map_and_aggregate_balance(info["BalanceGeneral"]), rate)
        usd_er = convert_to_usd(map_and_aggregate_pnl(info["EstadoResultados"]), rate)
        col = f"{name} ({yr})"
        df_bg[col] = [f"{usd_bg.get(c,0):,.2f}" for c in bg_idx]
        df_pnl[col]= [f"{usd_er.get(c,0):,.2f}" for c in pnl_idx]

    st.subheader("Balance General (USD)")
    st.dataframe(df_bg)
    st.subheader("Estado de Resultados (USD)")
    st.dataframe(df_pnl)

    # descarga Excel
    buf=io.BytesIO()
    with pd.ExcelWriter(buf,engine="xlsxwriter") as w:
        df_bg.to_excel(w,sheet_name="BG_USD")
        df_pnl.to_excel(w,sheet_name="ER_USD")
    buf.seek(0)
    st.download_button("Descargar Excel",buf,"EF_USD.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
