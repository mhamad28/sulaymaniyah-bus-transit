from datetime import datetime, date, timedelta

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from supabase import Client, create_client

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
    .block-container {padding-top: 1.5rem !important;}
</style>
""", unsafe_allow_html=True)

# =========================================================
# 2. DATA FUNCTIONS
# =========================================================
def get_fleet_data():
    try:
        res = supabase.table("live_bus_data").select("*").execute()
        return res.data or []
    except Exception:
        return []


def get_history_stats(plate):
    try:
        res = (
            supabase.table("bus_location_history")
            .select("recorded_at")
            .eq("plate_number", str(plate))
            .order("recorded_at", desc=False)
            .execute()
        )
        return res.data or []
    except Exception:
        return []


def get_history_bus_ids_for_date(selected_date: date):
    """
    Returns all unique bus ids that have history on the chosen date.
    This is the key fix: bus selector comes from history table,
    not only from live buses.
    """
    try:
        start_dt = datetime.combine(selected_date, datetime.min.time())
        end_dt = start_dt + timedelta(days=1)

        res = (
            supabase.table("bus_location_history")
            .select("plate_number, recorded_at")
            .gte("recorded_at", start_dt.isoformat())
            .lt("recorded_at", end_dt.isoformat())
            .order("recorded_at", desc=False)
            .execute()
        )

        rows = res.data or []
        bus_ids = sorted({str(r["plate_number"]) for r in rows if r.get("plate_number") is not None})
        return bus_ids
    except Exception:
        return []


# =========================================================
# 3. SIDEBAR CONTROLS
# =========================================================
st.sidebar.header("🕹️ Controls")

show_live = st.sidebar.toggle("Show live buses", value=True)
show_history = st.sidebar.toggle("Show history lines", value=True)

date_mode = st.sidebar.radio(
    "History date",
    ["Today", "Yesterday", "Custom"],
    index=0
)

if date_mode == "Today":
    selected_date = date.today()
elif date_mode == "Yesterday":
    selected_date = date.today() - timedelta(days=1)
else:
    selected_date = st.sidebar.date_input("Choose date", value=date.today())

selected_date_str = selected_date.strftime("%Y-%m-%d")

# IMPORTANT:
# Bus list comes from history table on selected date,
# so offline buses also appear.
history_bus_ids = get_history_bus_ids_for_date(selected_date)
bus_options = ["All buses"] + history_bus_ids

selected_bus = st.sidebar.selectbox(
    "Select bus for inquiry",
    bus_options,
    index=0
)

st.sidebar.caption(f"Selected date: {selected_date_str}")
st.sidebar.caption(f"Selected bus: {selected_bus}")


# =========================================================
# 4. PAGE DATA
# =========================================================
fleet = get_fleet_data()


# =========================================================
# 5. MAP HTML
# =========================================================
def build_map_html(
    supabase_url: str,
    supabase_key: str,
    show_live: bool,
    show_history: bool,
    selected_date_str: str,
    selected_bus: str,
) -> str:
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
                height: 620px;
                width: 100%;
                border-radius: 16px;
                border: 2px solid #333;
            }}
            .leaflet-control-zoom {{
                border: none !important;
            }}
            .leaflet-control-zoom a {{
                background: rgba(15,23,42,.95) !important;
                color: #e5e7eb !important;
                border: 1px solid rgba(255,255,255,.10) !important;
            }}
            .map-badge {{
                position: absolute;
                top: 12px;
                right: 12px;
                z-index: 1000;
                background: rgba(15,23,42,.95);
                color: #86efac;
                border: 1px solid rgba(34,197,94,.35);
                border-radius: 999px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: 700;
                backdrop-filter: blur(8px);
                box-shadow: 0 4px 16px rgba(0,0,0,.35);
            }}
            .mini-info {{
                position: absolute;
                top: 52px;
                right: 12px;
                z-index: 1000;
                background: rgba(15,23,42,.95);
                color: #cbd5e1;
                border: 1px solid rgba(255,255,255,.12);
                border-radius: 14px;
                padding: 10px 12px;
                font-size: 12px;
                line-height: 1.5;
                backdrop-filter: blur(8px);
                box-shadow: 0 4px 16px rgba(0,0,0,.35);
                min-width: 210px;
            }}
            .map-btn {{
                position: absolute;
                z-index: 1000;
                background: rgba(15,23,42,.95);
                color: #e5e7eb;
                border: 1px solid rgba(255,255,255,.12);
                border-radius: 12px;
                padding: 8px 12px;
                font-size: 12px;
                font-weight: 700;
                cursor: pointer;
                box-shadow: 0 4px 16px rgba(0,0,0,.35);
            }}
            #fit-live-btn {{
                top: 12px;
                left: 56px;
            }}
            #fit-history-btn {{
                top: 56px;
                left: 56px;
            }}
            .leaflet-tooltip {{
                font-size: 12px;
            }}
        </style>
    </head>
    <body>
        <div id="map"></div>

        <button id="fit-live-btn" class="map-btn" onclick="fitToLive()">Fit Live</button>
        <button id="fit-history-btn" class="map-btn" onclick="fitToHistory()">Fit History</button>

        <div class="map-badge" id="status-badge">Map ready</div>

        <div class="mini-info">
            <div><strong>Date:</strong> {selected_date_str}</div>
            <div><strong>Bus:</strong> {selected_bus}</div>
            <div><strong>Live buses shown:</strong> <span id="live-count">0</span></div>
            <div><strong>History buses shown:</strong> <span id="history-count">0</span></div>
        </div>

        <script>
            const SUPA_URL = "{supabase_url}";
            const SUPA_KEY = "{supabase_key}";
            const SHOW_LIVE = {str(show_live).lower()};
            const SHOW_HISTORY = {str(show_history).lower()};
            const SELECTED_DATE = "{selected_date_str}";
            const SELECTED_BUS = "{selected_bus}";
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

            const liveMarkers = {{}};
            const liveTrails = {{}};
            const historyLines = {{}};

            let firstFitDone = false;

            function setBadge(text, ok = true) {{
                const el = document.getElementById('status-badge');
                el.textContent = text;
                el.style.color = ok ? '#86efac' : '#fca5a5';
                el.style.borderColor = ok ? 'rgba(34,197,94,.35)' : 'rgba(239,68,68,.35)';
            }}

            function updateCounts() {{
                document.getElementById('live-count').textContent = Object.keys(liveMarkers).length;
                document.getElementById('history-count').textContent = Object.keys(historyLines).length;
            }}

            function colorFromPlate(plate) {{
                const s = String(plate);
                let hash = 0;
                for (let i = 0; i < s.length; i++) {{
                    hash = s.charCodeAt(i) + ((hash << 5) - hash);
                }}
                const hue = Math.abs(hash) % 360;
                return `hsl(${{hue}}, 78%, 55%)`;
            }}

            function fitToLive() {{
                const layers = Object.values(liveMarkers);
                if (!layers.length) return;
                const group = new L.featureGroup(layers);
                map.fitBounds(group.getBounds().pad(0.2));
            }}

            function fitToHistory() {{
                const layers = Object.values(historyLines);
                if (!layers.length) return;
                const group = new L.featureGroup(layers);
                map.fitBounds(group.getBounds().pad(0.15));
            }}

            async function fetchLiveFleet() {{
                const result = await sb
                    .from('live_bus_data')
                    .select('*');

                if (result.error) throw result.error;
                return result.data || [];
            }}

            async function fetchRecentPath(plate) {{
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

            async function fetchHistoryByDate(dateStr) {{
                const start = dateStr + "T00:00:00";
                const nextDate = new Date(dateStr + "T00:00:00");
                nextDate.setDate(nextDate.getDate() + 1);

                const endYear = nextDate.getFullYear();
                const endMonth = String(nextDate.getMonth() + 1).padStart(2, '0');
                const endDay = String(nextDate.getDate()).padStart(2, '0');
                const end = `${{endYear}}-${{endMonth}}-${{endDay}}T00:00:00`;

                const result = await sb
                    .from('bus_location_history')
                    .select('plate_number, lat, lon, recorded_at')
                    .gte('recorded_at', start)
                    .lt('recorded_at', end)
                    .order('recorded_at', {{ ascending: true }});

                if (result.error) throw result.error;

                const grouped = {{}};

                for (const row of (result.data || [])) {{
                    if (row.lat === null || row.lon === null) continue;

                    const plate = String(row.plate_number);

                    if (SELECTED_BUS !== "All buses" && plate !== SELECTED_BUS) continue;

                    if (!grouped[plate]) grouped[plate] = [];
                    grouped[plate].push([row.lat, row.lon]);
                }}

                return grouped;
            }}

            function clearHistoryLines() {{
                Object.keys(historyLines).forEach(plate => {{
                    map.removeLayer(historyLines[plate]);
                    delete historyLines[plate];
                }});
            }}

            async function renderHistoryLayer() {{
                clearHistoryLines();

                if (!SHOW_HISTORY) {{
                    updateCounts();
                    return;
                }}

                const grouped = await fetchHistoryByDate(SELECTED_DATE);

                Object.keys(grouped).forEach(plate => {{
                    const coords = grouped[plate];
                    if (coords.length < 2) return;

                    const color = colorFromPlate(plate);

                    historyLines[plate] = L.polyline(coords, {{
                        color: color,
                        weight: 5,
                        opacity: 0.6
                    }})
                    .addTo(map)
                    .bindTooltip(
                        "<b>Bus:</b> " + plate +
                        "<br><b>Date:</b> " + SELECTED_DATE +
                        "<br><b>Points:</b> " + coords.length +
                        "<br><b>Status:</b> History"
                    );
                }});

                updateCounts();

                if (!SHOW_LIVE && Object.keys(historyLines).length > 0 && !firstFitDone) {{
                    fitToHistory();
                    firstFitDone = true;
                }}
            }}

            async function renderLiveLayer() {{
                if (!SHOW_LIVE) {{
                    Object.keys(liveMarkers).forEach(plate => {{
                        map.removeLayer(liveMarkers[plate]);
                        delete liveMarkers[plate];
                    }});
                    Object.keys(liveTrails).forEach(plate => {{
                        map.removeLayer(liveTrails[plate]);
                        delete liveTrails[plate];
                    }});
                    updateCounts();
                    return;
                }}

                const fleet = await fetchLiveFleet();
                const activePlates = new Set();

                for (const bus of fleet) {{
                    const plate = String(bus.plate_number);

                    if (SELECTED_BUS !== "All buses" && plate !== SELECTED_BUS) {{
                        continue;
                    }}

                    const color = colorFromPlate(plate);
                    activePlates.add(plate);

                    if (liveMarkers[plate]) {{
                        liveMarkers[plate].setLatLng([bus.lat, bus.lon]);
                        liveMarkers[plate].setStyle({{
                            fillColor: color,
                            color: "#ffffff"
                        }});
                        liveMarkers[plate].setTooltipContent(
                            "<b>Bus:</b> " + plate +
                            "<br><b>Line:</b> " + (bus.line_id || "-") +
                            "<br><b>Status:</b> Live"
                        );
                    }} else {{
                        liveMarkers[plate] = L.circleMarker([bus.lat, bus.lon], {{
                            radius: 9,
                            fillColor: color,
                            color: "#ffffff",
                            weight: 2,
                            opacity: 1,
                            fillOpacity: 0.95
                        }})
                        .addTo(map)
                        .bindTooltip(
                            "<b>Bus:</b> " + plate +
                            "<br><b>Line:</b> " + (bus.line_id || "-") +
                            "<br><b>Status:</b> Live"
                        );
                    }}

                    const coords = await fetchRecentPath(plate);
                    if (coords.length > 1) {{
                        if (liveTrails[plate]) {{
                            liveTrails[plate].setLatLngs(coords);
                            liveTrails[plate].setStyle({{ color: color }});
                        }} else {{
                            liveTrails[plate] = L.polyline(coords, {{
                                color: color,
                                weight: 4,
                                opacity: 0.9
                            }}).addTo(map);
                        }}
                    }}
                }}

                Object.keys(liveMarkers).forEach(plate => {{
                    if (!activePlates.has(plate)) {{
                        map.removeLayer(liveMarkers[plate]);
                        delete liveMarkers[plate];
                    }}
                }});

                Object.keys(liveTrails).forEach(plate => {{
                    if (!activePlates.has(plate)) {{
                        map.removeLayer(liveTrails[plate]);
                        delete liveTrails[plate];
                    }}
                }});

                if (!firstFitDone && Object.keys(liveMarkers).length > 0) {{
                    fitToLive();
                    firstFitDone = true;
                }}

                updateCounts();
            }}

            async function renderAll() {{
                try {{
                    setBadge('Updating map...', true);
                    await renderHistoryLayer();
                    await renderLiveLayer();
                    setBadge('Live map', true);
                }} catch (err) {{
                    console.error(err);
                    setBadge('Update failed', false);
                }}
            }}

            renderAll();
            setInterval(renderAll, REFRESH_MS);
        </script>
    </body>
    </html>
    """


# =========================================================
# 6. PAGE UI
# =========================================================
st.title("Fleet Manager")

top_col_1, top_col_2 = st.columns([1, 2])
with top_col_1:
    if st.button("Refresh cards"):
        st.rerun()
with top_col_2:
    st.caption("The map updates by itself every 10 seconds without redrawing the whole page.")

st.metric("Total Active Buses", len(fleet))

st.subheader("🚌 Current Active Fleet")

if fleet:
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
else:
    st.warning("No buses currently online.")

st.divider()
st.subheader("🌍 Live Fleet Positions + History Lines")

components.html(
    build_map_html(
        supabase_url=URL,
        supabase_key=KEY,
        show_live=show_live,
        show_history=show_history,
        selected_date_str=selected_date_str,
        selected_bus=selected_bus,
    ),
    height=640,
)
