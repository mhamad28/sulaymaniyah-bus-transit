import json
import sys
from pathlib import Path
from typing import Dict, List

import streamlit as st
import streamlit.components.v1 as components

sys.path.append(str(Path(__file__).resolve().parents[1] / "shared"))
try:
    from supabase_client import get_supabase
    _SUPABASE_AVAILABLE = True
except ImportError:
    _SUPABASE_AVAILABLE = False

st.set_page_config(page_title="Suly Transit", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
  header[data-testid="stHeader"]   { display: none !important; }
  section[data-testid="stSidebar"] { display: none !important; }
  footer                           { display: none !important; }
  .stDeployButton                  { display: none !important; }
  .block-container { padding:0!important; margin:0!important; max-width:100%!important; }
  div[data-testid="stCustomComponentV1"] { margin:0!important; padding:0!important; line-height:0!important; }
</style>
""", unsafe_allow_html=True)

ROUTES_FILE    = Path(__file__).resolve().parents[1] / "assets" / "bus_lines.geojson"
DEFAULT_CENTER = [35.56, 45.43]
DEFAULT_ZOOM   = 13
MAX_WALK_KM    = 0.70

ROUTE_COLORS: Dict[str, str] = {
    "Bakrajo_Bazar":      "#e41a1c",
    "Chwarchra_Bazar":    "#377eb8",
    "FarmanBaran_Bazar":  "#4daf4a",
    "HawaryShar_Bazar":   "#984ea3",
    "Kazywa_Bazar":       "#ff7f00",
    "Kshtukal_Bazar":     "#a65628",
    "Qrgra_Bazar":        "#f781bf",
    "Raparin_Bazar":      "#999999",
    "Rzgary Bazar":       "#66c2a5",
    "Shakraka_Bazar":     "#fc8d62",
    "TwiMalik_Bazar":     "#8da0cb",
    "Xabat_Bazar":        "#ffd92f",
    "ZargatayTaza_Bazar": "#1b9e77",
}

@st.cache_data(hash_funcs={Path: lambda p: p.stat().st_mtime if p.exists() else 0})
def load_routes(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing route file: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def fetch_live_buses() -> list:
    if not _SUPABASE_AVAILABLE:
        return []
    try:
        sb  = get_supabase()
        res = sb.table("active_locations") \
                .select("bus_line,bus_number,lat,lon,speed_kmh,updated_at") \
                .eq("is_active", True).execute()
        return res.data or []
    except Exception:
        return []

def build_map_html(routes_geojson: dict, live_buses: list,
                   supabase_url: str, supabase_key: str) -> str:

    geojson_str  = json.dumps(routes_geojson)
    colors_str   = json.dumps(ROUTE_COLORS)
    buses_str    = json.dumps(live_buses)
    legend_items = json.dumps([
        {"name": k.replace("_", " "), "color": v} for k, v in ROUTE_COLORS.items()
    ])

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"/>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Noto+Naskh+Arabic:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html,body {{ width:100%; height:100%; background:#080d14; overflow:hidden;
  font-family:'Noto Naskh Arabic',system-ui,sans-serif; }}
#map {{ width:100%; height:100vh; }}

.card {{
  background:rgba(10,16,26,0.88); backdrop-filter:blur(16px);
  border:1px solid rgba(255,255,255,0.10); border-radius:14px;
  box-shadow:0 8px 32px rgba(0,0,0,0.5); color:#e2eaf4;
}}

/* ── CYAN TARGET BUTTON (SWAPPED) ── */
#recenter-btn {{
  position: absolute; bottom: 110px; right: 20px; z-index: 1001;
  width: 50px; height: 50px; border-radius: 12px; background: #000000; 
  border: 1px solid rgba(255,255,255,0.2); cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 4px 15px rgba(0,0,0,0.5); transition: all 0.2s;
}}
#recenter-btn::before {{
  content: ""; width: 28px; height: 28px;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%2300E5FF' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='12' cy='12' r='3' fill='%2300E5FF'/%3E%3Ccircle cx='12' cy='12' r='7'/%3E%3Cline x1='12' y1='1' x2='12' y2='5'/%3E%3Cline x1='12' y1='19' x2='12' y2='23'/%3E%3Cline x1='1' y1='12' x2='5' y2='12'/%3E%3Cline x1='19' y1='12' x2='23' y2='12'/%3E%3C/svg%3E");
  background-size: contain; background-repeat: no-repeat;
}}
#recenter-btn:active {{ transform: scale(0.9); }}
#recenter-btn.locating {{ border-color: #00E5FF; box-shadow: 0 0 15px #00E5FF; }}

/* ── TOP PANEL ── */
#top-panel {{
  position:absolute; top:14px; left:50%; transform:translateX(-50%);
  z-index:1000; width:min(520px,92vw); padding:12px 14px;
  display:flex; flex-direction:column; gap:8px;
}}
.row {{ display:flex; align-items:center; gap:8px; }}
.dot {{ width:11px; height:11px; border-radius:50%; flex-shrink:0; border:2px solid rgba(255,255,255,.5); }}
.pick-btn {{
  flex-shrink:0; padding:6px 13px; border-radius:8px; border:1.5px solid;
  font-size:12px; font-weight:700; cursor:pointer; background:transparent;
  transition:all .15s; white-space:nowrap; font-family:'Noto Naskh Arabic',sans-serif;
}}
.pick-btn:hover {{ filter:brightness(1.2); transform:translateY(-1px); }}
.pick-btn.green {{ border-color:#22c55e; color:#4ade80; }}
.pick-btn.green.on {{ background:#22c55e; color:#000; box-shadow:0 0 12px rgba(34,197,94,.5); }}
.pick-btn.red {{ border-color:#ef4444; color:#f87171; }}
.pick-btn.red.on {{ background:#ef4444; color:#fff; box-shadow:0 0 12px rgba(239,68,68,.5); }}

.coord-box {{
  flex:1; min-width:0; background:rgba(255,255,255,.07); border:1px solid rgba(255,255,255,.13);
  border-radius:8px; padding:7px 10px; font-size:12px; font-family:monospace;
  color:#e2eaf4; outline:none; transition:border-color .15s; direction:ltr;
}}
.coord-box::placeholder {{ color:#475569; direction:rtl; font-family:'Noto Naskh Arabic',sans-serif; }}
.coord-box:focus {{ border-color:#00d4ff; }}
.x-btn {{
  flex-shrink:0; width:24px; height:24px; border-radius:50%;
  border:1px solid rgba(255,255,255,.15); background:rgba(255,255,255,.06);
  color:#64748b; font-size:12px; cursor:pointer; line-height:1; transition:all .15s;
}}
.x-btn:hover {{ background:rgba(255,255,255,.18); color:#e2eaf4; }}
.hr {{ height:1px; background:rgba(255,255,255,.08); }}
.reset-btn {{
  background:transparent; border:1px solid rgba(148,163,184,.3);
  border-radius:7px; color:#94a3b8; font-size:11px; font-weight:600;
  padding:4px 14px; cursor:pointer; margin-left:auto; transition:all .15s;
  font-family:'Noto Naskh Arabic',sans-serif;
}}
.reset-btn:hover {{ background:rgba(148,163,184,.15); color:#e2eaf4; }}
.picking {{ cursor:crosshair !important; }}

/* ── RESULT CARD ── */
#result-card {{
  position:absolute; z-index:1000; pointer-events:none;
  transition:all .4s cubic-bezier(.34,1.56,.64,1);
}}
#result-card.float {{
  bottom:20px; left:50%; transform:translateX(-50%) translateY(300px);
  width:min(460px,92vw); padding:14px 16px; max-height:60vh; overflow-y:auto;
}}
#result-card.float.show {{ transform:translateX(-50%) translateY(0); pointer-events:all; }}
#result-card.bottom {{
  bottom:0; left:0; right:0; width:100%; border-radius:16px 16px 0 0;
  transform:translateY(100%); padding:12px 16px 16px; max-height:38vh; overflow-y:auto;
}}
#result-card.bottom.show {{ transform:translateY(0); pointer-events:all; }}
#result-toggle {{
  position:absolute; top:8px; left:10px;
  background:rgba(255,255,255,.08); border:1px solid rgba(255,255,255,.15);
  border-radius:6px; color:#94a3b8; font-size:11px; font-weight:600;
  padding:3px 8px; cursor:pointer; z-index:10; display:flex; align-items:center; gap:4px;
  transition:all .15s; font-family:'Noto Naskh Arabic',sans-serif;
}}
#result-toggle:hover {{ background:rgba(255,255,255,.16); color:#e2eaf4; }}
.summary {{
  text-align:center; font-size:13px; font-weight:700;
  padding:7px 12px; border-radius:8px; margin-bottom:10px;
}}
.summary.ok  {{ background:rgba(34,197,94,.15);  border:1px solid rgba(34,197,94,.3);  color:#4ade80; }}
.summary.xfr {{ background:rgba(251,191,36,.13); border:1px solid rgba(251,191,36,.3); color:#fbbf24; }}
.summary.err {{ background:rgba(239,68,68,.13);  border:1px solid rgba(239,68,68,.3);  color:#f87171; }}

/* ── LEG CARDS ── */
.legs {{ display:flex; flex-direction:column; gap:5px; }}
.leg {{
  border-radius:10px; overflow:hidden; background:rgba(255,255,255,.05);
  border:1px solid rgba(255,255,255,.08); cursor:pointer; transition:background .15s; user-select:none;
}}
.leg:hover {{ background:rgba(255,255,255,.09); }}
.leg-top {{ display:flex; align-items:center; gap:8px; padding:10px 12px; }}
.leg-chips {{ display:flex; align-items:center; gap:4px; flex-shrink:0; }}
.leg-chip {{ font-size:11px; font-weight:700; padding:3px 9px; border-radius:20px; border:1.5px solid; white-space:nowrap; }}
.leg-chip.walk {{ background:rgba(148,163,184,.1); border-color:rgba(148,163,184,.3); color:#94a3b8; }}
.leg-chip.xfer {{ background:rgba(251,191,36,.1); border-color:rgba(251,191,36,.3); color:#fbbf24; padding:3px 7px; }}
.leg-arr {{ color:#475569; font-size:12px; margin:0 1px; }}
.leg-label {{ flex:1; font-size:12px; color:#e2eaf4; font-weight:500; line-height:1.4; direction:rtl; }}
.leg-caret {{ color:#475569; font-size:14px; transition:transform .2s; flex-shrink:0; }}
.leg.open .leg-caret {{ transform:rotate(90deg); }}
.leg-detail {{
  display:none; padding:8px 12px 10px; font-size:11px; color:#64748b; line-height:1.5;
  border-top:1px solid rgba(255,255,255,.05); direction:rtl;
}}
.leg.open .leg-detail {{ display:block; }}

/* ── LEGEND ── */
#leg-btn {{
  position:absolute; top:14px; right:14px; z-index:1001; width:38px; height:38px;
  border-radius:10px; background:rgba(10,16,26,.88); backdrop-filter:blur(14px);
  border:1px solid rgba(255,255,255,.10); color:#e2eaf4; font-size:18px; cursor:pointer;
  display:flex; align-items:center; justify-content:center; box-shadow:0 4px 16px rgba(0,0,0,.4);
}}
#leg-panel {{
  position:absolute; top:60px; right:14px; z-index:1000;
  width:190px; max-height:55vh; overflow-y:auto;
  padding:10px 12px; display:none; flex-direction:column; gap:5px;
}}
#leg-panel.open {{ display:flex; }}
.li {{ display:flex; align-items:center; gap:7px; font-size:12px; color:#e2eaf4; }}
.ld {{ width:9px; height:9px; border-radius:50%; flex-shrink:0; }}

/* ── LIVE BADGE ── */
#live-badge {{
  position:absolute; bottom:20px; right:14px; z-index:1000;
  padding:5px 13px; border-radius:20px; font-size:11px; font-weight:600;
  color:#4ade80; border:1px solid rgba(34,197,94,.3);
  background:rgba(10,16,26,.88); backdrop-filter:blur(14px);
  display:flex; align-items:center; gap:6px;
}}
.ld-dot {{ width:7px; height:7px; border-radius:50%; background:#22c55e; animation:blink 1.4s infinite; }}
@keyframes blink {{ 0%,100%{{opacity:1;}} 50%{{opacity:.2;}} }}
.leaflet-control-zoom {{ border:none !important; }}
.leaflet-control-zoom a {{
  background:rgba(10,16,26,.88) !important; color:#e2eaf4 !important;
  border:1px solid rgba(255,255,255,.10) !important;
}}
</style>
</head>
<body>
<div id="map"></div>

<button id="recenter-btn" onclick="useMyLocation()" title="Find my location"></button>

<div id="top-panel" class="card" dir="rtl" lang="ckb">
  <div class="row">
    <span class="dot" style="background:#22c55e"></span>
    <button class="pick-btn green" id="btn-o" onclick="toggleMode('origin')">📍 هەڵبژێرە</button>
    <input class="coord-box" id="inp-o" placeholder="بنکە — کۆدینەیت لە گووگڵ مەپ لێرە بنووسە"
           oninput="onCoordInput('origin', this.value)"/>
    <button class="x-btn" onclick="clearPt('origin')">✕</button>
  </div>
  <div class="hr"></div>
  <div class="row">
    <span class="dot" style="background:#ef4444"></span>
    <button class="pick-btn red" id="btn-d" onclick="toggleMode('dest')">🏁 هەڵبژێرە</button>
    <input class="coord-box" id="inp-d" placeholder="مەودا — کۆدینەیت لە گووگڵ مەپ لێرە بنووسە"
           oninput="onCoordInput('dest', this.value)"/>
    <button class="x-btn" onclick="clearPt('dest')">✕</button>
  </div>
  <div class="hr"></div>
  <div class="row"><button class="reset-btn" onclick="resetAll()">↺ ڕەستکردنەوە</button></div>
</div>

<button id="leg-btn" onclick="toggleLeg()">🗺</button>
<div id="leg-panel" class="card">
  <div style="font-size:9px;font-weight:700;letter-spacing:.05em;color:#475569;margin-bottom:4px;">هێڵەکانی بەس</div>
</div>

<div id="result-card" class="card float" dir="rtl" lang="ckb">
  <button id="result-toggle" onclick="cycleResultMode()" style="display:none">▤ خوارەوە</button>
  <div id="result-inner"></div>
</div>

<div id="live-badge" dir="rtl" lang="ckb"><span class="ld-dot"></span><span id="bus-ct">٠ بەس</span></div>

<script>
const COLORS   = {colors_str};
const GEOJSON  = {geojson_str};
const LEGEND   = {legend_items};
const BUSES    = {buses_str};
const SUPA_URL = "{supabase_url}";
const SUPA_KEY = "{supabase_key}";
const MAX_WALK = {MAX_WALK_KM};

// ── Map ───────────────────────────────────────────────────────────────────────
const map = L.map('map', {{
  center: [{DEFAULT_CENTER[0]}, {DEFAULT_CENTER[1]}],
  zoom: {DEFAULT_ZOOM}, minZoom: 10, maxZoom: 19
}});
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
  {{attribution:'© OpenStreetMap', maxZoom:19}}).addTo(map);

// ── Routes ──
let routeLayer = null;
function drawRoutes(active) {{
  if(routeLayer) map.removeLayer(routeLayer);
  routeLayer = L.geoJSON(GEOJSON, {{
    style: f => {{
      const n = (f.properties && f.properties.layer) || '';
      const c = COLORS[n] || '#3388ff';
      if(active && active.size > 0)
        return active.has(n) ? {{color:c, weight:7, opacity:1.0}}
                             : {{color:c, weight:2, opacity:0.13}};
      return {{color:c, weight:4, opacity:0.88}};
    }},
    onEachFeature: (f,l) => l.bindTooltip((f.properties&&f.properties.layer)||'Route', {{sticky:true}})
  }}).addTo(map);
}}
drawRoutes(null);

// ── Legend ──
const legPanel = document.getElementById('leg-panel');
LEGEND.forEach(item => {{
  const d = document.createElement('div');
  d.className = 'li';
  d.innerHTML = `<span class="ld" style="background:${{item.color}}"></span>${{item.name}}`;
  legPanel.appendChild(d);
}});
function toggleLeg() {{ legPanel.classList.toggle('open'); }}

// ── Pin markers ──
function pinIcon(color) {{
  return L.divIcon({{
    html: `<div style="width:16px;height:16px;border-radius:50%;background:${{color}};border:3px solid #fff;box-shadow:0 0 8px ${{color}}"></div>`,
    iconSize:[16,16], iconAnchor:[8,8], className:''
  }});
}}
let mO = null, mD = null;
function placeO(lat, lon) {{
  if(mO) map.removeLayer(mO);
  mO = L.marker([lat,lon], {{icon:pinIcon('#22c55e')}}).bindTooltip('Origin').addTo(map);
}}
function placeD(lat, lon) {{
  if(mD) map.removeLayer(mD);
  mD = L.marker([lat,lon], {{icon:pinIcon('#ef4444')}}).bindTooltip('Destination').addTo(map);
}}

// ── Live buses ──
const busM = {{}};
function busIcon(color, num) {{
  return L.divIcon({{
    html: `<div style="background:${{color}};color:#fff;font-size:9px;font-weight:700;padding:3px 7px;border-radius:6px;border:2px solid #fff;box-shadow:0 0 8px ${{color}};white-space:nowrap;">${{num}}</div>`,
    className:'', iconAnchor:[20,12]
  }});
}}
function placeBus(b) {{
  const c = COLORS[b.bus_line] || '#00d4ff';
  const tip = b.bus_number+' · '+(b.bus_line||'').replace(/_/g,' ')+' · '+Math.round(b.speed_kmh||0)+' km/h';
  if(busM[b.bus_number]) {{
    busM[b.bus_number].setLatLng([b.lat,b.lon]);
    busM[b.bus_number].setTooltipContent(tip);
  }} else {{
    busM[b.bus_number] = L.marker([b.lat,b.lon], {{icon:busIcon(c,b.bus_number), zIndexOffset:500}})
      .bindTooltip(tip).addTo(map);
  }}
  document.getElementById('bus-ct').textContent = Object.keys(busM).length + ' بەس زیندوو';
}}
BUSES.forEach(placeBus);
if(SUPA_URL && SUPA_KEY) {{
  const {{createClient}} = supabase;
  const sb = createClient(SUPA_URL, SUPA_KEY, {{auth:{{persistSession:false}}}});
  sb.channel('buses').on('postgres_changes',
    {{event:'*', schema:'public', table:'active_locations'}}, p => {{
      const b = p.new; if(!b) return;
      if(b.is_active) placeBus(b);
      else if(busM[b.bus_number]) {{ map.removeLayer(busM[b.bus_number]); delete busM[b.bus_number]; }}
    }}).subscribe();
}}

// ══════════════════════════════════════════════════════════════════════════════
//  ROUTING ENGINE  (pure JS — zero Streamlit reruns)
// ══════════════════════════════════════════════════════════════════════════════
const XFER_MAX_KM = 0.05;   // 50m max gap for transfer
const XFER_SAME   = 0.015;  // 15m = same road

const ROUTE_PTS = Object.create(null);
for(const f of GEOJSON.features||[]) {{
  const name = (f.properties && f.properties.layer) || ''; if(!name) continue;
  if(!ROUTE_PTS[name]) ROUTE_PTS[name] = [];
  const geom = f.geometry || {{}};
  const segs = geom.type==='LineString'      ? [geom.coordinates]
             : geom.type==='MultiLineString' ?  geom.coordinates : [];
  for(const seg of segs)
    for(const c of seg)
      if(Array.isArray(c) && c.length>=2) ROUTE_PTS[name].push({{lat:c[1], lon:c[0]}});
}}
const ROUTE_NAMES = Object.keys(ROUTE_PTS);

function hav(la1,lo1,la2,lo2) {{
  const R=6371, r=Math.PI/180;
  const dla=(la2-la1)*r, dlo=(lo2-lo1)*r;
  const a=Math.sin(dla/2)**2+Math.cos(la1*r)*Math.cos(la2*r)*Math.sin(dlo/2)**2;
  return R*2*Math.atan2(Math.sqrt(a),Math.sqrt(1-a));
}}

function nearestOnRoute(lat, lon, name) {{
  let best=Infinity, bestPt=null;
  for(const p of (ROUTE_PTS[name]||[])) {{
    const d=hav(lat,lon,p.lat,p.lon);
    if(d<best){{best=d; bestPt=p;}}
  }}
  return {{km:best, pt:bestPt}};
}}

function nearbyRoutes(lat, lon, maxKm) {{
  const out=[];
  for(const name of ROUTE_NAMES) {{
    const {{km,pt}}=nearestOnRoute(lat,lon,name);
    if(km<=maxKm) out.push({{name,km,boardPt:pt}});
  }}
  return out.sort((a,b)=>a.km-b.km);
}}

function closestApproach(nameA, nameB) {{
  const ptsA=ROUTE_PTS[nameA]||[], ptsB=ROUTE_PTS[nameB]||[];
  if(!ptsA.length||!ptsB.length) return {{gapKm:Infinity,ptA:null,ptB:null}};
  let best=Infinity, ptA=ptsA[0], ptB=ptsB[0];
  for(let i=0;i<ptsA.length;i++) {{
    const la=ptsA[i].lat, lo=ptsA[i].lon;
    for(let j=0;j<ptsB.length;j++) {{
      const d=hav(la,lo,ptsB[j].lat,ptsB[j].lon);
      if(d<best){{best=d; ptA=ptsA[i]; ptB=ptsB[j];}}
    }}
  }}
  return {{gapKm:best, ptA, ptB}};
}}

const APPROACH = Object.create(null);
for(const a of ROUTE_NAMES) {{
  APPROACH[a] = Object.create(null);
  for(const b of ROUTE_NAMES) {{
    if(a!==b) APPROACH[a][b] = closestApproach(a,b);
  }}
}}

// ── State ──
let ptO=null, ptD=null;
let _dropMarker=null, _boardMarker=null, _walkLine=null, _walkLine2=null;
function clearXferLayers() {{
  [_dropMarker,_boardMarker,_walkLine,_walkLine2].forEach(l=>{{if(l)map.removeLayer(l);}});
  _dropMarker=_boardMarker=_walkLine=_walkLine2=null;
}}

// ── Compute route ──
function compute() {{
  clearXferLayers();
  if(!ptO||!ptD) {{ hideResult(); return; }}

  const atO=nearbyRoutes(ptO.lat,ptO.lon,MAX_WALK);
  const atD=nearbyRoutes(ptD.lat,ptD.lon,MAX_WALK);

  if(!atO.length) {{ showErr('دەستپێکردنت زیاتر لە '+Math.round(MAX_WALK*1000)+' م دوورە لە هیچ هێڵێک'); return; }}
  if(!atD.length) {{ showErr('مەوداکەت زیاتر لە '+Math.round(MAX_WALK*1000)+' م دوورە لە هیچ هێڵێک'); return; }}

  const namesAtD = new Set(atD.map(r=>r.name));

  // CASE 1: Direct
  const directs = atO.filter(r=>namesAtD.has(r.name));
  if(directs.length>0) {{
    let best=null, bestTotal=Infinity;
    for(const r of directs) {{
      const wD=atD.find(x=>x.name===r.name).km;
      if(r.km+wD<bestTotal){{bestTotal=r.km+wD; best=r;}}
    }}
    const walkD=atD.find(r=>r.name===best.name).km;
    const alts=directs.filter(r=>r.name!==best.name);
    _dropMarker=pulseMarker(best.boardPt.lat,best.boardPt.lon,'#22c55e','سەر پاسەکە کەوە');
    const dropPt=nearestOnRoute(ptD.lat,ptD.lon,best.name).pt;
    _boardMarker=pulseMarker(dropPt.lat,dropPt.lon,'#22c55e','بڵێ: دابەزین هەیە');
    drawRoutes(new Set(directs.map(r=>r.name)));
    showDirect({{lineO:best.name, labelO:best.name.replace(/_/g,' '),
      walkO_m:Math.round(best.km*1000), walkD_m:Math.round(walkD*1000),
      boardPt:best.boardPt, dropPt, alts}});
    return;
  }}

  // CASE 2: 1 transfer — road crossing
  let bestT=null, bestScore=Infinity;
  for(const rO of atO) for(const rD of atD) {{
    const app=APPROACH[rO.name]&&APPROACH[rO.name][rD.name];
    if(!app||app.gapKm>XFER_MAX_KM) continue;
    const score=rO.km+app.gapKm+rD.km;
    if(score<bestScore){{bestScore=score; bestT={{rO,rD,app}};}}
  }}
  if(bestT) {{
    const {{rO,rD,app}}=bestT;
    const sameRoad=app.gapKm<=XFER_SAME;
    drawRoutes(new Set([rO.name,rD.name]));
    _dropMarker=pulseMarker(app.ptA.lat,app.ptA.lon,'#fbbf24','بڵێ: دابەزین هەیە — شوێنی گۆڕین');
    _boardMarker=pulseMarker(app.ptB.lat,app.ptB.lon,'#60a5fa','سەر پاسی '+rD.name.replace(/_/g,' ')+' کەوە');
    if(!sameRoad && app.gapKm>0.01)
      _walkLine=L.polyline([[app.ptA.lat,app.ptA.lon],[app.ptB.lat,app.ptB.lon]],
        {{color:'#fbbf24',weight:2,dashArray:'6 5',opacity:0.8}}).addTo(map);
    showTransfer({{lineO:rO.name, labelO:rO.name.replace(/_/g,' '),
      lineD:rD.name, labelD:rD.name.replace(/_/g,' '),
      walkO_m:Math.round(rO.km*1000), walkD_m:Math.round(rD.km*1000),
      xferWalk_m:Math.round(app.gapKm*1000), sameRoad,
      dropPt:app.ptA, boardPt:app.ptB, viaBazaar:false}});
    return;
  }}

  // CASE 3: Via Bazaar hub
  const allEnds=[];
  for(const name of ROUTE_NAMES) {{
    const pts=ROUTE_PTS[name]; if(!pts.length) continue;
    allEnds.push({{pt:pts[0]}}); allEnds.push({{pt:pts[pts.length-1]}});
  }}
  const centLat=allEnds.reduce((s,e)=>s+e.pt.lat,0)/allEnds.length;
  const centLon=allEnds.reduce((s,e)=>s+e.pt.lon,0)/allEnds.length;
  function bazaarPt(name) {{
    const pts=ROUTE_PTS[name]; if(!pts.length) return null;
    const f=pts[0],l=pts[pts.length-1];
    return hav(f.lat,f.lon,centLat,centLon)<hav(l.lat,l.lon,centLat,centLon)?f:l;
  }}
  let bestB=null, bestBScore=Infinity;
  for(const rO of atO) {{
    const bzA=bazaarPt(rO.name); if(!bzA) continue;
    for(const rD of atD) {{
      if(rD.name===rO.name) continue;
      const bzB=bazaarPt(rD.name); if(!bzB) continue;
      const bw=hav(bzA.lat,bzA.lon,bzB.lat,bzB.lon);
      const score=rO.km+bw+rD.km;
      if(score<bestBScore){{bestBScore=score; bestB={{rO,rD,bzA,bzB,bazaarWalk:bw}};}}
    }}
  }}
  if(bestB) {{
    const {{rO,rD,bzA,bzB,bazaarWalk}}=bestB;
    drawRoutes(new Set([rO.name,rD.name]));
    _dropMarker=pulseMarker(rO.boardPt.lat,rO.boardPt.lon,'#22c55e','سەر پاسی '+rO.name.replace(/_/g,' ')+' کەوە');
    _boardMarker=pulseMarker(bzA.lat,bzA.lon,'#fbbf24','پاسەکە لە بازاڕ دەوەستێت بە خۆی');
    _walkLine=pulseMarker(bzB.lat,bzB.lon,'#60a5fa','سەر پاسی '+rD.name.replace(/_/g,' ')+' کەوە');
    if(bazaarWalk>0.01)
      _walkLine2=L.polyline([[bzA.lat,bzA.lon],[bzB.lat,bzB.lon]],
        {{color:'#fbbf24',weight:2,dashArray:'6 5',opacity:0.8}}).addTo(map);
    showTransfer({{lineO:rO.name, labelO:rO.name.replace(/_/g,' '),
      lineD:rD.name, labelD:rD.name.replace(/_/g,' '),
      walkO_m:Math.round(rO.km*1000), walkD_m:Math.round(rD.km*1000),
      xferWalk_m:Math.round(bazaarWalk*1000), sameRoad:bazaarWalk<=XFER_SAME,
      dropPt:bzA, boardPt:bzB, viaBazaar:true}});
    return;
  }}

  showErr('هیچ هێڵێک نەدۆزرایەوە.');
}}

// ── Pulse marker ──
function pulseMarker(lat, lon, color, tip) {{
  const icon = L.divIcon({{
    html:`<div style="width:18px;height:18px;border-radius:50%;background:${{color}};border:3px solid #fff;box-shadow:0 0 0 0 ${{color}}88;animation:ripple 1.4s infinite;"></div>`,
    iconSize:[18,18], iconAnchor:[9,9], className:''
  }});
  return L.marker([lat,lon],{{icon,zIndexOffset:900}})
    .bindTooltip(tip,{{permanent:false,direction:'top'}}).addTo(map);
}}
if(!document.getElementById('ripple-style')) {{
  const s=document.createElement('style'); s.id='ripple-style';
  s.textContent='@keyframes ripple{{0%{{box-shadow:0 0 0 0 rgba(255,255,255,.6);}}70%{{box-shadow:0 0 0 10px rgba(255,255,255,0);}}100%{{box-shadow:0 0 0 0 rgba(255,255,255,0);}}}}';
  document.head.appendChild(s);
}}

// ── Result renderers ──
function legRow(chips, label, detail) {{
  const chipHtml = chips.map(c => {{
    if(c.type==='walk') return `<span class="leg-chip walk">🚶 ${{c.label}}</span>`;
    if(c.type==='bus')  return `<span class="leg-chip bus" style="background:${{c.color}}22;border-color:${{c.color}}66;color:${{c.color}}">${{c.label}}</span>`;
    if(c.type==='xfer') return `<span class="leg-chip xfer">🔁</span>`;
    return '';
  }}).join('<span class="leg-arr">›</span>');
  return `<div class="leg" onclick="this.classList.toggle('open')">
    <div class="leg-top">
      <div class="leg-chips">${{chipHtml}}</div>
      <div class="leg-label">${{label}}</div>
      ${{detail ? '<span class="leg-caret">›</span>' : ''}}
    </div>
    ${{detail ? `<div class="leg-detail">${{detail}}</div>` : ''}}
  </div>`;
}}

function showDirect(r) {{
  const c = COLORS[r.lineO]||'#888';
  const altsHtml = r.alts.length
    ? ' · '+r.alts.map(a=>`<span style="color:${{COLORS[a.name]||'#888'}}">${{a.name.replace(/_/g,' ')}}</span>`).join(' / ')
    : '';
  document.getElementById('result-inner').innerHTML =
    `<div class="summary ok">✅ ڕاستەوخۆ — گۆڕین پێویست نیە</div><div class="legs">` +
    legRow([{{type:'walk',label:r.walkO_m+'م'}}],
      `بڕۆ بۆ شەقامی <strong style="color:${{c}}">${{r.labelO}}</strong>`+altsHtml,
      `پێویستە <strong>${{r.walkO_m}} م</strong> بە پێ بڕۆی — 🟢 خاڵی سەوز لەسەر نەخشەکە`) +
    legRow([{{type:'bus',label:r.labelO,color:c}}],
      `دەست ڕاگرە · سەر پاسەکە بکەوە · بڵێ <em>"دابەزین هەیە"</em>`,
      `شوفێر دەوەستێت ئەگەر ڕێگا هەبێت — 🟢 خاڵی سەوز = شوێنی دابەزین`) +
    legRow([{{type:'walk',label:r.walkD_m+'م'}}],
      `پێویستە <strong>${{r.walkD_m}} م</strong> بە پێ بڕۆی — گەیشتیت! 🎉`, null) +
    `</div>`;
  showCard();
}}

function showTransfer(r) {{
  const cO=COLORS[r.lineO]||'#888', cD=COLORS[r.lineD]||'#888';
  const xferDetail = r.sameRoad
    ? `هەمان شەقام — پیاسەکردن پێویست نیە`
    : `پێویستە <strong>${{r.xferWalk_m}} م</strong> بە پێ بڕۆی — 🟡 زەرد بۆ 🔵 شین لەسەر نەخشەکە`;
  const dropOffNote = r.viaBazaar
    ? `پاسەکە لە بازاڕ دەوەستێت بە خۆی — دابەزە`
    : `بڵێ: <em>"دابەزین هەیە"</em> لە شەقامی ${{r.labelD}} — 🟡 خاڵی زەرد`;
  const header = r.viaBazaar ? `🔁 یەک گۆڕین — لە ڕێگای بازاڕ` : `🔁 یەک گۆڕین — لە کەنارەی شەقام`;
  document.getElementById('result-inner').innerHTML =
    `<div class="summary xfr">${{header}}</div><div class="legs">` +
    legRow([{{type:'walk',label:r.walkO_m+'م'}}],
      `بڕۆ بۆ شەقامی <strong style="color:${{cO}}">${{r.labelO}}</strong>`,
      `پێویستە <strong>${{r.walkO_m}} م</strong> بە پێ بڕۆی — 🟢 خاڵی سەوز`) +
    legRow([{{type:'bus',label:r.labelO,color:cO}}],
      `دەست ڕاگرە · سەر پاسەکە بکەوە · ${{dropOffNote}}`,
      `سەر پاسەکە بکەوە بە تاوەکو خاڵی زەرد`) +
    legRow([{{type:'xfer'}},{{type:'walk',label:r.xferWalk_m+'م'}}],
      xferDetail,
      r.sameRoad ? `هەمان شەقام` : `🟡 دابەزە — 🔵 خاڵی شین = شوێنی سەرکەوتن لە ${{r.labelD}}`) +
    legRow([{{type:'bus',label:r.labelD,color:cD}}],
      `دەست ڕاگرە · سەر پاسی <strong style="color:${{cD}}">${{r.labelD}}</strong> بکەوە · بڵێ <em>"دابەزین هەیە"</em>`,
      `سەر پاسەکە بکەوە بە تاوەکو مەوداکەت`) +
    legRow([{{type:'walk',label:r.walkD_m+'م'}}],
      `پێویستە <strong>${{r.walkD_m}} م</strong> بە پێ بڕۆی — گەیشتیت! 🎉`, null) +
    `</div>`;
  showCard();
}}

function showErr(msg) {{
  document.getElementById('result-inner').innerHTML=`<div class="summary err">⚠️ ${{msg}}</div>`;
  showCard();
}}

// ── Result card show/hide/mode ──
let _resultMode = 'float';
function showCard() {{
  const rc  = document.getElementById('result-card');
  const btn = document.getElementById('result-toggle');
  rc.classList.remove('bottom'); rc.classList.add('float');
  _resultMode = 'float';
  btn.textContent = '▤ خوارەوە';
  rc.classList.add('show');
  btn.style.display = 'flex';
}}
function hideResult() {{
  clearXferLayers();
  const rc = document.getElementById('result-card');
  rc.classList.remove('show');
  document.getElementById('result-toggle').style.display = 'none';
  drawRoutes(null);
}}
function cycleResultMode() {{
  const rc  = document.getElementById('result-card');
  const btn = document.getElementById('result-toggle');
  rc.classList.remove(_resultMode);
  _resultMode = (_resultMode==='float') ? 'bottom' : 'float';
  rc.classList.add(_resultMode);
  rc.classList.add('show');
  btn.textContent = _resultMode==='float' ? '▤ خوارەوە' : '⊟ سەرەوە';
}}

// ── Map click picking ──
let mode = '';
function toggleMode(m) {{
  mode = (mode===m) ? '' : m;
  document.getElementById('btn-o').classList.toggle('on', mode==='origin');
  document.getElementById('btn-d').classList.toggle('on', mode==='dest');
  map.getContainer().classList.toggle('picking', mode!=='');
}}

map.on('click', e => {{
  if(!mode) return;
  const lat=e.latlng.lat, lon=e.latlng.lng;
  const fmt=lat.toFixed(6)+', '+lon.toFixed(6);
  if(mode==='origin') {{
    ptO={{lat,lon}}; placeO(lat,lon);
    document.getElementById('inp-o').value=fmt;
    mode='dest';
    document.getElementById('btn-o').classList.remove('on');
    document.getElementById('btn-d').classList.add('on');
  }} else {{
    ptD={{lat,lon}}; placeD(lat,lon);
    document.getElementById('inp-d').value=fmt;
    mode='';
    document.getElementById('btn-d').classList.remove('on');
    map.getContainer().classList.remove('picking');
  }}
  compute();
}});

// ── Manual coordinate input ──
function parseCoord(raw) {{
  const s=raw.trim().replace(/\s*,\s*/g,',');
  const parts=s.includes(',')?s.split(','):s.split(/\s+/);
  if(parts.length<2) return null;
  const la=parseFloat(parts[0]), lo=parseFloat(parts[1]);
  return (isNaN(la)||isNaN(lo)) ? null : {{lat:la,lon:lo}};
}}
function onCoordInput(which, val) {{
  const c=parseCoord(val); if(!c) return;
  if(which==='origin') {{
    ptO=c; placeO(c.lat,c.lon);
    map.setView([c.lat,c.lon], map.getZoom()<14?14:map.getZoom());
  }} else {{
    ptD=c; placeD(c.lat,c.lon);
    map.setView([c.lat,c.lon], map.getZoom()<14?14:map.getZoom());
  }}
  compute();
}}

// ── Clear / reset ──
let _gpsCircle = null;
function clearPt(which) {{
  if(which==='origin') {{
    ptO=null;
    if(mO){{map.removeLayer(mO); mO=null;}}
    if(_gpsCircle){{map.removeLayer(_gpsCircle); _gpsCircle=null;}}
    document.getElementById('inp-o').value='';
  }} else {{
    ptD=null;
    if(mD){{map.removeLayer(mD); mD=null;}}
    document.getElementById('inp-d').value='';
  }}
  hideResult();
}}
function resetAll() {{
  clearPt('origin'); clearPt('dest');
  mode='';
  document.getElementById('btn-o').classList.remove('on');
  document.getElementById('btn-d').classList.remove('on');
  map.getContainer().classList.remove('picking');
}}

// ── GPS Tracking ──
function useMyLocation() {{
  const btn = document.getElementById('recenter-btn');
  if(!navigator.geolocation) {{
    alert('بەدبەختانە، ئەم براوزەرە شوێننیشاندەر پشتگیری ناکات');
    return;
  }}
  btn.classList.add('locating');
  navigator.geolocation.getCurrentPosition(
    pos => {{
      const lat=pos.coords.latitude, lon=pos.coords.longitude;
      ptO={{lat,lon}}; placeO(lat,lon);
      document.getElementById('inp-o').value=lat.toFixed(6)+', '+lon.toFixed(6);
      map.setView([lat,lon], 16);
      if(_gpsCircle) map.removeLayer(_gpsCircle);
      _gpsCircle=L.circle([lat,lon],{{
        radius:pos.coords.accuracy, color:'#00E5FF', fillColor:'#00E5FF',
        fillOpacity:0.08, weight:1.5, dashArray:'4 4'
      }}).addTo(map);
      btn.classList.remove('locating');
      mode='dest';
      document.getElementById('btn-o').classList.remove('on');
      document.getElementById('btn-d').classList.add('on');
      compute();
    }},
    err => {{
      btn.classList.remove('locating');
      alert('هەڵەیەک لە دۆزینەوەی شوێنەکەت ڕوویدا');
    }},
    {{enableHighAccuracy:true, timeout:10000, maximumAge:30000}}
  );
}}

// ── Resize ──
function resize() {{
  window.parent.postMessage({{type:'resize_map', height:window.innerHeight||900}},'*');
}}
resize();
window.addEventListener('resize', resize);
</script>
</body>
</html>"""


def main():
    try:
        routes_geojson = load_routes(ROUTES_FILE)
    except Exception as e:
        st.error(f"Failed to load route file: {e}"); return

    live_buses = fetch_live_buses()
    supa_url = st.secrets.get("SUPABASE_URL", "")      if hasattr(st, "secrets") else ""
    supa_key = st.secrets.get("SUPABASE_ANON_KEY", "") if hasattr(st, "secrets") else ""

    components.html(build_map_html(routes_geojson, live_buses, supa_url, supa_key),
                    height=900, scrolling=False)

    components.html("""<script>
    window.addEventListener('message', function(e) {
        if(!e.data || e.data.type !== 'resize_map') return;
        document.querySelectorAll('iframe').forEach(function(f) {
            if(parseInt(f.getAttribute('height')||0) > 100) {
                f.style.height = e.data.height + 'px';
                f.style.minHeight = e.data.height + 'px';
                f.setAttribute('height', e.data.height);
            }
        });
    });
    </script>""", height=0)


if __name__ == "__main__":
    main()
