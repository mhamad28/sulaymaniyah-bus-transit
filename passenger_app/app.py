import json
     2	import math
     3	from typing import Dict, List, Optional, Tuple
     4	
     5	import folium
     6	import numpy as np
     7	import pandas as pd
     8	import streamlit as st
     9	from streamlit_folium import st_folium
    10	
    11	st.set_page_config(page_title="Suly Transit", layout="wide")
    12	st.title("Suly Transit (Offline Planner)")
    13	st.caption("Select origin and destination on the map to get route advice.")
    14	
    15	DEFAULT_CENTER = [35.56, 45.43]
    16	DEFAULT_ZOOM = 13
    17	
    18	ROUTE_COLORS: Dict[str, str] = {
    19	    "Bakrajo_Bazar": "#e41a1c",
    20	    "Chwarchra_Bazar": "#377eb8",
    21	    "FarmanBaran_Bazar": "#4daf4a",
    22	    "HawaryShar_Bazar": "#984ea3",
    23	    "Kazywa_Bazar": "#ff7f00",
    24	    "Kshtukal_Bazar": "#a65628",
    25	    "Qrgra_Bazar": "#f781bf",
    26	    "Raparin_Bazar": "#999999",
    27	    "Rzgary Bazar": "#66c2a5",
    28	    "Shakraka_Bazar": "#fc8d62",
    29	    "TwiMalik_Bazar": "#8da0cb",
    30	    "Xabat_Bazar": "#ffd92f",
    31	    "ZargatayTaza_Bazar": "#1b9e77",
    32	}
    33	
    34	
    35	@st.cache_data
    36	def load_routes() -> dict:
    37	    with open("assets/bus_lines.geojson", "r", encoding="utf-8") as f:
    38	        return json.load(f)
    39	
    40	
    41	@st.cache_data
    42	def extract_route_points(routes_geojson: dict) -> pd.DataFrame:
    43	    rows: List[dict] = []
    44	    for feature in routes_geojson.get("features", []):
    45	        route_name = feature.get("properties", {}).get("layer", "Unknown Route")
    46	        geometry = feature.get("geometry", {})
    47	        if geometry.get("type") != "LineString":
    48	            continue
    49	
    50	        for idx, coord in enumerate(geometry.get("coordinates", [])):
    51	            if len(coord) < 2:
    52	                continue
    53	            lon, lat = coord[0], coord[1]
    54	            rows.append(
    55	                {
    56	                    "route_name": route_name,
    57	                    "point_order": idx,
    58	                    "lat": lat,
    59	                    "lon": lon,
    60	                }
    61	            )
    62	
    63	    return pd.DataFrame(rows, columns=["route_name", "point_order", "lat", "lon"])
    64	
    65	
    66	def haversine_vectorized_km(lat1: float, lon1: float, lats2: np.ndarray, lons2: np.ndarray) -> np.ndarray:
    67	    r = 6371.0
    68	    lat1_rad = math.radians(lat1)
    69	    lon1_rad = math.radians(lon1)
    70	    lats2_rad = np.radians(lats2)
    71	    lons2_rad = np.radians(lons2)
    72	
    73	    dlat = lats2_rad - lat1_rad
    74	    dlon = lons2_rad - lon1_rad
    75	    a = np.sin(dlat / 2) ** 2 + np.cos(lat1_rad) * np.cos(lats2_rad) * np.sin(dlon / 2) ** 2
    76	    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    77	    return r * c
    78	
    79	
    80	def nearest_route(point_lat: float, point_lon: float, route_points_df: pd.DataFrame) -> Optional[dict]:
    81	    if route_points_df.empty:
    82	        return None
    83	
    84	    lats = pd.to_numeric(route_points_df["lat"], errors="coerce").to_numpy()
    85	    lons = pd.to_numeric(route_points_df["lon"], errors="coerce").to_numpy()
    86	    distances = haversine_vectorized_km(point_lat, point_lon, lats, lons)
    87	
    88	    if distances.size == 0 or np.isnan(distances).all():
    89	        return None
    90	
    91	    idx = int(np.nanargmin(distances))
    92	    row = route_points_df.iloc[idx].to_dict()
    93	    row["distance_km"] = float(distances[idx])
    94	    return row
    95	
    96	
    97	def init_state() -> None:
    98	    st.session_state.setdefault("origin_point", None)
    99	    st.session_state.setdefault("destination_point", None)
   100	    st.session_state.setdefault("last_click_key", None)
   101	    st.session_state.setdefault("map_center", DEFAULT_CENTER)
   102	    st.session_state.setdefault("map_zoom", DEFAULT_ZOOM)
   103	
   104	
   105	def build_map(routes_geojson: dict, highlight_routes: List[str]) -> folium.Map:
   106	    m = folium.Map(
   107	        location=st.session_state.map_center,
   108	        zoom_start=st.session_state.map_zoom,
   109	        tiles="CartoDB positron",
   110	        control_scale=True,
   111	        zoom_control=True,
   112	    )
   113	
   114	    for feature in routes_geojson.get("features", []):
   115	        route_name = feature.get("properties", {}).get("layer", "Bus Route")
   116	        color = ROUTE_COLORS.get(route_name, "#3388ff")
   117	
   118	        if highlight_routes:
   119	            opacity = 0.95 if route_name in highlight_routes else 0.15
   120	            weight = 6 if route_name in highlight_routes else 2
   121	        else:
   122	            opacity = 0.8
   123	            weight = 3
   124	
   125	        folium.GeoJson(
   126	            feature,
   127	            tooltip=route_name,
   128	            style_function=lambda _, color=color, weight=weight, opacity=opacity: {
   129	                "color": color,
   130	                "weight": weight,
   131	                "opacity": opacity,
   132	            },
   133	        ).add_to(m)
   134	
   135	    if st.session_state.origin_point:
   136	        folium.Marker(
   137	            [st.session_state.origin_point["lat"], st.session_state.origin_point["lon"]],
   138	            tooltip="Origin",
   139	            icon=folium.Icon(color="green"),
   140	        ).add_to(m)
   141	
   142	    if st.session_state.destination_point:
   143	        folium.Marker(
   144	            [st.session_state.destination_point["lat"], st.session_state.destination_point["lon"]],
   145	            tooltip="Destination",
   146	            icon=folium.Icon(color="red"),
   147	        ).add_to(m)
   148	
   149	    return m
   150	
   151	
   152	def compute_trip_result(route_points_df: pd.DataFrame) -> Tuple[Optional[dict], List[str]]:
   153	    if not st.session_state.origin_point or not st.session_state.destination_point:
   154	        return None, []
   155	
   156	    origin_route = nearest_route(
   157	        st.session_state.origin_point["lat"],
   158	        st.session_state.origin_point["lon"],
   159	        route_points_df,
   160	    )
   161	    destination_route = nearest_route(
   162	        st.session_state.destination_point["lat"],
   163	        st.session_state.destination_point["lon"],
   164	        route_points_df,
   165	    )
   166	
   167	    if not origin_route or not destination_route:
   168	        return None, []
   169	
   170	    result = {"origin_route": origin_route, "destination_route": destination_route}
   171	    if origin_route["route_name"] == destination_route["route_name"]:
   172	        return result, [origin_route["route_name"]]
   173	    return result, [origin_route["route_name"], destination_route["route_name"]]
   174	
   175	
   176	def process_click(map_data: Optional[dict]) -> None:
   177	    if not map_data:
   178	        return
   179	
   180	    if map_data.get("center"):
   181	        st.session_state.map_center = [map_data["center"]["lat"], map_data["center"]["lng"]]
   182	    if map_data.get("zoom"):
   183	        st.session_state.map_zoom = map_data["zoom"]
   184	
   185	    clicked = map_data.get("last_clicked")
   186	    if not clicked:
   187	        return
   188	
   189	    click_key = f"{round(clicked['lat'], 6)}_{round(clicked['lng'], 6)}"
   190	    if click_key == st.session_state.last_click_key:
   191	        return
   192	
   193	    st.session_state.last_click_key = click_key
   194	    point = {"lat": clicked["lat"], "lon": clicked["lng"]}
   195	
   196	    if st.session_state.origin_point is None:
   197	        st.session_state.origin_point = point
   198	    elif st.session_state.destination_point is None:
   199	        st.session_state.destination_point = point
   200	    else:
   201	        st.session_state.origin_point = point
   202	        st.session_state.destination_point = None
   203	
   204	    st.rerun()
   205	
   206	
   207	def render_sidebar() -> None:
   208	    st.sidebar.header("Trip Controls")
   209	    if st.sidebar.button("Reset Trip"):
   210	        st.session_state.origin_point = None
   211	        st.session_state.destination_point = None
   212	        st.session_state.last_click_key = None
   213	        st.rerun()
   214	
   215	    if st.session_state.origin_point is None:
   216	        st.sidebar.info("Click map to set origin.")
   217	    elif st.session_state.destination_point is None:
   218	        st.sidebar.info("Click map again to set destination.")
   219	    else:
   220	        st.sidebar.success("Trip selected. Click map again to start a new trip.")
   221	
   222	
   223	def render_result(trip_result: Optional[dict]) -> None:
   224	    if not trip_result:
   225	        return
   226	
   227	    origin_route = trip_result["origin_route"]
   228	    destination_route = trip_result["destination_route"]
   229	
   230	    st.subheader("Route Advice")
   231	    st.write(
   232	        f"Origin nearest: **{origin_route['route_name']}** | "
   233	        f"Destination nearest: **{destination_route['route_name']}**"
   234	    )
   235	
   236	    if origin_route["route_name"] == destination_route["route_name"]:
   237	        st.success(f"Take this bus line: {origin_route['route_name']}")
   238	    else:
   239	        st.warning(
   240	            f"Take **{origin_route['route_name']}** first, then transfer to "
   241	            f"**{destination_route['route_name']}**."
   242	        )
   243	
   244	
   245	def main() -> None:
   246	    init_state()
   247	    render_sidebar()
   248	
   249	    routes_geojson = load_routes()
   250	    route_points_df = extract_route_points(routes_geojson)
   251	    if route_points_df.empty:
   252	        st.error("No route points found in assets/bus_lines.geojson.")
   253	        return
   254	
   255	    trip_result, highlight_routes = compute_trip_result(route_points_df)
   256	    map_obj = build_map(routes_geojson, highlight_routes)
   257	
   258	    map_data = st_folium(
   259	        map_obj,
   260	        height=700,
   261	        width="100%",
   262	        returned_objects=["last_clicked", "center", "zoom"],
   263	        key="passenger_map",
   264	    )
   265	
   266	    process_click(map_data)
   267	    render_result(trip_result)
   268	
   269	    footer_items = []
   270	    if st.session_state.origin_point:
   271	        footer_items.append(
   272	            f"Origin: {st.session_state.origin_point['lat']:.5f}, {st.session_state.origin_point['lon']:.5f}"
   273	        )
   274	    if st.session_state.destination_point:
   275	        footer_items.append(
   276	            f"Destination: {st.session_state.destination_point['lat']:.5f}, {st.session_state.destination_point['lon']:.5f}"
   277	        )
   278	    if footer_items:
   279	        st.caption(" | ".join(footer_items))
   280	
   281	
   282	if __name__ == "__main__":
   283	    main()
Summary
