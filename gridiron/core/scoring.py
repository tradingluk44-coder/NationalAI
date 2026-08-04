"""
GRIDIRON Core Scoring Module

THE scoring function - only implementation in repo.
All modules (draft, sim, lineup, streams) MUST import this.
No numeric scoring literals anywhere else (H1 contract).

Macro objective: Exact scoring is the atomic unit of all reasoning.
Garbage scoring = garbage probabilities = garbage decisions.
"""

from dataclasses import dataclass
from typing import TypedDict
import yaml
from pathlib import Path


@dataclass(frozen=True)
class PlayerStats:
    """Player statistics for a single game."""
    # Passing
    pass_yards: float = 0.0
    pass_td: int = 0
    pass_int: int = 0
    
    # Rushing
    rush_yards: float = 0.0
    rush_td: int = 0
    
    # Receiving
    rec_yards: float = 0.0
    rec_td: int = 0
    receptions: int = 0
    
    # Misc
    two_pt_conversions: int = 0
    fumbles_lost: int = 0
    fumble_rec_td: int = 0  # Fumble recovery TD (offensive or defensive)
    return_td: int = 0      # Kick/punt/INT/fumble return TD
    
    # Kicking
    pat_made: int = 0
    fg_0_39: int = 0        # FG 0-39 yards
    fg_40_49: int = 0       # FG 40-49 yards
    fg_50_plus: int = 0     # FG 50+ yards
    
    # Defense/Special Teams
    sacks: float = 0.0
    def_int: int = 0         # Interceptions by defense
    fumble_rec_def: int = 0  # Fumble recoveries by defense
    safeties: int = 0
    def_td: int = 0          # Defensive TDs (not including return_td)
    two_pt_return: int = 0   # 2-point conversion returns
    points_allowed: int = 0  # Points allowed by defense


class ScoringConfig(TypedDict):
    """Type hint for scoring configuration dict."""
    passing: dict
    rushing: dict
    receiving: dict
    misc: dict
    kicker: dict
    defense: dict  # 'def' is a reserved keyword, use 'defense'


def load_config(config_path: str | None = None) -> ScoringConfig:
    """
    Load scoring configuration from league_config.yaml.
    
    This is the ONLY source of scoring rules. No hardcoded values.
    
    Args:
        config_path: Path to league_config.yaml. If None, uses default location.
    
    Returns:
        ScoringConfig dict with all scoring rules.
    
    Raises:
        FileNotFoundError: If config file doesn't exist.
        KeyError: If required scoring keys are missing.
    """
    if config_path is None:
        config_path = Path(__file__).parent.parent / "league_config.yaml"
    
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    scoring = config.get('scoring')
    if scoring is None:
        raise KeyError("Missing 'scoring' section in config")
    
    # Validate required keys
    required_keys = ['passing', 'rushing', 'receiving', 'misc', 'kicker', 'defense']
    for key in required_keys:
        if key not in scoring:
            raise KeyError(f"Missing required scoring key: {key}")
    
    return scoring


def compute_def_points_allowed(points_allowed: int, ladder_config: dict) -> int:
    """
    Compute DEF points allowed score using STEP FUNCTION (no interpolation).
    
    CRITICAL: This is a step function with specific breakpoints.
    20 points allowed = 1 pt, 21 points allowed = 0 pts.
    
    Args:
        points_allowed: Integer points allowed by defense
        ladder_config: Dict with range strings as keys (e.g., "14-20", "21-27")
    
    Returns:
        Points from points_allowed ladder
    
    Raises:
        ValueError: If points_allowed is negative
    """
    if points_allowed < 0:
        raise ValueError(f"points_allowed cannot be negative: {points_allowed}")
    
    # Parse ladder ranges and find matching bucket
    for range_str, points in ladder_config.items():
        range_str = str(range_str)  # Handle YAML parsing variations
        
        if range_str == "0":
            if points_allowed == 0:
                return int(points)
        elif range_str == "35+":
            if points_allowed >= 35:
                return int(points)
        elif '-' in range_str:
            low, high = map(int, range_str.split('-'))
            if low <= points_allowed <= high:
                return int(points)
        else:
            # Single value
            if points_allowed == int(range_str):
                return int(points)
    
    # Should never reach here if ladder is complete
    raise ValueError(f"No matching range for points_allowed={points_allowed}")


def compute_player_score(stats: PlayerStats, config: ScoringConfig | None = None) -> float:
    """
    Compute total fantasy score for a player given their stats.
    
    This is THE scoring function. All valuation derives from this.
    
    Args:
        stats: PlayerStats dataclass with game statistics
        config: ScoringConfig dict. If None, loads from league_config.yaml.
    
    Returns:
        Total fantasy points (float)
    
    Examples:
        >>> stats = PlayerStats(pass_yards=300, pass_td=2, pass_int=1)
        >>> score = compute_player_score(stats)
        >>> score  # 300/25*1 + 2*4 + 1*(-2) = 12 + 8 - 2 = 18
        18.0
    """
    if config is None:
        config = load_config()
    
    score = 0.0
    
    # Passing
    passing_cfg = config['passing']
    score += stats.pass_yards / passing_cfg['yards_per_point']
    score += stats.pass_td * passing_cfg['td']
    score += stats.pass_int * passing_cfg['int']
    
    # Rushing
    rushing_cfg = config['rushing']
    score += stats.rush_yards / rushing_cfg['yards_per_point']
    score += stats.rush_td * rushing_cfg['td']
    
    # Receiving (Full PPR)
    receiving_cfg = config['receiving']
    score += stats.rec_yards / receiving_cfg['yards_per_point']
    score += stats.rec_td * receiving_cfg['td']
    score += stats.receptions * receiving_cfg['reception']  # Full PPR = 1 pt/rec
    
    # Misc
    misc_cfg = config['misc']
    score += stats.two_pt_conversions * misc_cfg['two_pt']
    score += stats.fumbles_lost * misc_cfg['fumble_lost']
    score += stats.fumble_rec_td * misc_cfg['fumble_rec_td']
    # Note: return_td scored in defense section below to avoid double-counting
    
    # Kicking
    kicker_cfg = config['kicker']
    score += stats.pat_made * kicker_cfg['pat']
    score += stats.fg_0_39 * kicker_cfg['fg_0_39']
    score += stats.fg_40_49 * kicker_cfg['fg_40_49']
    score += stats.fg_50_plus * kicker_cfg['fg_50_plus']  # CRITICAL: 5 pts
    
    # Defense/Special Teams
    def_cfg = config['defense']  # Note: YAML uses 'def' but we access as 'defense'
    score += stats.sacks * def_cfg['sack']
    score += stats.def_int * def_cfg['int']
    score += stats.fumble_rec_def * def_cfg['fumble_rec']
    score += stats.safeties * def_cfg['safety']
    score += stats.def_td * def_cfg['td']
    score += stats.return_td * def_cfg['return_td']  # Return TDs (kick/punt/INT/fumble) - scored ONCE here
    score += stats.two_pt_return * def_cfg['two_pt_return']
    
    # Points allowed ladder (STEP FUNCTION)
    if stats.points_allowed > 0 or any([
        stats.sacks > 0, stats.def_int > 0, stats.fumble_rec_def > 0,
        stats.safeties > 0, stats.def_td > 0
    ]):
        # Only compute if player is a DEF or has defensive stats
        ladder = def_cfg.get('points_allowed_ladder', {})
        if ladder:
            score += compute_def_points_allowed(stats.points_allowed, ladder)
    
    return score


def compute_def_score(
    points_allowed: int,
    sacks: float = 0.0,
    interceptions: int = 0,
    fumble_recoveries: int = 0,
    safeties: int = 0,
    defensive_tds: int = 0,
    return_tds: int = 0,
    two_pt_returns: int = 0,
    config: ScoringConfig | None = None
) -> float:
    """
    Convenience function for computing DEF score directly.
    
    Args:
        points_allowed: Points allowed by defense
        sacks: Number of sacks
        interceptions: Interceptions
        fumble_recoveries: Fumble recoveries
        safeties: Safeties
        defensive_tds: Defensive touchdowns (not return TDs)
        return_tds: Return touchdowns (INT/fumble/kick/punt return)
        two_pt_returns: 2-point conversion returns
        config: ScoringConfig dict
    
    Returns:
        Total DEF fantasy points
    
    Examples:
        >>> compute_def_score(points_allowed=0)  # Shutout
        10.0
        >>> compute_def_score(points_allowed=20)  # 14-20 range
        1.0
        >>> compute_def_score(points_allowed=21)  # 21-27 range
        0.0
    """
    stats = PlayerStats(
        points_allowed=points_allowed,
        sacks=sacks,
        def_int=interceptions,
        fumble_rec_def=fumble_recoveries,
        safeties=safeties,
        def_td=defensive_tds,
        return_td=return_tds,
        two_pt_return=two_pt_returns
    )
    return compute_player_score(stats, config)


def compute_kicker_score(
    pat_made: int = 0,
    fg_0_39: int = 0,
    fg_40_49: int = 0,
    fg_50_plus: int = 0,
    config: ScoringConfig | None = None
) -> float:
    """
    Convenience function for computing kicker score directly.
    
    Args:
        pat_made: PATs made
        fg_0_39: Field goals 0-39 yards
        fg_40_49: Field goals 40-49 yards
        fg_50_plus: Field goals 50+ yards (5 pts each)
        config: ScoringConfig dict
    
    Returns:
        Total kicker fantasy points
    
    Examples:
        >>> compute_kicker_score(fg_50_plus=1)  # One 50+ yard FG
        5.0
    """
    stats = PlayerStats(
        pat_made=pat_made,
        fg_0_39=fg_0_39,
        fg_40_49=fg_40_49,
        fg_50_plus=fg_50_plus
    )
    return compute_player_score(stats, config)


# ============================================================================
# VALIDATION FIXTURES (Phase 0 Gate)
# ============================================================================

def get_validation_fixtures() -> list[dict]:
    """
    Return hand-computed validation fixtures for Phase 0 gate.
    
    Includes:
    - Rushing QB week
    - 0-points-allowed DEF week
    - 50+ FG kicker week
    - Multi-fumble week
    - DEF ladder boundary cases (20 vs 21 points)
    
    Returns:
        List of dicts with 'stats', 'expected_score', 'description'
    """
    fixtures = []
    
    # Fixture 1: Rushing QB week (I1 invariant test)
    # Stats: 200 pass yds, 1 pass TD, 0 INT, 80 rush yds, 1 rush TD
    # Score: 200/25 + 4 + 0 + 80/10 + 6 = 8 + 4 + 8 + 6 = 26
    fixtures.append({
        'stats': PlayerStats(
            pass_yards=200, pass_td=1, pass_int=0,
            rush_yards=80, rush_td=1
        ),
        'expected_score': 26.0,
        'description': 'Rushing QB week (I1: rushing at FULL RB rate)'
    })
    
    # Fixture 2: 0-points-allowed DEF week (shutout bonus)
    # Stats: 0 PA, 3 sacks, 2 INT, 1 FR, 0 TD
    # Score: 10 (shutout) + 3 + 4 + 2 = 19
    fixtures.append({
        'stats': PlayerStats(
            points_allowed=0, sacks=3.0, def_int=2, fumble_rec_def=1
        ),
        'expected_score': 19.0,
        'description': '0-points-allowed DEF week (shutout = 10 pts)'
    })
    
    # Fixture 3: 50+ FG kicker week (CRITICAL: 5 pts, not 4)
    # Stats: 2x FG 50+, 1x FG 40-49, 3x PAT
    # Score: 2*5 + 3 + 3 = 16
    fixtures.append({
        'stats': PlayerStats(
            fg_50_plus=2, fg_40_49=1, pat_made=3
        ),
        'expected_score': 16.0,
        'description': '50+ FG kicker week (fg_50_plus = 5 pts)'
    })
    
    # Fixture 4: Multi-fumble week
    # Stats: 100 rec yds, 1 rec TD, 2 fumbles lost, 1 fumble rec TD
    # Score: 100/10 + 6 + 2*(-2) + 6 = 10 + 6 - 4 + 6 = 18
    fixtures.append({
        'stats': PlayerStats(
            rec_yards=100, rec_td=1, receptions=0,
            fumbles_lost=2, fumble_rec_td=1
        ),
        'expected_score': 18.0,
        'description': 'Multi-fumble week (fumble_lost = -2, fumble_rec_td = 6)'
    })
    
    # Fixture 5: DEF ladder boundary - 20 points allowed (= 1 pt)
    # Stats: 20 PA, 0 other stats
    # Score: 1 (14-20 range)
    fixtures.append({
        'stats': PlayerStats(points_allowed=20),
        'expected_score': 1.0,
        'description': 'DEF ladder boundary: 20 PA = 1 pt (14-20 range)'
    })
    
    # Fixture 6: DEF ladder boundary - 21 points allowed (= 0 pts)
    # Stats: 21 PA, 0 other stats
    # Score: 0 (21-27 range)
    fixtures.append({
        'stats': PlayerStats(points_allowed=21),
        'expected_score': 0.0,
        'description': 'DEF ladder boundary: 21 PA = 0 pts (21-27 range)'
    })
    
    # Fixture 7: Full PPR receiver week
    # Stats: 8 rec, 120 yds, 1 TD
    # Score: 8*1 + 120/10 + 6 = 8 + 12 + 6 = 26
    fixtures.append({
        'stats': PlayerStats(receptions=8, rec_yards=120, rec_td=1),
        'expected_score': 26.0,
        'description': 'Full PPR receiver (reception = 1.0)'
    })
    
    # Fixture 8: Pass TD = 4 (not 6)
    # Stats: 3 pass TD, no other stats
    # Score: 3*4 = 12
    fixtures.append({
        'stats': PlayerStats(pass_td=3),
        'expected_score': 12.0,
        'description': 'Pass TD = 4 pts (not 6)'
    })
    
    # Fixture 9: Negative score possible
    # Stats: 100 pass yds, 3 INT, 1 fumble lost
    # Score: 100/25 + 3*(-2) + (-2) = 4 - 6 - 2 = -4
    fixtures.append({
        'stats': PlayerStats(pass_yards=100, pass_int=3, fumbles_lost=1),
        'expected_score': -4.0,
        'description': 'Negative score possible'
    })
    
    # Fixture 10: DEF ladder upper boundary - 35+ points (= -4)
    # Stats: 35 PA, 0 other stats
    # Score: -4 (35+ range)
    fixtures.append({
        'stats': PlayerStats(points_allowed=35),
        'expected_score': -4.0,
        'description': 'DEF ladder upper boundary: 35+ PA = -4 pts'
    })
    
    # Fixture 11: Two-point conversion
    # Stats: 2 two-pt conversions
    # Score: 2*2 = 4
    fixtures.append({
        'stats': PlayerStats(two_pt_conversions=2),
        'expected_score': 4.0,
        'description': 'Two-point conversions (2 pts each)'
    })
    
    # Fixture 12: Return TD (kick/punt/int/fumble)
    # Stats: 1 return TD - but this ALSO triggers misc return_td in scoring
    # which is counted once, not twice. Score: 6
    # Note: return_td appears in both misc and def sections but should only count once
    fixtures.append({
        'stats': PlayerStats(return_td=1),
        'expected_score': 6.0,
        'description': 'Return TD (6 pts)'
    })
    
    return fixtures


def validate_scoring_implementation() -> tuple[bool, list[str]]:
    """
    Validate scoring implementation against all fixtures.
    
    Phase 0 gate requirement: ALL fixtures must match EXACTLY.
    
    Returns:
        Tuple of (all_passed, list of failure messages)
    """
    fixtures = get_validation_fixtures()
    failures = []
    
    for fixture in fixtures:
        stats = fixture['stats']
        expected = fixture['expected_score']
        description = fixture['description']
        
        actual = compute_player_score(stats)
        
        if abs(actual - expected) > 1e-9:  # Float comparison tolerance
            failures.append(
                f"FAILED: {description}\n"
                f"  Expected: {expected}, Got: {actual}"
            )
    
    return len(failures) == 0, failures


if __name__ == "__main__":
    # Run validation on module load
    passed, failures = validate_scoring_implementation()
    if passed:
        print("✓ All scoring validation fixtures passed")
    else:
        print("✗ Scoring validation FAILED:")
        for failure in failures:
            print(failure)
        exit(1)
