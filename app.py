import math
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Pensacola Surf Watch", layout="wide")


# -----------------------------
# CONFIG
# -----------------------------
STATIONS = {
    "42001": {
        "label": "42001",
        "name": "Mid Gulf",
        "subtitle": "180 nm S of Southwest Pass, LA",
        "role": "Upstream gulf energy",
    },
    "42012": {
        "label": "42012",
        "name": "Orange Beach",
        "subtitle": "44 nm SE of Mobile, AL",
        "role": "Closest directional / local read",
    },
    "42040": {
        "label": "42040",
        "name": "Dauphin Island",
        "subtitle": "63 nm S of Dauphin Island, AL",
        "role": "Western Gulf support read",
    },
}

NDBC_TEXT_URL = "https://www.ndbc.noaa.gov/data/realtime2/{station}.txt"
NDBC_STD_PAGE = "https://www.ndbc.noaa.gov/station_page.php?station={station}"

REQUEST_TIMEOUT = 20


# -----------------------------
# STYLING
# -----------------------------
st.markdown(
    """
    <style>
    .main {
        padding-top: 1.2rem;
    }
    .hero {
        padding: 1rem 1.2rem;
        border-radius: 18px;
        background: linear-gradient(135deg, #0f172a 0%, #132238 55%, #18314f 100%);
        color: white;
        border: 1px solid rgba(255,255,255,0.08);
        margin-bottom: 1rem;
    }
    .hero h1 {
        margin: 0;
        font-size: 2rem;
    }
    .hero p {
        margin: 0.35rem 0 0 0;
        color: rgba(255,255,255,0.82);
    }
    .section-title {
        font-size: 1.15rem;
        font-weight: 700;
        margin-top: 0.35rem;
        margin-bottom: 0.5rem;
    }
    .score-card {
        border-radius: 18px;
        padding: 1rem 1.1rem;
        background: #111827;
        color: white;
        border: 1px solid rgba(255,255,255,0.08);
        min-height: 180px;
    }
    .score-label {
        font-size: 0.9rem;
        opacity: 0.8;
        margin-bottom: 0.35rem;
    }
    .score-grade {
        font-size: 2rem;
        font-weight: 800;
        line-height: 1;
        margin-bottom: 0.35rem;
    }
    .score-sub {
        font-size: 0.95rem;
        opacity: 0.9;
        margin-bottom: 0.6rem;
    }
    .pill {
        display: inline-block;
        padding: 0.25rem 0.6rem;
        border-radius: 999px;
        font-size: 0.78rem;
        font-weight: 700;
        margin-right: 0.35rem;
        margin-bottom: 0.35rem;
        background: rgba(255,255,255,0.09);
        border: 1px solid rgba(255,255,255,0.08);
    }
    .station-card {
        border-radius: 16px;
        padding: 0.95rem 1rem;
        background: #f8fafc;
        border: 1px solid #e5e7eb;
        min-height: 240px;
    }
    .station-top {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        gap: 0.5rem;
    }
    .station-name {
        font-size: 1.05rem;
        font-weight: 700;
        margin: 0;
    }
    .station-role {
        font-size: 0.8rem;
        color: #475569;
        margin-top: 0.15rem;
    }
    .station-time {
        font-size: 0.78rem;
        color: #64748b;
    }
    .metric-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 0.55rem 0.8rem;
        margin-top: 0.8rem;
    }
    .metric {
        padding: 0.55rem 0.65rem;
        border-radius: 12px;
        background: white;
        border: 1px solid #e5e7eb;
    }
    .metric-label {
        font-size: 0.74rem;
        color: #64748b;
        margin-bottom: 0.15rem;
    }
    .metric-value {
        font-size: 1rem;
        font-weight: 700;
        color: #0f172a;
    }
    .small-note {
        color: #64748b;
        font-size: 0.86rem;
    }
    .footer-note {
        margin-top: 1rem;
        color: #64748b;
        font-size: 0.84rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# -----------------------------
# HELPERS
# -----------------------------
def safe_float(value):
    try:
        if value in [None, "MM", "NaN", "nan", ""]:
            return None
        return float(value)
    except Exception:
        return None


def now_utc():
    return datetime.now(timezone.utc)


def direction_to_compass(deg):
    if deg is None:
        return "—"
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    idx = round(deg / 22.5) % 16
    return dirs[idx]


def format_ft(meters):
    if meters is None:
        return "—"
    return f"{meters * 3.28084:.1f} ft"


def format_c_to_f(c):
    if c is None:
        return "—"
    return f"{(c * 9/5) + 32:.0f}°F"


def format_mps_to_mph(mps):
    if mps is None:
        return "—"
    return f"{mps * 2.23694:.1f} mph"


def parse_ndbc_datetime(row):
    # realtime2 typically has YY MM DD hhmm
    try:
        yy = int(row["YY"])
        mm = int(row["MM"])
        dd = int(row["DD"])
        hhmm = str(row["hhmm"]).zfill(4)
        hh = int(hhmm[:2])
        minute = int(hhmm[2:])
        year = 2000 + yy if yy < 100 else yy
        return datetime(year, mm, dd, hh, minute, tzinfo=timezone.utc)
    except Exception:
        return None


@st.cache_data(ttl=900, show_spinner=False)
def fetch_station_df(station):
    url = NDBC_TEXT_URL.format(station=station)
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    lines = response.text.splitlines()
    cleaned = [line for line in lines if line.strip()]

    # NDBC files usually begin with two header lines starting with '#'
    # First header line has the column names.
    if not cleaned or not cleaned[0].startswith("#"):
        raise ValueError(f"Unexpected file format for station {station}")

    header = cleaned[0].replace("#", "").split()
    data_lines = []
    for line in cleaned[1:]:
        if line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) == len(header):
            data_lines.append(parts)

    if not data_lines:
        raise ValueError(f"No rows found for station {station}")

    df = pd.DataFrame(data_lines, columns=header)

    numeric_cols = [
        "WDIR", "WSPD", "GST", "WVHT", "DPD", "APD", "MWD",
        "PRES", "ATMP", "WTMP", "DEWP"
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = df[col].apply(safe_float)

    df["obs_time"] = df.apply(parse_ndbc_datetime, axis=1)
    df = df.dropna(subset=["obs_time"]).sort_values("obs_time", ascending=False).reset_index(drop=True)

    return df


def get_station_snapshot(station):
    df = fetch_station_df(station)
    latest = df.iloc[0].to_dict()
    latest["station"] = station
    latest["df"] = df
    return latest


def direction_band_score(deg):
    """
    Pensacola-ish directional weighting for incoming Gulf energy.
    Returns 0 to 1.
    """
    if deg is None:
        return 0.25

    # Best: ESE to S
    if 110 <= deg <= 180:
        return 1.00
    # Pretty decent shoulder zone
    if 90 <= deg < 110 or 180 < deg <= 200:
        return 0.72
    # Marginal wrap / weak usefulness
    if 75 <= deg < 90 or 200 < deg <= 220:
        return 0.42
    # Usually poor for your setup
    return 0.12


def period_score(seconds):
    if seconds is None:
        return 0.15
    if seconds >= 8:
        return 1.00
    if seconds >= 7:
        return 0.82
    if seconds >= 6:
        return 0.58
    if seconds >= 5:
        return 0.34
    return 0.12


def height_score(ft):
    if ft is None:
        return 0.20
    if ft >= 4.0:
        return 1.00
    if ft >= 3.0:
        return 0.82
    if ft >= 2.0:
        return 0.60
    if ft >= 1.2:
        return 0.35
    return 0.15


def local_wind_penalty(wind_dir, wind_speed_mps):
    """
    Lower penalty = better.
    We treat W/NW/NNW/N as cleaner for Pensacola-ish beachbreak,
    and E/SE/S as worse. This is intentionally simple.
    Returns 0 to 1, where 1 = best.
    """
    if wind_dir is None or wind_speed_mps is None:
        return 0.55

    mph = wind_speed_mps * 2.23694

    # Offshore / cleaner quadrants
    if 270 <= wind_dir <= 360 or 0 <= wind_dir <= 20:
        base = 1.0
    elif 230 <= wind_dir < 270:
        base = 0.8
    elif 20 < wind_dir <= 70:
        base = 0.45
    elif 70 < wind_dir <= 180:
        base = 0.18
    else:
        base = 0.35

    # Stronger wind hurts if not good direction, but light offshore is okay
    if mph <= 5:
        speed_adj = 0.0
    elif mph <= 10:
        speed_adj = -0.03
    elif mph <= 15:
        speed_adj = -0.08
    else:
        speed_adj = -0.15

    return max(0.0, min(1.0, base + speed_adj))


def weighted_value(values, weights):
    pairs = [(v, w) for v, w in zip(values, weights) if v is not None]
    if not pairs:
        return None
    total_w = sum(w for _, w in pairs)
    if total_w == 0:
        return None
    return sum(v * w for v, w in pairs) / total_w


def build_surf_outlook(snapshots):
    s42001 = snapshots.get("42001")
    s42012 = snapshots.get("42012")
    s42040 = snapshots.get("42040")

    # Use upstream + nearer buoy. Favor 42012 and 42001.
    wave_dirs = [
        s42001.get("MWD") if s42001 else None,
        s42012.get("MWD") if s42012 else None,
        s42040.get("MWD") if s42040 else None,
    ]
    dir_weights = [0.35, 0.45, 0.20]
    blended_dir = weighted_value(wave_dirs, dir_weights)

    periods = [
        s42001.get("DPD") if s42001 else None,
        s42012.get("DPD") if s42012 else None,
        s42040.get("DPD") if s42040 else None,
    ]
    period_weights = [0.45, 0.40, 0.15]
    blended_period = weighted_value(periods, period_weights)

    heights_ft = [
        (s42001.get("WVHT") * 3.28084) if s42001 and s42001.get("WVHT") is not None else None,
        (s42012.get("WVHT") * 3.28084) if s42012 and s42012.get("WVHT") is not None else None,
        (s42040.get("WVHT") * 3.28084) if s42040 and s42040.get("WVHT") is not None else None,
    ]
    height_weights = [0.35, 0.45, 0.20]
    blended_height_ft = weighted_value(heights_ft, height_weights)

    # Use 42012 as the local-ish wind read if available, else 42040
    local_wind_dir = None
    local_wind_speed = None
    if s42012:
        local_wind_dir = s42012.get("WDIR")
        local_wind_speed = s42012.get("WSPD")
    elif s42040:
        local_wind_dir = s42040.get("WDIR")
        local_wind_speed = s42040.get("WSPD")

    dir_component = direction_band_score(blended_dir)
    period_component = period_score(blended_period)
    height_component = height_score(blended_height_ft)
    wind_component = local_wind_penalty(local_wind_dir, local_wind_speed)

    raw_score = (
        dir_component * 0.34
        + period_component * 0.28
        + height_component * 0.22
        + wind_component * 0.16
    )

    score_pct = int(round(raw_score * 100))

    if score_pct >= 78:
        grade = "Good"
        summary = "Worth a look if local sandbars cooperate."
    elif score_pct >= 58:
        grade = "Fair"
        summary = "Some usable energy, but still watch local wind and bars."
    elif score_pct >= 38:
        grade = "Marginal"
        summary = "More signal than promise. Keep expectations realistic."
    else:
        grade = "Poor"
        summary = "Probably weak, sloppy, blocked, or mostly weather-not-surf."

    reasons = []

    if blended_dir is not None:
        d = int(round(blended_dir))
        if 110 <= blended_dir <= 180:
            reasons.append(f"Wave direction is favorable ({d}° / {direction_to_compass(blended_dir)}).")
        elif 90 <= blended_dir <= 200:
            reasons.append(f"Wave direction is somewhat workable ({d}° / {direction_to_compass(blended_dir)}).")
        else:
            reasons.append(f"Wave direction is not ideal ({d}° / {direction_to_compass(blended_dir)}).")

    if blended_period is not None:
        reasons.append(f"Dominant period is around {blended_period:.1f}s.")

    if blended_height_ft is not None:
        reasons.append(f"Regional buoy energy is about {blended_height_ft:.1f} ft.")

    if local_wind_dir is not None and local_wind_speed is not None:
        reasons.append(
            f"Nearest wind read: {direction_to_compass(local_wind_dir)} at {local_wind_speed * 2.23694:.1f} mph."
        )

    return {
        "score_pct": score_pct,
        "grade": grade,
        "summary": summary,
        "blended_dir": blended_dir,
        "blended_period": blended_period,
        "blended_height_ft": blended_height_ft,
        "local_wind_dir": local_wind_dir,
        "local_wind_speed": local_wind_speed,
        "reasons": reasons,
    }


def age_label(obs_time):
    if obs_time is None:
        return "Time unknown"

    delta = now_utc() - obs_time
    hours = delta.total_seconds() / 3600

    if hours < 1:
        mins = max(1, int(delta.total_seconds() // 60))
        return f"{mins} min ago"
    if hours < 48:
        return f"{int(round(hours))} hr ago"
    return f"{int(round(hours / 24))} days ago"


def freshness_badge(obs_time):
    if obs_time is None:
        return "Unknown"
    hours = (now_utc() - obs_time).total_seconds() / 3600
    if hours <= 6:
        return "Fresh"
    if hours <= 24:
        return "Recent"
    if hours <= 72:
        return "Stale-ish"
    return "Old"


def build_station_card_html(snapshot, meta):
    obs_time = snapshot.get("obs_time")
    when = obs_time.strftime("%Y-%m-%d %H:%M UTC") if obs_time else "Unknown"
    fresh = freshness_badge(obs_time)

    wave_dir = snapshot.get("MWD")
    wind_dir = snapshot.get("WDIR")

    html = f"""
    <div class="station-card">
        <div class="station-top">
            <div>
                <div class="station-name">{meta['label']} • {meta['name']}</div>
                <div class="station-role">{meta['subtitle']} • {meta['role']}</div>
            </div>
            <div class="station-time">{fresh}</div>
        </div>

        <div class="small-note" style="margin-top:0.55rem;">
            Last reading: {when} ({age_label(obs_time)})
        </div>

        <div class="metric-grid">
            <div class="metric">
                <div class="metric-label">Wave height</div>
                <div class="metric-value">{format_ft(snapshot.get('WVHT'))}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Dominant period</div>
                <div class="metric-value">{f"{snapshot.get('DPD'):.1f} s" if snapshot.get('DPD') is not None else "—"}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Wave direction</div>
                <div class="metric-value">{f"{int(round(wave_dir))}° {direction_to_compass(wave_dir)}" if wave_dir is not None else "—"}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Wind</div>
                <div class="metric-value">
                    {f"{direction_to_compass(wind_dir)} {format_mps_to_mph(snapshot.get('WSPD'))}" if snapshot.get('WSPD') is not None else "—"}
                </div>
            </div>
            <div class="metric">
                <div class="metric-label">Water temp</div>
                <div class="metric-value">{format_c_to_f(snapshot.get('WTMP'))}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Pressure</div>
                <div class="metric-value">{f"{snapshot.get('PRES'):.1f} mb" if snapshot.get('PRES') is not None else "—"}</div>
            </div>
        </div>
    </div>
    """
    return html


def color_for_grade(grade):
    if grade == "Good":
        return "#14532d"
    if grade == "Fair":
        return "#92400e"
    if grade == "Marginal":
        return "#9a3412"
    return "#7f1d1d"


# -----------------------------
# HEADER
# -----------------------------
st.markdown(
    """
    <div class="hero">
        <h1>Pensacola Surf Watch</h1>
        <p>
            Upstream Gulf buoy dashboard with one combined Pensacola-area surf outlook.
            Buoys are treated as evidence, not as individual surf forecasts.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

left_top, right_top = st.columns([3, 1])
with left_top:
    st.caption("Wave direction shown here is the direction waves are coming from.")
with right_top:
    if st.button("Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


# -----------------------------
# DATA LOAD
# -----------------------------
snapshots = {}
errors = {}

for station, meta in STATIONS.items():
    try:
        snapshots[station] = get_station_snapshot(station)
    except Exception as e:
        errors[station] = str(e)

if not snapshots:
    st.error("Could not load any buoy data right now.")
    st.stop()


# -----------------------------
# SURF OUTLOOK
# -----------------------------
outlook = build_surf_outlook(snapshots)
grade_color = color_for_grade(outlook["grade"])

st.markdown('<div class="section-title">Pensacola-area surf outlook</div>', unsafe_allow_html=True)

col1, col2 = st.columns([1.15, 2.2])

with col1:
    st.markdown(
        f"""
        <div class="score-card" style="background:{grade_color};">
            <div class="score-label">Combined outlook</div>
            <div class="score-grade">{outlook["grade"]}</div>
            <div class="score-sub">{outlook["score_pct"]}/100</div>
            <div style="font-size:0.95rem; line-height:1.45;">{outlook["summary"]}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with col2:
    pills = []
    if outlook["blended_dir"] is not None:
        pills.append(
            f'<span class="pill">Direction: {int(round(outlook["blended_dir"]))}° {direction_to_compass(outlook["blended_dir"])}</span>'
        )
    if outlook["blended_period"] is not None:
        pills.append(f'<span class="pill">Period: {outlook["blended_period"]:.1f}s</span>')
    if outlook["blended_height_ft"] is not None:
        pills.append(f'<span class="pill">Energy: {outlook["blended_height_ft"]:.1f} ft</span>')
    if outlook["local_wind_dir"] is not None and outlook["local_wind_speed"] is not None:
        pills.append(
            f'<span class="pill">Nearest wind: {direction_to_compass(outlook["local_wind_dir"])} {outlook["local_wind_speed"]*2.23694:.1f} mph</span>'
        )

    st.markdown("".join(pills), unsafe_allow_html=True)

    for reason in outlook["reasons"]:
        st.write(f"• {reason}")

    st.caption(
        "This score weights wave direction, period, regional energy, and nearest wind. "
        "It is meant to think more like a local check than a generic weather report."
    )


# -----------------------------
# BUOY CARDS
# -----------------------------
st.markdown('<div class="section-title">Buoy observations</div>', unsafe_allow_html=True)

cols = st.columns(len(STATIONS))
for i, (station, meta) in enumerate(STATIONS.items()):
    with cols[i]:
        if station in snapshots:
            st.markdown(build_station_card_html(snapshots[station], meta), unsafe_allow_html=True)
            st.markdown(
                f"[Open NOAA station page]({NDBC_STD_PAGE.format(station=station)})",
                help="Open the official NDBC station page.",
            )
        else:
            st.error(f"{station}: unavailable")
            if station in errors:
                st.caption(errors[station])


# -----------------------------
# TRENDS
# -----------------------------
st.markdown('<div class="section-title">Recent trend</div>', unsafe_allow_html=True)

selected_station = st.selectbox(
    "Trend station",
    options=list(STATIONS.keys()),
    index=1 if "42012" in STATIONS else 0,
    format_func=lambda s: f"{s} • {STATIONS[s]['name']}",
)

trend_df = snapshots[selected_station]["df"].copy()

if not trend_df.empty:
    trend_df = trend_df.sort_values("obs_time").tail(36).copy()
    trend_df["wave_height_ft"] = trend_df["WVHT"].apply(lambda x: x * 3.28084 if x is not None else None)

    chart_cols = st.columns(3)

    with chart_cols[0]:
        st.metric(
            "Latest wave height",
            format_ft(snapshots[selected_station].get("WVHT")),
            help="Significant wave height at the buoy.",
        )
    with chart_cols[1]:
        dpd = snapshots[selected_station].get("DPD")
        st.metric(
            "Latest dominant period",
            f"{dpd:.1f} s" if dpd is not None else "—",
        )
    with chart_cols[2]:
        mwd = snapshots[selected_station].get("MWD")
        st.metric(
            "Latest wave direction",
            f"{int(round(mwd))}° {direction_to_compass(mwd)}" if mwd is not None else "—",
        )

    st.line_chart(
        trend_df.set_index("obs_time")[["wave_height_ft"]],
        use_container_width=True,
    )

    period_plot = trend_df.set_index("obs_time")[["DPD"]].copy()
    period_plot.columns = ["dominant_period_s"]
    st.line_chart(period_plot, use_container_width=True)

    if trend_df["MWD"].notna().any():
        dir_plot = trend_df.set_index("obs_time")[["MWD"]].copy()
        dir_plot.columns = ["wave_direction_deg_from"]
        st.line_chart(dir_plot, use_container_width=True)
else:
    st.info("No trend rows available for that station.")


# -----------------------------
# RAW TABLE
# -----------------------------
with st.expander("Show latest raw rows"):
    raw_rows = []
    for station, snap in snapshots.items():
        raw_rows.append({
            "station": station,
            "name": STATIONS[station]["name"],
            "obs_time_utc": snap.get("obs_time"),
            "WVHT_m": snap.get("WVHT"),
            "WVHT_ft": round(snap.get("WVHT") * 3.28084, 2) if snap.get("WVHT") is not None else None,
            "DPD_s": snap.get("DPD"),
            "APD_s": snap.get("APD"),
            "MWD_deg_from": snap.get("MWD"),
            "WDIR_deg_from": snap.get("WDIR"),
            "WSPD_mps": snap.get("WSPD"),
            "WTMP_c": snap.get("WTMP"),
            "PRES_mb": snap.get("PRES"),
        })
    st.dataframe(pd.DataFrame(raw_rows), use_container_width=True)


# -----------------------------
# FOOTER
# -----------------------------
st.markdown(
    """
    <div class="footer-note">
        Notes: this app uses the latest available NDBC realtime text rows and does not hide a buoy just because it
        missed a recent report window. The buoy cards are raw observations. The only "forecast-style" judgment lives in the
        single combined Pensacola outlook card.
    </div>
    """,
    unsafe_allow_html=True,
)
