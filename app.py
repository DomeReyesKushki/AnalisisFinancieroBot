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
BALANCE_SHEET_STANDARD_CONCEPTS = [
    "Activos Corrientes", # Título de Categoría
    "Efectivo y equivalentes de efectivo", 
    "Inventarios",
    "Cuentas por cobrar", 
    "Cuentas por cobrar a empresas relacionadas CP", 
    "Gasto Anticipado", 
    "Otros activos",
    "Total Activo Corriente", 

    "Activos No Corrientes", # Título de Categoría
    "Propiedad, planta y equipo", 
    "Activo Fijo", 
    "Intangibles (Software)", 
    "Otros Activos No Corrientes",
    "Total Activo No Corriente", 

    "TOTAL ACTIVOS", 

    "Pasivos a Corto Plazo", # Título de Categoría
    "Préstamos y empréstitos corrientes",
    "Obligaciones Financieras", 
    "Cuentas comerciales y otras cuentas por pagar", 
    "Cuentas por Pagar", 
    "Pasivo Laborales", 
    "Anticipos", 
    "Impuestos Corrientes (Pasivo)", 
    "Impuestos por pagar", 
    "Otros pasivos corrientes",
    "Total Pasivo Corriente", 

    "Pasivos a Largo Plazo", # Título de Categoría
    "Préstamos y empréstitos no corrientes",
    "Obligaciones Financieras No Corrientes", 
    "Anticipos y Avances Recibidos", 
    "Otros pasivos no corrientes",
    "Total Pasivo No Corriente", 

    "TOTAL PASIVOS", 

    "Patrimonio Atribuible a los Propietarios de la Matriz", # Título de Categoría
    "Capital social", 
    "Capital Emitido",
    "Aportes Para Futuras Capitalizaciones", 
    "Resultados Ejerc. Anteriores", 
    "Resultado del Ejercicio", 
    "Otros componentes del patrimonio",
    "TOTAL PATRIMONIO", 

    "TOTAL PASIVO Y PATRIMONIO"
]

# Mapeo de sinónimos (llave es sinónimo.lower(), valor es el nombre estándar)
# Este diccionario se usará en Python para mapear lo que Gemini extrae a tus categorías estándar
BALANCE_SHEET_SYNONYMS = {
    "inventarios": "Inventarios", "inventario equipos": "Inventarios",
    "efectivo y equivalentes de efectivo": "Efectivo y equivalentes de efectivo", "efectivo y depósitos": "Efectivo y equivalentes de efectivo", "bancos": "Efectivo y equivalentes de efectivo", "caja": "Efectivo y equivalentes de efectivo", "fondo fijo de caja": "Efectivo y equivalentes de efectivo", "caja y bancos": "Efectivo y equivalentes de efectivo",
    "cuentas por cobrar": "Cuentas por cobrar", "clientes": "Cuentas por cobrar", "deudores": "Cuentas por cobrar", "cuentas por cobrar comerciales": "Cuentas por cobrar", "cuentas por cobrar a empresas relacionadas cp": "Cuentas por cobrar a empresas relacionadas CP", "deudores diversos": "Cuentas por cobrar",
    "gasto anticipado": "Gasto Anticipado", "gastos pagados por anticipado": "Gasto Anticipado", "pagos anticipados": "Gasto Anticipado", "impuestos a favor": "Gasto Anticipado", "pagos provisionales": "Gasto Anticipado",
    "otros activos": "Otros activos", "otros activos corrientes": "Otros activos", "activos por impuestos": "Otros activos", "activos financieros": "Otros activos", # Para Activos Corrientes

    "propiedad, planta y equipo": "Propiedad, planta y equipo", "propiedad planta y equipo": "Propiedad, planta y equipo", "activo fijo": "Propiedad, planta y equipo", "activo fijo neto": "Propiedad, planta y equipo",
    "intangibles (software)": "Intangibles (Software)", "intangibles": "Intangibles (Software)",
    "otros activos no corrientes": "Otros Activos No Corrientes", "activos diferidos": "Otros Activos No Corrientes", "activos a largo plazo": "Otros Activos No Corrientes",

    "total activo circulante": "Total Activo Corriente",
    "total activo no corriente": "Total Activo No Corriente", "total activo fijo": "Total Activo No Corriente", "total activo a largo plazo": "Total Activo No Corriente",
    "total activos": "TOTAL ACTIVOS", "total activo": "TOTAL ACTIVOS", "suma del activo": "TOTAL ACTIVOS",

    "préstamos y empréstitos corrientes": "Préstamos y empréstitos corrientes", "préstamos bancarios a corto plazo": "Préstamos y empréstitos corrientes",
    "obligaciones financieras": "Obligaciones Financieras", "préstamos": "Obligaciones Financieras",
    "cuentas comerciales y otras cuentas por pagar": "Cuentas comerciales y otras cuentas por pagar", "acreedores diversos": "Cuentas comerciales y otras cuentas por pagar", "proveedores": "Cuentas comerciales y otras cuentas por pagar",
    "cuentas por pagar": "Cuentas por Pagar", 
    "pasivo laborales": "Pasivo Laborales", "provisiones para sueldos y salarios": "Pasivo Laborales", "remuneraciones por pagar": "Pasivo Laborales", "provisión de sueldos y salarios x pagar": "Pasivo Laborales", "provisión de contribuciones segsocial x pagar": "Pasivo Laborales",
    "anticipos": "Anticipos", "anticipos de clientes": "Anticipos",
    "impuestos corrientes (pasivo)": "Impuestos Corrientes (Pasivo)", "impuestos por pagar": "Impuestos Corrientes (Pasivo)", "pasivo por impuestos": "Impuestos Corrientes (Pasivo)", "impuestos trasladados cobrados": "Impuestos Corrientes (Pasivo)", "impuestos trasladados no cobrados": "Impuestos Corrientes (Pasivo)", "impuestos y derechos por pagar": "Impuestos Corrientes (Pasivo)",
    "otros pasivos corrientes": "Otros pasivos corrientes",
    "total pasivo corriente": "Total Pasivo Corriente", "total pasivo a corto plazo": "Total Pasivo Corriente",

    "préstamos y empréstitos no corrientes": "Préstamos y empréstitos no corrientes", "préstamos bancarios a largo plazo": "Préstamos y empréstitos no corrientes",
    "obligaciones financieras no corrientes": "Obligaciones Financieras No Corrientes", 
    "anticipos y avances recibidos": "Anticipos y Avances Recibidos", "depósitos en garantía": "Anticipos y Avances Recibidos",
    "otros pasivos no corrientes": "Otros pasivos no corrientes", "ingresos diferidos": "Otros pasivos no corrientes",
    "total pasivo no corriente": "Total Pasivo No Corriente", "total pasivo a largo plazo": "Total Pasivo No Corriente",

    "total pasivos": "TOTAL PASIVOS", "total pasivo": "TOTAL PASIVOS", "suma del pasivo": "TOTAL PASIVOS",

    "capital social": "Capital social", "capital emitido": "Capital social",
    "aportes para futuras capitalizaciones": "Aportes Para Futuras Capitalizaciones",
    "resultados ejerc. anteriores": "Resultados Ejerc. Anteriores", "ganancias retenidas": "Resultados Ejerc. Anteriores",
    "resultado del ejercicio": "Resultado del Ejercicio", "utilidad del período": "Resultado del Ejercicio", "utilidad o pérdida del ejercicio": "Resultado del Ejercicio",
    "otros componentes del patrimonio": "Otros componentes del patrimonio", "otras reservas": "Otros componentes del patrimonio", "patrimonio minoritario": "Otros componentes del patrimonio", "impuestos retenidos": "Otros componentes del patrimonio", 
    "total patrimonio": "TOTAL PATRIMONIO", "suma del capital": "TOTAL PATRIMONIO",

    "total pasivo y patrimonio": "TOTAL PASIVO Y PATRIMONIO", "suma del pasivo y capital": "TOTAL PASIVO Y PATRIMONIO"
}

PNL_STANDARD_CONCEPTS = [
    "Ingresos por Ventas", "Costo de Ventas", "Ganancia Bruta", 
    "Gastos de Operación", "Ganancia (Pérdida) de Operación", 
    "Ingresos (Gastos) Financieros", "Impuesto a la Renta", "Ganancia (Pérdida) Neta"
]

PNL_SYNONYMS = {
    "ingresos por ventas": "Ingresos por Ventas", "ventas netas": "Ingresos por Ventas", "ingresos operacionales": "Ingresos por Ventas", "ingresos": "Ingresos por Ventas",
    "costo de ventas": "Costo de Ventas", "costo de bienes vendidos": "Costo de Ventas", "costos": "Costo de Ventas",
    "ganancia bruta": "Ganancia Bruta", "margen bruto": "Ganancia Bruta", 
    "gastos de operación": "Gastos de Operación", "gastos de administración": "Gastos de Operación", "gastos de venta": "Gastos de Operación", "gastos operacionales": "Gastos de Operación", "gastos generales": "Gastos de Operación",
    "ganancia (pérdida) de operación": "Ganancia (Pérdida) de Operación", "utilidad operacional": "Ganancia (Pérdida) de Operación", "ebitda": "Ganancia (Pérdida) de Operación", "utilidad (o pérdida)": "Ganancia (Pérdida) de Operación",
    "ingresos (gastos) financieros": "Ingresos (Gastos) Financieros", "gastos financieros": "Ingresos (Gastos) Financieros", "ingresos financieros": "Ingresos (Gastos) Financieros", "resultado integral de financiamiento": "Ingresos (Gastos) Financieros",
    "impuesto a la renta": "Impuesto a la Renta", "gasto por impuestos": "Impuesto a la Renta", "impuesto sobre la renta": "Impuesto a la Renta",
    "ganancia (pérdida) neta": "Ganancia (Pérdida) Neta", "utilidad neta": "Ganancia (Pérdida) Neta", "resultado del período": "Ganancia (Pérdida) Neta", "resultado del ejercicio": "Ganancia (Pérdida) Neta"
}


# --- Tasas de cambio de ejemplo por AÑO (AL 31 DE DICIEMBRE DE CADA AÑO) ---
EXCHANGE_RATES_BY_YEAR_TO_USD = {
    2025: { 
        "EUR": 1.0900, 
        "MXN": 0.0570, 
        "PEN": 0.2700, 
        "COP": 0.00023, 
        "CLP": 0.00105, 
        "USD": 1.0,
    },
    2024: { 
        "EUR": 1.0850, 
        "MXN": 0.0585, 
        "PEN": 0.2680, 
        "COP": 0.00024, 
        "CLP": 0.0011, 
        "USD": 1.0,
    },
    2023: { 
        "EUR": 1.0700, 
        "MXN": 0.0590, 
        "PEN": 0.2650, 
        "COP": 0.00026, 
        "CLP": 0.0012, 
        "USD": 1.0,
    }
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

# --- Función de Extracción de Datos con Gemini ---
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

        # PROMPT MEJORADO PARA EXTRACCIÓN DE CUENTAS DETALLADAS Y SIN INFERENCIA DE UNIDAD
        prompt = f"""
        Analiza cuidadosamente el siguiente documento PDF que contiene estados financieros.

        **Objetivo Principal:** Extraer los datos financieros del Balance General y del Estado de Pérdidas y Ganancias para CADA COLUMNA de DICIEMBRE (ej. "DICIEMBRE 2024", "DICIEMBRE 2023") que encuentres en el documento. Si no hay columnas de DICIEMBRE, entonces extrae los datos para las ÚLTIMAS 2 COLUMNAS de fecha disponibles (generalmente años fiscales).

        **Paso 1: Identificación de Moneda y Años de Reporte.**
        -   **Moneda Global:** Identifica la moneda principal. Busca símbolos de moneda ($, €, S/, Bs), códigos ISO (USD, EUR, MXN, COP, CLP, PEN), o palabras como "Pesos Mexicanos", "Pesos Colombianos", "Soles Peruanos", "Dólares", "Euros". Si el documento menciona el país de la empresa (ej. "Mexico", "Colombia", "Chile", "Perú"), infiere la moneda local si no está explícitamente definida (ej. "Mexico" -> MXN, "Colombia" -> COP, "Chile" -> CLP, "Perú" -> PEN). Extrae el código ISO o abreviatura más común (COP, CLP, MXN, USD, EUR, PEN). Si no se puede inferir con certeza, usa "USD" como valor por defecto.
        -   **Años de Reporte:** Identifica TODOS los años de las columnas de DICIEMBRE disponibles (ej. 2024, 2023). Si no hay DICIEMBRE, identifica los años de las últimas 2 columnas de fecha disponibles.

        **Paso 2: Extracción de Valores y Nombres de Cuentas (SIN ENCASILLAMIENTO DIRECTO EN ESTE PASO).**
        Para cada año/columna de fecha identificada, extrae los valores NUMÉRICOS.
        **MUY IMPORTANTE:** Los valores numéricos deben ser el número **TAL CUAL APARECE EN EL DOCUMENTO**, sin aplicar ninguna multiplicación por "millones" o "miles". Si el documento dice "1.485.361" y es "CLP$m", devuelve 1485361. Si dice "77.448,01", devuelve 77448.01. La conversión de la magnitud a unidades completas y a USD se hará COMPLETAMENTE en Python.
        Extrae los **NOMBRES DE LAS CUENTAS exactamente como aparecen en el documento**, y su valor. No intentes encasillar o resumir en este paso.

        **Formato de Salida Requerido:**
        Proporciona la salida en formato JSON con la siguiente estructura. Las claves de los años (ej. "2024") deben ser strings.

        {{
          "Moneda": "COP",
          "ReportesPorAnio": [
            {{
              "Anio": "2024",
              "BalanceGeneral": {{ 
                "ACTIVOS": {{
                    "Activo Corriente": {{
                        "Nombre de cuenta del documento 1": valor,
                        "Nombre de cuenta del documento 2": valor,
                        "TOTAL ACTIVO CIRCULANTE": valor,
                        ...
                    }},
                    "Activo No Corriente": {{
                        "Nombre de cuenta detalle X": valor,
                        "TOTAL ACTIVO NO CORRIENTE": valor,
                        ...
                    }},
                    "TOTAL ACTIVO": valor
                }},
                "PASIVOS": {{
                    "Pasivo Corriente": {{
                        "Nombre de cuenta detalle P1": valor,
                        "TOTAL PASIVO A CORTO PLAZO": valor,
                        ...
                    }},
                    "Pasivo a Largo Plazo": {{
                        "Nombre de cuenta detalle P2": valor,
                        "TOTAL PASIVO A LARGO PLAZO": valor,
                        ...
                    }},
                    "TOTAL PASIVO": valor
                }},
                "CAPITAL": {{
                    "Nombre de cuenta detalle C1": valor,
                    "TOTAL CAPITAL": valor,
                    ...
                }},
                "TOTAL PASIVO Y CAPITAL": valor
              }},
              "EstadoResultados": {{ 
                "Ingresos": {{
                    "Nombre de cuenta detalle I1": valor,
                    "TOTAL INGRESOS": valor,
                    ...
                }},
                "Costos": {{
                    "Nombre de cuenta detalle C1": valor,
                    "TOTAL COSTOS": valor,
                    ...
                }},
                "TOTAL UTILIDAD BRUTA": valor,
                "Gastos de Operación": {{
                    "Nombre de cuenta detalle G1": valor,
                    "TOTAL GASTO DE OPERACIÓN": valor,
                    ...
                }},
                "UTILIDAD DE OPERACIÓN": valor,
                "Gastos y Productos Financieros": {{
                    "Nombre de cuenta detalle F1": valor,
                    "TOTAL GTOS Y PROD FINANC": valor,
                    ...
                }},
                "RESULTADO DEL EJERCICIO": valor
              }}
            }}
            # ... Puede haber otro objeto similar para Anio 2023 ...
          ]
        }}

        Responde ÚNICAMENTE con el objeto JSON.
        """

        response = model.generate_content([prompt, pdf_part], stream=False)
        
        st.write(f"\n--- Respuesta cruda de Gemini para {file_name} ---")
        st.code(response.text, language='json') 
        st.write("---------------------------------")

        json_start = response.text.find('{')
        json_end = response.text.rfind('}') + 1
        
        if json_start != -1 and json_end != -1:
            json_string = response.text[json_start:json_end]
            data_from_gemini = json.loads(json_string) 
            
            global_currency = data_from_gemini.get("Moneda")
            # Ya no extraemos "Unidad" de Gemini. Se manejará en Python.
            
            for report_entry in data_from_gemini.get("ReportesPorAnio", []):
                year_str = report_entry.get("Anio") 
                if year_str:
                    extracted_data_key = f"{file_name}_{year_str}" 
                    extracted_data_for_file[extracted_data_key] = { 
                        "Moneda": global_currency,
                        "AnioInforme": year_str, 
                        "BalanceGeneral": report_entry.get("BalanceGeneral", {}),
                        "EstadoResultados": report_entry.get("EstadoResultados", {})
                    }
                else:
                    st.warning(f"Advertencia: Reporte sin 'Anio' encontrado en {file_name}. Saltando este reporte.")

        else:
            st.error(f"Error: No se pudo encontrar un JSON válido en la respuesta para {file_name}. Respuesta completa: {response.text}")
    except json.JSONDecodeError as e:
        st.error(f"Error al decodificar JSON para {file_name}: {e}. Respuesta completa: {response.text}")
    except Exception as e:
        st.error(f"Error al procesar el archivo {file_name}: {e}")
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path) 
        if 'pdf_part' in locals() and pdf_part:
            genai.delete_file(pdf_part.name)

    return extracted_data_for_file 

# --- Función auxiliar para aplicar el scale_factor a los números del JSON extraído (NO SE USA DIRECTAMENTE EN convert_to_usd AHORA) ---
def apply_scale_factor_to_raw_data(data_dict, unit):
    scaled_dict = {}
    scale_factor = 1.0
    if unit and isinstance(unit, str):
        unit_lower = unit.lower()
        if "millones" in unit_lower or "$m" in unit_lower or "mm" in unit_lower:
            scale_factor = 1_000_000.0
        elif "miles" in unit_lower:
            scale_factor = 1_000.0
    
    for k, v in data_dict.items():
        if isinstance(v, dict):
            scaled_dict[k] = apply_scale_factor_to_raw_data(v, unit)
        elif isinstance(v, (int, float)):
            scaled_dict[k] = v * scale_factor
        else:
            scaled_dict[k] = v
    return scaled_dict

# --- Función auxiliar para mapear y agregar cuentas de Balance General ---
def map_and_aggregate_balance(raw_balance_data_nested, synonyms_map):
    # raw_balance_data_nested es el diccionario que viene directamente del JSON de Gemini para BalanceGeneral
    # Ejemplo: {'ACTIVOS': {'Activo Corriente': {'FONDO FIJO DE CAJA': 699.1, 'BANCOS': 287341.76, ...}}}
    
    aggregated_data = {concept: 0.0 for concept in BALANCE_SHEET_STANDARD_CONCEPTS}
    
    # Recorrer las secciones principales (ACTIVOS, PASIVOS, CAPITAL)
    for main_section_name, main_section_content in raw_balance_data_nested.items():
        if isinstance(main_section_content, dict): # Si es una sección con sub-secciones (ej. "ACTIVOS")
            for sub_section_name, sub_section_content in main_section_content.items():
                if isinstance(sub_section_content, dict): # Si es una sub-sección con cuentas detalladas (ej. "Activo Corriente")
                    for account_name_raw, value_raw in sub_section_content.items():
                        if value_raw is not None and isinstance(value_raw, (int, float)):
                            mapped_name = synonyms_map.get(account_name_raw.lower())
                            if mapped_name:
                                aggregated_data[mapped_name] += value_raw
                            else:
                                st.warning(f"Advertencia: Cuenta BG detallada '{account_name_raw}' no mapeada a estándar. Valor: {value_raw}")
                elif isinstance(main_section_content, (int, float)): # Para totales directos de sección (ej. "TOTAL ACTIVO CIRCULANTE" si estuviera al mismo nivel)
                    mapped_name = synonyms_map.get(main_section_name.lower())
                    if mapped_name:
                        aggregated_data[mapped_name] += main_section_content 
                    else:
                        st.warning(f"Advertencia: Total BG de sub-sección '{main_section_name}' no mapeado. Valor: {main_section_content}")
        elif isinstance(main_section_content, (int, float)): # Para los TOTALES de nivel superior (ej. "TOTAL ACTIVOS" si está directamente bajo BalanceGeneral)
            mapped_name = synonyms_map.get(main_section_name.lower())
            if mapped_name:
                aggregated_data[mapped_name] = main_section_content # Se sobrescribe porque es un total directo
            else:
                st.warning(f"Advertencia: Total BG de nivel superior '{main_section_name}' no mapeado. Valor: {main_section_content}")
    
    # Asegurarse de que los totales principales que pueden estar en el nivel superior del BalanceGeneral de Gemini se mapeen
    # Ej: "TOTAL ACTIVOS"
    for total_concept_key in ["TOTAL ACTIVOS", "TOTAL PASIVOS", "TOTAL PATRIMONIO", "TOTAL PASIVO Y PATRIMONIO"]:
        if total_concept_key in raw_balance_data_nested and isinstance(raw_balance_data_nested[total_concept_key], (int, float)):
            mapped_name = synonyms_map.get(total_concept_key.lower())
            if mapped_name:
                aggregated_data[mapped_name] = raw_balance_data_nested[total_concept_key] # Usar el total directo
    
    return aggregated_data

# Función auxiliar para mapear y agregar cuentas de Estado de Pérdidas y Ganancias
def map_and_aggregate_pnl(raw_pnl_data_nested, synonyms_map):
    # raw_pnl_data_nested es el diccionario que viene directamente del JSON de Gemini para EstadoResultados
    # Ejemplo: {'Ingresos': {'INGRESOS': 421990.58, 'TOTAL INGRESOS': 421990.58}, 'UTILIDAD BRUTA': 421990.58, ...}
    
    aggregated_data = {concept: 0.0 for concept in PNL_STANDARD_CONCEPTS} 

    for section_name, section_content in raw_pnl_data_nested.items():
        if isinstance(section_content, dict): # Si es una sección con sub-cuentas (ej. "Ingresos")
            for account_name_raw, value_raw in section_content.items():
                if value_raw is not None and isinstance(value_raw, (int, float)):
                    mapped_name = synonyms_map.get(account_name_raw.lower())
                    if mapped_name:
                        aggregated_data[mapped_name] += value_raw
                    else:
                        st.warning(f"Advertencia: Cuenta PnL detallada '{account_name_raw}' no mapeada a estándar. Valor: {value_raw}")
        elif isinstance(section_content, (int, float)): # Para los totales directos de PnL (ej. "UTILIDAD BRUTA")
            mapped_name = synonyms_map.get(section_name.lower())
            if mapped_name:
                aggregated_data[mapped_name] = section_content 
            else:
                st.warning(f"Advertencia: Total PnL de sección '{section_name}' no mapeado. Valor: {section_content}")

    return aggregated_data

def convert_to_usd(data_dict, currency_code, report_year): 
    exchange_rate = get_exchange_rate(currency_code, date=report_year)
    
    st.write(f"DEBUG: Conversión - Moneda: {currency_code}, Año: {report_year}, Tasa USD: {exchange_rate}")

    converted_data = {} 
    for key, value in data_dict.items():
        if isinstance(value, dict):
            converted_data[key] = convert_to_usd(value, currency_code, report_year) 
        elif isinstance(value, (int, float)):
            converted_value = value * exchange_rate
            converted_data[key] = converted_value
        else:
            converted_data[key] = value 
    return converted_data

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
        
        with st.spinner("Procesando PDFs con Gemini... Esto puede tomar un momento."):
            for uploaded_file in uploaded_files_streamlit:
                results_for_one_file = extract_financial_data(uploaded_file, GOOGLE_API_KEY)
                total_extracted_results.update(results_for_one_file) 

        _final_data_for_display = {} 
        if total_extracted_results: 
            for extracted_key, data_from_gemini in total_extracted_results.items():
                
                parts = extracted_key.rsplit('_', 1) 
                file_name_original_pdf = parts[0]
                year_str_from_key = parts[1] if len(parts) > 1 else None
                
                global_currency = data_from_gemini.get("Moneda", "N/A").upper()
                # La unidad ya no viene de Gemini en el JSON final, la inferimos de los datos o asumimos
                # Sin embargo, el prompt le pide a Gemini que los valores YA estén en unidades completas.
                # Si el PDF dice CLP$m, Gemini debe dar el valor multiplicado por 1,000,000.
                # Si no dice nada, Gemini da el valor tal cual.
                # Por lo tanto, no necesitamos un 'unit' en la función convert_to_usd
                # Pero si lo queremos para debug, podemos inferirlo aquí
                
                year_int = None
                try:
                    if year_str_from_key:
                        year_int = int(year_str_from_key)
                except (ValueError, TypeError):
                    st.warning(f"Advertencia: El año '{year_str_from_key}' extraído de la clave no es un número válido para {extracted_key}. Saltando procesamiento de este reporte.")
                    continue

                if not global_currency or not year_int:
                    st.warning(f"Advertencia: Moneda o Año no identificados para {extracted_key}. Saltando conversión.")
                    continue
                
                st.write(f"Identificada moneda: {global_currency}, Año: {year_int} para {file_name_original_pdf} (Reporte {year_int}).")
                
                balance_data_raw = data_from_gemini.get("BalanceGeneral", {})
                pnl_data_raw = data_from_gemini.get("EstadoResultados", {})

                # NO APLICAMOS EL FACTOR DE ESCALA AQUÍ, SE ASUME QUE GEMINI YA DIÓ EL VALOR EN UNIDADES COMPLETAS
                # Pero sí debemos mapear y agregar las cuentas de detalle AHORA
                aggregated_balance_data = map_and_aggregate_balance(balance_data_raw, BALANCE_SHEET_SYNONYMS)
                aggregated_pnl_data = map_and_aggregate_pnl(pnl_data_raw, PNL_SYNONYMS)

                # Convertir los datos agregados a USD
                converted_balance_for_year = convert_to_usd(aggregated_balance_data, global_currency, year_int) 
                converted_pnl_for_year = convert_to_usd(aggregated_pnl_data, global_currency, year_int)
                
                if file_name_original_pdf not in _final_data_for_display:
                    _final_data_for_display[file_name_original_pdf] = {}
                _final_data_for_display[file_name_original_pdf][year_int] = {
                    "BalanceGeneralUSD": converted_balance_for_year,
                    "EstadoResultadosUSD": converted_pnl_for_year
                }
        else:
            st.warning("No se extrajeron datos válidos de ningún archivo para la conversión. Verifique el formato de los PDFs y el prompt.")

        if _final_data_for_display: 
            st.success("¡Datos extraídos y convertidos a USD con éxito!")

            st.subheader("Balance General (Valores en USD)")
            
            # --- CONSTRUCCIÓN ROBUSTA DEL DATAFRAME DE BALANCE GENERAL ---
            all_balance_concepts_display_order = []
            for category_name, items_list_in_structure in BALANCE_SHEET_STRUCTURE.items():
                all_balance_concepts_display_order.append(category_name) # Título de Categoría
                # Añadir los ítems estándar indentados
                for item_name_standard, _ in items_list_in_structure:
                    all_balance_concepts_display_order.append(f"    {item_name_standard}")

            df_balance_combined = pd.DataFrame(index=all_balance_concepts_display_order) 
            
            for file_name_original_pdf, file_years_data in _final_data_for_display.items():
                for year, converted_data_for_year in sorted(file_years_data.items()): 
                    balance_data_usd = converted_data_for_year.get("BalanceGeneralUSD", {})
                    
                    col_name = f"Valor - {file_name_original_pdf} ({year})" 
                    temp_column_data = pd.Series(index=all_balance_concepts_display_order, dtype=object)

                    for concept_to_display in all_balance_concepts_display_order:
                        if concept_to_display.strip().startswith("Total"): # Si es un total (ej. "TOTAL ACTIVOS", "Total Activo Corriente")
                            standard_name = concept_to_display.strip()
                            if standard_name in balance_data_usd:
                                temp_column_data.loc[concept_to_display] = balance_data_usd[standard_name]
                            else: # Puede que el total no exista en los datos o no se haya agregado
                                temp_column_data.loc[concept_to_display] = "" 
                        elif concept_to_display in BALANCE_SHEET_STRUCTURE: # Si es un título de categoría (ej. "Activos Corrientes")
                            temp_column_data.loc[concept_to_display] = "" # Celda vacía para el título
                        else: # Es una cuenta detallada (indentada)
                            standard_item_name = concept_to_display.strip()
                            if standard_item_name in balance_data_usd:
                                temp_column_data.loc[concept_to_display] = balance_data_usd[standard_item_name]
                            else:
                                temp_column_data.loc[concept_to_display] = "" # Si no hay valor, dejar vacío
                    
                df_balance_combined[col_name] = temp_column_data 
                
            for col in df_balance_combined.columns:
                df_balance_combined[col] = df_balance_combined[col].apply(
                    lambda x: f"{x:,.2f}" if isinstance(x, (int, float)) else ("" if pd.isna(x) else x)
                )
            
            st.dataframe(df_balance_combined) 

            st.subheader("Estado de Pérdidas y Ganancias (Valores en USD)")

            # --- CONSTRUCCIÓN ROBUSTA DEL DATAFRAME DE ESTADO DE PÉRDIDAS Y GANANCIAS ---
            df_pnl_combined = pd.DataFrame(index=PNL_STANDARD_CONCEPTS) # Usamos PNL_STANDARD_CONCEPTS para el índice

            for file_name_original_pdf, file_years_data in _final_data_for_display.items():
                for year, converted_data_for_year in sorted(file_years_data.items()): 
                    pnl_data_usd = converted_data_for_year.get("EstadoResultadosUSD", {})

                    col_name = f"Valor - {file_name_original_pdf} ({year})" 
                    temp_column_data = pd.Series(index=PNL_STANDARD_CONCEPTS, dtype=object) 
                    
                    for standard_item_name in PNL_STANDARD_CONCEPTS: # Iterar sobre el estándar PNL
                        if standard_item_name in pnl_data_usd:
                            temp_column_data.loc[standard_item_name] = pnl_data_usd[standard_item_name]
                        else:
                            temp_column_data.loc[standard_item_name] = "" # Dejar vacío si no hay valor

                df_pnl_combined[col_name] = temp_column_data
                
            for col in df_pnl_combined.columns:
                df_pnl_combined[col] = df_pnl_combined[col].apply(
                    lambda x: f"{x:,.2f}" if isinstance(x, (int, float)) else ("" if pd.isna(x) else x)
                )
            
            st.dataframe(df_pnl_combined) 

            import io
            output_excel_buffer = io.BytesIO()
            
            try:
                with pd.ExcelWriter(output_excel_buffer, engine='xlsxwriter') as writer:
                    if not df_balance_combined.empty:
                        df_balance_combined.to_excel(writer, sheet_name='BalanceGeneral_USD', index=True)
                    else:
                        st.info("Nota: El Balance General está vacío y no se exportó a Excel.")
                        
                    if not df_pnl_combined.empty:
                        df_pnl_combined.to_excel(writer, sheet_name='EstadoResultados_USD', index=True)
                    else:
                        st.info("Nota: El Estado de Pérdidas y Ganancias está vacío y no se exportó a Excel.")
                
                output_excel_buffer.seek(0)
                
                st.download_button(
                    label="Descargar Estados Financieros en Excel",
                    data=output_excel_buffer,
                    file_name="EstadosFinancieros_Convertidos_USD.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

            except Exception as e:
                st.error(f"Error al exportar a Excel: {e}")

        else: 
            st.error("No se pudieron extraer o convertir datos de los PDFs. Asegúrate de que los documentos sean legibles y contengan estados financieros estándar.")

else:
    st.info("Sube tus archivos PDF y haz clic en 'Procesar y Convertir a USD' para comenzar.")
