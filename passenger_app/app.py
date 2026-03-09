import streamlit as st
import folium
from streamlit_folium import st_folium
import json
import math
import base64
import pandas as pd


# --------------------------------------------------
# PAGE CONFIG
# --------------------------------------------------
st.set_page_config(page_title="Suly Transit Map", layout="wide")


# --------------------------------------------------
# BACKGROUND
# --------------------------------------------------
def set_background(image_file: str) -> None:
    with open(image_file, "rb") as img:
        encoded = base64.b64encode(img.read()).decode()

    page_bg = f"""
    <style>
    .stApp {{
        background-image: linear-gradient(
            rgba(10, 15, 30, 0.45),
            rgba(10, 15, 30, 0.65)
        ), url("data:image/jpg;base64,{encoded}");
        background-size: cover;
        background-position: center;
        background-attachment: fixed;
    }}

    [data-testid="stHeader"] {{
        background: rgba(0, 0, 0, 0);
    }}

    .block-container {{
        background-color: rgba(0, 0, 0, 0.08);
        padding: 1.5rem;
        border-radius: 18px;
    }}

    .glass-card {{
        background: rgba(10, 20, 35, 0.45);
        border: 1px solid rgba(255,255,255,0.08);
        backdrop-filter: blur(8px);
        padding: 1rem 1.2rem;
        border-radius: 16px;
        margin-bottom: 1rem;
    }}
    </style>
    """
    st.markdown(page_bg, unsafe_allow_html=True)


set_background("assets/suli_bg.jpg")


# --------------------------------------------------
# ROUTE COLORS
# --------------------------------------------------
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


# --------------------------------------------------
# HELPERS
# --------------------------------------------------
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
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
def load_routes_geojson(path="assets/bus_lines.geojson"):
    with open(path, "r", encoding="utf-8") as f:
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


def nearest_route(point_lat: float, point_lon: float, routes_geojson):
    route_points_df = extract_route_points(routes_geojson).copy()

    if route_points_df.empty:
        return None

    route_points_df["distance_km"] = route_points_df.apply(
        lambda row: haversine_km(point_lat, point_lon, row["lat"], row["lon"]),
        axis=1,
    )

    nearest = route_points_df.sort_values("distance_km").iloc[0]
    return nearest.to_dict()


def build_passenger_map(
    routes_geojson,
    origin_point=None,
    destination_point=None,
    highlight_route=None,
    show_all_lines=True,
):
    m = folium.Map(
        location=[35.56, 45.43],
        zoom_start=12,
        tiles="OpenStreetMap",
        control_scale=True,
    )

    if show_all_lines:
        all_routes_layer = folium.FeatureGroup(name="All Bus Lines", show=True)

        for feature in routes_geojson["features"]:
            route_name = feature["properties"].get("layer", "Bus Route")
            color = ROUTE_COLORS.get(route_name, "#00bfff")

            opacity = 0.35 if highlight_route and route_name != highlight_route else 0.8
            weight = 3 if highlight_route and route_name != highlight_route else 5

            folium.GeoJson(
                feature,
                tooltip=route_name,
                style_function=lambda x, color=color, weight=weight, opacity=opacity: {
                    "color": color,
                    "weight": weight,
                    "opacity": opacity,
                },
            ).add_to(all_routes_layer)

        all_routes_layer.add_to(m)

    if highlight_route:
        recommended_layer = folium.FeatureGroup(name="Recommended Route", show=True)

        for feature in routes_geojson["features"]:
            route_name = feature["properties"].get("layer", "Bus Route")
            if route_name == highlight_route:
                color = ROUTE_COLORS.get(route_name, "#00bfff")

                folium.GeoJson(
                    feature,
                    tooltip=f"Recommended: {route_name}",
                    style_function=lambda x, color=color: {
                        "color": color,
                        "weight": 7,
                        "opacity": 1.0,
                    },
                ).add_to(recommended_layer)

        recommended_layer.add_to(m)

    points_layer = folium.FeatureGroup(name="Points", show=True)

    if origin_point:
        folium.Marker(
            location=[origin_point["lat"], origin_point["lon"]],
            popup=origin_point.get("label", "Origin"),
            tooltip="Origin",
            icon=folium.Icon(color="green", icon="play"),
        ).add_to(points_layer)

    if destination_point:
        folium.Marker(
            location=[destination_point["lat"], destination_point["lon"]],
            popup=destination_point.get("label", "Destination"),
            tooltip="Destination",
            icon=folium.Icon(color="red", icon="flag"),
        ).add_to(points_layer)

    points_layer.add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)

    return m


# --------------------------------------------------
# SESSION STATE
# --------------------------------------------------
defaults = {
    "origin_point": None,
    "destination_point": None,
}
for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


# --------------------------------------------------
# APP
# --------------------------------------------------
st.title("Suly Transit System")
st.subheader("Static Passenger Map")

routes_geojson = load_routes_geojson("assets/bus_lines.geojson")

top1, top2 = st.columns([1, 5])
with top1:
    if st.button("🔄 Reset Points", width="stretch"):
        st.session_state.origin_point = None
        st.session_state.destination_point = None
        st.rerun()

with top2:
    st.info(
        "Click once on the map to set your origin. "
        "Click a second time to set your destination."
    )

st.markdown('<div class="glass-card">', unsafe_allow_html=True)

show_all_lines = st.checkbox("Show all bus lines", value=True)

highlight_route = None
origin_route = None
destination_route = None

if st.session_state.origin_point and st.session_state.destination_point:
    origin_route = nearest_route(
        st.session_state.origin_point["lat"],
        st.session_state.origin_point["lon"],
        routes_geojson,
    )
    destination_route = nearest_route(
        st.session_state.destination_point["lat"],
        st.session_state.destination_point["lon"],
        routes_geojson,
    )

    if origin_route and destination_route:
        if origin_route["route_name"] == destination_route["route_name"]:
            highlight_route = origin_route["route_name"]

passenger_map = build_passenger_map(
    routes_geojson=routes_geojson,
    origin_point=st.session_state.origin_point,
    destination_point=st.session_state.destination_point,
    highlight_route=highlight_route,
    show_all_lines=show_all_lines,
)

map_data = st_folium(passenger_map, height=700, width="stretch")
clicked = map_data.get("last_clicked") if map_data else None

if clicked:
    clicked_point = {
        "label": f"Selected point ({clicked['lat']:.5f}, {clicked['lng']:.5f})",
        "lat": clicked["lat"],
        "lon": clicked["lng"],
    }

    if st.session_state.origin_point is None:
        st.session_state.origin_point = clicked_point
        st.rerun()

    elif st.session_state.destination_point is None:
        st.session_state.destination_point = clicked_point
        st.rerun()

st.markdown("</div>", unsafe_allow_html=True)

if st.session_state.origin_point or st.session_state.destination_point:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.subheader("Selected Points")

    if st.session_state.origin_point:
        st.write(f"**Origin:** {st.session_state.origin_point['label']}")

    if st.session_state.destination_point:
        st.write(f"**Destination:** {st.session_state.destination_point['label']}")

    st.markdown("</div>", unsafe_allow_html=True)

if st.session_state.origin_point and st.session_state.destination_point:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.subheader("Trip Guidance")

    if origin_route:
        st.write(
            f"Nearest line to origin: **{origin_route['route_name']}** "
            f"({origin_route['distance_km']:.2f} km away)"
        )

    if destination_route:
        st.write(
            f"Nearest line to destination: **{destination_route['route_name']}** "
            f"({destination_route['distance_km']:.2f} km away)"
        )

    if origin_route and destination_route:
        if origin_route["route_name"] == destination_route["route_name"]:
            st.success(
                f"Take **{origin_route['route_name']}** from your origin area "
                f"toward your destination."
            )
            st.info(
                "Demo logic: walk to the nearest part of the highlighted line, "
                "take that bus, then walk from the line to your destination."
            )
        else:
            st.warning(
                "Your origin and destination are closest to different lines. "
                "This likely needs a transfer. Transfer logic can be added in the next version."
            )

    st.markdown("</div>", unsafe_allow_html=True)