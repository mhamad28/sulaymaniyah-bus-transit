import streamlit as st
import pandas as pd
import json
import math
import folium
from streamlit_folium import st_folium
from supabase import create_client

st.set_page_config(
    page_title="Suly Transit",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
html, body, [data-testid="stAppViewContainer"] {
    margin: 0;
    padding: 0;
    height: 100%;
    overflow: hidden;
}

[data-testid="stHeader"] {
    background: rgba(0, 0, 0, 0);
}

[data-testid="stAppViewContainer"] > .main {
    padding: 0 !important;
}

.block-container {
    padding: 0 !important;
    margin: 0 !important;
    max-width: 100% !important;
}

.top-bar {
    position: fixed;
    top: 12px;
    left: 12px;
    right: 12px;
    z-index: 9999;
    background: rgba(10, 15, 25, 0.80);
    border-radius: 14px;
    padding: 10px 14px 6px 14px;
    backdrop-filter: blur(6px);
}

.map-caption {
    position: fixed;
    bottom: 14px;
    left: 14px;
    z-index: 9999;
    background: rgba(10, 15, 25, 0.75);
    color: white;
    padding: 10px 14px;
    border-radius: 12px;
    font-size: 14px;
}

.result-box {
    position: fixed;
    top: 96px;
    right: 14px;
    width: 320px;
    z-index: 9999;
    background: rgba(10, 15, 25, 0.82);
    color: white;
    padding: 14px;
    border-radius: 14px;
    backdrop-filter: blur(6px);
}

div[data-testid="stHorizontalBlock"] > div {
    background: transparent !important;
}

iframe {
    border-radius: 0 !important;
}
</style>
""", unsafe_allow_html=True)

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
# Route colors
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
if "map_center" not in st.session_state:
    st.session_state.map_center = [35.56, 45.43]
if "map_zoom" not in st.session_state:
    st.session_state.map_zoom = 13

# -----------------------------
# Load data
# -----------------------------
routes_geojson = load_routes()
route_points_df = extract_route_points(routes_geojson)
live_df = get_live_buses()

# -----------------------------
# Compute result
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
# Top controls
# -----------------------------
st.markdown('<div class="top-bar">', unsafe_allow_html=True)

st.markdown("### Suly Transit")

c1, c2, c3, c4 = st.columns([1, 1, 1, 2])

with c1:
    if st.button("Pick Origin", use_container_width=True):
        st.session_state.pick_mode = "origin"

with c2:
    if st.button("Pick Destination", use_container_width=True):
        st.session_state.pick_mode = "destination"

with c3:
    if st.button("Clear", use_container_width=True):
        st.session_state.origin_point = None
        st.session_state.destination_point = None
        st.session_state.pick_mode = "origin"
        st.rerun()

with c4:
    st.write(f"Mode: **{st.session_state.pick_mode}**")

st.markdown('</div>', unsafe_allow_html=True)

# -----------------------------
# Build map
# -----------------------------
m = folium.Map(
    location=st.session_state.map_center,
    zoom_start=st.session_state.map_zoom,
    tiles="CartoDB positron",
    control_scale=True,
    zoom_control=True,
)

# Draw routes
for feature in routes_geojson["features"]:
    route_name = feature["properties"].get("layer", "Bus Route")
    color = ROUTE_COLORS.get(route_name, "#3388ff")

    if highlight_route:
        opacity = 0.95 if route_name == highlight_route else 0.20
        weight = 6 if route_name == highlight_route else 2
    else:
        opacity = 0.75
        weight = 3

    folium.GeoJson(
        feature,
        tooltip=route_name,
        style_function=lambda x, color=color, weight=weight, opacity=opacity: {
            "color": color,
            "weight": weight,
            "opacity": opacity,
        },
    ).add_to(m)

# Live buses
if not live_df.empty:
    for _, row in live_df.iterrows():
        if pd.notna(row["lat"]) and pd.notna(row["lon"]):
            folium.CircleMarker(
                location=[row["lat"], row["lon"]],
                radius=6,
                color="orange",
                fill=True,
                fill_color="orange",
                fill_opacity=0.95,
                popup=(
                    f"Bus: {row.get('plate_number', 'Unknown')}<br>"
                    f"Line: {row.get('line_id', 'Unknown')}"
                ),
            ).add_to(m)

# Origin marker
if st.session_state.origin_point:
    folium.Marker(
        [st.session_state.origin_point["lat"], st.session_state.origin_point["lon"]],
        tooltip="Origin",
        icon=folium.Icon(color="green"),
    ).add_to(m)

# Destination marker
if st.session_state.destination_point:
    folium.Marker(
        [st.session_state.destination_point["lat"], st.session_state.destination_point["lon"]],
        tooltip="Destination",
        icon=folium.Icon(color="red"),
    ).add_to(m)

# -----------------------------
# Full-page map
# -----------------------------
map_data = st_folium(
    m,
    height=900,
    width="stretch",
    returned_objects=["last_clicked", "center", "zoom"],
)

if map_data:
    if map_data.get("center"):
        st.session_state.map_center = [
            map_data["center"]["lat"],
            map_data["center"]["lng"],
        ]
    if map_data.get("zoom"):
        st.session_state.map_zoom = map_data["zoom"]

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
# Floating result box
# -----------------------------
if trip_result:
    origin_route = trip_result["origin_route"]
    destination_route = trip_result["destination_route"]

    result_html = f"""
    <div class="result-box">
        <h4 style="margin-top:0;">Suggested Route</h4>
        <div style="font-size:14px; margin-bottom:8px;">
            Origin nearest: <b>{origin_route['route_name']}</b><br>
            Destination nearest: <b>{destination_route['route_name']}</b>
        </div>
    """

    if origin_route["route_name"] == destination_route["route_name"]:
        route_name = origin_route["route_name"]
        result_html += f"""
        <div style="padding:10px; background:#113b22; border-radius:10px; margin-top:8px;">
            Recommended line: <b>{route_name}</b>
        </div>
        """

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
                result_html += f"""
                <div style="padding:10px; background:#12304a; border-radius:10px; margin-top:8px;">
                    Nearest bus: <b>{best_bus['plate_number']}</b><br>
                    ETA: <b>{best_bus['eta_minutes']:.1f} min</b>
                </div>
                """
            else:
                result_html += """
                <div style="padding:10px; background:#2e2e2e; border-radius:10px; margin-top:8px;">
                    No active bus on this line.
                </div>
                """
    else:
        result_html += """
        <div style="padding:10px; background:#5c3a12; border-radius:10px; margin-top:8px;">
            Origin and destination are on different nearby routes.
        </div>
        """

    result_html += "</div>"
    st.markdown(result_html, unsafe_allow_html=True)

# -----------------------------
# Floating footer info
# -----------------------------
footer_text = []
if st.session_state.origin_point:
    footer_text.append(
        f"Origin: {st.session_state.origin_point['lat']:.5f}, {st.session_state.origin_point['lon']:.5f}"
    )
if st.session_state.destination_point:
    footer_text.append(
        f"Destination: {st.session_state.destination_point['lat']:.5f}, {st.session_state.destination_point['lon']:.5f}"
    )
if not live_df.empty:
    footer_text.append(f"Active buses: {len(live_df)}")

if footer_text:
    st.markdown(
        f'<div class="map-caption">{" | ".join(footer_text)}</div>',
        unsafe_allow_html=True
    )
