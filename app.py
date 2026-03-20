from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Pensacola Surf Watch", layout="wide")


# -----------------------------
# CONFIG
# -----------------------------
STATIONS = {
    "42001": {"name": "Mid Gulf"},
    "42012": {"name": "Orange Beach"},
    "42040": {"name": "Dauphin Island"},
}

URL = "https://www.ndbc.noaa.gov/data/realtime2/{station}.txt"


# -----------------------------
# HELPERS
# -----------------------------
def safe_float(x):
    try:
        return float(x)
    except:
        return None


def parse_data(station):
    r = requests.get(URL.format(station=station), timeout=10)
    lines = r.text.split("\n")

    header = lines[0].replace("#", "").split()
    data = [l.split() for l in lines[2:] if len(l.split()) == len(header)]

    df = pd.DataFrame(data, columns=header)

    for col in ["WVHT", "DPD", "MWD", "WSPD", "WDIR"]:
        if col in df:
            df[col] = df[col].apply(safe_float)

    return df.iloc[0]


def deg_to_compass(d):
    if d is None:
        return "—"
    dirs = ["N","NE","E","SE","S","SW","W","NW"]
    return dirs[int((d+22.5)//45)%8]


# -----------------------------
# SURF LOGIC
# -----------------------------
def surf_score(buoys):
    dirs = []
    periods = []
    heights = []

    for b in buoys.values():
        if b is None:
            continue
        dirs.append(b.get("MWD"))
        periods.append(b.get("DPD"))
        heights.append(b.get("WVHT"))

    if not dirs:
        return "No Data"

    avg_dir = sum([d for d in dirs if d])/len([d for d in dirs if d])
    avg_period = sum([p for p in periods if p])/len([p for p in periods if p])
    avg_height = sum([h for h in heights if h])/len([h for h in heights if h])

    score = 0

    if 110 <= avg_dir <= 180:
        score += 40
    elif 90 <= avg_dir <= 200:
        score += 25
    else:
        score += 10

    if avg_period >= 7:
        score += 30
    elif avg_period >= 6:
        score += 20
    else:
        score += 10

    if avg_height >= 1:
        score += 30
    else:
        score += 10

    if score >= 80:
        return "Good"
    elif score >= 55:
        return "Fair"
    elif score >= 35:
        return "Marginal"
    else:
        return "Poor"


# -----------------------------
# HEADER
# -----------------------------
st.title("Pensacola Surf Watch")

st.caption(
    "Buoy cards are offshore indicators for incoming Gulf swell energy. "
    "They help track direction and swell period to show how the swell in the Gulf is trending"
)


# -----------------------------
# LOAD DATA
# -----------------------------
buoys = {}
for s in STATIONS:
    try:
        buoys[s] = parse_data(s)
    except:
        buoys[s] = None

if all(v is None for v in buoys.values()):
    st.error("Could not load any buoy data right now.")
    st.stop()


# -----------------------------
# BUOY CARDS
# -----------------------------
st.subheader("Buoy Observations")

cols = st.columns(3)

for i, (station, data) in enumerate(buoys.items()):
    with cols[i]:
        st.markdown(f"### {station} - {STATIONS[station]['name']}")

        st.markdown("""
- Is energy in the Gulf?
- What direction is it coming from?
- Use them to start your own local surf forecasting

The actual surf report is in the Pensacola Surf Outlook section below.
""")

        if data is None:
            st.write("No data")
        else:
            st.write(f"Wave Height: {data['WVHT']} m")
            st.write(f"Period: {data['DPD']} s")
            st.write(f"Direction: {data['MWD']}° {deg_to_compass(data['MWD'])}")
            st.write(f"Wind: {deg_to_compass(data['WDIR'])} {data['WSPD']} m/s")


# -----------------------------
# SURF OUTLOOK
# -----------------------------
st.subheader("Pensacola Surf Outlook")

result = surf_score(buoys)

st.markdown(f"## {result}")
