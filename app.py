"""
IciciDash - starter portfolio dashboard for ICICI Direct (Breeze API)

Run:
    pip install streamlit breeze-connect pandas plotly python-dotenv
    streamlit run app.py

Setup:
    1. Create an API app at the Breeze API portal -> get API key + secret.
    2. Put them in a .env file (never commit it):
           BREEZE_API_KEY=xxxx
           BREEZE_API_SECRET=xxxx
    3. The session token expires daily. Open the login URL shown in the
       sidebar, log in, and paste the token (from the redirect URL) into the app.
"""
import os
import urllib.parse
from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="IciciDash", layout="wide")
st.title("IciciDash - Portfolio Dashboard")

# ---------------------------------------------------------------- helpers
def to_num(series):
    return pd.to_numeric(series, errors="coerce").fillna(0.0)


def pick(df, *names):
    """Return the first column that exists (field names can vary by API version)."""
    for n in names:
        if n in df.columns:
            return df[n]
    return pd.Series([None] * len(df), index=df.index)


def normalize_holdings(raw):
    rows = (raw or {}).get("Success") or []
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    out = pd.DataFrame(
        {
            "symbol": pick(df, "stock_code", "stock_symbol"),
            "qty": to_num(pick(df, "quantity", "demat_total_bulk_quantity")),
            "avg_price": to_num(pick(df, "average_price")),
            "ltp": to_num(pick(df, "current_market_price")),
        }
    )
    out["invested"] = out.qty * out.avg_price
    out["current"] = out.qty * out.ltp
    out["pnl"] = out.current - out.invested
    out["pnl_pct"] = (out.pnl / out.invested.replace(0, pd.NA) * 100).astype(float)
    return out


@st.cache_data(ttl=60, show_spinner=False)
def fetch_holdings(api_key, secret, token):
    from breeze_connect import BreezeConnect

    b = BreezeConnect(api_key=api_key)
    b.generate_session(api_secret=secret, session_token=token)
    today = datetime.now()
    raw = b.get_portfolio_holdings(
        exchange_code="NSE",
        from_date=(today - timedelta(days=365)).strftime("%Y-%m-%dT06:00:00.000Z"),
        to_date=today.strftime("%Y-%m-%dT06:00:00.000Z"),
        stock_code="",
        portfolio_type="",
    )
    return raw


@st.cache_data(ttl=300, show_spinner=False)
def fetch_history(api_key, secret, token, symbol, days):
    from breeze_connect import BreezeConnect

    b = BreezeConnect(api_key=api_key)
    b.generate_session(api_secret=secret, session_token=token)
    end = datetime.now()
    res = b.get_historical_data_v2(
        interval="1day",
        from_date=(end - timedelta(days=days)).strftime("%Y-%m-%dT07:00:00.000Z"),
        to_date=end.strftime("%Y-%m-%dT07:00:00.000Z"),
        stock_code=symbol,
        exchange_code="NSE",
        product_type="cash",
    )
    df = pd.DataFrame((res or {}).get("Success") or [])
    if not df.empty:
        df["datetime"] = pd.to_datetime(df["datetime"])
        for c in ("open", "high", "low", "close"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Connection")
    api_key = st.text_input("API key", os.getenv("BREEZE_API_KEY", ""), type="password")
    secret = st.text_input("API secret", os.getenv("BREEZE_API_SECRET", ""), type="password")
    if api_key:
        st.markdown(
            "[1) Open login page]"
            f"(https://api.icicidirect.com/apiuser/login?api_key={urllib.parse.quote_plus(api_key)})"
        )
    token = st.text_input("2) Session token (changes daily)", type="password")
    st.divider()
    st.header("Or upload a CSV")
    st.caption("Columns: symbol, qty, avg_price, ltp")
    csv = st.file_uploader("Holdings CSV", type="csv")
    show_raw = st.checkbox("Show raw API response (debug)")

# ---------------------------------------------------------------- data
df = pd.DataFrame()
if csv is not None:
    df = pd.read_csv(csv)
    df["invested"] = df.qty * df.avg_price
    df["current"] = df.qty * df.ltp
    df["pnl"] = df.current - df.invested
    df["pnl_pct"] = df.pnl / df.invested * 100
elif api_key and secret and token:
    try:
        raw = fetch_holdings(api_key, secret, token)
        if show_raw:
            st.json(raw)
        df = normalize_holdings(raw)
    except Exception as e:
        st.error(f"Could not fetch holdings: {e}")
else:
    st.info("Enter your Breeze credentials + today's session token in the sidebar, or upload a CSV to try the dashboard.")

if df.empty:
    st.stop()

# ---------------------------------------------------------------- summary
inv, cur = df.invested.sum(), df.current.sum()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Invested", f"₹{inv:,.0f}")
c2.metric("Current value", f"₹{cur:,.0f}")
c3.metric("Total P&L", f"₹{cur - inv:,.0f}", f"{(cur - inv) / inv * 100:.2f}%" if inv else None)
c4.metric("Holdings", len(df))

# ---------------------------------------------------------------- charts
left, right = st.columns(2)
with left:
    st.subheader("Allocation")
    st.plotly_chart(px.pie(df, names="symbol", values="current", hole=0.45), use_container_width=True)
with right:
    st.subheader("P&L by stock")
    d = df.sort_values("pnl")
    st.plotly_chart(
        px.bar(d, x="pnl", y="symbol", orientation="h", color=d.pnl > 0,
               color_discrete_map={True: "#16a34a", False: "#dc2626"}).update_layout(showlegend=False),
        use_container_width=True,
    )

st.subheader("Holdings")
st.dataframe(
    df.sort_values("current", ascending=False).style.format(
        {"avg_price": "{:.2f}", "ltp": "{:.2f}", "invested": "{:,.0f}", "current": "{:,.0f}",
         "pnl": "{:,.0f}", "pnl_pct": "{:.2f}%"}
    ),
    use_container_width=True,
)

# ---------------------------------------------------------------- price chart
if api_key and secret and token:
    st.subheader("Price history")
    a, b_ = st.columns([2, 1])
    sym = a.selectbox("Stock", df.symbol.dropna().unique())
    days = b_.selectbox("Range (days)", [30, 90, 180, 365], index=2)
    try:
        h = fetch_history(api_key, secret, token, sym, days)
        if h.empty:
            st.warning("No history returned (check that the symbol is the ICICI stock code).")
        else:
            import plotly.graph_objects as go

            fig = go.Figure(go.Candlestick(x=h.datetime, open=h.open, high=h.high, low=h.low, close=h.close))
            fig.update_layout(xaxis_rangeslider_visible=False, height=450)
            st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.error(f"Could not fetch history: {e}")
