import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

st.set_page_config(page_title="Nifty Option Window", layout="centered")
st.title("Nifty Option Window")


def previous_weekday(d):
    """Previous Mon-Fri date before d (Monday -> Friday)."""
    d = d - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def get_trade_date(now):
    """
    Which trade date's data to read:
      - 8:30 PM onwards (till midnight): today's data
      - before 8:30 PM (e.g. 9 AM - 11 AM morning run): previous trading day's data
    Weekends are skipped (a Saturday/Sunday run uses Friday's data).
    """
    today = now.date()
    after_cutoff = (now.hour, now.minute) >= (20, 30)
    if after_cutoff and today.weekday() < 5:
        return today
    if today.weekday() >= 5:
        # Weekend: last trading day is the most recent Friday
        d = today
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        return d
    return previous_weekday(today)


def get_target_expiry_date(trade_date):
    """Target Tuesday expiry based on the trade date, formatted like '13-Oct-2026'."""
    wd = trade_date.weekday()  # Mon=0, Tue=1 ...
    if wd == 0:
        target = trade_date + timedelta(days=1)
    elif wd == 1:
        target = trade_date + timedelta(days=7)
    else:
        days = (1 - wd) % 7 or 7
        target = trade_date + timedelta(days=days)
    return target.strftime("%d-%b-%Y")


def parse_dates(series):
    """Parse dates like 12-Oct-2026 or 12-Oct-26."""
    s = series.astype(str).str.strip()
    d4 = pd.to_datetime(s, format="%d-%b-%Y", errors="coerce")
    d2 = pd.to_datetime(s, format="%d-%b-%y", errors="coerce")
    return d4.fillna(d2)


def round_half_up(x):
    """0.5 and above rounds up to next number, below 0.5 drops the decimal."""
    return int(x + 0.5)


def prime_value(total):
    return int(total / 2 + 0.5)


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

    # Pick the trade date: after 8:30 PM -> today, otherwise previous trading day
    df_raw["_trade_dt"] = parse_dates(df_raw["Date"])
    trade_date = get_trade_date(now)
    df_today = df_raw[df_raw["_trade_dt"].dt.date == trade_date].copy()
    if df_today.empty:
        latest = df_raw["_trade_dt"].max()
        if pd.isna(latest):
            raise ValueError("Could not read any valid dates from the 'Date' column.")
        st.warning(
            f"No rows found for {trade_date.strftime('%d-%b-%Y')}. "
            f"Using the latest date in the file instead: {latest.strftime('%d-%b-%Y')}.")
        trade_date = latest.date()
        df_today = df_raw[df_raw["_trade_dt"].dt.date == trade_date].copy()
    st.caption(f"Trade date used: {trade_date.strftime('%d-%b-%Y')}")

    # Expiry filter (based on the trade date, e.g. Monday data -> Tuesday expiry)
    exp4 = get_target_expiry_date(trade_date)
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
    records = {s: {"Strike": int(s), "CE": 0, "PE": 0} for s in selected}
    for _, row in df_100s[df_100s["Strike Price"].isin(selected)].iterrows():
        if row["Option Type"] in ("CE", "PE"):
            # Round CE/PE first; rounded values are used for all calculations
            records[row["Strike Price"]][row["Option Type"]] = round_half_up(row["Settlement Price"])

    df = pd.DataFrame(records.values()).sort_values("Strike", ascending=False).reset_index(drop=True)
    df["Total (CE + PE)"] = df["CE"] + df["PE"]
    df["Prime Value (Rounded)"] = df["Total (CE + PE)"].apply(prime_value)
    return df


uploaded = st.file_uploader("Upload bhavcopy CSV", type=["csv"])
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
