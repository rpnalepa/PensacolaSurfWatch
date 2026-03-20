import math
import re
from email.utils import parsedate_to_datetime

import pandas as pd
import requests
import streamlit as st


# =========================
# PAGE SETUP
# =========================
st.set_page_config(page_title="Pensacola Surf Watch", layout="wide")

st.title("Pensacola Surf Watch")
st.caption("Simple local buoy dashboard")


# ===== NAUTICAL MAP GOES HERE =====
import folium
from streamlit.components.v1 import html

BUOYS = [
    {"name": "42012", "label": "Orange Beach", "lat": 30.060, "lon": -87.548},
    {"name": "42001", "label": "Mid Gulf", "lat": 25.926, "lon": -89.662},
    {"name": "42040", "label": "Dauphin Island", "lat": 29.207, "lon": -88.237},
]

m = folium.Map(location=[28.9, -88.5], zoom_start=5, tiles=None)

folium.WmsTileLayer(
    url="https://gis.charttools.noaa.gov/arcgis/services/MCS/ENCOnline/MapServer/WMSServer?",
    name="NOAA Nautical Chart",
    layers="0",
    fmt="image/png",
    transparent=False,
    attr="NOAA"
).add_to(m)

for buoy in BUOYS:
    folium.Marker(
        [buoy["lat"], buoy["lon"]],
        tooltip=buoy["name"]
    ).add_to(m)

html(m._repr_html_(), height=600)
# ===== END MAP =====


# ===== YOUR EXISTING BUOY CARDS BELOW THIS =====
# (do not delete anything below)


# =========================
# CONFIG
# =========================
BUOYS = [
    {"id": "42012", "name": "Orange Beach"},
    {"id": "42040", "name": "Dauphin Island"},
    {"id": "42001", "name": "Mid Gulf"},
    {"id": "42003", "name": "East Gulf"},
]

STATIONS = [
    {
        "name": "Pensacola NAS",
        "url": "https://www.ndbc.noaa.gov/data/latest_obs/KPNS.rss",
        "fallback_id": "KPNS",
    },
    {
        "name": "Pensacola Beach",
        "url": "https://www.ndbc.noaa.gov/data/latest_obs/PNBF1.rss",
        "fallback_id": "PNBF1",
    },
    {
        "name": "Dauphin Island",
        "url": "https://www.ndbc.noaa.gov/data/latest_obs/DPIA1.rss",
        "fallback_id": "DPIA1",
    },
]


# =========================
# HELPERS
# =========================
def safe_float(value, default=None):
    try:
        if value is None:
            return default
        s = str(value).strip()
        if s in {"", "MM", "N/A", "NaN", "nan", "-999", "999.0", "999", "-99"}:
            return default
        return float(s)
    except (ValueError, TypeError):
        return default


def safe_int(value, default=None):
    try:
        if value is None:
            return default
        s = str(value).strip()
        if s in {"", "MM", "N/A", "NaN", "nan", "-999", "999", "-99"}:
            return default
        return int(float(s))
    except (ValueError, TypeError):
        return default


def format_value(value, suffix="", decimals=1, fallback="—"):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return fallback
    return f"{value:.{decimals}f}{suffix}"


def format_time_string(ts):
    if ts is None or pd.isna(ts):
        return "Time unavailable"
    try:
        return pd.to_datetime(ts).strftime("%b %d, %I:%M %p UTC")
    except Exception:
        return "Time unavailable"


def direction_to_compass(deg):
    if deg is None:
        return "—"
    dirs = [
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"
    ]
    idx = int((deg + 11.25) / 22.5) % 16
    return dirs[idx]


def swell_direction_hint(deg):
    if deg is None:
        return "Unknown direction"
    if 70 <= deg <= 140:
        return "E/SE swell angle"
    elif 141 <= deg <= 190:
        return "S swell angle"
    elif 191 <= deg <= 250:
        return "SW/W swell angle"
    elif 40 <= deg < 70:
        return "NE/E swell angle"
    return "Less direct Gulf angle"


def fetch_text(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (PensacolaSurfWatch)",
        "Accept": "text/plain, text/html, */*",
    }
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    return r.text


def parse_ndbc_realtime_text(text):
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("Empty NOAA response")

    header = None
    data_lines = []

    for line in lines:
        stripped = line.strip()

        # NOAA header often looks like:
        #YY  MM DD hh mm WDIR WSPD GST WVHT DPD APD MWD PRES ATMP WTMP DEWP VIS TIDE
        if stripped.startswith("#"):
            candidate = stripped.lstrip("#").strip()
            parts = candidate.split()
            if {"YY", "MM", "DD", "hh", "mm"}.issubset(set(parts)):
                header = parts
            continue

        data_lines.append(stripped)

    if header is None:
        raise ValueError("Could not find NOAA header row")

    rows = []
    for line in data_lines:
        parts = line.split()
        if len(parts) >= len(header):
            rows.append(parts[:len(header)])

    if not rows:
        raise ValueError("No valid data rows found in NOAA response")

    df = pd.DataFrame(rows, columns=header)

    required = ["YY", "MM", "DD", "hh", "mm"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")

    def build_timestamp(row):
        yy = safe_int(row["YY"])
        mm = safe_int(row["MM"])
        dd = safe_int(row["DD"])
        hh = safe_int(row["hh"])
        minute = safe_int(row["mm"])

        if None in (yy, mm, dd, hh, minute):
            return pd.NaT

        if yy < 100:
            yy += 2000

        try:
            return pd.Timestamp(year=yy, month=mm, day=dd, hour=hh, minute=minute, tz="UTC")
        except Exception:
            return pd.NaT

    df["timestamp"] = df.apply(build_timestamp, axis=1)

    numeric_cols = [
        "WVHT", "DPD", "APD", "MWD", "WDIR", "WSPD", "GST",
        "ATMP", "WTMP", "PRES", "BAR", "DEWP", "VIS", "TIDE"
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = df[col].apply(safe_float)

    df = df.dropna(subset=["timestamp"]).sort_values("timestamp", ascending=False).reset_index(drop=True)

    if df.empty:
        raise ValueError("All timestamps failed to parse")

    latest = df.iloc[0].to_dict()
    latest["history"] = df
    return latest


@st.cache_data(ttl=900)
def get_buoy_data(station_id):
    url = f"https://www.ndbc.noaa.gov/data/realtime2/{station_id}.txt"
    text = fetch_text(url)
    return parse_ndbc_realtime_text(text)


def extract_tag(text, tag):
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else None


def parse_rss_pubdate(pub_date):
    if not pub_date:
        return None
    try:
        dt = parsedate_to_datetime(pub_date)
        return dt.strftime("%b %d, %I:%M %p %Z")
    except Exception:
        return pub_date


@st.cache_data(ttl=900)
def get_station_rss(url, fallback_id):
    try:
        text = fetch_text(url)

        title_matches = re.findall(r"<title>(.*?)</title>", text, re.DOTALL | re.IGNORECASE)
        title = title_matches[1].strip() if len(title_matches) > 1 else fallback_id

        pub_date = extract_tag(text, "pubDate")
        description = extract_tag(text, "description")

        return {
            "station_id": fallback_id,
            "title": title,
            "pub_date": parse_rss_pubdate(pub_date),
            "description": description,
        }
    except Exception:
        return {
            "station_id": fallback_id,
            "title": fallback_id,
            "pub_date": None,
            "description": None,
        }


def wind_comment(wdir, wspd):
    if wdir is None or wspd is None:
        return "Wind data unavailable."

    if wdir >= 315 or wdir <= 45:
        flow = "more offshore/favorable"
    elif 46 <= wdir <= 90 or 271 <= wdir < 315:
        flow = "more sideshore/mixed"
    elif 91 <= wdir <= 225:
        flow = "more onshore/unfavorable"
    else:
        flow = "mixed"

    if wspd < 6:
        strength = "light"
    elif wspd < 12:
        strength = "moderate"
    else:
        strength = "strong"

    return f"{strength.capitalize()} {direction_to_compass(wdir)} wind, {flow} for local surf."


def score_surf(buoy_data_list):
    valid = [b for b in buoy_data_list if b is not None]
    if not valid:
        return {
            "headline": "No buoy data available",
            "body": "Could not build a local outlook from offshore buoy data right now."
        }

    heights = [b.get("WVHT") for b in valid if b.get("WVHT") is not None]
    periods = [b.get("DPD") for b in valid if b.get("DPD") is not None]
    dirs = [b.get("MWD") for b in valid if b.get("MWD") is not None]

    avg_h = sum(heights) / len(heights) if heights else None
    avg_p = sum(periods) / len(periods) if periods else None
    avg_d = sum(dirs) / len(dirs) if dirs else None

    if avg_h is None or avg_p is None:
        return {
            "headline": "Incomplete buoy picture",
            "body": "There is some offshore data, but not enough to build a clean outlook."
        }

    if avg_h >= 4 and avg_p >= 7:
        headline = "Most likely rideable"
        body = (
            f"Offshore Gulf energy looks more real than background chop right now, "
            f"with average swell around {avg_h:.1f} ft at {avg_p:.1f}s."
        )
    elif avg_h >= 2.5 and avg_p >= 6:
        headline = "Possible small surf"
        body = (
            f"There is at least some Gulf energy to watch, averaging about "
            f"{avg_h:.1f} ft at {avg_p:.1f}s offshore."
        )
    else:
        headline = "Likely weak / marginal"
        body = (
            f"Offshore energy looks limited right now, averaging roughly "
            f"{avg_h:.1f} ft at {avg_p:.1f}s."
        )

    if avg_d is not None:
        body += (
            f" Mean swell direction is around {avg_d:.0f}° "
            f"({direction_to_compass(avg_d)}), which reads as "
            f"{swell_direction_hint(avg_d).lower()}."
        )

    return {
        "headline": headline,
        "body": body
    }


def render_buoy_card(name, station_id, data):
    with st.container(border=True):
        st.markdown(f"### {name}")
        st.caption(f"Buoy {station_id}")

        if not data:
            st.error("No buoy data available.")
            st.markdown("**Latest update:** Unavailable")
            return

        timestamp = data.get("timestamp")
        wvht = data.get("WVHT")
        dpd = data.get("DPD")
        mwd = data.get("MWD")

        c1, c2, c3 = st.columns(3)
        c1.metric("Wave Height", format_value(wvht, " ft"))
        c2.metric("Dominant Period", format_value(dpd, " s"))
        c3.metric(
            "Direction",
            f"{int(mwd)}° {direction_to_compass(mwd)}" if mwd is not None else "—"
        )

        st.markdown(f"**Latest update:** {format_time_string(timestamp)}")

        desc_bits = []
        if wvht is not None:
            desc_bits.append(f"{wvht:.1f} ft")
        if dpd is not None:
            desc_bits.append(f"{dpd:.1f}s")
        if mwd is not None:
            desc_bits.append(f"{int(mwd)}° ({direction_to_compass(mwd)})")

        if desc_bits:
            st.write(" | ".join(desc_bits))
        else:
            st.write("Limited offshore data available.")


def render_station_card(station_name, station_data):
    with st.container(border=True):
        st.markdown(f"### {station_name}")

        if not station_data:
            st.error("No recent reports.")
            return

        title = station_data.get("title") or station_data.get("station_id") or station_name
        pub_date = station_data.get("pub_date")
        description = station_data.get("description")

        st.caption(title)
        st.markdown(f"**Latest update:** {pub_date if pub_date else 'Unavailable'}")

        if description:
            st.write(description)
        else:
            st.write("No recent reports.")


# =========================
# DATA LOAD
# =========================
buoy_results = []
buoy_errors = []

for buoy in BUOYS:
    try:
        data = get_buoy_data(buoy["id"])
        buoy_results.append(
            {
                "id": buoy["id"],
                "name": buoy["name"],
                "data": data,
            }
        )
    except Exception as e:
        buoy_results.append(
            {
                "id": buoy["id"],
                "name": buoy["name"],
                "data": None,
            }
        )
        buoy_errors.append(f'{buoy["id"]}: {str(e)}')

station_results = []
for station in STATIONS:
    station_results.append(
        {
            "name": station["name"],
            "data": get_station_rss(station["url"], station["fallback_id"]),
        }
    )


# =========================
# OFFSHORE BUOY SNAPSHOT
# =========================
st.subheader("Offshore Buoy Snapshot")

with st.expander("What do these buoy cards mean?", expanded=False):
    st.markdown(
        """
        **Buoy cards are offshore indicators for incoming Gulf swell energy.**  
        They help track direction and swell period to show trends in the Gulf

        **They'll Tell You:**
        - Is energy in the Gulf?
        - What direction is it coming from?
        - Use them to start your own local surf forecasting

        The actual surf report is in the **Pensacola Surf Outlook** section below.
        **COMING SOON**
        """
    )

buoy_cols = st.columns(len(buoy_results))
for col, buoy in zip(buoy_cols, buoy_results):
    with col:
        render_buoy_card(buoy["name"], buoy["id"], buoy["data"])


# =========================
# PENSACOLA SURF OUTLOOK
# =========================
st.subheader("Pensacola Surf Outlook")

outlook = score_surf([b["data"] for b in buoy_results])

st.info(outlook["headline"])
st.write(outlook["body"])

best_local_wind_source = None
for b in buoy_results:
    data = b["data"]
    if data and data.get("WDIR") is not None and data.get("WSPD") is not None:
        best_local_wind_source = data
        break

if best_local_wind_source:
    st.write(
        f"**Wind note:** {wind_comment(best_local_wind_source.get('WDIR'), best_local_wind_source.get('WSPD'))}"
    )
else:
    st.write("**Wind note:** Wind data unavailable.")

st.caption(
    "Buoy cards are offshore indicators for incoming Gulf swell energy. "
    "They help track direction and swell period to show how the swell in the Gulf is trending"
)


# =========================
# LOCAL STATION REPORTS
# =========================
st.subheader("Local Station Reports")

station_cols = st.columns(len(station_results))
for col, station in zip(station_cols, station_results):
    with col:
        render_station_card(station["name"], station["data"])


# =========================
# DEBUG
# =========================
with st.expander("Show raw buoy table", expanded=False):
    raw_rows = []
    for item in buoy_results:
        data = item["data"]
        raw_rows.append(
            {
                "Buoy": item["id"],
                "Name": item["name"],
                "Timestamp": data.get("timestamp") if data else None,
                "WVHT_ft": data.get("WVHT") if data else None,
                "DPD_s": data.get("DPD") if data else None,
                "MWD_deg": data.get("MWD") if data else None,
                "WDIR_deg": data.get("WDIR") if data else None,
                "WSPD_kt": data.get("WSPD") if data else None,
                "GST_kt": data.get("GST") if data else None,
                "ATMP_C": data.get("ATMP") if data else None,
                "WTMP_C": data.get("WTMP") if data else None,
                "PRES_hPa": data.get("PRES") if data else None,
            }
        )
    st.dataframe(pd.DataFrame(raw_rows), use_container_width=True)

if buoy_errors:
    with st.expander("Buoy fetch/debug errors", expanded=False):
        for err in buoy_errors:
            st.code(err)
