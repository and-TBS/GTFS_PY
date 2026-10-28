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
    .stButton > button {
        width: 100% !important;
        padding: 2px 0px !important;
        font-size: 15px !important;
        min-height: 34px !important;
        max-height: 36px !important;
        border-radius: 6px !important;
    }
    .table-text {
        font-size: 12px !important;
        color: #1e293b;
        line-height: 1.3;
    }
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
    
    agency_path = os.path.join(GTFS_DIR, 'agency.txt')
    agency = pd.read_csv(agency_path) if os.path.exists(agency_path) else None

    if 'route_short_name' in routes.columns:
        routes['linea'] = routes['route_short_name'].fillna(routes['route_long_name'])
    else:
        routes['linea'] = routes['route_long_name']
        
    return routes, trips, stop_times, stops, agency

@st.cache_data
def carica_geojson(filepath):
    if os.path.exists(filepath):
        gdf = gpd.read_file(filepath)
        if gdf.crs != "EPSG:4326":
            gdf = gdf.to_crs("EPSG:4326")
        return gdf
    return None

routes, trips, stop_times, stops, agency = carica_dati_gtfs()
gdf_comuni = carica_geojson(GEOJSON_FILE)

# --- ASSOCIAZIONE GEOGRAFICA FERMATE -> COMUNI ---
if gdf_comuni is not None and not stops.empty:
    try:
        if gdf_comuni.crs != "EPSG:4326":
            gdf_comuni = gdf_comuni.to_crs("EPSG:4326")

        gdf_stops = gpd.GeoDataFrame(stops.copy(), geometry=gpd.points_from_xy(stops.stop_lon, stops.stop_lat), crs="EPSG:4326")
        fermate_geo = gpd.sjoin(gdf_stops, gdf_comuni, how="left", predicate="within")
        fermate_geo = fermate_geo.drop_duplicates(subset=['stop_id'])
        
        col_comune = next((c for c in ['comune', 'COMUNE', 'Nome_Com', 'COM_NAME', 'DEN_COM', 'NAME_3', 'COMUNE_ISTAT', 'COM'] if c in fermate_geo.columns), None)
        col_prov = next((c for c in ['provincia', 'SIGLA', 'DEN_PROV', 'PROVINCIA', 'Sigla Prov', 'COD_PROV', 'PROV'] if c in fermate_geo.columns), None)
        
        if not col_comune:
            cols_testuali = [c for c in gdf_comuni.columns if c != 'geometry' and gdf_comuni[c].dtype == 'object']
            col_comune = cols_testuali[0] if cols_testuali else None

        cols_to_keep = ['stop_id']
        rename_map = {}
        if col_comune:
            cols_to_keep.append(col_comune)
            rename_map[col_comune] = 'comune_target'
        if col_prov:
            cols_to_keep.append(col_prov)
            rename_map[col_prov] = 'provincia_target'
            
        sub_geo = fermate_geo[[c for c in cols_to_keep if c in fermate_geo.columns]].copy()
        sub_geo = sub_geo.rename(columns=rename_map)
        
        stops = pd.merge(stops, sub_geo, on='stop_id', how='left')
        stops['comune'] = stops['comune_target'].fillna("N.D.") if 'comune_target' in stops.columns else "N.D."
        stops['provincia'] = stops['provincia_target'].fillna("N.D.") if 'provincia_target' in stops.columns else "N.D."
        
        if 'comune_target' in stops.columns: stops.drop(columns=['comune_target'], inplace=True)
        if 'provincia_target' in stops.columns: stops.drop(columns=['provincia_target'], inplace=True)

    except Exception:
        stops['comune'] = "N.D."
        stops['provincia'] = "N.D."
else:
    stops['comune'] = "N.D."
    stops['provincia'] = "N.D."

# Gestione Operatore
if agency is not None and 'agency_id' in routes.columns and 'agency_id' in agency.columns:
    routes = pd.merge(routes, agency[['agency_id', 'agency_name']], on='agency_id', how='left')
    route_operator_col = 'agency_name'
elif agency is not None and len(agency) > 0:
    routes['agency_name'] = agency['agency_name'].iloc[0]
    route_operator_col = 'agency_name'
else:
    routes['agency_name'] = 'Operatore Unico'
    route_operator_col = 'agency_name'

# --- CALCOLO GIORNI DI VALIDITÀ E DATE ---
calendar_path = os.path.join(GTFS_DIR, 'calendar.txt')
calendar_dates_path = os.path.join(GTFS_DIR, 'calendar_dates.txt')
service_active_dates = {}

min_global_date = date.today()
max_global_date = date.today() + timedelta(days=365)

if os.path.exists(calendar_path):
    calendar = pd.read_csv(calendar_path).drop_duplicates(subset=['service_id'])
    days_cols = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    all_dates_found = []
    for _, row in calendar.iterrows():
        s_id = row['service_id']
        try:
            start = datetime.strptime(str(int(row['start_date'])), '%Y%m%d')
            end = datetime.strptime(str(int(row['end_date'])), '%Y%m%d')
            active_dates = set()
            curr = start
            while curr <= end:
                if row.get(days_cols[curr.weekday()]) == 1:
                    active_dates.add(curr.date())
                    all_dates_found.append(curr.date())
                curr += timedelta(days=1)
            service_active_dates[s_id] = active_dates
        except Exception:
            service_active_dates[s_id] = set()

if os.path.exists(calendar_dates_path):
    calendar_dates = pd.read_csv(calendar_dates_path)
    for _, row in calendar_dates.iterrows():
        s_id = row['service_id']
        try:
            dt = datetime.strptime(str(int(row['date'])), '%Y%m%d').date()
            exc_type = row['exception_type']
            if s_id not in service_active_dates:
                service_active_dates[s_id] = set()
            if exc_type == 1:
                service_active_dates[s_id].add(dt)
                all_dates_found.append(dt)
            elif exc_type == 2:
                service_active_dates[s_id].discard(dt)
        except Exception:
            pass

if all_dates_found:
    min_global_date = min(all_dates_found)
    max_global_date = max(all_dates_found)

def get_giorni_validita(service_id):
    return len(service_active_dates.get(service_id, set()))

trips['giorni_validita'] = trips['service_id'].apply(get_giorni_validita).astype(int)

# Elaborazione capolinea, orari e Comuni di partenza/arrivo
stop_times['stop_sequence'] = pd.to_numeric(stop_times['stop_sequence'])
stop_times = stop_times.sort_values(['trip_id', 'stop_sequence'])

first_stops = stop_times.groupby('trip_id').first().reset_index()[['trip_id', 'stop_id', 'departure_time']]
first_stops.rename(columns={'stop_id': 'start_stop_id'}, inplace=True)
last_stops = stop_times.groupby('trip_id').last().reset_index()[['trip_id', 'stop_id', 'arrival_time']]
last_stops.rename(columns={'stop_id': 'end_stop_id'}, inplace=True)

trip_endpoints = pd.merge(first_stops, last_stops, on='trip_id')
stops_unique = stops.drop_duplicates(subset=['stop_id'])

trip_endpoints = pd.merge(
    trip_endpoints, stops_unique[['stop_id', 'stop_name', 'comune']], 
    left_on='start_stop_id', right_on='stop_id', how='left'
).rename(columns={'stop_name': 'fermata_partenza', 'comune': 'comune_partenza'}).drop(columns=['stop_id', 'start_stop_id'])

trip_endpoints = pd.merge(
    trip_endpoints, stops_unique[['stop_id', 'stop_name', 'comune']], 
    left_on='end_stop_id', right_on='stop_id', how='left'
).rename(columns={'stop_name': 'fermata_arrivo', 'comune': 'comune_arrivo'}).drop(columns=['stop_id', 'end_stop_id'])

trip_full = pd.merge(trip_endpoints, trips, on='trip_id', how='left')
trip_full = pd.merge(trip_full, routes[['route_id', 'linea', route_operator_col]], on='route_id', how='left')
trip_full = trip_full.drop_duplicates(subset=['trip_id'])

# ==========================================
# BARRA LATERALE: FILTRI GLOBALI E MENU
# ==========================================
st.sidebar.markdown("### 🎛️ Filtri Globali")

usa_intero_periodo = st.sidebar.checkbox("📅 Seleziona intero periodo disponibile", value=True)

if usa_intero_periodo:
    intervallo_date = (min_global_date, max_global_date)
    st.sidebar.caption(f"Periodo attivo: {min_global_date.strftime('%d/%m/%Y')} ➔ {max_global_date.strftime('%d/%m/%Y')}")
else:
    intervallo_date = st.sidebar.date_input(
        "Intervallo Date:",
        value=(min_global_date, max_global_date),
        min_value=min_global_date,
        max_value=max_global_date
    )

fascia_oraria = st.sidebar.slider(
    "Fascia Oraria Partenza:",
    min_value=0,
    max_value=24,
    value=(0, 24)
)

# --- APPLICAZIONE FILTRI GLOBALI ---
if isinstance(intervallo_date, tuple) and len(intervallo_date) == 2:
    start_f, end_f = intervallo_date
    def calc_valid_days_range(s_id):