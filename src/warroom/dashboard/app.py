"""Streamlit interactive dashboard for the Autonomous AI Supply Chain War Room."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any
import pandas as pd
import streamlit as st

# Ensure repository root src/ directory is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from warroom.dashboard.data import (
    ensure_data,
    load_a2a_log,
    load_timeline,
    messages_df,
    network_frame,
    po_df,
    sku_df,
    timeline_df,
)
from warroom.dashboard.figures import (
    agent_timeline,
    exposure_trajectory,
    po_breakdown,
    sku_risk,
    supply_network,
)
from warroom.db.session import get_session
from warroom.replanning.engine import ReplanEngine
from warroom.replanning.scenario import default_scenario

DEFAULT_OUT_DIR = PROJECT_ROOT / "data" / "replan"

st.set_page_config(
    page_title="Autonomous AI Supply Chain War Room",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data
def get_cached_data(out_dir_str: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load or generate timeline and A2A log data."""
    tl_path, log_path = ensure_data(out_dir_str)
    snapshots = load_timeline(tl_path)
    log = load_a2a_log(log_path)
    return snapshots, log


@st.cache_data
def get_cached_network_frame(
    snapshot_dict: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute network layout using a temporary session created and closed inside."""
    session = get_session()
    try:
        return network_frame(session, snapshot_dict)
    finally:
        session.close()


def format_compact_money(amount: float) -> str:
    """Format a dollar amount in compact form ($356.7K, $83.4K, $1.2M, $0.00)."""
    abs_amt = abs(amount)
    sign = "-" if amount < 0 else ""
    if abs_amt >= 1_000_000:
        return f"{sign}${abs_amt / 1_000_000:.1f}M"
    elif abs_amt >= 1_000:
        return f"{sign}${abs_amt / 1_000:.1f}K"
    else:
        return f"{sign}${abs_amt:,.2f}"


def format_money_delta(amount: float | None) -> str | None:
    """Format money delta with sign first (-$4,093.14, +$2,270.70, $0.00)."""
    if amount is None:
        return None
    if abs(amount) < 0.005:
        return "$0.00"
    elif amount < 0:
        return f"-${abs(amount):,.2f}"
    else:
        return f"+${amount:,.2f}"


def format_count_delta(count: int | float | None) -> str | None:
    """Format count delta with thousands separators (+4,270, -11,510, 0)."""
    if count is None:
        return None
    val = int(round(count))
    if val < 0:
        return f"-{abs(val):,}"
    elif val > 0:
        return f"+{val:,}"
    else:
        return "0"


def main() -> None:
    # 1. Load Data
    snapshots, a2a_log = get_cached_data(str(DEFAULT_OUT_DIR))
    if not snapshots:
        st.error("No timeline snapshots found. Please click 'Re-run scenario' in the sidebar.")
        return

    # 2. Sidebar Controls
    st.sidebar.title("⚡ War Room Controls")

    version_options = [f"v{s['version']} · day {s['day']}" for s in snapshots]
    selected_label = st.sidebar.select_slider(
        "Select Plan Version",
        options=version_options,
        value=version_options[0],
        help="Step through the timeline to see how the multi-agent system adapted to new events.",
    )
    selected_idx = version_options.index(selected_label)
    curr_snap = snapshots[selected_idx]
    prev_snap = snapshots[selected_idx - 1] if selected_idx > 0 else None

    st.sidebar.divider()

    # Re-run Scenario Button
    if st.sidebar.button("🔄 Re-run scenario", use_container_width=True):
        with st.spinner("Re-executing replanning scenario against real database..."):
            session = get_session()
            try:
                engine = ReplanEngine(session)
                events = default_scenario()
                new_snaps = engine.run(events)
                engine.write_outputs(new_snaps, DEFAULT_OUT_DIR)
                st.cache_data.clear()
                st.sidebar.success("Scenario re-run and outputs refreshed successfully!")
            finally:
                session.close()
            st.rerun()

    st.sidebar.divider()
    st.sidebar.subheader("About the System")
    st.sidebar.markdown(
        """
        The **Autonomous AI Supply Chain War Room** is a deterministic, multi-agent operational
        command center coordinating response planning for critical supply chain disruptions.

        - **LangGraph**: 6 specialized agents (Supplier, Inventory, Logistics, Demand, Procurement, Customer Impact).
        - **A2A Bus**: In-process Agent-to-Agent communication with task lifecycles and escalation protocols.
        - **Dynamic Replanning**: Timeline event simulator adapting routing, capacity allocations, and freight modes.
        """
    )

    # 3. Main Dashboard Header
    st.title("⚡ Autonomous AI Supply Chain War Room")
    day = curr_snap.get("day", 0)
    version = curr_snap.get("version", 1)
    status = curr_snap.get("status", "replanned").upper()
    triggers = curr_snap.get("trigger_events", [])
    trig_summary = "; ".join(triggers) if triggers else "Baseline condition"

    st.caption(
        f"**Plan Version v{version}** · **Timeline Day {day}** · Status: `{status}` · "
        f"Trigger: *{trig_summary}*"
    )

    # Stand-down banner if applicable
    if curr_snap.get("status") == "stand_down":
        st.success(
            "🟢 **Plan stood down**: All primary supplier outages and disruptions have been resolved. "
            "The War Room has stood down recovery operations with zero remaining financial exposure."
        )

    # 4. KPI Metrics Row
    hl = curr_snap.get("headline", {})
    prev_hl = prev_snap.get("headline", {}) if prev_snap else {}

    net_exp = hl.get("net_financial_exposure", 0.0)
    prev_net = prev_hl.get("net_financial_exposure")
    delta_net = (
        format_money_delta(net_exp - prev_net) if prev_net is not None else None
    )

    landed = hl.get("total_landed_cost", 0.0)
    prev_landed = prev_hl.get("total_landed_cost")
    delta_landed = (
        format_money_delta(landed - prev_landed) if prev_landed is not None else None
    )

    pos = hl.get("po_count", 0)
    prev_pos = prev_hl.get("po_count")
    delta_pos = (
        format_count_delta(pos - prev_pos) if prev_pos is not None else None
    )

    unsourced = hl.get("unsourced_units", 0)
    prev_unsourced = prev_hl.get("unsourced_units")
    delta_unsourced = (
        format_count_delta(unsourced - prev_unsourced)
        if prev_unsourced is not None
        else None
    )

    esc_count = curr_snap.get("escalation_count", 0)
    prev_esc = prev_snap.get("escalation_count") if prev_snap else None
    delta_esc = (
        format_count_delta(esc_count - prev_esc) if prev_esc is not None else None
    )

    risk = str(hl.get("overall_risk", "low")).upper()

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        st.metric(label="Overall Risk", value=risk)
    with col2:
        st.metric(
            label="Net Financial Exposure",
            value=format_compact_money(net_exp),
            delta=delta_net,
            delta_color="inverse",
            help=f"Exact Net Financial Exposure: ${net_exp:,.2f}",
        )
    with col3:
        st.metric(
            label="Total Landed Cost",
            value=format_compact_money(landed),
            delta=delta_landed,
            delta_color="inverse",
            help=f"Exact Total Landed Cost: ${landed:,.2f}",
        )
    with col4:
        st.metric(
            label="Purchase Orders",
            value=f"{pos}",
            delta=delta_pos,
            delta_color="off",
        )
    with col5:
        st.metric(
            label="Unsourced Gap (units)",
            value=f"{unsourced:,}",
            delta=delta_unsourced,
            delta_color="inverse",
        )
    with col6:
        st.metric(
            label="A2A Escalations",
            value=f"{esc_count}",
            delta=delta_esc,
            delta_color="inverse",
        )

    st.markdown("---")

    # 5. Core Charts: Exposure Trajectory & Network Topology
    c_left, c_right = st.columns([1, 1])

    with c_left:
        tdf = timeline_df(snapshots)
        fig_traj = exposure_trajectory(tdf, selected_version=version)
        st.plotly_chart(fig_traj, use_container_width=True)

    with c_right:
        nodes_df, edges_df = get_cached_network_frame(curr_snap)
        fig_net = supply_network(nodes_df, edges_df)
        st.plotly_chart(fig_net, use_container_width=True)

    # 6. Detailed Analysis Tabs
    tab_diff, tab_sku, tab_po, tab_msg, tab_scenario = st.tabs(
        [
            "Changes vs previous plan",
            "SKU risk",
            "Procurement",
            "Agent messages",
            "Scenario",
        ]
    )

    # Tab 1: Diff & Adaptation
    with tab_diff:
        st.subheader(f"Adaptation Analysis (Plan v{version})")
        narrative = curr_snap.get("narrative")
        if narrative:
            st.info(f"**Executive Narrative**: {narrative}")

        diff = curr_snap.get("diff")
        if not diff:
            st.markdown(
                f"*Plan v1 represents the initial baseline recovery plan formed in response to the primary disruption.*"
            )
        else:
            d_col1, d_col2 = st.columns(2)
            with d_col1:
                st.markdown("#### Supplier Re-routings")
                sup_ch = diff.get("supplier_changes", [])
                if sup_ch:
                    sup_ch_df = pd.DataFrame(sup_ch)
                    st.dataframe(sup_ch_df, use_container_width=True, hide_index=True)
                else:
                    st.write("No supplier changes occurred in this version.")

                st.markdown("#### Freight Mode Shifts")
                mode_ch = diff.get("mode_changes", [])
                if mode_ch:
                    mode_ch_df = pd.DataFrame(mode_ch)
                    st.dataframe(mode_ch_df, use_container_width=True, hide_index=True)
                else:
                    st.write("No freight mode shifts occurred in this version.")

            with d_col2:
                st.markdown("#### Metric Deltas")
                mdeltas = diff.get("metric_deltas", {})
                if mdeltas:
                    metric_labels = {
                        "net_financial_exposure": "Net Financial Exposure",
                        "total_landed_cost": "Total Landed Cost",
                        "po_count": "PO Count",
                        "unsourced_units": "Unsourced Units",
                        "revenue_delayed": "Revenue Delayed",
                        "sla_penalty_total": "SLA Penalty Total",
                    }
                    money_metric_keys = {
                        "net_financial_exposure",
                        "total_landed_cost",
                        "revenue_delayed",
                        "sla_penalty_total",
                    }
                    md_rows = []
                    for k, v in mdeltas.items():
                        label = metric_labels.get(k, k.replace("_", " ").title())
                        if k in money_metric_keys:
                            formatted_v = format_money_delta(float(v))
                        else:
                            formatted_v = format_count_delta(v)
                        md_rows.append({"Metric": label, "Delta": formatted_v})
                    st.dataframe(pd.DataFrame(md_rows), use_container_width=True, hide_index=True)

                st.markdown("#### High-Risk SKU Changes")
                new_hr = diff.get("new_high_risk_skus", [])
                res_hr = diff.get("resolved_high_risk_skus", [])
                st.write(f"- **New High-Risk SKUs**: {new_hr if new_hr else 'None'}")
                st.write(f"- **Resolved High-Risk SKUs**: {res_hr if res_hr else 'None'}")

    # Tab 2: SKU Risk
    with tab_sku:
        st.subheader("SKU Inventory & Stockout Exposure")
        if curr_snap.get("status") == "stand_down":
            st.success("All SKU stocks are secure under stand-down conditions. No uncovered demand.")
        else:
            sdf = sku_df(curr_snap)
            if not sdf.empty:
                fig_risk = sku_risk(sdf)
                st.plotly_chart(fig_risk, use_container_width=True)
                st.dataframe(sdf, use_container_width=True, hide_index=True)
            else:
                st.write("No SKU data available.")

    # Tab 3: Procurement
    with tab_po:
        st.subheader("Procurement & Purchase Order Allocations")
        if curr_snap.get("status") == "stand_down":
            st.success("No active purchase orders required under stand-down conditions.")
        else:
            podf = po_df(curr_snap)
            if not podf.empty:
                fig_po = po_breakdown(podf)
                st.plotly_chart(fig_po, use_container_width=True)
                st.dataframe(podf, use_container_width=True, hide_index=True)
            else:
                st.write("No purchase orders planned for this version.")

    # Tab 4: Agent Messages
    with tab_msg:
        st.subheader("A2A Agent Message Log & Sequencing")
        if curr_snap.get("status") == "stand_down":
            st.success("No agent messages generated during stand-down.")
        else:
            mdf = messages_df(a2a_log, version=version)
            if not mdf.empty:
                fig_msg = agent_timeline(mdf)
                st.plotly_chart(fig_msg, use_container_width=True)
                st.dataframe(mdf, use_container_width=True, hide_index=True)
            else:
                st.write("No messages recorded for this plan version.")

    # Tab 5: Scenario Timeline
    with tab_scenario:
        st.subheader("Simulated Timeline Events")
        events = default_scenario()
        event_rows = [
            {
                "Day": e.day,
                "Event ID": e.event_id,
                "Event Type": e.event_type.replace("_", " ").title(),
                "Description": e.description,
            }
            for e in events
        ]
        st.dataframe(pd.DataFrame(event_rows), use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
