"""Unit tests for deterministic CustomerImpactAgent within the War Room graph."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from warroom.agents.customer_impact_agent import (
    CustomerImpactAgent,
    PENALTY_CAP,
    PENALTY_PCT_PER_DAY,
)
from warroom.data_gen.generator import generate_all
from warroom.data_gen.loader import load_to_db
from warroom.db.session import init_db
from warroom.graph.detection import simulate_supplier_outage
from warroom.orchestrator.graph import build_warroom_graph
from warroom.orchestrator.state import create_initial_state


@pytest.fixture
def memory_session():
    """Create an isolated in-memory SQLite database populated with synthetic data."""
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    init_db(engine=engine, drop=True)
    dfs = generate_all(seed=42)
    load_to_db(dfs, engine=engine)

    with Session(engine) as session:
        yield session

    engine.dispose()


def test_customer_impact_agent_real_and_no_stubs(memory_session: Session):
    """Verify CustomerImpactAgent is real (no [STUB] prefix) and zero stubs remain in the graph."""
    simulate_supplier_outage(memory_session, "SUP01")
    graph = build_warroom_graph(memory_session)
    state = create_initial_state()

    result = graph.invoke(state)

    # 1. Customer impact result exists and is real
    ci_res = result.get("customer_impact_result")
    assert ci_res is not None
    assert ci_res["status"] == "ok"
    assert not ci_res["summary"].startswith("[STUB]")
    assert "Customer impact assessment" in ci_res["summary"]

    # 2. No stubs remain anywhere in the graph
    all_agent_keys = [
        "supplier_result",
        "inventory_result",
        "logistics_result",
        "demand_result",
        "procurement_result",
        "customer_impact_result",
    ]
    for key in all_agent_keys:
        res = result[key]
        assert res["status"] == "ok"
        assert not res["summary"].startswith("[STUB]"), f"Agent {key} is still returning stub"

    # 3. Message sequence is preserved exactly
    messages = result.get("messages", [])
    expected_order = [
        "orchestrator",
        "supplier",
        "inventory",
        "logistics",
        "demand",
        "procurement",
        "customer_impact",
    ]
    assert [m["from"] for m in messages] == expected_order


def test_customer_impact_order_recovery_conservation(memory_session: Session):
    """Verify that for every per-order row: recovered_qty + unrecovered_qty == short_qty."""
    simulate_supplier_outage(memory_session, "SUP01")
    graph = build_warroom_graph(memory_session)
    state = create_initial_state()
    result = graph.invoke(state)

    ci_data = result["customer_impact_result"]["data"]
    per_order = ci_data.get("per_order", [])
    assert len(per_order) > 0, "Expected at least one short order under SUP01 outage"

    for order in per_order:
        short_qty = order["short_qty"]
        recovered_qty = order["recovered_qty"]
        unrecovered_qty = order["unrecovered_qty"]

        assert short_qty > 0
        assert recovered_qty >= 0
        assert unrecovered_qty >= 0
        assert (
            recovered_qty + unrecovered_qty == short_qty
        ), f"Conservation failed for order {order['order_id']}: {recovered_qty} + {unrecovered_qty} != {short_qty}"


def test_customer_impact_financial_totals_and_customer_sums(memory_session: Session):
    """Verify financials totals equal the sums of per_order and per_customer rows."""
    simulate_supplier_outage(memory_session, "SUP01")
    graph = build_warroom_graph(memory_session)
    state = create_initial_state()
    result = graph.invoke(state)

    ci_data = result["customer_impact_result"]["data"]
    per_order = ci_data.get("per_order", [])
    per_customer = ci_data.get("per_customer", {})
    financials = ci_data.get("financials", {})

    # Check order counts
    assert financials["orders_at_risk"] == len(per_order)
    expected_delayed = sum(1 for o in per_order if o["delay_days"] is not None and o["delay_days"] > 0)
    assert financials["orders_delayed"] == expected_delayed
    expected_unfulfilled = sum(1 for o in per_order if o["unrecovered_qty"] > 0)
    assert financials["orders_unfulfilled"] == expected_unfulfilled

    # Check order sums
    sum_delayed_val = round(sum(o["delayed_value"] for o in per_order), 2)
    sum_lost_val = round(sum(o["lost_value"] for o in per_order), 2)
    sum_sla_pen = round(sum(o["sla_penalty"] for o in per_order), 2)

    assert financials["revenue_delayed"] == sum_delayed_val
    assert financials["revenue_lost"] == sum_lost_val
    assert financials["sla_penalty_total"] == sum_sla_pen

    # Check customer sums match order sums
    cust_delayed_sum = round(sum(c["delayed_value"] for c in per_customer.values()), 2)
    cust_lost_sum = round(sum(c["lost_value"] for c in per_customer.values()), 2)
    cust_sla_sum = round(sum(c["sla_penalty"] for c in per_customer.values()), 2)
    cust_short_sum = sum(c["short_qty"] for c in per_customer.values())
    cust_orders_sum = sum(c["orders_affected"] for c in per_customer.values())

    assert cust_delayed_sum == pytest.approx(financials["revenue_delayed"], abs=0.01)
    assert cust_lost_sum == pytest.approx(financials["revenue_lost"], abs=0.01)
    assert cust_sla_sum == pytest.approx(financials["sla_penalty_total"], abs=0.01)
    assert cust_short_sum == sum(o["short_qty"] for o in per_order)
    assert cust_orders_sum == len(per_order)

    # Net financial exposure check
    expected_net = round(
        financials["revenue_lost"] + financials["sla_penalty_total"] + financials["response_cost"], 2
    )
    assert financials["net_financial_exposure"] == expected_net


def test_customer_impact_sla_penalty_bounds(memory_session: Session):
    """Verify that sla_penalty >= 0 and <= PENALTY_CAP * (delayed_value + lost_value) for every order."""
    simulate_supplier_outage(memory_session, "SUP01")
    graph = build_warroom_graph(memory_session)
    state = create_initial_state()
    result = graph.invoke(state)

    ci_data = result["customer_impact_result"]["data"]
    per_order = ci_data.get("per_order", [])

    for order in per_order:
        delayed_val = order["delayed_value"]
        lost_val = order["lost_value"]
        penalty = order["sla_penalty"]

        assert penalty >= 0.0, f"SLA penalty {penalty} is negative for order {order['order_id']}"
        max_penalty = round(PENALTY_CAP * (delayed_val + lost_val), 2)
        assert penalty <= max_penalty + 0.01, (
            f"SLA penalty {penalty} exceeds cap {max_penalty} for order {order['order_id']}"
        )


def test_customer_impact_risk_level_rules(memory_session: Session):
    """Verify customer risk_level conforms strictly to the specified business rules."""
    simulate_supplier_outage(memory_session, "SUP01")
    graph = build_warroom_graph(memory_session)
    state = create_initial_state()
    result = graph.invoke(state)

    ci_data = result["customer_impact_result"]["data"]
    per_customer = ci_data.get("per_customer", {})

    for cust_id, cust_info in per_customer.items():
        assert cust_info["orders_affected"] > 0, f"Customer {cust_id} with 0 orders was not omitted"

        tier = cust_info["tier"]
        lost_val = cust_info["lost_value"]
        max_delay = cust_info["max_delay_days"]
        actual_risk = cust_info["risk_level"]

        is_gold = (tier == "gold")
        has_lost_or_long = (lost_val > 0 or max_delay >= 14)

        if is_gold and has_lost_or_long:
            expected_risk = "critical"
        elif has_lost_or_long:
            expected_risk = "high"
        elif max_delay > 0:
            expected_risk = "medium"
        else:
            expected_risk = "low"

        assert (
            actual_risk == expected_risk
        ), f"Customer {cust_id} ({tier}) risk {actual_risk} != expected {expected_risk} (lost={lost_val}, delay={max_delay})"


def test_customer_impact_determinism_and_missing_inputs(memory_session: Session):
    """Verify determinism across two runs and error status handling on missing/failed inputs."""
    simulate_supplier_outage(memory_session, "SUP01")
    graph = build_warroom_graph(memory_session)

    # Determinism
    res1 = graph.invoke(create_initial_state())
    res2 = graph.invoke(create_initial_state())

    ci1 = res1["customer_impact_result"]["data"]
    ci2 = res2["customer_impact_result"]["data"]

    assert ci1["financials"] == ci2["financials"]
    assert ci1["service"] == ci2["service"]
    assert ci1["plan_effect"] == ci2["plan_effect"]
    assert ci1["overall_risk"] == ci2["overall_risk"]
    assert ci1["top_customers_at_risk"] == ci2["top_customers_at_risk"]
    assert len(ci1["per_order"]) == len(ci2["per_order"])
    assert len(ci1["per_customer"]) == len(ci2["per_customer"])

    # Missing inputs
    agent = CustomerImpactAgent(memory_session)

    # 1. Empty state
    empty_res = agent.run(create_initial_state())
    assert empty_res.status == "error"
    assert "required" in empty_res.summary.lower() or "missing" in empty_res.summary.lower()

    # 2. Upstream status == "error"
    err_state = dict(res1)
    err_state["procurement_result"] = {"status": "error", "summary": "Failed", "data": {}}
    err_res = agent.run(err_state)
    assert err_res.status == "error"
