import streamlit as st
from supabase import create_client, Client
import pandas as pd
import json
import streamlit.components.v1 as components
from datetime import datetime

# =========================================================
# 1. CONFIG & SUPABASE
# =========================================================
st.set_page_config(page_title="Suly Transit – Manager", layout="wide")

URL = st.secrets["SUPABASE_URL"]
KEY = st.secrets["SUPABASE_ANON_KEY"]
supabase: Client = create_client(URL, KEY)

st.markdown("""
<style>
    header {display: none !important;}
    footer {display: none !important;}
    .block-container {padding-top: 2rem !important;}
</style>
""", unsafe_allow_html=True)

# =========================================================
# 2. DATA FUNCTIONS
# =========================================================
def get_fleet_data():
    try:
        res = supabase.table("live_bus_data").select("*").execute()
        return res.data or []
    except:
        return []

def get_history_stats(plate):
    try:
        res = supabase.table("bus_location_history") \
            .select("recorded_at") \
            .eq("plate_number", str(plate)) \
            .order("recorded_at", desc=False) \
            .execute()
        return res.data or []
    except:
        return []

# =========================================================
# 3. LIVE MAP HTML
# Map updates inside JavaScript itself every 10s
# so Streamlit does NOT redraw the whole map.
# =========================================================
def build_map_html(supabase_url, supabase_key):
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8"/>
        <meta name="viewport" content="width=device-width,initial-scale=1"/>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
        <style>
            html, body {{
                margin: 0;
                padding: 0;
                background: #0e1117;
                font-family: system-ui, sans-serif;
            }}
            #map {{
                height: 560px;
                width: 100%;
                border-radius: 16px;
                border: 2px solid #333;
            }}
            .leaflet-control-zoom {{
                border: none !important;
            }}
            .leaflet-control-zoom a {{
                background: rgba(15,23,42,.92) !important;
                color: #e5e7eb !important;
                border: 1px solid rgba(255,255,255,.10) !important;
            }}
            .map-badge {{
                position: absolute;
                top: 12px;
                right: 12px;
                z-index: 1000;
                background: rgba(15,23,42,.92);
                color: #86efac;
                border: 1px solid rgba(34,197,94,.35);
                border-radius: 999px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: 600;
                backdrop-filter: blur(8px);
                box-shadow: 0 4px 16px rgba(0,0,0,.35);
            }}
            .map-btn {{
                position: absolute;
                z-index: 1000;
                background: rgba(15,23,42,.92);
                color: #e5e7eb;
                border: 1px solid rgba(255,255,255,.12);
                border-radius: 12px;
                padding: 8px 12px;
                font-size: 12px;
                font-weight: 600;
                cursor: pointer;
                box-shadow: 0 4px 16px rgba(0,0,0,.35);
            }}
            #fit-btn {{
                top: 12px;
                left: 56px;
            }}
        </style>
    </head>
    <body>
        <div id="map"></div>
        <button id="fit-btn" class="map-btn" onclick="fitToFleet()">Fit Fleet</button>
        <div class="map-badge" id="status-badge">Live map</div>

        <script>
            const SUPA_URL = "{supabase_url}";
            const SUPA_KEY = "{supabase_key}";
            const REFRESH_MS = 10000;
            const DEFAULT_CENTER = [35.56, 45.43];
            const DEFAULT_ZOOM = 12;

            const {{ createClient }} = supabase;
            const sb = createClient(SUPA_URL, SUPA_KEY, {{
                auth: {{ persistSession: false }}
            }});

            const map = L.map('map', {{
                center: DEFAULT_CENTER,
                zoom: DEFAULT_ZOOM
            }});

            L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                attribution: '© OpenStreetMap',
                maxZoom: 19
            }}).addTo(map);

            const busMarkers = {{}};
            const busTrails = {{}};
            let firstFitDone = false;

            function badge(text, ok=true) {{
                const el = document.getElementById('status-badge');
                el.textContent = text;
                el.style.color = ok ? '#86efac' : '#fca5a5';
                el.style.borderColor = ok ? 'rgba(34,197,94,.35)' : 'rgba(239,68,68,.35)';
            }}

            function busColor(lineId) {{
                const colors = {{
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
                    "ZargatayTaza_Bazar": "#1b9e77"
                }};
                return colors[lineId] || "#00E5FF";
            }}

            function fitToFleet() {{
                const layers = Object.values(busMarkers);
                if (!layers.length) return;
                const group = new L.featureGroup(layers);
                map.fitBounds(group.getBounds().pad(0.2));
            }}

            async function fetchFleet() {{
                const result = await sb
                    .from('live_bus_data')
                    .select('*');

                if (result.error) throw result.error;
                return result.data || [];
            }}

            async function fetchBusPath(plate) {{
                const result = await sb
                    .from('bus_location_history')
                    .select('lat, lon, recorded_at')
                    .eq('plate_number', String(plate))
                    .order('recorded_at', {{ ascending: false }})
                    .limit(300);

                if (result.error) throw result.error;

                const rows = result.data || [];
                rows.reverse();

                return rows
                    .filter(r => r.lat !== null && r.lon !== null)
                    .map(r => [r.lat, r.lon]);
            }}

            async function renderMapData() {{
                try {{
                    badge('Updating...', true);

                    const fleet = await fetchFleet();
                    const activePlates = new Set();

                    for (const bus of fleet) {{
                        const plate = String(bus.plate_number);
                        activePlates.add(plate);

                        const color = busColor(bus.line_id);

                        // update / create live marker
                        if (busMarkers[plate]) {{
                            busMarkers[plate].setLatLng([bus.lat, bus.lon]);
                            busMarkers[plate].setStyle({{
                                fillColor: color,
                                color: "#fff"
                            }});
                            busMarkers[plate].setTooltipContent(
                                "<b>Bus:</b> " + plate +
                                "<br><b>Line:</b> " + (bus.line_id || "-")
                            );
                        }} else {{
                            busMarkers[plate] = L.circleMarker([bus.lat, bus.lon], {{
                                radius: 9,
                                fillColor: color,
                                color: "#fff",
                                weight: 2,
                                opacity: 1,
                                fillOpacity: 0.95
                            }})
                            .addTo(map)
                            .bindTooltip(
                                "<b>Bus:</b> " + plate +
                                "<br><b>Line:</b> " + (bus.line_id || "-")
                            );
                        }}

                        // fetch and draw path
                        const coords = await fetchBusPath(plate);

                        if (coords.length > 1) {{
                            if (busTrails[plate]) {{
                                busTrails[plate].setLatLngs(coords);
                                busTrails[plate].setStyle({{
                                    color: color
                                }});
                            }} else {{
                                busTrails[plate] = L.polyline(coords, {{
                                    color: color,
                                    weight: 4,
                                    opacity: 0.85
                                }}).addTo(map);
                            }}
                        }}
                    }}

                    // remove markers/trails for buses no longer active
                    Object.keys(busMarkers).forEach(plate => {{
                        if (!activePlates.has(plate)) {{
                            map.removeLayer(busMarkers[plate]);
                            delete busMarkers[plate];
                        }}
                    }});

                    Object.keys(busTrails).forEach(plate => {{
                        if (!activePlates.has(plate)) {{
                            map.removeLayer(busTrails[plate]);
                            delete busTrails[plate];
                        }}
                    }});

                    // fit only first time so map does not keep jumping
                    if (!firstFitDone && Object.keys(busMarkers).length > 0) {{
                        fitToFleet();
                        firstFitDone = true;
                    }}

                    badge('Live map', true);

                }} catch (err) {{
                    console.error(err);
                    badge('Update failed', false);
                }}
            }}

            renderMapData();
            setInterval(renderMapData, REFRESH_MS);
        </script>
    </body>
    </html>
    """

# =========================================================
# 4. UI
# =========================================================
st.title("📊 Fleet Research Manager")

col_top_1, col_top_2 = st.columns([1, 1])
with col_top_1:
    if st.button("Refresh cards"):
        st.rerun()
with col_top_2:
    st.caption("The map updates by itself every 10 seconds without redrawing the whole page.")

fleet = get_fleet_data()

if fleet:
    st.metric("Total Active Buses", len(fleet))

    st.subheader("🚐 Current Active Fleet")

    for bus in fleet:
        with st.expander(f"🚌 Bus {bus['plate_number']} | Line: {bus.get('line_id', '-')}", expanded=False):
            col1, col2, col3 = st.columns(3)
            history = get_history_stats(bus["plate_number"])

            if history:
                start_time = pd.to_datetime(history[0]["recorded_at"])
                duration = datetime.now(start_time.tzinfo) - start_time

                col1.metric("Shift Start", start_time.strftime("%H:%M:%S"))
                col2.metric("Total Mins", f"{duration.seconds // 60}m")
                col3.metric("Data Points", len(history))
            else:
                st.info("No history yet.")

    st.divider()
    st.subheader("🌍 Live Fleet Positions + Route History")
    components.html(build_map_html(URL, KEY), height=580)

else:
    st.warning("No buses currently online.")
    st.subheader("🌍 Live Fleet Positions + Route History")
    components.html(build_map_html(URL, KEY), height=580)
