# GRIDIRON Risk Register

## Critical Risks (Phase 0–1)

### R1: API Authentication Failure
- **Description**: FantasyPros/NFL Fantasy API credentials expire or become invalid
- **Probability**: Medium
- **Impact**: High (blocks automated data ingestion)
- **Mitigation**: Manual CSV entry workflows as first-class citizens; test manual path weekly
- **Trigger**: Authentication errors in Phase 1 ingestion tests
- **Owner**: System

### R2: Rate Limit Exhaustion
- **Description**: FantasyPros API 50 req/day limit reached during critical periods
- **Probability**: Medium
- **Impact**: Medium (delays data updates)
- **Mitigation**: Aggressive caching, request batching, priority queue for essential calls
- **Trigger**: HTTP 429 responses logged
- **Owner**: System

### R3: Scoring Implementation Drift
- **Description**: Scoring rules implemented incorrectly despite validation fixtures
- **Probability**: Low (with gate tests)
- **Impact**: Critical (corrupts all downstream valuations)
- **Mitigation**: 10+ hand-computed fixtures, adversarial review of DEF ladder and FG breakpoints
- **Trigger**: Gate test failures in Phase 0
- **Owner**: Developer

### R4: Player ID Mapping Gaps
- **Description**: >2% of players unmappable through ids.py crosswalk
- **Probability**: Medium
- **Impact**: Medium (data loss, incorrect joins)
- **Mitigation**: Fuzzy matching fallback, manual ID resolution log
- **Trigger**: Unmapped rate exceeds threshold in Phase 1 audit
- **Owner**: System

### R5: Timezone Conversion Errors
- **Description**: UTC/Europe-Berlin conversions cause lock-time miscalculations
- **Probability**: Low
- **Impact**: High (late-window pivots fail, illegal lineup submissions)
- **Mitigation**: Explicit timezone tests, game-lock deadline alerts with margin
- **Trigger**: DST transition edge cases, Sunday morning CET tests
- **Owner**: System

## High Risks (Phase 2–4)

### R6: Projection Model Overfitting
- **Description**: LightGBM quantile residuals fit noise rather than signal
- **Probability**: Medium
- **Impact**: High (suboptimal draft/lineup decisions)
- **Mitigation**: Purged time-series CV, calibration gates, consensus anchor dominance
- **Trigger**: Out-of-sample calibration failure (>5pp from nominal coverage)
- **Owner**: Developer

### R7: Correlation Kernel Unrealism
- **Description**: Teammate correlations (QB-WR) outside empirical ranges
- **Probability**: Medium
- **Impact**: Medium (lineup sim accuracy degraded)
- **Mitigation**: Historical correlation validation, feature importance audits
- **Trigger**: Pearson correlation out of bounds in Phase 2 gate
- **Owner**: Developer

### R8: Replacement Level Misestimation
- **Description**: FA-level replacement computed incorrectly for 10-team league
- **Probability**: Medium
- **Impact**: High (VORP board fundamentally flawed)
- **Mitigation**: ADP noise simulation averaging, structural property tests (I1, I3)
- **Trigger**: TE cliff or QB compression not emerging in Phase 3
- **Owner**: System

### R9: Draft Engine Slot Bias
- **Description**: Engine only competitive from corner slots (1–2, 9–10)
- **Probability**: Medium
- **Impact**: High (fails macro objective for mid-slot users)
- **Mitigation**: 200-draft simulation per slot, positional run detection tuning
- **Trigger**: Win rate <65% vs naive in any slot during Phase 4 gate
- **Owner**: Developer

## Medium Risks (Phase 5–7)

### R10: Posture Logic Points-For Sacrifice
- **Description**: P(win) optimization sacrifices too many points_for tiebreaker points
- **Probability**: Medium
- **Impact**: Medium (loses playoff seeding in tie scenarios)
- **Mitigation**: Guard rail ≤1% points-for sacrifice, backtest on reconstructed league
- **Trigger**: Points-for loss >1% in Phase 5 backtest
- **Owner**: System

### R11: Late-Window Pivot Timing Failure
- **Description**: Sunday CET pivot alerts arrive after early games locked
- **Probability**: Low
- **Impact**: High (missed optimization window)
- **Mitigation**: Conservative timing (17:00 CET pre-lock), Telegram delivery confirmation
- **Trigger**: Alert timestamp after any game kickoff in Phase 7 dry-run
- **Owner**: System

### R12: Season Engine Tiebreaker Ignorance
- **Description**: Playoff probabilities don't account for points_for tiebreaker
- **Probability**: Low
- **Impact**: High (misleading ΔP(playoffs) valuations)
- **Mitigation**: Explicit tiebreaker modeling, 7-7 coin-flip test case
- **Trigger**: 7-7 teams show equal P(playoffs) despite points_for difference in Phase 6
- **Owner**: Developer

### R13: systemd Timer Silent Failure
- **Description**: Scheduled jobs fail without alerting
- **Probability**: Low
- **Impact**: Medium (missed waiver sweeps, stale lineups)
- **Mitigation**: Watchdog alerts via Telegram, manual CLI fallback for every job
- **Trigger**: Timer non-execution detected in Phase 7
- **Owner**: System

## Low Risks (Phase 8+)

### R14: Backtest Lookahead Bias
- **Description**: Future data leaks into historical validation
- **Probability**: Low (with H5 guard)
- **Impact**: High (false confidence in system edge)
- **Mitigation**: as_of filtering, future-dated row injection test
- **Trigger**: Gate test failure in Phase 8
- **Owner**: Developer

### R15: Threshold Overfitting
- **Description**: System edge vanishes when thresholds move ±5pp
- **Probability**: Medium
- **Impact**: High (non-robust recommendations)
- **Mitigation**: Sensitivity analysis grid, flag overfit components
- **Trigger**: Edge sensitivity >5pp in Phase 8 audit
- **Owner**: Developer

### R16: Small-N Statistical Power
- **Description**: 14-week season insufficient to distinguish skill from luck
- **Probability**: High (inherent constraint)
- **Impact**: Medium (process metrics matter more than trophy)
- **Mitigation**: Honest reporting of minimum seasons needed, focus on Brier/calibration
- **Trigger**: Phase 8 small-N report
- **Owner**: Developer

---

## Risk Mitigation Status

| Risk ID | Phase Detected | Mitigation Implemented | Status |
|---------|---------------|----------------------|--------|
| R1 | Phase 1 | Manual CSV templates created | Open |
| R2 | Phase 1 | Request caching + budget logging | Open |
| R3 | Phase 0 | 10+ hand-computed fixtures | Pending |
| R4 | Phase 1 | ID mapping rate monitoring | Pending |
| R5 | Phase 0 | Timezone validation tests | Pending |

---

## Assumptions Log

| ID | Assumption | Verification Step | Phase | Status |
|----|------------|------------------|-------|--------|
| A1 | FantasyPros API accessible long-term | Weekly connectivity test | Phase 1 | Open |
| A2 | 50 req/day sufficient for workflow | Request count monitoring | Phase 1 | Open |
| A3 | No complex JS rendering required | Scrape test in Phase 1 | Phase 1 | Open |
| A4 | Rolling waivers default | Week 1 in-app verification | Phase 1 | Open |
| A5 | Telegram rate limits adequate | Notification stress test | Phase 7 | Open |
| A6 | DuckDB handles simulation load | Performance profiling | Phase 2 | Open |
| A7 | nflreadpy API stable | Version monitoring | Phase 1 | Open |
| A8 | Local resources adequate for 10k sims | Memory/CPU profiling | Phase 2 | Open |
| A9 | Session auth persists | Auth persistence test | Phase 1 | Open |
| A10 | 2021–2025 data available | Data availability check | Phase 8 | Open |
| A11 | Europe/Berlin compatible with US sports | Weekend workflow test | Phase 7 | Open |
| A12 | systemd available on target OS | OS compatibility check | Phase 7 | Open |
| A13 | No firewall restrictions | Network connectivity test | Phase 1 | Open |
| A14 | DuckDB concurrency safe | Concurrency testing | Phase 7 | Open |
| A15 | DuckDB backup adequate | Backup/restore test | Phase 7 | Open |
| A16 | Telegram delivery reliable | End-to-end test | Phase 7 | Open |
| A17 | Projection format stable | Format validation | Phase 1 | Open |
| A18 | Odds markets sufficient | Feature availability test | Phase 2 | Open |
| A19 | Player IDs stable | ID consistency monitoring | Phase 1 | Open |
| A20 | Storage adequate | Storage estimation | Phase 1 | Open |
| A21 | Python 3.11+ typing sufficient | Type checking throughout | Phase 0 | Open |
| A22 | Polars performance adequate | Performance testing | Phase 1 | Open |
| A23 | Auth doesn't require frequent refresh | Auth persistence test | Phase 1 | Open |
| A24 | DuckDB SQL operations sufficient | Query complexity test | Phase 1 | Open |
| A25 | Dependencies backward compatible | Version locking | Phase 0 | Open |
