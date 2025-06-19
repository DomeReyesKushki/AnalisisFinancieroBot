import streamlit as st 
import pandas as pd
import google.generativeai as genai
import os
import json
import datetime
import tempfile
import io 

# --- Configuración de la API de Gemini ---
if "GOOGLE_API_KEY" in st.secrets:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
else:
    st.error("Error: La clave de API de Google Gemini (GOOGLE_API_KEY) no se encontró en Streamlit Secrets.")
    st.info("Por favor, configura tu secret 'GOOGLE_API_KEY' en Streamlit Community Cloud (Menú -> Secrets) con el formato: GOOGLE_API_KEY='TU_CLAVE_REAL_AQUI'")
    st.stop() 

genai.configure(api_key=GOOGLE_API_KEY)

# --- Estructura del Balance General con SINÓNIMOS para mapeo ---
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
        # Agregado para mapear "Capital Variable"
        ("Capital Variable", ["Capital Variable"]),
        ("TOTAL PATRIMONIO", ["TOTAL PATRIMONIO", "Total Patrimonio", "SUMA DEL CAPITAL", "TOTAL CAPITAL"]) 
    ],
    "TOTAL PASIVO Y PATRIMONIO": [("TOTAL PASIVO Y PATRIMONIO", ["TOTAL PASIVO Y PATRIMONIO", "Total Pasivo y Patrimonio", "SUMA DEL PASIVO Y CAPITAL"])] 
}

# Genera la lista de conceptos estándar para usar como índice de DataFrame
BALANCE_SHEET_STANDARD_CONCEPTS_LIST = []
for category_name, items_list in BALANCE_SHEET_STRUCTURE.items():
    BALANCE_SHEET_STANDARD_CONCEPTS_LIST.append(category_name) 
    for standard_name, _ in items_list: 
        BALANCE_SHEET_STANDARD_CONCEPTS_LIST.append(f"    {standard_name}")

# Diccionario de sinónimos para facilitar el mapeo en el código (llave es sinónimo.lower(), valor es el nombre estándar)
BALANCE_SHEET_SYNONYMS = {}
for main_category, items_list in BALANCE_SHEET_STRUCTURE.items():
    for standard_name, synonyms in items_list: 
        for syn in synonyms:
            BALANCE_SHEET_SYNONYMS[syn.lower()] = standard_name

PNL_STANDARD_CONCEPTS = [
    "Ingresos por Ventas", "Costo de Ventas", "Ganancia Bruta", 
    "Gastos de Operación", "Ganancia (Pérdida) de Operación", 
    "Ingresos (Gastos) Financieros", "Impuesto a la Renta", "Ganancia (Pérdida) Neta"
]

PNL_SYNONYMS = {
    "ingresos por ventas": "Ingresos por Ventas", "ventas netas": "Ingresos por Ventas", "ingresos operacionales": "Ingresos por Ventas", "ingresos": "Ingresos por Ventas", "total ingresos": "Ingresos por Ventas", 
    "costo de ventas": "Costo de Ventas", "costo de bienes vendidos": "Costo de Ventas", "costos": "Costo de Ventas", "total costos": "Costo de Ventas",
    "ganancia bruta": "Ganancia Bruta", "margen bruto": "Ganancia Bruta", "utilidad bruta": "Ganancia Bruta", 
    "gastos de operación": "Gastos de Operación", "gastos de administración": "Gastos de Operación", "gastos de venta": "Gastos de Operación", "gastos operacionales": "Gastos de Operación", "gastos generales": "Gastos de Operación", "total gasto de operación": "Gastos de Operación",
    "ganancia (pérdida) de operación": "Ganancia (Pérdida) de Operación", "utilidad operacional": "Ganancia (Pérdida) de Operación", "ebitda": "Ganancia (Pérdida) de Operación", "utilidad (o pérdida)": "Ganancia (Pérdida) de Operación", "utilidad de operación": "Ganancia (Pérdida) de Operación",
    "ingresos (gastos) financieros": "Ingresos (Gastos) Financieros", "gastos financieros": "Ingresos (Gastos) Financieros", "ingresos financieros": "Ingresos (Gastos) Financieros", "resultado integral de financiamiento": "Ingresos (Gastos) Financieros", "total gtos y prod financ": "Ingresos (Gastos) Financieros",
    "impuesto a la renta": "Impuesto a la Renta", "gasto por impuestos": "Impuesto a la Renta", "impuesto sobre la renta": "Impuesto a la Renta",
    "ganancia (pérdida) neta": "Ganancia (Pérdida) Neta", "utilidad neta": "Ganancia (Pérdida) Neta", "resultado del período": "Ganancia (Pérdida) Neta", "resultado del ejercicio": "Ganancia (Pérdida) Neta"
}


# Tasas de cambio de ejemplo por AÑO (AL 31 DE DICIEMBRE DE CADA AÑO)
EXCHANGE_RATES_BY_YEAR_TO_USD = {
    2025: { "EUR": 1.0900, "MXN": 0.0570, "PEN": 0.2700, "COP": 0.00023, "CLP": 0.00105, "USD": 1.0,},
    2024: { "EUR": 1.0850, "MXN": 0.0482, "PEN": 0.2680, "COP": 0.00024, "CLP": 0.0011,  "USD": 1.0,},
    2023: { "EUR": 1.0700, "MXN": 0.0590, "PEN": 0.2650, "COP": 0.00026, "CLP": 0.0012,  "USD": 1.0,}
}

def get_exchange_rate(currency_code, target_currency="USD", date=None):
    if currency_code == target_currency:
        return 1.0
    if date and isinstance(date, int) and date in EXCHANGE_RATES_BY_YEAR_TO_USD:
        rate = EXCHANGE_RATES_BY_YEAR_TO_USD[date].get(currency_code.upper())
        if rate:
            return rate
        else:
            st.warning(f"Advertencia: No se encontró una tasa de cambio para {currency_code} en el año {date} en los datos de ejemplo. Se asumirá 1.0.")
            return 1.0 
    else:
        st.warning(f"Advertencia: No se pudo encontrar tasas para el año {date} o el año no es válido. Asumiendo 1.0 para {currency_code}.")
        return 1.0 

@st.cache_data(show_spinner=False) 
def extract_financial_data(uploaded_file_content_object, api_key): 
    model = genai.GenerativeModel('gemini-1.5-flash') 
    extracted_data_for_file = {} 
    file_name = uploaded_file_content_object.name 
    file_bytes = uploaded_file_content_object.read() 
    st.write(f"Procesando archivo: {file_name}")
    temp_file_path = None 
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
            temp_pdf.write(file_bytes) 
            temp_file_path = temp_pdf.name 
        pdf_part = genai.upload_file(path=temp_file_path, display_name=file_name)
        # ... aquí va tu prompt largo de extracción ...
        response = model.generate_content([prompt, pdf_part], stream=False)
        # procesamiento de JSON igual que antes...
    except Exception as e:
        st.error(f"Error al procesar el archivo {file_name}: {e}")
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path) 
        if 'pdf_part' in locals() and pdf_part:
            genai.delete_file(pdf_part.name)
    return extracted_data_for_file 

# (Funciones auxiliares: apply_scale_factor_to_raw_data, map_and_aggregate_balance, map_and_aggregate_pnl, convert_to_usd)
# … mantenlas sin cambios …

# --- Lógica de la Aplicación Streamlit ---
st.set_page_config(layout="wide")
st.title("Bot de Análisis de Estados Financieros con Gemini")

uploaded_files_streamlit = st.file_uploader(
    "Sube tus archivos PDF de estados financieros (máximo 4)",
    type="pdf",
    accept_multiple_files=True
)

if uploaded_files_streamlit:
    st.info(f"Archivos cargados: {', '.join([f.name for f in uploaded_files_streamlit])}")
    if st.button("Procesar y Convertir a USD"):
        total_extracted_results = {} 
        with st.spinner("Procesando PDFs con Gemini..."):
            for uploaded_file in uploaded_files_streamlit:
                results_for_one_file = extract_financial_data(uploaded_file, GOOGLE_API_KEY)
                total_extracted_results.update(results_for_one_file)

        _final_data_for_display = {}
        # ... lógica de agregación y conversión ...
        if _final_data_for_display:
            st.success("¡Datos extraídos y convertidos a USD con éxito!")

            # Construcción del índice corregido:
            all_balance_concepts_display_order = []
            for category_name, items_list in BALANCE_SHEET_STRUCTURE.items():
                all_balance_concepts_display_order.append(category_name) 
                for item_pair in items_list:
                    all_balance_concepts_display_order.append(f"    {item_pair[0]}")

            # **Aquí corregimos el NameError** usando la variable correcta:
            df_balance_combined = pd.DataFrame(index=all_balance_concepts_display_order)

            # Resto de tu código para poblar df_balance_combined...
            # (llenado de columnas, formateo y st.dataframe)

            st.subheader("Estado de Pérdidas y Ganancias (Valores en USD)")
            df_pnl_combined = pd.DataFrame(index=PNL_STANDARD_CONCEPTS)
            # Relleno de df_pnl_combined y st.dataframe...

            # Botón de descarga a Excel...
        else:
            st.error("No se pudieron extraer o convertir datos.")
else:
    st.info("Sube tus archivos PDF y haz clic en 'Procesar y Convertir a USD' para comenzar.")
