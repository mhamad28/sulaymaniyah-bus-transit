"""Offline passenger route planner for Suly Transit."""

import base64
import json
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import folium
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

st.set_page_config(page_title="Suly Transit", layout="wide")
st.title("Suly Transit (Offline Planner)")
st.caption("Click once for origin, click again for destination.")

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
ROUTES_FILE = ASSETS_DIR / "bus_lines.geojson"
MAP_IMAGE = ASSETS_DIR / "sulaymaniyah_map.png"

DEFAULT_CENTER = [35.56, 45.43]
DEFAULT_ZOOM = 13
MAX_WALK_KM = 0.70

# Adjust these bounds until the PNG aligns correctly with your route GeoJSON.
# Format: [[south_lat, west_lon], [north_lat, east_lon]]
MAP_BOUNDS = [
    [35.50, 45.35],
    [35.62, 45.52],
]

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


def image_to_data_url(image_path: Path) -> str:
    encoded = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


@st.cache_data
def load_routes() -> dict:
    if not ROUTES_FILE.exists():
        raise FileNotFoundError(f"Missing route file: {ROUTES_FILE}")
    with open(ROUTES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


@st.cache_data
def extract_route_points(routes_geojson: dict) -> pd.DataFrame:
    rows: List[dict] = []

    for feature in routes_geojson.get("features", []):
        route_name = feature.get("properties", {}).get("layer", "Unknown Route")
        geometry = feature.get("geometry", {})
        geom_type = geometry.get("type")
        coords = geometry.get("coordinates", [])

        if geom_type == "LineString":
            line_sets = [coords]
        elif geom_type == "MultiLineString":
            line_sets = coords
        else:
            continue

        for line in line_sets:
            for idx, coord in enumerate(line):
                if not isinstance(coord, (list, tuple)) or len(coord) < 2:
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


def haversine_vectorized_km(
    lat1: float, lon1: float, lats2: np.ndarray, lons2: np.ndarray
) -> np.ndarray:
    r = 6371.0
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lats2_rad = np.radians(lats2)
    lons2_rad = np.radians(lons2)

    dlat = lats2_rad - lat1_rad
    dlon = lons2_rad - lon1_rad
    a = (
        np.sin(dlat / 2) ** 2
        + np.cos(lat1_rad) * np.cos(lats2_rad) * np.sin(dlon / 2) ** 2
    )
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    return r * c


def nearest_route(
    point_lat: float, point_lon: float, route_points_df: pd.DataFrame
) -> Optional[dict]:
    if route_points_df.empty:
        return None

    clean_df = route_points_df.copy()
    clean_df["lat"] = pd.to_numeric(clean_df["lat"], errors="coerce")
    clean_df["lon"] = pd.to_numeric(clean_df["lon"], errors="coerce")
    clean_df = clean_df.dropna(subset=["lat", "lon"])

    if clean_df.empty:
        return None

    lats = clean_df["lat"].to_numpy()
    lons = clean_df["lon"].to_numpy()
    distances = haversine_vectorized_km(point_lat, point_lon, lats, lons)

    if distances.size == 0 or np.isnan(distances).all():
        return None

    idx = int(np.nanargmin(distances))
    row = clean_df.iloc[idx].to_dict()
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
        min_zoom=11,
        max_zoom=16,
        tiles=None,
        control_scale=True,
        zoom_control=True,
        max_bounds=True,
    )

    if MAP_IMAGE.exists():
        folium.raster_layers.ImageOverlay(
            image=image_to_data_url(MAP_IMAGE),
            bounds=MAP_BOUNDS,
            opacity=1.0,
            interactive=False,
            cross_origin=False,
            zindex=1,
        ).add_to(m)
    else:
        st.warning(f"Map image not found: {MAP_IMAGE}")

    for feature in routes_geojson.get("features", []):
        route_name = feature.get("properties", {}).get("layer", "Bus Route")
        color = ROUTE_COLORS.get(route_name, "#3388ff")

        if highlight_routes:
            opacity = 0.95 if route_name in highlight_routes else 0.18
            weight = 6 if route_name in highlight_routes else 2
        else:
            opacity = 0.85
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
            [
                st.session_state.destination_point["lat"],
                st.session_state.destination_point["lon"],
            ],
            tooltip="Destination",
            icon=folium.Icon(color="red"),
        ).add_to(m)

    return m


def compute_trip_result(
    route_points_df: pd.DataFrame,
) -> Tuple[Optional[dict], List[str]]:
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
        return {"error": "Could not find nearby routes."}, []

    if origin_route["distance_km"] > MAX_WALK_KM:
        return {
            "error": (
                f"Origin is too far from any route "
                f"({origin_route['distance_km']:.2f} km)."
            )
        }, []

    if destination_route["distance_km"] > MAX_WALK_KM:
        return {
            "error": (
                f"Destination is too far from any route "
                f"({destination_route['distance_km']:.2f} km)."
            )
        }, []

    result = {
        "origin_route": origin_route,
        "destination_route": destination_route,
    }

    if origin_route["route_name"] == destination_route["route_name"]:
        return result, [origin_route["route_name"]]

    return result, [origin_route["route_name"], destination_route["route_name"]]


def process_click(map_data: Optional[dict]) -> bool:
    if not map_data:
        return False

    changed = False

    if map_data.get("center"):
        center = map_data["center"]
        st.session_state.map_center = [center["lat"], center["lng"]]

    if map_data.get("zoom"):
        st.session_state.map_zoom = map_data["zoom"]

    clicked = map_data.get("last_clicked")
    if not clicked:
        return changed

    click_key = f"{round(clicked['lat'], 6)}_{round(clicked['lng'], 6)}"
    if click_key == st.session_state.last_click_key:
        return changed

    st.session_state.last_click_key = click_key
    point = {"lat": clicked["lat"], "lon": clicked["lng"]}

    if st.session_state.origin_point is None:
        st.session_state.origin_point = point
    elif st.session_state.destination_point is None:
        st.session_state.destination_point = point
    else:
        st.session_state.origin_point = point
        st.session_state.destination_point = None

    changed = True
    return changed


def render_sidebar() -> None:
    st.sidebar.header("Trip Controls")

    if st.sidebar.button("Reset Trip"):
        st.session_state.origin_point = None
        st.session_state.destination_point = None
        st.session_state.last_click_key = None
        st.rerun()

    st.sidebar.markdown("### Map image")
    st.sidebar.caption(str(MAP_IMAGE))

    st.sidebar.markdown("### Bounds")
    st.sidebar.code(str(MAP_BOUNDS))

    if st.session_state.origin_point is None:
        st.sidebar.info("Click the map to set origin.")
    elif st.session_state.destination_point is None:
        st.sidebar.info("Click the map again to set destination.")
    else:
        st.sidebar.success("Trip selected. Click again to start a new trip.")


def render_result(trip_result: Optional[dict]) -> None:
    if not trip_result:
        return

    if "error" in trip_result:
        st.subheader("Route Advice")
        st.error(trip_result["error"])
        return

    origin_route = trip_result["origin_route"]
    destination_route = trip_result["destination_route"]

    st.subheader("Route Advice")
    st.write(
        f"Origin nearest: **{origin_route['route_name']}** "
        f"({origin_route['distance_km']:.2f} km) | "
        f"Destination nearest: **{destination_route['route_name']}** "
        f"({destination_route['distance_km']:.2f} km)"
    )

    if origin_route["route_name"] == destination_route["route_name"]:
        st.success(f"Take this bus line: {origin_route['route_name']}")
    else:
        st.warning(
            f"Take **{origin_route['route_name']}** first, then transfer to "
            f"**{destination_route['route_name']}**."
        )


def render_footer() -> None:
    footer_items = []

    if st.session_state.origin_point:
        footer_items.append(
            "Origin: "
            f"{st.session_state.origin_point['lat']:.5f}, "
            f"{st.session_state.origin_point['lon']:.5f}"
        )

    if st.session_state.destination_point:
        footer_items.append(
            "Destination: "
            f"{st.session_state.destination_point['lat']:.5f}, "
            f"{st.session_state.destination_point['lon']:.5f}"
        )

    if footer_items:
        st.caption(" | ".join(footer_items))


def main() -> None:
    init_state()
    render_sidebar()

    try:
        routes_geojson = load_routes()
    except Exception as e:
        st.error(f"Failed to load route file: {e}")
        return

    route_points_df = extract_route_points(routes_geojson)
    if route_points_df.empty:
        st.error("No route points found in assets/bus_lines.geojson.")
        return

    # Build initial map without highlights first
    map_obj = build_map(routes_geojson, [])

    map_data = st_folium(
        map_obj,
        height=700,
        width=1200,
        returned_objects=["last_clicked", "center", "zoom"],
        key="passenger_map",
    )

    changed = process_click(map_data)
    if changed:
        st.rerun()

    trip_result, highlight_routes = compute_trip_result(route_points_df)

    # Rebuild with highlighted routes once trip is known
    if highlight_routes:
        map_obj_highlighted = build_map(routes_geojson, highlight_routes)
        st_folium(
            map_obj_highlighted,
            height=700,
            width=1200,
            returned_objects=[],
            key="passenger_map_highlighted",
        )

    render_result(trip_result)
    render_footer()


if __name__ == "__main__":
    main()
