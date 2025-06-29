import os
import tempfile
import json
import gradio as gr
from processing import extract_financial_data_from_path, get_exchange_rate, convert_to_usd

# Carga variables de entorno desde .env (localmente)
from dotenv import load_dotenv
load_dotenv()

def process_pdf(pdf_file):
    # Guarda el PDF en disco
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.write(pdf_file.read())
    tmp.close()

    # Extrae datos financieros
    reports = extract_financial_data_from_path(tmp.name)

    # Convierte cada reporte a USD
    final = {}
    for key, data in reports.items():
        year = data["Año"]
        curr = data["Moneda"]
        rate = get_exchange_rate(curr, year)
        calc = data.get("Calculated", {})
        usd = convert_to_usd(calc, rate)
        final[key] = usd

    # Devuelve JSON formateado
    return json.dumps(final, indent=2, ensure_ascii=False)

# Define la interfaz
demo = gr.Interface(
    fn=process_pdf,
    inputs=gr.File(label="Sube tu estado financiero (PDF)"),
    outputs=gr.Textbox(label="Resultado JSON"),
    title="Extractor y Conversor de Estados Financieros",
    description="Carga un PDF y obtén los datos clave convertidos a USD en JSON."
)

if __name__ == "__main__":
    # En producción HF Spaces no necesita server_name ni share
    demo.launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", 7860)))
