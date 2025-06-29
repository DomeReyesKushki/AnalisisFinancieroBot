import os
import tempfile
import json
import pandas as pd
import gradio as gr
from processing import extract_financial_data_from_path, get_exchange_rate, convert_to_usd
from dotenv import load_dotenv

# Carga variables de entorno localmente
load_dotenv()

def process_pdfs(pdf_files):
    # Si no llegó nada, devolvemos error
    if not pdf_files:
        return "No se subió ningún PDF.", None

    all_reports = {}
    # Procesar cada PDF
    for pdf in pdf_files:
        # Guardar en temporal
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        tmp.write(pdf.read())
        tmp.close()
        try:
            reports = extract_financial_data_from_path(tmp.name)
            all_reports.update(reports)
        except Exception as e:
            return f"Error procesando {pdf.name}: {e}", None

    # Convertir a USD y armar DataFrame
    rows = []
    for key, data in all_reports.items():
        year = data["Año"]
        curr = data["Moneda"]
        rate = get_exchange_rate(curr, year)
        calc = data.get("Calculated", {})
        usd_dict = convert_to_usd(calc, rate)
        usd_dict["Reporte"] = key
        rows.append(usd_dict)

    if not rows:
        return "No se extrajeron datos calculados.", None

    df = pd.DataFrame(rows)
    # Reordenar columnas opcionalmente: Reporte al inicio
    cols = ["Reporte"] + [c for c in df.columns if c != "Reporte"]
    df = df[cols]

    # Guardar a Excel
    out = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    df.to_excel(out.name, index=False)
    out.close()

    # Retornar mensaje y ruta de descarga
    return "✅ Procesado OK. Descarga tu Excel:", out.name

# Interfaz Gradio
demo = gr.Interface(
    fn=process_pdfs,
    inputs=gr.Files(label="Sube hasta 4 estados financieros (PDF)", file_count="multiple", maximum=4),
    outputs=[
        gr.Textbox(label="Mensaje"),
        gr.File(label="Descarga tu Excel")
    ],
    title="Extractor y Conversor de Estados Financieros",
    description="Carga hasta 4 PDFs y recibe un archivo Excel con los datos convertidos a USD."
)

if __name__ == "__main__":
    # En HF Spaces no hace falta share ni server_name
    demo.launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", 7860)))
