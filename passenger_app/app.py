import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from shared.db import get_supabase

st.set_page_config(page_title="Sulaymaniyah Bus Transit", layout="wide")

supabase = get_supabase()

@st.cache_data
def load_route():
    return pd.read_csv("assets/l v l.csv")

df_route = load_route()

st.title("🚌 Sulaymaniyah Bus Transit")
st.subheader("Passenger Portal")
st.write("See the live route and active buses.")

# Optional manual refresh button
if st.button("Refresh live buses"):
    st.cache_data.clear()

# Fetch live buses from Supabase
response = supabase.table("live_bus_data").select("*").execute()
live_buses = response.data if response.data else []

# Build map
m = folium.Map(location=[35.5852, 45.4390], zoom_start=14)

# Draw route line
folium.PolyLine(
    df_route[["Y", "X"]].values,
    color="blue",
    weight=5,
    opacity=0.7,
    tooltip="Bus Route"
).add_to(m)

# Plot live buses
if live_buses:
    for bus in live_buses:
        lat = bus.get("lat")
        lon = bus.get("lon")

        if lat is not None and lon is not None:
            plate = bus.get("plate_number", "Unknown")
            driver = bus.get("driver_name", "Unknown")
            line_id = bus.get("line_id", "N/A")
            last_ping = bus.get("last_ping", "N/A")

            folium.Marker(
                [lat, lon],
                popup=(
                    f"<b>Bus:</b> {plate}<br>"
                    f"<b>Driver:</b> {driver}<br>"
                    f"<b>Line:</b> {line_id}<br>"
                    f"<b>Last update:</b> {last_ping}"
                ),
                tooltip=f"Bus {plate}",
                icon=folium.Icon(color="red", icon="bus", prefix="fa")
            ).add_to(m)

    st.success(f"{len(live_buses)} active bus(es) found.")
else:
    st.warning("No buses are currently broadcasting.")

st_folium(m, width=1400, height=650)
