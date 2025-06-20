import streamlit as st
import pandas as pd
import google.generativeai as genai
import os
import json
import tempfile
import io
import re

# --- Tu prompt de extracción ---
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
  "Moneda": "COP",
  "ReportesPorAnio": [
    {
      "Anio": "2024",
      "BalanceGeneral": { … },
      "EstadoResultados": { … }
    }
    // Puede haber otro objeto para 2023
  ]
}
Responde únicamente con ese JSON.
"""

# --- Configuración de Gemini ---
if "GOOGLE_API_KEY" in st.secrets:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
else:
    st.error("Falta la clave GOOGLE_API_KEY en Streamlit Secrets.")
    st.stop()

# --- Estructura y sinónimos ---
BALANCE_SHEET_STRUCTURE = {
    "Activos Corrientes": [
        ("Inventarios", ["Inventarios", "Inventario Equipos"]),
        ("Efectivo y equivalentes de efectivo", ["Efectivo y equivalentes de efectivo", "Caja y Bancos", "Bancos", "Fondo Fijo de Caja"]),
        ("Cuentas por cobrar", ["Cuentas por cobrar", "Clientes", "Deudores diversos"]),
        ("Gasto Anticipado", ["Impuestos a favor", "Pagos provisionales"]),
        ("Otros activos", ["Otros activos", "Activos financieros"])
    ],
    "Pasivos a Corto Plazo": [
        ("Cuentas por Pagar", ["Proveedores", "Acreedores diversos"]),
        ("Impuestos Corrientes (Pasivo)", ["Impuestos y derechos por pagar"]),
    ],
    "Patrimonio Atribuible a los Propietarios de la Matriz": [
        ("Capital social", ["CAPITAL SOCIAL"]),
        ("Capital Variable", ["CAPITAL VARIABLE"]),
        ("Resultados Ejerc. Anteriores", ["RESULTADO DE EJERCICIOS ANTERIORES"]),
        ("Resultado del Ejercicio", ["RESULTADO DEL EJERCICIO"])
    ]
}

# Generamos listas planas
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

# Tasas de cambio
EXCHANGE_RATES_BY_YEAR_TO_USD = {
    2024: {"MXN": 0.0482, "USD": 1.0},
    # ...
}

def get_exchange_rate(code, year):
    if code.upper() == "USD": return 1.0
    return EXCHANGE_RATES_BY_YEAR_TO_USD.get(year, {}).get(code.upper(), 1.0)

def normalize_numeric_strings(obj):
    """ Recorre dicts anidados y convierte cadenas numéricas con comas a float. """
    if isinstance(obj, dict):
        return {k: normalize_numeric_strings(v) for k, v in obj.items()}
    if isinstance(obj, str):
        s = obj.replace(",", "")
        try:
            return float(s)
        except:
            return None
    return obj

@st.cache_data
def extract_financial_data(file_obj):
    name = file_obj.name
    st.write(f"Procesando {name}...")

    # Guardar PDF
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(file_obj.read())
        path = tmp.name

    data_out = {}
    try:
        part = genai.upload_file(path=path, display_name=name)
        resp = genai.GenerativeModel("gemini-1.5-flash").generate_content([PROMPT_EXTRACTION, part], stream=False)

        # Debug raw
        st.write(">>> RESPUESTA GEMINI RAW:")
        st.text(resp.text)

        # Extraer JSON
        m = re.search(r"(\{.*\})", resp.text, flags=re.DOTALL)
        if not m:
            st.error("No pude aislar un JSON válido.")
            return {}
        obj = json.loads(m.group(1))

        for rpt in obj.get("ReportesPorAnio", []):
            yr = int(rpt.get("Anio", 0))
            key = f"{name}_{yr}"
            bg = normalize_numeric_strings(rpt.get("BalanceGeneral", {}))
            er = normalize_numeric_strings(rpt.get("EstadoResultados", {}))
            data_out[key] = {
                "Moneda": obj.get("Moneda", "USD"),
                "BalanceGeneral": bg,
                "EstadoResultados": er,
                "Año": yr
            }
    finally:
        os.remove(path)
        if 'part' in locals(): genai.delete_file(part.name)

    return data_out

def map_and_aggregate_balance(bg_dict):
    agg = {c: 0.0 for c in BALANCE_SHEET_STANDARD_CONCEPTS_LIST}
    # Si bg_dict es plano, simplemente iteramos las cuentas:
    for acct, val in bg_dict.items():
        std = BALANCE_SHEET_SYNONYMS.get(acct.lower())
        if std and isinstance(val, (int, float)):
            agg[std] += val
    return agg

def map_and_aggregate_pnl(er_dict):
    agg = {c: 0.0 for c in PNL_STANDARD_CONCEPTS}
    for acct, val in er_dict.items():
        std = PNL_SYNONYMS.get(acct.lower())
        if std and isinstance(val, (int, float)):
            agg[std] += val
    return agg

def convert_dict_to_usd(d, rate):
    return {k: v * rate if isinstance(v, (int, float)) else v for k, v in d.items()}

# --- App ---
st.title("Estados Financieros → USD")

files = st.file_uploader("Sube hasta 4 PDFs", type="pdf", accept_multiple_files=True)
if files and st.button("Procesar"):
    results = {}
    for f in files:
        results.update(extract_financial_data(f))

    if not results:
        st.error("No se extrajeron datos.")
        st.stop()

    # Armar DataFrames
    bg_index = BALANCE_SHEET_STANDARD_CONCEPTS_LIST
    pnl_index = PNL_STANDARD_CONCEPTS
    df_bg = pd.DataFrame(index=bg_index)
    df_pnl = pd.DataFrame(index=pnl_index)

    for key, info in results.items():
        name, yr = key.rsplit("_", 1)
        yr = int(yr)
        rate = get_exchange_rate(info["Moneda"], yr)

        agg_bg = map_and_aggregate_balance(info["BalanceGeneral"])
        usd_bg = convert_dict_to_usd(agg_bg, rate)

        agg_er = map_and_aggregate_pnl(info["EstadoResultados"])
        usd_er = convert_dict_to_usd(agg_er, rate)

        col = f"{name} ({yr})"
        df_bg[col] = [f"{usd_bg.get(c, 0):,.2f}" for c in bg_index]
        df_pnl[col] = [f"{usd_er.get(c, 0):,.2f}" for c in pnl_index]

    st.subheader("Balance General (USD)")
    st.dataframe(df_bg)
    st.subheader("Estado de Resultados (USD)")
    st.dataframe(df_pnl)

    # Descargar
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
        df_bg.to_excel(w, sheet_name="BG_USD")
        df_pnl.to_excel(w, sheet_name="ER_USD")
    buf.seek(0)
    st.download_button("Descargar Excel", data=buf, file_name="EF_USD.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
