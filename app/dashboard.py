import os
import time
import requests
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dotenv import load_dotenv

load_dotenv()

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY", "dev-key-change-me")

st.set_page_config(
    page_title="Carrier Sales Dashboard",
    page_icon="🚛",
    layout="wide"
)

def fetch_data(endpoint: str):
    try:
        r = requests.get(
            f"{API_BASE}{endpoint}",
            headers={"x-api-key": API_KEY},
            timeout=10
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"Error fetching data: {e}")
        return None

# ── Header ──
st.title("🚛 Carrier Load Sales Dashboard")
st.caption("Real-time metrics from inbound carrier calls")

# Auto-refresh toggle
auto_refresh = st.sidebar.toggle("Auto-refresh (30s)", value=True)
if st.sidebar.button("🔄 Refresh now"):
    st.rerun()

# ── Fetch data ──
stats = fetch_data("/api/stats")
calls_data = fetch_data("/api/calls?limit=500")

if not stats or stats.get("total_calls", 0) == 0:
    st.info("No calls recorded yet. Make a test call to see data here!")
    if auto_refresh:
        time.sleep(30)
        st.rerun()
    st.stop()

# ── KPI Row ──
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Total Calls", stats["total_calls"])
col2.metric("Avg Duration", f"{stats['avg_duration_seconds']}s")
col3.metric("Avg Latency (P70)", f"{stats['avg_latency_p70_ms']}ms")
col4.metric("Avg Negotiation Rounds", f"{stats['avg_negotiation_rounds']}")

# Booking rate
outcomes = stats.get("outcomes", {})
total_outcomes = sum(outcomes.values())
booked = outcomes.get("booked", 0) + outcomes.get("transferred_to_sales", 0)
booking_rate = round((booked / total_outcomes * 100), 1) if total_outcomes > 0 else 0
col5.metric("Booking Rate", f"{booking_rate}%")

# ── Charts Row 1 ──
chart1, chart2 = st.columns(2)

with chart1:
    st.subheader("Call Outcomes")
    if outcomes:
        fig = px.pie(
            names=list(outcomes.keys()),
            values=list(outcomes.values()),
            color_discrete_sequence=px.colors.qualitative.Set2
        )
        fig.update_layout(margin=dict(t=20, b=20, l=20, r=20))
        st.plotly_chart(fig, use_container_width=True)

with chart2:
    st.subheader("Carrier Sentiment")
    sentiments = stats.get("sentiments", {})
    if sentiments:
        colors = {"positive": "#2ecc71", "neutral": "#f39c12", "negative": "#e74c3c"}
        fig = px.bar(
            x=list(sentiments.keys()),
            y=list(sentiments.values()),
            color=list(sentiments.keys()),
            color_discrete_map=colors,
        )
        fig.update_layout(
            showlegend=False,
            margin=dict(t=20, b=20, l=20, r=20),
            xaxis_title="",
            yaxis_title="Count"
        )
        st.plotly_chart(fig, use_container_width=True)

# ── Charts Row 2 ──
if calls_data and calls_data.get("calls"):
    df = pd.DataFrame(calls_data["calls"])
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    chart3, chart4 = st.columns(2)

    with chart3:
        st.subheader("Calls Over Time")
        daily = df.set_index("timestamp").resample("D").size().reset_index(name="calls")
        fig = px.line(daily, x="timestamp", y="calls", markers=True)
        fig.update_layout(margin=dict(t=20, b=20, l=20, r=20))
        st.plotly_chart(fig, use_container_width=True)

    with chart4:
        st.subheader("Rate Analysis")
        rate_df = df[df["initial_rate_offered"].notna()].copy()
        if not rate_df.empty:
            for col in ["initial_rate_offered", "carrier_counter_offer", "final_agreed_rate"]:
                rate_df[col] = (
                    rate_df[col]
                    .astype(str)
                    .str.replace(r"[^\d.]", "", regex=True)
                    .apply(lambda x: float(x) if x else None)
                )
            fig = go.Figure()
            fig.add_trace(go.Bar(name="Loadboard Rate", x=rate_df["load_id"], y=rate_df["initial_rate_offered"]))
            fig.add_trace(go.Bar(name="Counter Offer", x=rate_df["load_id"], y=rate_df["carrier_counter_offer"]))
            fig.add_trace(go.Bar(name="Agreed Rate", x=rate_df["load_id"], y=rate_df["final_agreed_rate"]))
            fig.update_layout(barmode="group", margin=dict(t=20, b=20, l=20, r=20))
            st.plotly_chart(fig, use_container_width=True)

    # ── Call Log Table ──
    st.subheader("📋 Recent Calls")
    display_cols = [
        "timestamp", "mc_number", "carrier_name", "origin", "destination",
        "equipment_type", "initial_rate_offered", "carrier_counter_offer",
        "final_agreed_rate", "negotiation_rounds", "call_outcome",
        "carrier_sentiment", "duration"
    ]
    existing_cols = [c for c in display_cols if c in df.columns]
    st.dataframe(
        df[existing_cols].sort_values("timestamp", ascending=False),
        use_container_width=True,
        hide_index=True
    )

# ── Auto refresh ──
if auto_refresh:
    time.sleep(30)
    st.rerun()
