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
st.markdown("<p style='color: gray; font-size: 13px;'>Analizza le singole corse, filtra per Comune di partenza o esplora l'intera offerta.</p>", unsafe_allow_html=True)

GTFS_DIR = "."
GEOJSON_FILE = "Piemonte.geojson"

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

# --- ASSOCIAZIONE GEOGRAFICA FERMATE -> COMUNI ---
if gdf_comuni is not None and not stops.empty:
    try:
        gdf_stops = gpd.GeoDataFrame(
            stops.copy(), 
            geometry=gpd.points_from_xy(stops.stop_lon, stops.stop_lat), 
            crs="EPSG:4326"
        )
        fermate_geo = gpd.sjoin(gdf_stops, gdf_comuni, how="left", predicate="within").drop_duplicates(subset=['stop_id'])
        
        col_comune = next((c for c in ['COMUNE', 'comune', 'Nome_Com', 'COM_NAME', 'DEN_COM', 'NAME_3', 'COMUNE_ISTAT', 'COM'] if c in fermate_geo.columns), None)
        col_prov = next((c for c in ['SIGLA', 'DEN_PROV', 'PROVINCIA', 'provincia', 'Sigla Prov', 'COD_PROV', 'PROV'] if c in fermate_geo.columns), None)
        
        if col_comune:
            stops['comune'] = fermate_geo[col_comune].values
        else:
            cols_testuali = [c for c in gdf_comuni.columns if c != 'geometry' and gdf_comuni[c].dtype == 'object']
            stops['comune'] = fermate_geo[cols_testuali[0]].values if cols_testuali else "N.D."

        stops['provincia'] = fermate_geo[col_prov].values if col_prov else "N.D."
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
    trip_endpoints, 
    stops_unique[['stop_id', 'stop_name', 'comune']], 
    left_on='start_stop_id', 
    right_on='stop_id', 
    how='left'
).rename(columns={'stop_name': 'fermata_partenza', 'comune': 'comune_partenza'}).drop(columns=['stop_id', 'start_stop_id'])

trip_endpoints = pd.merge(
    trip_endpoints, 
    stops_unique[['stop_id', 'stop_name', 'comune']], 
    left_on='end_stop_id', 
    right_on='stop_id', 
    how='left'
).rename(columns={'stop_name': 'fermata_arrivo', 'comune': 'comune_arrivo'}).drop(columns=['stop_id', 'end_stop_id'])

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

# Se siamo in modalità corsa singola o intera linea, chiediamo la linea e il comune
if modalità != "🏢 Intero Operatore":
    linee_disponibili = sorted(df_op['linea'].dropna().unique().tolist())
    linea_scelta = st.sidebar.selectbox("Linea:", linee_disponibili)
    df_linea = df_op[df_op['linea'] == linea_scelta].sort_values('departure_time')

    # --- FILTRO COMUNE DI PARTENZA ---
    comuni_partenza_disponibili = ["Tutti"] + sorted([str(c) for c in df_linea['comune_partenza'].dropna().unique() if c != "N.D."])
    comune_filtro = st.sidebar.selectbox("🏙️ Partenza da (Comune):", comuni_partenza_disponibili)
    
    if comune_filtro != "Tutti":
        df_linea = df_linea[df_linea['comune_partenza'] == comune_filtro]

    if modalità == "🔍 Corsa Singola":
        if not df_linea.empty:
            df_linea['descrizione_corsa'] = df_linea['departure_time'] + " ➔ " + df_linea['fermata_arrivo'] + " (" + df_linea['comune_partenza'].astype(str) + ")"
            corse_disponibili = df_linea['descrizione_corsa'].tolist()
            corsa_scelta = st.sidebar.selectbox("Orario di Partenza:", corse_disponibili)
            trip_id_selezionato = df_linea[df_linea['descrizione_corsa'] == corsa_scelta]['trip_id'].values[0]
        else:
            st.sidebar.warning("Nessuna corsa trovata con partenza da questo Comune.")
            trip_id_selezionato = None

# ==========================================
# GESTIONE STATO PER APPROFONDIMENTO CORSA
# ==========================================
if "selected_trip_id" not in st.session_state:
    st.session_state.selected_trip_id = None

if "last_modalita" not in st.session_state or st.session_state.last_modalita != modalità:
    st.session_state.selected_trip_id = None
    st.session_state.last_modalita = modalità

is_corsa_cliccata = st.session_state.selected_trip_id is not None

# ==========================================
# PANNELLO PRINCIPALE
# ==========================================
if is_corsa_cliccata:
    if st.button("⬅️ Torna alla panoramica precedente"):
        st.session_state.selected_trip_id = None
        st.rerun()

    trip_id_selezionato = st.session_state.selected_trip_id
    corsa_info = trip_full[trip_full['trip_id'] == trip_id_selezionato].iloc[0]
    linea_scelta = corsa_info['linea']

    st.markdown(f"""
    <div style='background-color: #f8f9fa; border: 1px solid #e9ecef; padding: 10px 15px; border-radius: 6px; margin-bottom: 15px; font-size: 13px; color: #333;'>
        <b>Linea:</b> {linea_scelta} &nbsp;&nbsp;|&nbsp;&nbsp;
        <b>Partenza:</b> {corsa_info['fermata_partenza']} ({corsa_info['comune_partenza']}) alle {corsa_info['departure_time']} &nbsp;&nbsp;|&nbsp;&nbsp;
        <b>Arrivo:</b> {corsa_info['fermata_arrivo']} ({corsa_info['comune_arrivo']}) alle {corsa_info['arrival_time']} &nbsp;&nbsp;|&nbsp;&nbsp;
        <b>Giorni validità:</b> {corsa_info['giorni_validita']} giorni
    </div>
    """, unsafe_allow_html=True)

    st_trip = stop_times[stop_times['trip_id'] == trip_id_selezionato].sort_values('stop_sequence')
    path_stops = pd.merge(st_trip, stops_unique, on='stop_id')

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
    if 'trip_id_selezionato' in locals() and trip_id_selezionato is not None:
        corsa_info = df_linea[df_linea['trip_id'] == trip_id_selezionato].iloc[0]

        st.markdown(f"""
        <div style='background-color: #f8f9fa; border: 1px solid #e9ecef; padding: 10px 15px; border-radius: 6px; margin-bottom: 15px; font-size: 13px; color: #333;'>
            <b>Partenza:</b> {corsa_info['fermata_partenza']} ({corsa_info['comune_partenza']}) alle {corsa_info['departure_time']} &nbsp;&nbsp;|&nbsp;&nbsp;
            <b>Arrivo:</b> {corsa_info['fermata_arrivo']} ({corsa_info['comune_arrivo']}) alle {corsa_info['arrival_time']} &nbsp;&nbsp;|&nbsp;&nbsp;
            <b>Giorni validità:</b> {corsa_info['giorni_validita']} giorni
        </div>
        """, unsafe_allow_html=True)

        st_trip = stop_times[stop_times['trip_id'] == trip_id_selezionato].sort_values('stop_sequence')
        path_stops = pd.merge(st_trip, stops_unique, on='stop_id')

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
    else:
        st.info("Seleziona una linea e un Comune di partenza dalla barra laterale.")

elif modalità == "🌐 Intera Linea":
    st.markdown(f"#### 🌐 Panoramica Linea: **{linea_scelta}** (Operatore: {operatore_scelto})")
    st.markdown(f"<p style='color: gray; font-size: 13px;'>Trovate <b>{len(df_linea)} corse</b> filtrate. Usa il selettore sottostante per visualizzare i dettagli di una corsa.</p>", unsafe_allow_html=True)

    col_left, col_right = st.columns([1.2, 1.2])

    with col_left:
        st.markdown("##### 📋 Elenco corse della linea")
        df_tabella_corse = df_linea[['departure_time', 'fermata_partenza', 'comune_partenza', 'arrival_time', 'fermata_arrivo', 'giorni_validita']].copy()
        df_tabella_corse.columns = ['Partenza', 'Da', 'Comune Origine', 'Arrivo', 'A', 'Giorni Validità']
        
        st.dataframe(df_tabella_corse, use_container_width=True, hide_index=True, height=340)
        
        if not df_linea.empty:
            df_linea['descrizione_scelta'] = df_linea['departure_time'] + " - " + df_linea['fermata_partenza'] + " (" + df_linea['comune_partenza'].astype(str) + ") ➔ " + df_linea['fermata_arrivo']
            corsa_selezionata_tendina = st.selectbox("Seleziona corsa da approfondire:", df_linea['descrizione_scelta'].tolist())
            
            if st.button("🔍 Mostra dettagli corsa"):
                trip_id_scelto = df_linea[df_linea['descrizione_scelta'] == corsa_selezionata_tendina]['trip_id'].values[0]
                st.session_state.selected_trip_id = trip_id_scelto
                st.rerun()
        else:
            st.info("Nessuna corsa disponibile con i filtri selezionati.")

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
                    popup=f"<b>{row['stop_name']}</b><br>Comune: {row['comune']}",
                    tooltip=row['stop_name'],
                    icon=folium.Icon(color='red', icon='bus', prefix='fa')
                ).add_to(m_linea)
                
            map_html = m_linea._repr_html_()
            st.components.v1.html(map_html, height=480)
        else:
            st.warning("Nessuna fermata geolocalizzata per questa linea.")

else:
    st.markdown(f"#### 🏢 Panoramica Operatore: **{operatore_scelto}**")
    st.markdown(f"<p style='color: gray; font-size: 13px;'>Trovate <b>{len(df_op)} corse totali</b>. Usa il selettore sottostante per visualizzare i dettagli di una corsa.</p>", unsafe_allow_html=True)

    col_left, col_right = st.columns([1.2, 1.2])

    with col_left:
        st.markdown("##### 📋 Elenco di tutte le corse dell'operatore")
        df_tabella_op = df_op[['linea', 'departure_time', 'fermata_partenza', 'comune_partenza', 'arrival_time', 'fermata_arrivo', 'giorni_validita']].copy()
        df_tabella_op.columns = ['Linea', 'Partenza', 'Da', 'Comune Origine', 'Arrivo', 'A', 'Giorni Validità']
        
        st.dataframe(df_tabella_op, use_container_width=True, hide_index=True, height=340)
        
        if not df_op.empty:
            df_op['descrizione_scelta_op'] = "Linea " + df_op['linea'].astype(str) + " (" + df_op['departure_time'] + " - " + df_op['fermata_partenza'] + ")"
            corsa_op_tendina = st.selectbox("Seleziona corsa dell'operatore:", df_op['descrizione_scelta_op'].tolist())
            
            if st.button("🔍 Mostra dettagli corsa operatore"):
                trip_id_op_scelto = df_op[df_op['descrizione_scelta_op'] == corsa_op_tendina]['trip_id'].values[0]
                st.session_state.selected_trip_id = trip_id_op_scelto
                st.rerun()
        else:
            st.info("Nessuna corsa disponibile per questo operatore.")

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
                    popup=f"<b>{row['stop_name']}</b><br>Comune: {row['comune']}",
                    tooltip=row['stop_name'],
                    icon=folium.Icon(color='green', icon='bus', prefix='fa')
                ).add_to(m_op)
                
            map_html = m_op._repr_html_()
            st.components.v1.html(map_html, height=480)
        else:
            st.warning("Nessuna fermata geolocalizzata per questo operatore.")