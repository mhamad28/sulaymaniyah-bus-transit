"""Suly Transit – Offline Passenger Route Planner.

Uses a pure Leaflet.js map embedded via st.components.v1.html so that
zoom / pan never triggers a Streamlit re-render and never goes black.
"""

import json
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Suly Transit", layout="wide")

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
ROUTES_FILE = ASSETS_DIR / "bus_lines.geojson"

DEFAULT_CENTER = [35.56, 45.43]
DEFAULT_ZOOM = 13
MAX_WALK_KM = 0.70

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


# ── Data loading ──────────────────────────────────────────────────────────────

@st.cache_data(hash_funcs={Path: lambda p: p.stat().st_mtime if p.exists() else 0})
def load_routes(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing route file: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@st.cache_data
def extract_route_points(routes_geojson: dict) -> pd.DataFrame:
    rows: List[dict] = []
    for feature in routes_geojson.get("features", []):
        route_name = feature.get("properties", {}).get("layer", "Unknown Route")
        geometry = feature.get("geometry", {})
        geom_type = geometry.get("type")
        coords = geometry.get("coordinates", [])
        line_sets = [coords] if geom_type == "LineString" else (
            coords if geom_type == "MultiLineString" else []
        )
        for line in line_sets:
            for idx, coord in enumerate(line):
                if isinstance(coord, (list, tuple)) and len(coord) >= 2:
                    rows.append({"route_name": route_name, "point_order": idx,
                                 "lat": coord[1], "lon": coord[0]})
    return pd.DataFrame(rows, columns=["route_name", "point_order", "lat", "lon"])


# ── Routing logic ─────────────────────────────────────────────────────────────

def haversine_km(lat1: float, lon1: float,
                 lats2: np.ndarray, lons2: np.ndarray) -> np.ndarray:
    r = 6371.0
    rl1, rn1 = math.radians(lat1), math.radians(lon1)
    rl2, rn2 = np.radians(lats2), np.radians(lons2)
    dl, dn = rl2 - rl1, rn2 - rn1
    a = np.sin(dl / 2) ** 2 + np.cos(rl1) * np.cos(rl2) * np.sin(dn / 2) ** 2
    return r * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


def nearest_route(lat: float, lon: float,
                  df: pd.DataFrame) -> Optional[dict]:
    clean = df.dropna(subset=["lat", "lon"])
    if clean.empty:
        return None
    dists = haversine_km(lat, lon, clean["lat"].to_numpy(), clean["lon"].to_numpy())
    if dists.size == 0 or np.isnan(dists).all():
        return None
    idx = int(np.nanargmin(dists))
    row = clean.iloc[idx].to_dict()
    row["distance_km"] = float(dists[idx])
    return row


def compute_trip(df: pd.DataFrame) -> Tuple[Optional[dict], List[str]]:
    o, d = st.session_state.get("origin"), st.session_state.get("destination")
    if not o or not d:
        return None, []

    or_ = nearest_route(o["lat"], o["lon"], df)
    dr_ = nearest_route(d["lat"], d["lon"], df)

    if not or_ or not dr_:
        return {"error": "Could not find nearby routes."}, []
    if or_["distance_km"] > MAX_WALK_KM:
        return {"error": f"Origin too far from any route ({or_['distance_km']:.2f} km)."}, []
    if dr_["distance_km"] > MAX_WALK_KM:
        return {"error": f"Destination too far from any route ({dr_['distance_km']:.2f} km)."}, []

    result = {"origin_route": or_, "destination_route": dr_}
    if or_["route_name"] == dr_["route_name"]:
        return result, [or_["route_name"]]
    return result, [or_["route_name"], dr_["route_name"]]


# ── Leaflet map HTML ──────────────────────────────────────────────────────────

def build_leaflet_html(routes_geojson: dict,
                       highlight: List[str],
                       origin: Optional[dict],
                       destination: Optional[dict]) -> str:
    geojson_str = json.dumps(routes_geojson)
    colors_str = json.dumps(ROUTE_COLORS)
    highlight_str = json.dumps(highlight)
    origin_str = json.dumps(origin)
    dest_str = json.dumps(destination)
    center_lat, center_lon = DEFAULT_CENTER
    zoom = DEFAULT_ZOOM

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body, #map {{ width:100%; height:100%; }}
</style>
</head>
<body>
<div id="map"></div>
<script>
const COLORS   = {colors_str};
const HIGHLIGHT = new Set({highlight_str});
const geojson  = {geojson_str};
const origin   = {origin_str};
const dest     = {dest_str};

// ── Map init ──────────────────────────────────────────────────────────────
const map = L.map('map', {{
  center: [{center_lat}, {center_lon}],
  zoom: {zoom},
  minZoom: 11,
  maxZoom: 19,
  zoomSnap: 0.5,
}});

L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
  attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  maxZoom: 19,
}}).addTo(map);

// ── Routes ────────────────────────────────────────────────────────────────
L.geoJSON(geojson, {{
  style: function(feature) {{
    const name  = (feature.properties && feature.properties.layer) || '';
    const color = COLORS[name] || '#3388ff';
    if (HIGHLIGHT.size > 0) {{
      const active = HIGHLIGHT.has(name);
      return {{ color, weight: active ? 6 : 2, opacity: active ? 0.95 : 0.18 }};
    }}
    return {{ color, weight: 4, opacity: 0.9 }};
  }},
  onEachFeature: function(feature, layer) {{
    const name = (feature.properties && feature.properties.layer) || 'Route';
    layer.bindTooltip(name, {{sticky: true}});
  }}
}}).addTo(map);

// ── Markers ───────────────────────────────────────────────────────────────
function makeIcon(color) {{
  // Simple colored circle marker
  return L.divIcon({{
    html: `<div style="
      width:16px; height:16px; border-radius:50%;
      background:${{color}}; border:3px solid #fff;
      box-shadow:0 0 4px rgba(0,0,0,.5)"></div>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
    className: ''
  }});
}}

if (origin) {{
  L.marker([origin.lat, origin.lon], {{icon: makeIcon('#22c55e')}})
   .bindTooltip('Origin').addTo(map);
}}
if (dest) {{
  L.marker([dest.lat, dest.lon], {{icon: makeIcon('#ef4444')}})
   .bindTooltip('Destination').addTo(map);
}}

// ── Click → send to Streamlit ─────────────────────────────────────────────
map.on('click', function(e) {{
  const msg = {{ lat: e.latlng.lat, lon: e.latlng.lng }};
  window.parent.postMessage({{ type: 'map_click', payload: msg }}, '*');
}});
</script>
</body>
</html>"""


# ── Session state ─────────────────────────────────────────────────────────────

def init_state() -> None:
    st.session_state.setdefault("origin", None)
    st.session_state.setdefault("destination", None)
    st.session_state.setdefault("last_click", None)
    st.session_state.setdefault("highlight_routes", [])


# ── Sidebar ───────────────────────────────────────────────────────────────────

def render_sidebar() -> None:
    st.sidebar.title("🚌 Suly Transit")
    st.sidebar.caption("Offline Route Planner – Sulaymaniyah")

    if st.sidebar.button("🔄 Reset Trip"):
        st.session_state.origin = None
        st.session_state.destination = None
        st.session_state.last_click = None
        st.session_state.highlight_routes = []
        st.rerun()

    st.sidebar.markdown("---")
    if st.session_state.origin is None:
        st.sidebar.info("📍 Click the map to set **origin**.")
    elif st.session_state.destination is None:
        st.sidebar.info("📍 Click the map to set **destination**.")
    else:
        st.sidebar.success("✅ Trip selected.\nClick again to reset.")

    st.sidebar.markdown("---")
    st.sidebar.markdown("### Bus Lines")
    for route, color in ROUTE_COLORS.items():
        label = route.replace("_", " ")
        st.sidebar.markdown(
            f'<span style="color:{color};font-size:20px;">●</span> {label}',
            unsafe_allow_html=True,
        )


# ── Result panel ──────────────────────────────────────────────────────────────

def render_result(trip_result: Optional[dict]) -> None:
    if not trip_result:
        st.info("Click an origin and destination on the map to get route advice.")
        return
    if "error" in trip_result:
        st.error(trip_result["error"])
        return

    o = trip_result["origin_route"]
    d = trip_result["destination_route"]
    c1, c2 = st.columns(2)
    c1.metric("Origin route", o["route_name"], f"{o['distance_km']:.0f} m walk")
    c2.metric("Destination route", d["route_name"], f"{d['distance_km']:.0f} m walk")

    if o["route_name"] == d["route_name"]:
        st.success(f"✅ Take **{o['route_name']}** — no transfer needed.")
    else:
        st.warning(
            f"🔁 Board **{o['route_name']}**, then transfer to **{d['route_name']}**."
        )


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    init_state()
    render_sidebar()

    try:
        routes_geojson = load_routes(ROUTES_FILE)
    except Exception as e:
        st.error(f"Failed to load route file: {e}")
        return

    route_points_df = extract_route_points(routes_geojson)
    if route_points_df.empty:
        st.error("No route points found in assets/bus_lines.geojson.")
        return

    trip_result, highlight_routes = compute_trip(route_points_df)
    if highlight_routes != st.session_state.highlight_routes:
        st.session_state.highlight_routes = highlight_routes
        st.rerun()

    # ── Render Leaflet map (never re-renders on Streamlit rerun) ──────────────
    html = build_leaflet_html(
        routes_geojson,
        st.session_state.highlight_routes,
        st.session_state.origin,
        st.session_state.destination,
    )
    components.html(html, height=620, scrolling=False)

    # ── Receive click events from the map via postMessage ─────────────────────
    # We use a tiny JS snippet to relay postMessage events to a Streamlit
    # text_input (hidden via CSS), then read it back in Python.
    click_receiver = """
    <script>
    window.addEventListener('message', function(e) {
        if (e.data && e.data.type === 'map_click') {
            const v = e.data.payload.lat.toFixed(6) + '_' + e.data.payload.lon.toFixed(6);
            const el = window.parent.document.querySelector('input[data-testid="stTextInput"] input');
            if (el) { el.value = v; el.dispatchEvent(new Event('input', {bubbles:true})); }
        }
    });
    </script>
    """
    components.html(click_receiver, height=0)

    click_val = st.text_input("click_relay", key="click_relay",
                               label_visibility="collapsed")

    if click_val and click_val != st.session_state.last_click:
        st.session_state.last_click = click_val
        try:
            lat_s, lon_s = click_val.split("_")
            point = {"lat": float(lat_s), "lon": float(lon_s)}
            if st.session_state.origin is None:
                st.session_state.origin = point
            elif st.session_state.destination is None:
                st.session_state.destination = point
            else:
                st.session_state.origin = point
                st.session_state.destination = None
            st.rerun()
        except ValueError:
            pass

    render_result(trip_result)


if __name__ == "__main__":
    main()
