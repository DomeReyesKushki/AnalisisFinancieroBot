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
        ("Efectivo y equivalentes de efectivo", ["Efectivo y equivalentes de efectivo", "Efectivo y depósitos", "Bancos", "Caja", "Caja y Bancos"]), 
        ("Cuentas por cobrar", ["Cuentas por cobrar", "Clientes", "Deudores", "Cuentas por cobrar comerciales", "Cuentas por cobrar a empresas relacionadas CP", "Deudores diversos"]), 
        ("Gasto Anticipado", ["Gasto Anticipado", "Gastos pagados por anticipado", "Pagos anticipados"]), 
        ("Otros activos", ["Otros activos", "Otros activos corrientes", "Activos por Impuestos", "Otros Activos", "Activos financieros"]), # Añadido Activos financieros aquí
        ("Total Activo Corriente", ["Total Activo Corriente", "Total Activo a Corto Plazo", "Total Activo Corriente Netos"]) 
    ],
    "Activos No Corrientes": [
        ("Propiedad, planta y equipo", ["Propiedad, planta y equipo", "Propiedad Planta y Equipo", "Activo Fijo", "Activo Fijo Neto"]), 
        ("Intangibles (Software)", ["Intangibles (Software)", "Intangibles"]), 
        ("Otros Activos No Corrientes", ["Otros Activos No Corrientes", "Activos diferidos", "Otros activos no corrientes", "Activos a largo plazo"]),
        ("Total Activo No Corriente", ["Total Activo No Corriente", "Total Activo Fijo", "Total Activo a largo plazo"]) 
    ],
    "TOTAL ACTIVOS": [("TOTAL ACTIVOS", ["TOTAL ACTIVOS", "Total Activo", "SUMA DEL ACTIVO"])], # Añadido SUMA DEL ACTIVO
    "Pasivos a Corto Plazo": [
        ("Préstamos y empréstitos corrientes", ["Préstamos y empréstitos corrientes", "Préstamos bancarios a corto plazo"]),
        ("Obligaciones Financieras", ["Obligaciones Financieras", "Préstamos"]), 
        ("Cuentas comerciales y otras cuentas por pagar", ["Cuentas comerciales y otras cuentas por pagar", "Acreedores diversos", "Proveedores"]), # Añadido Proveedores
        ("Cuentas por Pagar", ["Cuentas por Pagar", "Proveedores"]), 
        ("Pasivo Laborales", ["Pasivo Laborales", "Provisiones para sueldos y salarios", "Remuneraciones por pagar", "Provisión de sueldos y salarios x pagar", "Provisión de contribuciones segsocial x pagar"]), # Añadido sinónimos específicos
        ("Anticipos", ["Anticipos", "Anticipos de clientes"]), 
        ("Impuestos Corrientes (Pasivo)", ["Impuestos Corrientes (Pasivo)", "Impuestos por pagar", "Pasivo por impuestos", "Impuestos trasladados cobrados", "Impuestos trasladados no cobrados", "Impuestos y derechos por pagar"]), # Añadido sinónimos específicos
        ("Otros pasivos corrientes", ["Otros pasivos corrientes"]),
        ("Total Pasivo Corriente", ["Total Pasivo Corriente", "Total Pasivo a Corto Plazo"]) 
    ],
    "Pasivos a Largo Plazo": [
        ("Préstamos y empréstitos no corrientes", ["Préstamos y empréstitos no corrientes", "Préstamos bancarios a largo plazo"]),
        ("Obligaciones Financieras No Corrientes", ["Obligaciones Financieras No Corrientes", "Obligaciones Financieras"]), 
        ("Anticipos y Avances Recibidos", ["Anticipos y Avances Recibidos", "Depósitos en garantía"]), # Añadido Depósitos en garantía
        ("Otros pasivos no corrientes", ["Otros pasivos no corrientes", "Ingresos diferidos"]),
        ("Total Pasivo No Corriente", ["Total Pasivo No Corriente", "Total Pasivo a largo plazo"]) 
    ],
    "TOTAL PASIVOS": [("TOTAL PASIVOS", ["TOTAL PASIVOS", "Total Pasivo", "SUMA DEL PASIVO"])], # Añadido SUMA DEL PASIVO
    "Patrimonio Atribuible a los Propietarios de la Matriz": [
        ("Capital social", ["Capital social", "Capital Emitido", "Capital Social"]), 
        ("Aportes Para Futuras Capitalizaciones", ["Aportes Para Futuras Capitalizaciones"]), 
        ("Resultados Ejerc. Anteriores", ["Resultados Ejerc. Anteriores", "Ganancias retenidas"]), 
        ("Resultado del Ejercicio", ["Resultado del Ejercicio", "Utilidad del período", "Utilidad o Pérdida del Ejercicio"]), 
        ("Otros componentes del patrimonio", ["Otros componentes del patrimonio", "Otras reservas", "Patrimonio Minoritario", "Impuestos retenidos"]), # Impuestos retenidos como patrimonio negativo
        ("TOTAL PATRIMONIO", ["TOTAL PATRIMONIO", "Total Patrimonio", "SUMA DEL CAPITAL"]) 
    ],
    "TOTAL PASIVO Y PATRIMONIO": [("TOTAL PASIVO Y PATRIMONIO", ["TOTAL PASIVO Y PATRIMONIO", "Total Pasivo y Patrimonio", "SUMA DEL PASIVO Y CAPITAL"])] 
}

# Diccionario de sinónimos para facilitar el mapeo en el código
BALANCE_SHEET_SYNONYMS = {}
for main_category, items_list in BALANCE_SHEET_STRUCTURE.items():
    for standard_name, synonyms in items_list: 
        for syn in synonyms:
            BALANCE_SHEET_SYNONYMS[syn.lower()] = standard_name

PNL_STANDARD_ITEMS_MAP = {
    "Ingresos por Ventas": ["Ingresos por Ventas", "Ventas Netas", "Ingresos Operacionales", "Ingresos"],
    "Costo de Ventas": ["Costo de Ventas", "Costo de Bienes Vendidos", "Costos"],
    "Ganancia Bruta": ["Ganancia Bruta", "Margen Bruto"], 
    "Gastos de Operación": ["Gastos de Operación", "Gastos de Administración", "Gastos de Venta", "Gastos Operacionales", "Gastos generales"],
    "Ganancia (Pérdida) de Operación": ["Ganancia (Pérdida) de Operación", "Utilidad Operacional", "EBITDA", "Utilidad (o Pérdida)"],
    "Ingresos (Gastos) Financieros": ["Ingresos (Gastos) Financieros", "Gastos Financieros", "Ingresos Financieros", "Resultado Integral de Financiamiento"],
    "Impuesto a la Renta": ["Impuesto a la Renta", "Gasto por Impuestos", "Impuesto sobre la Renta"],
    "Ganancia (Pérdida) Neta": ["Ganancia (Pérdida) Neta", "Utilidad Neta", "Resultado del Período", "Resultado del Ejercicio"]
}

PNL_SYNONYMS = {}
for standard_name, synonyms in PNL_STANDARD_ITEMS_MAP.items():
    for syn in synonyms:
        PNL_SYNONYMS[syn.lower()] = standard_name


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

        prompt = f"""
        Analiza cuidadosamente el siguiente documento PDF que contiene estados financieros.

        **Objetivo Principal:** Extraer los datos financieros del Balance General y del Estado de Pérdidas y Ganancias para CADA COLUMNA de DICIEMBRE (ej. "DICIEMBRE 2024", "DICIEMBRE 2023") que encuentres en el documento. Si no hay columnas de DICIEMBRE, entonces extrae los datos para las ÚLTIMAS 2 COLUMNAS de fecha disponibles (generalmente años fiscales).

        **Paso 1: Identificación de Moneda, Unidad de Magnitud y Años de Reporte.**
        -   **Moneda Global:** Identifica la moneda principal. Busca símbolos de moneda ($, €, S/, Bs), códigos ISO (USD, EUR, MXN, COP, CLP, PEN), o palabras como "Pesos Mexicanos", "Pesos Colombianos", "Soles Peruanos", "Dólares", "Euros". Si el documento menciona el país de la empresa (ej. "Mexico", "Colombia", "Chile"), infiere la moneda local si no está explícitamente definida (ej. "Mexico" -> MXN, "Colombia" -> COP, "Chile" -> CLP, "Perú" -> PEN). Extrae el código ISO o abreviatura más común (COP, CLP, MXN, USD, EUR, PEN). Si no se puede inferir con certeza, usa "USD" como valor por defecto.
        -   **Unidad Global (Escala):** Identifica la unidad de los valores. Si el documento dice "CLP$m", "US$m", "Expresado en millones", la unidad es "millones". Si dice "miles de pesos", la unidad es "miles". Si no indica, asume "unidades".
        -   **Años de Reporte:** Identifica TODOS los años de las columnas de DICIEMBRE disponibles (ej. 2024, 2023). Si no hay DICIEMBRE, identifica los años de las últimas 2 columnas de fecha disponibles.

        **Paso 2: Extracción de Valores y Encasillamiento Estricto para Balance General (por Año).**
        Para cada año/columna de fecha identificada (DICIEMBRE 2024, DICIEMBRE 2023, o las dos últimas columnas), extrae los valores NUMÉRICOS.
        **MUY IMPORTANTE:** Los valores numéricos SIEMPRE deben ser el **VALOR COMPLETO EN UNIDADES BASE de la moneda**, aplicando la multiplicación por "millones" (1,000,000) o "miles" (1,000) si la "Unidad Global" del Paso 1 lo indica. Por ejemplo, si el documento dice "1.485.361" y la unidad es "millones", el valor devuelto debe ser 1485361000000. Si dice "374.192" y es "miles", el valor debe ser 374192000. Si no indica unidad o es "unidades", devuelve el número tal cual.
        Sé flexible con los nombres de las cuentas que encuentres en el documento y encasíllalas en las categorías ESTÁNDAR proporcionadas. Si una cuenta no encaja, omítela o déjala como "N/A".

        **Categorías ESTÁNDAR de Balance General y COINCIDENCIAS ESTRICTAS:**
        -   **Activos Corrientes:**
            -   "Efectivo y equivalentes de efectivo": valor
            -   "Cuentas por cobrar": valor
            -   "Cuentas por cobrar a empresas relacionadas CP": valor
            -   "Inventario Equipos": valor
            -   "Gasto Anticipado": valor
            -   "Otros activos": valor
            "Total Activo Corriente": valor
        -   **Activos No Corrientes:**
            -   "Propiedad, planta y equipo": valor
            -   "Activo Fijo": valor
            -   "Intangibles (Software)": valor
            -   "Otros Activos No Corrientes": valor
            "Total Activo No Corriente": valor
        -   **TOTAL ACTIVOS**: valor
        -   **Pasivos a Corto Plazo:**
            -   "Préstamos y empréstitos corrientes": valor
            -   "Obligaciones Financieras": valor
            -   "Cuentas comerciales y otras cuentas por pagar": valor
            -   "Cuentas por Pagar": valor
            -   "Pasivo Laborales": valor
            -   "Anticipos": valor
            -   "Impuestos Corrientes (Pasivo)": valor
            -   "Impuestos por pagar": valor
            "Otros pasivos corrientes": valor
            "Total Pasivo Corriente": valor
        -   **Pasivos a Largo Plazo:** (Si no están explícitamente listados, omite esta sección.)
            -   "Préstamos y empréstitos no corrientes": valor
            -   "Obligaciones Financieras No Corrientes": valor
            -   "Anticipos y Avances Recibidos": valor
            -   "Otros pasivos no corrientes": valor
            "Total Pasivo No Corriente": valor
        -   **TOTAL PASIVOS**: valor
        -   **Patrimonio Atribuible a los Propietarios de la Matriz:**
            -   "Capital social": valor
            -   "Capital Emitido": valor
            -   "Aportes Para Futuras Capitalizaciones": valor
            -   "Resultados Ejerc. Anteriores": valor
            -   "Resultado del Ejercicio": valor
            -   "Otros componentes del patrimonio": valor
            "TOTAL PATRIMONIO": valor
        -   **TOTAL PASIVO Y PATRIMONIO**: valor

        **Paso 3: Extracción de Estado de Pérdidas y Ganancias (por Año, si presente).**
        Si el documento contiene un Estado de Pérdidas y Ganancias, extrae los valores para las mismas columnas de años identificadas en el Paso 1 para las siguientes categorías ESTÁNDAR:
        -   "Ingresos por Ventas"
        -   "Costo de Ventas"
        -   "Ganancia Bruta"
        -   "Gastos de Operación"
        -   "Ganancia (Pérdida) de Operación"
        -   "Ingresos (Gastos) Financieros"
        -   "Impuesto a la Renta"
        -   "Ganancia (Pérdida) Neta"

        **Formato de Salida Requerido:**
        Proporciona la salida en formato JSON con la siguiente estructura. Las claves de los años (ej. "2024") deben ser strings.

        {{
          "Moneda": "COP",
          "Unidad": "miles",
          "ReportesPorAnio": [
            {{
              "Anio": "2024",
              "BalanceGeneral": {{ 
                "Activos Corrientes": {{ "Efectivo y equivalentes de efectivo": valor, ... }},
                "TOTAL ACTIVOS": valor,
                ...
              }},
              "EstadoResultados": {{ 
                "Ingresos por Ventas": valor,
                ...
              }}
            }},
            {{
              "Anio": "2023",
              "BalanceGeneral": {{ 
                "Activos Corrientes": {{ "Efectivo y equivalentes de efectivo": valor, ... }},
                "TOTAL ACTIVOS": valor,
                ...
              }},
              "EstadoResultados": {{ 
                "Ingresos por Ventas": valor,
                ...
              }}
            }}
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
            global_unit = data_from_gemini.get("Unidad")
            
            for report_entry in data_from_gemini.get("ReportesPorAnio", []):
                year_str = report_entry.get("Anio") 
                if year_str:
                    extracted_data_key = f"{file_name}_{year_str}" 
                    extracted_data_for_file[extracted_data_key] = { 
                        "Moneda": global_currency,
                        "Unidad": global_unit,
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


def convert_to_usd(data_dict, currency_code, report_year, unit="unidades"):
    scale_factor = 1.0
    if unit and isinstance(unit, str):
        unit_lower = unit.lower()
        if "millones" in unit_lower or "$m" in unit_lower or "mm" in unit_lower:
            scale_factor = 1_000_000.0 
        elif "miles" in unit_lower:
            scale_factor = 1_000.0 
    
    exchange_rate = get_exchange_rate(currency_code, date=report_year)
    
    st.write(f"DEBUG: Conversión - Moneda: {currency_code}, Año: {report_year}, Unidad: {unit}, Factor Escala: {scale_factor}, Tasa USD: {exchange_rate}")

    for key, value in data_dict.items():
        if isinstance(value, dict):
            converted_data[key] = convert_to_usd(value, currency_code, report_year, unit) 
        elif isinstance(value, (int, float)):
            converted_value = value * scale_factor * exchange_rate
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
                
                # Obtener los datos de BalanceGeneral y EstadoResultados directamente del JSON de Gemini
                # y luego convertirlos
                balance_data_raw = data_from_gemini.get("BalanceGeneral", {})
                pnl_data_raw = data_from_gemini.get("EstadoResultados", {})

                converted_balance_for_year = convert_to_usd(balance_data_raw, global_currency, year_int, global_unit) 
                converted_pnl_for_year = convert_to_usd(pnl_data_raw, global_currency, year_int, global_unit)
                
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
            
            all_balance_concepts_ordered = []
            for category_name, items_list in BALANCE_SHEET_STRUCTURE.items():
                all_balance_concepts_ordered.append(category_name) 
                if category_name not in ["TOTAL ACTIVOS", "TOTAL PASIVOS", "TOTAL PASIVO Y PATRIMONIO"]:
                    all_balance_concepts_ordered.extend([f"    {item_pair[0]}" for item_pair in items_list]) # Usar item_pair[0] para el nombre estándar
                else: 
                    all_balance_concepts_ordered.extend([f"    {item_pair[0]}" for item_pair in items_list]) # Usar item_pair[0] para el nombre estándar

            df_balance_combined = pd.DataFrame(index=all_balance_concepts_ordered) 
            
            for file_name_original_pdf, file_years_data in _final_data_for_display.items():
                for year, converted_data_for_year in sorted(file_years_data.items()): 
                    balance_data_usd = converted_data_for_year.get("BalanceGeneralUSD", {})
                    
                    col_name = f"Valor - {file_name_original_pdf} ({year})" 
                    temp_column_data = pd.Series(index=all_balance_concepts_ordered, dtype=object)

                    for category_name_outer, items_list_outer in BALANCE_SHEET_STRUCTURE.items():
                        if category_name_outer in balance_data_usd:
                            temp_column_data.loc[category_name_outer] = "" 

                            if isinstance(balance_data_usd.get(category_name_outer), dict): 
                                for standard_item_name, _ in items_list_outer: # Iterar sobre el nombre estándar para el orden
                                    # Buscar el valor de la cuenta extraída por Gemini usando los sinónimos
                                    found_value = None
                                    for extracted_account_name, extracted_value in balance_data_usd[category_name_outer].items():
                                        # Convertir el nombre extraído a su sinónimo estándar si existe
                                        mapped_standard_name = BALANCE_SHEET_SYNONYMS.get(extracted_account_name.lower())
                                        if mapped_standard_name == standard_item_name:
                                            found_value = extracted_value
                                            break # Encontramos el valor para este estándar
                                    
                                    if found_value is not None:
                                        temp_column_data.loc[f"    {standard_item_name}"] = found_value
                                    # else: temp_column_data.loc[f"    {standard_item_name}"] = "" # Si no se encuentra, dejar vacío o N/A

                        # Para totales directos que no son diccionarios anidados
                        elif isinstance(balance_data_usd.get(category_name_outer), (int, float)):
                            temp_column_data.loc[category_name_outer] = balance_data_usd[category_name_outer]
                    
                df_balance_combined[col_name] = temp_column_data 
                
            for col in df_balance_combined.columns:
                df_balance_combined[col] = df_balance_combined[col].apply(
                    lambda x: f"{x:,.2f}" if isinstance(x, (int, float)) else ("" if pd.isna(x) else x)
                )
            
            st.dataframe(df_balance_combined) 

            st.subheader("Estado de Pérdidas y Ganancias (Valores en USD)")

            df_pnl_combined = pd.DataFrame(index=[item_name for item_name in PNL_STANDARD_ITEMS_MAP.keys()]) # Usar las claves del mapeo para el orden

            for file_name_original_pdf, file_years_data in _final_data_for_display.items():
                for year, converted_data_for_year in sorted(file_years_data.items()): 
                    pnl_data_usd = converted_data_for_year.get("EstadoResultadosUSD", {})

                    col_name = f"Valor - {file_name_original_pdf} ({year})" 
                    temp_column_data = pd.Series(index=list(PNL_STANDARD_ITEMS_MAP.keys()), dtype=object) # Usar las claves para el índice
                    
                    for standard_item_name in PNL_STANDARD_ITEMS_MAP.keys(): # Iterar sobre el estándar PNL
                        found_value = None
                        for extracted_account_name, extracted_value in pnl_data_usd.items():
                            # Convertir el nombre extraído a su sinónimo estándar si existe
                            mapped_standard_name = PNL_SYNONYMS.get(extracted_account_name.lower())
                            if mapped_standard_name == standard_item_name:
                                found_value = extracted_value
                                break # Encontramos el valor para este estándar
                        
                        if found_value is not None:
                            temp_column_data.loc[standard_item_name] = found_value
                        # else: temp_column_data.loc[standard_item_name] = "" # Si no se encuentra, dejar vacío o N/A
                
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
