# GRIDIRON Risk Register

This file tracks all identified risks, their severity, mitigation strategies, and ownership.

## Risk Format

Each entry follows this format:
- **ID**: Unique identifier (R001, R002, etc.)
- **Category**: Data | API | Model | Ops | Security | Other
- **Severity**: Low | Medium | High | Critical
- **Likelihood**: Rare | Unlikely | Possible | Likely | Almost Certain
- **Status**: Open | Mitigated | Accepted | Transferred
- **Description**: What could go wrong
- **Impact**: Consequences if risk materializes
- **Mitigation**: Steps to reduce likelihood or impact
- **Trigger**: Event that would activate the risk
- **Owner**: Who monitors this risk

---

## Active Risks

### R001 — NFL Fantasy Unofficial API Unreliable
- **Category**: API
- **Severity**: High
- **Likelihood**: Possible
- **Status**: Mitigated
- **Description**: `api.fantasy.nfl.com` unofficial endpoints may change, require auth refresh, or become unavailable
- **Impact**: Cannot auto-fetch rosters, standings, waiver order
- **Mitigation**: 
  - Manual CSV entry templates built as first-class citizens (D009)
  - System fully operable with manual data entry
  - Week-1 auth test to verify endpoint status
- **Trigger**: API returns 401/403/500 errors consistently
- **Owner**: User (verify week 1)

### R002 — FantasyPros API Rate Limit Changes
- **Category**: API
- **Severity**: Medium
- **Likelihood**: Unlikely
- **Status**: Open
- **Description**: Free tier may reduce from 50 req/day or require authentication changes
- **Impact**: Projection scraping constrained; may need fallback sources
- **Mitigation**: 
  - Budget enforcement in code (assert ≤50/day)
  - Multiple projection sources aggregated (degrade gracefully)
  - Cache responses aggressively
- **Trigger**: API returns 429 rate limit errors
- **Owner**: System (rate limiter enforces)

### R003 — TheOdds API Budget Exhaustion
- **Category**: API
- **Severity**: Medium
- **Likelihood**: Unlikely
- **Status**: Open
- **Description**: 500 req/month budget exceeded before season end
- **Impact**: Cannot pull implied totals for DEF stream, correlation model
- **Mitigation**: 
  - Hard-coded limit: ≤2 pulls/week (config: `odds_pulls_per_week: 2`)
  - Cache odds for 3+ days
  - Fallback to consensus implied totals if available elsewhere
- **Trigger**: API returns quota exceeded error
- **Owner**: System (rate limiter enforces)

### R004 — Telegram Bot Token Compromise
- **Category**: Security
- **Severity**: High
- **Likelihood**: Rare
- **Status**: Mitigated
- **Description**: Bot token leaked via version control or log exposure
- **Impact**: Unauthorized access to send messages as bot; potential spam
- **Mitigation**: 
  - Token stored as env var expansion `${TELEGRAM_BOT_TOKEN}` (D010)
  - Config file can be version-controlled safely
  - Token can be revoked/regenerated via @BotFather
- **Trigger**: Token appears in public repo or logs
- **Owner**: User (protect env vars)

### R005 — Player ID Mapping Failures (>2% unmapped)
- **Category**: Data
- **Severity**: Medium
- **Likelihood**: Possible
- **Status**: Open
- **Description**: New players, name variations, or ID changes cause unmapped rate >2%
- **Impact**: Data joins fail; projections missing for affected players
- **Mitigation**: 
  - `core/ids.py` tracks unmapped names
  - Phase 1 gate requires <2% unmapped or documented exceptions
  - Manual ID resolution workflow for edge cases
- **Trigger**: Unmapped rate exceeds threshold in staleness report
- **Owner**: System (validation tests flag)

### R006 — DuckDB Corruption Under Concurrent Access
- **Category**: Data
- **Severity**: High
- **Likelihood**: Unlikely
- **Status**: Open
- **Description**: Multiple processes writing to warehouse.duckdb simultaneously
- **Impact**: Data corruption; lost writes; inconsistent state
- **Mitigation**: 
  - Append-only design reduces conflict surface
  - systemd timers serialized (no overlapping schedules)
  - Manual CLI includes file-lock checks
  - Regular backup snapshots to parquet/
- **Trigger**: Database lock errors or integrity check failures
- **Owner**: System (timer serialization)

### R007 — Model Calibration Drift Mid-Season
- **Category**: Model
- **Severity**: Medium
- **Likelihood**: Possible
- **Status**: Open
- **Description**: Quantile calibration degrades as season progresses (injuries, role changes)
- **Impact**: P(win) estimates inaccurate; posture logic makes wrong calls
- **Mitigation**: 
  - Weekly Brier score tracking (Phase 7 ops)
  - Purged time-series CV in training (no shuffled K-fold)
  - Consensus anchor provides baseline; residual model adds marginal value
- **Trigger**: Brier score exceeds threshold in weekly report
- **Owner**: System (calibration monitor)

### R008 — Overfitting to Historical Data
- **Category**: Model
- **Severity**: High
- **Likelihood**: Possible
- **Status**: Open
- **Description**: Thresholds (posture band, waiver priority cutoff) optimized for past seasons
- **Impact**: System underperforms in out-of-sample season
- **Mitigation**: 
  - Sensitivity analysis on all thresholds (Phase 8)
  - Small-N honesty report: compute minimum seasons to distinguish from luck
  - Process metrics (Brier, calibration) prioritized over trophy
- **Trigger**: Sensitivity analysis shows edge vanishes with ±5% threshold change
- **Owner**: System (anti-overfitting audit)

### R009 — Late-Window Pivot Timing Miss
- **Category**: Ops
- **Severity**: Medium
- **Likelihood**: Possible
- **Status**: Open
- **Description**: Sunday 21:30 CET pivot check misses locked players or score differential
- **Impact**: Missed opportunity to optimize unlocked slots
- **Mitigation**: 
  - Per-game lock tracking in `data/ingest/manual_entry.py`
  - Explicit game-time validation before pivot recommendation
  - Telegram alert includes lock status confirmation
- **Trigger**: Pivot recommended for already-locked player
- **Owner**: User (confirm before executing)

### R010 — systemd Timer Silent Failure
- **Category**: Ops
- **Severity**: High
- **Likelihood**: Unlikely
- **Status**: Mitigated
- **Description**: Timer job fails without notification; user assumes system running
- **Impact**: Missing waiver boards, lineup cards, data refreshes
- **Mitigation**: 
  - Watchdog service alerts via Telegram if timer didn't run (Phase 7)
  - Manual CLI fallback for every automated job
  - "Did-not-run" detection with independent schedule
- **Trigger**: Timer execution log gap > expected interval
- **Owner**: System (watchdog monitors)

### R011 — League Rule Changes Mid-Season
- **Category**: Data
- **Severity**: Critical
- **Likelihood**: Rare
- **Status**: Accepted
- **Description**: Commissioner modifies scoring, roster, or playoff rules after draft
- **Impact**: All valuations based on incorrect rules; system produces illegal recommendations
- **Mitigation**: 
  - `league_config.yaml` is single source of truth; easy to update
  - Config hash tracked; mismatch triggers warning
  - Horizontal audit (H6) detects hardcoded rule drift
- **Trigger**: User reports rule discrepancy
- **Owner**: User (verify config matches league settings)

### R012 — Insufficient Backtest Data for Calibration
- **Category**: Model
- **Severity**: Medium
- **Likelihood**: Possible
- **Status**: Open
- **Description**: 5 seasons (2021–2025) insufficient for robust calibration at position granularity
- **Impact**: Quantile coverage outside ±5pp tolerance; unreliable P(win) estimates
- **Mitigation**: 
  - Report per-position calibration separately (QB differs from DEF)
  - Honest uncertainty: print confidence intervals on all probabilities
  - Season-one scoreboard = PROCESS metrics, not trophy
- **Trigger**: Calibration report shows coverage outside tolerance
- **Owner**: System (calibration module reports)

---

## Mitigated Risks (Closed)

| ID | Description | Mitigation Date | Status |
|----|-------------|-----------------|--------|
| R004 | Telegram token compromise | Env var storage (D010) | Mitigated |
| R010 | systemd silent failure | Watchdog service | Mitigated |

---

## Accepted Risks (No Further Mitigation)

| ID | Description | Rationale |
|----|-------------|-----------|
| R011 | League rule changes | Rare event; easy config update suffices |

---

## Risk Monitoring Schedule

| Frequency | Activity | Owner |
|-----------|----------|-------|
| Weekly | Brier score + calibration report | System (auto) |
| Weekly | API quota usage review | System (auto-alert) |
| Week 1 | Verify NFL Fantasy API access | User |
| Week 1 | Confirm waiver type (rolling vs FAAB) | User |
| Monthly | DuckDB integrity check | System (auto) |
| Phase 8 | Sensitivity analysis on all thresholds | System (auto) |

---

*Last updated: 2025-08-03*
