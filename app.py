import streamlit as st
import pandas as pd
import google.generativeai as genai
import os, json, tempfile, io, re

# --------------------------------------------------
# ENVUELVE TODA LA LÓGICA EN UN try/except PARA ATRAPAR ERRORES
# --------------------------------------------------
try:
    # --- Tu prompt completo para Gemini ---
    # Este prompt ha sido modificado para ser más explícito sobre las cuentas
    # que se esperan en el Balance General y el Estado de Resultados.
    # También se incluye una estructura de JSON de ejemplo para guiar al modelo.
    PROMPT_EXTRACTION = """
    Analiza cuidadosamente el siguiente documento PDF que contiene estados financieros.

    **Objetivo Principal:** Extraer los datos financieros del Balance General y del Estado de Pérdidas y Ganancias para CADA COLUMNA de DICIEMBRE (ej. "DICIEMBRE 2024", "DICIEMBRE 2023") que encuentres en el documento. Si no hay columnas de DICIEMBRE, extrae los datos para las ÚLTIMAS 2 COLUMNAS de fecha disponibles.

    **Paso 1: Identificación de Moneda y Años.**
    - **Moneda Global:** Código ISO (USD, EUR, MXN, COP, CLP, PEN). Infierelo por país si no aparece.
    - **Unidad (Escala):** "millones", "miles", etc. (Si no se especifica, asume que los valores están en la unidad base).
    - **Años de Reporte:** Busca columnas de DICIEMBRE o las dos últimas fechas.

    **Paso 2: Extracción exacta de cuentas y valores.**
    - Valores numéricos tal cual aparecen en el documento (sin multiplicar por la escala, si la hay).
    - Nombres exactos de las cuentas como aparecen en el documento.

    **Para el Balance General, extrae las siguientes cuentas si están presentes, con sus valores numéricos exactos:**
    - Activos Corrientes
        - Inventarios
        - Efectivo y equivalentes de efectivo
        - Cuentas por cobrar
        - Gasto Anticipado
        - Otros activos
    - Pasivos a Corto Plazo
        - Cuentas por Pagar
        - Impuestos Corrientes (Pasivo)
    - Patrimonio Atribuible a los Propietarios de la Matriz
        - Capital social
        - Capital Variable
        - Resultados Ejerc. Anteriores
        - Resultado del Ejercicio

    **Para el Estado de Pérdidas y Ganancias, extrae las siguientes cuentas si están presentes, con sus valores numéricos exactos:**
    - Ingresos por Ventas
    - Costo de Ventas
    - Ganancia Bruta
    - Gastos de Operación
    - Ganancia (Pérdida) de Operación
    - Ingresos (Gastos) Financieros
    - Impuesto a la Renta
    - Ganancia (Pérdida) Neta

    **Formato de salida (solo JSON):**
    ```json
    {
      "Moneda": "USD",
      "Unidad": "unidad_base", // o "miles", "millones", etc.
      "ReportesPorAnio": [
        {
          "Anio": "2024",
          "BalanceGeneral": {
            "Activos Corrientes": {
              "Inventarios": 123.45,
              "Efectivo y equivalentes de efectivo": 67.89,
              "Cuentas por cobrar": 10.11,
              "Gasto Anticipado": 5.00,
              "Otros activos": 20.00
            },
            "Pasivos a Corto Plazo": {
              "Cuentas por Pagar": 50.00,
              "Impuestos Corrientes (Pasivo)": 5.00
            },
            "Patrimonio Atribuible a los Propietarios de la Matriz": {
              "Capital social": 100.00,
              "Capital Variable": 20.00,
              "Resultados Ejerc. Anteriores": 30.00,
              "Resultado del Ejercicio": 40.00
            }
          },
          "EstadoResultados": {
            "Ingresos por Ventas": 1000.00,
            "Costo de Ventas": 500.00,
            "Ganancia Bruta": 500.00,
            "Gastos de Operación": 200.00,
            "Ganancia (Pérdida) de Operación": 300.00,
            "Ingresos (Gastos) Financieros": 10.00,
            "Impuesto a la Renta": 50.00,
            "Ganancia (Pérdida) Neta": 260.00
          }
        }
      ]
    }
    ```
    Responde únicamente con ese JSON.
    """

    # --- Configuración de la API de Gemini ---
    if "GOOGLE_API_KEY" not in st.secrets:
        st.error("Error: falta la clave GOOGLE_API_KEY en Streamlit Secrets. Asegúrate de configurarla.")
        st.stop()
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])

    # --- Definición de estructura y sinónimos ---
    # Se han mejorado los sinónimos para incluir más variaciones comunes
    # y para asegurar que tanto las categorías como las subcuentas
    # puedan ser identificadas si Gemini las devuelve.

    BALANCE_SHEET_STRUCTURE = {
        "Activos Corrientes": [
            ("Inventarios", ["inventarios", "inventario equipos", "existencias"]),
            ("Efectivo y equivalentes de efectivo", ["efectivo y equivalentes de efectivo", "bancos", "caja", "fondo fijo de caja", "caja y bancos", "disponible"]),
            ("Cuentas por cobrar", ["cuentas por cobrar", "clientes", "deudores diversos", "documentos por cobrar", "clientes netos", "cuentas por cobrar comerciales"]),
            ("Gasto Anticipado", ["gastos pagados por anticipado", "impuestos a favor", "pagos provisionales", "pagos anticipados", "desembolsos anticipados"]),
            ("Otros activos", ["otros activos", "activos financieros", "activos no corrientes disponibles para la venta", "inversiones a largo plazo"])
        ],
        "Pasivos a Corto Plazo": [
            ("Cuentas por Pagar", ["proveedores", "acreedores diversos", "cuentas por pagar comerciales", "documentos por pagar", "pasivos comerciales"]),
            ("Impuestos Corrientes (Pasivo)", ["impuestos y derechos por pagar", "impuesto sobre la renta por pagar", "impuestos por pagar", "IVA por pagar"])
        ],
        "Patrimonio Atribuible a los Propietarios de la Matriz": [
            ("Capital social", ["capital social", "capital aportado"]),
            ("Capital Variable", ["capital variable", "acciones ordinarias"]),
            ("Resultados Ejerc. Anteriores", ["resultado de ejercicios anteriores", "utilidades retenidas", "reservas", "superávit acumulado"]),
            ("Resultado del Ejercicio", ["resultado del ejercicio", "utilidad del periodo", "pérdida del periodo", "resultado neto"])
        ]
    }

    # Construir lista de conceptos y diccionario de sinónimos
    BALANCE_SHEET_STANDARD_CONCEPTS_LIST = []
    BALANCE_SHEET_SYNONYMS = {}

    # Agrega las categorías principales al diccionario de sinónimos si Gemini las devuelve como claves directas
    for cat in BALANCE_SHEET_STRUCTURE.keys():
        BALANCE_SHEET_SYNONYMS[cat.lower()] = cat # Mapea la categoría a sí misma estandarizada
        BALANCE_SHEET_STANDARD_CONCEPTS_LIST.append(cat) # Agrega la categoría a la lista

    for cat, items in BALANCE_SHEET_STRUCTURE.items():
        for std, syns in items:
            BALANCE_SHEET_STANDARD_CONCEPTS_LIST.append(f"    {std}") # Usa sangría para sub-conceptos
            for s in syns:
                BALANCE_SHEET_SYNONYMS[s.lower()] = std # Mapea los sinónimos a su nombre estándar

    # Conceptos estándar para el Estado de Pérdidas y Ganancias
    PNL_STANDARD_CONCEPTS = [
        "Ingresos por Ventas", "Costo de Ventas", "Ganancia Bruta",
        "Gastos de Operación", "Ganancia (Pérdida) de Operación",
        "Ingresos (Gastos) Financieros", "Impuesto a la Renta", "Ganancia (Pérdida) Neta"
    ]

    # Sinónimos para el Estado de Pérdidas y Ganancias
    PNL_SYNONYMS = {
        "ingresos": "Ingresos por Ventas",
        "ingresos operativos": "Ingresos por Ventas",
        "ventas netas": "Ingresos por Ventas",
        "costo de ingresos": "Costo de Ventas",
        "costo de bienes vendidos": "Costo de Ventas",
        "utilidad bruta": "Ganancia Bruta",
        "margen bruto": "Ganancia Bruta",
        "gastos de operación": "Gastos de Operación",
        "gastos administrativos": "Gastos de Operación",
        "gastos de venta": "Gastos de Operación",
        "gastos generales": "Gastos de Operación",
        "utilidad de operación": "Ganancia (Pérdida) de Operación",
        "pérdida de operación": "Ganancia (Pérdida) de Operación",
        "resultado operacional": "Ganancia (Pérdida) de Operación",
        "ingresos financieros": "Ingresos (Gastos) Financieros",
        "gastos financieros": "Ingresos (Gastos) Financieros",
        "intereses": "Ingresos (Gastos) Financieros",
        "impuesto sobre la renta": "Impuesto a la Renta",
        "impuestos a la utilidad": "Impuesto a la Renta",
        "utilidad neta": "Ganancia (Pérdida) Neta",
        "resultado neto": "Ganancia (Pérdida) Neta",
        "pérdida neta": "Ganancia (Pérdida) Neta"
    }

    # Tasas de cambio de ejemplo (puedes expandir esto o cargarlo de una fuente externa)
    EXCHANGE_RATES_BY_YEAR_TO_USD = {
        2024: {"MXN": 0.058, "USD": 1.0, "COP": 0.00025, "CLP": 0.0010, "PEN": 0.27},
        2025: {"MXN": 0.057, "USD": 1.0, "COP": 0.00026, "CLP": 0.0011, "PEN": 0.28}
    }

    def get_exchange_rate(code, year):
        """Obtiene la tasa de cambio para una moneda y año dados, asumiendo 1.0 para USD."""
        code = code.upper()
        # Si la moneda es USD o no hay tasa definida, usa 1.0
        return EXCHANGE_RATES_BY_YEAR_TO_USD.get(year, {}).get(code, 1.0)

    def normalize_numeric(v):
        """
        Normaliza un valor a float. Maneja cadenas con comas, paréntesis para negativos,
        y devuelve None si la conversión falla.
        """
        if isinstance(v, str):
            # Eliminar comas de miles
            v = v.replace(",", "")
            # Manejar paréntesis para números negativos (ej. (1,000.00) -> -1000.00)
            if v.startswith("(") and v.endswith(")"):
                v = "-" + v[1:-1]
            try:
                return float(v)
            except ValueError:
                return None # Devuelve None si no se puede convertir
        return v # Si ya es int o float, lo devuelve tal cual

    @st.cache_data(show_spinner=True) # Mostrar spinner para operaciones largas
    def extract_financial_data(file_obj):
        """
        Extrae datos financieros de un PDF usando la API de Gemini.
        Sube el archivo temporalmente y lo borra después.
        """
        name = file_obj.name
        st.info(f"Procesando archivo: {name}...") # Mensaje informativo
        
        # Guardar el archivo cargado en un archivo temporal
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(file_obj.read())
            path = tmp.name

        out = {}
        part = None # Inicializar part para asegurar que siempre esté definida
        try:
            # Subir el archivo a Gemini
            part = genai.upload_file(path=path, display_name=name)
            # Generar contenido con el prompt y el archivo
            resp = genai.GenerativeModel("gemini-1.5-flash") \
                        .generate_content([PROMPT_EXTRACTION, part], stream=False)
            
            st.subheader(">>> RESPUESTA RAW DE GEMINI:")
            st.text(resp.text) # Mostrar la respuesta completa de Gemini para depuración

            # Extraer el JSON de la respuesta de Gemini
            m = re.search(r"(\{.*\})", resp.text, flags=re.DOTALL)
            if not m:
                st.error(f"No se pudo aislar un JSON válido de Gemini para {name}.")
                return {} # Devuelve vacío si no se encuentra JSON
            
            obj = json.loads(m.group(1))

            # Procesar los reportes por año
            for rpt in obj.get("ReportesPorAnio", []):
                yr = int(rpt.get("Anio", 0))
                if yr == 0: continue # Saltar si el año no es válido
                
                key = f"{name} ({yr})" # Clave única para cada reporte (archivo_año)
                
                # Normalizar y limpiar los datos extraídos
                # Aquí es crucial asegurarse de que los valores de 'BalanceGeneral'
                # sean procesados correctamente, incluso si están anidados.
                bg_raw = rpt.get("BalanceGeneral", {})
                er_raw = rpt.get("EstadoResultados", {})

                # Función auxiliar para normalizar valores en diccionarios anidados
                def normalize_dict_values(d):
                    normalized_d = {}
                    for k, v in d.items():
                        if isinstance(v, dict):
                            normalized_d[k] = normalize_dict_values(v)
                        else:
                            normalized_d[k] = normalize_numeric(v)
                    return normalized_d

                bg_normalized = normalize_dict_values(bg_raw)
                er_normalized = normalize_dict_values(er_raw)

                out[key] = {
                    "Moneda": obj.get("Moneda", "USD"),
                    "Unidad": obj.get("Unidad", "unidad_base"), # Captura la unidad si Gemini la infiere
                    "BalanceGeneral": bg_normalized,
                    "EstadoResultados": er_normalized,
                    "Año": yr
                }
        except Exception as e:
            st.error(f"Error al procesar el archivo {name}: {e}")
        finally:
            # Asegurarse de limpiar el archivo temporal y el archivo de Gemini
            if os.path.exists(path):
                os.remove(path)
            if part: # Solo intentar borrar si 'part' fue creado
                try:
                    genai.delete_file(part.name)
                except Exception as e:
                    st.warning(f"No se pudo eliminar el archivo de Gemini '{part.name}': {e}")

        return out

    # Función para mapear y agregar datos del Balance General
    def map_and_aggregate_balance(bg_data):
        agg = {c: 0.0 for c in BALANCE_SHEET_STANDARD_CONCEPTS_LIST}

        # Función recursiva para buscar valores numéricos en cualquier nivel del diccionario
        def recurse_and_map(d):
            for k, v in d.items():
                if isinstance(v, dict):
                    recurse_and_map(v) # Recorrer diccionarios anidados
                elif isinstance(v, (int, float)):
                    # Intentar mapear la clave a un sinónimo estandarizado
                    std_name = BALANCE_SHEET_SYNONYMS.get(k.lower())
                    if std_name:
                        # Si es una categoría principal, sumarla directamente
                        if std_name in BALANCE_SHEET_STRUCTURE.keys():
                            agg[std_name] += v
                        # Si es un sub-concepto, sumarlo a su entrada con sangría
                        elif f"    {std_name}" in agg:
                             agg[f"    {std_name}"] += v
                        elif std_name in agg: # Fallback por si acaso no tiene sangría
                            agg[std_name] += v
                    # Considerar también el caso donde la clave ya es un nombre estándar (sinónimos no usados)
                    elif k in BALANCE_SHEET_STRUCTURE.keys(): # Si es una categoría directa
                        agg[k] += v
                    elif f"    {k}" in agg: # Si es un sub-concepto directo
                        agg[f"    {k}"] += v
                    else:
                        st.warning(f"Cuenta de Balance General no mapeada o sin sinónimo: '{k}' con valor {v}")
        
        recurse_and_map(bg_data)
        return agg

    # Función para mapear y agregar datos del Estado de Pérdidas y Ganancias
    def map_and_aggregate_pnl(er_data):
        agg = {c: 0.0 for c in PNL_STANDARD_CONCEPTS}

        # Similar función recursiva para PNL
        def recurse_and_map(d):
            for k, v in d.items():
                if isinstance(v, dict):
                    recurse_and_map(v)
                elif isinstance(v, (int, float)):
                    std_name = PNL_SYNONYMS.get(k.lower())
                    if std_name and std_name in agg:
                        agg[std_name] += v
                    elif k in agg: # Si la clave ya es un nombre estándar de PNL
                        agg[k] += v
                    else:
                        st.warning(f"Cuenta de P&L no mapeada o sin sinónimo: '{k}' con valor {v}")

        recurse_and_map(er_data)
        return agg

    # Función para convertir valores a USD (aplica escala si es necesario)
    def convert_to_usd(data_dict, rate, unit):
        converted_data = {}
        scale_factor = 1.0
        if unit.lower() == "miles":
            scale_factor = 1_000
        elif unit.lower() == "millones":
            scale_factor = 1_000_000
        # Puedes añadir más unidades si es necesario

        for k, v in data_dict.items():
            if isinstance(v, (int, float)):
                converted_data[k] = v * rate * scale_factor
            else:
                converted_data[k] = v
        return converted_data

    # --- Streamlit App ---
    st.set_page_config(layout="wide", page_title="Bot de Análisis Financiero")
    st.title("📊 Bot de Análisis de Estados Financieros → USD")
    st.markdown("""
        Sube tus PDFs de estados financieros para extraer y consolidar los datos.
        Los resultados se mostrarán en USD y podrás descargarlos en un archivo Excel.
    """)

    files = st.file_uploader(
        "Sube tus PDFs de Balance General y Estado de Pérdidas y Ganancias (máx. 4 archivos a la vez)",
        type="pdf",
        accept_multiple_files=True
    )

    if files:
        if st.button("🚀 Procesar y Convertir a USD"):
            all_data = {}
            # Mostrar barra de progreso para la extracción
            extraction_progress_bar = st.progress(0)
            for i, f in enumerate(files):
                st.info(f"Extrayendo datos de: {f.name}...")
                extracted_file_data = extract_financial_data(f)
                all_data.update(extracted_file_data)
                extraction_progress_bar.progress((i + 1) / len(files))
            
            extraction_progress_bar.empty() # Ocultar barra al finalizar

            if not all_data:
                st.error("❌ No se extrajeron datos válidos de los PDFs. Por favor, revisa los archivos y el prompt.")
                st.stop()

            st.success("✅ Datos extraídos y procesados exitosamente!")

            # Preparar DataFrames para el Balance General y P&L
            bg_idx = BALANCE_SHEET_STANDARD_CONCEPTS_LIST
            pnl_idx = PNL_STANDARD_CONCEPTS
            
            df_bg_data = [] # Lista para recolectar los datos del Balance General
            df_pnl_data = [] # Lista para recolectar los datos del P&L
            
            # Recolectar nombres de columnas dinámicamente para evitar desorden si los años varían
            all_columns = sorted(all_data.keys())

            # Preparar los DataFrames vacíos con las columnas dinámicas
            df_bg = pd.DataFrame(index=bg_idx, columns=all_columns)
            df_pnl = pd.DataFrame(index=pnl_idx, columns=all_columns)

            for key, info in all_data.items():
                name_part, yr_part = key.rsplit(" ", 1) # Separar "nombre_archivo (año)"
                yr = int(yr_part.strip("()"))
                
                currency = info.get("Moneda", "USD")
                unit = info.get("Unidad", "unidad_base") # Obtener la unidad reportada por Gemini
                rate = get_exchange_rate(currency, yr)

                st.write(f"--- Procesando reporte: {key} (Moneda: {currency}, Tasa: {rate:.4f}, Unidad: {unit}) ---")

                # Mapear y agregar Balance General
                bg_agg = map_and_aggregate_balance(info["BalanceGeneral"])
                bg_usd = convert_to_usd(bg_agg, rate, unit)
                
                # Mapear y agregar Estado de Resultados
                er_agg = map_and_aggregate_pnl(info["EstadoResultados"])
                er_usd = convert_to_usd(er_agg, rate, unit)

                # Asignar valores al DataFrame del Balance General
                for concept in bg_idx:
                    # Eliminar la sangría para la clave de búsqueda si es un sub-concepto
                    clean_concept = concept.lstrip(' ') 
                    val = bg_usd.get(clean_concept, 0.0) # Buscar por el nombre limpio
                    df_bg.loc[concept, key] = f"{val:,.2f}"

                # Asignar valores al DataFrame del P&L
                for concept in pnl_idx:
                    val = er_usd.get(concept, 0.0)
                    df_pnl.loc[concept, key] = f"{val:,.2f}"
            
            # Ordenar las columnas alfabéticamente para una mejor visualización
            df_bg = df_bg[sorted(df_bg.columns)]
            df_pnl = df_pnl[sorted(df_pnl.columns)]


            st.subheader("📊 Balance General (USD)")
            st.dataframe(df_bg)

            st.subheader("📈 Estado de Pérdidas y Ganancias (USD)")
            st.dataframe(df_pnl)

            # Botón de descarga para Excel
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
                df_bg.to_excel(writer, sheet_name="BalanceGeneral_USD")
                df_pnl.to_excel(writer, sheet_name="EstadoResultados_USD")
            buf.seek(0) # Regresar al inicio del buffer
            
            st.download_button(
                "Descargar Estados Financieros en Excel",
                data=buf,
                file_name="EstadosFinancieros_USD.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

# --------------------------------------------------
# SI ALGO FALLA, SE MUESTRA EL TRACEBACK COMPLETO
# --------------------------------------------------
except Exception as e:
    st.error("Se produjo un error inesperado en la aplicación. Por favor, intenta de nuevo o contacta al soporte.")
    st.exception(e) # Muestra el traceback completo para depuración
