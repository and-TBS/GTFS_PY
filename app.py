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

        gdf_stops = gpd.GeoDataFrame(
            stops.copy(), 
            geometry=gpd.points_from_xy(stops.stop_lon, stops.stop_lat), 
            crs="EPSG:4326"
        )
        
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
st.sidebar.markdown("### 🔍 Filtri e Navigazione")

# Scelta Comune Globale
comuni_globali_disponibili = ["Tutti"] + sorted([str(c) for c in trip_full['comune_partenza'].dropna().unique() if c != "N.D."])
comune_filtro = st.sidebar.selectbox("🏙️ Filtra per Comune (X):", comuni_globali_disponibili)

if comune_filtro == "Tutti":
    modalità = st.sidebar.radio(
        "Modalità standard:", 
        ["🌐 Intera Linea", "🏢 Intero Operatore"]
    )
    operatore_scelto = st.sidebar.selectbox("Operatore:", sorted(trip_full[route_operator_col].dropna().unique().tolist()))
    df_op = trip_full[trip_full[route_operator_col] == operatore_scelto]
    
    if modalità == "🌐 Intera Linea":
        linee_disponibili = sorted(df_op['linea'].dropna().unique().tolist())
        linea_scelta = st.sidebar.selectbox("Linea:", linee_disponibili) if linee_disponibili else None
        df_linea = df_op[df_op['linea'] == linea_scelta].sort_values('departure_time') if linea_scelta else pd.DataFrame()
    else:
        linea_scelta = None
        df_linea = pd.DataFrame()
else:
    # Se viene scelto un comune X specifico, attiviamo la modalità dedicata
    modalità = "Analisi Comune"

# ==========================================
# GESTIONE STATO PER APPROFONDIMENTO CORSA
# ==========================================
if "selected_trip_id" not in st.session_state:
    st.session_state.selected_trip_id = None

is_corsa_cliccata = st.session_state.selected_trip_id is not None

# ==========================================
# PANNELLO PRINCIPALE
# ==========================================
if is_corsa_cliccata:
    if st.button("⬅️ Torna alla schermata precedente"):
        st.session_state.selected_trip_id = None
        st.rerun()

    trip_id_corrente = st.session_state.selected_trip_id
    corsa_info = trip_full[trip_full['trip_id'] == trip_id_corrente].iloc[0]
    linea_corrente = corsa_info['linea']

    st.markdown(f"""
    <div style='background-color: #f8f9fa; border: 1px solid #e9ecef; padding: 10px 15px; border-radius: 6px; margin-bottom: 15px; font-size: 13px; color: #333;'>
        <b>Linea:</b> {linea_corrente} &nbsp;&nbsp;|&nbsp;&nbsp;
        <b>Partenza:</b> {corsa_info['fermata_partenza']} ({corsa_info['comune_partenza']}) alle {corsa_info['departure_time']} &nbsp;&nbsp;|&nbsp;&nbsp;
        <b>Arrivo:</b> {corsa_info['fermata_arrivo']} ({corsa_info['comune_arrivo']}) alle {corsa_info['arrival_time']} &nbsp;&nbsp;|&nbsp;&nbsp;
        <b>Giorni validità:</b> {corsa_info['giorni_validita']} giorni
    </div>
    """, unsafe_allow_html=True)

    st_trip = stop_times[stop_times['trip_id'] == trip_id_corrente].sort_values('stop_sequence')
    path_stops = pd.merge(st_trip, stops_unique, on='stop_id')

    if not path_stops.empty:
        col_left, col_right = st.columns([1.1, 1.3])
        
        with col_left:
            st.markdown("##### 📋 Fermate e Orari di Passaggio")
            df_tabella_fermate = path_stops[['stop_sequence', 'stop_name', 'departure_time', 'comune']].copy()
            df_tabella_fermate.columns = ['N°', 'Fermata', 'Orario', 'Comune']
            st.dataframe(df_tabella_fermate, use_container_width=True, hide_index=True, height=480)
            
        with col_right:
            st.markdown(f"##### 🗺️ Mappa Percorso (Linea {linea_corrente})")
            centro_lat = path_stops['stop_lat'].mean()
            centro_lon = path_stops['stop_lon'].mean()
            
            m = folium.Map(location=[centro_lat, centro_lon], zoom_start=12, tiles="Esri.WorldStreetMap")
            coords = path_stops[['stop_lat', 'stop_lon']].values.tolist()
            folium.PolyLine(coords, color="blue", weight=4, opacity=0.8, tooltip=f"Linea {linea_corrente}").add_to(m)
            
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

elif modalità == "Analisi Comune":
    st.markdown(f"### 🏙️ Analisi per il Comune: **{comune_filtro}**")
    st.markdown("Esplora le corse in partenza, in arrivo o con fermata intermedia in questo comune. Clicca sull'icona 🔍 per visualizzare il percorso dettagliato di una corsa.")

    # 1. Corse in partenza da X
    st.markdown(f"#### 🚀 Corse in **partenza** da {comune_filtro}")
    corse_partenza = trip_full[trip_full['comune_partenza'] == comune_filtro]
    
    if not corse_partenza.empty:
        for _, row in corse_partenza.iterrows():
            c1, c2, c3, c4, c5 = st.columns([1, 2, 2, 2, 1])
            c1.write(f"**{row['linea']}**")
            c2.write(f"🕒 {row['departure_time']}")
            c3.write(f"Da: {row['fermata_partenza']}")
            c4.write(f"A: {row['fermata_arrivo']}")
            if c5.button("🔍 Percorso", key=f"part_{row['trip_id']}"):
                st.session_state.selected_trip_id = row['trip_id']
                st.rerun()
    else:
        st.info("Nessuna corsa in partenza da questo comune.")

    st.markdown("---")

    # 2. Corse in arrivo ad X
    st.markdown(f"#### 🏁 Corse in **arrivo** a {comune_filtro}")
    corse_arrivo = trip_full[trip_full['comune_arrivo'] == comune_filtro]
    
    if not corse_arrivo.empty:
        for _, row in corse_arrivo.iterrows():
            c1, c2, c3, c4, c5 = st.columns([1, 2, 2, 2, 1])
            c1.write(f"**{row['linea']}**")
            c2.write(f"🕒 {row['arrival_time']}")
            c3.write(f"Da: {row['fermata_partenza']}")
            c4.write(f"A: {row['fermata_arrivo']}")
            if c5.button("🔍 Percorso", key=f"arr_{row['trip_id']}"):
                st.session_state.selected_trip_id = row['trip_id']
                st.rerun()
    else:
        st.info("Nessuna corsa in arrivo in questo comune.")

    st.markdown("---")

    # 3. Corse con fermata intermedia in X
    st.markdown(f"#### 🚏 Corse con **fermata intermedia** a {comune_filtro}")
    
    # Troviamo le fermate appartenenti a questo comune
    stop_ids_comune = stops[stops['comune'] == comune_filtro]['stop_id'].tolist()
    
    # Troviamo i trip_id che passano per queste fermate ma che non sono né la prima né l'ultima fermata
    stop_times_comune = stop_times[stop_times['stop_id'].isin(stop_ids_comune)]
    trip_ids_intermedi = stop_times_comune['trip_id'].unique()
    
    corse_intermedie = trip_full[
        (trip_full['trip_id'].isin(trip_ids_intermedi)) & 
        (trip_full['comune_partenza'] != comune_filtro) & 
        (trip_full['comune_arrivo'] != comune_filtro)
    ]

    if not corse_intermedie.empty:
        for _, row in corse_intermedie.iterrows():
            c1, c2, c3, c4, c5 = st.columns([1, 2, 2, 2, 1])
            c1.write(f"**{row['linea']}**")
            c2.write(f"Da {row['comune_partenza']} a {row['comune_arrivo']}")
            c3.write(f"Partenza: {row['departure_time']}")
            c4.write(f"Arrivo: {row['arrival_time']}")
            if c5.button("🔍 Percorso", key=f"int_{row['trip_id']}"):
                st.session_state.selected_trip_id = row['trip_id']
                st.rerun()
    else:
        st.info("Nessuna corsa con fermata intermedia esclusiva in questo comune.")

elif modalità == "🌐 Intera Linea":
    if linea_scelta:
        st.markdown(f"#### 🌐 Panoramica Linea: **{linea_scelta}** (Operatore: {operatore_scelto})")
        st.dataframe(df_linea[['departure_time', 'fermata_partenza', 'arrival_time', 'fermata_arrivo', 'giorni_validita']], use_container_width=True, hide_index=True)
    else:
        st.info("Seleziona una linea dalla barra laterale.")

else:
    if operatore_scelto:
        st.markdown(f"#### 🏢 Panoramica Operatore: **{operatore_scelto}**")
        st.dataframe(df_op[['linea', 'departure_time', 'fermata_partenza', 'arrival_time', 'fermata_arrivo']], use_container_width=True, hide_index=True)