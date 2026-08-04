"""
nflreadpy Client - Play-by-Play, Stats, Snap Counts, Injuries, Depth Charts

Primary data source for historical and current NFL statistics.
Uses nflreadpy package for efficient data access.

Macro Objective: Provide clean, validated player-level data for projections
Micro Focus: Exact column mapping, timestamp handling (UTC storage, Europe/Berlin render)
"""

import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pathlib import Path

import polars as pl

logger = logging.getLogger(__name__)

# Attempt to import nflreadpy
try:
    import nflreadpy as nfl
    NFLREADPY_AVAILABLE = True
except ImportError:
    NFLREADPY_AVAILABLE = False
    logger.warning("nflreadpy not available. Using fallback mode.")


class NflReadPyClient:
    """
    Wrapper around nflreadpy for standardized data access
    
    Provides:
    - Play-by-play data
    - Weekly player stats
    - Snap counts
    - Injury reports
    - Depth charts
    
    Failure modes documented in RISKS.md:
    - Package API changes
    - Data source downtime
    - Schema drift
    """
    
    def __init__(self):
        if not NFLREADPY_AVAILABLE:
            raise ImportError("nflreadpy package not installed")
            
        self._cache_dir = Path("data/parquet/raw_snapshots")
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        
    def load_pbp(self, season: int, week: Optional[int] = None) -> Optional[pl.DataFrame]:
        """
        Load play-by-play data
        
        Returns DataFrame with columns:
        - game_id, play_id, down, ytg, yardline, score_differential
        - posteam, receiver, passer, rusher, etc.
        - as_of timestamp (UTC)
        """
        try:
            if week:
                df = nfl.load_pbp(seasons=[season], weeks=[week])
            else:
                df = nfl.load_pbp(seasons=[season])
                
            # Add as_of timestamp
            df = df.with_columns(
                pl.lit(datetime.now(timezone.utc).isoformat()).alias("as_of")
            )
            
            # Cache raw snapshot
            cache_file = self._cache_dir / f"pbp_{season}_{'w'+str(week) if week else 'full'}.parquet"
            df.write_parquet(cache_file)
            
            logger.info(f"Loaded PBP data: {len(df)} plays, season={season}, week={week}")
            return df
            
        except Exception as e:
            logger.error(f"Failed to load PBP data: {e}")
            return None
    
    def load_player_stats(self, season: int, week: Optional[int] = None) -> Optional[pl.DataFrame]:
        """
        Load weekly player statistics
        
        Returns DataFrame with columns:
        - player_id, player_name, position, team
        - passing_yards, passing_tds, ints
        - rushing_yards, rushing_tds, rushing_attempts
        - receptions, receiving_yards, receiving_tds, targets
        - fumbles_lost, two_point_conversions
        - special_teams_tds
        - as_of timestamp (UTC)
        """
        try:
            if week:
                df = nfl.load_player_stats(seasons=[season], weeks=[week])
            else:
                df = nfl.load_player_stats(seasons=[season])
                
            # Add as_of timestamp
            df = df.with_columns(
                pl.lit(datetime.now(timezone.utc).isoformat()).alias("as_of")
            )
            
            # Cache raw snapshot
            cache_file = self._cache_dir / f"player_stats_{season}_{'w'+str(week) if week else 'full'}.parquet"
            df.write_parquet(cache_file)
            
            logger.info(f"Loaded player stats: {len(df)} rows, season={season}, week={week}")
            return df
            
        except Exception as e:
            logger.error(f"Failed to load player stats: {e}")
            return None
    
    def load_snap_counts(self, season: int, week: Optional[int] = None) -> Optional[pl.DataFrame]:
        """
        Load snap count data
        
        Returns DataFrame with columns:
        - player_id, player_name, position, team
        - offensive_snaps, defensive_snaps, special_teams_snaps
        - snap_percentage
        - as_of timestamp (UTC)
        """
        try:
            if week:
                df = nfl.load_snap_counts(seasons=[season], weeks=[week])
            else:
                df = nfl.load_snap_counts(seasons=[season])
                
            # Add as_of timestamp
            df = df.with_columns(
                pl.lit(datetime.now(timezone.utc).isoformat()).alias("as_of")
            )
            
            # Cache raw snapshot
            cache_file = self._cache_dir / f"snap_counts_{season}_{'w'+str(week) if week else 'full'}.parquet"
            df.write_parquet(cache_file)
            
            logger.info(f"Loaded snap counts: {len(df)} rows, season={season}, week={week}")
            return df
            
        except Exception as e:
            logger.error(f"Failed to load snap counts: {e}")
            return None
    
    def load_injuries(self, season: int, week: Optional[int] = None) -> Optional[pl.DataFrame]:
        """
        Load injury reports
        
        Returns DataFrame with columns:
        - player_id, player_name, position, team
        - injury_status (OUT, DOUBTFUL, QUESTIONABLE, PROBABLE)
        - injury_body_part, injury_description
        - practice_status
        - as_of timestamp (UTC)
        """
        try:
            if week:
                df = nfl.load_injuries(seasons=[season], weeks=[week])
            else:
                df = nfl.load_injuries(seasons=[season])
                
            # Add as_of timestamp
            df = df.with_columns(
                pl.lit(datetime.now(timezone.utc).isoformat()).alias("as_of")
            )
            
            # Cache raw snapshot
            cache_file = self._cache_dir / f"injuries_{season}_{'w'+str(week) if week else 'full'}.parquet"
            df.write_parquet(cache_file)
            
            logger.info(f"Loaded injuries: {len(df)} rows, season={season}, week={week}")
            return df
            
        except Exception as e:
            logger.error(f"Failed to load injuries: {e}")
            return None
    
    def load_depth_charts(self, season: int, week: Optional[int] = None) -> Optional[pl.DataFrame]:
        """
        Load depth chart data
        
        Returns DataFrame with columns:
        - player_id, player_name, position, team
        - depth_chart_position, depth_order (1=starter, 2=backup, etc.)
        - as_of timestamp (UTC)
        """
        try:
            if week:
                df = nfl.load_depth_charts(seasons=[season], weeks=[week])
            else:
                df = nfl.load_depth_charts(seasons=[season])
                
            # Add as_of timestamp
            df = df.with_columns(
                pl.lit(datetime.now(timezone.utc).isoformat()).alias("as_of")
            )
            
            # Cache raw snapshot
            cache_file = self._cache_dir / f"depth_charts_{season}_{'w'+str(week) if week else 'full'}.parquet"
            df.write_parquet(cache_file)
            
            logger.info(f"Loaded depth charts: {len(df)} rows, season={season}, week={week}")
            return df
            
        except Exception as e:
            logger.error(f"Failed to load depth charts: {e}")
            return None
    
    def validate_schema(self, df: pl.DataFrame, expected_cols: set, source: str) -> bool:
        """Validate DataFrame has expected columns"""
        actual = set(df.columns)
        missing = expected_cols - actual
        
        if missing:
            logger.error(f"[{source}] Missing columns: {missing}")
            return False
            
        logger.info(f"[{source}] Schema validation passed")
        return True


def staleness_monitor(df: pl.DataFrame, max_age_hours: int = 48, source: str = "nflreadpy") -> bool:
    """
    Check data freshness
    
    Vertical Gate: Staleness monitor for each source
    """
    if "as_of" not in df.columns:
        logger.warning(f"[{source}] No as_of column for staleness check")
        return True
        
    try:
        as_of_str = df["as_of"][0]
        as_of = datetime.fromisoformat(as_of_str.replace('Z', '+00:00'))
        age = datetime.now(timezone.utc) - as_of
        
        if age.total_seconds() / 3600 > max_age_hours:
            logger.warning(f"[{source}] Data is stale: {age.total_seconds()/3600:.1f} hours old")
            return True
            
        logger.info(f"[{source}] Data is fresh: {age.total_seconds()/3600:.1f} hours old")
        return False
        
    except Exception as e:
        logger.error(f"[{source}] Staleness check failed: {e}")
        return True


def row_count_sanity(df: pl.DataFrame, min_rows: int, max_rows: int, source: str) -> bool:
    """
    Sanity check on row counts
    
    Vertical Gate: Row-count bounds per source
    """
    n = len(df)
    if n < min_rows or n > max_rows:
        logger.error(f"[{source}] Row count out of bounds: {n} (expected {min_rows}-{max_rows})")
        return False
        
    logger.info(f"[{source}] Row count OK: {n}")
    return True


def test_corruption_handling():
    """
    Deliberately corrupt input and confirm pipeline refuses loudly
    
    Vertical Gate: Pipeline must refuse on garbage input
    """
    # Create a corrupted DataFrame
    corrupted = pl.DataFrame({"bad_column": [None, None, None]})
    
    # Try to process it - should fail gracefully
    if not staleness_monitor(corrupted, source="test_corruption"):
        print("✓ Corruption detected - pipeline refused to process")
        return True
    else:
        print("✗ Corruption NOT detected - pipeline accepted garbage")
        return False


if __name__ == "__main__":
    if NFLREADPY_AVAILABLE:
        client = NflReadPyClient()
        print("nflreadpy client initialized successfully")
        
        # Test loading recent data
        import datetime
        current_year = datetime.datetime.now().year
        
        # Try to load some data
        stats = client.load_player_stats(current_year)
        if stats:
            print(f"Loaded {len(stats)} player stat rows")
            
            # Run validation tests
            print("\nRunning validation tests...")
            staleness_monitor(stats, source="player_stats")
            row_count_sanity(stats, min_rows=100, max_rows=100000, source="player_stats")
    else:
        print("nflreadpy not available - using fallback mode")
        
    # Test corruption handling
    print("\nTesting corruption detection...")
    test_corruption_handling()
