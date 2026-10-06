import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

st.set_page_config(page_title="Nifty Option Window", layout="centered")
st.title("Nifty Option Window")


def get_target_expiry_date(now):
    """Target Tuesday expiry, formatted like '13-Oct-2026'."""
    wd = now.weekday()  # Mon=0, Tue=1 ...
    if wd == 0:
        target = now + timedelta(days=1)
    elif wd == 1:
        target = now + timedelta(days=7)
    else:
        days = (1 - wd) % 7 or 7
        target = now + timedelta(days=days)
    return target.strftime("%d-%b-%Y")


def prime_value(total):
    half = total / 2
    rounded = int(half + 0.5) if half % 1 >= 0.5 else int(half)
    return f"{rounded} ({half:.2f})"


def process(df_raw, nifty_spot, now):
    df_raw = df_raw.copy()
    df_raw.columns = df_raw.columns.str.strip()

    for col in ["Strike Price", "Settlement Price", "Option Type", "Date", "Expiry Date"]:
        if col not in df_raw.columns:
            raise ValueError(f"Column '{col}' not found. Available: {list(df_raw.columns)}")

    df_raw["Strike Price"] = pd.to_numeric(
        df_raw["Strike Price"].astype(str).str.replace(",", ""), errors="coerce")
    df_raw["Settlement Price"] = pd.to_numeric(
        df_raw["Settlement Price"].astype(str).str.replace(",", ""), errors="coerce").fillna(0)
    df_raw["Option Type"] = df_raw["Option Type"].astype(str).str.strip()

    # Filter for today's trade date
    d4, d2 = now.strftime("%d-%b-%Y"), now.strftime("%d-%b-%y")
    df_raw["Date"] = df_raw["Date"].astype(str).str.strip()
    df_today = df_raw[df_raw["Date"].isin([d4, d2])].copy()
    if df_today.empty:
        st.warning(f"No rows found for trade date {d4}. Using the entire file.")
        df_today = df_raw.copy()

    # Expiry filter
    exp4 = get_target_expiry_date(now)
    exp2 = exp4[:-4] + exp4[-2:]
    df_today["Expiry Date"] = df_today["Expiry Date"].astype(str).str.strip()
    df_exp = df_today[df_today["Expiry Date"].isin([exp4, exp2])].copy()
    if df_exp.empty:
        raise ValueError(
            f"Target expiry '{exp4}' not found. "
            f"Available expiries: {list(df_today['Expiry Date'].unique())}")
    df_today = df_exp
    st.caption(f"Expiry used: {exp4}")

    # ATM and 100-interval strikes
    atm = round(nifty_spot / 100) * 100
    df_100s = df_today[df_today["Strike Price"] % 100 == 0].copy()
    strikes = sorted(df_100s["Strike Price"].dropna().unique())
    if not strikes:
        raise ValueError("No valid 100-interval strikes found.")
    if atm not in strikes:
        atm = min(strikes, key=lambda x: abs(x - atm))
    idx = strikes.index(atm)
    selected = strikes[max(0, idx - 4): min(len(strikes), idx + 5)]
    st.caption(f"ATM strike base: {int(atm)}")

    # Build table
    records = {s: {"Strike": int(s), "CE": 0.0, "PE": 0.0} for s in selected}
    for _, row in df_100s[df_100s["Strike Price"].isin(selected)].iterrows():
        if row["Option Type"] in ("CE", "PE"):
            records[row["Strike Price"]][row["Option Type"]] = row["Settlement Price"]

    df = pd.DataFrame(records.values()).sort_values("Strike", ascending=False).reset_index(drop=True)
    df["Total (CE + PE)"] = df["CE"] + df["PE"]
    df["Prime Value (Rounded)"] = df["Total (CE + PE)"].apply(prime_value)
    for c in ["CE", "PE", "Total (CE + PE)"]:
        df[c] = df[c].map("{:.2f}".format)
    return df


uploaded = st.file_uploader("Upload today's bhavcopy CSV", type=["csv"])
spot = st.number_input("Current NIFTY spot price", min_value=0.0, value=22700.0, step=1.0)
run = st.button("Generate", type="primary")

if run:
    if uploaded is None:
        st.error("Please upload the CSV file first.")
    else:
        try:
            now = datetime.now(IST)
            df_final = process(pd.read_csv(uploaded), spot, now)
            st.subheader("Final processed NIFTY option window")
            st.dataframe(df_final, hide_index=True, use_container_width=True)
            st.download_button(
                "Download CSV",
                df_final.to_csv(index=False).encode("utf-8"),
                file_name=f"Nifty_Final_Output_{now.strftime('%Y-%m-%d_%H%M%S')}.csv",
                mime="text/csv",
            )
        except Exception as e:
            st.error(str(e))
