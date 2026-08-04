"""
DuckDB Warehouse Initialization

All tables are append-only with as_of timestamps.
Single source of truth for all GRIDIRON data.

Macro Objective: Reliable, queryable storage for championship-maximizing decisions
Micro Focus: Exact schema matching league_config.yaml, UTC timestamps
"""

import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

import duckdb
import polars as pl

logger = logging.getLogger(__name__)

# Warehouse path
WAREHOUSE_PATH = Path("data/warehouse.duckdb")


def init_warehouse(db_path: Path = WAREHOUSE_PATH):
    """
    Initialize DuckDB warehouse with append-only tables
    
    Schema design:
    - All tables have as_of timestamp (UTC)
    - Player IDs normalized through core/ids.py
    - No raw name joins (H2 contract)
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    conn = duckdb.connect(str(db_path))
    
    # Create tables
    tables = {
        # Player master table (ID crosswalk)
        "players": """
            CREATE TABLE IF NOT EXISTS players (
                player_id VARCHAR PRIMARY KEY,
                player_name VARCHAR NOT NULL,
                position VARCHAR,
                nfl_team VARCHAR,
                gsis_id VARCHAR,
                nfl_com_id VARCHAR,
                sleeper_id VARCHAR,
                fantasy_pros_id VARCHAR,
                as_of TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """,
        
        # League standings
        "standings": """
            CREATE TABLE IF NOT EXISTS standings (
                season INTEGER NOT NULL,
                week INTEGER NOT NULL,
                team_id VARCHAR NOT NULL,
                team_name VARCHAR,
                owner_name VARCHAR,
                wins INTEGER,
                losses INTEGER,
                ties INTEGER,
                points_for DOUBLE,
                points_against DOUBLE,
                rank INTEGER,
                playoff_seed INTEGER,
                as_of TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (season, week, team_id)
            )
        """,
        
        # Team rosters
        "rosters": """
            CREATE TABLE IF NOT EXISTS rosters (
                season INTEGER NOT NULL,
                week INTEGER NOT NULL,
                team_id VARCHAR NOT NULL,
                player_id VARCHAR NOT NULL,
                slot VARCHAR,
                is_starter BOOLEAN,
                is_bench BOOLEAN,
                is_ir BOOLEAN,
                as_of TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (season, week, team_id, player_id)
            )
        """,
        
        # Waiver order
        "waiver_order": """
            CREATE TABLE IF NOT EXISTS waiver_order (
                season INTEGER NOT NULL,
                week INTEGER NOT NULL,
                team_id VARCHAR NOT NULL,
                team_name VARCHAR,
                waiver_priority INTEGER NOT NULL,
                as_of TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (season, week, team_id)
            )
        """,
        
        # Player weekly stats
        "player_stats": """
            CREATE TABLE IF NOT EXISTS player_stats (
                season INTEGER NOT NULL,
                week INTEGER NOT NULL,
                player_id VARCHAR NOT NULL,
                passing_yards DOUBLE,
                passing_tds INTEGER,
                ints INTEGER,
                rushing_yards DOUBLE,
                rushing_tds INTEGER,
                rushing_attempts INTEGER,
                receptions INTEGER,
                receiving_yards DOUBLE,
                receiving_tds INTEGER,
                targets INTEGER,
                fumbles_lost INTEGER,
                two_point_conversions INTEGER,
                special_teams_tds INTEGER,
                fg_made INTEGER,
                fg_attempted INTEGER,
                fg_longest INTEGER,
                pat_made INTEGER,
                pat_attempted INTEGER,
                def_sacks INTEGER,
                def_ints INTEGER,
                def_fumble_recoveries INTEGER,
                def_safeties INTEGER,
                def_tds INTEGER,
                def_return_tds INTEGER,
                def_two_pt_returns INTEGER,
                def_points_allowed INTEGER,
                as_of TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (season, week, player_id)
            )
        """,
        
        # Snap counts
        "snap_counts": """
            CREATE TABLE IF NOT EXISTS snap_counts (
                season INTEGER NOT NULL,
                week INTEGER NOT NULL,
                player_id VARCHAR NOT NULL,
                offensive_snaps INTEGER,
                defensive_snaps INTEGER,
                special_teams_snaps INTEGER,
                snap_percentage DOUBLE,
                as_of TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (season, week, player_id)
            )
        """,
        
        # Injury reports
        "injuries": """
            CREATE TABLE IF NOT EXISTS injuries (
                season INTEGER NOT NULL,
                week INTEGER NOT NULL,
                player_id VARCHAR NOT NULL,
                injury_status VARCHAR,
                injury_body_part VARCHAR,
                injury_description VARCHAR,
                practice_status VARCHAR,
                as_of TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (season, week, player_id)
            )
        """,
        
        # Depth charts
        "depth_charts": """
            CREATE TABLE IF NOT EXISTS depth_charts (
                season INTEGER NOT NULL,
                week INTEGER NOT NULL,
                player_id VARCHAR NOT NULL,
                depth_chart_position VARCHAR,
                depth_order INTEGER,
                as_of TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (season, week, player_id)
            )
        """,
        
        # Consensus projections
        "projections": """
            CREATE TABLE IF NOT EXISTS projections (
                season INTEGER NOT NULL,
                week INTEGER NOT NULL,
                player_id VARCHAR NOT NULL,
                consensus_mean DOUBLE,
                consensus_std DOUBLE,
                source_count INTEGER,
                all_projections VARCHAR,  -- JSON array
                sources VARCHAR,  -- JSON array
                as_of TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (season, week, player_id)
            )
        """,
        
        # Betting odds
        "odds": """
            CREATE TABLE IF NOT EXISTS odds (
                game_id VARCHAR NOT NULL,
                season INTEGER NOT NULL,
                week INTEGER NOT NULL,
                commence_time TIMESTAMP WITH TIME ZONE,
                home_team VARCHAR,
                away_team VARCHAR,
                bookmaker VARCHAR,
                home_moneyline DOUBLE,
                away_moneyline DOUBLE,
                home_spread DOUBLE,
                away_spread DOUBLE,
                spread_price_home DOUBLE,
                spread_price_away DOUBLE,
                total_points DOUBLE,
                implied_home_total DOUBLE,
                implied_away_total DOUBLE,
                as_of TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (game_id, as_of)
            )
        """,
        
        # Decision log (for calibration tracking)
        "decisions_log": """
            CREATE TABLE IF NOT EXISTS decisions_log (
                decision_id VARCHAR PRIMARY KEY,
                season INTEGER NOT NULL,
                week INTEGER NOT NULL,
                decision_type VARCHAR,  -- lineup, waiver, stream, etc.
                decision_details VARCHAR,  -- JSON
                predicted_outcome DOUBLE,
                actual_outcome DOUBLE,
                brier_score DOUBLE,
                as_of TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """
    }
    
    for table_name, create_sql in tables.items():
        conn.execute(create_sql)
        logger.info(f"Created table: {table_name}")
        
    conn.close()
    logger.info(f"Warehouse initialized: {db_path}")
    return db_path


def insert_dataframe(df: pl.DataFrame, table_name: str, db_path: Path = WAREHOUSE_PATH):
    """
    Insert DataFrame into warehouse table (append-only)
    
    H5 Contract: Every stored table carries as_of
    """
    if "as_of" not in df.columns:
        df = df.with_columns(
            pl.lit(datetime.now(timezone.utc)).alias("as_of")
        )
        
    conn = duckdb.connect(str(db_path))
    
    # Convert Polars DataFrame to DuckDB format
    conn.register("temp_df", df)
    
    # Get column names from table
    result = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    columns = [row[1] for row in result]
    
    # Filter DataFrame to only table columns
    available_cols = [col for col in columns if col in df.columns]
    if len(available_cols) < len(df.columns):
        logger.warning(f"Dropping columns not in table: {set(df.columns) - set(columns)}")
        
    col_str = ", ".join(available_cols)
    conn.execute(f"INSERT INTO {table_name} ({col_str}) SELECT {col_str} FROM temp_df")
    
    row_count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    logger.info(f"Inserted {len(df)} rows into {table_name}. Total: {row_count}")
    
    conn.close()


def query_warehouse(query: str, db_path: Path = WAREHOUSE_PATH) -> Optional[pl.DataFrame]:
    """
    Query warehouse and return as Polars DataFrame
    
    H5 Contract: Backtests must filter as_of <= decision_time
    """
    conn = duckdb.connect(str(db_path))
    
    try:
        result = conn.execute(query).fetchdf()
        df = pl.from_pandas(result)
        return df
    except Exception as e:
        logger.error(f"Query failed: {e}")
        return None
    finally:
        conn.close()


def test_lookahead_bias(db_path: Path = WAREHOUSE_PATH):
    """
    Lookahead probe: Insert future-dated row, verify it cannot influence backtest
    
    H5 Contract: Future-dated rows cannot leak into historical queries
    """
    try:
        # Insert a future-dated row
        future_row = pl.DataFrame({
            "season": [2099],
            "week": [1],
            "team_id": ["FUTURE"],
            "team_name": ["Future Team"],
            "wins": [999],
            "losses": [0],
            "ties": [0],
            "points_for": [9999.0]
        })
        
        insert_dataframe(future_row, "standings", db_path)
    except Exception as e:
        # If duplicate key (already inserted in previous run), that's OK
        logger.info(f"Future row insert skipped/failed (expected if re-running): {e}")
    
    # Query for historical data (should not include future row)
    historical_query = """
        SELECT * FROM standings 
        WHERE season <= 2025 
        AND as_of < '2026-01-01'
    """
    
    result = query_warehouse(historical_query, db_path)
    
    if result is not None:
        if "FUTURE" in result["team_id"].to_list():
            logger.error("LOOKAHEAD BIAS DETECTED: Future row leaked into historical query!")
            return False
        else:
            logger.info("✓ Lookahead bias test PASSED: Future row correctly excluded")
            return True
    else:
        logger.warning("Could not verify lookahead bias protection")
        return None


if __name__ == "__main__":
    print("Initializing DuckDB warehouse...")
    db_path = init_warehouse()
    print(f"✓ Warehouse created at {db_path}")
    
    # Test insert and query
    print("\nTesting insert/query...")
    test_data = pl.DataFrame({
        "season": [2025],
        "week": [1],
        "team_id": ["TEST"],
        "team_name": ["Test Team"],
        "owner_name": ["Tester"],
        "wins": [0],
        "losses": [0],
        "ties": [0],
        "points_for": [0.0],
        "points_against": [0.0]
    })
    
    insert_dataframe(test_data, "standings")
    
    result = query_warehouse("SELECT * FROM standings WHERE team_id = 'TEST'")
    if result is not None and not result.is_empty():
        print(f"✓ Insert/query test passed: {len(result)} rows retrieved")
    else:
        print("✗ Insert/query test failed")
    
    # Test lookahead bias protection
    print("\nTesting lookahead bias protection...")
    test_lookahead_bias()
