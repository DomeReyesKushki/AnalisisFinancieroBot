import streamlit as st
import pandas as pd
import google.generativeai as genai
import os, json, tempfile, io, re

# --- Tu prompt completo para Gemini ---
PROMPT_EXTRACTION = """
Analiza cuidadosamente el siguiente documento PDF que contiene estados financieros.

**Objetivo Principal:** Extraer los datos financieros del Balance General y del Estado de Pérdidas y Ganancias para CADA COLUMNA de DICIEMBRE (ej. "DICIEMBRE 2024", "DICIEMBRE 2023") que encuentres en el documento. Si no hay columnas de DICIEMBRE, extrae los datos para las ÚLTIMAS 2 COLUMNAS de fecha disponibles.

**Paso 1: Identificación de Moneda y Años.**
- **Moneda Global:** Código ISO (USD, EUR, MXN, COP, CLP, PEN). Infierelo por país si no aparece.
- **Unidad (Escala):** "millones", "miles", etc.
- **Años de Reporte:** Busca columnas de DICIEMBRE o las dos últimas fechas.

**Paso 2: Extracción exacta de cuentas y valores.**
- Valores numéricos tal cual aparecen (sin multiplicar por la escala).
- Nombres exactos de las cuentas.

**Formato de salida (solo JSON):**
{
  "Moneda": "MXN",
  "ReportesPorAnio": [
    {
      "Anio": "2024",
      "BalanceGeneral": { … },
      "EstadoResultados": { … }
    }
  ]
}
Responde únicamente con ese JSON.
"""

# --- Configuración de la API de Gemini ---
if "GOOGLE_API_KEY" not in st.secrets:
    st.error("Error: falta la clave GOOGLE_API_KEY en Streamlit Secrets.")
    st.stop()
genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])

# --- Estructura de Balance con sinónimos ---
BALANCE_SHEET_STRUCTURE = {
    "Activos Corrientes": [
        ("Inventarios", ["inventarios", "inventario equipos"]),
        ("Efectivo y equivalentes de efectivo", ["efectivo y equivalentes de efectivo", "bancos", "caja", "fondo fijo de caja", "caja y bancos"]),
        ("Cuentas por cobrar", ["cuentas por cobrar", "clientes", "deudores diversos"]),
        ("Gasto Anticipado", ["impuestos a favor", "pagos provisionales"]),
        ("Otros activos", ["otros activos", "activos financieros"])
    ],
    "Pasivos a Corto Plazo": [
        ("Cuentas por Pagar", ["proveedores", "acreedores diversos"]),
        ("Impuestos Corrientes (Pasivo)", ["impuestos y derechos por pagar"])
    ],
    "Patrimonio Atribuible a los Propietarios de la Matriz": [
        ("Capital social", ["capital social"]),
        ("Capital Variable", ["capital variable"]),
        ("Resultados Ejerc. Anteriores", ["resultado de ejercicios anteriores"]),
        ("Resultado del Ejercicio", ["resultado del ejercicio"])
    ]
}

# Construcción de lista de conceptos y diccionario de sinónimos
BALANCE_SHEET_STANDARD_CONCEPTS_LIST = []
BALANCE_SHEET_SYNONYMS = {}
for cat, items in BALANCE_SHEET_STRUCTURE.items():
    BALANCE_SHEET_STANDARD_CONCEPTS_LIST.append(cat)
    for std, syns in items:
        BALANCE_SHEET_STANDARD_CONCEPTS_LIST.append(f"    {std}")
        for s in syns:
            BALANCE_SHEET_SYNONYMS[s.lower()] = std

PNL_STANDARD_CONCEPTS = [
    "Ingresos por Ventas", "Costo de Ventas", "Ganancia Bruta",
    "Gastos de Operación", "Ganancia (Pérdida) de Operación",
    "Ingresos (Gastos) Financieros", "Impuesto a la Renta", "Ganancia (Pérdida) Neta"
]
PNL_SYNONYMS = {
    "ingresos": "Ingresos por Ventas",
    "utilidad bruta": "Ganancia Bruta",
    "gastos generales": "Gastos de Operación",
    "utilidad de operación": "Ganancia (Pérdida) de Operación",
    "resultado del ejercicio": "Resultado del Ejercicio"
}

# Tasas de cambio de ejemplo
EXCHANGE_RATES_BY_YEAR_TO_USD = {
    2024: {"MXN": 0.0482, "USD": 1.0},
    2025: {"MXN": 0.0570, "USD": 1.0}
}

def get_exchange_rate(code, year):
    code = code.upper()
    return 1.0 if code == "USD" else EXCHANGE_RATES_BY_YEAR_TO_USD.get(year, {}).get(code, 1.0)

def normalize_numeric(v):
    if isinstance(v, str):
        v = v.replace(",", "")
        try:
            return float(v)
        except:
            return None
    return v

@st.cache_data(show_spinner=False)
def extract_financial_data(file_obj):
    name = file_obj.name
    st.write(f"Procesando archivo: {name}")
    # Guardar PDF en temp
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(file_obj.read())
        path = tmp.name

    out = {}
    try:
        part = genai.upload_file(path=path, display_name=name)
        resp = genai.GenerativeModel("gemini-1.5-flash") \
                    .generate_content([PROMPT_EXTRACTION, part], stream=False)
        st.write(">>> RESPUESTA GEMINI RAW:")
        st.text(resp.text)

        m = re.search(r"(\{.*\})", resp.text, flags=re.DOTALL)
        if not m:
            st.error("No pude aislar un JSON válido de Gemini.")
            return {}
        obj = json.loads(m.group(1))

        for rpt in obj.get("ReportesPorAnio", []):
            yr = int(rpt.get("Anio", 0))
            key = f"{name}_{yr}"
            bg_raw = {k: normalize_numeric(v) for k, v in rpt.get("BalanceGeneral", {}).items()}
            er_raw = {k: normalize_numeric(v) for k, v in rpt.get("EstadoResultados", {}).items()}
            out[key] = {
                "Moneda": obj.get("Moneda", "USD"),
                "BalanceGeneral": bg_raw,
                "EstadoResultados": er_raw,
                "Año": yr
            }
    finally:
        os.remove(path)
        if 'part' in locals():
            genai.delete_file(part.name)

    return out

def map_and_aggregate_balance(bg):
    agg = {c: 0.0 for c in BALANCE_SHEET_STANDARD_CONCEPTS_LIST}
    def recurse(d):
        for k, v in d.items():
            if isinstance(v, dict):
                recurse(v)
            elif isinstance(v, (int, float)):
                std = BALANCE_SHEET_SYNONYMS.get(k.lower())
                if std in agg:
                    agg[std] += v
    recurse(bg)
    return agg

def map_and_aggregate_pnl(er):
    agg = {c: 0.0 for c in PNL_STANDARD_CONCEPTS}
    def recurse(d):
        for k, v in d.items():
            if isinstance(v, dict):
                recurse(v)
            elif isinstance(v, (int, float)):
                std = PNL_SYNONYMS.get(k.lower())
                if std in agg:
                    agg[std] += v
    recurse(er)
    return agg

def convert_to_usd(d, rate):
    return {k: (v * rate if isinstance(v, (int, float)) else v) for k, v in d.items()}

# --- Streamlit App ---
st.set_page_config(layout="wide")
st.title("Bot de Análisis de Estados Financieros → USD")

files = st.file_uploader("Sube tus PDFs (máx. 4)", type="pdf", accept_multiple_files=True)
if files and st.button("Procesar y Convertir a USD"):
    all_data = {}
    for f in files:
        all_data.update(extract_financial_data(f))

    if not all_data:
        st.error("No se extrajeron datos de los PDFs.")
        st.stop()

    # Prepara DataFrames
    bg_idx = BALANCE_SHEET_STANDARD_CONCEPTS_LIST
    pnl_idx = PNL_STANDARD_CONCEPTS
    df_bg = pd.DataFrame(index=bg_idx)
    df_pnl = pd.DataFrame(index=pnl_idx)

    # Rellenar
    for key, info in all_data.items():
        name, yr = key.rsplit("_", 1)
        yr = int(yr)
        rate = get_exchange_rate(info["Moneda"], yr)

        bg_agg = map_and_aggregate_balance(info["BalanceGeneral"])
        bg_usd = convert_to_usd(bg_agg, rate)

        er_agg = map_and_aggregate_pnl(info["EstadoResultados"])
        er_usd = convert_to_usd(er_agg, rate)

        col = f"{name} ({yr})"
        df_bg[col] = [f"{bg_usd.get(c, 0):,.2f}" for c in bg_idx]
        df_pnl[col] = [f"{er_usd.get(c, 0):,.2f}" for c in pnl_idx]

    st.subheader("Balance General (USD)")
    st.dataframe(df_bg)
    st.subheader("Estado de Pérdidas y Ganancias (USD)")
    st.dataframe(df_pnl)

    # Descargar Excel
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        df_bg.to_excel(writer, sheet_name="BalanceGeneral_USD")
        df_pnl.to_excel(writer, sheet_name="EstadoResultados_USD")
    buffer.seek(0)
    st.download_button(
        "Descargar Estados Financieros en Excel",
        data=buffer,
        file_name="EstadosFinancieros_USD.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
