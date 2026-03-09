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
            rgba(10, 15, 30, 0.25),
            rgba(10, 15, 30, 0.35)
        ), url("data:image/jpg;base64,{encoded}");
        background-size: cover;
        background-position: center;
        background-attachment: fixed;
    }}

    [data-testid="stHeader"] {{
        background: rgba(0, 0, 0, 0);
    }}

    .block-container {{
        padding-top: 0.5rem;
        padding-bottom: 0.5rem;
        padding-left: 0.5rem;
        padding-right: 0.5rem;
        max-width: 100%;
    }}

    /* Make the map feel dominant */
    .map-shell {{
        position: relative;
        width: 100%;
    }}

    /* Floating cards */
    .floating-card {{
        background: rgba(10, 20, 35, 0.78);
        border: 1px solid rgba(255,255,255,0.10);
        backdrop-filter: blur(10px);
        padding: 1rem 1rem;
        border-radius: 16px;
        color: white;
        box-shadow: 0 8px 24px rgba(0,0,0,0.25);
    }}

    /* Small visual improvement for metric text */
    .small-note {{
        font-size: 0.95rem;
        opacity: 0.95;
        line-height: 1.45;
    }}

    /* Hide default extra spacing in some places */
    div[data-testid="stVerticalBlock"] > div:empty {{
        display: none;
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
    map_style="OpenStreetMap",
):
    m = folium.Map(
        location=[35.56, 45.43],
        zoom_start=12,
        tiles=map_style,
        control_scale=True,
    )

    if show_all_lines:
        all_routes_layer = folium.FeatureGroup(name="All Bus Lines", show=True)

        for feature in routes_geojson["features"]:
            route_name = feature["properties"].get("layer", "Bus Route")
            color = ROUTE_COLORS.get(route_name, "#00bfff")

            opacity = 0.35 if highlight_route and route_name != highlight_route else 0.80
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
# LOAD DATA
# --------------------------------------------------
routes_geojson = load_routes_geojson("assets/bus_lines.geojson")


# --------------------------------------------------
# LOGIC
# --------------------------------------------------
origin_route = None
destination_route = None
highlight_route = None

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


# --------------------------------------------------
# TOP FLOATING LAYOUT
# --------------------------------------------------
top_left, top_center, top_right = st.columns([1.3, 3.2, 1.7], gap="small")

with top_left:
    st.markdown('<div class="floating-card">', unsafe_allow_html=True)
    st.markdown("## Suly Transit")
    st.markdown(
        '<div class="small-note">Click once on the map for your <b>origin</b>. '
        'Click a second time for your <b>destination</b>.</div>',
        unsafe_allow_html=True,
    )

    if st.button("🔄 Reset points", width="stretch"):
        st.session_state.origin_point = None
        st.session_state.destination_point = None
        st.rerun()

    show_all_lines = st.checkbox("Show all bus lines", value=True)

    map_style = st.selectbox(
        "Map style",
        ["OpenStreetMap", "CartoDB positron", "CartoDB dark_matter"],
        index=0,
    )

    st.markdown("</div>", unsafe_allow_html=True)

with top_center:
    st.markdown('<div class="floating-card">', unsafe_allow_html=True)
    st.markdown("### City Bus Network")
    st.markdown(
        '<div class="small-note">This is a static passenger map. '
        'It shows how the bus lines work in the city without live tracking.</div>',
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

with top_right:
    st.markdown('<div class="floating-card">', unsafe_allow_html=True)
    st.markdown("### Selected Points")

    if st.session_state.origin_point:
        st.success(f"Origin set")
        st.caption(st.session_state.origin_point["label"])
    else:
        st.info("Origin not selected")

    if st.session_state.destination_point:
        st.success("Destination set")
        st.caption(st.session_state.destination_point["label"])
    else:
        st.info("Destination not selected")

    st.markdown("</div>", unsafe_allow_html=True)


# --------------------------------------------------
# MAP
# --------------------------------------------------
passenger_map = build_passenger_map(
    routes_geojson=routes_geojson,
    origin_point=st.session_state.origin_point,
    destination_point=st.session_state.destination_point,
    highlight_route=highlight_route,
    show_all_lines=show_all_lines,
    map_style=map_style,
)

st.markdown('<div class="map-shell">', unsafe_allow_html=True)
map_data = st_folium(passenger_map, height=720, width="stretch")
st.markdown("</div>", unsafe_allow_html=True)

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


# --------------------------------------------------
# BOTTOM FLOATING RESULT AREA
# --------------------------------------------------
bottom_left, bottom_right = st.columns([2.4, 1.6], gap="small")

with bottom_left:
    st.markdown('<div class="floating-card">', unsafe_allow_html=True)
    st.markdown("### Trip Guidance")

    if st.session_state.origin_point and st.session_state.destination_point:
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
                    f"Take **{origin_route['route_name']}** from your origin area toward your destination."
                )
                st.info(
                    "Demo logic: walk to the nearest part of the highlighted line, "
                    "ride that line, then walk to your destination."
                )
            else:
                st.warning(
                    "Your origin and destination are closest to different lines. "
                    "This likely needs a transfer. Transfer logic can be added later."
                )
    else:
        st.info("Choose two points on the map to get trip guidance.")

    st.markdown("</div>", unsafe_allow_html=True)

with bottom_right:
    st.markdown('<div class="floating-card">', unsafe_allow_html=True)
    st.markdown("### How to use")

    st.markdown(
        """
1. Open the map  
2. Click your start point  
3. Click your destination  
4. Read the suggested bus line  
        """
    )

    st.markdown("</div>", unsafe_allow_html=True)