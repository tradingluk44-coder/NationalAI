# GRIDIRON Decision Log

## Architecture Decisions

### [2024-XX-XX] Initial Repository Setup
- **Decision**: Create full parameterization for draft slots 1–10
- **Rationale**: Draft slot unknown; system must work for any slot
- **Impact**: All draft outputs parameterized; cheat sheets regenerated when slot known

### [2024-XX-XX] API Strategy
- **Decision**: Use FantasyPros free API (50 req/day) as primary NFL Fantasy data source
- **Rationale**: Provided API key enables automated roster/standings ingestion
- **Fallback**: Manual CSV entry remains first-class citizen if API fails
- **Risk**: Rate limit requires careful request budgeting (logged in config)

### [2024-XX-XX] Telegram Integration
- **Decision**: Use provided bot token (xxxxxxxx)
- **Rationale**: Enables immediate notification testing in Phase 7
- **Security**: Token stored in environment variables, never committed

### [2024-XX-XX] Backtest Scope
- **Decision**: Use 2021–2025 seasons (5 seasons) for validation
- **Rationale**: Maximizes historical data while staying within recent rule environment
- **Note**: 2025 season data will be partial/incomplete; use through available weeks

### [2024-XX-XX] System Constraints
- **Decision**: Assume standard modern laptop/desktop (8GB+ RAM, multi-core CPU)
- **Rationale**: No specific constraints provided; local execution requirement
- **Optimization**: DuckDB + Polars for memory-efficient operations

---

## Cut Features (Per §6 Explicit Non-Goals)

- Multi-league support
- Trade optimizer beyond passive ΔP scan
- Paid data APIs
- Cloud deployment
- Mobile app
- DFS features
- Public-facing anything
- Projection model heroics beyond calibrated quantiles

---

## Pending Decisions

| ID | Description | Phase | Status |
|----|-------------|-------|--------|
| P1 | FAAB vs Rolling waivers confirmation | Phase 1 | Awaiting Week 1 verification |
| P2 | Final draft slot assignment | Phase 3 | Awaiting draft date |
| P3 | Opponent manager skill priors calibration | Phase 4 | Awaiting league observation |

---

## Risk Register Cross-References

See RISKS.md for detailed risk analysis linked to decisions above.
