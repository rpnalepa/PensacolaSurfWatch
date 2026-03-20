import pandas as pd
import streamlit as st
from zoneinfo import ZoneInfo
from datetime import datetime
from io import StringIO
import requests

st.set_page_config(page_title="Pensacola Surf Watch", layout="wide")

LATEST_OBS_URL = "https://www.ndbc.noaa.gov/data/latest_obs/latest_obs.txt"
LOCAL_TZ = ZoneInfo("America/Chicago")

# You can change labels here anytime
STATIONS = {
    "42039": "Pensacola - 115nm SSE",
    "42040": "LuLu",
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
    return dt_utc.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %I:%M %p %Z")

def to_utc_time_str(dt_utc):
    if dt_utc is None:
        return "—"
    return dt_utc.strftime("%Y-%m-%d %H:%M UTC")

@st.cache_data(ttl=300)
def fetch_latest_obs():
    response = requests.get(LATEST_OBS_URL, timeout=20)
    response.raise_for_status()

    # NDBC latest_obs has two header/comment lines, then whitespace-delimited data
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
        delim_whitespace=True,
        names=columns,
        na_values=["MM", "999", "99", "999.0", "99.0"]
    )

    df["station"] = df["station"].astype(str)

    # Numeric cleanup
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
    # Simple Gulf-friendly heuristic you can tune later
    if wvht_ft is None or period_s is None:
        return "⚪ No wave data"

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

    # Loose heuristic: N/NE/E winds tend to be cleaner for Pensacola Beach
    if wind_dir_deg is not None:
        if 0 <= wind_dir_deg <= 90:
            score += 1
        elif 180 <= wind_dir_deg <= 270:
            score -= 1

    if score >= 5:
        return "🟢 Go surf"
    if score >= 3:
        return "🟡 Maybe fun"
    return "🔴 Probably weak"

def format_station_row(row):
    if row is None:
        return {
            "Station": "—",
            "Name": "—",
            "Wave Height (ft)": "—",
            "Dominant Period (s)": "—",
            "Average Period (s)": "—",
            "Wind (kt)": "—",
            "Wind Dir": "—",
            "Water Temp (°C)": "—",
            "Observed (Local)": "—",
            "Observed (UTC)": "—",
            "Rating": "⚪ No recent report",
        }

    wvht_m = safe_float(row.get("wvht"))
    dpd = safe_float(row.get("dpd"))
    apd = safe_float(row.get("apd"))
    wspd = safe_float(row.get("wspd"))
    wtmp = safe_float(row.get("wtmp"))
    wdir = safe_float(row.get("wdir"))

    wvht_ft = round(wvht_m * 3.28084, 1) if wvht_m is not None else None
    obs_time = row.get("obs_time_utc")

    return {
        "Station": str(row.get("station", "—")),
        "Name": STATIONS.get(str(row.get("station", "")), "Unknown"),
        "Wave Height (ft)": wvht_ft if wvht_ft is not None else "—",
        "Dominant Period (s)": round(dpd, 1) if dpd is not None else "—",
        "Average Period (s)": round(apd, 1) if apd is not None else "—",
        "Wind (kt)": round(wspd, 1) if wspd is not None else "—",
        "Wind Dir": wind_dir_to_text(wdir) if wdir is not None else "—",
        "Water Temp (°C)": round(wtmp, 1) if wtmp is not None else "—",
        "Observed (Local)": to_local_time_str(obs_time),
        "Observed (UTC)": to_utc_time_str(obs_time),
        "Rating": surf_rating(wvht_ft, dpd, wspd, wdir),
    }

# -------- UI --------

st.title("Pensacola Surf Watch")
st.caption("Live NOAA buoy dashboard for Pensacola-area surf checks")

refresh_now = datetime.now(tz=LOCAL_TZ)
st.write(f"**App refreshed:** {refresh_now.strftime('%Y-%m-%d %I:%M:%S %p %Z')}")

try:
    obs = fetch_latest_obs()
except Exception as e:
    st.error(f"Could not load NOAA data right now: {e}")
    st.stop()

rows = []
for station_id in STATIONS.keys():
    match = obs.loc[obs["station"] == station_id]
    if match.empty:
        rows.append({
            "Station": station_id,
            "Name": STATIONS[station_id],
            "Wave Height (ft)": "—",
            "Dominant Period (s)": "—",
            "Average Period (s)": "—",
            "Wind (kt)": "—",
            "Wind Dir": "—",
            "Water Temp (°C)": "—",
            "Observed (Local)": "—",
            "Observed (UTC)": "—",
            "Rating": "⚪ No recent report",
        })
    else:
        rows.append(format_station_row(match.iloc[0]))

display_df = pd.DataFrame(rows)

st.subheader("Current Buoy Conditions")
st.dataframe(display_df, use_container_width=True, hide_index=True)

# Pick a "best right now" based on simple scoring from the displayed data
scored = display_df.copy()

def score_rating(rating):
    if "🟢" in str(rating):
        return 3
    if "🟡" in str(rating):
        return 2
    if "🔴" in str(rating):
        return 1
    return 0

scored["score"] = scored["Rating"].apply(score_rating)
scored["wave_num"] = pd.to_numeric(scored["Wave Height (ft)"], errors="coerce").fillna(0)
scored["period_num"] = pd.to_numeric(scored["Dominant Period (s)"], errors="coerce").fillna(0)

best = scored.sort_values(
    by=["score", "period_num", "wave_num"],
    ascending=False
).iloc[0]

st.subheader("Quick Read")
if best["score"] == 0:
    st.write("No station has a solid recent report right now.")
else:
    st.write(
        f"**Best-looking buoy right now:** {best['Station']} ({best['Name']})  \n"
        f"**Rating:** {best['Rating']}  \n"
        f"**Observed:** {best['Observed (Local)']}  \n"
        f"**Wave Height:** {best['Wave Height (ft)']} ft  \n"
        f"**Dominant Period:** {best['Dominant Period (s)']} s"
    )

with st.expander("How the rating works"):
    st.write(
        """
This is a simple first-pass score:
- more points for bigger waves
- more points for longer period
- a little help for lighter winds
- a little help for N/NE/E wind directions

We can tune this next so it matches what *you* actually like to surf.
        """
    )

st.markdown("---")
st.caption(
    "Source: NOAA / NDBC latest observations feed. Times shown per-station so 'current' never loses its timestamp."
)
