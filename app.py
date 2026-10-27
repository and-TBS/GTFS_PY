import os
import streamlit as st
import pandas as pd
import geopandas as gpd
from datetime import datetime, timedelta
import folium

# ==========================================
# CONFIGURAZIONE DELLA PAGINA E STILE CSS
# ==========================================
st.set_page_config(
    page_title="Dashboard Trasporti GTFS",
    page_icon="🚌",
    layout="wide"
)

# Iniezione CSS personalizzato per box, pulsanti e testi compatti
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
# BARRA LATERALE: MENU PRINCIPALE E FILTRI
# ==========================================
st.sidebar.markdown("### 🔍 Tipo di Visualizzazione")

tipo_vista = st.sidebar.radio(
    "Seleziona modalità:",
    ["🧭 Navigazione Classica", "🏙️ Analisi per Comune"]
)

trip_id_selezionato = None
df_linea = pd.DataFrame()
linea_scelta = None
operatore_scelto = None

if tipo_vista == "🧭 Navigazione Classica":
    modalità_classica = st.sidebar.radio(
        "Modalità Classica:", 
        ["🔍 Corsa Singola", "🌐 Intera Linea", "🏢 Intero Operatore"]
    )
    
    operatori_disponibili = sorted(trip_full[route_operator_col].dropna().unique().tolist())
    operatore_scelto = st.sidebar.selectbox("Operatore:", operatori_disponibili) if operatori_disponibili else None
    
    df_op = trip_full[trip_full[route_operator_col] == operatore_scelto] if operatore_scelto else pd.DataFrame()
    
    if modalità_classica != "🏢 Intero Operatore" and not df_op.empty:
        linee_disponibili = sorted(df_op['linea'].dropna().unique().tolist())
        linea_scelta = st.sidebar.selectbox("Linea:", linee_disponibili) if linee_disponibili else None
        df_linea = df_op[df_op['linea'] == linea_scelta].sort_values('departure_time') if linea_scelta else pd.DataFrame()
        
        if modalità_classica == "🔍 Corsa Singola" and not df_linea.empty:
            df_linea['descrizione_corsa'] = df_linea['departure_time'] + " ➔ " + df_linea['fermata_arrivo'] + " (" + df_linea['comune_partenza'].astype(str) + ")"
            corse_disponibili = df_linea['descrizione_corsa'].tolist()
            if corse_disponibili:
                corsa_scelta = st.sidebar.selectbox("Orario di Partenza:", corse_disponibili)
                trip_id_selezionato = df_linea[df_linea['descrizione_corsa'] == corsa_scelta]['trip_id'].values[0]

else:
    comuni_globali_disponibili = sorted([str(c) for c in trip_full['comune_partenza'].dropna().unique() if c != "N.D."])
    comune_scelto = st.sidebar.selectbox("🏙️ Seleziona Comune (X):", comuni_globali_disponibili) if comuni_globali_disponibili else None

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
    <div class="info-box">
        <b>🚍 Linea:</b> {linea_corrente} &nbsp;&nbsp;|&nbsp;&nbsp;
        <b>🕒 Partenza:</b> {corsa_info['fermata_partenza']} ({corsa_info['comune_partenza']}) alle {corsa_info['departure_time']} &nbsp;&nbsp;|&nbsp;&nbsp;
        <b>🏁 Arrivo:</b> {corsa_info['fermata_arrivo']} ({corsa_info['comune_arrivo']}) alle {corsa_info['arrival_time']} &nbsp;&nbsp;|&nbsp;&nbsp;
        <b>📅 Giorni validità:</b> {corsa_info['giorni_validita']} giorni
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
            st.dataframe(df_tabella_fermate, use_container_width=True, hide_index=True, height=720)
            
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
            st.components.v1.html(map_html, height=720)
    else:
        st.warning("Nessuna coordinata trovata per questa corsa.")

elif tipo_vista == "🏙️ Analisi per Comune":
    st.markdown(f"### 🏙️ Analisi per il Comune: **{comune_scelto}**")
    st.markdown("Filtra le corse per tipologia e clicca su **🔍** per aprire la mappa dettagliata.")

    filtro_tipo = st.radio(
        "Seleziona tipologia corse:",
        ["🚀 In partenza", "🏁 In arrivo", "🚏 In transito (intermedie)"],
        horizontal=True
    )

    st.markdown("---")

    if filtro_tipo == "🚀 In partenza":
        st.markdown(f"#### Corse in **partenza** da {comune_scelto}")
        corse_target = trip_full[trip_full['comune_partenza'] == comune_scelto]
    elif filtro_tipo == "🏁 In arrivo":
        st.markdown(f"#### Corse in **arrivo** a {comune_scelto}")
        corse_target = trip_full[trip_full['comune_arrivo'] == comune_scelto]
    else:
        st.markdown(f"#### Corse con **fermata intermedia** a {comune_scelto}")
        stop_ids_comune = stops[stops['comune'] == comune_scelto]['stop_id'].tolist()
        stop_times_comune = stop_times[stop_times['stop_id'].isin(stop_ids_comune)]
        trip_ids_intermedi = stop_times_comune['trip_id'].unique()
        
        corse_target = trip_full[
            (trip_full['trip_id'].isin(trip_ids_intermedi)) & 
            (trip_full['comune_partenza'] != comune_scelto) & 
            (trip_full['comune_arrivo'] != comune_scelto)
        ]

    if not corse_target.empty:
        for _, row in corse_target.iterrows():
            c1, c2, c3, c4, c5 = st.columns([0.8, 2, 2.5, 2.5, 1])
            if c1.button("🔍", key=f"com_{row['trip_id']}_{filtro_tipo}"):
                st.session_state.selected_trip_id = row['trip_id']
                st.rerun()
            c2.markdown(f"<span class='table-text'><b>{row['linea']}</b> 🕒 {row.get('departure_time', row.get('arrival_time', ''))}</span>", unsafe_allow_html=True)
            c3.markdown(f"<span class='table-text'>Da: {row['fermata_partenza']}</span>", unsafe_allow_html=True)
            c4.markdown(f"<span class='table-text'>A: {row['fermata_arrivo']}</span>", unsafe_allow_html=True)
            c5.markdown(f"<span class='table-text'>📅 {row['giorni_validita']}g</span>", unsafe_allow_html=True)
    else:
        st.info("Nessuna corsa trovata per i criteri selezionati in questo comune.")

else:
    # Navigazione Classica
    if modalità_classica == "🔍 Corsa Singola":
        if trip_id_selezionato is not None:
            corsa_info = df_linea[df_linea['trip_id'] == trip_id_selezionato].iloc[0]
            
            st.markdown(f"""
            <div class="info-box">
                <b>🕒 Partenza:</b> {corsa_info['fermata_partenza']} ({corsa_info['comune_partenza']}) alle {corsa_info['departure_time']} &nbsp;&nbsp;|&nbsp;&nbsp;
                <b>🏁 Arrivo:</b> {corsa_info['fermata_arrivo']} ({corsa_info['comune_arrivo']}) alle {corsa_info['arrival_time']} &nbsp;&nbsp;|&nbsp;&nbsp;
                <b>📅 Giorni validità:</b> {corsa_info['giorni_validita']} giorni
            </div>
            """, unsafe_allow_html=True)

            st_trip = stop_times[stop_times['trip_id'] == trip_id_selezionato].sort_values('stop_sequence')
            path_stops = pd.merge(st_trip, stops_unique, on='stop_id')

            if not path_stops.empty:
                col_left, col_right = st.columns([1.1, 1.3])
                with col_left:
                    st.markdown("##### 📋 Fermate e Orari di Passaggio")
                    df_tab_fermate = path_stops[['stop_sequence', 'stop_name', 'departure_time', 'comune']].copy()
                    df_tab_fermate.columns = ['N°', 'Fermata', 'Orario', 'Comune']
                    st.dataframe(df_tab_fermate, use_container_width=True, hide_index=True, height=720)
                with col_right:
                    st.markdown(f"##### 🗺️ Mappa Percorso (Linea {linea_scelta})")
                    centro_lat, centro_lon = path_stops['stop_lat'].mean(), path_stops['stop_lon'].mean()
                    m = folium.Map(location=[centro_lat, centro_lon], zoom_start=12, tiles="Esri.WorldStreetMap")
                    coords = path_stops[['stop_lat', 'stop_lon']].values.tolist()
                    folium.PolyLine(coords, color="blue", weight=4, opacity=0.8).add_to(m)
                    for _, row in path_stops.iterrows():
                        folium.Marker(
                            location=[row['stop_lat'], row['stop_lon']],
                            popup=f"<b>{row['stop_name']}</b><br>Orario: {row.get('departure_time', '')}<br>Comune: {row['comune']}",
                            icon=folium.Icon(color='red', icon='bus', prefix='fa')
                        ).add_to(m)
                    st.components.v1.html(m._repr_html_(), height=720)
        else:
            st.info("Seleziona una linea e una corsa dalla barra laterale.")

    elif modalità_classica == "🌐 Intera Linea":
        if linea_scelta:
            st.markdown(f"#### 🌐 Panoramica Linea: **{linea_scelta}** (Operatore: {operatore_scelto})")
            col_left, col_right = st.columns([1.4, 1.1])
            with col_left:
                st.markdown("##### 📋 Elenco corse della linea")
                st.markdown("Clicca su **🔍** per visualizzare i dettagli della corsa.")
                
                with st.container(height=720):
                    if not df_linea.empty:
                        for _, row in df_linea.iterrows():
                            c1, c2, c3, c4, c5 = st.columns([0.8, 1.8, 3.2, 1.8, 3.2])
                            if c1.button("🔍", key=f"linea_btn_{row['trip_id']}"):
                                st.session_state.selected_trip_id = row['trip_id']
                                st.rerun()
                            c2.markdown(f"<span class='table-text'>🕒 {row['departure_time']}</span>", unsafe_allow_html=True)
                            c3.markdown(f"<span class='table-text'>Da: {row['fermata_partenza']}</span>", unsafe_allow_html=True)
                            c4.markdown(f"<span class='table-text'>🏁 {row['arrival_time']}</span>", unsafe_allow_html=True)
                            c5.markdown(f"<span class='table-text'>A: {row['fermata_arrivo']}</span>", unsafe_allow_html=True)
                    else:
                        st.info("Nessuna corsa disponibile per questa linea.")
            with col_right:
                st.markdown("##### 🗺️ Mappa Cumulativa Linea")
                trip_ids = df_linea['trip_id'].tolist()
                st_all = stop_times[stop_times['trip_id'].isin(trip_ids)]
                path_all = pd.merge(st_all, stops_unique, on='stop_id').drop_duplicates(subset=['stop_id'])
                if not path_all.empty:
                    m_lin = folium.Map(location=[path_all['stop_lat'].mean(), path_all['stop_lon'].mean()], zoom_start=11, tiles="Esri.WorldStreetMap")
                    for t_id in trip_ids[:15]:
                        st_t = stop_times[stop_times['trip_id'] == t_id].sort_values('stop_sequence')
                        p_t = pd.merge(st_t, stops_unique, on='stop_id')
                        if len(p_t) > 1:
                            folium.PolyLine(p_t[['stop_lat', 'stop_lon']].