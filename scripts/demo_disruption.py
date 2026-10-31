"""Demonstration script simulating a supplier disruption, analyzing impacts, and restoring status."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure src/ is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from warroom.db.session import get_session
from warroom.graph.analysis import (
    impact_of_supplier_failure,
    single_point_of_failure_report,
)
from warroom.graph.builder import build_supply_graph
from warroom.graph.detection import (
    detect_disruptions,
    restore_supplier,
    simulate_supplier_outage,
)


def main() -> None:
    session = get_session()
    supplier_target = "SUP01"

    print("=" * 75)
    print("Autonomous AI Supply Chain War Room - Disruption Simulation Demo")
    print("=" * 75)

    try:
        # Step 1: Baseline inspection
        print("[1/5] Building supply graph and scanning baseline disruptions...")
        G = build_supply_graph(session)
        print(f"      Graph constructed: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

        baseline_disruptions = detect_disruptions(session)
        print(f"      Active disruptions detected: {len(baseline_disruptions)}")
        if baseline_disruptions:
            print("      WARNING: Unexpected existing disruptions detected!")
        else:
            print("      Baseline system state: NOMINAL (All suppliers active).")
        print()

        # Step 2: Simulate Outage
        print(f"[2/5] Simulating sudden outage for key supplier '{supplier_target}'...")
        simulate_supplier_outage(session, supplier_target, duration_days=30)
        print(f"      Supplier '{supplier_target}' status updated to 'unavailable' (committed).")
        print()

        # Step 3: Rebuild graph and detect disruptions
        print("[3/5] Rebuilding supply graph with updated supplier status & detecting...")
        G_disrupted = build_supply_graph(session)
        disruptions = detect_disruptions(session)
        print(f"      Detected disruptions count: {len(disruptions)}")

        for ev in disruptions:
            print("-" * 75)
            print(f"DISRUPTION EVENT: [{ev.event_id}]")
            print(f"  Supplier:          {ev.supplier_id} ({G_disrupted.nodes[ev.supplier_id].get('name')})")
            print(f"  Severity:          {ev.severity.upper()}")
            print(f"  Detected At:       {ev.detected_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            print(f"  Expected Duration: {ev.expected_duration_days} days")
            print(f"  Affected SKUs:     {ev.affected_sku_count}")
        print()

        # Step 4: Comprehensive Impact Analysis
        print("[4/5] Computing impact of supplier failure...")
        impact = impact_of_supplier_failure(G_disrupted, session, supplier_target)

        print("-" * 75)
        print("IMPACT ANALYSIS SUMMARY")
        print("-" * 75)
        print(f"Primary SKUs Affected:  {len(impact['affected_skus'])} ({', '.join(impact['affected_skus'])})")
        print(f"Sole-Sourced SKUs:      {len(impact['sole_source_skus'])} ({impact['sole_source_skus']})")
        print(f"Exposed Open Orders:    {impact['exposed_open_orders']['count']} orders (Total Quantity: {impact['exposed_open_orders']['total_quantity']:,} units)")
        print()

        print("SKU Disruption Details (Days of Cover & Supply Gaps):")
        for sku_id in impact["affected_skus"]:
            sku_name = G_disrupted.nodes[sku_id].get("name", sku_id)
            doc = impact["days_of_cover"].get(sku_id, 0.0)
            gap = impact["supply_gap_days"].get(sku_id)
            alts = impact["alternatives"].get(sku_id, [])

            gap_str = f"{gap:.1f} days" if gap is not None else "CRITICAL (SOLE-SOURCED)"
            alt_details = [
                f"{a['supplier_id']} (${a['unit_price']:.2f}, {a['lead_time_days']}d)"
                for a in alts
            ]
            print(f"  - [{sku_id}] {sku_name}")
            print(f"      Days of Cover: {doc:.1f}d | Shortest Supply Gap: {gap_str}")
            print(f"      Active Alternatives ({len(alts)}): {'; '.join(alt_details)}")
        print()

        print("Exposed Customers:")
        for cust_id, cust_data in impact["exposed_customers"].items():
            print(
                f"  - [{cust_id}] {cust_data['name']:<32} | "
                f"Open Qty: {cust_data['quantity']:>5} units | Max Priority: {cust_data['max_priority']}"
            )
        print()

        # Step 5: Single Point of Failure Report
        print("[5/5] Single Point of Failure (SPOF) Ranking Report:")
        spof_df = single_point_of_failure_report(G_disrupted)
        print(
            spof_df[
                [
                    "supplier_id",
                    "name",
                    "sole_source_sku_count",
                    "primary_sku_count",
                    "status",
                    "is_key_supplier",
                ]
            ].to_string(index=False)
        )
        print("=" * 75)

    finally:
        # Step 6: Restore supplier to maintain database integrity
        print("\nRestoring supplier status back to 'active'...")
        restore_supplier(session, supplier_target)
        post_restoration_disruptions = detect_disruptions(session)
        print(
            f"Restoration verified: {len(post_restoration_disruptions)} active disruptions remaining."
        )
        print("Database returned to pristine state.")
        session.close()


if __name__ == "__main__":
    main()
