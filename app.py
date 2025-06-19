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

st.title("Bot de Análisis de Estados Financieros (DEBUG)")
st.write("Si ves este mensaje, la configuración de la API funciona.")

# st.file_uploader(...) # Comenta todo lo demás
# if uploaded_files_streamlit:
#   st.info(...)
#   if st.button(...):
#       ... (todo el resto del código) ...
