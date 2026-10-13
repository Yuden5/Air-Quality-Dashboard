import json


import pandas as pd
import streamlit as st
import folium


from azure.storage.blob import BlobServiceClient
from streamlit_autorefresh import st_autorefresh
from streamlit_folium import st_folium



# ------------------------------------------------------------
# 1. Page configuration
# ------------------------------------------------------------


st.set_page_config(
    page_title="GeoEther | Azure Air Quality Monitoring",
    layout="wide",
    initial_sidebar_state="expanded",
)


# Refresh every 60 seconds.
# New readings require the Azure pipeline to be running.
st_autorefresh(
    interval=60_000,
    key="azure_telemetry_autorefresh",
)


# Load existing CSS.
try:
    with open("style.css", encoding="utf-8") as css_file:
        st.markdown(
            f"<style>{css_file.read()}</style>",
            unsafe_allow_html=True,
        )
except FileNotFoundError:
    pass



# ------------------------------------------------------------
# 2. Azure telemetry configuration
# ------------------------------------------------------------


REQUIRED_COLUMNS = [
    "device_id",
    "temperature",
    "humidity",
    "air_quality",
    "event_time",
]



def parse_blob_content(content: str) -> list[dict]:
    """Read a JSON object, array, or line-separated JSON records."""


    content = content.strip()


    if not content:
        return []


    try:
        parsed = json.loads(content)


        if isinstance(parsed, list):
            return [
                item for item in parsed
                if isinstance(item, dict)
            ]


        if isinstance(parsed, dict):
            return [parsed]


    except json.JSONDecodeError:
        pass


    records = []


    for line in content.splitlines():
        line = line.strip()


        if not line:
            continue


        try:
            item = json.loads(line)


            if isinstance(item, dict):
                records.append(item)


        except json.JSONDecodeError:
            # Ignore invalid or incomplete JSON lines.
            continue


    return records



@st.cache_data(ttl=60, show_spinner=False)
def fetch_azure_telemetry() -> tuple[pd.DataFrame, str | None]:
    """Read recent JSON telemetry blobs from Azure Blob Storage."""


    try:
        connection_string = st.secrets[
            "AZURE_STORAGE_CONNECTION_STRING"
        ]


        container_name = st.secrets[
            "AZURE_CONTAINER_NAME"
        ]


        prefix = st.secrets.get(
            "AZURE_BLOB_PREFIX",
            "",
        )


        service = BlobServiceClient.from_connection_string(
            connection_string
        )


        container = service.get_container_client(
            container_name
        )


        # List JSON blobs in the configured container.
        json_blobs = [
            blob
            for blob in container.list_blobs(
                name_starts_with=prefix or None
            )
            if blob.name.lower().endswith(".json")
        ]


        # Newest modified blobs first.
        json_blobs.sort(
            key=lambda blob: (
                blob.last_modified
                or pd.Timestamp.min.tz_localize("UTC")
            ),
            reverse=True,
        )


        records = []


        # Download only the 20 newest JSON blobs.
        for blob in json_blobs[:20]:
            try:
                raw = container.download_blob(
                    blob.name
                ).readall()


                content = raw.decode("utf-8-sig")


                records.extend(
                    parse_blob_content(content)
                )


            except Exception:
                # Continue if an individual blob cannot be read.
                continue


        if not records:
            return (
                pd.DataFrame(columns=REQUIRED_COLUMNS),
                None,
            )


        df = pd.DataFrame(records)


        # Missing fields remain missing.
        # No synthetic readings are created.
        for column in REQUIRED_COLUMNS:
            if column not in df.columns:
                df[column] = pd.NA


        df = df[REQUIRED_COLUMNS].copy()


        df["device_id"] = df["device_id"].astype("string")


        for column in [
            "temperature",
            "humidity",
            "air_quality",
        ]:
            df[column] = pd.to_numeric(
                df[column],
                errors="coerce",
            )


        df["event_time"] = pd.to_datetime(
            df["event_time"],
            errors="coerce",
            utc=True,
        )


        df = df.dropna(
            subset=["device_id", "event_time"]
        )


        df = df[
            df["device_id"].str.strip() != ""
        ]


        df = df.drop_duplicates(
            subset=["device_id", "event_time"],
            keep="last",
        )


        df = df.sort_values("event_time")


        return df, None


    except KeyError as exc:
        return (
            pd.DataFrame(columns=REQUIRED_COLUMNS),
            f"Missing Streamlit secret: {exc}. "
            "Configure your Azure secrets.",
        )


    except Exception as exc:
        return (
            pd.DataFrame(columns=REQUIRED_COLUMNS),
            f"Could not read Azure Blob Storage: {exc}",
        )



# Retrieve telemetry using the existing Azure connection.
df, load_error = fetch_azure_telemetry()



# ------------------------------------------------------------
# 3. Header
# ------------------------------------------------------------


st.markdown(
    """
    <div class="top-nav">
        <div class="nav-brand">
            GeoEther | Air Quality Monitoring System
        </div>
        <div>
            <span class="nav-status">
                Azure Blob Telemetry
            </span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


st.caption(
    "Live readings from Azure IoT Hub → Stream Analytics "
    "→ Blob Storage. The dashboard refreshes every 60 seconds."
)


if load_error:
    st.error(load_error)



# ------------------------------------------------------------
# 4. Dashboard page navigation
# ------------------------------------------------------------


st.sidebar.markdown("### GeoEther")


selected_page = st.sidebar.radio(
    "DASHBOARD PAGES",
    [
        "Live Monitoring",
        "Azure Pipeline & Workflow",
    ],
    index=0,
)


st.sidebar.markdown("---")



# ============================================================
# PAGE 2: AZURE PIPELINE & WORKFLOW
# ============================================================


if selected_page == "Azure Pipeline & Workflow":


    st.title("Azure Pipeline & Workflow")


    st.caption(
        "GeoEther | End-to-end IoT telemetry processing "
        "and visualization"
    )


    st.markdown("---")


    # --------------------------------------------------------
    # 4.1 End-to-end data pipeline
    # --------------------------------------------------------


    st.subheader("End-to-End Data Pipeline")


    st.write(
        "The following workflow shows how telemetry travels "
        "from the Python simulator through Azure services "
        "and into the GeoEther dashboard."
    )


    pipeline_steps = [
        {
            "number": "01",
            "title": "IoT Sensor Simulator",
            "service": "Python · azure-iot-device",
            "details": (
                "Generates sample sensor telemetry containing "
                "device_id, temperature, humidity, air_quality, "
                "and event_time. Sends messages at regular intervals."
            ),
            "output": "Telemetry messages",
        },
        {
            "number": "02",
            "title": "Azure IoT Hub",
            "service": "Device-to-cloud messaging",
            "details": (
                "Receives telemetry from the registered IoT device "
                "through its device connection."
            ),
            "output": "Incoming device events",
        },
        {
            "number": "03",
            "title": "Azure Stream Analytics",
            "service": "Real-time stream processing",
            "details": (
                "Reads events from the IoT Hub input and selects "
                "the telemetry fields required by GeoEther. "
                "System.Timestamp() supplies the event-processing "
                "timestamp used by the query."
            ),
            "output": "Structured telemetry records",
        },
        {
            "number": "04",
            "title": "Azure Blob Storage",
            "service": "Persistent output storage",
            "details": (
                "Receives processed records through the configured "
                "BlobOutput output alias. JSON blobs store the "
                "telemetry for subsequent retrieval."
            ),
            "output": "JSON blob files",
        },
        {
            "number": "05",
            "title": "GeoEther Dashboard",
            "service": "Python · Streamlit",
            "details": (
                "Connects to the configured storage container, "
                "reads recent JSON blobs, parses records, and "
                "displays KPIs, charts, warning states, insights, "
                "and the sensor records table."
            ),
            "output": "Monitoring and visualization",
        },
    ]


    for index, step in enumerate(pipeline_steps):


        with st.container(border=True):


            number_col, details_col = st.columns(
                [1, 5]
            )


            with number_col:
                st.markdown(
                    f"## {step['number']}"
                )


            with details_col:
                st.markdown(
                    f"### {step['title']}"
                )


                st.caption(step["service"])


                st.write(step["details"])


                st.markdown(
                    f"**Output:** {step['output']}"
                )


        if index < len(pipeline_steps) - 1:
            st.markdown(
                """
                <div style="
                    text-align:center;
                    font-size:26px;
                    color:#718096;
                    margin:2px 0;
                ">↓</div>
                """,
                unsafe_allow_html=True,
            )


    st.markdown("---")


    # --------------------------------------------------------
    # 4.2 Stream Analytics queries
    # --------------------------------------------------------


    st.subheader("Stream Analytics Queries")


    st.write(
        "These queries read the IoT Hub input and send the "
        "selected telemetry fields to the configured Blob output."
    )


    query_tab_1, query_tab_2, query_tab_3 = st.tabs(
        [
            "1. Base Telemetry Query",
            "2. Condition-Based Query",
            "3. Aggregation Query",
        ]
    )


    with query_tab_1:


        st.markdown("#### Base Telemetry Query")


        st.write(
            "This is the existing query. It forwards every "
            "telemetry event and its required fields to Blob Storage."
        )


        st.code(
            """SELECT
    device_id,
    temperature,
    humidity,
    air_quality,
    System.Timestamp() AS event_time
INTO
    BlobOutput
FROM
    [thailand-air-iothub]""",
            language="sql",
        )


    with query_tab_2:


        st.markdown("#### Condition-Based Query")


        st.write(
            "This query forwards only events where the air-quality "
            "value is greater than or equal to 80."
        )


        st.code(
            """SELECT
    device_id,
    temperature,
    humidity,
    air_quality,
    System.Timestamp() AS event_time
INTO
    BlobOutput
FROM
    [thailand-air-iothub]
WHERE
    air_quality >= 80""",
            language="sql",
        )


        st.caption(
            "In the Live Monitoring page, the dashboard also shows "
            "a local view of the records matching this condition."
        )


    with query_tab_3:


        st.markdown("#### Aggregation Query")


        st.write(
            "This query groups telemetry by device and one-minute "
            "tumbling window. It calculates average, maximum, and "
            "sum of air quality, plus average temperature."
        )


        st.code(
            """SELECT
    device_id,
    AVG(air_quality) AS avg_air_quality,
    MAX(air_quality) AS max_air_quality,
    SUM(air_quality) AS sum_air_quality,
    AVG(temperature) AS avg_temperature
INTO
    BlobOutput
FROM
    [thailand-air-iothub]
GROUP BY
    device_id,
    TumblingWindow(minute, 1)""",
            language="sql",
        )


        st.caption(
            "In the Live Monitoring page, the dashboard also shows "
            "a local one-minute aggregation view calculated from "
            "the retrieved Azure telemetry."
        )


    st.caption(
        "BlobOutput is the Stream Analytics output alias. "
        "The actual storage container is configured separately."
    )


    st.info(
        "If you add the condition-based or aggregation query as "
        "an additional Stream Analytics output, use a separate "
        "output alias and container or blob prefix. Do not send "
        "multiple query outputs to the same BlobOutput unless you "
        "intend to mix record types."
    )


    st.markdown("---")


    # --------------------------------------------------------
    # 4.3 Telemetry data schema
    # --------------------------------------------------------


    st.subheader("Telemetry Data Schema")


    schema_df = pd.DataFrame(
        [
            {
                "Field": "device_id",
                "Purpose": "Identifies the sending device",
                "Dashboard Use": (
                    "Device filtering and record identification"
                ),
            },
            {
                "Field": "temperature",
                "Purpose": (
                    "Temperature value supplied by the simulator"
                ),
                "Dashboard Use": (
                    "Temperature KPI, trend, and thresholds"
                ),
            },
            {
                "Field": "humidity",
                "Purpose": (
                    "Humidity value supplied by the simulator"
                ),
                "Dashboard Use": (
                    "Humidity KPI and sensor insights"
                ),
            },
            {
                "Field": "air_quality",
                "Purpose": (
                    "Air-quality value supplied by the simulator"
                ),
                "Dashboard Use": (
                    "Air-quality KPI, trend, thresholds, "
                    "condition filtering, and aggregation"
                ),
            },
            {
                "Field": "event_time",
                "Purpose": (
                    "Timestamp assigned by Stream Analytics"
                ),
                "Dashboard Use": (
                    "Time-series charts, event ordering, and "
                    "one-minute aggregation windows"
                ),
            },
        ]
    )


    st.dataframe(
        schema_df,
        use_container_width=True,
        hide_index=True,
    )


    st.info(
        "The current simulator produces sample telemetry. "
        "The air_quality field is a simulated value, not a direct "
        "measurement from a certified air-quality instrument."
    )


    st.markdown("---")


    # --------------------------------------------------------
    # 4.4 Dashboard processing workflow
    # --------------------------------------------------------


    st.subheader("Dashboard Data Processing Workflow")


    dashboard_steps = [
        (
            "1. Authenticate",
            "Read the Azure Storage connection string and "
            "container name from Streamlit secrets.",
        ),
        (
            "2. Discover recent files",
            "List JSON blobs in the configured container and "
            "sort them by last-modified timestamp.",
        ),
        (
            "3. Retrieve telemetry",
            "Download up to 20 of the newest JSON blobs and "
            "parse JSON objects, arrays, or line-separated records.",
        ),
        (
            "4. Validate and prepare",
            "Convert numeric fields and timestamps, discard "
            "invalid device/timestamp records, remove duplicate "
            "device-time records, and sort by event time.",
        ),
        (
            "5. Calculate indicators",
            "Calculate latest and average values from the records "
            "retrieved and classify the latest readings using "
            "the project's configured thresholds.",
        ),
        (
            "6. Apply query views",
            "Create a condition-based view for air_quality >= 80 "
            "and a local one-minute aggregation view by device.",
        ),
        (
            "7. Visualize and refresh",
            "Render KPI cards, time-series charts, rule-based "
            "insights, query-result sections, the regional map, "
            "and the records table. The dashboard refreshes every "
            "60 seconds.",
        ),
    ]


    for title, description in dashboard_steps:


        with st.container(border=True):
            st.markdown(f"**{title}**")
            st.write(description)


    st.markdown("---")


    # --------------------------------------------------------
    # 4.5 Warning and alert workflow
    # --------------------------------------------------------


    st.subheader("Warning and Alert Workflow")


    alert_df = pd.DataFrame(
        [
            {
                "Metric": "Air Quality",
                "NORMAL": "≤ 50",
                "WARNING": "51–100",
                "ALERT": "> 100",
            },
            {
                "Metric": "Temperature",
                "NORMAL": "< 35 °C",
                "WARNING": "35–< 40 °C",
                "ALERT": "≥ 40 °C",
            },
        ]
    )


    st.dataframe(
        alert_df,
        use_container_width=True,
        hide_index=True,
    )


    st.markdown(
        """
        **Decision rule**


        - **NORMAL:** Available latest readings are within the
          configured normal ranges.
        - **WARNING:** At least one latest reading is in the
          warning range and none is in the alert range.
        - **ALERT:** At least one latest reading has reached
          the alert range.
        - **NO DATA:** Neither air quality nor temperature has
          a valid latest reading.
        """
    )


    st.caption(
        "These are demonstration thresholds, not official "
        "environmental or health standards. The dashboard "
        "classifies readings locally; this code does not configure "
        "Azure-side alerts."
    )


    st.markdown("---")


    # --------------------------------------------------------
    # 4.6 Azure components and roles
    # --------------------------------------------------------


    st.subheader("Azure Components and Their Roles")


    service_df = pd.DataFrame(
        [
            {
                "Component": "Azure IoT Hub",
                "Role": "Ingests device-to-cloud telemetry",
            },
            {
                "Component": "Azure Stream Analytics",
                "Role": (
                    "Processes the event stream, applies the "
                    "condition filter, and calculates aggregates"
                ),
            },
            {
                "Component": "Azure Blob Storage",
                "Role": "Stores processed JSON output",
            },
            {
                "Component": "Streamlit Secrets",
                "Role": (
                    "Stores storage connection configuration securely"
                ),
            },
            {
                "Component": "Streamlit Dashboard",
                "Role": (
                    "Reads stored telemetry and displays monitoring UI"
                ),
            },
        ]
    )


    st.dataframe(
        service_df,
        use_container_width=True,
        hide_index=True,
    )


    st.warning(
        "The simulator must be running to generate new messages. "
        "Stream Analytics must process the messages, and Blob Storage "
        "must receive output. Refreshing Streamlit alone does not "
        "create new telemetry."
    )


    st.success(
        "Workflow overview complete. Select Live Monitoring "
        "in the sidebar to return to the dashboard."
    )


    # Stop here so the live dashboard sections below are not rendered.
    st.stop()



# ============================================================
# PAGE 1: LIVE MONITORING
# ============================================================


# ------------------------------------------------------------
# 5. Device filter
# ------------------------------------------------------------


st.sidebar.markdown("### IoT Devices")


st.sidebar.caption(
    "Choose which device telemetry to display."
)


if not df.empty:


    device_ids = sorted(
        df["device_id"].dropna().astype(str).unique().tolist()
    )


    selected_device = st.sidebar.selectbox(
        "Select device",
        ["All Devices"] + device_ids,
        label_visibility="collapsed",
    )


    if selected_device == "All Devices":
        filtered_df = df.copy()
    else:
        filtered_df = df[
            df["device_id"].astype(str) == selected_device
        ].copy()


else:
    selected_device = "All Devices"
    filtered_df = df.copy()



# ------------------------------------------------------------
# 6. KPI calculations and warning states
# ------------------------------------------------------------


def latest_value(data: pd.DataFrame, column: str):
    valid = data.dropna(
        subset=[column, "event_time"]
    )


    if valid.empty:
        return None


    return valid.sort_values(
        "event_time"
    ).iloc[-1][column]



def average_value(data: pd.DataFrame, column: str):
    values = data[column].dropna()


    if values.empty:
        return None


    return values.mean()



def metric_text(value, suffix=""):
    if value is None or pd.isna(value):
        return "—"


    return f"{value:.1f}{suffix}"



def air_quality_state(value):
    if value is None or pd.isna(value):
        return "NO DATA"


    if value <= 50:
        return "NORMAL"


    if value <= 100:
        return "WARNING"


    return "ALERT"



def temperature_state(value):
    if value is None or pd.isna(value):
        return "NO DATA"


    if value < 35:
        return "NORMAL"


    if value < 40:
        return "WARNING"


    return "ALERT"



def overall_state(air_quality, temperature):
    states = [
        air_quality_state(air_quality),
        temperature_state(temperature),
    ]


    if "ALERT" in states:
        return "ALERT"


    if "WARNING" in states:
        return "WARNING"


    if all(state == "NO DATA" for state in states):
        return "NO DATA"


    return "NORMAL"



latest_air_quality = latest_value(
    filtered_df,
    "air_quality",
)


latest_temp = latest_value(
    filtered_df,
    "temperature",
)


latest_humidity = latest_value(
    filtered_df,
    "humidity",
)


average_air_quality = average_value(
    filtered_df,
    "air_quality",
)


average_temp = average_value(
    filtered_df,
    "temperature",
)


last_seen = (
    filtered_df["event_time"].max()
    if (
        not filtered_df.empty
        and filtered_df["event_time"].notna().any()
    )
    else None
)


system_status = overall_state(
    latest_air_quality,
    latest_temp,
)



# ------------------------------------------------------------
# 7. KPI cards: two columns per row
# ------------------------------------------------------------


st.subheader("Air Quality Overview")


kpi_left, kpi_right = st.columns(
    2,
    gap="medium",
)


with kpi_left:
    st.metric(
        "Latest Air Quality",
        metric_text(latest_air_quality),
    )


with kpi_right:
    st.metric(
        "Average Air Quality",
        metric_text(average_air_quality),
    )



kpi_left, kpi_right = st.columns(
    2,
    gap="medium",
)


with kpi_left:
    st.metric(
        "Latest Temperature",
        metric_text(latest_temp, " °C"),
    )


with kpi_right:
    st.metric(
        "Average Temperature",
        metric_text(average_temp, " °C"),
    )



kpi_left, kpi_right = st.columns(
    2,
    gap="medium",
)


with kpi_left:
    st.metric(
        "Latest Humidity",
        metric_text(latest_humidity, " %"),
    )


with kpi_right:
    st.metric(
        "System Status",
        system_status,
    )



if system_status == "ALERT":


    st.error(
        "ALERT: At least one latest sensor reading has "
        "crossed the configured alert threshold."
    )


elif system_status == "WARNING":


    st.warning(
        "WARNING: At least one latest sensor reading is "
        "in the configured warning range."
    )


elif system_status == "NORMAL":


    st.success(
        "NORMAL: Latest available readings are within "
        "the configured ranges."
    )


else:


    st.info(
        "System status is unavailable until valid sensor "
        "readings arrive."
    )



if last_seen is not None:
    st.caption(
        f"Latest event timestamp: "
        f"{last_seen.strftime('%Y-%m-%d %H:%M:%S UTC')} "
        f"| Selected device: {selected_device}"
    )


st.markdown("---")



# ------------------------------------------------------------
# 8. Sensor trends
# ------------------------------------------------------------


st.subheader("Sensor Trends")


trend_left, trend_right = st.columns(2)


with trend_left:


    st.markdown("#### Air Quality Over Time")


    st.caption(
        "Actual air_quality readings from Azure telemetry."
    )


    air_chart = filtered_df.dropna(
        subset=["event_time", "air_quality"]
    ).sort_values("event_time")


    if not air_chart.empty:


        air_chart = air_chart.set_index(
            "event_time"
        )[["air_quality"]]


        air_chart = air_chart.rename(
            columns={
                "air_quality": "Air Quality",
            }
        )


        st.line_chart(
            air_chart,
            height=320,
        )


    else:


        st.info(
            "No air-quality readings are available yet."
        )



with trend_right:


    st.markdown("#### Temperature Over Time")


    st.caption(
        "Actual temperature readings from Azure telemetry."
    )


    temp_chart = filtered_df.dropna(
        subset=["event_time", "temperature"]
    ).sort_values("event_time")


    if not temp_chart.empty:


        temp_chart = temp_chart.set_index(
            "event_time"
        )[["temperature"]]


        temp_chart = temp_chart.rename(
            columns={
                "temperature": "Temperature (°C)",
            }
        )


        st.line_chart(
            temp_chart,
            height=320,
        )


    else:


        st.info(
            "No temperature readings are available yet."
        )


st.markdown("---")



# ------------------------------------------------------------
# 8.1 Condition-based query view
# ------------------------------------------------------------


st.subheader("Condition-Based Records")


st.caption(
    "Dashboard view of the Stream Analytics condition: "
    "air_quality >= 80. This uses the telemetry already loaded "
    "from Azure Blob Storage."
)


condition_df = filtered_df.dropna(
    subset=["air_quality"]
).copy()


condition_df = condition_df[
    condition_df["air_quality"] >= 80
].sort_values(
    "event_time",
    ascending=False,
)


condition_left, condition_right = st.columns(
    [1, 3]
)


with condition_left:
    st.metric(
        "Records With Air Quality ≥ 80",
        len(condition_df),
    )


with condition_right:
    if not condition_df.empty:
        st.line_chart(
            condition_df.set_index("event_time")[
                ["air_quality"]
            ].rename(
                columns={
                    "air_quality": "Air Quality ≥ 80"
                }
            ),
            height=260,
        )
    else:
        st.info(
            "No records currently meet the condition "
            "air_quality >= 80."
        )


if not condition_df.empty:


    condition_display_df = condition_df.copy()


    condition_display_df["event_time"] = (
        condition_display_df["event_time"].dt.strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
    )


    st.dataframe(
        condition_display_df.head(100),
        use_container_width=True,
        hide_index=True,
        height=280,
    )


    st.caption(
        "Showing up to 100 matching records from the currently "
        "loaded Azure telemetry."
    )


else:
    st.warning(
        "No condition-based records are available yet."
    )


st.markdown("---")



# ------------------------------------------------------------
# 8.2 One-minute aggregation query view
# ------------------------------------------------------------


st.subheader("One-Minute Aggregates by Device")


st.caption(
    "Dashboard view of the Stream Analytics aggregation query: "
    "records grouped by device and a one-minute tumbling window."
)


aggregation_df = filtered_df.dropna(
    subset=[
        "device_id",
        "event_time",
        "air_quality",
    ]
).copy()


if not aggregation_df.empty:


    aggregation_df["window_start"] = (
        aggregation_df["event_time"].dt.floor("1min")
    )


    aggregation_df = aggregation_df.groupby(
        [
            "device_id",
            "window_start",
        ],
        as_index=False,
    ).agg(
        avg_air_quality=(
            "air_quality",
            "mean",
        ),
        max_air_quality=(
            "air_quality",
            "max",
        ),
        sum_air_quality=(
            "air_quality",
            "sum",
        ),
        avg_temperature=(
            "temperature",
            "mean",
        ),
    )


    aggregation_df = aggregation_df.sort_values(
        [
            "window_start",
            "device_id",
        ],
        ascending=[False, True],
    )


    aggregate_left, aggregate_right = st.columns(
        [1, 2]
    )


    with aggregate_left:
        st.metric(
            "Aggregated Windows",
            len(aggregation_df),
        )


    with aggregate_right:
        aggregate_chart = aggregation_df.copy()


        aggregate_chart["window_start"] = (
            aggregate_chart[
                "window_start"
            ].dt.strftime(
                "%Y-%m-%d %H:%M"
            )
        )


        aggregate_chart = aggregate_chart.set_index(
            "window_start"
        )[["avg_air_quality"]]


        aggregate_chart = aggregate_chart.rename(
            columns={
                "avg_air_quality": (
                    "Average Air Quality"
                )
            }
        )


        st.line_chart(
            aggregate_chart,
            height=260,
        )


    aggregation_display_df = aggregation_df.copy()


    aggregation_display_df["window_start"] = (
        aggregation_display_df[
            "window_start"
        ].dt.strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
    )


    st.dataframe(
        aggregation_display_df.head(100),
        use_container_width=True,
        hide_index=True,
        height=320,
    )


    st.caption(
        "Showing up to 100 most recent one-minute windows from "
        "the currently loaded Azure telemetry. Average temperature "
        "is blank for windows without a valid temperature value."
    )


else:
    st.info(
        "No valid telemetry is available to calculate "
        "one-minute aggregates."
    )


st.markdown("---")



# ------------------------------------------------------------
# 9. Sensor location map
# ------------------------------------------------------------


st.subheader("Sensor Location Map")


st.caption(
    "Regional map for project context. Current Azure telemetry "
    "does not include latitude or longitude, so this is not "
    "a verified live sensor-location map."
)


map_col, map_info_col = st.columns([1.6, 1])


with map_col:


    # Regional context only; no fabricated sensor coordinates.
    sensor_map = folium.Map(
        location=[17.0, 101.0],
        zoom_start=5,
        tiles="OpenStreetMap",
    )


    folium.Marker(
        location=[17.0, 101.0],
        tooltip="Regional view: Thailand",
        popup=(
            "Regional context only. "
            "No live sensor coordinates are available."
        ),
        icon=folium.Icon(
            color="blue",
            icon="info-sign",
        ),
    ).add_to(sensor_map)


    st_folium(
        sensor_map,
        height=420,
        use_container_width=True,
        key="geoether_regional_map",
    )



with map_info_col:


    st.markdown("#### Location Data")


    st.write(
        "**Selected device:**",
        selected_device,
    )


    if last_seen is not None:


        st.write(
            "**Last recorded event:**",
            last_seen.strftime("%Y-%m-%d %H:%M:%S UTC"),
        )


    else:


        st.write(
            "**Last recorded event:** No data"
        )


    st.info(
        "To display real sensor markers, telemetry must include "
        "valid latitude and longitude fields, and the dashboard "
        "must retain those fields when loading the records."
    )


st.markdown("---")



# ------------------------------------------------------------
# 10. Smart sensor insights
# ------------------------------------------------------------


st.subheader("Smart Sensor Insights")


st.caption(
    "Rule-based interpretation of actual readings. "
    "No generative AI model is connected in this version."
)


insight_col, threshold_col = st.columns([1.2, 1])


with insight_col:


    st.markdown("#### Current Interpretation")


    if filtered_df.empty:


        st.info(
            "No sensor records are available for interpretation. "
            "Check the Azure telemetry pipeline."
        )


    else:


        if (
            latest_air_quality is not None
            and not pd.isna(latest_air_quality)
        ):


            aq_state = air_quality_state(
                latest_air_quality
            )


            if aq_state == "NORMAL":


                st.success(
                    f"Air quality value is "
                    f"{latest_air_quality:.1f}, within the "
                    "project's normal range."
                )


            elif aq_state == "WARNING":


                st.warning(
                    f"Air quality value is "
                    f"{latest_air_quality:.1f}, within the "
                    "project's warning range."
                )


            else:


                st.error(
                    f"Air quality value is "
                    f"{latest_air_quality:.1f}, above the "
                    "project's warning range."
                )


        else:


            st.info(
                "No valid air-quality value is available."
            )



        if (
            latest_temp is not None
            and not pd.isna(latest_temp)
        ):


            temp_state = temperature_state(
                latest_temp
            )


            if temp_state == "NORMAL":


                st.success(
                    f"Temperature is {latest_temp:.1f} °C, "
                    "within the project's normal range."
                )


            elif temp_state == "WARNING":


                st.warning(
                    f"Temperature is {latest_temp:.1f} °C, "
                    "within the project's warning range."
                )


            else:


                st.error(
                    f"Temperature is {latest_temp:.1f} °C, "
                    "at or above the project's alert threshold."
                )


        else:


            st.info(
                "No valid temperature value is available."
            )



        if (
            latest_humidity is not None
            and not pd.isna(latest_humidity)
        ):


            st.write(
                f"Latest recorded humidity: "
                f"{latest_humidity:.1f}%."
            )


        else:


            st.write(
                "Humidity data is not available."
            )



with threshold_col:


    st.markdown("#### Project Alert Thresholds")


    threshold_df = pd.DataFrame(
        [
            {
                "Metric": "Air Quality",
                "NORMAL": "≤ 50",
                "WARNING": "51–100",
                "ALERT": "> 100",
            },
            {
                "Metric": "Temperature",
                "NORMAL": "< 35 °C",
                "WARNING": "35–< 40 °C",
                "ALERT": "≥ 40 °C",
            },
        ]
    )


    st.dataframe(
        threshold_df,
        use_container_width=True,
        hide_index=True,
    )


    st.caption(
        "These are demonstration thresholds for this project, "
        "not official health or environmental safety standards. "
        "The air_quality field is supplied by the simulator."
    )


st.markdown("---")



# ------------------------------------------------------------
# 11. Latest sensor records
# ------------------------------------------------------------


st.subheader("Latest Sensor Records")


if not filtered_df.empty:


    display_df = filtered_df.sort_values(
        "event_time",
        ascending=False,
    ).copy()


    display_df["event_time"] = (
        display_df["event_time"].dt.strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
    )


    st.dataframe(
        display_df.head(100),
        use_container_width=True,
        hide_index=True,
        height=350,
    )


    st.caption(
        "Records loaded from the 20 most recently modified "
        "JSON blobs. The dashboard displays values from Azure "
        "telemetry and does not generate missing readings."
    )


else:


    st.warning(
        "No Azure telemetry records found. Check the container "
        "name, Streamlit secrets, Stream Analytics output, "
        "and simulator."
    )



# ------------------------------------------------------------
# 12. Troubleshooting and data notes
# ------------------------------------------------------------


with st.expander("Troubleshooting and Data Notes"):


    st.markdown(
        """
        - **No records:** Confirm that Stream Analytics is running
          and writing JSON files to the configured Blob Storage container.


        - **No new readings:** The simulator, IoT Hub input,
          Stream Analytics job, and Blob output must all be working.


        - **Missing values:** Confirm that the output contains
          `device_id`, `temperature`, `humidity`, `air_quality`,
          and `event_time`.


        - **Old readings:** Check the newest blob's Last modified
          time in Azure Portal.


        - **Condition-based records:** These records require a valid
          `air_quality` value of 80 or greater.


        - **One-minute aggregates:** These are calculated locally
          from loaded telemetry using device and one-minute windows.
          They mirror the Stream Analytics aggregation query but are
          not a replacement for Azure-side aggregation output.


        - **Map:** The current telemetry schema does not contain
          latitude or longitude, so the map is regional context only.


        - **Smart insights:** Current interpretations use explicit
          thresholds. No generative AI service is connected here.


        - **Security:** Keep the Azure Storage connection string in
          Streamlit Secrets and never commit it to your repository.
        """
    )