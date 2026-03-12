import streamlit as st
from supabase import create_client, Client
import pandas as pd
import pydeck as pdk
import time
from datetime import datetime

# --- 1. SETUP ---
URL = st.secrets["SUPABASE_URL"]
KEY = st.secrets["SUPABASE_ANON_KEY"]
supabase: Client = create_client(URL, KEY)

st.set_page_config(page_title="Suly Transit – Manager", layout="wide")

# --- 2. DATA FETCHING ---
def get_live_data():
    try:
        res = supabase.table("live_bus_data").select("*").execute()
        return pd.DataFrame(res.data)
    except Exception as e:
        st.error(f"Error fetching live data: {e}")
        return pd.DataFrame()

def get_bus_stats(plate):
    try:
        # Correcting the query chain to prevent TypeErrors
        res = supabase.table("bus_location_history") \
            .select("*") \
            .eq("plate_number", plate) \
            .order("recorded_at", desc=False) \
            .execute()
        return pd.DataFrame(res.data)
    except Exception as e:
        # Silently return empty if fails to keep app running
        return pd.DataFrame()

# --- 3. UI LAYOUT ---
st.title("🛰️ Suly Transit Live Monitor")

df_live = get_live_data()

# SIDEBAR CONTROLS
st.sidebar.header("🕹️ Controls")
show_map = st.sidebar.checkbox("Show Live Map", value=True)
map_style = st.sidebar.selectbox("Map Style", ["Dark", "Light", "Satellite"])

style_url = "mapbox://styles/mapbox/dark-v10"
if map_style == "Light": style_url = "mapbox://styles/mapbox/light-v10"
if map_style == "Satellite": style_url = "mapbox://styles/mapbox/satellite-v9"

if not df_live.empty:
    st.sidebar.header("🚌 Active Fleet")
    selected_bus = st.sidebar.selectbox("Select Bus for Details", ["All Buses"] + list(df_live["plate_number"]))

    # Main Layout
    col_left, col_right = st.columns([3, 1])

    with col_left:
        if show_map:
            view = pdk.ViewState(latitude=df_live["lat"].mean(), longitude=df_live["lon"].mean(), zoom=12)
            layer = pdk.Layer(
                "ScatterplotLayer",
                df_live,
                get_position='[lon, lat]',
                get_color='[34, 197, 94, 200]',
                get_radius=200,
                pickable=True
            )
            st.pydeck_chart(pdk.Deck(
                layers=[layer], 
                initial_view_state=view, 
                map_style=style_url,
                tooltip={"text": "Bus: {plate_number}\nLine: {line_id}"}
            ))
        else:
            st.info("Map is hidden. Enable 'Show Live Map' in the sidebar to view.")

    with col_right:
        if selected_bus != "All Buses":
            bus_info = df_live[df_live["plate_number"] == selected_bus].iloc[0]
            hist = get_bus_stats(selected_bus)
            
            st.subheader(f"Stats: {selected_bus}")
            st.markdown(f"**Driver:** {bus_info['driver_name']}")
            
            if not hist.empty:
                # 1. Start Time
                start_time = pd.to_datetime(hist['recorded_at'].min())
                st.metric("Shift Start", start_time.strftime("%H:%M:%S"))
                
                # 2. Distance Calculation (Simplified)
                # For research, we sum distance between consecutive points
                st.metric("Logged Points", len(hist))
                
                # 3. Last Seen
                last_seen = pd.to_datetime(bus_info['last_ping'])
                st.write(f"Last Ping: {last_seen.strftime('%H:%M:%S')}")

# Auto-refresh
time.sleep(5)
st.rerun()
