from datetime import datetime, date, timedelta
import json
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
    .block-container {padding-top: 1.2rem !important;}
    .stMetric {
        background: rgba(255,255,255,0.02);
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 14px;
        padding: 12px;
    }
</style>
""", unsafe_allow_html=True)

# =========================================================
# 2. DATA FUNCTIONS
# =========================================================
def get_fleet_data():
    try:
        res = (
            supabase.table("live_bus_data")
            .select("*")
            .execute()
        )
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


def get_history_rows_for_date(selected_date: date):
    try:
        start_dt = datetime.combine(selected_date, datetime.min.time())
        end_dt = start_dt + timedelta(days=1)

        all_rows = []
        page_size = 1000
        start_index = 0

        while True:
            end_index = start_index + page_size - 1

            res = (
                supabase.table("bus_location_history")
                .select("plate_number, lat, lon, recorded_at, line_id")
                .gte("recorded_at", start_dt.isoformat())
                .lt("recorded_at", end_dt.isoformat())
                .order("recorded_at", desc=False)
                .range(start_index, end_index)
                .execute()
            )

            rows = res.data or []
            all_rows.extend(rows)

            if len(rows) < page_size:
                break

            start_index += page_size

        return all_rows

    except Exception:
        return []


def get_history_bus_ids_for_date(selected_date: date):
    rows = get_history_rows_for_date(selected_date)
    return sorted({str(r["plate_number"]) for r in rows if r.get("plate_number") is not None})


def filter_history_rows(rows, selected_bus: str):
    if selected_bus == "All buses":
        return rows
    return [r for r in rows if str(r.get("plate_number")) == str(selected_bus)]


def build_history_grouped(filtered_rows):
    grouped = {}
    for row in filtered_rows:
        plate = str(row.get("plate_number"))
        lat = row.get("lat")
        lon = row.get("lon")
        if lat is None or lon is None:
            continue
        grouped.setdefault(plate, []).append([lat, lon])
    return grouped


# =========================================================
# 3. PAGE TITLE
# =========================================================
st.title("Fleet Manager")

# =========================================================
# 4. MANUAL INQUIRY CONTROLS
# =========================================================
st.subheader("History Inquiry")

ctrl1, ctrl2, ctrl3, ctrl4 = st.columns([1, 1, 1.2, 1])

with ctrl1:
    date_mode = st.radio("Date mode", ["Today", "Yesterday", "Custom"], index=0)

if date_mode == "Today":
    selected_date = date.today()
elif date_mode == "Yesterday":
    selected_date = date.today() - timedelta(days=1)
else:
    with ctrl2:
        selected_date = st.date_input("Choose date", value=date.today())

if date_mode != "Custom":
    with ctrl2:
        st.text_input("Chosen date", value=selected_date.strftime("%Y-%m-%d"), disabled=True)

history_bus_ids = get_history_bus_ids_for_date(selected_date)
bus_options = ["All buses"] + history_bus_ids

with ctrl3:
    selected_bus = st.selectbox("Select bus", bus_options, index=0)

with ctrl4:
    show_live = st.toggle("Show live buses", value=True)
    show_history = st.toggle("Show history", value=True)
    # NEW: Color picker for history lines
    history_line_color = st.color_picker("Line color", "#00E5FF")

selected_date_str = selected_date.strftime("%Y-%m-%d")

all_history_rows = get_history_rows_for_date(selected_date)
filtered_history_rows = filter_history_rows(all_history_rows, selected_bus)
grouped_history = build_history_grouped(filtered_history_rows)

# =========================================================
# 5. QUERY RESULT SUMMARY
# =========================================================
fleet = get_fleet_data()

m1, m2, m3, m4 = st.columns(4)
m1.metric("Total Active Buses", len(fleet))
m2.metric("History Rows Found", len(filtered_history_rows))
m3.metric("History Buses Found", len(grouped_history))
m4.metric("Selected Date", selected_date_str)

# =========================================================
# 6. DATA PREVIEW
# =========================================================
with st.expander("Show queried history data", expanded=False):
    if filtered_history_rows:
        df = pd.DataFrame(filtered_history_rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No history rows found for this bus/date selection.")

# =========================================================
# 7. LIVE FLEET CARDS
# =========================================================
top_col_1, top_col_2 = st.columns([1, 2])
with top_col_1:
    if st.button("Refresh cards"):
        st.rerun()
with top_col_2:
    st.caption("The live map updates in the browser. History lines come from your manual date/bus inquiry above.")

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

# =========================================================
# 8. MAP HTML
# =========================================================
def build_map_html(
    supabase_url: str,
    supabase_key: str,
    show_live: bool,
    show_history: bool,
    selected_date_str: str,
    selected_bus: str,
    grouped_history: dict,
    line_color: str, # Added parameter
) -> str:
    history_json = json.dumps(grouped_history)

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
                height: 640px;
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
                min-width: 220px;
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
            #fit-live-btn {{ top: 12px; left: 56px; }}
            #fit-history-btn {{ top: 56px; left: 56px; }}
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
            <div><strong>Live buses:</strong> <span id="live-count">0</span></div>
            <div><strong>History buses:</strong> <span id="history-count">0</span></div>
        </div>

        <script>
            const SUPA_URL = "{supabase_url}";
            const SUPA_KEY = "{supabase_key}";
            const SHOW_LIVE = {str(show_live).lower()};
            const SHOW_HISTORY = {str(show_history).lower()};
            const SELECTED_BUS = "{selected_bus}";
            const HISTORY_COLOR = "{line_color}"; // Link to Streamlit picker
            const REFRESH_MS = 10000;
            const DEFAULT_CENTER = [35.56, 45.43];
            const DEFAULT_ZOOM = 12;
            const HISTORY_DATA = {history_json};

            const {{ createClient }} = supabase;
            const sb = createClient(SUPA_URL, SUPA_KEY, {{ auth: {{ persistSession: false }} }});

            const map = L.map('map', {{ center: DEFAULT_CENTER, zoom: DEFAULT_ZOOM }});
            L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                attribution: '© OpenStreetMap', maxZoom: 19
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

            function colorFromPlate(plate) {{
                const s = String(plate);
                let hash = 0;
                for (let i = 0; i < s.length; i++) {{ hash = s.charCodeAt(i) + ((hash << 5) - hash); }}
                return `hsl(${{Math.abs(hash) % 360}}, 78%, 55%)`;
            }}

            function fitToLive() {{
                const layers = Object.values(liveMarkers);
                if (layers.length) map.fitBounds(new L.featureGroup(layers).getBounds().pad(0.2));
            }}

            function fitToHistory() {{
                const layers = Object.values(historyLines);
                if (layers.length) map.fitBounds(new L.featureGroup(layers).getBounds().pad(0.15));
            }}

            async function fetchLiveFleet() {{
                const result = await sb.from('live_bus_data').select('*');
                if (result.error) throw result.error;
                return result.data || [];
            }}

            async function fetchRecentPath(plate) {{
                const result = await sb.from('bus_location_history').select('lat, lon')
                    .eq('plate_number', String(plate)).order('recorded_at', {{ ascending: false }}).limit(300);
                if (result.error) throw result.error;
                return (result.data || []).reverse().filter(r => r.lat && r.lon).map(r => [r.lat, r.lon]);
            }}

            function renderHistoryLayer() {{
                Object.keys(historyLines).forEach(p => map.removeLayer(historyLines[p]));
                if (!SHOW_HISTORY) return;

                Object.keys(HISTORY_DATA).forEach(plate => {{
                    const coords = HISTORY_DATA[plate];
                    if (!coords || coords.length < 2) return;
                    
                    historyLines[plate] = L.polyline(coords, {{
                        color: HISTORY_COLOR, // Use the selected color
                        weight: 5, opacity: 0.7
                    }}).addTo(map).bindTooltip("Bus: " + plate);
                }});

                if (Object.keys(historyLines).length > 0 && !firstFitDone) {{
                    fitToHistory(); firstFitDone = true;
                }}
            }}

            async function renderLiveLayer() {{
                Object.keys(liveMarkers).forEach(p => map.removeLayer(liveMarkers[p]));
                Object.keys(liveTrails).forEach(p => map.removeLayer(liveTrails[p]));
                if (!SHOW_LIVE) return;

                const fleet = await fetchLiveFleet();
                for (const bus of fleet) {{
                    const plate = String(bus.plate_number);
                    if (SELECTED_BUS !== "All buses" && plate !== SELECTED_BUS) continue;

                    const color = colorFromPlate(plate);
                    liveMarkers[plate] = L.circleMarker([bus.lat, bus.lon], {{
                        radius: 9, fillColor: color, color: "#fff", weight: 2, fillOpacity: 0.95
                    }}).addTo(map);

                    const path = await fetchRecentPath(plate);
                    if (path.length > 1) {{
                        liveTrails[plate] = L.polyline(path, {{ color: color, weight: 4, opacity: 0.95 }}).addTo(map);
                    }}
                }}
                if (!firstFitDone && Object.keys(liveMarkers).length > 0 && Object.keys(historyLines).length === 0) {{
                    fitToLive(); firstFitDone = true;
                }}
            }}

            async function renderAll() {{
                try {{
                    setBadge('Updating...', true);
                    renderHistoryLayer();
                    await renderLiveLayer();
                    document.getElementById('live-count').textContent = Object.keys(liveMarkers).length;
                    document.getElementById('history-count').textContent = Object.keys(historyLines).length;
                    setBadge('Map ready', true);
                }} catch (err) {{ setBadge('Error', false); }}
            }}

            renderAll();
            setInterval(renderAll, REFRESH_MS);
        </script>
    </body>
    </html>
    """

# =========================================================
# 9. MAP
# =========================================================
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
        grouped_history=grouped_history,
        line_color=history_line_color,
    ),
    height=660,
)
