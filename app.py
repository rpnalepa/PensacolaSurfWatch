import pandas as pd
import streamlit as st

st.set_page_config(page_title="Pensacola Surf Watch", layout="wide")

st.title("Pensacola Surf Watch")
st.caption("Simple local buoy dashboard")

data = {
    "Buoy": ["42039", "42040", "42012"],
    "Wave Height (ft)": [2.1, 1.8, 2.7],
    "Period (s)": [5, 6, 7],
    "Wind (kt)": [12, 10, 15]
}

df = pd.DataFrame(data)

st.subheader("Current Conditions")
st.dataframe(df, use_container_width=True)

st.subheader("Quick Read")
best_buoy = df.loc[df["Wave Height (ft)"].idxmax(), "Buoy"]
st.write(f"Best looking buoy right now: **{best_buoy}**")