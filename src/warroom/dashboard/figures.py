"""Plotly visualization figures for the Autonomous AI Supply Chain War Room dashboard."""

from __future__ import annotations

from typing import Any
import pandas as pd
import plotly.graph_objects as go

# Design Palette & Themes
BG_DARK = "#0f172a"
PAPER_DARK = "#1e293b"
GRID_COLOR = "rgba(255, 255, 255, 0.08)"
TEXT_COLOR = "#f8fafc"
MUTED_TEXT = "#94a3b8"

COLOR_FAILED = "#ef4444"
COLOR_RECOMMENDED = "#22c55e"
COLOR_BACKUP = "#f59e0b"
COLOR_OTHER = "#64748b"
COLOR_SKU = "#06b6d4"
COLOR_WH = "#a855f7"
COLOR_CUST = "#3b82f6"

BASE_LAYOUT = dict(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color=TEXT_COLOR, family="Inter, system-ui, sans-serif"),
    margin=dict(l=40, r=40, t=50, b=40),
)


def _empty_figure(annotation_text: str) -> go.Figure:
    """Return a clean empty figure with a centered annotation message."""
    fig = go.Figure()
    fig.update_layout(
        **BASE_LAYOUT,
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        annotations=[
            dict(
                text=annotation_text,
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font=dict(size=16, color=MUTED_TEXT),
            )
        ],
    )
    return fig


def exposure_trajectory(
    tdf: pd.DataFrame, selected_version: int | None = None
) -> go.Figure:
    """Generate stacked bars for financial exposure components plus net exposure line."""
    if tdf.empty:
        return _empty_figure("No timeline data available")

    # X-axis version labels: "v1 · day 0", "v2 · day 3", etc.
    x_labels = [f"v{int(r['version'])} · day {int(r['day'])}" for _, r in tdf.iterrows()]
    versions = [int(r["version"]) for _, r in tdf.iterrows()]

    fig = go.Figure()

    # Stacked bars: SLA Penalty, Response Cost, Revenue Lost
    fig.add_trace(
        go.Bar(
            x=x_labels,
            y=tdf["sla_penalty_total"],
            name="SLA Penalties",
            marker=dict(color="#f59e0b", line=dict(width=0)),
            hovertemplate="<b>%{x}</b><br>SLA Penalties: $%{y:,.2f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=x_labels,
            y=tdf["response_cost"],
            name="Response Cost",
            marker=dict(color="#3b82f6", line=dict(width=0)),
            hovertemplate="<b>%{x}</b><br>Response Cost: $%{y:,.2f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=x_labels,
            y=tdf["revenue_lost"],
            name="Lost Revenue",
            marker=dict(color="#ef4444", line=dict(width=0)),
            hovertemplate="<b>%{x}</b><br>Lost Revenue: $%{y:,.2f}<extra></extra>",
        )
    )

    # Line overlay: Net Financial Exposure
    fig.add_trace(
        go.Scatter(
            x=x_labels,
            y=tdf["net_financial_exposure"],
            mode="lines+markers",
            name="Net Exposure",
            line=dict(color="#10b981", width=3.5),
            marker=dict(size=9, color="#10b981", line=dict(color="#ffffff", width=1.5)),
            hovertemplate="<b>%{x}</b><br>Net Financial Exposure: $%{y:,.2f}<extra></extra>",
        )
    )

    # Highlight selected version if provided
    shapes = []
    if selected_version is not None and selected_version in versions:
        idx = versions.index(selected_version)
        selected_label = x_labels[idx]
        shapes.append(
            dict(
                type="line",
                xref="x",
                yref="paper",
                x0=selected_label,
                x1=selected_label,
                y0=0,
                y1=1,
                line=dict(color="rgba(255, 255, 255, 0.45)", width=2, dash="dash"),
            )
        )

    fig.update_layout(**BASE_LAYOUT)
    fig.update_layout(
        margin=dict(l=40, r=40, t=70, b=70),
        title=dict(
            text="Financial Exposure & Response Cost Trajectory Across Replan Cycles",
            font=dict(size=16),
            x=0.5,
            xanchor="center",
            y=0.96,
            yanchor="top",
        ),
        barmode="stack",
        hovermode="x unified",
        xaxis=dict(
            title="Plan Version & Timeline Day",
            gridcolor=GRID_COLOR,
            showgrid=True,
            tickfont=dict(size=12),
        ),
        yaxis=dict(
            title="Amount (USD)",
            gridcolor=GRID_COLOR,
            showgrid=True,
            tickformat="$,.0f",
        ),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.22,
            xanchor="center",
            x=0.5,
            bgcolor="rgba(0,0,0,0)",
        ),
        shapes=shapes,
    )

    return fig


def supply_network(nodes_df: pd.DataFrame, edges_df: pd.DataFrame) -> go.Figure:
    """Generate interactive 2D graph scatter visualization of the supply network."""
    if nodes_df.empty:
        return _empty_figure("No network nodes available")

    fig = go.Figure()

    # 1. Add Edges by Class
    # Draw 'other' edges first and very faint (low opacity, thin) so they do not hide highlighted ones
    # Draw primary_lost (red dashed) and active_plan (green) thicker and on top
    edge_priority = [
        ("other", dict(color="rgba(148, 163, 184, 0.12)", width=0.8, dash="solid", name="Baseline Network Edge")),
        ("primary_lost", dict(color=COLOR_FAILED, width=3.0, dash="dash", name="Disrupted Primary Lane")),
        ("active_plan", dict(color=COLOR_RECOMMENDED, width=3.0, dash="solid", name="Active Replanned Lane")),
    ]

    for e_class, style in edge_priority:
        subset = edges_df[edges_df["edge_class"] == e_class]
        if subset.empty:
            continue

        edge_x: list[float | None] = []
        edge_y: list[float | None] = []
        for _, r in subset.iterrows():
            edge_x.extend([r["x0"], r["x1"], None])
            edge_y.extend([r["y0"], r["y1"], None])

        fig.add_trace(
            go.Scatter(
                x=edge_x,
                y=edge_y,
                mode="lines",
                name=style["name"],
                line=dict(color=style["color"], width=style["width"], dash=style["dash"]),
                hoverinfo="none",
                showlegend=True,
            )
        )

    # 2. Add Nodes by Group
    # Show text labels for suppliers, warehouses and customers.
    # Show SKU labels in a smaller font.
    # Failed suppliers get a larger red marker so SUP01 is obvious.
    node_groups = [
        # (state_key, group_name, symbol, color, size, font_size, text_color, text_pos, border_width)
        ("failed", "Failed Supplier", "circle", COLOR_FAILED, 24, 11, COLOR_FAILED, "top center", 2.5),
        ("recommended", "Recommended Alternative", "circle", COLOR_RECOMMENDED, 15, 10, TEXT_COLOR, "top center", 1.5),
        ("backup", "Backup Alternative", "circle", COLOR_BACKUP, 14, 10, TEXT_COLOR, "top center", 1.5),
        ("other", "Standard Supplier", "circle", COLOR_OTHER, 12, 10, TEXT_COLOR, "top center", 1.0),
        ("sku", "SKU Item", "diamond", COLOR_SKU, 10, 8, MUTED_TEXT, "top center", 1.0),
        ("warehouse", "Warehouse Hub", "square", COLOR_WH, 16, 11, TEXT_COLOR, "top center", 1.5),
        ("customer", "Customer Account", "triangle-up", COLOR_CUST, 14, 11, TEXT_COLOR, "top center", 1.5),
    ]

    for state_key, group_name, symbol, color, size, font_size, text_color, text_pos, border_width in node_groups:
        subset = nodes_df[nodes_df["supplier_state"] == state_key]
        if subset.empty:
            continue

        fig.add_trace(
            go.Scatter(
                x=subset["x"],
                y=subset["y"],
                mode="markers+text",
                name=group_name,
                text=subset["label"],
                textposition=text_pos,
                textfont=dict(size=font_size, color=text_color),
                hovertext=subset["hover_text"],
                hoverinfo="text",
                marker=dict(
                    symbol=symbol,
                    color=color,
                    size=size,
                    line=dict(color="#ffffff", width=border_width),
                ),
                showlegend=True,
            )
        )

    # 3. Column headers as annotations above the plot: Suppliers, SKUs, Warehouses, Customers
    column_headers = [
        dict(
            x=0,
            y=1.06,
            xref="x",
            yref="paper",
            text="<b>Suppliers</b>",
            showarrow=False,
            font=dict(size=14, color=TEXT_COLOR),
            xanchor="center",
        ),
        dict(
            x=1,
            y=1.06,
            xref="x",
            yref="paper",
            text="<b>SKUs</b>",
            showarrow=False,
            font=dict(size=14, color=TEXT_COLOR),
            xanchor="center",
        ),
        dict(
            x=2,
            y=1.06,
            xref="x",
            yref="paper",
            text="<b>Warehouses</b>",
            showarrow=False,
            font=dict(size=14, color=TEXT_COLOR),
            xanchor="center",
        ),
        dict(
            x=3,
            y=1.06,
            xref="x",
            yref="paper",
            text="<b>Customers</b>",
            showarrow=False,
            font=dict(size=14, color=TEXT_COLOR),
            xanchor="center",
        ),
    ]

    fig.update_layout(**BASE_LAYOUT)
    fig.update_layout(
        height=650,
        margin=dict(l=40, r=40, t=80, b=70),
        title=dict(
            text="Multi-Tier Supply Chain Topology & Active Disruption Overlay",
            font=dict(size=16),
            x=0.5,
            xanchor="center",
            y=0.98,
            yanchor="top",
        ),
        xaxis=dict(range=[-0.6, 3.6], showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(range=[-0.06, 1.06], showgrid=False, zeroline=False, showticklabels=False),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.08,
            xanchor="center",
            x=0.5,
            bgcolor="rgba(0,0,0,0)",
        ),
        annotations=column_headers,
        hoverlabel=dict(bgcolor=PAPER_DARK, font_size=12, font_family="Inter"),
    )

    return fig


def sku_risk(sdf: pd.DataFrame) -> go.Figure:
    """Generate horizontal bar chart of days uncovered per SKU with fill rate in hover."""
    if sdf.empty:
        return _empty_figure("No active disruption")

    # Sort so highest uncovered days are at the top
    sdf_sorted = sdf.sort_values(by="days_uncovered", ascending=True)

    # Color bars: red for high uncovered (>14d), amber for moderate, green for 0
    colors = []
    for d in sdf_sorted["days_uncovered"]:
        if d >= 14:
            colors.append(COLOR_FAILED)
        elif d > 0:
            colors.append(COLOR_BACKUP)
        else:
            colors.append(COLOR_RECOMMENDED)

    customdata = sdf_sorted[
        ["fill_rate_pct", "forecast_daily", "ordered_qty", "unsourced_qty"]
    ].values

    fig = go.Figure(
        go.Bar(
            y=sdf_sorted["sku_id"],
            x=sdf_sorted["days_uncovered"],
            orientation="h",
            marker=dict(color=colors, line=dict(color="#ffffff", width=0.5)),
            customdata=customdata,
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Days Uncovered: %{x:.1f}d<br>"
                "Fill Rate: %{customdata[0]:.1f}%<br>"
                "Daily Forecast: %{customdata[1]:.1f} units<br>"
                "Replenishment Ordered: %{customdata[2]:,} units<br>"
                "Unsourced Gap: %{customdata[3]:,} units<extra></extra>"
            ),
        )
    )

    fig.update_layout(
        **BASE_LAYOUT,
        title=dict(text="Stockout Exposure (Days Uncovered Demand by SKU)", font=dict(size=16)),
        xaxis=dict(title="Days Uncovered", gridcolor=GRID_COLOR, showgrid=True),
        yaxis=dict(title="SKU Identifier", tickfont=dict(size=12)),
    )

    return fig


def po_breakdown(podf: pd.DataFrame) -> go.Figure:
    """Generate stacked bar chart of line cost per SKU broken down by supplier."""
    if podf.empty:
        return _empty_figure("No purchase orders planned")

    fig = go.Figure()

    suppliers = sorted(podf["supplier_id"].unique())
    skus = sorted(podf["sku_id"].unique())

    # Stack by supplier
    for sup in suppliers:
        sup_df = podf[podf["supplier_id"] == sup]
        y_vals = []
        hover_texts = []
        for sku in skus:
            row = sup_df[sup_df["sku_id"] == sku]
            if not row.empty:
                cost = float(row["line_cost"].sum())
                qty = int(row["quantity"].sum())
                mode = str(row.iloc[0]["freight_mode"])
                y_vals.append(cost)
                hover_texts.append(
                    f"<b>{sku} via {sup}</b><br>Line Cost: ${cost:,.2f}<br>Qty: {qty:,}<br>Mode: {mode}"
                )
            else:
                y_vals.append(0.0)
                hover_texts.append("")

        fig.add_trace(
            go.Bar(
                x=skus,
                y=y_vals,
                name=sup,
                hovertext=hover_texts,
                hoverinfo="text",
            )
        )

    fig.update_layout(
        **BASE_LAYOUT,
        title=dict(text="Purchase Order Expenditure by SKU (Stacked by Vendor)", font=dict(size=16)),
        barmode="stack",
        xaxis=dict(title="SKU Identifier", gridcolor=GRID_COLOR),
        yaxis=dict(title="Total Line Cost (USD)", gridcolor=GRID_COLOR, tickformat="$,.0f"),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            bgcolor="rgba(0,0,0,0)",
        ),
    )

    return fig


def agent_timeline(mdf: pd.DataFrame) -> go.Figure:
    """Generate scatter timeline of A2A message events by sender and type."""
    if mdf.empty:
        return _empty_figure("No A2A messages in this plan version")

    fig = go.Figure()

    # Distinct symbols and colors per message type
    msg_styles = {
        "broadcast": dict(symbol="star", color="#eab308", size=13),
        "task_request": dict(symbol="circle", color="#3b82f6", size=10),
        "status_update": dict(symbol="square", color="#64748b", size=9),
        "task_result": dict(symbol="diamond", color="#22c55e", size=11),
        "escalation": dict(symbol="triangle-up", color="#ef4444", size=14),
    }

    types = mdf["msg_type"].unique()
    for mtype in types:
        subset = mdf[mdf["msg_type"] == mtype]
        style = msg_styles.get(mtype, dict(symbol="circle", color="#a855f7", size=10))

        hover_texts = [
            f"<b>{r['message_id']} ({r['sender']} -> {r['recipient']})</b><br>"
            f"Type: {r['msg_type'].upper()}<br>"
            f"Task: {r['task_id']}<br>"
            f"Content: {r['text'][:90]}..."
            for _, r in subset.iterrows()
        ]

        fig.add_trace(
            go.Scatter(
                x=list(range(len(subset))) if len(subset) > 0 else [],
                y=subset["sender"],
                mode="markers",
                name=mtype.upper(),
                marker=dict(
                    symbol=style["symbol"],
                    color=style["color"],
                    size=style["size"],
                    line=dict(color="#ffffff", width=1),
                ),
                hovertext=hover_texts,
                hoverinfo="text",
            )
        )

    fig.update_layout(
        **BASE_LAYOUT,
        title=dict(text="A2A Agent Message Sequence & Inter-Agent Coordination", font=dict(size=16)),
        xaxis=dict(title="Message Sequence", showgrid=True, gridcolor=GRID_COLOR),
        yaxis=dict(title="Sender Agent / Node", tickfont=dict(size=12)),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            bgcolor="rgba(0,0,0,0)",
        ),
    )

    return fig
