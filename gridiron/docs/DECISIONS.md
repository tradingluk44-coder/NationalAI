# GRIDIRON Decision Log

This file documents all design decisions, tradeoffs, and rationale for the GRIDIRON fantasy football system.

## Decision Format

Each entry follows this format:
- **ID**: Unique identifier (D001, D002, etc.)
- **Date**: Decision date
- **Status**: Proposed | Accepted | Rejected | Superseded
- **Context**: What situation prompted this decision
- **Decision**: What was decided
- **Rationale**: Why this decision advances the macro objective
- **Consequences**: Expected outcomes and tradeoffs

---

## Decisions

### D001 — Single Scoring Implementation (H1 Contract)
- **Date**: 2025-08-03
- **Status**: Accepted
- **Context**: Need to ensure scoring consistency across all modules (draft, sim, lineup, waivers)
- **Decision**: All scoring logic lives exclusively in `core/scoring.py`; no numeric scoring literals anywhere else
- **Rationale**: Prevents drift between modules; a bug fix in one place fixes everywhere
- **Consequences**: Any module needing scoring must import `compute_player_score()`; grep-audit enforces this

### D002 — DEF Points Allowed as Step Function
- **Date**: 2025-08-03
- **Status**: Accepted
- **Context**: League rules specify discrete breakpoints (20 PA = 1pt, 21 PA = 0pt)
- **Decision**: Implement as explicit step function with no interpolation
- **Rationale**: Micro Focus (Lens C) — exact rule implementation; interpolation would be incorrect
- **Consequences**: `compute_def_points_allowed()` uses range matching, not linear interpolation

### D003 — FG 50+ = 5 Points (Not 4)
- **Date**: 2025-08-03
- **Status**: Accepted
- **Context**: Standard NFL Fantasy scoring uses 4 pts for 50+ FG; this league uses 5
- **Decision**: Encode explicitly in config and scoring module
- **Rationale**: Macro objective requires exact rule compliance; 1 pt difference affects kicker valuation
- **Consequences**: Kicker stream board will prioritize long-distance kickers more than standard systems

### D004 — Replacement Level = Free Agent (Not Last Drafted)
- **Date**: 2025-08-03
- **Status**: Accepted
- **Context**: Traditional VORP uses "last drafted player" as replacement
- **Decision**: Replacement = best projected undrafted (free agent) player per position
- **Rationale**: More accurate for in-season waiver valuation; reflects true opportunity cost
- **Consequences**: VORP values will differ from published ADP-based systems; more accurate for this league's FA dynamics

### D005 — Posture Band 40–60% for P(win) Optimization
- **Date**: 2025-08-03
- **Status**: Accepted
- **Context**: I5 invariant specifies when to deviate from E[points] maximization
- **Decision**: Switch to P(win) optimization only when 0.40 ≤ P(win) ≤ 0.60 in playoff-relevant weeks
- **Rationale**: Balances points_for tiebreaker value with win probability in close matchups
- **Consequences**: Lineup recommendations may differ from expectation-maximizing lineups in ~20% of weeks

### D006 — Two-Week Aggregate Final Modeled Explicitly
- **Date**: 2025-08-03
- **Status**: Accepted
- **Context**: Weeks 16–17 are aggregated for championship determination
- **Decision**: Sim engine treats weeks 16–17 as single joint distribution, not independent events
- **Rationale**: Lower variance event; affects Week 15 (semifinal) risk posture
- **Consequences**: Week 15 may recommend higher-variance plays if underdog; weeks 16–17 maximize expectation

### D007 — Rolling Waivers Assumed (FAAB Adapter Stubbed)
- **Date**: 2025-08-03
- **Status**: Accepted
- **Context**: League uses rolling priority waivers by default; FAAB possible but unlikely
- **Decision**: Build rolling priority as primary; FAAB adapter behind interface for week-1 discovery flip
- **Rationale**: I8 invariant requires priority-spend thresholds; FAAB would need different valuation
- **Consequences**: One config line changes waiver engine behavior if league uses FAAB

### D008 — Backtest Scope: 2021–2025 (5 Seasons)
- **Date**: 2025-08-03
- **Status**: Accepted
- **Context**: User specified backtest scope
- **Decision**: Use 2021–2025 seasons for historical validation
- **Rationale**: Maximizes data for calibration while staying within NFL Fantasy era
- **Consequences**: Requires data ingestion for 5 seasons; more compute for backtests

### D009 — API Strategy: FantasyPros Primary, Manual Fallback First-Class
- **Date**: 2025-08-03
- **Status**: Accepted
- **Context**: NFL Fantasy unofficial API may be unreliable; manual entry must work
- **Decision**: Build FantasyPros integration with manual CSV templates as equal citizens
- **Rationale**: System must operate if API dies mid-season; no single point of failure
- **Consequences**: Duplicate data entry paths; both must pass schema tests

### D010 — Telegram Bot Token Stored in Config (Env Var Expansion)
- **Date**: 2025-08-03
- **Status**: Accepted
- **Context**: User provided bot token; needs secure handling
- **Decision**: Store as `${TELEGRAM_BOT_TOKEN}` in config; expand from environment at runtime
- **Rationale**: Separates secrets from code; enables deployment flexibility
- **Consequences**: Deployment requires setting env vars; config file can be version-controlled safely

---

## Cut Features (Feature Creep Log)

Per Lens D (Macro Focus), features that don't measurably move P(championship) are cut:

| Feature | Reason Cut | Date |
|---------|------------|------|
| Multi-league support | Violates single-league focus | 2025-08-03 |
| Trade optimizer | Beyond passive ΔP scan (explicit non-goal) | 2025-08-03 |
| Paid data APIs | Budget = 0 constraint | 2025-08-03 |
| Cloud deployment | Local execution constraint | 2025-08-03 |
| Mobile app | Delivery via Telegram only | 2025-08-03 |
| DFS features | Season-long only focus | 2025-08-03 |
| Public-facing anything | Private tool for this league | 2025-08-03 |
| Projection heroics | Consensus anchor + calibrated quantiles sufficient | 2025-08-03 |

---

## Open Parameters (To Be Resolved)

| Parameter | Current Value | Resolution Trigger |
|-----------|---------------|-------------------|
| `draft_slot` | UNKNOWN | User learns draft position |
| `draft_date` | UNKNOWN | League announces draft date |
| `waiver_type` | rolling_priority | Week 1 in-app verification |

---

*Last updated: 2025-08-03*

## Consensus Scraper Tradeoff - 2026-08-03T22:48:30.084004+00:00

**Decision**: Test tradeoff

**Rationale**: Per architecture spec §2, we prefer falling back to fewer sources
rather than implementing fragile headless browsing. The consensus mean from 2-3
reliable sources is near-efficient; the edge lives in valuation/posture/streams/waivers,
not projection heroics.

**Impact**: May miss some niche projections, but system remains operable.

## Consensus Scraper Tradeoff - 2026-08-03T22:48:38.323837+00:00

**Decision**: Test tradeoff

**Rationale**: Per architecture spec §2, we prefer falling back to fewer sources
rather than implementing fragile headless browsing. The consensus mean from 2-3
reliable sources is near-efficient; the edge lives in valuation/posture/streams/waivers,
not projection heroics.

**Impact**: May miss some niche projections, but system remains operable.

## Consensus Scraper Tradeoff - 2026-08-03T22:49:11.204360+00:00

**Decision**: Test tradeoff

**Rationale**: Per architecture spec §2, we prefer falling back to fewer sources
rather than implementing fragile headless browsing. The consensus mean from 2-3
reliable sources is near-efficient; the edge lives in valuation/posture/streams/waivers,
not projection heroics.

**Impact**: May miss some niche projections, but system remains operable.

## Consensus Scraper Tradeoff - 2026-08-03T22:49:27.707632+00:00

**Decision**: Test tradeoff

**Rationale**: Per architecture spec §2, we prefer falling back to fewer sources
rather than implementing fragile headless browsing. The consensus mean from 2-3
reliable sources is near-efficient; the edge lives in valuation/posture/streams/waivers,
not projection heroics.

**Impact**: May miss some niche projections, but system remains operable.
