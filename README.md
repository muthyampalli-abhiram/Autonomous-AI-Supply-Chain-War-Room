# Autonomous AI Supply Chain War Room

An autonomous, multi-agent operational command center that detects supply chain bottlenecks, negotiates multi-tier supplier reroutings, optimizes multi-modal freight logistics, projects stockout risks, allocates purchase orders, evaluates financial SLA impacts, and dynamically replans across cascading disruption timelines.

---

## 1. System Architecture

The War Room operates as a directed LangGraph workflow coordinating six specialized domain agents through an in-process Agent-to-Agent (A2A) messaging bus, supported by Model Context Protocol (MCP) logistics tools, a NetworkX supply network graph, an SQLAlchemy database layer, and a dynamic replanning simulation engine.

```mermaid
flowchart TD
    subgraph Storage & Environment
        DB[(SQLAlchemy Database / SQLite or Postgres)]
        G[NetworkX Supply Network Graph]
        MCP[Simulated Logistics API & MCP Server]
    end

    subgraph Timeline Engine
        SIM[ReplanEngine / SimEvents Timeline]
    end

    subgraph LangGraph Orchestration & A2A Communication
        BUS[A2A In-Process Message Bus]
        INTAKE[Orchestrator Intake Node]
        SUP[1. Supplier Agent]
        INV[2. Inventory Agent]
        LOG[3. Logistics Agent]
        DEM[4. Demand Agent]
        PROC[5. Procurement Agent]
        CI[6. Customer Impact Agent]
        FIN[Orchestrator Finalize Node]
    end

    SIM -->|Simulate Outage / Delay / Surge| DB
    SIM -->|Build Graph Closure| INTAKE

    INTAKE -->|1. Disruption Detection| G
    INTAKE -->|Broadcast Announcement| BUS
    INTAKE -->|State Handoff| SUP

    SUP -->|Task Delegation & Result| BUS
    SUP -->|Query Alternatives & Score| DB
    SUP --> INV

    INV -->|Task Delegation & Result| BUS
    INV -->|Priority Stock Allocation| DB
    INV --> LOG

    LOG -->|Task Delegation & Result| BUS
    LOG -->|Lanes & Freight Quotes| MCP
    LOG --> DEM

    DEM -->|Task Delegation & Result| BUS
    DEM -->|Trend Clamp & Uplift| DB
    DEM --> PROC

    PROC -->|Task Delegation & Result| BUS
    PROC -->|Capacity Allocation & POs| DB
    PROC --> CI

    CI -->|Task Delegation & Result| BUS
    CI -->|SLA Penalty & Customer Risk| DB
    CI --> FIN

    FIN -->|Escalations & Final Plan| BUS
    FIN -->|Plan Snapshot & Diff| SIM
```

---

## 2. Technology Stack

| Technology / Component | Version / Type | System Role |
| :--- | :--- | :--- |
| **Python** | 3.10+ (tested on 3.11) | Core runtime environment |
| **LangGraph / LangChain** | StateGraph | Deterministic sequential pipeline coordination and state management |
| **A2A Messaging Bus** | In-process Pydantic | Structured AgentCard discovery, task lifecycle (`submitted` $\to$ `working` $\to$ `completed`/`failed`), broadcasts, and escalations |
| **Model Context Protocol (MCP)** | FastMCP / Stdio Server | Simulated logistics API tooling exposing quotes, carrier directories, and delay reporting |
| **Pandas / Plain Python** | 3.0+ | Deterministic multi-criteria scoring, inventory allocation, demand trend analysis, and SLA calculations |
| **NetworkX** | DiGraph (seed=42) | Multi-tier supply chain topology modeling and spring layout coordinate projection |
| **SQLAlchemy** | 2.0+ Declarative | Database ORM supporting SQLite (default local) and PostgreSQL production databases |
| **Plotly** | Graph Objects | Interactive financial trajectory, topology scatter network, SKU risk, and timeline figures |
| **Streamlit** | Web Application | Executive operational dashboard with timeline sliders, scenario reruns, and KPI delta metrics |

---

## 3. Installation & Setup

### Prerequisites
- Python 3.10 or higher
- Git

### Setup Steps (Windows PowerShell)
```powershell
# 1. Create and activate virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment variables
cp .env.example .env
```

### Setup Steps (macOS / Linux)
```bash
# 1. Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment variables
cp .env.example .env
```

---

## 4. Execution Workflow

Execute the command pipeline in order:

```bash
# 1. Generate synthetic supply chain baseline data
python scripts/generate_data.py

# 2. Inspect graph topology and simulate supplier failure detection
python scripts/demo_disruption.py

# 3. Execute full War Room multi-agent response pipeline for a catastrophic outage
python scripts/run_warroom.py --supplier SUP01

# 4. Execute the dynamic 14-day replanning simulation timeline
python scripts/run_replanning.py

# 5. Launch the Streamlit executive command dashboard
streamlit run src/warroom/dashboard/app.py

# 6. Run the complete test suite (69 collected: 68 run on SQLite and 1 PostgreSQL test is skipped unless POSTGRES_TEST_URL is set)
pytest
```

---

## 5. Agent Architecture, Logic & Formulas

Each agent inherits from `BaseAgent`, executes deterministic algorithms on local data, and reports execution telemetry through the A2A bus.

### 1. Supplier Agent (`SupplierAgent`)
- **Inputs**: Upstream disruption event (`supplier_id`, `affected_sku_count`) and graph impact.
- **Logic**: For each affected SKU, discovers active alternative suppliers from `supplier_skus`. Filters out disrupted suppliers. Computes multi-criteria score:
  $$\text{Score} = 0.40 \cdot \text{CostScore} + 0.35 \cdot \text{ReliabilityScore} + 0.25 \cdot \text{LeadTimeScore}$$
  where:
  $$\text{CostScore} = \frac{\min(\text{unit\_price})}{\text{unit\_price}}, \quad \text{LeadTimeScore} = \frac{\min(\text{lead\_time\_days})}{\text{lead\_time\_days}}$$
- **Outputs**: Recommended primary alternative and backup alternative per SKU, monthly price premium vs. baseline.

### 2. Inventory Agent (`InventoryAgent`)
- **Inputs**: Disrupted SKU set and supplier recommendations.
- **Logic**: Aggregates warehouse on-hand stock and allocates inventory to open customer orders within the disruption window ($H = 30$ days) using strict priority tiers:
  $$\text{Priority } 3 \text{ (Gold/Urgent)} \longrightarrow \text{Priority } 2 \text{ (Silver)} \longrightarrow \text{Priority } 1 \text{ (Bronze)}$$
  Orders with equal priority are sorted by earliest `due_date`, then `order_id`.
- **Outputs**: Per-SKU fill rate, warehouse allocation matrix, short orders, and critical SKU designations ($\text{fill rate} < 100\%$).

### 3. Logistics Agent (`LogisticsAgent`)
- **Inputs**: Recommended supplier origin countries, warehouse destinations, reference replenishment quantities.
- **Logic**: Evaluates freight routes across Air, Road, and Sea carriers using simulated logistics tools:
  $$\text{Freight Total} = (\text{CostPerKg} \cdot \text{UnitWeight} \cdot \text{Qty} \cdot \text{DistFactor}) + \text{HandlingFee}$$
  $$\text{Transit Days} = \max(1, \lceil \text{SpeedDays} \cdot \text{DistFactor} \rceil) + \text{ModeDelay}$$
  $$\text{Total Lead Time} = \text{SupplierLeadTime} + \text{Transit Days}$$
  For critical SKUs, selects the carrier and mode that strictly minimizes total lead time.
- **Outputs**: Recommended multi-modal lane selection, ETA arrival dates, expedited freight cost premiums, and mode mix.

### 4. Demand Agent (`DemandAgent`)
- **Inputs**: Baseline daily demand, recent order history, and disruption severity.
- **Logic**: Computes recent demand momentum over a 14-day window and clamps the trend factor:
  $$\text{TrendFactor} = \text{clamp}\left(\frac{\text{RecentDaily}}{\text{BaselineDaily}}, \, 0.8, \, 1.5\right)$$
  $$\text{ForecastDaily} = \text{BaselineDaily} \cdot \text{TrendFactor} \cdot (1 + \text{DisruptionUplift})$$
  $$\text{Projected Gap} = \max\left(0, \, (\text{ForecastDaily} \cdot \text{Horizon}) - \text{OnHands}\right)$$
- **Outputs**: SKU daily forecast, uncovered stockout days, projected volume gap, customer tier mix, and high-risk designations.

### 5. Procurement Agent (`ProcurementAgent`)
- **Inputs**: Projected replenishment gap, supplier capacities, supplier lead times, and freight modes.
- **Logic**: Slices order volume to fill the demand gap. Splits orders across recommended and backup suppliers according to monthly capacity limits. If gap exceeds total capacity, leaves remainder as unsourced volume. Applies executive approval flag if:
  $$\text{Total Landed Cost} > \$100,000$$
- **Outputs**: Purchase orders (PO IDs, quantities, prices, arrival dates, line costs), unsourced SKU volume, total freight, and approval status.

### 6. Customer Impact Agent (`CustomerImpactAgent`)
- **Inputs**: Inventory order allocations, procurement PO line arrival dates, and SKU selling prices.
- **Logic**: Matches procurement replenishment pools against short orders in priority order:
  $$\text{RecoveredQty} = \min(\text{ShortQty}, \, \text{SupplyPool})$$
  $$\text{DelayDays} = \max(0, \, (\text{FulfilmentDate} - \text{DueDate}).\text{days})$$
  $$\text{DelayedValue} = \text{RecoveredQty} \cdot \text{UnitPrice} \quad (\text{if DelayDays} > 0)$$
  $$\text{LostValue} = \text{UnrecoveredQty} \cdot \text{UnitPrice}$$
  $$\text{SLAPenalty} = \text{DelayedValue} \cdot \min(0.20, \, \text{PenaltyRate}_{\text{tier}} \cdot \text{DelayDays}) + (\text{LostValue} \cdot 0.20)$$
  Where daily penalty rates are Gold: 2%/day, Silver: 1%/day, Bronze: 0.5%/day, capped at 20%.
  Customer risk levels:
  - **CRITICAL**: Gold tier with $\text{LostValue} > 0$ or $\text{MaxDelay} \ge 14\text{d}$.
  - **HIGH**: Non-Gold tier with $\text{LostValue} > 0$ or $\text{MaxDelay} \ge 14\text{d}$.
  - **MEDIUM**: $\text{MaxDelay} > 0$.
  - **LOW**: No delays or lost volume.
- **Outputs**: Per-order recovery details, customer risk categorization, financial exposure totals, on-time service metrics, and value protected.

---

## 6. A2A Communication Protocol

The in-process Agent-to-Agent (A2A) bus coordinates domain agents using standardized Pydantic data schemas:

- **`AgentCard`**: Agent identity, description, capability skill tags, and schema version.
- **`A2AMessage`**: Formatted message (`MSG-0001`..) with sender, recipient, message type (`task_request`, `status_update`, `task_result`, `broadcast`, `escalation`), structured text/data payload parts, and UTC timestamp.
- **`A2ATask`**: Formal task lifecycle tracking strictly enforcing state transitions:
  $$\text{submitted} \longrightarrow \text{working} \longrightarrow \text{completed} \;\big|\; \text{failed}$$
  Artifacts returned upon completion are strictly constrained to agent status and summary.
- **Escalation Protocol**:
  - `procurement.approval_required` $\implies$ Escalates `orchestrator` $\to$ `human_approver` with total landed cost and PO count.
  - `procurement.unsourced_by_sku` not empty $\implies$ Escalates `orchestrator` $\to$ `supplier` requesting additional sourcing capacity.
  - `customer_impact.overall_risk in ("critical", "high")` $\implies$ Escalates `orchestrator` $\to$ `human_approver` with at-risk accounts.

---

## 7. How the Replanning Scenario Unfolds

The simulation timeline runs across 14 simulated days, dynamically adjusting allocations, routes, and risk levels:

| Plan Version | Day | Trigger Event | Status | Down Suppliers | Net Financial Exposure | Total Landed Cost | PO Count | Unsourced Gap | Active Adaptation & Narrative |
| :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **v1** | Day 0 | Primary supplier SUP01 outage declared across 7 critical SKUs | `REPLANNED` | `SUP01` | **$83,416.94** | $356,677.90 | 14 POs | 7,220 units | Baseline recovery plan formed; orders split across alternatives. |
| **v2** | Day 3 | Air freight capacity crunch adds +6 days delay to all air shipments | `REPLANNED` | `SUP01` | **$79,323.80** | $352,756.10 | 14 POs | 7,220 units | Logistics shifts SKU001, SKU002, SKU003, SKU006 from Air to Road freight. Exposure shifts by -$4,093.14. |
| **v3** | Day 6 | Secondary supplier SUP07 goes offline (backup source for SKU005) | `REPLANNED` | `SUP01, SUP07` | **$81,594.50** | $348,651.70 | 14 POs | 7,240 units | Supplier reroutes SKU005 from SUP07 to SUP10. Exposure shifts by +$2,270.70. |
| **v4** | Day 10 | Demand surge for SKU004 (+50% volume from Gold customers due in 7d) | `REPLANNED` | `SUP01, SUP07` | **$139,654.44** | $348,459.20 | 14 POs | 11,510 units | Demand forecast for SKU004 spikes to 189.9 units/day; unsourced volume widens. Exposure increases by +$58,059.94. |
| **v5** | Day 14 | Primary supplier SUP01 fully restored to active operations | `STAND_DOWN` | `SUP07` | **$0.00** | $0.00 | 0 POs | 0 units | All primary disruptions resolved. War room stands down with zero financial exposure (-$139,654.44). |

Order dates and delivery windows are computed from the run date, so exact figures shift slightly from day to day.

---

## 8. Switching from SQLite to PostgreSQL

The codebase is built on declarative SQLAlchemy 2.0 and supports PostgreSQL with zero code changes:

1. Update `.env`:
   ```ini
   # Switch from SQLite to PostgreSQL
   DB_URL=postgresql+psycopg2://warroom:warroom@localhost:5432/warroom
   ```
2. Re-create the database schema and populate synthetic baseline data:
   ```bash
   python scripts/generate_data.py
   ```
3. Run the War Room pipeline or replanning engine as normal.

### Verified on PostgreSQL

The entire multi-agent war room pipeline and data generation layer have been verified on PostgreSQL 16. You can run PostgreSQL via the included `docker-compose.yml` or connect to an existing local PostgreSQL installation.

#### Option A: Running via Docker Compose

1. **Start PostgreSQL 16 container**:
   ```bash
   docker compose up -d
   ```
   *(This launches a PostgreSQL 16 service with user `warroom`, password `warroom`, database `warroom` on port 5432 with health check and named volume `pgdata`.)*

2. **Configure database URL**:
   - On Bash / macOS / Linux:
     ```bash
     export DB_URL="postgresql+psycopg2://warroom:warroom@localhost:5432/warroom"
     ```
   - On Windows PowerShell:
     ```powershell
     $env:DB_URL="postgresql+psycopg2://warroom:warroom@localhost:5432/warroom"
     ```
   - Or uncomment the line in `.env`:
     ```ini
     DB_URL=postgresql+psycopg2://warroom:warroom@localhost:5432/warroom
     ```

3. **Generate synthetic schema and baseline data**:
   ```bash
   python scripts/generate_data.py
   ```

4. **Verify database connection and row counts**:
   ```bash
   python scripts/check_db.py
   ```
   *(Prints dialect `postgresql`, server version, and row count per table, verifying all 781 records.)*

5. **Execute the War Room pipeline for supplier disruption**:
   ```bash
   python scripts/run_warroom.py --supplier SUP01
   ```

6. **Run PostgreSQL integration tests**:
   - On Bash / macOS / Linux:
     ```bash
     POSTGRES_TEST_URL="postgresql+psycopg2://warroom:warroom@localhost:5432/warroom" pytest -m postgres
     ```
   - On Windows PowerShell:
     ```powershell
     $env:POSTGRES_TEST_URL="postgresql+psycopg2://warroom:warroom@localhost:5432/warroom"
     pytest -m postgres
     ```

#### Option B: Local PostgreSQL Installation (without Docker)

If Docker is not installed or running, you can use a local PostgreSQL server:
1. Create a database and user:
   ```sql
   CREATE USER warroom WITH PASSWORD 'warroom';
   CREATE DATABASE warroom OWNER warroom;
   ```
2. Set `DB_URL="postgresql+psycopg2://warroom:warroom@localhost:5432/warroom"` (or your custom credentials).
3. Run steps 3 through 6 above.

---

## 9. Design Decisions & Limitations

1. **Deterministic Execution with Optional LLM Summarization**:
   All routing, scoring, allocation, forecasting, and penalty calculations are executed deterministically using Pandas and pure Python algorithms. If an LLM is enabled (`MOCK_LLM=False`), it is strictly used to word executive narratives from verified facts. An LLM failure or timeout will never break the pipeline.
2. **In-Process A2A Architecture**:
   The A2A messaging layer implements Agent Cards, sequential tasks, and message typing in-process rather than through distributed HTTP endpoints to ensure deterministic reproducibility, millisecond test runs, and zero networking flakiness.
3. **Logistics Tooling & MCP**:
   Logistics calculations are exposed via Model Context Protocol (MCP) tool bindings using FastMCP while sharing the same deterministic calculation engine.
4. **Timeline Simplifications**:
   Between replanning events, days serve as discrete timeline labels; inventory does not undergo continuous hourly depletion between event triggers.
5. **Distance & Freight Model**:
   Distances are modeled using inter-regional coefficients (same region: 0.4, adjacent: 0.7, intercontinental: 1.0) rather than real-time GPS routing APIs.
6. **Run-Date Relative Calculations**:
   Order dates and delivery windows are computed from the run date, so exact figures shift slightly from day to day.

---

## 10. Project Structure

```
Autonomous AI Supply Chain War Room/
├── README.md                               # Technical reference & system documentation
├── docker-compose.yml                      # PostgreSQL 16 container service configuration
├── pytest.ini                              # Test configuration
├── requirements.txt                        # Project dependencies
├── scripts/
│   ├── check_db.py                         # Database dialect, version & row count diagnostics
│   ├── demo_disruption.py                  # Disruption detection & topology impact demo
│   ├── generate_data.py                    # Synthetic supply chain database generator
│   ├── mcp_smoke_test.py                   # In-process FastMCP tool calling smoke test
│   ├── package_project.py                  # Packaging script for distributable zip archive
│   ├── run_replanning.py                   # Dynamic replanning timeline runner
│   └── run_warroom.py                      # Single-disruption LangGraph orchestrator runner
├── src/
│   └── warroom/
│       ├── a2a/                            # In-process Agent-to-Agent protocol
│       │   ├── bus.py                      # Synchronous A2ABus message router & task tracker
│       │   └── models.py                   # AgentCard, A2AMessage, A2ATask schemas
│       ├── agents/                         # Domain-specific LangGraph agent implementations
│       │   ├── base.py                     # BaseAgent interface & node wrapping helper
│       │   ├── customer_impact_agent.py    # Order recovery, SLA penalties & risk tiers
│       │   ├── demand_agent.py             # Trend clamping, uplifts & stockout projections
│       │   ├── inventory_agent.py          # Priority-tier order allocation & fill rates
│       │   ├── llm.py                      # Safe narrative summarization helper
│       │   ├── logistics_agent.py          # Multi-modal freight quotes & lead time optimization
│       │   ├── procurement_agent.py        # Purchase order generation & capacity allocation
│       │   ├── stubs.py                    # Legacy testing stubs (unused)
│       │   └── supplier_agent.py           # Multi-criteria alternative vendor discovery
│       ├── config.py                       # Pydantic system settings
│       ├── dashboard/                      # Streamlit & Plotly operational command center
│       │   ├── app.py                      # Main Streamlit UI application
│       │   ├── data.py                     # Pure data transformation & network frames
│       │   └── figures.py                  # Plotly visualizations (exposure, network, risk)
│       ├── data_gen/                       # Synthetic seed data generators & DB loaders
│       ├── db/                             # SQLAlchemy models & session factory
│       ├── graph/                          # NetworkX topology analysis & disruption detection
│       ├── orchestrator/                   # LangGraph StateGraph workflow definition
│       ├── replanning/                     # Dynamic timeline simulator & versioning engine
│       │   ├── engine.py                   # ReplanEngine & guaranteed cleanup
│       │   ├── events.py                   # SimEvent models & mutation handlers
│       │   ├── scenario.py                 # Default 5-event timeline scenario
│       │   └── snapshot.py                 # PlanSnapshot model & diffing engine
│       └── tools/                          # Logistics API registry & FastMCP server
└── tests/                                  # Comprehensive pytest suite (69 collected: 68 run on SQLite and 1 PostgreSQL test is skipped unless POSTGRES_TEST_URL is set)
    ├── test_a2a.py                         # A2A bus, card discovery, and task lifecycle tests
    ├── test_agents_demand_procurement.py   # Demand and procurement determinism tests
    ├── test_agents_supplier_inventory.py   # Supplier and inventory agent tests
    ├── test_customer_impact.py             # Customer impact, SLA caps & conservation tests
    ├── test_dashboard.py                   # Dashboard data processing & Plotly figure tests
    ├── test_data_gen.py                    # Database schema & synthetic generator tests
    ├── test_graph.py                       # NetworkX supply graph & disruption detection tests
    ├── test_logistics.py                   # Logistics tools, MCP server & mode selection tests
    ├── test_orchestrator.py                # LangGraph message ordering & state tests
    ├── test_postgres.py                    # PostgreSQL integration, schema & headline parity tests
    └── test_replanning.py                  # 14-day timeline replanning, diff & cleanup tests
```
