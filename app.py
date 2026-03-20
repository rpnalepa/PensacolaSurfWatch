import pandas as pd
import streamlit as st
from zoneinfo import ZoneInfo
from datetime import datetime
from io import StringIO
import requests

st.set_page_config(page_title="Pensacola Surf Watch", layout="wide")

LATEST_OBS_URL = "https://www.ndbc.noaa.gov/data/latest_obs/latest_obs.txt"
LOCAL_TZ = ZoneInfo("America/Chicago")

# Pensacola Beach-ish point for NWS forecast lookup
FORECAST_LAT = 30.333
FORECAST_LON = -87.142

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


def reading_age_text(dt_utc):
    if dt_utc is None:
        return "—"
    now_utc = datetime.now(ZoneInfo("UTC"))
    delta = now_utc - dt_utc
    total_minutes = int(delta.total_seconds() // 60)

    if total_minutes < 60:
        return f"{total_minutes} min ago"

    hours = total_minutes // 60
    minutes = total_minutes % 60

    if hours < 24:
        return f"{hours}h {minutes}m ago"

    days = hours // 24
    rem_hours = hours % 24
    return f"{days}d {rem_hours}h ago"


def wind_dir_to_text(deg):
    if deg is None:
        return "—"
    dirs = [
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"
    ]
    idx = int((deg + 11.25) // 22.5) % 16
    return dirs[idx]


def wind_dir_category(deg):
    if deg is None:
        return "unknown"
    if 0 <= deg <= 90:
        return "cleaner"
    if 91 <= deg <= 157:
        return "side-on"
    if 158 <= deg <= 270:
        return "onshore"
    return "side-off"


def surf_rating(wvht_ft, period_s, wind_kt, wind_dir_deg):
    if wvht_ft is None or period_s is None:
        return "⚪ No wave data", 0

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
        return "🟢 Go surf", score
    if score >= 3:
        return "🟡 Maybe fun", score
    return "🔴 Probably weak", score


@st.cache_data(ttl=300)
def fetch_latest_obs():
    response = requests.get(LATEST_OBS_URL, timeout=20)
    response.raise_for_status()

    lines = response.text.splitlines()
    if len(lines) < 3:
        raise ValueError("NOAA latest observations feed came back empty or malformed.")

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


@st.cache_data(ttl=300)
def fetch_station_history(station_id):
    url = f"https://www.ndbc.noaa.gov/data/realtime2/{station_id}.txt"
    response = requests.get(url, timeout=20)
    response.raise_for_status()

    lines = response.text.splitlines()
    if len(lines) < 3:
        return pd.DataFrame()

    data_text = "\n".join(lines[2:])
    columns = [
        "YY", "MM", "DD", "hh", "mm",
        "WDIR", "WSPD", "GST", "WVHT", "DPD", "APD", "MWD",
        "PRES", "ATMP", "WTMP", "DEWP", "VIS", "PTDY", "TIDE"
    ]

    df = pd.read_csv(
        StringIO(data_text),
        sep=r"\s+",
        names=columns,
        na_values=["MM", "999", "99", "999.0", "99.0"]
    )

    for col in columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    def build_obs_time(row):
        needed = ["YY", "MM", "DD", "hh", "mm"]
        if row[needed].isna().any():
            return None
        try:
            return datetime(
                int(row["YY"]),
                int(row["MM"]),
                int(row["DD"]),
                int(row["hh"]),
                int(row["mm"]),
                tzinfo=ZoneInfo("UTC")
            )
        except Exception:
            return None

    df["obs_time_utc"] = df.apply(build_obs_time, axis=1)
    df = df.sort_values("obs_time_utc", ascending=False)
    return df


def get_best_station_row(latest_obs_df, station_id):
    match = latest_obs_df.loc[latest_obs_df["station"] == station_id]
    if not match.empty:
        row = match.iloc[0]
        return {
            "station": station_id,
            "obs_time_utc": row.get("obs_time_utc"),
            "wdir": safe_float(row.get("wdir")),
            "wspd": safe_float(row.get("wspd")),
            "wvht": safe_float(row.get("wvht")),
            "dpd": safe_float(row.get("dpd")),
            "apd": safe_float(row.get("apd")),
            "wtmp": safe_float(row.get("wtmp")),
            "source": "Current",
            "is_stale": False,
        }

    try:
        hist = fetch_station_history(station_id)
        if not hist.empty:
            for _, row in hist.iterrows():
                if (
                    pd.notna(row.get("WVHT"))
                    or pd.notna(row.get("DPD"))
                    or pd.notna(row.get("WSPD"))
                ):
                    return {
                        "station": station_id,
                        "obs_time_utc": row.get("obs_time_utc"),
                        "wdir": safe_float(row.get("WDIR")),
                        "wspd": safe_float(row.get("WSPD")),
                        "wvht": safe_float(row.get("WVHT")),
                        "dpd": safe_float(row.get("DPD")),
                        "apd": safe_float(row.get("APD")),
                        "wtmp": safe_float(row.get("WTMP")),
                        "source": "Last known reading",
                        "is_stale": True,
                    }
    except Exception:
        pass

    return None


def format_station_data(station_id, station_name, raw):
    if raw is None:
        return {
            "Station": station_id,
            "Name": station_name,
            "Wave Height (ft)": None,
            "Dominant Period (s)": None,
            "Average Period (s)": None,
            "Wind (kt)": None,
            "Wind Dir": "—",
            "Water Temp (°F)": None,
            "Observed (Local)": "—",
            "Observed (UTC)": "—",
            "Age": "—",
            "Rating": "⚪ No report",
            "Score": 0,
            "Source": "No station data",
            "Raw Wind Dir Deg": None,
        }

    wvht_m = raw.get("wvht")
    dpd = raw.get("dpd")
    apd = raw.get("apd")
    wspd = raw.get("wspd")
    wdir = raw.get("wdir")
    wtmp_c = raw.get("wtmp")

    wvht_ft = round(wvht_m * 3.28084, 1) if wvht_m is not None else None
    wtmp_f = round((wtmp_c * 9 / 5) + 32, 1) if wtmp_c is not None else None
    rating, score = surf_rating(wvht_ft, dpd, wspd, wdir)

    return {
        "Station": station_id,
        "Name": station_name,
        "Wave Height (ft)": wvht_ft,
        "Dominant Period (s)": round(dpd, 1) if dpd is not None else None,
        "Average Period (s)": round(apd, 1) if apd is not None else None,
        "Wind (kt)": round(wspd, 1) if wspd is not None else None,
        "Wind Dir": wind_dir_to_text(wdir),
        "Water Temp (°F)": wtmp_f,
        "Observed (Local)": to_local_time_str(raw.get("obs_time_utc")),
        "Observed (UTC)": to_utc_time_str(raw.get("obs_time_utc")),
        "Age": reading_age_text(raw.get("obs_time_utc")),
        "Rating": rating,
        "Score": score,
        "Source": raw.get("source", "Unknown"),
        "Raw Wind Dir Deg": wdir,
    }


@st.cache_data(ttl=1800)
def fetch_forecast_periods():
    headers = {"User-Agent": "pensacola-surf-watch"}

    points_url = f"https://api.weather.gov/points/{FORECAST_LAT},{FORECAST_LON}"
    point_resp = requests.get(points_url, headers=headers, timeout=20)
    point_resp.raise_for_status()
    point_data = point_resp.json()

    forecast_url = point_data["properties"]["forecast"]
    hourly_url = point_data["properties"]["forecastHourly"]

    forecast_resp = requests.get(forecast_url, headers=headers, timeout=20)
    forecast_resp.raise_for_status()
    forecast_data = forecast_resp.json()

    hourly_resp = requests.get(hourly_url, headers=headers, timeout=20)
    hourly_resp.raise_for_status()
    hourly_data = hourly_resp.json()

    return (
        forecast_data["properties"]["periods"],
        hourly_data["properties"]["periods"],
    )


def hourly_wind_speed_to_int(wind_speed_text):
    if not wind_speed_text:
        return None
    digits = []
    current_num = ""
    for ch in str(wind_speed_text):
        if ch.isdigit():
            current_num += ch
        else:
            if current_num:
                digits.append(int(current_num))
                current_num = ""
    if current_num:
        digits.append(int(current_num))
    if not digits:
        return None
    return round(sum(digits) / len(digits))


def outlook_from_conditions(label, base_wave_ft, base_period_s, hourly_periods_slice):
    score = 0

    if base_wave_ft is not None:
        if base_wave_ft >= 2.0:
            score += 2
        elif base_wave_ft >= 1.2:
            score += 1

    if base_period_s is not None:
        if base_period_s >= 7:
            score += 2
        elif base_period_s >= 5:
            score += 1

    wind_speeds = []
    wind_dirs = []

    for period in hourly_periods_slice:
        ws = hourly_wind_speed_to_int(period.get("windSpeed"))
        if ws is not None:
            wind_speeds.append(ws)

        wd = period.get("windDirection")
        if wd:
            wind_dirs.append(wd)

    avg_wind = round(sum(wind_speeds) / len(wind_speeds)) if wind_speeds else None

    cleaner_count = 0
    onshore_count = 0

    for wd in wind_dirs:
        if wd in ["N", "NNE", "NE", "ENE", "E"]:
            cleaner_count += 1
        if wd in ["S", "SSW", "SW", "WSW", "W", "SSE", "SE"]:
            onshore_count += 1

    if avg_wind is not None:
        if avg_wind <= 10:
            score += 1
        elif avg_wind >= 16:
            score -= 1

    if cleaner_count > onshore_count:
        score += 1
    elif onshore_count > cleaner_count:
        score -= 1

    if score >= 5:
        rating = "🟢 Go surf"
    elif score >= 3:
        rating = "🟡 Maybe fun"
    else:
        rating = "🔴 Probably weak"

    reasons = []

    if base_wave_ft is not None and base_period_s is not None:
        reasons.append(f"{base_wave_ft} ft @ {base_period_s}s at the buoys")

    if avg_wind is not None:
        reasons.append(f"forecast wind around {avg_wind} kt")

    if cleaner_count > onshore_count:
        reasons.append("cleaner wind direction window")
    elif onshore_count > cleaner_count:
        reasons.append("more onshore wind look")
    else:
        reasons.append("mixed wind direction")

    why = ", ".join(reasons) if reasons else "limited data"

    return {
        "label": label,
        "rating": rating,
        "why": why,
        "score": score,
    }


def swell_trend_text(local_rows, upstream_rows):
    all_rows = local_rows + upstream_rows

    valid_wave = [r["Wave Height (ft)"] for r in all_rows if r["Wave Height (ft)"] is not None]
    valid_period = [r["Dominant Period (s)"] for r in all_rows if r["Dominant Period (s)"] is not None]

    if not valid_wave and not valid_period:
        return "Unavailable"

    avg_wave = sum(valid_wave) / len(valid_wave) if valid_wave else 0
    avg_period = sum(valid_period) / len(valid_period) if valid_period else 0

    if avg_wave >= 2.0 and avg_period >= 6.0:
        return "Building / enough energy in the chain"
    if avg_wave >= 1.2 and avg_period >= 5.0:
        return "Steady / small but rideable"
    return "Fading or weak"


def wind_trend_text(hourly_periods):
    first6 = hourly_periods[:6]
    if not first6:
        return "Unavailable"

    speeds = []
    cleaner = 0
    onshore = 0

    for p in first6:
        ws = hourly_wind_speed_to_int(p.get("windSpeed"))
        if ws is not None:
            speeds.append(ws)

        wd = p.get("windDirection")
        if wd in ["N", "NNE", "NE", "ENE", "E"]:
            cleaner += 1
        elif wd in ["S", "SSW", "SW", "WSW", "W", "SSE", "SE"]:
            onshore += 1

    avg_speed = round(sum(speeds) / len(speeds)) if speeds else None

    if cleaner > onshore:
        if avg_speed is not None and avg_speed <= 10:
            return "Cleaner early"
        return "Manageable but not glassy"
    if onshore > cleaner:
        return "Likely worse as the day goes on"
    return "Mixed"


def fmt_metric(value, suffix=""):
    if value is None:
        return "—"
    return f"{value}{suffix}"


st.title("Pensacola Surf Watch")
st.caption("Live buoy check + surf outlook for Pensacola-area calls")

refresh_now = datetime.now(tz=LOCAL_TZ)
st.write(f"**App refreshed:** {refresh_now.strftime('%b %d, %I:%M %p %Z')}")

try:
    latest_obs = fetch_latest_obs()
except Exception as e:
    st.error(f"Could not load NOAA data right now: {e}")
    st.stop()

rows = []
for station_id, station_name in STATIONS.items():
    raw = get_best_station_row(latest_obs, station_id)
    rows.append(format_station_data(station_id, station_name, raw))

best = max(
    rows,
    key=lambda r: (
        r["Score"],
        r["Dominant Period (s)"] if r["Dominant Period (s)"] is not None else 0,
        r["Wave Height (ft)"] if r["Wave Height (ft)"] is not None else 0,
    )
)

top1, top2, top3 = st.columns(3)
top1.metric("Best buoy right now", best["Name"])
top2.metric("Best rating", best["Rating"])
top3.metric("Last refresh", refresh_now.strftime("%I:%M %p"))

st.subheader("Current Buoy Conditions")

cols = st.columns(2)

for i, row in enumerate(rows):
    with cols[i % 2]:
        with st.container(border=True):
            st.markdown(f"### {row['Name']}")
            st.caption(f"Station {row['Station']}")

            st.write(f"**Status:** {row['Source']}")
            st.write(f"**Observed:** {row['Observed (Local)']}")
            st.write(f"**Age:** {row['Age']}")
            st.write(f"**Rating:** {row['Rating']}")

            m1, m2 = st.columns(2)
            m1.metric("Wave Height", fmt_metric(row["Wave Height (ft)"], " ft"))
            m2.metric("Dominant Period", fmt_metric(row["Dominant Period (s)"], " s"))

            m3, m4 = st.columns(2)
            m3.metric("Wind", fmt_metric(row["Wind (kt)"], " kt"))
            m4.metric("Wind Dir", row["Wind Dir"])

            m5, m6 = st.columns(2)
            m5.metric("Water Temp", fmt_metric(row["Water Temp (°F)"], " °F"))
            m6.metric("Avg Period", fmt_metric(row["Average Period (s)"], " s"))

st.subheader("Surf Outlook")

try:
    forecast_periods, hourly_periods = fetch_forecast_periods()

    local_rows = [r for r in rows if r["Station"] in ["42039", "42040"]]
    upstream_rows = [r for r in rows if r["Station"] in ["42001", "42026"]]

    local_wave_values = [r["Wave Height (ft)"] for r in local_rows if r["Wave Height (ft)"] is not None]
    local_period_values = [r["Dominant Period (s)"] for r in local_rows if r["Dominant Period (s)"] is not None]

    upstream_wave_values = [r["Wave Height (ft)"] for r in upstream_rows if r["Wave Height (ft)"] is not None]
    upstream_period_values = [r["Dominant Period (s)"] for r in upstream_rows if r["Dominant Period (s)"] is not None]

    base_wave = None
    base_period = None

    if local_wave_values or upstream_wave_values:
        combined = local_wave_values + upstream_wave_values
        base_wave = round(sum(combined) / len(combined), 1)

    if local_period_values or upstream_period_values:
        combined = local_period_values + upstream_period_values
        base_period = round(sum(combined) / len(combined), 1)

    morning = outlook_from_conditions("This Morning", base_wave, base_period, hourly_periods[:4])
    afternoon = outlook_from_conditions("This Afternoon", base_wave, base_period, hourly_periods[4:9])

    tomorrow_base_wave = base_wave
    tomorrow_base_period = base_period

    if upstream_wave_values:
        tomorrow_base_wave = round(sum(upstream_wave_values) / len(upstream_wave_values), 1)
    if upstream_period_values:
        tomorrow_base_period = round(sum(upstream_period_values) / len(upstream_period_values), 1)

    tomorrow = outlook_from_conditions("Tomorrow Morning", tomorrow_base_wave, tomorrow_base_period, hourly_periods[12:18])

    out1, out2, out3 = st.columns(3)

    with out1:
        with st.container(border=True):
            st.markdown("### This Morning")
            st.write(morning["rating"])
            st.write(morning["why"])

    with out2:
        with st.container(border=True):
            st.markdown("### This Afternoon")
            st.write(afternoon["rating"])
            st.write(afternoon["why"])

    with out3:
        with st.container(border=True):
            st.markdown("### Tomorrow Morning")
            st.write(tomorrow["rating"])
            st.write(tomorrow["why"])

    trend1, trend2 = st.columns(2)

    with trend1:
        with st.container(border=True):
            st.markdown("### Swell Trend")
            st.write(swell_trend_text(local_rows, upstream_rows))

    with trend2:
        with st.container(border=True):
            st.markdown("### Wind Trend")
            st.write(wind_trend_text(hourly_periods))

    st.markdown("#### Quick Call")

    best_window = max([morning, afternoon, tomorrow], key=lambda x: x["score"])
    if best_window["label"] == "This Morning":
        st.success(f"Best shot looks like **this morning** — {best_window['rating']}.")
    elif best_window["label"] == "This Afternoon":
        st.success(f"Best shot looks like **this afternoon** — {best_window['rating']}.")
    else:
        st.success(f"Best shot looks like **tomorrow morning** — {best_window['rating']}.")

except Exception as e:
    st.warning(f"Surf outlook unavailable right now: {e}")

st.subheader("Weather Assist")

try:
    if 'forecast_periods' not in locals() or 'hourly_periods' not in locals():
        forecast_periods, hourly_periods = fetch_forecast_periods()

    wx_cols = st.columns(3)
    for i, period in enumerate(forecast_periods[:3]):
        with wx_cols[i]:
            with st.container(border=True):
                st.markdown(f"### {period['name']}")
                st.write(f"**Temp:** {period['temperature']}°{period['temperatureUnit']}")
                st.write(f"**Wind:** {period['windSpeed']} {period['windDirection']}")
                st.write(period["shortForecast"])

except Exception as e:
    st.warning(f"Weather section unavailable right now: {e}")

with st.expander("Raw buoy data table"):
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
