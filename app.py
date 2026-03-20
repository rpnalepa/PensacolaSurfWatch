import pandas as pd
import streamlit as st
from zoneinfo import ZoneInfo
from datetime import datetime
from io import StringIO
import requests

st.set_page_config(page_title="Pensacola Surf Watch", layout="wide")

LATEST_OBS_URL = "https://www.ndbc.noaa.gov/data/latest_obs/latest_obs.txt"
LOCAL_TZ = ZoneInfo("America/Chicago")

STATIONS = {
    "42039": "Pensacola - 115nm SSE",
    "42040": "Dauphin Island",
    "42001": "Mid Gulf",
    "42026": "West Tampa",
}

def safe_float(value):
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None

def to_local_time_str(dt_utc):
    if dt_utc is None:
        return "—"
    return dt_utc.astimezone(LOCAL_TZ).strftime("%b %d, %I:%M %p %Z")

def to_utc_time_str(dt_utc):
    if dt_utc is None:
        return "—"
    return dt_utc.strftime("%Y-%m-%d %H:%M UTC")

@st.cache_data(ttl=300)
def fetch_latest_obs():
    response = requests.get(LATEST_OBS_URL, timeout=20)
    response.raise_for_status()

    lines = response.text.splitlines()
    if len(lines) < 3:
        raise ValueError("NOAA feed came back empty or malformed.")

    data_text = "\n".join(lines[2:])

    columns = [
        "station", "lat", "lon", "year", "month", "day", "hour", "minute",
        "wdir", "wspd", "gst", "wvht", "dpd", "apd", "mwd",
        "pres", "atmp", "wtmp", "dewp", "vis", "ptdy", "tide"
    ]

    df = pd.read_csv(
        StringIO(data_text),
        sep=r"\s+",
        names=columns,
        na_values=["MM", "999", "99", "999.0", "99.0"]
    )

    df["station"] = df["station"].astype(str)

    numeric_cols = [
        "lat", "lon", "year", "month", "day", "hour", "minute",
        "wdir", "wspd", "gst", "wvht", "dpd", "apd", "mwd",
        "pres", "atmp", "wtmp", "dewp", "vis", "ptdy", "tide"
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    def build_obs_time(row):
        needed = ["year", "month", "day", "hour", "minute"]
        if row[needed].isna().any():
            return None
        try:
            return datetime(
                int(row["year"]),
                int(row["month"]),
                int(row["day"]),
                int(row["hour"]),
                int(row["minute"]),
                tzinfo=ZoneInfo("UTC")
            )
        except Exception:
            return None

    df["obs_time_utc"] = df.apply(build_obs_time, axis=1)
    return df

def wind_dir_to_text(deg):
    if deg is None:
        return "—"

    dirs = [
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"
    ]
    idx = int((deg + 11.25) // 22.5) % 16
    return dirs[idx]

def surf_rating(wvht_ft, period_s, wind_kt, wind_dir_deg):
    if wvht_ft is None or period_s is None:
        return "no_data", "⚪ No report", 0

    score = 0

    if wvht_ft >= 2.0:
        score += 2
    elif wvht_ft >= 1.2:
        score += 1

    if period_s >= 7:
        score += 2
    elif period_s >= 5:
        score += 1

    if wind_kt is not None:
        if wind_kt <= 12:
            score += 1
        elif wind_kt >= 20:
            score -= 1

    if wind_dir_deg is not None:
        if 0 <= wind_dir_deg <= 90:
            score += 1
        elif 180 <= wind_dir_deg <= 270:
            score -= 1

    if score >= 5:
        return "good", "🟢 Go surf", score
    if score >= 3:
        return "maybe", "🟡 Maybe fun", score
    return "poor", "🔴 Probably weak", score

def fmt_value(value, suffix=""):
    if value is None:
        return "—"
    return f"{value}{suffix}"

def format_station_row(row, station_id, station_name):
    if row is None:
        return {
            "Station": station_id,
            "Name": station_name,
            "Wave Height (ft)": None,
            "Dominant Period (s)": None,
            "Average Period (s)": None,
            "Wind (kt)": None,
            "Wind Dir": "—",
            "Water Temp (°C)": None,
            "Observed (Local)": "—",
            "Observed (UTC)": "—",
            "Rating Key": "no_data",
            "Rating Label": "⚪ No recent report",
            "Score": 0,
        }

    wvht_m = safe_float(row.get("wvht"))
    dpd = safe_float(row.get("dpd"))
    apd = safe_float(row.get("apd"))
    wspd = safe_float(row.get("wspd"))
    wtmp = safe_float(row.get("wtmp"))
    wdir = safe_float(row.get("wdir"))

    wvht_ft = round(wvht_m * 3.28084, 1) if wvht_m is not None else None
    obs_time = row.get("obs_time_utc")
    rating_key, rating_label, score = surf_rating(wvht_ft, dpd, wspd, wdir)

    return {
        "Station": station_id,
        "Name": station_name,
        "Wave Height (ft)": wvht_ft,
        "Dominant Period (s)": round(dpd, 1) if dpd is not None else None,
        "Average Period (s)": round(apd, 1) if apd is not None else None,
        "Wind (kt)": round(wspd, 1) if wspd is not None else None,
        "Wind Dir": wind_dir_to_text(wdir) if wdir is not None else "—",
        "Water Temp (°C)": round(wtmp, 1) if wtmp is not None else None,
        "Observed (Local)": to_local_time_str(obs_time),
        "Observed (UTC)": to_utc_time_str(obs_time),
        "Rating Key": rating_key,
        "Rating Label": rating_label,
        "Score": score,
    }

st.markdown("""
<style>
.block-container {
    padding-top: 1.5rem;
    padding-bottom: 2rem;
}
.main-title {
    font-size: 2.2rem;
    font-weight: 800;
    margin-bottom: 0.15rem;
}
.subtle {
    color: #6b7280;
    font-size: 0.95rem;
    margin-bottom: 1rem;
}
.summary-card {
    background: #f8fafc;
    border: 1px solid #e5e7eb;
    border-radius: 18px;
    padding: 1rem;
    margin-bottom: 1rem;
}
.summary-label {
    font-size: 0.8rem;
    color: #6b7280;
    margin-bottom: 0.3rem;
}
.summary-value {
    font-size: 1.2rem;
    font-weight: 700;
}
.buoy-card {
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 20px;
    padding: 1rem;
    margin-bottom: 1rem;
    box-shadow: 0 1px 6px rgba(0,0,0,0.04);
}
.buoy-title {
    font-size: 1.1rem;
    font-weight: 800;
    margin-bottom: 0.15rem;
}
.buoy-subtitle {
    color: #6b7280;
    font-size: 0.9rem;
    margin-bottom: 0.75rem;
}
.metric-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.7rem;
    margin-top: 0.5rem;
    margin-bottom: 0.8rem;
}
.metric-box {
    background: #f8fafc;
    border-radius: 14px;
    padding: 0.75rem;
}
.metric-label {
    font-size: 0.78rem;
    color: #6b7280;
    margin-bottom: 0.2rem;
}
.metric-value {
    font-size: 1.15rem;
    font-weight: 700;
}
.meta-line {
    font-size: 0.88rem;
    color: #4b5563;
    margin-top: 0.25rem;
}
.rating-good, .rating-maybe, .rating-poor, .rating-no_data {
    display: inline-block;
    padding: 0.35rem 0.7rem;
    border-radius: 999px;
    font-weight: 700;
    font-size: 0.9rem;
    margin-bottom: 0.8rem;
}
.rating-good {
    background: #dcfce7;
    color: #166534;
}
.rating-maybe {
    background: #fef3c7;
    color: #92400e;
}
.rating-poor {
    background: #fee2e2;
    color: #991b1b;
}
.rating-no_data {
    background: #e5e7eb;
    color: #374151;
}
.section-title {
    font-size: 1.15rem;
    font-weight: 800;
    margin-top: 1rem;
    margin-bottom: 0.8rem;
}
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title">Pensacola Surf Watch</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="subtle">Live NOAA buoy dashboard for quick Pensacola-area surf checks</div>',
    unsafe_allow_html=True
)

refresh_now = datetime.now(tz=LOCAL_TZ)

try:
    obs = fetch_latest_obs()
except Exception as e:
    st.error(f"Could not load NOAA data right now: {e}")
    st.stop()

rows = []
for station_id, station_name in STATIONS.items():
    match = obs.loc[obs["station"] == station_id]
    if match.empty:
        rows.append(format_station_row(None, station_id, station_name))
    else:
        rows.append(format_station_row(match.iloc[0], station_id, station_name))

display_df = pd.DataFrame(rows)

best = max(
    rows,
    key=lambda r: (
        r["Score"],
        r["Dominant Period (s)"] if r["Dominant Period (s)"] is not None else 0,
        r["Wave Height (ft)"] if r["Wave Height (ft)"] is not None else 0,
    )
)

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown(
        f"""
        <div class="summary-card">
            <div class="summary-label">Best buoy right now</div>
            <div class="summary-value">{best['Name']}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

with col2:
    st.markdown(
        f"""
        <div class="summary-card">
            <div class="summary-label">Best rating</div>
            <div class="summary-value">{best['Rating Label']}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

with col3:
    st.markdown(
        f"""
        <div class="summary-card">
            <div class="summary-label">App refreshed</div>
            <div class="summary-value">{refresh_now.strftime('%b %d, %I:%M %p')}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

st.markdown('<div class="section-title">Current Buoy Conditions</div>', unsafe_allow_html=True)

card_cols = st.columns(2)

for i, row in enumerate(rows):
    with card_cols[i % 2]:
        st.markdown(
            f"""
            <div class="buoy-card">
                <div class="buoy-title">{row['Name']}</div>
                <div class="buoy-subtitle">Station {row['Station']}</div>
                <div class="rating-{row['Rating Key']}">{row['Rating Label']}</div>

                <div class="metric-grid">
                    <div class="metric-box">
                        <div class="metric-label">Wave Height</div>
                        <div class="metric-value">{fmt_value(row['Wave Height (ft)'], ' ft')}</div>
                    </div>
                    <div class="metric-box">
                        <div class="metric-label">Dominant Period</div>
                        <div class="metric-value">{fmt_value(row['Dominant Period (s)'], ' s')}</div>
                    </div>
                    <div class="metric-box">
                        <div class="metric-label">Wind</div>
                        <div class="metric-value">{fmt_value(row['Wind (kt)'], ' kt')}</div>
                    </div>
                    <div class="metric-box">
                        <div class="metric-label">Wind Direction</div>
                        <div class="metric-value">{row['Wind Dir']}</div>
                    </div>
                </div>

                <div class="meta-line"><strong>Observed:</strong> {row['Observed (Local)']}</div>
                <div class="meta-line"><strong>UTC:</strong> {row['Observed (UTC)']}</div>
                <div class="meta-line"><strong>Water Temp:</strong> {fmt_value(row['Water Temp (°C)'], ' °C')}</div>
                <div class="meta-line"><strong>Average Period:</strong> {fmt_value(row['Average Period (s)'], ' s')}</div>
            </div>
            """,
            unsafe_allow_html=True
        )

with st.expander("Raw data table"):
    st.dataframe(
        display_df[
            [
                "Station", "Name", "Wave Height (ft)", "Dominant Period (s)",
                "Average Period (s)", "Wind (kt)", "Wind Dir",
                "Water Temp (°C)", "Observed (Local)", "Observed (UTC)",
                "Rating Label"
            ]
        ],
        use_container_width=True,
        hide_index=True
    )
