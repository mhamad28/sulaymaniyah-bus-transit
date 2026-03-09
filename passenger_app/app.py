import streamlit as st
import pandas as pd
import json
import math
import folium
from folium.plugins import Fullscreen
from streamlit_folium import st_folium
from supabase import create_client

st.set_page_config(page_title="Suly Transit", layout="wide")

# -----------------------------
# Supabase
# -----------------------------
def get_supabase():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = get_supabase()

# -----------------------------
# Helpers
# -----------------------------
def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c

@st.cache_data
def load_routes():
    with open("assets/bus_lines.geojson", "r", encoding="utf-8") as f:
        return json.load(f)

@st.cache_data
def extract_route_points(routes_geojson):
    rows = []
    for feature in routes_geojson["features"]:
        route_name = feature["properties"].get("layer", "Unknown Route")
        geometry = feature.get("geometry", {})
        coords = geometry.get("coordinates", [])

        if geometry.get("type") == "LineString":
            for idx, coord in enumerate(coords):
                lon, lat = coord[0], coord[1]
                rows.append(
                    {
                        "route_name": route_name,
                        "point_order": idx,
                        "lat": lat,
                        "lon": lon,
                    }
                )
    return pd.DataFrame(rows)

def nearest_route(point_lat, point_lon, route_points_df):
    df = route_points_df.copy()
    df["distance_km"] = df.apply(
        lambda row: haversine_km(point_lat, point_lon, row["lat"], row["lon"]),
        axis=1,
    )
    return df.sort_values("distance_km").iloc[0].to_dict()

def get_live_buses():
    result = supabase.table("live_bus_data").select("*").execute()
    if result.data:
        return pd.DataFrame(result.data)
    return pd.DataFrame(columns=["plate_number", "driver_name", "line_id", "lat", "lon", "last_ping"])

# -----------------------------
# Colors
# -----------------------------
ROUTE_COLORS = {
    "Bakrajo_Bazar": "#e41a1c",
    "Chwarchra_Bazar": "#377eb8",
    "FarmanBaran_Bazar": "#4daf4a",
    "HawaryShar_Bazar": "#984ea3",
    "Kazywa_Bazar": "#ff7f00",
    "Kshtukal_Bazar": "#a65628",
    "Qrgra_Bazar": "#f781bf",
    "Raparin_Bazar": "#999999",
    "Rzgary Bazar": "#66c2a5",
    "Shakraka_Bazar": "#fc8d62",
    "TwiMalik_Bazar": "#8da0cb",
    "Xabat_Bazar": "#ffd92f",
    "ZargatayTaza_Bazar": "#1b9e77",
}

# -----------------------------
# Session state
# -----------------------------
if "origin_point" not in st.session_state:
    st.session_state.origin_point = None
if "destination_point" not in st.session_state:
    st.session_state.destination_point = None
if "pick_mode" not in st.session_state:
    st.session_state.pick_mode = "origin"

# -----------------------------
# Load data
# -----------------------------
routes_geojson = load_routes()
route_points_df = extract_route_points(routes_geojson)
live_df = get_live_buses()

# -----------------------------
# UI
# -----------------------------
st.title("Suly Transit")

c1, c2, c3 = st.columns(3)

with c1:
    if st.button("Pick Origin"):
        st.session_state.pick_mode = "origin"

with c2:
    if st.button("Pick Destination"):
        st.session_state.pick_mode = "destination"

with c3:
    if st.button("Clear"):
        st.session_state.origin_point = None
        st.session_state.destination_point = None
        st.session_state.pick_mode = "origin"
        st.rerun()

st.caption(f"Current selection mode: {st.session_state.pick_mode}")

# -----------------------------
# Route suggestion logic
# -----------------------------
highlight_route = None
trip_result = None

if st.session_state.origin_point and st.session_state.destination_point:
    origin_route = nearest_route(
        st.session_state.origin_point["lat"],
        st.session_state.origin_point["lon"],
        route_points_df,
    )
    destination_route = nearest_route(
        st.session_state.destination_point["lat"],
        st.session_state.destination_point["lon"],
        route_points_df,
    )

    trip_result = {
        "origin_route": origin_route,
        "destination_route": destination_route,
    }

    if origin_route["route_name"] == destination_route["route_name"]:
        highlight_route = origin_route["route_name"]

# -----------------------------
# Map
# -----------------------------
m = folium.Map(
    location=[35.56, 45.43],
    zoom_start=12,
    tiles="CartoDB positron",
    control_scale=True,
)

Fullscreen().add_to(m)

for feature in routes_geojson["features"]:
    route_name = feature["properties"].get("layer", "Bus Route")
    color = ROUTE_COLORS.get(route_name, "#3388ff")

    if highlight_route:
        opacity = 0.95 if route_name == highlight_route else 0.20
        weight = 6 if route_name == highlight_route else 3
    else:
        opacity = 0.80
        weight = 4

    folium.GeoJson(
        feature,
        tooltip=route_name,
        style_function=lambda x, color=color, weight=weight, opacity=opacity: {
            "color": color,
            "weight": weight,
            "opacity": opacity,
        },
    ).add_to(m)

if not live_df.empty:
    for _, row in live_df.iterrows():
        if pd.notna(row["lat"]) and pd.notna(row["lon"]):
            folium.CircleMarker(
                location=[row["lat"], row["lon"]],
                radius=6,
                color="orange",
                fill=True,
                fill_opacity=0.9,
                popup=(
                    f"Bus: {row['plate_number']}<br>"
                    f"Line: {row.get('line_id', 'Unknown')}"
                ),
            ).add_to(m)

if st.session_state.origin_point:
    folium.Marker(
        [st.session_state.origin_point["lat"], st.session_state.origin_point["lon"]],
        tooltip="Origin",
        icon=folium.Icon(color="green"),
    ).add_to(m)

if st.session_state.destination_point:
    folium.Marker(
        [st.session_state.destination_point["lat"], st.session_state.destination_point["lon"]],
        tooltip="Destination",
        icon=folium.Icon(color="red"),
    ).add_to(m)

map_data = st_folium(m, height=650, width="stretch")

clicked = map_data.get("last_clicked") if map_data else None
if clicked:
    point = {"lat": clicked["lat"], "lon": clicked["lng"]}

    if st.session_state.pick_mode == "origin":
        st.session_state.origin_point = point
        st.session_state.pick_mode = "destination"
    else:
        st.session_state.destination_point = point
        st.session_state.pick_mode = "origin"

    st.rerun()

# -----------------------------
# Result
# -----------------------------
if trip_result:
    st.subheader("Suggested Route")

    origin_route = trip_result["origin_route"]
    destination_route = trip_result["destination_route"]

    st.write(f"Nearest to origin: **{origin_route['route_name']}**")
    st.write(f"Nearest to destination: **{destination_route['route_name']}**")

    if origin_route["route_name"] == destination_route["route_name"]:
        route_name = origin_route["route_name"]
        st.success(f"Recommended line: {route_name}")

        if not live_df.empty and "line_id" in live_df.columns:
            line_buses = live_df[live_df["line_id"] == route_name].copy()

            if not line_buses.empty:
                line_buses["eta_minutes"] = line_buses.apply(
                    lambda row: haversine_km(
                        row["lat"],
                        row["lon"],
                        st.session_state.origin_point["lat"],
                        st.session_state.origin_point["lon"],
                    ) / 18 * 60,
                    axis=1,
                )

                best_bus = line_buses.sort_values("eta_minutes").iloc[0]
                st.info(f"Nearest active bus: {best_bus['plate_number']} | ETA: {best_bus['eta_minutes']:.1f} min")
            else:
                st.info("No active bus currently on this line.")
    else:
        st.warning("Origin and destination are on different nearby routes.")
