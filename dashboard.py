import json
from pathlib import Path

import pandas as pd
import streamlit as st
import plotly.express as px

from azure.storage.blob import BlobServiceClient
from streamlit_autorefresh import st_autorefresh

# ------------------------------------------------------------
# 1. Page configuration
# ------------------------------------------------------------
st.set_page_config(
    page_title="GeoEther | Air Quality Intelligence",
    layout="wide",
    initial_sidebar_state="collapsed",   # navigation and filters now live in the page itself
)

# Refresh every 60 seconds. New readings require the Azure pipeline to be running.
st_autorefresh(interval=60_000, key="azure_telemetry_autorefresh")

# ------------------------------------------------------------
# 2. Theme
# ------------------------------------------------------------
INK, MUTED, GRID = "#17233C", "#6B7689", "#E6EAF1"
ACCENT = "#2F6BFF"
PURPLE, GREEN, AMBER, RED, BLUE = "#625DF5", "#16B887", "#E9A23B", "#E35D6A", "#3397E8"
CHART_FONT = "Poppins, DM Sans, sans-serif"

# Device colours are deliberately distinct from the status colours (green / amber / red)
# so a device colour is never mistaken for a status.
DEVICE_COLORS = ["#2563EB", "#7C3AED", "#0891B2", "#C026D3", "#475569",
                 "#4F46E5", "#0D9488", "#BE185D", "#65A30D", "#1E3A8A"]

# Background of the "System status" KPI card for each state.
STATUS_TONE = {"NORMAL": "#12B76A", "WARNING": "#F5A524", "ALERT": "#FF6B1A", "NO DATA": "#98A2B3"}

AQ_NORMAL, AQ_ALERT, AQ_HIGH = 50, 100, 80   # demo thresholds

# Feather icons (MIT licence) used inside the KPI badges and the top bar.
ICON_PATHS = {
    "wind": '<path d="M9.59 4.59A2 2 0 1 1 11 8H2m10.59 11.41A2 2 0 1 0 14 16H2m15.73-8.27A2.5 2.5 0 1 1 19.5 12H2"/>',
    "thermometer": '<path d="M14 14.76V3.5a2.5 2.5 0 0 0-5 0v11.26a4.5 4.5 0 1 0 5 0z"/>',
    "droplet": '<path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z"/>',
    "cpu": '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/>'
           '<path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3"/>',
    "activity": '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
}
LOGO = ('<svg viewBox="0 0 24 24" width="26" height="26"><path d="M12 2l9 5v10l-9 5-9-5V7z" fill="#2F6BFF"/>'
        '<path d="M12 7l4.5 2.5v5L12 17l-4.5-2.5v-5z" fill="#fff"/></svg>')


def load_css(filename: str = "style.css") -> None:
    try:
        css = Path(__file__).with_name(filename).read_text(encoding="utf-8")
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    except OSError:
        st.warning(f"Stylesheet '{filename}' not found next to the app file.")


load_css()

REQUIRED_COLUMNS = ["device_id", "temperature", "humidity", "air_quality", "event_time"]
OPTIONAL_COLUMNS = ["location", "city", "device_name"]
ALL_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS


# ------------------------------------------------------------
# 3. Data loading
# ------------------------------------------------------------
def parse_blob_content(content: str) -> list[dict]:
    content = content.strip()
    if not content:
        return []
    try:
        parsed = json.loads(content)
        if isinstance(parsed, list):
            return [x for x in parsed if isinstance(x, dict)]
        if isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        pass
    records = []
    for line in content.splitlines():
        try:
            item = json.loads(line.strip())
            if isinstance(item, dict):
                records.append(item)
        except (json.JSONDecodeError, TypeError):
            continue
    return records


@st.cache_data(ttl=55, show_spinner=False)
def fetch_azure_telemetry() -> tuple[pd.DataFrame, str | None, int]:
    """Load recent JSON blobs from the existing Azure Blob Storage configuration."""
    try:
        connection_string = st.secrets["AZURE_STORAGE_CONNECTION_STRING"]
        container_name = st.secrets["AZURE_CONTAINER_NAME"]
        prefix = st.secrets.get("AZURE_BLOB_PREFIX", "")
        service = BlobServiceClient.from_connection_string(connection_string)
        container = service.get_container_client(container_name)
        blobs = [b for b in container.list_blobs(name_starts_with=prefix or None)
                 if b.name.lower().endswith(".json")]
        blobs.sort(key=lambda b: b.last_modified or pd.Timestamp.min.tz_localize("UTC"), reverse=True)
        records = []
        for blob in blobs[:30]:
            try:
                records.extend(parse_blob_content(
                    container.download_blob(blob.name).readall().decode("utf-8-sig")))
            except Exception:
                continue
        if not records:
            return pd.DataFrame(columns=ALL_COLUMNS), None, min(len(blobs), 30)
        data = pd.DataFrame(records)
        for col in ALL_COLUMNS:
            if col not in data.columns:
                data[col] = pd.NA
        data = data[ALL_COLUMNS].copy()
        data["device_id"] = data["device_id"].astype("string")
        for col in ["temperature", "humidity", "air_quality"]:
            data[col] = pd.to_numeric(data[col], errors="coerce")
        data["event_time"] = pd.to_datetime(data["event_time"], errors="coerce", utc=True)
        data = data.dropna(subset=["device_id", "event_time"])
        data = data[data["device_id"].str.strip().ne("")]
        data = data.drop_duplicates(subset=["device_id", "event_time"], keep="last")
        return data.sort_values("event_time"), None, min(len(blobs), 30)
    except KeyError as exc:
        return pd.DataFrame(columns=ALL_COLUMNS), f"Missing Streamlit secret: {exc}. Configure Azure secrets.", 0
    except Exception as exc:
        return pd.DataFrame(columns=ALL_COLUMNS), f"Could not read Azure Blob Storage: {exc}", 0


# ------------------------------------------------------------
# 4. Helpers
# ------------------------------------------------------------
def fmt(value, suffix="", digits=1):
    if value is None or pd.isna(value):
        return "—"
    return f"{value:,.{digits}f}{suffix}"


def aq_state(v):
    if v is None or pd.isna(v):
        return "NO DATA"
    return "NORMAL" if v <= AQ_NORMAL else ("WARNING" if v <= AQ_ALERT else "ALERT")


def temp_state(v):
    if v is None or pd.isna(v):
        return "NO DATA"
    return "NORMAL" if v < 35 else ("WARNING" if v < 40 else "ALERT")


def overall_state(aq, temp):
    states = [aq_state(aq), temp_state(temp)]
    if "ALERT" in states:
        return "ALERT"
    if "WARNING" in states:
        return "WARNING"
    if all(x == "NO DATA" for x in states):
        return "NO DATA"
    return "NORMAL"


def state_class(s):
    return "status-" + s.lower().replace(" ", "-")


def icon(name: str) -> str:
    return ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round">{ICON_PATHS[name]}</svg>')


def kpi(label, value, note, icon_name, variant="", tone=None, value_class=""):
    """KPI card. variant: '' (white), 'primary' (accent fill) or 'status' (fill follows system status)."""
    style = f' style="--tone:{tone}"' if tone else ""
    st.markdown(
        f'<div class="kpi {variant}"{style}>'
        f'<div class="kpi-top"><div class="kpi-label">{label}</div>'
        f'<span class="kpi-icon">{icon(icon_name)}</span></div>'
        f'<div class="kpi-value {value_class}">{value}</div><div class="kpi-note">{note}</div></div>',
        unsafe_allow_html=True)


def heading(title, note=""):
    st.markdown(f'<div class="section-title">{title}</div><div class="section-note">{note}</div>',
                unsafe_allow_html=True)


def card(key: str):
    """Light panel that holds a chart or table (styled in style.css via the key-based class)."""
    return st.container(key=f"card-{key}")


def panel(key: str, title: str, note: str = ""):
    """Section title above a panel, as in the reference design."""
    heading(title, note)
    return card(key)


def style_plot(fig, height=280, unified=True):
    fig.update_layout(
        height=height, margin=dict(l=4, r=4, t=8, b=4), showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=CHART_FONT, color=INK, size=11),
        hovermode="x unified" if unified else "closest",
        hoverlabel=dict(bgcolor="white", font_size=12),
    )
    fig.update_xaxes(title=None, showgrid=False, zeroline=False, linecolor=GRID)
    fig.update_yaxes(title=None, showgrid=True, gridcolor="#E4E9F1", zeroline=False)
    return fig


def show(fig):
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def build_registry(data):
    """One stable colour + label + place per device, used by every chart and the legend."""
    registry, used = {}, set()
    if data.empty:
        return registry
    latest = data.sort_values("event_time").groupby("device_id").tail(1).sort_values("device_id")
    for i, (_, r) in enumerate(latest.iterrows()):
        did = str(r["device_id"])
        name = str(r["device_name"]).strip() if pd.notna(r["device_name"]) and str(r["device_name"]).strip() else did
        if name in used:
            name = f"{name} ({did})"
        used.add(name)
        place = next((str(r[c]) for c in ["location", "city"] if pd.notna(r[c]) and str(r[c]).strip()), "")
        registry[did] = {"label": name, "place": place, "color": DEVICE_COLORS[i % len(DEVICE_COLORS)]}
    return registry


def header_html(title, subtitle, pill=""):
    return (f'<div class="page-title">{title}</div>'
            f'<div class="subtitle">{subtitle}{pill}</div>')


# ------------------------------------------------------------
# 5. Load data and device registry
# ------------------------------------------------------------
df, load_error, blob_count = fetch_azure_telemetry()
REGISTRY = build_registry(df)
COLOR_MAP = {v["label"]: v["color"] for v in REGISTRY.values()}
df["label"] = df["device_id"].astype(str).map({k: v["label"] for k, v in REGISTRY.items()})
devices = sorted(df["device_id"].dropna().astype(str).unique().tolist())

if load_error:
    PILL = '<span class="pill bad"><i></i>Connection needs attention</span>'
elif df.empty:
    PILL = '<span class="pill wait"><i></i>Connected, awaiting records</span>'
else:
    PILL = '<span class="pill ok"><i></i>Azure Blob Storage · refreshes every 60 s</span>'

# ------------------------------------------------------------
# 6. Top navigation bar
# ------------------------------------------------------------
with st.container(key="topbar"):
    nav_brand, nav_tabs, nav_meta = st.columns([1.2, 2, 1.2], vertical_alignment="center")
    with nav_brand:
        st.markdown(f'<div class="nav-brand">{LOGO}<span>GEOETHER</span></div>', unsafe_allow_html=True)
    with nav_tabs:
        page = st.radio("Workspace", ["Dashboard", "Azure Pipeline"], horizontal=True,
                        label_visibility="collapsed")
    with nav_meta:
        st.markdown('<div class="nav-meta"><span>DSA</span><b>441</b></div>', unsafe_allow_html=True)

# ------------------------------------------------------------
# 7. Page: Azure pipeline & workflow
# ------------------------------------------------------------
if page == "Azure Pipeline":
    st.markdown(header_html("Azure Pipeline & Workflow",
                            "How telemetry moves from IoT devices to the live monitoring experience.", PILL),
                unsafe_allow_html=True)
    st.write("")
    stages = [
        ("1", "IoT devices", "Python simulator / registered sensors", "Temperature, humidity, air quality, timestamp", PURPLE, "#EDEBFF"),
        ("2", "Azure IoT Hub", "Device-to-cloud ingestion", "Receives device telemetry", BLUE, "#E1F5FF"),
        ("3", "Stream Analytics", "Streaming query and routing", "Selects, filters or aggregates events", GREEN, "#E1FAF1"),
        ("4", "Blob Storage", "JSON persistence", "Stores processed telemetry", AMBER, "#FFF3D9"),
        ("5", "GeoEther dashboard", "Streamlit visualization", "Loads blobs, computes views, renders insights", RED, "#FCE7EC")]
    cols = st.columns(5, gap="small")
    for col, (num, title, sub, detail, color, tint) in zip(cols, stages):
        with col:
            st.markdown(
                f'<div class="kpi" style="min-height:190px"><span class="badge" style="background:{tint};color:{color}">{num}</span>'
                f'<div style="font-weight:700;margin:.3rem 0 .5rem;color:{INK}">{title}</div>'
                f'<div style="font-size:.76rem;color:{color};font-weight:600">{sub}</div>'
                f'<div class="kpi-note" style="margin-top:.6rem">{detail}</div></div>', unsafe_allow_html=True)
    st.write("")
    c1, c2, c3, c4 = st.columns(4)
    latest_event = df["event_time"].max().strftime("%d %b, %H:%M UTC") if not df.empty else "—"
    for col, label, value in zip(
            [c1, c2, c3, c4],
            ["Records loaded", "JSON blobs scanned", "Devices detected", "Latest event"],
            [f"{len(df):,}", f"{blob_count:,}", f"{len(devices):,}", latest_event]):
        with col:
            st.markdown(f'<div class="kpi" style="min-height:90px"><div class="kpi-label">{label}</div>'
                        f'<div class="kpi-value" style="font-size:1.35rem;margin-top:.3rem">{value}</div></div>',
                        unsafe_allow_html=True)
    st.markdown("### Stream Analytics query patterns")
    t1, t2, t3 = st.tabs(["Base telemetry", "Condition filter", "One-minute aggregate"])
    with t1:
        st.caption("Forwards each event's core fields to Blob Storage.")
        st.code("""SELECT device_id, temperature, humidity, air_quality,
       System.Timestamp() AS event_time
INTO BlobOutput
FROM [thailand-air-iothub]""", language="sql")
    with t2:
        st.caption("Example condition: air_quality ≥ 80. The dashboard also derives a local view from loaded base telemetry.")
        st.code("""SELECT device_id, temperature, humidity, air_quality,
       System.Timestamp() AS event_time
INTO ConditionOutput
FROM [thailand-air-iothub]
WHERE air_quality >= 80""", language="sql")
    with t3:
        st.caption("Groups incoming events by device and one-minute tumbling window.")
        st.code("""SELECT device_id, AVG(air_quality) AS avg_air_quality,
       MAX(air_quality) AS max_air_quality,
       AVG(temperature) AS avg_temperature
INTO AggregateOutput
FROM [thailand-air-iothub]
GROUP BY device_id, TumblingWindow(minute, 1)""", language="sql")
    st.info("The monitoring page calculates condition and one-minute aggregate views locally from loaded base telemetry. "
            "If you configure dedicated Azure outputs, keep their schemas or blob prefixes separate to avoid mixing record types.")
    with st.expander("Schema, thresholds & operating notes"):
        st.markdown("""- **Required fields:** `device_id`, `temperature`, `humidity`, `air_quality`, `event_time`.
- **Optional label fields:** `location`, `city`, `device_name`. They only change how devices are named in the legend and records table.
- **Refresh:** reads recent JSON blobs every 60 seconds; refreshing does not generate telemetry.
- **Demo thresholds:** air quality ≤ 50 normal, 51–100 warning, > 100 alert; temperature < 35°C normal, 35–<40°C warning, ≥40°C alert. These are not official health or environmental standards.
- **Security:** keep the Azure Storage connection string in Streamlit Secrets, never in source control.""")
    st.stop()

# ------------------------------------------------------------
# 8. Page: Live monitoring
# ------------------------------------------------------------
head_left, head_right = st.columns([5, 1], vertical_alignment="center")
with head_left:
    st.markdown(header_html("Air Quality Monitoring Dashboard",
                            "Recent readings, trends and device health", PILL), unsafe_allow_html=True)

selected = devices
with head_right:
    if devices:
        with st.popover("Filter"):
            selected = st.multiselect(
                "Devices", devices, default=devices,
                format_func=lambda d: REGISTRY[d]["label"],
                help="KPIs, charts, insights and records follow this filter.")

st.write("")
if load_error:
    st.error(load_error)
if df.empty:
    st.warning("No telemetry loaded. Check Azure secrets, the Blob Storage container, Stream Analytics output, and the device simulator.")
    st.stop()
if not selected:
    st.info("Select at least one device in the Filter menu.")
    st.stop()

data = df[df["device_id"].astype(str).isin(selected)].copy()
latest_devices = data.sort_values("event_time").groupby("device_id", as_index=False).tail(1)
last_seen = data["event_time"].max()

# Network-level values are the average of each device's latest reading
aq_now = latest_devices["air_quality"].mean()
temp_now = latest_devices["temperature"].mean()
hum_now = latest_devices["humidity"].mean()
aq_peak = data["air_quality"].max()

device_states = [overall_state(r["air_quality"], r["temperature"]) for _, r in latest_devices.iterrows()]
if "ALERT" in device_states:
    status = "ALERT"
elif "WARNING" in device_states:
    status = "WARNING"
elif device_states and all(x == "NO DATA" for x in device_states):
    status = "NO DATA"
else:
    status = "NORMAL"

# ---- KPIs ----
cols = st.columns(5, gap="medium")
with cols[0]:
    kpi("Air quality", fmt(aq_now, digits=0), f"Average of latest readings · peak {fmt(aq_peak, digits=0)}",
        "wind", "primary", ACCENT)
with cols[1]:
    kpi("Temperature", fmt(temp_now, " °C"), f"Period average {fmt(data['temperature'].mean(), ' °C')}", "thermometer")
with cols[2]:
    kpi("Humidity", fmt(hum_now, " %"), f"Period average {fmt(data['humidity'].mean(), ' %')}", "droplet",
        value_class="accent")
with cols[3]:
    kpi("Devices", f"{len(selected)} / {len(devices)}", f"{len(data):,} readings loaded", "cpu")
with cols[4]:
    kpi("System status", status.title(), f"Updated {last_seen.strftime('%H:%M:%S')} UTC", "activity",
        "status", STATUS_TONE[status])

# ---- Device legend (colours match every chart; dimmed = filtered out) ----
latest_all = df.sort_values("event_time").groupby("device_id").tail(1).sort_values("device_id")
chips = []
for _, r in latest_all.iterrows():
    did = str(r["device_id"])
    info = REGISTRY[did]
    dim = "" if did in selected else " dim"
    chips.append(f'<div class="chip{dim}"><span class="chip-dot" style="background:{info["color"]}"></span>'
                 f'<span class="chip-name">{info["label"]}</span><b>{fmt(r["air_quality"], digits=0)}</b></div>')
st.markdown(f'<div class="chips">{"".join(chips)}</div>', unsafe_allow_html=True)

# ---- Row 1: air quality trend + latest by device ----
left, right = st.columns([1.6, 1], gap="large")
with left:
    with panel("aq-trend", "Air quality over time",
               "Shaded bands show normal (≤ 50), warning (≤ 100) and alert (> 100) ranges."):
        chart = data.dropna(subset=["air_quality"]).sort_values("event_time")
        if not chart.empty:
            top = max(120.0, float(chart["air_quality"].max()) * 1.1)
            fig = px.line(chart, x="event_time", y="air_quality", color="label", color_discrete_map=COLOR_MAP)
            fig.update_traces(line=dict(width=2))
            for lo, hi, col, name in [(0, AQ_NORMAL, GREEN, "Normal"), (AQ_NORMAL, AQ_ALERT, AMBER, "Warning"), (AQ_ALERT, top, RED, "Alert")]:
                fig.add_hrect(y0=lo, y1=hi, fillcolor=col, opacity=.07, line_width=0, layer="below",
                              annotation_text=name, annotation_position="top left",
                              annotation_font=dict(size=10, color=col))
            fig.update_yaxes(range=[0, top])
            show(style_plot(fig, 300))
        else:
            st.info("No air-quality readings for this filter.")
with right:
    with panel("aq-latest", "Latest air quality by device", "Dotted lines mark 50 and 100."):
        lat = latest_devices.dropna(subset=["air_quality"]).sort_values("air_quality")
        if not lat.empty:
            fig = px.bar(lat, x="air_quality", y="label", orientation="h", color="label",
                         color_discrete_map=COLOR_MAP, text_auto=".0f")
            fig.update_traces(textposition="outside", cliponaxis=False)
            for x in (AQ_NORMAL, AQ_ALERT):
                fig.add_vline(x=x, line_dash="dot", line_color="#A0AEC0")
            fig.update_xaxes(range=[0, max(120.0, float(lat["air_quality"].max()) * 1.15)],
                             showgrid=False)
            fig.update_yaxes(showgrid=False)
            show(style_plot(fig, 300, unified=False))
        else:
            st.info("No air-quality readings for this filter.")

st.write("")

# ---- Row 2: temperature + humidity ----
left, right = st.columns(2, gap="large")
with left:
    with panel("temp", "Temperature", "Degrees Celsius · dotted lines mark 35 °C (warning) and 40 °C (alert)."):
        chart = data.dropna(subset=["temperature"]).sort_values("event_time")
        if not chart.empty:
            tmin, tmax = float(chart["temperature"].min()), float(chart["temperature"].max())
            hi = max(tmax + 2, 36.0)
            fig = px.line(chart, x="event_time", y="temperature", color="label", color_discrete_map=COLOR_MAP)
            fig.update_traces(line=dict(width=2))
            fig.add_hline(y=35, line_dash="dot", line_color=AMBER)
            if hi >= 40:
                fig.add_hline(y=40, line_dash="dot", line_color=RED)
            fig.update_yaxes(range=[min(tmin - 2, 34.0), hi])
            show(style_plot(fig, 260))
        else:
            st.info("No temperature readings for this filter.")
with right:
    with panel("humidity", "Humidity", "Relative humidity in percent."):
        chart = data.dropna(subset=["humidity"]).sort_values("event_time")
        if not chart.empty:
            fig = px.line(chart, x="event_time", y="humidity", color="label", color_discrete_map=COLOR_MAP)
            fig.update_traces(line=dict(width=2))
            fig.update_yaxes(range=[max(0.0, float(chart["humidity"].min()) - 5),
                                    min(100.0, float(chart["humidity"].max()) + 5)])
            show(style_plot(fig, 260))
        else:
            st.info("No humidity readings for this filter.")

st.write("")

# ---- Local condition + one-minute aggregation ----
condition = data.dropna(subset=["air_quality"]).query(f"air_quality >= {AQ_HIGH}").sort_values("event_time", ascending=False).copy()
agg_source = data.dropna(subset=["device_id", "event_time", "air_quality"]).copy()
if not agg_source.empty:
    agg_source["window_start"] = agg_source["event_time"].dt.floor("1min")
    aggregation = (agg_source.groupby(["device_id", "label", "window_start"], as_index=False)
                   .agg(avg_air_quality=("air_quality", "mean"), max_air_quality=("air_quality", "max"),
                        avg_temperature=("temperature", "mean"), readings=("air_quality", "count"))
                   .sort_values("window_start"))
else:
    aggregation = pd.DataFrame()

# ---- Row 3: exceedances + one-minute averages ----
left, right = st.columns([1, 1.4], gap="large")
with left:
    with panel("exceed", "High-reading share by device",
               f"Share of readings at or above {AQ_HIGH} · {len(condition):,} of {len(data):,} readings overall."):
        valid = data.dropna(subset=["air_quality"])
        if not valid.empty:
            exc = (valid.assign(hit=valid["air_quality"] >= AQ_HIGH)
                   .groupby("label", as_index=False).agg(hits=("hit", "sum"), total=("hit", "size")))
            exc["share"] = exc["hits"] / exc["total"] * 100
            exc["text"] = exc.apply(lambda r: f"{r['share']:.0f}%  ({int(r['hits'])} of {int(r['total'])})", axis=1)
            fig = px.bar(exc.sort_values("share"), x="share", y="label", orientation="h", color="label",
                         color_discrete_map=COLOR_MAP, text="text")
            fig.update_traces(textposition="outside", cliponaxis=False)
            fig.update_xaxes(range=[0, max(15.0, float(exc["share"].max()) * 1.6)], showgrid=False, ticksuffix="%")
            fig.update_yaxes(showgrid=False)
            show(style_plot(fig, 260, unified=False))
        else:
            st.info("No air-quality readings for this filter.")
with right:
    with panel("agg", "One-minute average air quality",
               f"Last 30 windows per device · dotted line marks the {AQ_HIGH} condition threshold."):
        if not aggregation.empty:
            recent = aggregation.groupby("device_id").tail(30)
            fig = px.line(recent, x="window_start", y="avg_air_quality", color="label", markers=True,
                          color_discrete_map=COLOR_MAP,
                          hover_data={"max_air_quality": ":.1f", "readings": True})
            fig.update_traces(line=dict(width=2), marker=dict(size=5))
            fig.add_hline(y=AQ_HIGH, line_dash="dot", line_color=RED)
            show(style_plot(fig, 260))
        else:
            st.info("No valid telemetry for one-minute aggregation.")

st.write("")

# ---- Insights (rule-based) ----
if status == "ALERT":
    insight1 = ("Alert", "Alert-level reading", "At least one latest air-quality or temperature value crossed the alert threshold.", RED)
elif status == "WARNING":
    insight1 = ("Warning", "Review warning readings", "At least one latest value is within a warning range.", AMBER)
elif status == "NORMAL":
    insight1 = ("Normal", "Readings within range", "Latest air-quality and temperature readings are below warning thresholds.", GREEN)
else:
    insight1 = ("No data", "Insufficient readings", "Valid air-quality and temperature values are not available.", MUTED)

if not condition.empty:
    row = condition.iloc[0]
    insight2 = ("High readings", f"{len(condition)} record(s) at or above {AQ_HIGH}",
                f"Most recent: {row['label']} at {row['event_time'].strftime('%d %b %H:%M UTC')}, air quality {row['air_quality']:.1f}.", RED)
else:
    insight2 = ("Clear", "No high-condition records", f"No loaded reading reaches {AQ_HIGH} in this filter.", GREEN)

age = (pd.Timestamp.now(tz="UTC") - last_seen).total_seconds() / 60 if pd.notna(last_seen) else None
if age is None:
    insight3 = ("No data", "Freshness unavailable", "No valid event timestamp is available.", MUTED)
elif age <= 3:
    insight3 = ("Fresh", "Telemetry looks recent", f"Newest event is about {max(age, 0):.1f} minute(s) old.", GREEN)
else:
    insight3 = ("Stale", "Check telemetry freshness", f"Newest event is about {age:.0f} minutes old. Confirm the simulator and Azure outputs.", AMBER)

# ---- Row 4: attention points (full width, one column per insight) ----
with panel("insights", "Attention points", "Rule-based reading of the selected telemetry."):
    insight_cols = st.columns(3, gap="medium")
    for col, (tag, title, body, color) in zip(insight_cols, [insight1, insight2, insight3]):
        with col:
            st.markdown(f'<div class="insight"><div class="insight-tag" style="color:{color}">{tag}</div>'
                        f'<b>{title}</b><p>{body}</p></div>', unsafe_allow_html=True)
    st.caption("Demo thresholds, not official environmental or medical standards. Air quality may be simulated.")

st.write("")

# ---- Records table ----
with panel("records", "Latest Sensor Records", "Most recent events first, filtered to the selected devices."):
    limit = st.selectbox("Rows to display", [25, 50, 100, 250], index=1, label_visibility="collapsed")
    records = data.sort_values("event_time", ascending=False).head(limit).copy()
    records["event_time"] = records["event_time"].dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    records = records.rename(columns={"label": "Device", "device_id": "Device ID", "location": "Location", "city": "City",
                                      "temperature": "Temperature (°C)", "humidity": "Humidity (%)",
                                      "air_quality": "Air quality", "event_time": "Event time"})
    visible = [c for c in ["Event time", "Device", "Device ID", "Location", "City", "Air quality",
                           "Temperature (°C)", "Humidity (%)"]
               if c in records.columns and records[c].notna().any()]
    st.dataframe(records[visible], use_container_width=True, hide_index=True, height=340)
    c1, c2 = st.columns([1, 3])
    with c1:
        st.download_button("Export CSV", records[visible].to_csv(index=False).encode("utf-8"),
                           "geoether_sensor_records.csv", "text/csv", use_container_width=True)
    with c2:
        st.markdown(f'<div class="muted" style="padding:.55rem 0">Showing {len(records):,} of {len(data):,} records · '
                    f'scanned {blob_count} JSON blobs</div>', unsafe_allow_html=True)

st.markdown('<div class="muted" style="text-align:center;padding:1.5rem 0">GeoEther · live telemetry monitoring · refreshes every 60 seconds</div>',
            unsafe_allow_html=True)
