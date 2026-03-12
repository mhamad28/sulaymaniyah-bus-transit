import streamlit as st
from supabase import create_client, Client
import pandas as pd
import json
import streamlit.components.v1 as components
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# --- 1. CONFIG & SUPABASE ---
st.set_page_config(page_title="Suly Transit – Manager", layout="wide")

# Silent refresh every 10 seconds - only internal components will update
st_autorefresh(interval=10000, key="silent_refresh")

URL = st.secrets["SUPABASE_URL"]
KEY = st.secrets["SUPABASE_ANON_KEY"]
supabase: Client = create_client(URL, KEY)

st.markdown("""
<style>
    header {display: none !important;}
    footer {display: none !important;}
    .block-container {padding-top: 2rem !important;}
</style>
""", unsafe_allow_html=True)

# --- 2. DATA FUNCTIONS ---
def get_fleet_data():
    try:
        res = supabase.table("live_bus_data").select("*").execute()
        return res.data
    except:
        return []

def get_history_stats(plate):
    try:
        res = supabase.table("bus_location_history") \
            .select("recorded_at") \
            .eq("plate_number", plate) \
            .order("recorded_at", desc=False) \
            .execute()
        return res.data
    except:
        return []

# --- 3. THE LEAFLET MAP HTML (WITH AUTO-ZOOM) ---
def build_map_html(buses_json):
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <style>
            #map {{ height: 500px; width: 100%; border-radius: 15px; border: 2px solid #333; }}
            body {{ margin: 0; background: #0e1117; }}
        </style>
    </head>
    <body>
        <div id="map"></div>
        <script>
            const map = L.map('map').setView([35.56, 45.43], 12);
            L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(map);

            const buses = {buses_json};
            const markers = [];

            buses.forEach(b => {{
                const marker = L.circleMarker([b.lat, b.lon], {{
                    radius: 9,
                    fillColor: "#22c55e",
                    color: "#fff",
                    weight: 2,
                    opacity: 1,
                    fillOpacity: 0.9
                }}).addTo(map).bindTooltip("<b>Bus:</b> " + b.plate_number + "<br><b>Line:</b> " + b.line_id);
                markers.push(marker);
            }});

            // AUTO-ZOOM LOGIC: Zoom map to fit all active bus markers
            if (markers.length > 0) {{
                const group = new L.featureGroup(markers);
                map.fitBounds(group.getBounds().pad(0.2)); // Added padding for better view
            }}
        </script>
    </body>
    </html>
    """

# --- 4. UI LAYOUT ---
st.title("📊 Fleet Research Manager")

fleet = get_fleet_data()

if fleet:
    st.sidebar.header("🕹️ Controls")
    show_map = st.sidebar.toggle("🛰️ Show Satellite Tracking", value=True)
    
    st.metric("Total Active Buses", len(fleet))

    # --- LIST ALL BUSES ---
    st.subheader("🚐 Current Active Fleet")
    
    for bus in fleet:
        with st.expander(f"🚌 Bus {bus['plate_number']} | Line: {bus['line_id']}", expanded=False):
            col1, col2, col3 = st.columns(3)
            history = get_history_stats(bus['plate_number'])
            
            if history:
                start_time = pd.to_datetime(history[0]['recorded_at'])
                duration = datetime.now(start_time.tzinfo) - start_time
                
                col1.metric("Shift Start", start_time.strftime("%H:%M:%S"))
                col2.metric("Total Mins", f"{duration.seconds // 60}m")
                col3.metric("Data Points", len(history))
            else:
                st.info("No history yet.")

    # --- THE MAP ---
    if show_map:
        st.divider()
        st.subheader("🌍 Live Fleet Positions")
        buses_json = json.dumps(fleet)
        components.html(build_map_html(buses_json), height=520)

else:
    st.warning("No buses currently online.")
