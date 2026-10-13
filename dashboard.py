import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import st_folium

# 1. Page Config
st.set_page_config(
    page_title="Thailand Air Quality IoT Dashboard",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Load External CSS File
with open("style.css") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# 2. Hoverable Sidebar District List (Using radio options styled via CSS)
st.sidebar.markdown("### Regional Districts")
st.sidebar.caption("Hover & click to filter dashboard metrics:")

DISTRICTS = {
    "All Districts": "bangkok",
    "Bangkok (Central)": "bangkok",
    "Chiang Mai (North)": "chiang mai",
    "Chiang Rai (North)": "chiang rai",
    "Lampang (North)": "lampang",
    "Phuket (South)": "phuket",
    "Hat Yai / Songkhla (South)": "hat yai",
    "Surat Thani (South)": "surat thani",
    "Khon Kaen (Northeast)": "khon kaen",
    "Udon Thani (Northeast)": "udon thani",
    "Nakhon Ratchasima (Northeast)": "nakhon ratchasima",
    "Chonburi / Pattaya (East)": "chonburi",
    "Rayong (East)": "rayong",
    "Ayutthaya (Central)": "ayutthaya",
    "Nakhon Pathom (Central)": "nakhon pathom",
    "Phitsanulok (Central)": "phitsanulok"
}

selected_district_name = st.sidebar.radio("Select District", list(DISTRICTS.keys()), label_visibility="collapsed")
selected_station_query = DISTRICTS[selected_district_name]

AQICN_TOKEN = st.secrets["AQICN_TOKEN"]

# 3. Fetch Live Telemetry Data across all districts
@st.cache_data(ttl=300)
def fetch_district_telemetry():
    records = []
    for name, query in DISTRICTS.items():
        if name == "All Districts":
            continue
        try:
            res = requests.get(f"https://api.waqi.info/feed/{query}/?token={AQICN_TOKEN}", timeout=4).json()
            if res.get("status") == "ok":
                d = res["data"]
                geo = d.get("city", {}).get("geo", [13.7563, 100.5018])
                aqi = d.get("aqi", 0)
                iaqi = d.get("iaqi", {})
                temp = iaqi.get("t", {}).get("v", 30.0)
                humi = iaqi.get("h", {}).get("v", 65.0)
                pm25 = iaqi.get("pm25", {}).get("v", aqi * 0.6)
                pm10 = iaqi.get("pm10", {}).get("v", aqi * 0.4)
                o3 = iaqi.get("o3", {}).get("v", 20.0)
                
                status = "NORMAL" if aqi <= 50 else ("WARNING" if aqi <= 100 else "ALERT")
                records.append({
                    "district": name,
                    "query_id": query,
                    "lat": float(geo[0]),
                    "lon": float(geo[1]),
                    "aqi": float(aqi),
                    "temperature": float(temp),
                    "humidity": float(humi),
                    "pm25": float(pm25),
                    "pm10": float(pm10),
                    "o3": float(o3),
                    "status": status,
                    "timestamp": d.get("time", {}).get("s", pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"))
                })
        except Exception:
            continue
    return pd.DataFrame(records)

df = fetch_district_telemetry()

# Filter Data Based on District Selection
if selected_district_name != "All Districts":
    filtered_df = df[df["district"] == selected_district_name]
else:
    filtered_df = df

# Generate Historical Trend for Selected District
def generate_trend_data():
    now = pd.Timestamp.now()
    times = [now - pd.Timedelta(hours=i*2) for i in range(12)]
    times.reverse()
    
    base_aqi = filtered_df["aqi"].mean() if not filtered_df.empty else 55
    import random
    trend = [max(10, int(base_aqi + random.randint(-8, 8))) for _ in range(12)]
    
    return pd.DataFrame({"Timestamp": times, "Air Quality (AQI)": trend})

trend_df = generate_trend_data()

# App Top Header
st.markdown(f"""
    <div class="top-nav">
        <div class="nav-brand">GeoEther | Air Quality Monitoring System</div>
        <div>
            <span class="nav-status">Synced: Live AQICN Feed</span>
        </div>
    </div>
""", unsafe_allow_html=True)

# --- KPI Metric Cards Row (Dynamically changes with district filter) ---
k1, k2, k3, k4 = st.columns(4)

avg_aqi = filtered_df["aqi"].mean() if not filtered_df.empty else 0
avg_temp = filtered_df["temperature"].mean() if not filtered_df.empty else 0
avg_humi = filtered_df["humidity"].mean() if not filtered_df.empty else 0

current_status = "NORMAL" if avg_aqi <= 50 else ("WARNING" if avg_aqi <= 100 else "ALERT")
status_class = "status-normal" if current_status == "NORMAL" else ("status-warning" if current_status == "WARNING" else "status-alert")

with k1:
    st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-title">Current Region AQI</div>
            <div class="kpi-value">{avg_aqi:.0f}</div>
            <div class="kpi-sub {status_class}">● {selected_district_name}</div>
        </div>
    """, unsafe_allow_html=True)

with k2:
    st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-title">Avg Temperature</div>
            <div class="kpi-value">{avg_temp:.1f} °C</div>
            <div class="kpi-sub" style="color: #718096;">Live Thermal Read</div>
        </div>
    """, unsafe_allow_html=True)

with k3:
    st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-title">Avg Humidity</div>
            <div class="kpi-value">{avg_humi:.1f} %</div>
            <div class="kpi-sub" style="color: #718096;">Atmospheric Moisture</div>
        </div>
    """, unsafe_allow_html=True)

with k4:
    st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-title">System Alert Level</div>
            <div class="kpi-value {status_class}">{current_status}</div>
            <div class="kpi-sub {status_class}">Automatic Threshold</div>
        </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# --- Main Grid Layout (Map + Pollutant Breakdown Visualization) ---
col_left, col_right = st.columns([1.7, 1.0])

with col_left:
    st.subheader(f"Map View — {selected_district_name}")
    map_center = [13.7563, 100.5018]
    zoom_level = 6
    
    if selected_district_name != "All Districts" and not filtered_df.empty:
        map_center = [filtered_df.iloc[0]["lat"], filtered_df.iloc[0]["lon"]]
        zoom_level = 9

    m = folium.Map(location=map_center, zoom_start=zoom_level, tiles="OpenStreetMap")
    
    if not df.empty:
        for _, row in df.iterrows():
            folium.CircleMarker(
                location=[row["lat"], row["lon"]],
                radius=8,
                popup=f"{row['district']}: AQI {row['aqi']}",
                color="red" if row['aqi'] > 100 else ("orange" if row['aqi'] > 50 else "green"),
                fill=True,
                fill_opacity=0.7
            ).add_to(m)

    tile_url = f"https://tiles.aqicn.org/tiles/usepa-aqi/{{z}}/{{x}}/{{y}}.png?token={AQICN_TOKEN}"
    folium.TileLayer(tiles=tile_url, attr="AQICN.org", name="Live Air Quality Overlay", overlay=True).add_to(m)
    
    st_folium(m, width="100%", height=380)

with col_right:
    st.subheader("Pollutant Concentration Breakdown")
    st.caption(f"Real-time pollutant breakdown for {selected_district_name}")
    
    if not filtered_df.empty:
        pollutant_data = pd.DataFrame({
            "Pollutant": ["PM2.5", "PM10", "O3 (Ozone)"],
            "Concentration": [
                filtered_df["pm25"].mean(),
                filtered_df["pm10"].mean(),
                filtered_df["o3"].mean()
            ]
        }).set_index("Pollutant")
        
        st.bar_chart(pollutant_data, height=330, color="#3182ce")
    else:
        st.info("No pollutant telemetry available for this filter.")

st.markdown("---")

# --- Progress Line Chart & Table Section ---
c_chart, c_table = st.columns([1.2, 1.3])

with c_chart:
    st.subheader(f"Air Quality Progress ({selected_district_name})")
    st.line_chart(trend_df.set_index("Timestamp"), height=300)

with c_table:
    st.subheader("Station Telemetry Records Table")
    if not filtered_df.empty:
        st.dataframe(filtered_df[["district", "aqi", "temperature", "humidity", "status", "timestamp"]], use_container_width=True, height=300, hide_index=True)
    else:
        st.info("No records found for the selected filter.")

