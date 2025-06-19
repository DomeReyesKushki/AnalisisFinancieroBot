import streamlit as st
import pandas as pd
import google.generativeai as genai
import os
import json
import tempfile
import io

# --- Tu prompt completo para Gemini (defínelo aquí una vez) ---
PROMPT_EXTRACTION = """
Analiza cuidadosamente el siguiente documento PDF que contiene estados financieros.

**Objetivo Principal:** Extraer los datos financieros del Balance General y del Estado de Pérdidas y Ganancias para CADA COLUMNA de DICIEMBRE (ej. "DICIEMBRE 2024", "DICIEMBRE 2023") que encuentres en el documento. Si no hay columnas de DICIEMBRE, entonces extrae los datos para las ÚLTIMAS 2 COLUMNAS de fecha disponibles.

**Paso 1: Identificación de Moneda y Años de Reporte.**
-   **Moneda Global:** Identifica el código ISO (USD, EUR, MXN, COP, CLP, PEN). Si no aparece explícita, infiere por país.
-   **Unidad Global (Escala):** Si dice "millones", "miles", etc.
-   **Años de Reporte:** Busca columnas de DICIEMBRE o las dos últimas fechas.

**Paso 2: Extracción de Valores y Nombres de Cuentas.**
- Devuelve los números **tal cual** aparecen (sin multiplicar por la escala).
- Extrae los nombres EXACTOS de las cuentas.

**Formato de Salida (solo JSON):**
{
  "Moneda": "COP",
  "ReportesPorAnio": [
    {
      "Anio": "2024",
      "BalanceGeneral": { ... },
      "EstadoResultados": { ... }
    },
    { ... }
  ]
}
Responde **ÚNICAMENTE** con ese objeto JSON.
"""

# --- Configuración de la API de Gemini ---
if "GOOGLE_API_KEY" in st.secrets:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
else:
    st.error("Error: no se encontró tu clave GOOGLE_API_KEY en Streamlit Secrets.")
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
        ("Total Activo Corriente", ["Total Activo Corriente", "Total Activo a Corto Plazo", "Total Activo Corriente Netos", "TOTAL ACTIVO CIRCULANTE"])
    ],
    "Activos No Corrientes": [
        ("Propiedad, planta y equipo", ["Propiedad, planta y equipo", "Propiedad Planta y Equipo", "Activo Fijo", "Activo Fijo Neto"]),
        ("Intangibles (Software)", ["Intangibles (Software)", "Intangibles"]),
        ("Otros Activos No Corrientes", ["Otros Activos No Corrientes", "Activos diferidos", "Otros activos no corrientes", "Activos a largo plazo", "Depósitos en garantía"]),
        ("Total Activo No Corriente", ["Total Activo No Corriente", "Total Activo Fijo", "Total Activo a largo plazo", "TOTAL ACTIVO NO CIRCULANTE"])
    ],
    "TOTAL ACTIVOS": [("TOTAL ACTIVOS", ["TOTAL ACTIVOS", "Total Activo", "SUMA DEL ACTIVO"])],
    "Pasivos a Corto Plazo": [
        ("Préstamos y empréstitos corrientes", ["Préstamos y empréstitos corrientes", "Préstamos bancarios a corto plazo"]),
        ("Obligaciones Financieras", ["Obligaciones Financieras", "Préstamos"]),
        ("Cuentas comerciales y otras cuentas por pagar", ["Cuentas comerciales y otras cuentas por pagar", "Acreedores diversos", "Proveedores"]),
        ("Cuentas por Pagar", ["Cuentas por Pagar", "Proveedores"]),
        ("Pasivo Laborales", ["Pasivo Laborales", "Provisiones para sueldos y salarios", "Remuneraciones por pagar", "Provisión de sueldos y salarios x pagar", "Provisión de contribuciones segsocial x pagar"]),
        ("Anticipos", ["Anticipos", "Anticipos de clientes"]),
        ("Impuestos Corrientes (Pasivo)", ["Impuestos Corrientes (Pasivo)", "Impuestos por pagar", "Pasivo por impuestos", "Impuestos trasladados cobrados", "Impuestos trasladados no cobrados", "Impuestos y derechos por pagar"]),
        ("Otros pasivos corrientes", ["Otros pasivos corrientes"]),
        ("Total Pasivo Corriente", ["Total Pasivo Corriente", "Total Pasivo a Corto Plazo", "TOTAL PASIVO A CORTO PLAZO"])
    ],
    "Pasivos a Largo Plazo": [
        ("Préstamos y empréstitos no corrientes", ["Préstamos y empréstitos no corrientes", "Préstamos bancarios a largo plazo"]),
        ("Obligaciones Financieras No Corrientes", ["Obligaciones Financieras No Corrientes", "Obligaciones Financieras"]),
        ("Anticipos y Avances Recibidos", ["Anticipos y Avances Recibidos", "Depósitos en garantía"]),
        ("Otros pasivos no corrientes", ["Otros pasivos no corrientes", "Ingresos diferidos"]),
        ("Total Pasivo No Corriente", ["Total Pasivo No Corriente", "Total Pasivo a largo plazo", "TOTAL PASIVO A LARGO PLAZO"])
    ],
    "TOTAL PASIVOS": [("TOTAL PASIVOS", ["TOTAL PASIVOS", "Total Pasivo", "SUMA DEL PASIVO"])],
    "Patrimonio Atribuible a los Propietarios de la Matriz": [
        ("Capital social", ["Capital social", "Capital Emitido", "Capital Social"]),
        ("Aportes Para Futuras Capitalizaciones", ["Aportes Para Futuras Capitalizaciones"]),
        ("Resultados Ejerc. Anteriores", ["Resultados Ejerc. Anteriores", "Ganancias retenidas", "Resultado de Ejercicios Anteriores"]),
        ("Resultado del Ejercicio", ["Resultado del Ejercicio", "Utilidad del período", "Utilidad o Pérdida del Ejercicio"]),
        ("Otros componentes del patrimonio", ["Otros componentes del patrimonio", "Otras reservas", "Patrimonio Minoritario", "Impuestos retenidos"]),
        # Aquí incluimos Capital Variable para evitar warnings
        ("Capital Variable", ["Capital Variable"]),
        ("TOTAL PATRIMONIO", ["TOTAL PATRIMONIO", "Total Patrimonio", "SUMA DEL CAPITAL", "TOTAL CAPITAL"])
    ],
    "TOTAL PASIVO Y PATRIMONIO": [("TOTAL PASIVO Y PATRIMONIO", ["TOTAL PASIVO Y PATRIMONIO", "Total Pasivo y Patrimonio", "SUMA DEL PASIVO Y CAPITAL"])]
}

# Lista de conceptos estándar
BALANCE_SHEET_STANDARD_CONCEPTS_LIST = []
for cat, items in BALANCE_SHEET_STRUCTURE.items():
    BALANCE_SHEET_STANDARD_CONCEPTS_LIST.append(cat)
    for name, _ in items:
        BALANCE_SHEET_STANDARD_CONCEPTS_LIST.append(f"    {name}")

# Diccionario de sinónimos
BALANCE_SHEET_SYNONYMS = {}
for items in BALANCE_SHEET_STRUCTURE.values():
    for standard, syns in items:
        for s in syns:
            BALANCE_SHEET_SYNONYMS[s.lower()] = standard

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

def get_exchange_rate(currency, date=None):
    if currency.upper() == "USD":
        return 1.0
    rates = EXCHANGE_RATES_BY_YEAR_TO_USD.get(date, {})
    return rates.get(currency.upper(), 1.0)

@st.cache_data(show_spinner=False)
def extract_financial_data(file_obj, api_key):
    model = genai.GenerativeModel('gemini-1.5-flash')
    name = file_obj.name
    bytes_ = file_obj.read()
    st.write(f"Procesando archivo: {name}")

    # guardamos PDF temporalmente
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(bytes_)
        path = tmp.name

    data_out = {}
    try:
        part = genai.upload_file(path=path, display_name=name)
        # aquí sí definimos prompt
        prompt = PROMPT_EXTRACTION
        resp = model.generate_content([prompt, part], stream=False)
        st.code(resp.text, language='json')

        # parse JSON
        text = resp.text
        start = text.find('{')
        end   = text.rfind('}') + 1
        if start>=0 and end>start:
            obj = json.loads(text[start:end])
            for rpt in obj.get("ReportesPorAnio", []):
                yr = rpt.get("Anio")
                key = f"{name}_{yr}"
                data_out[key] = {
                    "Moneda": obj.get("Moneda"),
                    "AnioInforme": yr,
                    "BalanceGeneral": rpt.get("BalanceGeneral", {}),
                    "EstadoResultados": rpt.get("EstadoResultados", {})
                }
        else:
            st.error(f"No se encontró JSON válido en Gemini para {name}")
    except Exception as e:
        st.error(f"Error al procesar el archivo {name}: {e}")
    finally:
        if os.path.exists(path):
            os.remove(path)
        if 'part' in locals():
            genai.delete_file(part.name)

    return data_out

# Resto de funciones: apply_scale_factor_to_raw_data, map_and_aggregate_balance,
# map_and_aggregate_pnl, convert_to_usd (idénticas a tu versión anterior)

# --- Streamlit UI ---
st.set_page_config(layout="wide")
st.title("Bot de Análisis de Estados Financieros con Gemini")

files = st.file_uploader("Sube hasta 4 PDFs", type="pdf", accept_multiple_files=True)
if files:
    if st.button("Procesar y Convertir a USD"):
        all_results = {}
        with st.spinner("Extrayendo datos..."):
            for f in files:
                res = extract_financial_data(f, GOOGLE_API_KEY)
                all_results.update(res)

        final_display = {}
        # aquí aplicas tu lógica de mapeo, agregación y conversión a USD
        # para llenar final_display[file_name][year] = {"BalanceGeneralUSD":..., "EstadoResultadosUSD":...}

        if final_display:
            st.success("¡Listo! Datos convertidos a USD.")

            # Construcción del índice corregido:
            all_balance_concepts_display_order = []
            for cat, items in BALANCE_SHEET_STRUCTURE.items():
                all_balance_concepts_display_order.append(cat)
                for name, _ in items:
                    all_balance_concepts_display_order.append(f"    {name}")

            # Usamos la lista correcta:
            df_balance = pd.DataFrame(index=all_balance_concepts_display_order)
            # ... rellenar columnas y formatear igual que antes ...
            st.dataframe(df_balance)

            st.subheader("Estado de Pérdidas y Ganancias (USD)")
            df_pnl = pd.DataFrame(index=PNL_STANDARD_CONCEPTS)
            # ... rellenar y formatear ...
            st.dataframe(df_pnl)

            # Botón de descarga Excel
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
                df_balance.to_excel(writer, sheet_name='BalanceGeneral_USD')
                df_pnl.to_excel(writer, sheet_name='EstadoResultados_USD')
            buf.seek(0)
            st.download_button("Descargar Excel", data=buf, file_name="Estados_USD.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            st.error("No se pudo extraer o convertir datos.")
else:
    st.info("Sube tus archivos y haz clic en 'Procesar y Convertir a USD'.")
