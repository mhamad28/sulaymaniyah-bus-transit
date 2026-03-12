import streamlit as st
from supabase import create_client, Client
import pandas as pd
import pydeck as pdk
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# --- 1. SETUP ---
URL = st.secrets["SUPABASE_URL"]
KEY = st.secrets["SUPABASE_ANON_KEY"]
supabase: Client = create_client(URL, KEY)

st.set_page_config(page_title="Suly Transit – Manager Dashboard", layout="wide")

# This automatically refreshes the data every 10 seconds WITHOUT locking the UI
st_autorefresh(interval=10000, key="datarefresh")

# --- 2. DATA FETCHING ---
def get_live_data():
    try:
        res = supabase.table("live_bus_data").select("*").execute()
        return pd.DataFrame(res.data)
    except:
        return pd.DataFrame()

def get_bus_stats(plate):
    try:
        res = supabase.table("bus_location_history") \
            .select("*") \
            .eq("plate_number", plate) \
            .order("recorded_at", desc=False) \
            .execute()
        return pd.DataFrame(res.data)
    except:
        return pd.DataFrame()

# --- 3. UI LAYOUT ---
st.title("📊 Fleet Research Manager")

df_live = get_live_data()

# Sidebar: These will now work perfectly!
st.sidebar.header("🕹️ Controls")
show_map = st.sidebar.toggle("🛰️ View Fleet on Map", value=False)
map_style = st.sidebar.selectbox("Map Style", ["Satellite", "Dark", "Light"])

if not df_live.empty:
    st.metric("Total Active Buses", len(df_live))
    
    # --- LIST ALL BUSES ---
    st.subheader("🚐 Current Active Fleet")
    
    for _, bus in df_live.iterrows():
        # Clean labels for your research
        with st.expander(f"🚌 Bus {bus['plate_number']} | Line: {bus['line_id']} | Driver: {bus['driver_name']}", expanded=True):
            col1, col2, col3 = st.columns(3)
            
            hist = get_bus_stats(bus['plate_number'])
            
            if not hist.empty:
                start_time = pd.to_datetime(hist['recorded_at'].min())
                duration = datetime.now(start_time.tzinfo) - start_time
                
                col1.metric("Shift Start", start_time.strftime("%H:%M:%S"))
                col2.metric("Working Time", f"{duration.seconds // 60} min")
                col3.metric("Data Points Collected", len(hist))
                
                # Checkbox now works because the while loop is gone
                if st.checkbox(f"Show Logs for {bus['plate_number']}", key=f"log_{bus['plate_number']}"):
                    st.dataframe(hist.tail(10), use_container_width=True)

    # --- OPTIONAL MAP VIEW ---
    if show_map:
        st.divider()
        st.subheader(f"🌍 Live {map_style} Tracking")
        
        # Map Styles
        styles = {
            "Satellite": "mapbox://styles/mapbox/satellite-v9",
            "Dark": "mapbox://styles/mapbox/dark-v10",
            "Light": "mapbox://styles/mapbox/light-v10"
        }
        
        view = pdk.ViewState(latitude=df_live["lat"].mean(), longitude=df_live["lon"].mean(), zoom=11)
        layer = pdk.Layer(
            "ScatterplotLayer",
            df_live,
            get_position='[lon, lat]',
            get_color='[34, 197, 94, 255]', 
            get_radius=250,
            pickable=True
        )
        
        st.pydeck_chart(pdk.Deck(
            layers=[layer],
            initial_view_state=view,
            map_style=styles[map_style],
            tooltip={"text": "Bus: {plate_number}\nDriver: {driver_name}"}
        ))

else:
    st.warning("No buses are currently reporting data.")
    
