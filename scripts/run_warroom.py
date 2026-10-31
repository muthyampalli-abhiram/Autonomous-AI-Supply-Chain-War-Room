"""Script to execute the Autonomous AI Supply Chain War Room LangGraph orchestrator."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure src/ is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from warroom.db.session import get_session
from warroom.graph.detection import restore_supplier, simulate_supplier_outage
from warroom.orchestrator.graph import build_warroom_graph
from warroom.orchestrator.state import create_initial_state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Autonomous AI Supply Chain War Room Graph"
    )
    parser.add_argument(
        "--supplier",
        type=str,
        default=None,
        help="Supplier ID to simulate outage for (e.g., SUP01). If omitted, runs in nominal mode.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    session = get_session()

    print("=" * 75)
    print("Autonomous AI Supply Chain War Room - Orchestrator Execution")
    print("=" * 75)

    simulated_supplier = args.supplier

    try:
        if simulated_supplier:
            print(f"[*] Simulating outage for supplier '{simulated_supplier}'...")
            simulate_supplier_outage(session, simulated_supplier)
            print(f"[*] Supplier '{simulated_supplier}' set to 'unavailable'.")
        else:
            print("[*] Running in nominal mode (no simulated outage).")

        print("[*] Building War Room LangGraph workflow...")
        graph = build_warroom_graph(session)

        print("[*] Invoking workflow...")
        initial_state = create_initial_state()
        final_state = graph.invoke(initial_state)

        status = final_state.get("status", "unknown")
        print(f"[*] Workflow completed with status: '{status}'.\n")

        # 1. Print Messages Log
        messages = final_state.get("messages", [])
        print("-" * 75)
        print(f"MESSAGE LOG ({len(messages)} messages recorded)")
        print("-" * 75)
        if not messages:
            print("  (No messages generated - system nominal)")
        else:
            for idx, msg in enumerate(messages, 1):
                sender = msg.get("from", "unknown")
                recipient = msg.get("to", "unknown")
                msg_type = msg.get("type", "unknown")
                summary = msg.get("summary", "")
                ts = msg.get("timestamp", "")
                print(f"  [{idx}] {ts} | {sender.upper():<16} -> {recipient:<12} ({msg_type})")
                print(f"      {summary}")
        print()

        # 2. Print Final Plan / Outcome
        print("-" * 75)
        print("FINAL PLAN / RESOLUTION")
        print("-" * 75)
        final_plan = final_state.get("final_plan")
        if final_plan:
            print(f"  Plan Status:    {final_plan.get('status')}")
            print(f"  Plan Version:   {final_plan.get('plan_version')}")
            print(f"  Disruption ID:  {final_plan.get('disruption_id')}")
            print("  Agent Summaries:")
            summaries = final_plan.get("agent_summaries", {})
            for agent, summ in summaries.items():
                print(f"    - {agent:<16}: {summ}")
        else:
            print(f"  Outcome: Nominal condition - No disruption active. No recovery plan needed.")
        print()

        # 3. Print Supplier Evaluation Table
        supplier_res = final_state.get("supplier_result")
        if supplier_res and isinstance(supplier_res, dict) and "data" in supplier_res:
            s_data = supplier_res["data"]
            per_sku = s_data.get("per_sku", {})
            if per_sku:
                print("-" * 75)
                print("SUPPLIER SOURCING RECOMMENDATIONS")
                print("-" * 75)
                print(f"  {'SKU':<8} | {'RECOMMENDED SUPPLIER':<24} | {'PREMIUM %':<10} | {'LEAD TIME':<10} | {'CAPACITY COV'}")
                print("  " + "-" * 72)
                for sku_id, info in sorted(per_sku.items()):
                    rec = info.get("recommended")
                    if rec:
                        sup_name = f"{rec.get('supplier_id')} ({rec.get('name')[:15]})"
                        prem = f"{rec.get('price_premium_pct', 0.0):+.1f}%"
                        lt = f"{rec.get('lead_time_days', 0)} days"
                        cov = f"{rec.get('capacity_coverage_pct', 0.0):.1f}%"
                    else:
                        sup_name = "None"
                        prem = "N/A"
                        lt = "N/A"
                        cov = "0.0%"
                    print(f"  {sku_id:<8} | {sup_name:<24} | {prem:<10} | {lt:<10} | {cov}")
                print()

        # 4. Print Inventory Stock Allocation Table & Shortfall by Customer
        inventory_res = final_state.get("inventory_result")
        if inventory_res and isinstance(inventory_res, dict) and "data" in inventory_res:
            i_data = inventory_res["data"]
            per_sku = i_data.get("per_sku", {})
            if per_sku:
                print("-" * 75)
                print("INVENTORY ALLOCATION & SHORTFALL ANALYSIS")
                print("-" * 75)
                print(f"  {'SKU':<8} | {'DAYS COVER':<11} | {'WIN DEMAND':<11} | {'ALLOCATED':<10} | {'SHORTFALL':<10} | {'FILL RATE'}")
                print("  " + "-" * 72)
                for sku_id, info in sorted(per_sku.items()):
                    doc = f"{info.get('days_of_cover', 0.0):.1f}"
                    w_dem = f"{info.get('window_demand', 0):,}"
                    alloc = f"{info.get('allocated_qty', 0):,}"
                    short = f"{info.get('shortfall_qty', 0):,}"
                    fr = f"{info.get('fill_rate_pct', 0.0):.1f}%"
                    print(f"  {sku_id:<8} | {doc:<11} | {w_dem:<11} | {alloc:<10} | {short:<10} | {fr}")
                print()

            shortfall_by_cust = i_data.get("shortfall_by_customer", {})
            if shortfall_by_cust:
                print("  Customer Shortfall Summary:")
                for cust_id, qty in sorted(shortfall_by_cust.items(), key=lambda x: x[1], reverse=True):
                    print(f"    - {cust_id:<12}: {qty:,} units shortfall")
                print()

        # 5. Print Logistics Route Plan Table
        logistics_res = final_state.get("logistics_result")
        if logistics_res and isinstance(logistics_res, dict) and "data" in logistics_res:
            l_data = logistics_res["data"]
            per_sku = l_data.get("per_sku", {})
            if per_sku:
                print("-" * 75)
                print("LOGISTICS ROUTE PLAN (RECOMMENDED LANES)")
                print("-" * 75)
                print(f"  {'SKU':<8} | {'SUPPLIER':<9} | {'MODE':<6} | {'CARRIER':<8} | {'TRANSIT':<8} | {'TOT LEAD':<9} | {'ETA':<11} | {'FRT/UNIT':<9} | {'EXPEDITED'}")
                print("  " + "-" * 90)
                for sku_id, info in sorted(per_sku.items()):
                    lanes = info.get("lanes", [])
                    rec_lane = next((l for l in lanes if l.get("role") == "recommended"), None)
                    if rec_lane:
                        sup = rec_lane.get("supplier_id", "N/A")
                        sel = rec_lane.get("selected", {})
                        mode_str = sel.get("mode", "").upper()
                        carrier_str = sel.get("carrier_id", "")
                        transit_str = f"{sel.get('transit_days', 0)}d"
                        lead_str = f"{sel.get('total_lead_time_days', 0)}d"
                        eta_str = sel.get("eta_date", "")
                        frt_unit = f"${sel.get('freight_per_unit', 0.0):.2f}"
                        exp_str = "YES" if sel.get("expedited") else "NO"
                        print(f"  {sku_id:<8} | {sup:<9} | {mode_str:<6} | {carrier_str:<8} | {transit_str:<8} | {lead_str:<9} | {eta_str:<11} | {frt_unit:<9} | {exp_str}")
                print()

            totals = l_data.get("totals", {})
            if totals:
                tot_freight = totals.get("total_freight_estimate", 0.0)
                tot_expedite = totals.get("total_expedite_extra_cost", 0.0)
                exp_skus = totals.get("expedited_skus", [])
                mm = totals.get("mode_mix", {})
                print(f"  Logistics Totals: Est Freight: ${tot_freight:,.2f} | Expedite Extra: ${tot_expedite:,.2f} | Expedited SKUs: {len(exp_skus)} {exp_skus} | Mode Mix: {mm}")
                print()

        # 6. Print Demand Forecast Table
        demand_res = final_state.get("demand_result")
        if demand_res and isinstance(demand_res, dict) and "data" in demand_res:
            d_data = demand_res["data"]
            per_sku = d_data.get("per_sku", {})
            if per_sku:
                print("-" * 75)
                print("DEMAND FORECAST & STOCKOUT RISK")
                print("-" * 75)
                print(f"  {'SKU':<8} | {'BASE/DAY':<9} | {'TREND':<6} | {'UPLIFT %':<9} | {'FCST/DAY':<9} | {'HORIZON':<8} | {'ON HAND':<8} | {'PROJ GAP':<9} | {'DAYS UNCOV'}")
                print("  " + "-" * 88)
                for sku_id, info in sorted(per_sku.items()):
                    b_day = f"{info.get('baseline_daily', 0.0):.1f}"
                    trend = f"{info.get('trend_factor', 1.0):.2f}"
                    uplift = f"{info.get('uplift_pct', 0.0):+.1f}%"
                    f_day = f"{info.get('forecast_daily', 0.0):.1f}"
                    horiz = f"{info.get('horizon_days', 0)}d"
                    on_h = f"{info.get('on_hand', 0):,}"
                    gap = f"{info.get('projected_gap_qty', 0.0):,.0f}"
                    uncov = f"{info.get('days_uncovered', 0.0):.1f}d"
                    print(f"  {sku_id:<8} | {b_day:<9} | {trend:<6} | {uplift:<9} | {f_day:<9} | {horiz:<8} | {on_h:<8} | {gap:<9} | {uncov}")
                print()

            d_totals = d_data.get("totals", {})
            high_risk = d_data.get("high_risk_skus", [])
            print(f"  Demand Totals: Forecast Demand: {d_totals.get('forecast_demand', 0):,.0f} units | Projected Gap: {d_totals.get('projected_gap_qty', 0):,.0f} units")
            print(f"  High-Risk SKUs (Stockout before replenishment): {len(high_risk)} {high_risk}")
            print()

        # 7. Print Procurement Plan Table
        procurement_res = final_state.get("procurement_result")
        if procurement_res and isinstance(procurement_res, dict) and "data" in procurement_res:
            p_data = procurement_res["data"]
            pos = p_data.get("purchase_orders", [])
            if pos:
                print("-" * 75)
                print("PROCUREMENT PLAN (PURCHASE ORDERS)")
                print("-" * 75)
                print(f"  {'PO ID':<19} | {'SUP':<6} | {'SKU':<7} | {'ROLE':<11} | {'QTY':<7} | {'PRICE':<8} | {'MODE':<6} | {'LINE COST':<11} | {'ARRIVAL':<11} | {'URGENCY'}")
                print("  " + "-" * 102)
                for po in pos:
                    p_id = po.get("po_id", "")
                    sup = po.get("supplier_id", "")
                    sku = po.get("sku_id", "")
                    role = po.get("role", "").upper()
                    qty = f"{po.get('quantity', 0):,}"
                    price = f"${po.get('unit_price', 0.0):.2f}"
                    mode = po.get("freight_mode", "").upper()
                    l_cost = f"${po.get('line_cost', 0.0):,.2f}"
                    arr = po.get("expected_arrival", "")
                    urg = po.get("urgency", "").upper()
                    print(f"  {p_id:<19} | {sup:<6} | {sku:<7} | {role:<11} | {qty:<7} | {price:<8} | {mode:<6} | {l_cost:<11} | {arr:<11} | {urg}")
                print()

            p_totals = p_data.get("totals", {})
            if p_totals:
                p_cnt = p_totals.get("po_count", 0)
                tot_val = p_totals.get("total_po_value", 0.0)
                tot_frt = p_totals.get("total_freight", 0.0)
                tot_land = p_totals.get("total_landed_cost", 0.0)
                tot_prem = p_totals.get("total_premium_vs_baseline", 0.0)
                print(f"  Procurement Totals: {p_cnt} POs | PO Value: ${tot_val:,.2f} | Freight: ${tot_frt:,.2f} | Landed Cost: ${tot_land:,.2f} | Premium: ${tot_prem:,.2f}")

            unsourced = p_data.get("unsourced_by_sku", {})
            if unsourced:
                print(f"  Unsourced Volume by SKU: {unsourced}")
            else:
                print("  Unsourced Volume by SKU: None (100% covered)")

            appr = p_data.get("approval_required", False)
            appr_str = "YES (Exceeds $100,000 threshold)" if appr else "NO (Within threshold)"
            print(f"  Executive Approval Required: {appr_str}")
            print()

        # 8. Print Customer Impact Analysis
        customer_res = final_state.get("customer_impact_result")
        if customer_res and isinstance(customer_res, dict) and "data" in customer_res:
            c_data = customer_res["data"]
            per_cust = c_data.get("per_customer", {})
            if per_cust:
                print("-" * 75)
                print("CUSTOMER IMPACT ANALYSIS")
                print("-" * 75)
                print(f"  {'CUST ID':<8} | {'CUSTOMER NAME':<24} | {'TIER':<7} | {'ORDERS':<6} | {'SHORT':<6} | {'MAX DELAY':<9} | {'DELAYED VAL':<11} | {'LOST VAL':<10} | {'SLA PENALTY':<11} | {'RISK'}")
                print("  " + "-" * 115)
                for c_id, info in sorted(per_cust.items()):
                    c_name = str(info.get("name", c_id))[:24]
                    tier_str = str(info.get("tier", "")).upper()
                    ords = f"{info.get('orders_affected', 0)}"
                    short = f"{info.get('short_qty', 0):,}"
                    max_d = f"{info.get('max_delay_days', 0)}d"
                    del_val = f"${info.get('delayed_value', 0.0):,.2f}"
                    lost_val = f"${info.get('lost_value', 0.0):,.2f}"
                    sla_pen = f"${info.get('sla_penalty', 0.0):,.2f}"
                    risk = str(info.get("risk_level", "")).upper()
                    print(f"  {c_id:<8} | {c_name:<24} | {tier_str:<7} | {ords:<6} | {short:<6} | {max_d:<9} | {del_val:<11} | {lost_val:<10} | {sla_pen:<11} | {risk}")
                print()

            fin = c_data.get("financials", {})
            if fin:
                print(f"  Financial Exposure: At-Risk Orders: {fin.get('orders_at_risk', 0)} ({fin.get('orders_delayed', 0)} delayed, {fin.get('orders_unfulfilled', 0)} unfulfilled)")
                print(f"  Revenue Delayed: ${fin.get('revenue_delayed', 0.0):,.2f} | Revenue Lost: ${fin.get('revenue_lost', 0.0):,.2f} | SLA Penalties: ${fin.get('sla_penalty_total', 0.0):,.2f}")
                print(f"  Response Cost: ${fin.get('response_cost', 0.0):,.2f} | Net Financial Exposure: ${fin.get('net_financial_exposure', 0.0):,.2f}")

            f_exp = c_data.get("forecast_exposure", {})
            if f_exp:
                by_t = f_exp.get("by_tier", {})
                print(f"  Forecast Revenue Exposure: Total ${f_exp.get('total', 0.0):,.2f} (Gold: ${by_t.get('gold', 0.0):,.2f}, Silver: ${by_t.get('silver', 0.0):,.2f}, Bronze: ${by_t.get('bronze', 0.0):,.2f})")

            pe = c_data.get("plan_effect", {})
            if pe:
                print(f"  Plan Effect: Baseline Lost Value: ${pe.get('baseline_lost_value', 0.0):,.2f} | Plan Lost Value: ${pe.get('plan_lost_value', 0.0):,.2f} | Value Protected: ${pe.get('value_protected', 0.0):,.2f}")
            print()

        # 9. Print A2A Agent Cards & Message Log
        a2a_log = final_state.get("a2a_log", [])
        final_plan = final_state.get("final_plan") or {}
        a2a_summary = final_plan.get("a2a", {})
        task_states = a2a_summary.get("task_states", {})

        print("-" * 75)
        print("A2A AGENT CARDS (CAPABILITIES REGISTRY)")
        print("-" * 75)
        agent_cards_info = [
            ("orchestrator", "War Room Orchestrator", ["incident_response", "workflow_orchestration"]),
            ("supplier", "Supplier Agent", ["alternative_supplier_discovery", "supplier_scoring"]),
            ("inventory", "Inventory Agent", ["stock_allocation", "shortage_analysis"]),
            ("logistics", "Logistics Agent", ["route_optimization", "freight_quoting"]),
            ("demand", "Demand Agent", ["demand_forecasting", "stockout_projection"]),
            ("procurement", "Procurement Agent", ["po_generation", "procurement_planning"]),
            ("customer_impact", "Customer Impact Agent", ["sla_penalty_calculation", "customer_risk_assessment"]),
            ("human_approver", "Human Executive Approver", ["executive_approval", "risk_governance"]),
        ]
        for aid, aname, skills in agent_cards_info:
            print(f"  [{aid:<15}] {aname:<28} | Skills: {', '.join(skills)}")
        print()

        print("-" * 75)
        print(f"A2A MESSAGE LOG ({len(a2a_log)} messages exchanged)")
        print("-" * 75)
        if not a2a_log:
            print("  (No A2A messages generated - system nominal)")
        else:
            print(f"  {'SEQ':<9} | {'ROUTE':<30} | {'MSG TYPE':<15} | {'TASK ID':<11} | {'TASK STATE'}")
            print("  " + "-" * 80)
            for m in a2a_log:
                mid = m.get("message_id", "")
                sender = m.get("sender", "")
                recip = m.get("recipient", "")
                route = f"{sender} -> {recip}"
                mtype = m.get("msg_type", "")
                tid = m.get("task_id") or "-"
                tstate = task_states.get(recip if sender == "orchestrator" else sender, "-") if tid != "-" else "-"
                print(f"  {mid:<9} | {route:<30} | {mtype:<15} | {tid:<11} | {tstate}")
            print()

        # Write A2A log to data/a2a_log.jsonl
        log_path = PROJECT_ROOT / "data" / "a2a_log.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as f:
            for entry in a2a_log:
                f.write(json.dumps(entry, default=str) + "\n")
        print(f"[*] A2A message log exported to: {log_path}")
        print()
        print("=" * 75)

    finally:
        if simulated_supplier:
            print(f"\n[*] Restoring supplier '{simulated_supplier}' back to 'active'...")
            restore_supplier(session, simulated_supplier)
            print("[*] Database restored to nominal active state.")
        session.close()


if __name__ == "__main__":
    main()
