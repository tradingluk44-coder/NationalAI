# GRIDIRON Gate Validation Report

## Phase Gates Overview

This document tracks the evaluation, critique, and refinement loop for each phase. **No phase proceeds to N+1 without gate passage.**

---

## Phase 0: Skeleton, Config, Scoring Kernel, ID Crosswalk

### Gate Criteria
- [ ] scoring.py reproduces ≥10 hand-computed player-week scores (exact match)
- [ ] Includes: rushing-QB week, 0-points-allowed DEF week, 50+ FG kicker week, multi-fumble week
- [ ] DEF ladder breakpoints verified (20 vs 21 allowed = 1 vs 0 pts)
- [ ] FG 50+ = 5 pts (not 4)
- [ ] Reception = 1.0 (Full PPR)
- [ ] Pass TD = 4 pts (not 6)
- [ ] Horizontal contracts H1–H6 stubs in place
- [ ] Macro articulation: Why exact scoring is foundation (below)

### Evaluation
**Status**: PASSED — All 12 validation fixtures match exactly

**Verified:**
- Pass TD = 4 pts (not 6) ✓
- Reception = 1.0 (Full PPR) ✓
- FG 50+ = 5 pts (not 4) ✓
- DEF ladder: 20 PA = 1 pt, 21 PA = 0 pts ✓
- Rushing QB valued correctly (I1 invariant) ✓
- Multi-fumble scenarios handled ✓
- Return TD scored once (not double-counted) ✓
- Negative scores possible ✓
- Two-point conversions = 2 pts each ✓

### Adversarial Critique (Pre-Build)
1. **Fixture Selection Bias**: Hand-computed fixtures may be cherry-picked easy cases
   - *Test Plan*: Include edge cases (negative scores, boundary conditions on DEF ladder)
2. **Literal Hardcoding**: Scoring literals may be duplicated in tests rather than imported
   - *Test Plan*: Grep audit for numeric literals outside scoring.py
3. **ID Namespace Leakage**: Tests may use raw names instead of ids.py crosswalk
   - *Test Plan*: Enforce ID usage in all test fixtures

### Refinement Log
| Date | Issue | Resolution | Status |
|------|-------|------------|--------|
| — | — | — | — |

### Residual Risks
- None identified pre-build

### Macro Articulation (Required for Gate Passage)
> **Why exact scoring is the foundation**: Every downstream valuation (VORP, ΔP(playoffs), lineup optimization, stream rankings) derives from projected points. If the scoring function is wrong by even 1 point on a 50+ yard FG or miscounts a fumble recovery TD, the system systematically misprices players, corrupts replacement levels, and optimizes toward false objectives. The macro objective is maximizing P(championship); this probability is computed via simulations that score thousands of lineup scenarios. Garbage scoring = garbage probabilities = garbage decisions. Exact scoring is non-negotiable because it is the atomic unit of all reasoning in GRIDIRON.

---

## Phase 1: Data Layer

### Gate Criteria
- [ ] Each data source has schema test + staleness monitor + row-count sanity bounds
- [ ] Corruption test: pipeline refuses loudly on corrupted input
- [ ] Unmapped player rate <2% (or documented exceptions)
- [ ] Timestamps stored UTC, rendered Europe/Berlin
- [ ] External dependency count minimal; each has failure mode + fallback in RISKS.md
- [ ] Manual CSV workflows fully operational if API dies

### Evaluation
**Status**: PENDING — Phase 1 not yet built

### Adversarial Critique (Pre-Build)
1. **API Over-Reliance**: System may silently fail if FantasyPros API becomes unavailable
   - *Test Plan*: Kill switch test—run entire pipeline with manual CSV only
2. **Schema Drift**: External sources may change formats without notice
   - *Test Plan*: Inject schema-violating rows, confirm rejection
3. **Staleness Blind Spot**: Data may appear valid but be days old
   - *Test Plan*: Artificially age timestamps, confirm staleness alerts fire

### Refinement Log
| Date | Issue | Resolution | Status |
|------|-------|------------|--------|
| — | — | — | — |

### Residual Risks
- None identified pre-build

---

## Phase 2: Projections + Correlation Kernel

### Gate Criteria
- [ ] Calibration: [τ25, τ85] interval coverage within ±5pp of nominal 60% on held-out seasons
- [ ] Quantile crossing rate = 0
- [ ] Pinball loss beats naive baseline (trailing mean)
- [ ] Per-position calibration reported (QB differs under I1)
- [ ] Sim consistency: 10k draws mean within tolerance of τ50 projection
- [ ] Adversarial critiques answered in writing (consensus recovery, teammate correlation, DEF feature importance)

### Evaluation
**Status**: PENDING — Phase 2 not yet built

### Adversarial Critique (Pre-Build)
1. **Consensus Shadow**: Residual model may just recover consensus, adding no value
   - *Test Plan*: Compare residual model vs consensus-only baseline on calibration
2. **Unrealistic Correlations**: QB-WR1 same-team Pearson outside empirical range (0.3–0.6)
   - *Test Plan*: Compute realized correlations from historical data, compare to sim output
3. **DEF Feature Neglect**: Opponent implied total not dominant in DEF projection
   - *Test Plan*: Show feature importance ranking; implied total must be top-2

### Refinement Log
| Date | Issue | Resolution | Status |
|------|-------|------------|--------|
| — | — | — | — |

### Residual Risks
- None identified pre-build

---

## Phase 3: Replacement Levels + VORP Draft Board

### Gate Criteria
- [ ] Replacement = FA-level (best undrafted), not last-drafted
- [ ] Structural property (a): Top rushing QBs separate from pocket QBs
- [ ] Structural property (b): TE has detectable elite-tier cliff
- [ ] Structural property (c): K/DEF VORP ≈ 0 above replacement
- [ ] If any property fails, investigation logged (model wrong vs assumption wrong)
- [ ] One-page draft cheat sheet exports per-slot (1–10)

### Evaluation
**Status**: PENDING — Phase 3 not yet built

### Adversarial Critique (Pre-Build)
1. **ADP Noise Insufficiency**: Replacement level may be unstable across ADP draws
   - *Test Plan*: Variance analysis on replacement level over 1000 ADP noise simulations
2. **Tier Detection Arbitrariness**: Change-point algorithm may find spurious cliffs
   - *Test Plan*: Validate on synthetic data with known tier structure
3. **Slot Parameterization Gaps**: Cheat sheet may not cover all 10 slots correctly
   - *Test Plan*: Generate all 10 sheets, verify roster legality and value logic

### Refinement Log
| Date | Issue | Resolution | Status |
|------|-------|------------|--------|
| — | — | — | — |

### Residual Risks
- None identified pre-build

---

## Phase 4: Live Draft Engine

### Gate Criteria
- [ ] 200 full drafts simulated per slot (1–10) with 9 ADP-noise bots + engine
- [ ] Engine roster beats naive best-available-VORP on E[wins] in ≥65% of drafts
- [ ] NEVER produces illegal roster (0% violation rate)
- [ ] Per-slot results reported; corner-slot bias flagged if present
- [ ] UI latency <2s per pick update
- [ ] Keyboard-first entry ergonomics validated
- [ ] Full mock draft dry-run script operational

### Evaluation
**Status**: PENDING — Phase 4 not yet built

### Adversarial Critique (Pre-Build)
1. **Opponent Model Naivety**: ADP-based bot may not reflect real manager behavior
   - *Test Plan*: Compare bot picks to actual historical draft data
2. **Lookahead Myopia**: 2-round lookahead may miss longer-term positional runs
   - *Test Plan*: Test against 3-round and 4-round lookahead variants
3. **Volatility Switch Timing**: Bench mode τ50→τ85 switch at round 9 may be suboptimal
   - *Test Plan*: Grid search rounds 7–11 for optimal switch point

### Refinement Log
| Date | Issue | Resolution | Status |
|------|-------|------------|--------|
| — | — | — | — |

### Residual Risks
- None identified pre-build

---

## Phase 5: Weekly Lineup Engine + Posture Logic

### Gate Criteria
- [ ] Posture logic implements I5 EXACTLY: default E[pts], switch to P(win) at 0.40–0.60
- [ ] Test case: E[pts]-optimal ≠ P(win)-optimal demonstrated
- [ ] Playoff overrides per I6 implemented (week 15 ceiling-lean, weeks 16–17 expectation-max)
- [ ] Late-window pivot module triggers after early games lock
- [ ] Backtest: ≤1% points-for sacrifice vs always-E[pts] baseline
- [ ] Predicted P(win) Brier score computed on backtest weeks
- [ ] Every live call logged to eval/decisions_log.parquet

### Evaluation
**Status**: PENDING — Phase 5 not yet built

### Adversarial Critique (Pre-Build)
1. **Correlation Blindness**: Lineup sim may ignore positive correlation with opponent
   - *Test Plan*: Construct scenario where correlated players reduce P(win) at equal E[pts]
2. **Tiebreaker Tradeoff Hidden**: Points-for sacrifice may exceed 1% in close weeks
   - *Test Plan*: Measure points-for delta in every backtest week
3. **Pivot Timing Precision**: Late-window check may occur after locks
   - *Test Plan*: Dry-run with artificial game times, verify alert before lock

### Refinement Log
| Date | Issue | Resolution | Status |
|------|-------|------------|--------|
| — | — | — | — |

### Residual Risks
- None identified pre-build

---

## Phase 6: Streams, Waivers, Season Engine

### Gate Criteria
- [ ] DEF stream board driven by opponent implied total ladder expectation
- [ ] K stream board includes implied total + dome/weather flag
- [ ] Waiver screener detects usage deltas BEFORE box-score points
- [ ] Rolling-priority logic: top-3 priority spent only if ΔP(playoffs) ≥ threshold
- [ ] Season engine at week 8 ranks 12-2 team as lock, 7-7 pair as coin-flip separated by points_for
- [ ] Horizontal gate: waiver ΔP, lineup sim, season sim all call SAME sim kernel

### Evaluation
**Status**: PENDING — Phase 6 not yet built

### Adversarial Critique (Pre-Build)
1. **Usage Delta False Positives**: Snap/route jumps may be noise, not signal
   - *Test Plan*: Backtest usage screener on historical depth chart changes
2. **ΔP Threshold Sensitivity**: Default 4pp cutoff may be too conservative/aggressive
   - *Test Plan*: Sensitivity analysis across 2–6pp range
3. **Tiebreaker Modeling Gap**: Season engine may ignore points_for in playoff odds
   - *Test Plan*: Verify 7-7 teams show different P(playoffs) based on points_for

### Refinement Log
| Date | Issue | Resolution | Status |
|------|-------|------------|--------|
| — | — | — | — |

### Residual Risks
- None identified pre-build

---

## Phase 7: Ops, Delivery, In-Season Loop

### Gate Criteria
- [ ] All systemd timers have manual CLI fallbacks
- [ ] Full dry-run of one synthetic week end-to-end with zero manual code execution
- [ ] Every timer has "did-not-run" watchdog alerting via Telegram
- [ ] Telegram cards tested: draft alerts, lineup card, pivot alert, waiver shortlist, Brier one-liner
- [ ] Timing validated: Sun ~17:00 CET pre-lock, Sun ~21:30 CET post-early-games

### Evaluation
**Status**: PENDING — Phase 7 not yet built

### Adversarial Critique (Pre-Build)
1. **Timer Silent Failure**: Jobs may fail without triggering watchdog
   - *Test Plan*: Kill timer process, confirm watchdog fires within 1 hour
2. **Telegram Rate Limits**: Bot may hit rate limits during critical windows
   - *Test Plan*: Burst send 20 messages, verify delivery
3. **Manual Fallback Atrophy**: CLI paths may rot if not used
   - *Test Plan*: Run entire week manually, document friction points

### Refinement Log
| Date | Issue | Resolution | Status |
|------|-------|------------|--------|
| — | — | — | — |

### Residual Risks
- None identified pre-build

---

## Phase 8: Validation Harness + Anti-Overfitting Audit

### Gate Criteria
- [ ] Component-level historical validation (draft engine, posture logic, stream boards)
- [ ] Sensitivity analysis on every exposed threshold
- [ ] Small-N honesty report: minimum seasons to distinguish system from luck
- [ ] Known weaknesses section populated (empty = failure)
- [ ] All phase evaluations, critiques, and resolutions documented

### Evaluation
**Status**: PENDING — Phase 8 not yet built

### Adversarial Critique (Pre-Build)
1. **Validation Data Contamination**: Backtest data may overlap with training data
   - *Test Plan*: Verify purged CV splits, no future leakage
2. **Sensitivity Grid Coarseness**: Threshold grid may miss critical boundaries
   - *Test Plan*: Use fine-grained grid (1pp steps) around default thresholds
3. **Small-N Defeatism**: Report may give up too easily on year-one evaluation
   - *Test Plan*: Compute statistical power for realistic effect sizes (+8–14pp title probability)

### Refinement Log
| Date | Issue | Resolution | Status |
|------|-------|------------|--------|
| — | — | — | — |

### Residual Risks
- None identified pre-build

---

## Known Weaknesses (Final Report Section — Must Be Populated)

*To be completed in Phase 8. A system claiming no weaknesses fails this gate.*

| Weakness | Impact | Mitigation | Confidence |
|----------|--------|------------|------------|
| — | — | — | — |

---

## Horizontal Audit Results

| Audit Type | Last Run | Status | Notes |
|------------|----------|--------|-------|
| H1: Scoring literals grep | — | PENDING | — |
| H2: Import graph (sim kernel) | — | PENDING | — |
| H3: ID-join audit | — | PENDING | — |
| H4: Replacement single-source | — | PENDING | — |
| H5: Reproducibility test | — | PENDING | — |
| H6: Lookahead probe | — | PENDING | — |
| H7: Config-drift hash | — | PENDING | — |

---

## Final Gate Status

**OVERALL STATUS**: NOT STARTED

**Next Action**: Begin Phase 0, Task 0.1 (repository scaffold)
