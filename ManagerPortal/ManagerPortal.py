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

# Custom CSS for a "Command Center" look
st.markdown("""
    <style>
    .metric-card {
        background-color: #0e1117;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #262730;
    }
    </style>
""", unsafe_allow_html=True)

# --- 2. DATA FETCHING ---
def get_live_data():
    res = supabase.table("live_bus_data").select("*").execute()
    return pd.DataFrame(res.data)

def get_bus_stats(plate):
    # Fetch recent history for this bus to calculate distance/speed
    res = supabase.table("bus_location_history")\
        .select("*")\
        .eq("plate_number", plate)\
        .order("recorded_at", ascending=True)\
        .execute()
    return pd.DataFrame(res.data)

# --- 3. UI LAYOUT ---
st.title("🛰️ Suly Transit Live Monitor")

df_live = get_live_data()

if not df_live.empty:
    # Sidebar for selection
    st.sidebar.header("🚌 Active Fleet")
    selected_bus = st.sidebar.selectbox("Select Bus for Details", ["All Buses"] + list(df_live["plate_number"]))

    # Main Layout: Map (Left) and Stats (Right)
    col_map, col_stats = st.columns([3, 1])

    with col_map:
        # Highlight selected bus color
        df_live["color"] = df_live["plate_number"].apply(
            lambda x: [255, 255, 255, 255] if x == selected_bus else [34, 197, 94, 200]
        )
        
        view = pdk.ViewState(latitude=df_live["lat"].mean(), longitude=df_live["lon"].mean(), zoom=12)
        layer = pdk.Layer(
            "ScatterplotLayer",
            df_live,
            get_position='[lon, lat]',
            get_color='color',
            get_radius=200,
            pickable=True
        )
        st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view, tooltip=True))

    with col_stats:
        if selected_bus != "All Buses":
            bus_info = df_live[df_live["plate_number"] == selected_bus].iloc[0]
            hist = get_bus_stats(selected_bus)
            
            st.subheader(f"Details: {selected_bus}")
            st.markdown(f"**Driver:** {bus_info['driver_name']}")
            st.markdown(f"**Line:** {bus_info['line_id']}")
            
            if not hist.empty:
                # Calculations
                start_time = pd.to_datetime(hist['recorded_at'].min())
                now_time = datetime.now(start_time.tzinfo)
                duration = now_time - start_time
                
                st.divider()
                st.metric("Started At", start_time.strftime("%H:%M:%S"))
                st.metric("Time Working", f"{duration.seconds // 60} minutes")
                st.metric("Total Data Points", len(hist)) # [cite: 1, 10]
                
                # Show raw data preview for the researcher
                if st.checkbox("Show Logs"):
                    st.dataframe(hist.tail(5))
        else:
            st.info("Select a bus from the sidebar or click one on the map to see details.")
            st.metric("Total Buses Online", len(df_live))

else:
    st.warning("No buses are currently reporting location.")

# Auto-refresh
time.sleep(5)
st.rerun()
