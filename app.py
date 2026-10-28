import os
import streamlit as st
import pandas as pd
import geopandas as gpd
from datetime import datetime, timedelta, date
import folium

# ==========================================
# CONFIGURAZIONE DELLA PAGINA E STILE CSS
# ==========================================
st.set_page_config(
    page_title="Dashboard Trasporti GTFS",
    page_icon="🚌",
    layout="wide"
)

# Iniezione CSS personalizzato per box, pulsanti, KPI e testi compatti
st.markdown("""
<style>
    .info-box {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-left: 5px solid #2563eb;
        padding: 15px 20px;
        border-radius: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        margin-bottom: 20px;
        color: #1e293b;
        font-size: 14px;
    }
    /* Pulsanti a icona ingranditi, centrati e perfettamente visibili */
    .stButton > button {
        width: 100% !important;
        padding: 2px 0px !important;
        font-size: 15px !important;
        min-height: 34px !important;
        max-height: 36px !important;
        border-radius: 6px !important;
    }
    /* Stile compatto per i testi delle tabelle interattive */
    .table-text {
        font-size: 12px !important;
        color: #1e293b;
        line-height: 1.3;
    }
    /* Riduzione padding per contenere i KPI senza tagli */
    [data-testid="stMetricValue"] {
        font-size: 20px !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 12px !important;
    }
</style>
""", unsafe_allow_html=True)

st.markdown("### 🚌 Dashboard Tratta e Orari GTFS")
st.markdown("<p style='color: gray; font-size: 13px;'>Analizza le singole corse, filtra per Comune o esplora l'intera offerta.</p>", unsafe_allow_html=True)

GTFS_DIR = "."
GEOJSON_FILE = "Piemonte.geojson"

# ==========================================
# CARICAMENTO DATI CON CACHE
# ==========================================
@st.cache_data
def carica_dati_gtfs():
    routes = pd.read_csv(os.path.join(GTFS_DIR, 'routes.txt'))
    trips = pd.read_csv(os.path.join(GTFS_DIR, 'trips.txt'))
    stop_times = pd.read_csv(os.path.join(GTFS_DIR, 'stop_times.txt'))
    stops = pd.read_csv(os.path.join(GTFS_DIR, 'stops.txt'))
    
    agency_path = os.path.join(GTFS_DIR, '