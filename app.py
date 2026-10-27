import os
import streamlit as st
import pandas as pd
import geopandas as gpd
from datetime import datetime, timedelta
import folium

# ==========================================
# CONFIGURAZIONE DELLA PAGINA
# ==========================================
st.set_page_config(
    page_title="Dashboard Trasporti GTFS",
    page_icon="🚌",
    layout="wide"
)

# Intestazione compatta
st.markdown("### 🚌 Dashboard Tratta e Orari GTFS")
st.markdown("<p style='color: gray; font-size: 13px;'>Analizza le singole corse, l'intera offerta di una linea o tutte le corse di un operatore. Clicca su una riga della tabella per approfondire la corsa.</p>", unsafe_allow_html=True)

GTFS_DIR = "."
GEOJSON_FILE = "Italia.geojson"

# ==========================================
# CARICAMENTO DATI CON CACHE (Ottimizzato)
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

# --- CALCOLO GIORNI DI VALIDITÀ ---
calendar_path = os.path.join(GTFS_DIR, 'calendar.txt')
calendar_dates_path = os.path.join(GTFS_DIR, 'calendar_dates.txt')
service_active_days = {}

if os.path.exists(calendar_path):
    calendar = pd.read_csv(calendar_path).drop_duplicates(subset=['service_id'])
    days_cols = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    for _, row in calendar.iterrows():
        s_id = row['service_id']
        try:
            start = datetime.strptime(str(int(row['start_date'])), '%Y%m%d')
            end = datetime.strptime(str(int(row['end_date'])), '%Y%m%d')
            active_dates = set()
            curr = start
            while curr <= end:
                if row.get(days_cols[curr.weekday()]) == 1:
                    active_dates.add(curr)
                curr += timedelta(days=1)
            service_active_days[s_id] = active_dates
        except Exception:
            service_active_days[s_id] = set()

if os.path.exists(calendar_dates_path):
    calendar_dates = pd.read_csv(calendar_dates_path)
    for _, row in calendar_dates.iterrows():
        s_id = row['service_id']
        try:
            dt = datetime.strptime(str(int(row['date'])), '%Y%m%d')
            exc_type = row['exception_type']
            if s_id not in service_active_days:
                service_active_days[s_id] = set()
            if exc_type == 1:
                service_active_days[s_id].add(dt)
            elif exc_type == 2:
                service_active_days[s_id].discard(dt)
        except Exception:
            pass

def get_giorni_validita(service_id):
    return len(service_active_days.get(service_id, []))

trips['giorni_validita'] = trips['service_id'].apply(get_giorni_validita)

# Elaborazione capolinea e orari base per i trip
stop_times['stop_sequence'] = pd.to_numeric(stop_times['stop_sequence'])
stop_times = stop_times.sort_values(['trip_id', 'stop_sequence'])

first_stops = stop_times.groupby('trip_id').first().reset_index()[['trip_id', 'stop_id', 'departure_time']]
first_stops.rename(columns={'stop_id': 'start_stop_id'}, inplace=True)
last_stops = stop_times.groupby('trip_id').last().reset_index()[['trip_id', 'stop_id', 'arrival_time']]
last_stops.rename(columns={'stop_id': 'end_stop_id'}, inplace=True)

trip_endpoints = pd.merge(first_stops, last_stops, on='trip_id')
stops_unique = stops.drop_duplicates(subset=['stop_id'])

trip_endpoints = pd.merge(trip_endpoints, stops_unique[['stop_id', 'stop_name']], left_on='start_stop_id', right_on='stop_id', how='left').rename(columns={'stop_name': 'fermata_partenza'}).drop(columns=['stop_id', 'start_stop_id'])
trip_endpoints = pd.merge(trip_endpoints, stops_unique[['stop_id', 'stop_name']], left_on='end_stop_id', right_on='stop_id', how='left').rename(columns={'stop_name': 'fermata_arrivo'}).drop(columns=['stop_id', 'end_stop_id'])

trip_full = pd.merge(trip_endpoints, trips, on='trip_id', how='left')
trip_full = pd.merge(trip_full, routes[['route_id', 'linea', route_operator_col]], on='route_id', how='left')
trip_full = trip_full.drop_duplicates(subset=['trip_id'])

# ==========================================
# BARRA LATERALE: FILTRI E MODALITÀ
# ==========================================
st.sidebar.markdown("### 🔍 Filtri e Visualizzazione")

modalità = st.sidebar.radio(
    "Modalità:", 
    ["🔍 Corsa Singola", "🌐 Intera Linea", "🏢 Intero Operatore"]
)

operatori_disponibili = sorted(trip_full[route_operator_col].dropna().unique().tolist())
operatore_scelto = st.sidebar.selectbox("Operatore:", operatori_disponibili)

df_op = trip_full[trip_full[route_operator_col] == operatore_scelto]

# Se siamo in modalità corsa singola o intera linea, chiediamo la linea
if modalità != "🏢 Intero Operatore":
    linee_disponibili = sorted(df_op['linea'].dropna().unique().tolist())
    linea_scelta = st.sidebar.selectbox("Linea:", linee_disponibili)
    df_linea = df_op[df_op['linea'] == linea_scelta].sort_values('departure_time')

    if modalità == "🔍 Corsa Singola":
        df_linea['descrizione_corsa'] = df_linea['departure_time'] + " ➔ " + df_linea['fermata_arrivo'] + " (" + df_linea['trip_headsign'].fillna('') + ")"
        corse_disponibili = df_linea['descrizione_corsa'].tolist()
        corsa_scelta = st.sidebar.selectbox("Orario di Partenza:", corse_disponibili)
        trip_id_selezionato = df_linea[df_linea['descrizione_corsa'] == corsa_scelta]['trip_id'].values[0]

# ==========================================
# GESTIONE STATO PER CLIC SULLA TABELLA
# ==========================================
if "selected_trip_id" not in st.session_state:
    st.session_state.selected_trip_id = None

# Se l'utente cambia modalità o operatore/linea, resettiamo la selezione
if "last_modalita" not in st.session_state or st.session_state.last_modalita != modalità:
    st.session_state.selected_trip_id = None
    st.session_state.last_modalita = modalità

# Se è stato selezionato un trip dalla tabella, forziamo la visualizzazione della corsa singola
is_corsa_cliccata = st.session_state.selected_trip_id is not None

# ==========================================
# PANNELLO PRINCIPALE
# ==========================================
if is_corsa_cliccata:
    # Pulsante per tornare indietro alla panoramica
    if st.button("⬅️ Torna alla panoramica precedente"):
        st.session_state.selected_trip_id = None
        st.rerun()

    trip_id_selezionato = st.session_state.selected_trip_id
    corsa_info = trip_full[trip_full['trip_id'] == trip_id_selezionato].iloc[0]
    linea_scelta = corsa_info['linea']

    st.markdown(f"""
    <div style='background-color: #f8f9fa; border: 1px solid #e9ecef; padding: 10px 15px; border-radius: 6px; margin-bottom: 15px; font-size: 13px; color: #333;'>
        <b>Linea:</b> {linea_scelta} &nbsp;&nbsp;|&nbsp;&nbsp;
        <b>Partenza:</b> {corsa_info['fermata_partenza']} ({corsa_info['departure_time']}) &nbsp;&nbsp;|&nbsp;&nbsp;
        <b>Arrivo:</b> {corsa_info['fermata_arrivo']} ({corsa_info['arrival_time']}) &nbsp;&nbsp;|&nbsp;&nbsp;
        <b>Giorni validità:</b> {corsa_info['giorni_validita']} giorni
    </div>
    """, unsafe_allow_html=True)

    st_trip = stop_times[stop_times['trip_id'] == trip_id_selezionato].sort_values('stop_sequence')
    path_stops = pd.merge(st_trip, stops_unique, on='stop_id')

    if gdf_comuni is not None and not path_stops.empty:
        try:
            gdf_stops = gpd.GeoDataFrame(path_stops.copy(), geometry=gpd.points_from_xy(path_stops.stop_lon, path_stops.stop_lat), crs="EPSG:4326")
            fermate_geo = gpd.sjoin(gdf_stops, gdf_comuni, how="left", predicate="within").drop_duplicates(subset=['stop_id'])
            
            col_comune = next((c for c in ['COMUNE', 'comune', 'Nome_Com', 'COM_NAME', 'DEN_COM'] if c in fermate_geo.columns), None)
            col_prov = next((c for c in ['SIGLA', 'DEN_PROV', 'PROVINCIA', 'provincia', 'Sigla Prov', 'COD_PROV'] if c in fermate_geo.columns), None)
            
            path_stops['comune'] = fermate_geo[col_comune].values if col_comune else "N.D."
            path_stops['provincia'] = fermate_geo[col_prov].values if col_prov else "N.D."
        except Exception:
            path_stops['comune'] = "N.D."
            path_stops['provincia'] = "N.D."
    else:
        path_stops['comune'] = "N.D."
        path_stops['provincia'] = "N.D."

    if not path_stops.empty:
        col_left, col_right = st.columns([1.1, 1.3])
        
        with col_left:
            st.markdown("##### 📋 Fermate e Orari di Passaggio")
            df_tabella_fermate = path_stops[['stop_sequence', 'stop_name', 'departure_time', 'comune']].copy()
            df_tabella_fermate.columns = ['N°', 'Fermata', 'Orario', 'Comune']
            st.dataframe(df_tabella_fermate, use_container_width=True, hide_index=True, height=480)
            
        with col_right:
            st.markdown(f"##### 🗺️ Mappa Percorso (Linea {linea_scelta})")
            centro_lat = path_stops['stop_lat'].mean()
            centro_lon = path_stops['stop_lon'].mean()
            
            m = folium.Map(location=[centro_lat, centro_lon], zoom_start=12, tiles="Esri.WorldStreetMap")
            coords = path_stops[['stop_lat', 'stop_lon']].values.tolist()
            folium.PolyLine(coords, color="blue", weight=4, opacity=0.8, tooltip=f"Linea {linea_scelta}").add_to(m)
            
            for _, row in path_stops.iterrows():
                popup_html = f"<b>{row['stop_name']}</b><br>Orario: {row.get('departure_time', '')}<br>Comune: {row['comune']} ({row['provincia']})"
                folium.Marker(
                    location=[row['stop_lat'], row['stop_lon']],
                    popup=popup_html,
                    tooltip=row['stop_name'],
                    icon=folium.Icon(color='red', icon='bus', prefix='fa')
                ).add_to(m)
                
            map_html = m._repr_html_()
            st.components.v1.html(map_html, height=480)
    else:
        st.warning("Nessuna coordinata trovata per questa corsa.")

elif modalità == "🔍 Corsa Singola":
    # --- MODALITÀ CORSA SINGOLA STANDARD ---
    corsa_info = df_linea[df_linea['trip_id'] == trip_id_selezionato].iloc[0]

    st.markdown(f"""
    <div style='background-color: #f8f9fa; border: 1px solid #e9ecef; padding: 10px 15px; border-radius: 6px; margin-bottom: 15px; font-size: 13px; color: #333;'>
        <b>Partenza:</b> {corsa_info['fermata_partenza']} ({corsa_info['departure_time']}) &nbsp;&nbsp;|&nbsp;&nbsp;
        <b>Arrivo:</b> {corsa_info['fermata_arrivo']} ({corsa_info['arrival_time']}) &nbsp;&nbsp;|&nbsp;&nbsp;
        <b>Giorni validità:</b> {corsa_info['giorni_validita']} giorni
    </div>
    """, unsafe_allow_html=True)

    st_trip = stop_times[stop_times['trip_id'] == trip_id_selezionato].sort_values('stop_sequence')
    path_stops = pd.merge(st_trip, stops_unique, on='stop_id')

    if gdf_comuni is not None and not path_stops.empty:
        try:
            gdf_stops = gpd.GeoDataFrame(path_stops.copy(), geometry=gpd.points_from_xy(path_stops.stop_lon, path_stops.stop_lat), crs="EPSG:4326")
            fermate_geo = gpd.sjoin(gdf_stops, gdf_comuni, how="left", predicate="within").drop_duplicates(subset=['stop_id'])
            
            col_comune = next((c for c in ['COMUNE', 'comune', 'Nome_Com', 'COM_NAME', 'DEN_COM'] if c in fermate_geo.columns), None)
            col_prov = next((c for c in ['SIGLA', 'DEN_PROV', 'PROVINCIA', 'provincia', 'Sigla Prov', 'COD_PROV'] if c in fermate_geo.columns), None)
            
            path_stops['comune'] = fermate_geo[col_comune].values if col_comune else "N.D."
            path_stops['provincia'] = fermate_geo[col_prov].values if col_prov else "N.D."
        except Exception:
            path_stops['comune'] = "N.D."
            path_stops['provincia'] = "N.D."
    else:
        path_stops['comune'] = "N.D."
        path_stops['provincia'] = "N.D."

    if not path_stops.empty:
        col_left, col_right = st.columns([1.1, 1.3])
        
        with col_left:
            st.markdown("##### 📋 Fermate e Orari di Passaggio")
            df_tabella_fermate = path_stops[['stop_sequence', 'stop_name', 'departure_time', 'comune']].copy()
            df_tabella_fermate.columns = ['N°', 'Fermata', 'Orario', 'Comune']
            st.dataframe(df_tabella_fermate, use_container_width=True, hide_index=True, height=480)
            
        with col_right:
            st.markdown(f"##### 🗺️ Mappa Percorso (Linea {linea_scelta})")
            centro_lat = path_stops['stop_lat'].mean()
            centro_lon = path_stops['stop_lon'].mean()
            
            m = folium.Map(location=[centro_lat, centro_lon], zoom_start=12, tiles="Esri.WorldStreetMap")
            coords = path_stops[['stop_lat', 'stop_lon']].values.tolist()
            folium.PolyLine(coords, color="blue", weight=4, opacity=0.8, tooltip=f"Linea {linea_scelta}").add_to(m)
            
            for _, row in path_stops.iterrows():
                popup_html = f"<b>{row['stop_name']}</b><br>Orario: {row.get('departure_time', '')}<br>Comune: {row['comune']} ({row['provincia']})"
                folium.Marker(
                    location=[row['stop_lat'], row['stop_lon']],
                    popup=popup_html,
                    tooltip=row['stop_name'],
                    icon=folium.Icon(color='red', icon='bus', prefix='fa')
                ).add_to(m)
                
            map_html = m._repr_html_()
            st.components.v1.html(map_html, height=480)
    else:
        st.warning("Nessuna coordinata trovata per questa corsa.")

elif modalità == "🌐 Intera Linea":
    st.markdown(f"#### 🌐 Panoramica Linea: **{linea_scelta}** (Operatore: {operatore_scelto})")
    st.markdown(f"<p style='color: gray; font-size: 13px;'>Trovate <b>{len(df_linea)} corse</b> totali. <b>Clicca su una riga della tabella</b> per visualizzare i dettagli della singola corsa.</p>", unsafe_allow_html=True)

    col_left, col_right = st.columns([1.2, 1.2])

    with col_left:
        st.markdown("##### 📋 Elenco corse della linea (Clicca una riga)")
        df_tabella_corse = df_linea[['departure_time', 'fermata_partenza', 'arrival_time', 'fermata_arrivo', 'giorni_validita']].copy()
        df_tabella_corse.columns = ['Partenza', 'Da', 'Arrivo', 'A', 'Giorni Validità']
        
        event = st.dataframe(
            df_tabella_corse, 
            selection_mode="single-row", 
            on_selection="rerun", 
            use_container_width=True, 
            hide_index=True, 
            height=480
        )
        
        # Gestione selezione riga
        selected_rows = event.selection.get("rows", [])
        if selected_rows:
            idx = selected_rows[0]
            st.session_state.selected_trip_id = df_linea.iloc[idx]['trip_id']
            st.rerun()

    with col_right:
        st.markdown(f"##### 🗺️ Mappa Cumulativa Linea {linea_scelta}")
        trip_ids_linea = df_linea['trip_id'].tolist()
        st_linea_all = stop_times[stop_times['trip_id'].isin(trip_ids_linea)]
        path_stops_linea = pd.merge(st_linea_all, stops_unique, on='stop_id').drop_duplicates(subset=['stop_id'])

        if not path_stops_linea.empty:
            centro_lat = path_stops_linea['stop_lat'].mean()
            centro_lon = path_stops_linea['stop_lon'].mean()
            
            m_linea = folium.Map(location=[centro_lat, centro_lon], zoom_start=11, tiles="Esri.WorldStreetMap")
            for t_id in trip_ids_linea[:15]:
                st_t = stop_times[stop_times['trip_id'] == t_id].sort_values('stop_sequence')
                p_stops = pd.merge(st_t, stops_unique, on='stop_id')
                if len(p_stops) > 1:
                    coords = p_stops[['stop_lat', 'stop_lon']].values.tolist()
                    folium.PolyLine(coords, color="blue", weight=3, opacity=0.5).add_to(m_linea)
            
            for _, row in path_stops_linea.iterrows():
                folium.Marker(
                    location=[row['stop_lat'], row['stop_lon']],
                    popup=f"<b>{row['stop_name']}</b>",
                    tooltip=row['stop_name'],
                    icon=folium.Icon(color='red', icon='bus', prefix='fa')
                ).add_to(m_linea)
                
            map_html = m_linea._repr_html_()
            st.components.v1.html(map_html, height=480)
        else:
            st.warning("Nessuna fermata geolocalizzata per questa linea.")

else:
    st.markdown(f"#### 🏢 Panoramica Operatore: **{operatore_scelto}**")
    st.markdown(f"<p style='color: gray; font-size: 13px;'>Trovate <b>{len(df_op)} corse totali</b>. <b>Clicca su una riga della tabella</b> per visualizzare i dettagli della singola corsa.</p>", unsafe_allow_html=True)

    col_left, col_right = st.columns([1.2, 1.2])

    with col_left:
        st.markdown("##### 📋 Elenco di tutte le corse dell'operatore (Clicca una riga)")
        df_tabella_op = df_op[['linea', 'departure_time', 'fermata_partenza', 'arrival_time', 'fermata_arrivo', 'giorni_validita']].copy()
        df_tabella_op.columns = ['Linea', 'Partenza', 'Da', 'Arrivo', 'A', 'Giorni Validità']
        
        event = st.dataframe(
            df_tabella_op, 
            selection_mode="single-row", 
            on_selection="rerun", 
            use_container_width=True, 
            hide_index=True, 
            height=480
        )
        
        # Gestione selezione riga
        selected_rows = event.selection.get("rows", [])
        if selected_rows:
            idx = selected_rows[0]
            st.session_state.selected_trip_id = df_op.iloc[idx]['trip_id']
            st.rerun()

    with col_right:
        st.markdown(f"##### 🗺️ Mappa Globale Operatore")
        trip_ids_op = df_op['trip_id'].tolist()
        st_op_all = stop_times[stop_times['trip_id'].isin(trip_ids_op)]
        path_stops_op = pd.merge(st_op_all, stops_unique, on='stop_id').drop_duplicates(subset=['stop_id'])

        if not path_stops_op.empty:
            centro_lat = path_stops_op['stop_lat'].mean()
            centro_lon = path_stops_op['stop_lon'].mean()
            
            m_op = folium.Map(location=[centro_lat, centro_lon], zoom_start=10, tiles="Esri.WorldStreetMap")
            
            for t_id in trip_ids_op[:20]:
                st_t = stop_times[stop_times['trip_id'] == t_id].sort_values('stop_sequence')
                p_stops = pd.merge(st_t, stops_unique, on='stop_id')
                if len(p_stops) > 1:
                    coords = p_stops[['stop_lat', 'stop_lon']].values.tolist()
                    folium.PolyLine(coords, color="green", weight=2, opacity=0.4).add_to(m_op)
            
            for _, row in path_stops_op.iterrows():
                folium.Marker(
                    location=[row['stop_lat'], row['stop_lon']],
                    popup=f"<b>{row['stop_name']}</b>",
                    tooltip=row['stop_name'],
                    icon=folium.Icon(color='green', icon='bus', prefix='fa')
                ).add_to(m_op)
                
            map_html = m_op._repr_html_()
            st.components.v1.html(map_html, height=480)
        else:
            st.warning("Nessuna fermata geolocalizzata per questo operatore.")