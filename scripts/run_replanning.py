"""Command-line script executing the War Room dynamic replanning simulation."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Ensure src/ is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from warroom.db.session import get_session
from warroom.replanning.engine import ReplanEngine
from warroom.replanning.scenario import default_scenario


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Autonomous Supply Chain War Room Replanning Timeline"
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default="data/replan",
        help="Directory where output timeline.json and a2a_replan_log.jsonl are written",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Skip writing output files to disk",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    session = get_session()

    print("=" * 80)
    print("Autonomous AI Supply Chain War Room - Dynamic Replanning Simulation")
    print("=" * 80)
    print("[*] Initializing Replanning Engine and loading default scenario...")

    engine = ReplanEngine(session)
    events = default_scenario()
    print(f"[*] Scenario loaded with {len(events)} events across days: {[e.day for e in events]}")

    try:
        snapshots = engine.run(events)

        print("\n" + "=" * 80)
        print("REPLANNING TIMELINE SUMMARY")
        print("=" * 80)
        print(
            f"  {'VER':<5} | {'DAY':<4} | {'STATUS':<11} | {'DOWN SUP':<12} | {'RISK':<9} | "
            f"{'NET EXPOSURE':<13} | {'LANDED COST':<12} | {'POs':<4} | {'UNSOURCED':<9} | {'ESC'}"
        )
        print("  " + "-" * 105)

        for s in snapshots:
            ver_str = f"v{s.version}"
            day_str = f"d{s.day}"
            status_str = s.status.upper()
            down_str = ",".join(s.down_suppliers) if s.down_suppliers else "None"
            risk_str = str(s.headline.get("overall_risk", "low")).upper()
            net_exp = f"${s.headline.get('net_financial_exposure', 0.0):,.2f}"
            landed = f"${s.headline.get('total_landed_cost', 0.0):,.2f}"
            pos = f"{s.headline.get('po_count', 0)}"
            unsourced = f"{s.headline.get('unsourced_units', 0):,}"
            esc = f"{s.escalation_count}"

            print(
                f"  {ver_str:<5} | {day_str:<4} | {status_str:<11} | {down_str:<12} | {risk_str:<9} | "
                f"{net_exp:<13} | {landed:<12} | {pos:<4} | {unsourced:<9} | {esc}"
            )

        print()

        # Print DIFF blocks for versions after the first
        print("=" * 80)
        print("PLAN DIFF ANALYSIS & ADAPTATION NARRATIVES")
        print("=" * 80)

        for s in snapshots:
            if s.version == 1 or not s.diff:
                print(f"--- Plan v1 (Day {s.day}) Initial Plan ---")
                print(f"  Trigger: {s.trigger_events[0] if s.trigger_events else 'Initial baseline'}")
                print(f"  Narrative: {s.narrative}\n")
                continue

            diff = s.diff
            print(f"--- Plan Diff: v{s.version - 1} -> v{s.version} (Day {s.day}) ---")
            print(f"  Trigger Events: {'; '.join(s.trigger_events)}")
            print(f"  Status: {s.status.upper()}")

            # Supplier changes
            sup_ch = diff.get("supplier_changes", [])
            if sup_ch:
                ch_strs = [f"{c['sku']}: {c['from']} -> {c['to']}" for c in sup_ch]
                print(f"  Supplier Changes: {', '.join(ch_strs)}")
            else:
                print("  Supplier Changes: None")

            # Mode changes
            mode_ch = diff.get("mode_changes", [])
            if mode_ch:
                m_strs = [f"{c['sku']}: {c['from'].upper()} -> {c['to'].upper()}" for c in mode_ch]
                print(f"  Freight Mode Shifts: {', '.join(m_strs)}")
            else:
                print("  Freight Mode Shifts: None")

            # Metric deltas
            deltas = diff.get("metric_deltas", {})
            net_d = deltas.get("net_financial_exposure", 0.0)
            land_d = deltas.get("total_landed_cost", 0.0)
            po_d = deltas.get("po_count", 0)
            uns_d = deltas.get("unsourced_units", 0)
            sla_d = deltas.get("sla_penalty_total", 0.0)
            print(
                f"  Metric Deltas: Net Exposure: ${net_d:+,.2f} | Landed Cost: ${land_d:+,.2f} | "
                f"POs: {po_d:+d} | Unsourced: {uns_d:+d} units | SLA Penalties: ${sla_d:+,.2f}"
            )

            # High risk deltas
            new_hr = diff.get("new_high_risk_skus", [])
            res_hr = diff.get("resolved_high_risk_skus", [])
            print(f"  High-Risk SKUs: New: {new_hr if new_hr else 'None'} | Resolved: {res_hr if res_hr else 'None'}")

            # Risk change
            rc = diff.get("risk_change", {})
            print(f"  Risk Level Transition: {rc.get('from', '').upper()} -> {rc.get('to', '').upper()}")

            # Narrative
            print(f"  Executive Narrative: {s.narrative}\n")

        # Net financial exposure trajectory
        trajectory_parts = [
            f"v{s.version} (${s.headline.get('net_financial_exposure', 0.0):,.2f})"
            for s in snapshots
        ]
        print("=" * 80)
        print("NET FINANCIAL EXPOSURE TRAJECTORY")
        print("=" * 80)
        print("  " + " -> ".join(trajectory_parts))
        print()

        # Write output files unless --no-write is set
        if not args.no_write:
            out_dir = PROJECT_ROOT / args.out_dir
            timeline_file, replan_log_file = engine.write_outputs(snapshots, out_dir)
            print(f"[*] Timeline exported to: {timeline_file}")
            print(f"[*] A2A replanning message log exported to: {replan_log_file}")
        else:
            print("[*] --no-write flag provided; skipping file export.")

        print("=" * 80)
        print("[*] Replanning simulation complete. All temporary mutations cleaned up successfully.")

    finally:
        session.close()


if __name__ == "__main__":
    main()
