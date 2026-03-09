"""Offline passenger route planner for Suly Transit."""

import json
import math
from typing import Dict, List, Optional, Tuple

import folium
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

st.set_page_config(page_title="Suly Transit", layout="wide")
st.title("Suly Transit (Offline Planner)")
st.caption("Select origin and destination on the map to get route advice.")

DEFAULT_CENTER = [35.56, 45.43]
DEFAULT_ZOOM = 13

ROUTE_COLORS: Dict[str, str] = {
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


@st.cache_data
def load_routes() -> dict:
    with open("assets/bus_lines.geojson", "r", encoding="utf-8") as f:
        return json.load(f)


@st.cache_data
def extract_route_points(routes_geojson: dict) -> pd.DataFrame:
    rows: List[dict] = []
    for feature in routes_geojson.get("features", []):
        route_name = feature.get("properties", {}).get("layer", "Unknown Route")
        geometry = feature.get("geometry", {})
        if geometry.get("type") != "LineString":
            continue

        for idx, coord in enumerate(geometry.get("coordinates", [])):
            if len(coord) < 2:
                continue
            lon, lat = coord[0], coord[1]
            rows.append(
                {
                    "route_name": route_name,
                    "point_order": idx,
                    "lat": lat,
                    "lon": lon,
                }
            )

    return pd.DataFrame(rows, columns=["route_name", "point_order", "lat", "lon"])


def haversine_vectorized_km(lat1: float, lon1: float, lats2: np.ndarray, lons2: np.ndarray) -> np.ndarray:
    r = 6371.0
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lats2_rad = np.radians(lats2)
    lons2_rad = np.radians(lons2)

    dlat = lats2_rad - lat1_rad
    dlon = lons2_rad - lon1_rad
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1_rad) * np.cos(lats2_rad) * np.sin(dlon / 2) ** 2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    return r * c


def nearest_route(point_lat: float, point_lon: float, route_points_df: pd.DataFrame) -> Optional[dict]:
    if route_points_df.empty:
        return None

    lats = pd.to_numeric(route_points_df["lat"], errors="coerce").to_numpy()
    lons = pd.to_numeric(route_points_df["lon"], errors="coerce").to_numpy()
    distances = haversine_vectorized_km(point_lat, point_lon, lats, lons)

    if distances.size == 0 or np.isnan(distances).all():
        return None

    idx = int(np.nanargmin(distances))
    row = route_points_df.iloc[idx].to_dict()
    row["distance_km"] = float(distances[idx])
    return row


def init_state() -> None:
    st.session_state.setdefault("origin_point", None)
    st.session_state.setdefault("destination_point", None)
    st.session_state.setdefault("last_click_key", None)
    st.session_state.setdefault("map_center", DEFAULT_CENTER)
    st.session_state.setdefault("map_zoom", DEFAULT_ZOOM)


def build_map(routes_geojson: dict, highlight_routes: List[str]) -> folium.Map:
    m = folium.Map(
        location=st.session_state.map_center,
        zoom_start=st.session_state.map_zoom,
        tiles="CartoDB positron",
        control_scale=True,
        zoom_control=True,
    )

    for feature in routes_geojson.get("features", []):
        route_name = feature.get("properties", {}).get("layer", "Bus Route")
        color = ROUTE_COLORS.get(route_name, "#3388ff")

        if highlight_routes:
            opacity = 0.95 if route_name in highlight_routes else 0.15
            weight = 6 if route_name in highlight_routes else 2
        else:
            opacity = 0.8
            weight = 3

        folium.GeoJson(
            feature,
            tooltip=route_name,
            style_function=lambda _, color=color, weight=weight, opacity=opacity: {
                "color": color,
                "weight": weight,
                "opacity": opacity,
            },
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

    return m


def compute_trip_result(route_points_df: pd.DataFrame) -> Tuple[Optional[dict], List[str]]:
    if not st.session_state.origin_point or not st.session_state.destination_point:
        return None, []

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

    if not origin_route or not destination_route:
        return None, []

    result = {"origin_route": origin_route, "destination_route": destination_route}
    if origin_route["route_name"] == destination_route["route_name"]:
        return result, [origin_route["route_name"]]
    return result, [origin_route["route_name"], destination_route["route_name"]]


def process_click(map_data: Optional[dict]) -> None:
    if not map_data:
        return

    if map_data.get("center"):
        st.session_state.map_center = [map_data["center"]["lat"], map_data["center"]["lng"]]
    if map_data.get("zoom"):
        st.session_state.map_zoom = map_data["zoom"]

    clicked = map_data.get("last_clicked")
    if not clicked:
        return

    click_key = f"{round(clicked['lat'], 6)}_{round(clicked['lng'], 6)}"
    if click_key == st.session_state.last_click_key:
        return

    st.session_state.last_click_key = click_key
    point = {"lat": clicked["lat"], "lon": clicked["lng"]}

    if st.session_state.origin_point is None:
        st.session_state.origin_point = point
    elif st.session_state.destination_point is None:
        st.session_state.destination_point = point
    else:
        st.session_state.origin_point = point
        st.session_state.destination_point = None

    st.rerun()


def render_sidebar() -> None:
    st.sidebar.header("Trip Controls")
    if st.sidebar.button("Reset Trip"):
        st.session_state.origin_point = None
        st.session_state.destination_point = None
        st.session_state.last_click_key = None
        st.rerun()

    if st.session_state.origin_point is None:
        st.sidebar.info("Click map to set origin.")
    elif st.session_state.destination_point is None:
        st.sidebar.info("Click map again to set destination.")
    else:
        st.sidebar.success("Trip selected. Click map again to start a new trip.")


def render_result(trip_result: Optional[dict]) -> None:
    if not trip_result:
        return

    origin_route = trip_result["origin_route"]
    destination_route = trip_result["destination_route"]

    st.subheader("Route Advice")
    st.write(
        f"Origin nearest: **{origin_route['route_name']}** | "
        f"Destination nearest: **{destination_route['route_name']}**"
    )

    if origin_route["route_name"] == destination_route["route_name"]:
        st.success(f"Take this bus line: {origin_route['route_name']}")
    else:
        st.warning(
            f"Take **{origin_route['route_name']}** first, then transfer to "
            f"**{destination_route['route_name']}**."
        )


def main() -> None:
    init_state()
    render_sidebar()

    routes_geojson = load_routes()
    route_points_df = extract_route_points(routes_geojson)
    if route_points_df.empty:
        st.error("No route points found in assets/bus_lines.geojson.")
        return

    trip_result, highlight_routes = compute_trip_result(route_points_df)
    map_obj = build_map(routes_geojson, highlight_routes)

    map_data = st_folium(
        map_obj,
        height=700,
        width="100%",
        returned_objects=["last_clicked", "center", "zoom"],
        key="passenger_map",
    )

    process_click(map_data)
    render_result(trip_result)

    footer_items = []
    if st.session_state.origin_point:
        footer_items.append(
            f"Origin: {st.session_state.origin_point['lat']:.5f}, {st.session_state.origin_point['lon']:.5f}"
        )
    if st.session_state.destination_point:
        footer_items.append(
            f"Destination: {st.session_state.destination_point['lat']:.5f}, {st.session_state.destination_point['lon']:.5f}"
        )
    if footer_items:
        st.caption(" | ".join(footer_items))


if __name__ == "__main__":
    main()
