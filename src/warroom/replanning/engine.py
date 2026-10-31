"""Dynamic replanning engine executing timeline events and generating versioned plan snapshots."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from warroom.agents.llm import narrate
from warroom.db.models import Order, Supplier
from warroom.graph.detection import detect_disruptions
from warroom.orchestrator.graph import build_warroom_graph
from warroom.orchestrator.state import create_initial_state
from warroom.replanning.events import SimEvent, apply_event
from warroom.replanning.snapshot import PlanSnapshot, build_snapshot, diff_snapshots
from warroom.tools.registry import call_tool


class ReplanEngine:
    """Coordinates timeline replanning cycles across dynamic supply chain disruptions."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def _generate_narrative(
        self,
        diff: dict[str, Any] | None,
        version: int,
        day: int,
        is_stand_down: bool = False,
        headline: dict[str, Any] | None = None,
    ) -> str:
        """Generate a 1-2 sentence executive summary using narrate() with a deterministic fallback."""
        headline = headline or {}
        facts = {
            "version": version,
            "day": day,
            "is_stand_down": is_stand_down,
            "diff": diff,
            "headline": headline,
        }

        if version == 1:
            net_exp = headline.get("net_financial_exposure", 0.0)
            po_count = headline.get("po_count", 0)
            fallback = (
                f"Plan v1 (Day {day}): Baseline recovery plan established for initial disruption. "
                f"Total net financial exposure is ${net_exp:,.2f} across {po_count} purchase orders."
            )
        elif is_stand_down:
            fallback = (
                f"Plan v{version} (Day {day}): Disruption resolved and all primary suppliers restored. "
                "War Room standing down with zero remaining financial exposure."
            )
        else:
            diff = diff or {}
            sup_changes = diff.get("supplier_changes", [])
            mode_changes = diff.get("mode_changes", [])
            metric_deltas = diff.get("metric_deltas", {})
            net_delta = metric_deltas.get("net_financial_exposure", 0.0)
            new_hr = diff.get("new_high_risk_skus", [])
            net_curr = headline.get("net_financial_exposure", 0.0)

            change_items: list[str] = []
            if sup_changes:
                change_items.append(f"{len(sup_changes)} supplier reroutes")
            if mode_changes:
                change_items.append(f"{len(mode_changes)} freight mode shifts")
            if new_hr:
                change_items.append(f"new risk on {new_hr}")

            change_str = ", ".join(change_items) if change_items else "operational parameter adjustments"
            fallback = (
                f"Plan v{version} (Day {day}): Adapted response via {change_str}. "
                f"Net financial exposure shifted by ${net_delta:+,.2f} to ${net_curr:,.2f}."
            )

        return narrate(role="replanning", facts=facts, fallback=fallback)

    def run(self, events: list[SimEvent]) -> list[PlanSnapshot]:
        """Execute the simulated timeline of events and return versioned plan snapshots.

        Groups events by day, applies mutations, checks disruptions, rebuilds the graph
        or records a stand_down snapshot, and guarantees full cleanup in a finally block.
        """
        # 1. Snapshot initial state for guaranteed rollback
        suppliers = self.session.scalars(select(Supplier)).all()
        initial_statuses = {s.supplier_id: s.status for s in suppliers}
        initial_delays = dict(call_tool("get_active_delays"))
        initial_surge_ids = set(
            self.session.scalars(
                select(Order.order_id).where(Order.order_id.like("SURGE-%"))
            ).all()
        )

        undo_stack: list[Callable[[], None]] = []
        snapshots: list[PlanSnapshot] = []

        down_suppliers: list[str] = [
            s.supplier_id for s in suppliers if s.status.lower() != "active"
        ]
        active_delays: dict[str, int] = dict(initial_delays)

        # 2. Group events by day in chronological order
        events_by_day: dict[int, list[SimEvent]] = {}
        for evt in sorted(events, key=lambda e: e.day):
            events_by_day.setdefault(evt.day, []).append(evt)

        version = 1
        prev_snapshot: PlanSnapshot | None = None

        try:
            for day, day_events in sorted(events_by_day.items()):
                trigger_descriptions: list[str] = []

                # Apply all events for the current day
                for evt in day_events:
                    undo_fn = apply_event(self.session, evt)
                    undo_stack.append(undo_fn)
                    trigger_descriptions.append(evt.description)

                    # Update internal tracking
                    if evt.event_type == "supplier_outage":
                        sup_id = str(evt.params["supplier_id"])
                        if sup_id not in down_suppliers:
                            down_suppliers.append(sup_id)
                    elif evt.event_type == "supplier_recovery":
                        sup_id = str(evt.params["supplier_id"])
                        if sup_id in down_suppliers:
                            down_suppliers.remove(sup_id)
                    elif evt.event_type == "carrier_delay":
                        m = str(evt.params["mode"]).lower()
                        d = int(evt.params["extra_days"])
                        active_delays[m] = d

                # Detect active disruptions in the database
                disruptions = detect_disruptions(self.session)
                active_disruptions = [d for d in disruptions if d.affected_sku_count > 0]

                if not active_disruptions:
                    # Record stand_down snapshot WITHOUT invoking graph
                    snapshot = build_snapshot(
                        version=version,
                        day=day,
                        events=trigger_descriptions,
                        state={"status": "stand_down"},
                        down_suppliers=list(down_suppliers),
                        active_delays=dict(active_delays),
                    )
                    if prev_snapshot is not None:
                        snapshot.diff = diff_snapshots(prev_snapshot, snapshot)
                    snapshot.narrative = self._generate_narrative(
                        snapshot.diff, version, day, is_stand_down=True
                    )
                    snapshots.append(snapshot)
                    prev_snapshot = snapshot
                    version += 1
                else:
                    # Rebuild fresh war room graph
                    graph = build_warroom_graph(self.session)

                    # Ensure active transit delays persist across the rebuild into the new logistics API
                    for m, d in active_delays.items():
                        call_tool("report_mode_delay", mode=m, extra_days=d)

                    initial_state = create_initial_state()
                    initial_state["run_id"] = f"replan-v{version}-day{day}"

                    final_state = graph.invoke(initial_state)

                    snapshot = build_snapshot(
                        version=version,
                        day=day,
                        events=trigger_descriptions,
                        state=final_state,
                        down_suppliers=list(down_suppliers),
                        active_delays=dict(active_delays),
                    )
                    if prev_snapshot is not None:
                        snapshot.diff = diff_snapshots(prev_snapshot, snapshot)
                    snapshot.narrative = self._generate_narrative(
                        snapshot.diff,
                        version,
                        day,
                        is_stand_down=False,
                        headline=snapshot.headline,
                    )
                    snapshots.append(snapshot)
                    prev_snapshot = snapshot
                    version += 1

            return snapshots

        finally:
            # Guaranteed cleanup in reverse order
            while undo_stack:
                undo = undo_stack.pop()
                try:
                    undo()
                except Exception:
                    pass

            # Fail-safe database restoration to initial values
            try:
                for sup_id, stat in initial_statuses.items():
                    self.session.execute(
                        update(Supplier)
                        .where(Supplier.supplier_id == sup_id)
                        .values(status=stat)
                    )
                self.session.execute(
                    delete(Order).where(
                        Order.order_id.like("SURGE-%"),
                        ~Order.order_id.in_(initial_surge_ids),
                    )
                )
                self.session.commit()
            except Exception:
                self.session.rollback()

            # Fail-safe logistics API delay restoration
            try:
                call_tool("clear_delays")
                for m, d in initial_delays.items():
                    call_tool("report_mode_delay", mode=m, extra_days=d)
            except Exception:
                pass

    @staticmethod
    def write_outputs(
        snapshots: list[PlanSnapshot], out_dir: str | Path
    ) -> tuple[Path, Path]:
        """Write timeline.json and a2a_replan_log.jsonl into out_dir."""
        return write_outputs(snapshots, out_dir)


def write_outputs(
    snapshots: list[PlanSnapshot], out_dir: str | Path
) -> tuple[Path, Path]:
    """Write timeline.json and a2a_replan_log.jsonl to the specified directory."""
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    timeline_file = out_path / "timeline.json"
    replan_log_file = out_path / "a2a_replan_log.jsonl"

    # 1. Write timeline.json (full list of snapshots without a2a_log)
    timeline_data = []
    for snap in snapshots:
        d = snap.model_dump()
        d.pop("a2a_log", None)
        timeline_data.append(d)

    with open(timeline_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(timeline_data, default=str, indent=2))

    # 2. Write a2a_replan_log.jsonl (all stamped messages across all snapshots)
    with open(replan_log_file, "w", encoding="utf-8") as f:
        for snap in snapshots:
            for msg in snap.a2a_log:
                f.write(json.dumps(msg, default=str) + "\n")

    return timeline_file, replan_log_file
