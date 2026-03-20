import math
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st


st.set_page_config(page_title="Pensacola Surf Watch", layout="wide")

APP_TITLE = "Pensacola Surf Watch"
APP_SUBTITLE = "Upstream Gulf swell indicators + local Pensacola surf outlook"

# Upstream buoys: these are NOT surf forecasts.
# They are offshore indicators that help show where swell energy is coming from.
BUOYS = [
    {"id": "42001", "name": "Mid Gulf", "body": "Gulf of Mexico"},
    {"id": "42012", "name": "Orange Beach", "body": "Gulf of Mexico"},
    {"id": "42040", "name": "Dauphin Island", "body": "Gulf of Mexico"},
]

# Pensacola Beach-ish point for local forecast
LOCAL_SPOT = {
    "name": "Pensacola Beach",
    "lat": 30.333,
    "lon": -87.142,
}

REQUEST_TIMEOUT = 12


# -----------------------------
# Helpers
# -----------------------------
def safe_float(value):
    try:
        if value in [None, "", "MM"]:
            return None
        return float(value)
    except Exception:
        return None


def to_degrees_text(deg):
    if deg is None:
        return "—"
    return f"{int(round(deg))}°"


def cardinal_from_degrees(deg):
    if deg is None:
        return "—"
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    ix = round(deg / 22.5) % 16
    return dirs[ix]


def parse_ndbc_time(row):
    try:
        year = int(row["#YY"])
        month = int(row["MM"])
        day = int(row["DD"])
        hour = int(row["hh"])
        minute = int(row["mm"])
        return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    except Exception:
        return None


def hours_old(dt):
    if not dt:
        return None
    now = datetime.now(timezone.utc)
    return (now - dt).total_seconds() / 3600.0


def format_obs_time(dt):
    if not dt:
        return "Unknown"
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def trend_label(series, decimals=1):
    vals = [v for v in series if v is not None]
    if len(vals) < 2:
        return "steady"

    latest = round(vals[0], decimals)
    prior = round(vals[1], decimals)

    if latest > prior:
        return "building"
    if latest < prior:
        return "fading"
    return "steady"


def wind_quality_label(wspd_kt, wdir_deg):
    """
    Extremely rough local read for Pensacola Beach:
    - N / NW / NE-ish: cleaner than onshore
    - S / SE / SW-ish: more onshore/choppy
    """
    if wspd_kt is None or wdir_deg is None:
        return "unknown"

    # Offshore-ish / side-off-ish for Pensacola-ish beaches
    offshore_dirs = ["N", "NNE", "NE", "NNW", "NW"]
    cross_dirs = ["ENE", "E", "WNW", "W"]
    onshore_dirs = ["ESE", "SE", "SSE", "S", "SSW", "SW", "WSW"]

    card = cardinal_from_degrees(wdir_deg)

    if card in offshore_dirs:
        if wspd_kt <= 12:
            return "clean"
        return "windy but workable"

    if card in cross_dirs:
        if wspd_kt <= 10:
            return "fair"
        return "mixed"

    if card in onshore_dirs:
        if wspd_kt <= 8:
            return "bumpy"
        return "choppy"

    return "unknown"


def score_local_surf(primary_height_ft, primary_period_s, local_wspd_kt, local_wdir_deg):
    """
    Very rough heuristic for local beachbreak.
    This is intentionally simple and readable.
    """
    score = 0

    if primary_height_ft is not None:
        if primary_height_ft >= 3.5:
            score += 3
        elif primary_height_ft >= 2.5:
            score += 2
        elif primary_height_ft >= 1.5:
            score += 1

    if primary_period_s is not None:
        if primary_period_s >= 8:
            score += 3
        elif primary_period_s >= 6:
            score += 2
        elif primary_period_s >= 5:
            score += 1

    if local_wspd_kt is not None and local_wdir_deg is not None:
        quality = wind_quality_label(local_wspd_kt, local_wdir_deg)
        if quality == "clean":
            score += 2
        elif quality == "fair":
            score += 1
        elif quality == "bumpy":
            score -= 1
        elif quality == "choppy":
            score -= 2
        elif quality == "windy but workable":
            score += 0
        elif quality == "mixed":
            score -= 1

    if score >= 7:
        return "Good"
    if score >= 4:
        return "Fair"
    if score >= 2:
        return "Poor to Fair"
    return "Poor"


def swell_signal_text(height_ft, period_s, direction_deg, trend):
    if height_ft is None and period_s is None:
        return "Latest buoy reading is incomplete, but it still serves as an upstream Gulf check."

    direction_text = cardinal_from_degrees(direction_deg)

    if period_s is not None and period_s >= 8:
        period_label = "a longer-period pulse"
    elif period_s is not None and period_s >= 6:
        period_label = "moderate-period energy"
    elif period_s is not None:
        period_label = "short-period windswell"
    else:
        period_label = "unclear-period energy"

    if height_ft is not None and height_ft >= 3:
        size_label = "meaningful energy in the water"
    elif height_ft is not None and height_ft >= 1.5:
        size_label = "some swell energy present"
    elif height_ft is not None:
        size_label = "limited swell energy"
    else:
        size_label = "unknown size"

    return (
        f"This buoy is showing {size_label} with {period_label} from {direction_text}. "
        f"Trend is {trend}."
    )


# -----------------------------
# NOAA / NDBC data fetchers
# -----------------------------
@st.cache_data(ttl=600, show_spinner=False)
def fetch_buoy_table(station_id):
    """
    Pull the last several standard meteorological observations from NDBC.
    We use the latest available reading and do NOT reject older data,
    so the app keeps showing the last reported observation.
    """
    url = f"https://www.ndbc.noaa.gov/data/realtime2/{station_id}.txt"
    r = requests.get(url, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()

    lines = r.text.splitlines()
    if len(lines) < 3:
        raise ValueError(f"No usable data returned for station {station_id}")

    header = lines[0].split()
    data_lines = []
    for line in lines[2:]:
        parts = line.split()
        if len(parts) == len(header):
            data_lines.append(parts)

    if not data_lines:
        raise ValueError(f"No data rows found for station {station_id}")

    df = pd.DataFrame(data_lines, columns=header)
    return df


@st.cache_data(ttl=900, show_spinner=False)
def fetch_local_forecast(lat, lon):
    headers = {
        "User-Agent": "pensacola-surf-watch (ryan local dashboard)",
        "Accept": "application/geo+json",
    }

    points_url = f"https://api.weather.gov/points/{lat},{lon}"
    points_resp = requests.get(points_url, headers=headers, timeout=REQUEST_TIMEOUT)
    points_resp.raise_for_status()
    points_json = points_resp.json()

    hourly_url = points_json["properties"]["forecastHourly"]
    forecast_url = points_json["properties"]["forecast"]

    hourly_resp = requests.get(hourly_url, headers=headers, timeout=REQUEST_TIMEOUT)
    hourly_resp.raise_for_status()
    hourly_json = hourly_resp.json()

    forecast_resp = requests.get(forecast_url, headers=headers, timeout=REQUEST_TIMEOUT)
    forecast_resp.raise_for_status()
    forecast_json = forecast_resp.json()

    return {
        "hourly": hourly_json,
        "forecast": forecast_json,
    }


def extract_buoy_snapshot(station_id):
    df = fetch_buoy_table(station_id)

    latest = df.iloc[0].to_dict()
    prev = df.iloc[1].to_dict() if len(df) > 1 else None

    obs_time = parse_ndbc_time(latest)

    wave_height_ft = safe_float(latest.get("WVHT"))
    dominant_period_s = safe_float(latest.get("DPD"))
    average_period_s = safe_float(latest.get("APD"))
    mean_wave_dir = safe_float(latest.get("MWD"))
    wind_dir = safe_float(latest.get("WDIR"))
    wind_speed_kt = safe_float(latest.get("WSPD"))
    gust_kt = safe_float(latest.get("GST"))
    air_temp_c = safe_float(latest.get("ATMP"))
    water_temp_c = safe_float(latest.get("WTMP"))
    pressure_mb = safe_float(latest.get("PRES"))

    prev_wave_height = safe_float(prev.get("WVHT")) if prev else None
    prev_period = safe_float(prev.get("DPD")) if prev else None

    height_trend = trend_label([wave_height_ft, prev_wave_height], decimals=1)
    period_trend = trend_label([dominant_period_s, prev_period], decimals=0)

    return {
        "station_id": station_id,
        "obs_time": obs_time,
        "hours_old": hours_old(obs_time),
        "wave_height_ft": wave_height_ft,
        "dominant_period_s": dominant_period_s,
        "average_period_s": average_period_s,
        "mean_wave_dir": mean_wave_dir,
        "wind_dir": wind_dir,
        "wind_speed_kt": wind_speed_kt,
        "gust_kt": gust_kt,
        "air_temp_c": air_temp_c,
        "water_temp_c": water_temp_c,
        "pressure_mb": pressure_mb,
        "height_trend": height_trend,
        "period_trend": period_trend,
    }


def c_to_f(c):
    if c is None:
        return None
    return (c * 9 / 5) + 32


def extract_local_conditions():
    fc = fetch_local_forecast(LOCAL_SPOT["lat"], LOCAL_SPOT["lon"])

    hourly_periods = fc["hourly"]["properties"]["periods"]
    daily_periods = fc["forecast"]["properties"]["periods"]

    now_period = hourly_periods[0] if hourly_periods else None
    next_period = hourly_periods[1] if len(hourly_periods) > 1 else None
    today_period = daily_periods[0] if daily_periods else None
    tonight_period = daily_periods[1] if len(daily_periods) > 1 else None

    def parse_wind_speed_kt(speed_str):
        if not speed_str:
            return None
        first_num = ""
        for ch in speed_str:
            if ch.isdigit():
                first_num += ch
            elif first_num:
                break
        return float(first_num) if first_num else None

    def direction_to_degrees(direction):
        mapping = {
            "N": 0, "NNE": 22.5, "NE": 45, "ENE": 67.5,
            "E": 90, "ESE": 112.5, "SE": 135, "SSE": 157.5,
            "S": 180, "SSW": 202.5, "SW": 225, "WSW": 247.5,
            "W": 270, "WNW": 292.5, "NW": 315, "NNW": 337.5,
        }
        return mapping.get(direction)

    local = {
        "now_name": now_period.get("name") if now_period else "Now",
        "temp_f": now_period.get("temperature") if now_period else None,
        "wind_speed_kt": parse_wind_speed_kt(now_period.get("windSpeed")) if now_period else None,
        "wind_dir_text": now_period.get("windDirection") if now_period else None,
        "wind_dir_deg": direction_to_degrees(now_period.get("windDirection")) if now_period else None,
        "short_forecast": now_period.get("shortForecast") if now_period else "Unavailable",
        "detailed_forecast": today_period.get("detailedForecast") if today_period else "Unavailable",
        "next_forecast": next_period.get("shortForecast") if next_period else "Unavailable",
        "tonight_forecast": tonight_period.get("detailedForecast") if tonight_period else "Unavailable",
    }
    return local


def build_local_outlook(buoy_snapshots, local):
    valid_heights = [b["wave_height_ft"] for b in buoy_snapshots if b["wave_height_ft"] is not None]
    valid_periods = [b["dominant_period_s"] for b in buoy_snapshots if b["dominant_period_s"] is not None]

    primary_height = max(valid_heights) if valid_heights else None
    primary_period = max(valid_periods) if valid_periods else None

    call = score_local_surf(
        primary_height_ft=primary_height,
        primary_period_s=primary_period,
        local_wspd_kt=local["wind_speed_kt"],
        local_wdir_deg=local["wind_dir_deg"],
    )

    wind_quality = wind_quality_label(local["wind_speed_kt"], local["wind_dir_deg"])

    if wind_quality == "clean":
        best_window = "Best shot is while local winds stay cleaner."
    elif wind_quality == "fair":
        best_window = "There may be a decent window before winds worsen."
    elif wind_quality == "bumpy":
        best_window = "Rideable for a look, but local texture likely limits quality."
    elif wind_quality == "choppy":
        best_window = "Conditions likely stay pretty chopped up unless winds back off."
    elif wind_quality == "windy but workable":
        best_window = "There may be a window, but the wind could still be a factor."
    else:
        best_window = "Watch local winds closely."

    summary_parts = []

    if primary_height is not None and primary_period is not None:
        summary_parts.append(
            f"Upstream buoys are showing around {primary_height:.1f} ft at up to {primary_period:.0f}s."
        )
    elif primary_height is not None:
        summary_parts.append(f"Upstream buoys are showing around {primary_height:.1f} ft.")
    else:
        summary_parts.append("Upstream buoy data is limited right now.")

    if local["wind_speed_kt"] is not None and local["wind_dir_text"]:
        summary_parts.append(
            f"Local wind is about {int(local['wind_speed_kt'])} kt from the {local['wind_dir_text']}."
        )

    summary_parts.append(f"Overall local call: {call}.")
    summary = " ".join(summary_parts)

    return {
        "call": call,
        "wind_quality": wind_quality,
        "best_window": best_window,
        "summary": summary,
    }


# -----------------------------
# UI
# -----------------------------
st.title(APP_TITLE)
st.caption(APP_SUBTITLE)

with st.expander("What the buoy cards mean", expanded=False):
    st.write(
        """
These buoy cards are **upstream swell indicators**, not surf forecasts.

They help answer:
- Is energy in the Gulf?
- What direction is it coming from?
- Is it building, holding, or fading before it reaches the coast?

The actual surf call is in the **Pensacola Surf Outlook** section below.
        """
    )

# Refresh button
if st.button("Refresh now"):
    st.cache_data.clear()
    st.rerun()

# -----------------------------
# Data load
# -----------------------------
buoy_snapshots = []
buoy_errors = []

for buoy in BUOYS:
    try:
        snap = extract_buoy_snapshot(buoy["id"])
        snap["name"] = buoy["name"]
        snap["body"] = buoy["body"]
        buoy_snapshots.append(snap)
    except Exception as e:
        buoy_errors.append(f"{buoy['id']} ({buoy['name']}): {e}")

local = None
local_outlook = None
local_error = None

try:
    local = extract_local_conditions()
    local_outlook = build_local_outlook(buoy_snapshots, local)
except Exception as e:
    local_error = str(e)

# -----------------------------
# Local outlook section
# -----------------------------
st.subheader("Pensacola Surf Outlook")

if local and local_outlook:
    m1, m2, m3, m4 = st.columns(4)

    with m1:
        st.metric("Local Call", local_outlook["call"])

    with m2:
        wind_display = "—"
        if local["wind_speed_kt"] is not None and local["wind_dir_text"]:
            wind_display = f"{int(local['wind_speed_kt'])} kt {local['wind_dir_text']}"
        st.metric("Local Wind", wind_display)

    with m3:
        st.metric("Wind Quality", local_outlook["wind_quality"].title())

    with m4:
        st.metric("Current Weather", local["short_forecast"])

    st.info(local_outlook["summary"])
    st.write(f"**Best Window:** {local_outlook['best_window']}")
    st.write(f"**Today:** {local['detailed_forecast']}")
else:
    st.warning("Local outlook is temporarily unavailable.")
    if local_error:
        st.caption(local_error)

st.divider()

# -----------------------------
# Buoy cards
# -----------------------------
st.subheader("Upstream Swell Indicators")

cols = st.columns(len(BUOYS))

for i, buoy in enumerate(BUOYS):
    with cols[i]:
        snap = next((b for b in buoy_snapshots if b["station_id"] == buoy["id"]), None)

        st.markdown(f"### {buoy['id']}")
        st.caption(f"{buoy['name']} · {buoy['body']}")

        if not snap:
            st.error("Unable to load station data.")
            continue

        obs_age = snap["hours_old"]
        age_text = "unknown age"
        if obs_age is not None:
            age_text = f"{obs_age:.1f}h old"

        st.write(f"**Latest Reading:** {format_obs_time(snap['obs_time'])}")
        st.caption(f"Showing most recent report available ({age_text})")

        a, b = st.columns(2)
        with a:
            st.metric(
                "Wave Height",
                f"{snap['wave_height_ft']:.1f} ft" if snap["wave_height_ft"] is not None else "—",
                snap["height_trend"],
            )
            st.metric(
                "Dominant Period",
                f"{snap['dominant_period_s']:.0f} s" if snap["dominant_period_s"] is not None else "—",
                snap["period_trend"],
            )
            direction_value = "—"
            if snap["mean_wave_dir"] is not None:
                direction_value = f"{cardinal_from_degrees(snap['mean_wave_dir'])} {to_degrees_text(snap['mean_wave_dir'])}"
            st.metric("Primary Direction", direction_value)

        with b:
            wind_value = "—"
            if snap["wind_speed_kt"] is not None and snap["wind_dir"] is not None:
                wind_value = (
                    f"{snap['wind_speed_kt']:.0f} kt "
                    f"{cardinal_from_degrees(snap['wind_dir'])}"
                )
            elif snap["wind_speed_kt"] is not None:
                wind_value = f"{snap['wind_speed_kt']:.0f} kt"
            st.metric("Wind at Buoy", wind_value)

            water_value = "—"
            wt_f = c_to_f(snap["water_temp_c"])
            if wt_f is not None:
                water_value = f"{wt_f:.0f}°F"
            st.metric("Water Temp", water_value)

            pressure_value = "—"
            if snap["pressure_mb"] is not None:
                pressure_value = f"{snap['pressure_mb']:.1f} mb"
            st.metric("Pressure", pressure_value)

        st.markdown("**Swell Signal**")
        st.write(
            swell_signal_text(
                snap["wave_height_ft"],
                snap["dominant_period_s"],
                snap["mean_wave_dir"],
                snap["height_trend"],
            )
        )

# -----------------------------
# Errors
# -----------------------------
if buoy_errors:
    st.divider()
    st.subheader("Station Notes")
    for err in buoy_errors:
        st.caption(err)

st.divider()
st.caption(
    "Buoy cards are offshore indicators for incoming Gulf swell energy. "
    "They help track direction, period, and trend — not local rideability at the buoy itself."
)
