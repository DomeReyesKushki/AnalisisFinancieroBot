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
        "MXN": 0.0482, # CORREGIDO AQUÍ
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

        prompt = f"""
        Analiza cuidadosamente el siguiente documento PDF que contiene estados financieros.

        **Objetivo Principal:** Extraer los datos financieros del Balance General y del Estado de Pérdidas y Ganancias para CADA COLUMNA de DICIEMBRE (ej. "DICIEMBRE 2024", "DICIEMBRE 2023") que encuentres en el documento. Si no hay columnas de DICIEMBRE, entonces extrae los datos para las ÚLTIMAS 2 COLUMNAS de fecha disponibles (generalmente años fiscales).

        **Paso 1: Identificación de Moneda y Años de Reporte.**
        -   **Moneda Global:** Identifica la moneda principal. Busca símbolos de moneda ($, €, S/, Bs), códigos ISO (USD, EUR, MXN, COP, CLP, PEN), o palabras como "Pesos Mexicanos", "Pesos Colombianos", "Soles Peruanos", "Dólares", "Euros". Si el documento menciona el país de la empresa (ej. "Mexico", "Colombia", "Chile", "Perú"), infiere la moneda local si no está explícitamente definida (ej. "Mexico" -> MXN, "Colombia" -> COP, "Chile" -> CLP, "Perú" -> PEN). Extrae el código ISO o abreviatura más común (COP, CLP, MXN, USD, EUR, PEN). Si no se puede inferir con certeza, usa "USD" como valor por defecto.
        -   **Unidad Global (Escala):** Identifica la unidad de los valores. Si el documento dice "CLP$m", "US$m", "Expresado en millones", la unidad es "millones". Si dice "miles de pesos", la unidad es "miles". Si no indica, asume "unidades".
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


# Función auxiliar para aplicar el scale_factor a los números del JSON extraído (ANTES de conversión USD)
def apply_scale_factor_to_raw_data(data_nested, unit):
    scaled_data = {}
    scale_factor = 1.0
    if unit and isinstance(unit, str):
        unit_lower = unit.lower()
        if "millones" in unit_lower or "$m" in unit_lower or "mm" in unit_lower:
            scale_factor = 1_000_000.0
        elif "miles" in unit_lower:
            scale_factor = 1_000.0
    
    # Manejar si data_nested no es un diccionario (ej. si es null o un solo número)
    if not isinstance(data_nested, dict):
        return data_nested # Devolverlo tal cual si no es un diccionario

    for key, value in data_nested.items():
        if isinstance(value, dict):
            scaled_data[key] = apply_scale_factor_to_raw_data(value, unit) 
        elif isinstance(value, (int, float)):
            scaled_data[key] = value * scale_factor 
        else:
            scaled_data[key] = value
    return scaled_data

# Función auxiliar para mapear y agregar cuentas de Balance General
def map_and_aggregate_balance(raw_balance_data_nested, synonyms_map, unit):
    # Inicializar el diccionario con las categorías estándar a 0.0
    aggregated_data_final = {concept.strip(): 0.0 for concept in BALANCE_SHEET_STANDARD_CONCEPTS_LIST} 

    # Primero, aplicar el scale factor a todos los números ANTES de la agregación
    # Esto asegura que todas las sumas se hagan con valores en unidades completas
    scaled_raw_data = apply_scale_factor_to_raw_data(raw_balance_data_nested, unit)

    # REVISIÓN CRÍTICA AQUÍ: scaled_raw_data puede no ser un diccionario si Gemini devolvió un valor directo.
    # En ese caso, la sección no tiene sub-items para iterar.
    if not isinstance(scaled_raw_data, dict):
        st.warning(f"Advertencia: Datos crudos escalados de Balance General no son un diccionario: {type(scaled_raw_data)}. Se intentará mapear como un total global si su clave original lo permite.")
        # Buscar el nombre estándar para esta clave principal si es un total global directo (ej. "TOTAL ACTIVOS")
        # Aquí, `raw_balance_data_nested` es el diccionario original antes de escalar.
        # Necesitamos la clave original para mapearla.
        # Esto es un parche, la mejor solución es que Gemini siga la estructura siempre.
        
        # Si raw_balance_data_nested es un diccionario y tiene una clave con el valor directo
        # ej. {'TOTAL_ACTIVOS': 123}
        if isinstance(raw_balance_data_nested, dict) and len(raw_balance_data_nested) == 1:
            key_name_original = list(raw_balance_data_nested.keys())[0]
            mapped_name = synonyms_map.get(key_name_original.lower())
            if mapped_name and mapped_name in aggregated_data_final:
                 if isinstance(scaled_raw_data, (int, float)):
                    aggregated_data_final[mapped_name] = scaled_raw_data
                 else:
                    st.error(f"Error: Total global mapeado '{mapped_name}' no es un número: {type(scaled_raw_data)}")
        else: # Si no es ni un diccionario anidado, ni un total directo con clave conocida.
            st.error(f"Error: Formato inesperado para datos de Balance General después de escalar: {type(scaled_raw_data)}, Valor: {scaled_raw_data}. No se pudo procesar la agregación.")
        return aggregated_data_final # Devuelve los datos inicializados a 0.0 o con el total si se mapeó
    
    # Recorrer las secciones principales (ACTIVOS, PASIVOS, CAPITAL) del JSON de Gemini
    for section_name_outer, section_content_outer in scaled_raw_data.items():
        if isinstance(section_content_outer, dict): # Si es una sección con sub-secciones (ej. "ACTIVOS", "PASIVOS")
            for sub_section_name, sub_section_content in section_content_outer.items():
                if isinstance(sub_section_content, dict): # Si es una sub-sección con cuentas detalladas (ej. "Activo Corriente")
                    for account_name_raw, value_raw in sub_section_content.items():
                        if value_raw is not None and isinstance(value_raw, (int, float)):
                            mapped_name = synonyms_map.get(account_name_raw.lower())
                            if mapped_name and mapped_name in aggregated_data_final: 
                                aggregated_data_final[mapped_name] += value_raw
                            else:
                                st.warning(f"Advertencia: Cuenta BG detallada '{account_name_raw}' no mapeada a estándar o fuera de estructura. Valor: {value_raw}")
                # Manejar totales de sub-sección si están directamente bajo la sección principal (ej. "TOTAL ACTIVO CIRCULANTE")
                elif isinstance(sub_section_content, (int, float)): # Si el contenido de la sub-sección es un total directo
                    mapped_name = synonyms_map.get(sub_section_name.lower())
                    if mapped_name and mapped_name in aggregated_data_final: 
                        aggregated_data_final[mapped_name] = sub_section_content 
                    else:
                        st.warning(f"Advertencia: Total BG de sub-sección '{sub_section_name}' no mapeado. Valor: {sub_section_content}")
        elif isinstance(section_content_outer, (int, float)): # Para los TOTALES de nivel superior (ej. "TOTAL ACTIVOS" del JSON)
            mapped_name = synonyms_map.get(section_name_outer.lower())
            if mapped_name and mapped_name in aggregated_data_final:
                aggregated_data_final[mapped_name] = section_content_outer 
            else:
                st.warning(f"Advertencia: Total BG de nivel superior '{section_name_outer}' no mapeado. Valor: {section_content_outer}")
    
    return aggregated_data_final

# Función auxiliar para mapear y agregar cuentas de Estado de Pérdidas y Ganancias
def map_and_aggregate_pnl(raw_pnl_data_nested, synonyms_map, unit):
    aggregated_data_final = {concept: 0.0 for concept in PNL_STANDARD_CONCEPTS} 

    scaled_raw_data = apply_scale_factor_to_raw_data(raw_pnl_data_nested, unit)

    if not isinstance(scaled_raw_data, dict):
        st.error(f"Error: Datos crudos escalados de PnL no son un diccionario: {type(scaled_raw_data)}")
        return {concept: 0.0 for concept in PNL_STANDARD_CONCEPTS} 

    for section_name, section_content in scaled_raw_data.items():
        if isinstance(section_content, dict): 
            for account_name_raw, value_raw in section_content.items():
                if value_raw is not None and isinstance(value_raw, (int, float)):
                    mapped_name = synonyms_map.get(account_name_raw.lower())
                    if mapped_name and mapped_name in aggregated_data_final:
                        aggregated_data_final[mapped_name] += value_raw
                    # else: st.warning(f"Advertencia: Cuenta PnL detallada '{account_name_raw}' no mapeada o fuera de estructura. Valor: {value_raw}")
        elif isinstance(section_content, (int, float)): 
            mapped_name = synonyms_map.get(section_name.lower())
            if mapped_name and mapped_name in aggregated_data_final:
                aggregated_data_final[mapped_name] = section_content 
            # else: st.warning(f"Advertencia: Total PnL de sección '{section_name}' no mapeado. Valor: {section_content}")

    return aggregated_data_final


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
                global_unit = data_from_gemini.get("Unidad", "unidades") 
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
                
                st.write(f"Identificada moneda: {global_currency}, Año: {year_int}, Unidad: {global_unit} para {file_name_original_pdf} (Reporte {year_int}).")
                
                balance_data_raw = data_from_gemini.get("BalanceGeneral", {})
                pnl_data_raw = data_from_gemini.get("EstadoResultados", {})

                # Mapear y Agrupar cuentas (y aplicar escala aquí dentro)
                aggregated_balance_data = map_and_aggregate_balance(balance_data_raw, BALANCE_SHEET_SYNONYMS, global_unit)
                aggregated_pnl_data = map_and_aggregate_pnl(pnl_data_raw, PNL_SYNONYMS, global_unit)
                
                # Convertir los datos AGREGADOS a USD
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
            
            all_balance_concepts_display_order = []
            for category_name, items_list_in_structure in BALANCE_SHEET_STRUCTURE.items():
                all_balance_concepts_display_order.append(category_name) 
                if isinstance(items_list_in_structure, list) and items_list_in_structure and isinstance(items_list_in_structure[0], tuple):
                    all_balance_concepts_display_order.extend([f"    {item_pair[0]}" for item_pair in items_list_in_structure]) 
                elif isinstance(items_list_in_structure, list):
                    all_balance_concepts_display_order.extend([f"    {item}" for item in items_list_in_structure])

            df_balance_combined = pd.DataFrame(index=all_balance_concepts_ordered) 
            
            for file_name_original_pdf, file_years_data in _final_data_for_display.items():
                for year, converted_data_for_year in sorted(file_years_data.items()): 
                    balance_data_usd = converted_data_for_year.get("BalanceGeneralUSD", {})
                    
                    col_name = f"Valor - {file_name_original_pdf} ({year})" 
                    temp_column_data = pd.Series(index=all_balance_concepts_display_order, dtype=object)

                    for concept_to_display in all_balance_concepts_display_order:
                        standard_name_no_indent = concept_to_display.strip() 

                        if standard_name_no_indent in balance_data_usd and isinstance(balance_data_usd[standard_name_no_indent], (int, float)):
                            temp_column_data.loc[concept_to_display] = balance_data_usd[standard_name_no_indent]
                        elif standard_name_no_indent in [cat_item[0] for category_list in BALANCE_SHEET_STRUCTURE.values() for cat_item in category_list if isinstance(cat_item, tuple)]: 
                            pass 
                        elif standard_name_no_indent in BALANCE_SHEET_STRUCTURE.keys(): 
                             temp_column_data.loc[concept_to_display] = "" 
                        else: 
                             pass 
                    
                df_balance_combined[col_name] = temp_column_data 
                
            for col in df_balance_combined.columns:
                df_balance_combined[col] = df_balance_combined[col].apply(
                    lambda x: f"{x:,.2f}" if isinstance(x, (int, float)) else ("" if pd.isna(x) else x)
                )
            
            st.dataframe(df_balance_combined) 

            st.subheader("Estado de Pérdidas y Ganancias (Valores en USD)")

            df_pnl_combined = pd.DataFrame(index=PNL_STANDARD_CONCEPTS) 

            for file_name_original_pdf, file_years_data in _final_data_for_display.items():
                for year, converted_data_for_year in sorted(file_years_data.items()): 
                    pnl_data_usd = converted_data_for_year.get("EstadoResultadosUSD", {})

                    col_name = f"Valor - {file_name_original_pdf} ({year})" 
                    temp_column_data = pd.Series(index=PNL_STANDARD_CONCEPTS, dtype=object) 
                    
                    for standard_item_name in PNL_STANDARD_CONCEPTS: 
                        if standard_item_name in pnl_data_usd:
                            temp_column_data.loc[standard_item_name] = pnl_data_usd[standard_item_name]
                        else:
                            temp_column_data.loc[standard_item_name] = "" 
                
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
