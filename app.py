import streamlit as st
import pandas as pd
import google.generativeai as genai
import os
import json
import tempfile
import io
import re

# --- Tu prompt completo para Gemini (defínelo solo una vez aquí) ---
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
      "BalanceGeneral": { ... },
      "EstadoResultados": { ... }
    }
    // Puede haber otro objeto para 2023
  ]
}
Responde únicamente con ese JSON.
"""

# --- Configuración de la API de Gemini ---
if "GOOGLE_API_KEY" in st.secrets:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
else:
    st.error("Error: falta tu clave GOOGLE_API_KEY en Streamlit Secrets.")
    st.stop()

genai.configure(api_key=GOOGLE_API_KEY)

# --- Estructura de Balance con sinónimos ---
BALANCE_SHEET_STRUCTURE = {
    "Activos Corrientes": [
        ("Inventarios", ["Inventarios", "Inventario Equipos"]),
        ("Efectivo y equivalentes de efectivo", ["Efectivo y equivalentes de efectivo", "Efectivo y depósitos", "Bancos", "Caja", "Fondo Fijo de Caja", "Caja y Bancos"]),
        ("Cuentas por cobrar", ["Cuentas por cobrar", "Clientes", "Deudores", "Cuentas por cobrar comerciales", "Cuentas por cobrar a empresas relacionadas CP", "Deudores diversos"]),
        ("Gasto Anticipado", ["Gasto Anticipado", "Gastos pagados por anticipado", "Pagos anticipados", "Impuestos a favor", "Pagos provisionales"]),
        ("Otros activos", ["Otros activos", "Otros activos corrientes", "Activos por Impuestos", "Activos financieros"]),
        ("Total Activo Corriente", ["Total Activo Corriente", "Total Activo a Corto Plazo", "TOTAL ACTIVO CIRCULANTE"])
    ],
    "Activos No Corrientes": [
        ("Propiedad, planta y equipo", ["Propiedad, planta y equipo", "Propiedad Planta y Equipo", "Activo Fijo", "Activo Fijo Neto"]),
        ("Intangibles (Software)", ["Intangibles (Software)", "Intangibles"]),
        ("Otros Activos No Corrientes", ["Otros Activos No Corrientes", "Activos diferidos", "Otros activos no corrientes", "Activos a largo plazo", "Depósitos en garantía"]),
        ("Total Activo No Corriente", ["Total Activo No Corriente", "Total Activo Fijo", "TOTAL ACTIVO NO CIRCULANTE"])
    ],
    "TOTAL ACTIVOS": [("TOTAL ACTIVOS", ["TOTAL ACTIVOS", "Total Activo", "SUMA DEL ACTIVO"])],
    "Pasivos a Corto Plazo": [
        ("Préstamos y empréstitos corrientes", ["Préstamos y empréstitos corrientes", "Préstamos bancarios a corto plazo"]),
        ("Obligaciones Financieras", ["Obligaciones Financieras", "Préstamos"]),
        ("Cuentas comerciales y otras cuentas por pagar", ["Cuentas comerciales y otras cuentas por pagar", "Acreedores diversos", "Proveedores"]),
        ("Pasivo Laborales", ["Pasivo Laborales", "Provisiones para sueldos y salarios", "Remuneraciones por pagar"]),
        ("Anticipos", ["Anticipos", "Anticipos de clientes"]),
        ("Impuestos Corrientes (Pasivo)", ["Impuestos Corrientes (Pasivo)", "Impuestos por pagar", "Pasivo por impuestos"]),
        ("Otros pasivos corrientes", ["Otros pasivos corrientes"]),
        ("Total Pasivo Corriente", ["Total Pasivo Corriente", "TOTAL PASIVO A CORTO PLAZO"])
    ],
    "Pasivos a Largo Plazo": [
        ("Préstamos y empréstitos no corrientes", ["Préstamos y empréstitos no corrientes", "Préstamos bancarios a largo plazo"]),
        ("Obligaciones Financieras No Corrientes", ["Obligaciones Financieras No Corrientes"]),
        ("Anticipos y Avances Recibidos", ["Anticipos y Avances Recibidos"]),
        ("Otros pasivos no corrientes", ["Otros pasivos no corrientes", "Ingresos diferidos"]),
        ("Total Pasivo No Corriente", ["Total Pasivo No Corriente", "TOTAL PASIVO A LARGO PLAZO"])
    ],
    "TOTAL PASIVOS": [("TOTAL PASIVOS", ["TOTAL PASIVOS", "Total Pasivo", "SUMA DEL PASIVO"])],
    "Patrimonio Atribuible a los Propietarios de la Matriz": [
        ("Capital social", ["Capital social", "Capital Emitido"]),
        ("Aportes Para Futuras Capitalizaciones", ["Aportes Para Futuras Capitalizaciones"]),
        ("Resultados Ejerc. Anteriores", ["Resultados Ejerc. Anteriores", "Ganancias retenidas"]),
        ("Resultado del Ejercicio", ["Resultado del Ejercicio", "Utilidad del período"]),
        ("Otros componentes del patrimonio", ["Otros componentes del patrimonio", "Otras reservas"]),
        ("Capital Variable", ["Capital Variable"]),  # <--- agregado
        ("TOTAL PATRIMONIO", ["TOTAL PATRIMONIO", "Total Patrimonio"])
    ],
    "TOTAL PASIVO Y PATRIMONIO": [("TOTAL PASIVO Y PATRIMONIO", ["TOTAL PASIVO Y PATRIMONIO"])]
}

# Lista de conceptos y diccionario de sinónimos
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
    "ingresos por ventas": "Ingresos por Ventas", "ventas netas": "Ingresos por Ventas",
    "costo de ventas": "Costo de Ventas", "ganancia bruta": "Ganancia Bruta",
    "gastos de operación": "Gastos de Operación", "ebitda": "Ganancia (Pérdida) de Operación",
    "gastos financieros": "Ingresos (Gastos) Financieros", "impuesto a la renta": "Impuesto a la Renta",
    "utilidad neta": "Ganancia (Pérdida) Neta"
}

# Tasas de cambio de ejemplo
EXCHANGE_RATES_BY_YEAR_TO_USD = {
    2025: {"EUR":1.09,"MXN":0.057,"PEN":0.27,"COP":0.00023,"CLP":0.00105,"USD":1.0},
    2024: {"EUR":1.085,"MXN":0.0482,"PEN":0.268,"COP":0.00024,"CLP":0.0011,"USD":1.0},
    2023: {"EUR":1.07,"MXN":0.059,"PEN":0.265,"COP":0.00026,"CLP":0.0012,"USD":1.0},
}

def get_exchange_rate(code, date=None):
    if code.upper()=="USD": return 1.0
    return EXCHANGE_RATES_BY_YEAR_TO_USD.get(date, {}).get(code.upper(), 1.0)

@st.cache_data(show_spinner=False)
def extract_financial_data(file_obj, api_key):
    model = genai.GenerativeModel('gemini-1.5-flash')
    name = file_obj.name
    data_out = {}
    st.write(f"Procesando archivo: {name}")

    # Guardar PDF temporalmente
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(file_obj.read())
        path = tmp.name

    try:
        part = genai.upload_file(path=path, display_name=name)
        prompt = PROMPT_EXTRACTION

        resp = model.generate_content([prompt, part], stream=False)
        st.write(">>> RESPUESTA GEMINI RAW:")
        st.text(resp.text)

        # Extraer JSON con regex
        m = re.search(r"(\{.*\})", resp.text, flags=re.DOTALL)
        if not m:
            st.error("No pude aislar un objeto JSON de la respuesta de Gemini.")
            return {}

        obj = json.loads(m.group(1))
        rpt_list = obj.get("ReportesPorAnio", [])
        for rpt in rpt_list:
            yr = rpt.get("Anio")
            if yr:
                key = f"{name}_{yr}"
                data_out[key] = {
                    "Moneda": obj.get("Moneda"),
                    "Unidad": obj.get("Unidad", "unidades"),
                    "AnioInforme": int(yr),
                    "BalanceGeneral": rpt.get("BalanceGeneral", {}),
                    "EstadoResultados": rpt.get("EstadoResultados", {})
                }

        st.write(f"extract_financial_data para {name} devolvió: {list(data_out.keys())}")
    except Exception as e:
        st.error(f"Error al procesar {name}: {e}")
    finally:
        if os.path.exists(path): os.remove(path)
        if 'part' in locals(): genai.delete_file(part.name)

    return data_out

def apply_scale_factor_to_raw_data(data, unit):
    factor = 1
    ul = unit.lower()
    if "millones" in ul or "$m" in ul: factor = 1_000_000
    if "miles" in ul: factor = 1_000
    if not isinstance(data, dict): return data
    out = {}
    for k,v in data.items():
        if isinstance(v, dict):
            out[k] = apply_scale_factor_to_raw_data(v, unit)
        elif isinstance(v, (int,float)):
            out[k] = v * factor
        else:
            out[k] = v
    return out

def map_and_aggregate_balance(raw, syn_map, unit):
    # inicializar todo en 0
    agg = {c:0.0 for c in BALANCE_SHEET_STANDARD_CONCEPTS_LIST}
    scaled = apply_scale_factor_to_raw_data(raw, unit)
    # recorre secciones y cuentas...
    for sec, content in scaled.items():
        if isinstance(content, dict):
            for sub, subcont in content.items():
                if isinstance(subcont, dict):
                    for acct, val in subcont.items():
                        m = syn_map.get(acct.lower())
                        if m in agg: agg[m] += val
                elif isinstance(subcont, (int,float)):
                    m = syn_map.get(sub.lower())
                    if m in agg: agg[m] = subcont
        elif isinstance(content, (int,float)):
            m = syn_map.get(sec.lower())
            if m in agg: agg[m] = content
    return agg

def map_and_aggregate_pnl(raw, syn_map, unit):
    agg = {c:0.0 for c in PNL_STANDARD_CONCEPTS}
    scaled = apply_scale_factor_to_raw_data(raw, unit)
    for sec, cont in scaled.items():
        if isinstance(cont, dict):
            for acct, val in cont.items():
                m = syn_map.get(acct.lower())
                if m in agg: agg[m] += val
        elif isinstance(cont, (int,float)):
            m = syn_map.get(sec.lower())
            if m in agg: agg[m] = cont
    return agg

def convert_to_usd(data_dict, currency, year):
    rate = get_exchange_rate(currency, year)
    out = {}
    for k,v in data_dict.items():
        if isinstance(v,(int,float)):
            out[k] = v * rate
        elif isinstance(v, dict):
            out[k] = convert_to_usd(v, currency, year)
        else:
            out[k] = v
    st.write(f"DEBUG: Conversión {currency} {year} → {rate}")
    return out

# --- Streamlit App ---
st.set_page_config(layout="wide")
st.title("Bot de Análisis de Estados Financieros con Gemini")

uploaded = st.file_uploader("Sube tus PDFs (máx. 4)", type="pdf", accept_multiple_files=True)
if not uploaded:
    st.info("Sube tus archivos y haz clic en 'Procesar y Convertir a USD'.")
    st.stop()

if st.button("Procesar y Convertir a USD"):
    all_results = {}
    with st.spinner("Extrayendo datos..."):
        for f in uploaded:
            res = extract_financial_data(f, GOOGLE_API_KEY)
            all_results.update(res)

    if not all_results:
        st.error("No se pudieron extraer datos de ninguno de los PDFs.")
        st.stop()

    # Agregar mapeo, agregación y conversión:
    final_display = {}
    for key, info in all_results.items():
        name, yr = key.rsplit("_",1)
        yr = int(yr)
        cur = info["Moneda"].upper()
        unit = info.get("Unidad","unidades")
        bg_raw = info["BalanceGeneral"]
        er_raw = info["EstadoResultados"]
        agg_bg = map_and_aggregate_balance(bg_raw, BALANCE_SHEET_SYNONYMS, unit)
        agg_er = map_and_aggregate_pnl(er_raw, PNL_SYNONYMS, unit)
        bg_usd = convert_to_usd(agg_bg, cur, yr)
        er_usd = convert_to_usd(agg_er, cur, yr)
        final_display.setdefault(name, {})[yr] = {
            "BalanceGeneralUSD": bg_usd,
            "EstadoResultadosUSD": er_usd
        }

    st.success("¡Datos extraídos y convertidos a USD con éxito!")

    # Prepara índices
    balance_index = []
    for cat, items in BALANCE_SHEET_STRUCTURE.items():
        balance_index.append(cat)
        for std, _ in items:
            balance_index.append(f"    {std}")

    df_bg = pd.DataFrame(index=balance_index)
    df_pnl = pd.DataFrame(index=PNL_STANDARD_CONCEPTS)

    # Poblar columnas
    for name, years in final_display.items():
        for yr, data in sorted(years.items()):
            col = f"{name} ({yr})"
            # BG
            series_bg = pd.Series(index=balance_index, dtype="object")
            for idx in balance_index:
                n = idx.strip()
                val = data["BalanceGeneralUSD"].get(n)
                series_bg[idx] = f"{val:,.2f}" if isinstance(val,(int,float)) else ""
            df_bg[col] = series_bg
            # PnL
            series_er = pd.Series(index=PNL_STANDARD_CONCEPTS, dtype="object")
            for n in PNL_STANDARD_CONCEPTS:
                val = data["EstadoResultadosUSD"].get(n)
                series_er[n] = f"{val:,.2f}" if isinstance(val,(int,float)) else ""
            df_pnl[col] = series_er

    st.subheader("Balance General (USD)")
    st.dataframe(df_bg)
    st.subheader("Estado de Pérdidas y Ganancias (USD)")
    st.dataframe(df_pnl)

    # Descargar a Excel
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        df_bg.to_excel(writer, sheet_name="BalanceGeneral_USD")
        df_pnl.to_excel(writer, sheet_name="EstadoResultados_USD")
    buf.seek(0)
    st.download_button(
        "Descargar Estados Financieros en Excel",
        data=buf,
        file_name="EstadosFinancieros_USD.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
