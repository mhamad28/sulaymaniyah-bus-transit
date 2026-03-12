import streamlit as st
from supabase import create_client, Client
import pandas as pd
import pydeck as pdk
import time

# --- 1. SETUP ---
# Use the same secrets as the driver app
URL = st.secrets["SUPABASE_URL"]
KEY = st.secrets["SUPABASE_ANON_KEY"]
supabase: Client = create_client(URL, KEY)

st.set_page_config(page_title="Suly Transit – Manager Dashboard", layout="wide")

st.title("📊 Suly Transit Live Monitor")

# --- 2. THE LIVE MAP LOOP ---
# Placeholder for the map so it updates in-place
map_placeholder = st.empty()
stats_placeholder = st.sidebar.empty()

while True:
    # A. Fetch data from Supabase
    response = supabase.table("live_bus_data").select("*").execute()
    df = pd.DataFrame(response.data)

    if not df.empty:
        # B. Map Visualization with PyDeck
        view_state = pdk.ViewState(
            latitude=df["lat"].mean(),
            longitude=df["lon"].mean(),
            zoom=12,
            pitch=0
        )

        layer = pdk.Layer(
            "ScatterplotLayer",
            df,
            get_position='[lon, lat]',
            get_color='[34, 197, 94, 200]', # Green dots
            get_radius=150,
            pickable=True,
        )

        # C. Update the Map
        map_placeholder.pydeck_chart(pdk.Deck(
            layers=[layer],
            initial_view_state=view_state,
            tooltip={"text": "Bus: {plate_number}\nDriver: {driver_name}\nLine: {line_id}"}
        ))

        # D. Update Sidebar Stats
        with stats_placeholder.container():
            st.metric("Active Buses", len(df))
            st.write("### Active List")
            for _, row in df.iterrows():
                st.info(f"🚌 {row['plate_number']} - {row['line_id']}")
    else:
        map_placeholder.warning("No buses are currently active.")

    # Refresh every 5 seconds to avoid spamming the API
    time.sleep(5)
    st.rerun()
