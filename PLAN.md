# GRIDIRON BUILD PLAN

## 1. FULL FILE-TREE PLAN

```
gridiron/
├── league_config.yaml              # §1 — Single source of truth for league rules
├── config/
│   ├── __init__.py
│   ├── settings.py                 # Paths, API keys (env), seeds, thresholds
│   └── thresholds.yaml             # Exposed thresholds (posture band, ΔP cutoff, etc.)
├── data/
│   ├── ingest/
│   │   ├── __init__.py
│   │   ├── nflreadpy_client.py     # Play-by-play, weekly stats, snap counts
│   │   ├── projections_scraper.py  # Consensus from ≥3 public sources
│   │   ├── odds_client.py          # The Odds API client (budgeted ≤2 calls/week)
│   │   ├── nfl_fantasy_reader.py   # Unofficial API + manual CSV fallback
│   │   └── schemas.py              # Pydantic schemas for each data source
│   ├── warehouse.duckdb            # DuckDB database (append-only tables)
│   └── parquet/                    # Raw immutable snapshots
│       └── .gitkeep
├── core/
│   ├── __init__.py
│   ├── scoring.py                  # THE scoring function (only implementation)
│   ├── ids.py                      # Player-ID crosswalk service
│   ├── projections.py              # Consensus anchor + LightGBM quantile residuals
│   ├── correlation.py              # Game-script sim: team totals → player draws
│   ├── replacement.py              # League-size-correct FA-level replacement
│   └── rng.py                      # Seeded RNG service (H4 compliance)
├── engines/
│   ├── __init__.py
│   ├── draft/
│   │   ├── __init__.py
│   │   ├── vorp_board.py           # VORP calculation + tier detection
│   │   ├── pick_optimizer.py       # Snake-aware pick optimizer (2-round lookahead)
│   │   ├── live_tracker.py         # Draft state tracker
│   │   └── cheat_sheet.py          # Per-slot draft cheat sheet generator
│   ├── lineup/
│   │   ├── __init__.py
│   │   ├── optimizer.py            # Weekly optimizer with I5 posture logic
│   │   ├── posture.py              # E[pts] vs P(win) regime selector
│   │   └── late_window.py          # Post-lock pivot module (I7)
│   ├── waivers/
│   │   ├── __init__.py
│   │   ├── screener.py             # Usage-delta candidate screener
│   │   ├── valuation.py            # ΔP(playoffs) per candidate
│   │   └── priority.py             # Rolling-priority option logic (I8)
│   ├── streams/
│   │   ├── __init__.py
│   │   ├── def_board.py            # DEF stream board (opponent implied total driven)
│   │   ├── k_board.py              # K stream board (implied total + weather)
│   │   └── qb_board.py             # QB stream board (rushing-value aware)
│   └── season/
│       ├── __init__.py
│       ├── monte_carlo.py          # Rest-of-season Monte Carlo engine
│       ├── standings.py            # Standings projector
│       └── playoff_odds.py         # P(playoffs)/P(bye)/E[pts_for percentile]
├── sim/
│   ├── __init__.py
│   ├── kernel.py                   # Shared simulation kernel (10k scenarios)
│   └── scenarios.py                # Scenario generation utilities
├── ui/
│   ├── __init__.py
│   ├── draft_dashboard/
│   │   ├── __init__.py
│   │   ├── app.py                  # Local HTML dashboard (Sektor-Regime-Terminal skeleton)
│   │   ├── templates/
│   │   │   └── draft.html
│   │   └── static/
│   │       └── style.css
│   └── telegram/
│       ├── __init__.py
│       ├── bot.py                  # Telegram bot client
│       └── cards.py                # Card formatters (lineup, waiver, pivot, Brier)
├── eval/
│   ├── __init__.py
│   ├── backtest.py                 # Historical validation harness
│   ├── calibration.py              # Brier score, quantile coverage
│   ├── test_horizontal.py          # Horizontal audit tests (H1-H6)
│   ├── test_vertical_*.py          # Per-module vertical tests
│   ├── fixtures/                   # Hand-computed test fixtures
│   │   ├── scoring_week14_2023.json
│   │   └── ...
│   └── decisions_log.parquet       # In-season decision tracking
├── ops/
│   ├── __init__.py
│   ├── timers/
│   │   ├── gridiron-tue-refresh.timer
│   │   ├── gridiron-wed-sweep.timer
│   │   ├── gridiron-thu-prelim.timer
│   │   ├── gridiron-sun-final.timer
│   │   ├── gridiron-sun-pivot.timer
│   │   ├── gridiron-mon-calibration.timer
│   │   └── corresponding.service files
│   ├── cli.py                      # Manual CLI entrypoints (fallback for every timer)
│   └── watchdog.py                 # "Did-not-run" watchdog with Telegram alert
├── Makefile                        # Build targets, audit automation
├── pyproject.toml                  # Dependencies, tool config
├── README.md                       # Quickstart, architecture overview
├── DECISIONS.md                    # Design decisions with rationale (feature cuts logged here)
├── RISKS.md                        # Residual risks, failure modes, fallbacks
└── GATES.md                        # Phase gate reports, adversarial critiques, known weaknesses
```

---

## 2. PHASE 0–1 TASK BREAKDOWN

### PHASE 0 — Skeleton, Config, Scoring Kernel, ID Crosswalk
**Estimated Time: 8–12 hours**

| Task | Description | Estimate |
|------|-------------|----------|
| **0.1** | Create repo scaffold (directory structure, .gitignore, pyproject.toml) | 1h |
| **0.2** | Write `league_config.yaml` (exact spec from §1) | 0.5h |
| **0.3** | Write `config/settings.py` (paths, env vars, seed discipline) | 1h |
| **0.4** | Write `config/thresholds.yaml` (exposed thresholds with defaults) | 0.5h |
| **0.5** | Implement `core/scoring.py` (THE scoring function, typed, docstring'd) | 3h |
| **0.6** | Create `eval/fixtures/` with ≥10 hand-computed scoring fixtures | 2h |
| **0.7** | Write `core/ids.py` (player-ID crosswalk service, namespace contract) | 1.5h |
| **0.8** | Initialize DuckDB schema (`data/warehouse.duckdb`) | 1h |
| **0.9** | Write vertical tests for scoring.py (fixture replay, exact match) | 2h |
| **0.10** | Write horizontal audit stub (`eval/test_horizontal.py`, H1-H6 placeholders) | 1h |
| **0.11** | Write GATES.md Phase 0 gate report (macro check paragraph) | 0.5h |
| **0.12** | Run adversarial critique (3 ways Phase 0 could be wrong) + refine | 1h |

**Phase 0 Gate Criteria:**
- [ ] scoring.py reproduces ≥10 hand-computed fixtures (exact match)
- [ ] DEF ladder breakpoints verified (20 vs 21 allowed = 1 vs 0 pts)
- [ ] FG 50+ = 5 pts, reception = 1.0, pass TD = 4 (not 6)
- [ ] GATES.md contains macro-check paragraph
- [ ] All horizontal audit stubs in place (H1-H6, even if trivial at this stage)

---

### PHASE 1 — Data Layer
**Estimated Time: 16–24 hours**

| Task | Description | Estimate |
|------|-------------|----------|
| **1.1** | Implement `data/ingest/schemas.py` (Pydantic schemas for all sources) | 2h |
| **1.2** | Implement `data/ingest/nflreadpy_client.py` (play-by-play, weekly stats, snaps) | 3h |
| **1.3** | Implement `data/ingest/projections_scraper.py` (≥3 sources, graceful degradation) | 4h |
| **1.4** | Implement `data/ingest/odds_client.py` (The Odds API, budget assert ≤2 calls/week) | 2h |
| **1.5** | Implement `data/ingest/nfl_fantasy_reader.py` (unofficial API + MANUAL CSV fallback) | 3h |
| **1.6** | Create manual-entry CSV templates (fully operable if endpoints die) | 1h |
| **1.7** | Write schema tests + staleness monitors + row-count sanity bounds | 2h |
| **1.8** | Write "corrupt input" test (pipeline refuses loudly on garbage) | 1h |
| **1.9** | Implement ID mapping through `core/ids.py`, report unmapped rate (<2%) | 2h |
| **1.10** | Ensure timestamps stored UTC, rendered Europe/Berlin | 1h |
| **1.11** | Document external dependency failure modes + fallbacks in RISKS.md | 1h |
| **1.12** | Write Phase 1 gate report + adversarial critique | 1h |

**Phase 1 Gate Criteria:**
- [ ] Each data source has schema test + staleness monitor + row-count bounds
- [ ] Corrupt-input test passes (pipeline refuses, doesn't compute on garbage)
- [ ] Unmapped player-ID rate <2% (or documented exception)
- [ ] Timestamps: UTC storage, Europe/Berlin rendering
- [ ] RISKS.md documents each dependency's failure mode + fallback
- [ ] Manual CSV fallback is first-class (system operable if API dies)

---

## 3. ASSUMPTIONS LIST (with verification steps)

| # | Assumption | Source | Verification Step |
|---|------------|--------|-------------------|
| **A1** | NFL Fantasy unofficial API (`api.fantasy.nfl.com`) endpoints exist and are accessible with session cookies | Common knowledge in fantasy dev communities | Attempt authenticated request in Phase 1; if fails, fall back to manual CSV as primary (already designed as first-class) |
| **A2** | The Odds API free tier (500 req/month) allows access to NFL team totals and player props | The Odds API documentation | Test call in Phase 1; confirm endpoint availability; log actual monthly burn rate |
| **A3** | nflreadpy package provides play-by-play, snap counts, depth charts for NFL data | Package documentation | Import and query in Phase 1; verify data availability for 2023–2024 seasons |
| **A4** | DuckDB can run locally without cloud dependencies | DuckDB documentation | Install and create warehouse in Phase 0; confirm no cloud auth required |
| **A5** | Telegram Bot API works via simple HTTP requests (no OAuth complexity) | Telegram Bot API docs | Create test bot in Phase 7; send message; confirm simplicity |
| **A6** | Public consensus projections are available from ≥3 sources without JS rendering | Known sources: FantasyPros, ESPN, CBS | Scrape test in Phase 1; if JS-rendered, fall back to fewer sources (log tradeoff per spec) |
| **A7** | systemd timers are available on user's local machine (Linux with systemd) | User spec mentions systemd | Confirm in Phase 7; if unavailable, CLI fallback is already designed as equivalent |
| **A8** | Last season's table provided is accurate and complete | User-provided spec | Accept as ground truth; no verification needed (user-supplied fact) |
| **A9** | Rolling waiver priority is the default (not FAAB) | Spec says "ASSUMED default; verify in-app week 1" | Verify in Week 1 of actual season; FAAB adapter stub already designed behind interface |
| **A10** | 4 playoff teams is correct (seeds 1–4; 5th+ out) | User spec | Accept as ground truth (league rule) |
| **A11** | Two-week aggregate final (weeks 16–17) is correct | User spec | Accept as ground truth (league rule) |
| **A12** | Points-for tiebreaker governs both seeding AND playoff cutoff | User spec + last season observation | Accept as ground truth; encode in season engine explicitly |
| **A13** | No keeper rules (pure redraft) | User spec | Accept as ground truth |
| **A14** | Trade deadline is none (trades allowed all season) | User spec | Accept as ground truth; expect minimal trades per spec |
| **A15** | Adds per week is unlimited | User spec | Accept as ground truth |
| **A16** | Waiver period is 1 day | User spec | Accept as ground truth; configurable in `league_config.yaml` |
| **A17** | Free agents lock per-game at kickoff (not whole roster on Sunday) | User spec | Accept as ground truth; critical for I7 late-window logic |
| **A18** | IR slots = 3, bench = 6, starters = 9 | User spec | Accept as ground truth; encoded in `league_config.yaml` |
| **A19** | Scoring rules exactly as specified (especially DEF ladder step function) | User spec | Verify against official league settings in Week 0; treat spec as authoritative until contradicted |
| **A20** | Opponent skill prior is "semi-informed" (follow public rankings) | User spec | Encode as ADP-based opponent model in draft engine; validate behavior in simulation |
| **A21** | Timezone Europe/Berlin for user-facing output | User spec | Hardcode in `config/settings.py`; test rendering in Phase 1 |
| **A22** | Zero-cost constraint means no APIs requiring credit card | User spec | Enforce in code review; grep for paid API references |
| **A23** | Local execution means no cloud deployment | User spec | Enforce in architecture; all paths are local filesystem |
| **A24** | Python 3.11+ is available on user's machine | Style/quality bar | Check in Phase 0; fail early if version mismatch |
| **A25** | Polars, DuckDB, LightGBM can be installed locally without issues | Package availability | Install in Phase 0; document any platform-specific issues |

---

## 4. CRITICAL PATH DEPENDENCIES

```
Phase 0 (scoring.py exactness) 
    ↓
Phase 1 (data ingestion under exact scoring) 
    ↓
Phase 2 (projections calibrated to exact scoring) 
    ↓
Phase 3 (VORP computed on exact scoring + replacement) 
    ↓
Phase 4 (draft engine optimizing exact-scoring VORP) 
    ↓
Phase 5 (lineup sim using exact scoring + calibrated projections) 
    ↓
Phase 6 (season engine + waivers using same sim kernel) 
    ↓
Phase 7 (ops automation of all above) 
    ↓
Phase 8 (validation of entire chain)
```

**No phase may proceed without passing its gate.** This is non-negotiable per spec.

---

## 5. OPEN QUESTIONS FOR USER

Before proceeding to code, please confirm:

1. **Draft slot**: Do you know your draft slot yet, or should I build all outputs parameterized (default: generate for all slots 1–10)?

2. **NFL Fantasy API access**: Are you comfortable providing session cookies for the unofficial API, or should I prioritize the manual CSV workflow as the primary path?

3. **Telegram bot**: Do you already have a Telegram bot token, or should I include setup instructions in Phase 7?

4. **Historical data scope**: For backtests, should I target 2021–2024 (4 seasons) or adjust based on data availability?

5. **Machine specs**: Any constraints I should know about (RAM, CPU, OS) for sizing the simulation workloads?

---

**Awaiting approval before writing code.** Once approved, I will begin Phase 0, Task 0.1.
