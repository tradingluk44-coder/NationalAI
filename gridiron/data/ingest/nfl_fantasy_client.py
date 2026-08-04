"""
NFL Fantasy API Client - Data Ingestion Module

Reads rosters, standings, waiver order from NFL Fantasy platform.
Primary: api.fantasy.nfl.com unofficial endpoints (via session auth)
Fallback: Manual CSV entry (first-class citizen, not afterthought)

Macro Objective: Provide reliable league state data to maximize P(championship)
Micro Focus: Exact field mapping to league_config.yaml schema
"""

import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, asdict

import requests
import polars as pl
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Constants
FANTASY_PROS_API_KEY = os.getenv("FANTASY_PROS_API_KEY", "")
BASE_URL = "https://api.fantasypros.com/v1"
TIMEZONE_USER = "Europe/Berlin"


@dataclass
class LeagueState:
    """Current state of the league - rosters, standings, waiver order"""
    week: int
    season: int
    teams: List[Dict[str, Any]]
    standings: List[Dict[str, Any]]
    waiver_order: List[Dict[str, Any]]
    as_of: str  # UTC timestamp


class FantasyProsClient:
    """
    Client for FantasyPros API (free tier: 50 req/day)
    
    Provides:
    - League standings
    - Team rosters
    - Player rankings/projections
    
    Failure modes documented in RISKS.md:
    - Rate limiting (50/day hard cap)
    - API endpoint changes
    - Authentication expiry
    """
    
    def __init__(self, api_key: str = FANTASY_PROS_API_KEY):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json"
        })
        self.base_url = BASE_URL
        self._request_count = 0
        self._daily_reset = None
        
    def _check_rate_limit(self) -> bool:
        """Check if we're within daily rate limit (50 req/day)"""
        now = datetime.now(timezone.utc)
        
        # Reset counter at midnight UTC
        if self._daily_reset is None or now.date() > self._daily_reset.date():
            self._request_count = 0
            self._daily_reset = now
            
        if self._request_count >= 50:
            logger.warning(f"Daily rate limit reached ({self._request_count}/50)")
            return False
            
        return True
        
    def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Make API request with rate limiting and error handling"""
        if not self._check_rate_limit():
            return None
            
        try:
            url = f"{self.base_url}/{endpoint}"
            response = self.session.get(url, params=params, timeout=30)
            self._request_count += 1
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode failed: {e}")
            return None
    
    def get_league_standings(self, league_id: str, season: int) -> Optional[pl.DataFrame]:
        """
        Fetch league standings
        
        Returns DataFrame with columns:
        - team_id, team_name, owner_name, wins, losses, ties, points_for, points_against
        - rank, playoff_seed (if applicable)
        - as_of timestamp
        """
        params = {
            "league_id": league_id,
            "season": season,
            "sport": "nfl"
        }
        
        data = self._make_request("standings", params)
        if not data:
            return None
            
        try:
            # Normalize response structure
            teams = []
            for team_data in data.get("teams", []):
                team = {
                    "team_id": team_data.get("team_id"),
                    "team_name": team_data.get("team_name", ""),
                    "owner_name": team_data.get("owner_name", ""),
                    "wins": team_data.get("wins", 0),
                    "losses": team_data.get("losses", 0),
                    "ties": team_data.get("ties", 0),
                    "points_for": team_data.get("points_for", 0.0),
                    "points_against": team_data.get("points_against", 0.0),
                    "rank": team_data.get("rank"),
                    "playoff_seed": team_data.get("playoff_seed"),
                    "as_of": datetime.now(timezone.utc).isoformat()
                }
                teams.append(team)
                
            df = pl.DataFrame(teams)
            logger.info(f"Fetched standings for {len(teams)} teams")
            return df
            
        except Exception as e:
            logger.error(f"Failed to parse standings: {e}")
            return None
    
    def get_team_roster(self, league_id: str, team_id: str, season: int, week: Optional[int] = None) -> Optional[pl.DataFrame]:
        """
        Fetch team roster for specific week
        
        Returns DataFrame with columns:
        - player_id, player_name, position, team, status, slot
        - is_starter, is_bench, is_ir
        - as_of timestamp
        """
        params = {
            "league_id": league_id,
            "team_id": team_id,
            "season": season,
            "sport": "nfl"
        }
        
        if week:
            params["week"] = week
            
        data = self._make_request("rosters", params)
        if not data:
            return None
            
        try:
            players = []
            for player_data in data.get("players", []):
                player = {
                    "player_id": player_data.get("player_id"),
                    "player_name": player_data.get("player_name", ""),
                    "position": player_data.get("position", ""),
                    "team": player_data.get("nfl_team", ""),
                    "status": player_data.get("injury_status", "ACTIVE"),
                    "slot": player_data.get("slot", ""),
                    "is_starter": player_data.get("is_starter", False),
                    "is_bench": player_data.get("is_bench", False),
                    "is_ir": player_data.get("is_ir", False),
                    "as_of": datetime.now(timezone.utc).isoformat()
                }
                players.append(player)
                
            df = pl.DataFrame(players)
            logger.info(f"Fetched roster for team {team_id}: {len(players)} players")
            return df
            
        except Exception as e:
            logger.error(f"Failed to parse roster: {e}")
            return None
    
    def get_waiver_order(self, league_id: str, season: int, week: int) -> Optional[pl.DataFrame]:
        """
        Fetch current waiver order (rolling priority)
        
        Returns DataFrame with columns:
        - team_id, team_name, waiver_priority (1=highest)
        - as_of timestamp
        """
        params = {
            "league_id": league_id,
            "season": season,
            "week": week,
            "sport": "nfl"
        }
        
        data = self._make_request("waiver_order", params)
        if not data:
            return None
            
        try:
            order = []
            for i, team_data in enumerate(data.get("order", []), 1):
                team = {
                    "team_id": team_data.get("team_id"),
                    "team_name": team_data.get("team_name", ""),
                    "waiver_priority": i,
                    "as_of": datetime.now(timezone.utc).isoformat()
                }
                order.append(team)
                
            df = pl.DataFrame(order)
            logger.info(f"Fetched waiver order: {len(order)} teams")
            return df
            
        except Exception as e:
            logger.error(f"Failed to parse waiver order: {e}")
            return None
    
    def get_player_rankings(self, position: Optional[str] = None, category: str = "overall") -> Optional[pl.DataFrame]:
        """
        Fetch player rankings/projections
        
        Categories: overall, QB, RB, WR, TE, K, DEF
        
        Returns DataFrame with columns:
        - player_id, player_name, position, team
        - rank, projected_points, adp
        - as_of timestamp
        """
        params = {
            "category": category,
            "sport": "nfl"
        }
        
        if position:
            params["position"] = position
            
        data = self._make_request("rankings", params)
        if not data:
            return None
            
        try:
            players = []
            for player_data in data.get("rankings", []):
                player = {
                    "player_id": player_data.get("player_id"),
                    "player_name": player_data.get("player_name", ""),
                    "position": player_data.get("position", ""),
                    "team": player_data.get("nfl_team", ""),
                    "rank": player_data.get("rank"),
                    "projected_points": player_data.get("projected_points"),
                    "adp": player_data.get("adp"),
                    "as_of": datetime.now(timezone.utc).isoformat()
                }
                players.append(player)
                
            df = pl.DataFrame(players)
            logger.info(f"Fetched rankings: {len(players)} players")
            return df
            
        except Exception as e:
            logger.error(f"Failed to parse rankings: {e}")
            return None


class ManualEntryLoader:
    """
    Manual CSV entry fallback - FIRST-CLASS CITIZEN
    
    System must be fully operable if API dies mid-season.
    Templates provided for all data types.
    
    Macro Focus: Zero dependency on external APIs for core operation
    """
    
    def __init__(self, data_dir: Path = Path("data/manual")):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
    def create_templates(self):
        """Create CSV templates for manual data entry"""
        templates = {
            "standings_template.csv": [
                "team_id,team_name,owner_name,wins,losses,ties,points_for,points_against,rank,playoff_seed,as_of"
            ],
            "roster_template.csv": [
                "team_id,player_id,player_name,position,nfl_team,status,slot,is_starter,is_bench,is_ir,as_of"
            ],
            "waiver_order_template.csv": [
                "team_id,team_name,waiver_priority,as_of"
            ],
            "projections_template.csv": [
                "player_id,player_name,position,nfl_team,projected_points,adp,source,as_of"
            ]
        }
        
        for filename, headers in templates.items():
            filepath = self.data_dir / filename
            if not filepath.exists():
                with open(filepath, 'w') as f:
                    f.write('\n'.join(headers))
                logger.info(f"Created template: {filepath}")
                
    def load_standings(self, filename: str = "standings.csv") -> Optional[pl.DataFrame]:
        """Load standings from manual CSV"""
        filepath = self.data_dir / filename
        if not filepath.exists():
            logger.warning(f"Manual standings file not found: {filepath}")
            return None
            
        try:
            df = pl.read_csv(filepath)
            # Validate required columns
            required = {"team_id", "wins", "losses", "points_for", "as_of"}
            if not required.issubset(set(df.columns)):
                logger.error(f"Missing required columns. Expected: {required}")
                return None
            logger.info(f"Loaded manual standings: {len(df)} teams")
            return df
        except Exception as e:
            logger.error(f"Failed to load manual standings: {e}")
            return None
            
    def load_roster(self, team_id: str, filename: str = "rosters.csv") -> Optional[pl.DataFrame]:
        """Load team roster from manual CSV"""
        filepath = self.data_dir / filename
        if not filepath.exists():
            logger.warning(f"Manual roster file not found: {filepath}")
            return None
            
        try:
            df = pl.read_csv(filepath)
            if "team_id" not in df.columns:
                logger.error("Missing team_id column")
                return None
                
            roster = df.filter(pl.col("team_id") == team_id)
            logger.info(f"Loaded manual roster for {team_id}: {len(roster)} players")
            return roster
        except Exception as e:
            logger.error(f"Failed to load manual roster: {e}")
            return None
            
    def load_waiver_order(self, filename: str = "waiver_order.csv") -> Optional[pl.DataFrame]:
        """Load waiver order from manual CSV"""
        filepath = self.data_dir / filename
        if not filepath.exists():
            logger.warning(f"Manual waiver order file not found: {filepath}")
            return None
            
        try:
            df = pl.read_csv(filepath)
            required = {"team_id", "waiver_priority", "as_of"}
            if not required.issubset(set(df.columns)):
                logger.error(f"Missing required columns. Expected: {required}")
                return None
            logger.info(f"Loaded manual waiver order: {len(df)} teams")
            return df
        except Exception as e:
            logger.error(f"Failed to load manual waiver order: {e}")
            return None


def validate_schema(df: pl.DataFrame, expected_columns: set, source: str) -> bool:
    """
    Validate DataFrame schema against expected columns
    
    Micro Focus: Catch schema drift early
    Macro Focus: Prevent garbage-in-garbage-out
    """
    actual = set(df.columns)
    missing = expected_columns - actual
    
    if missing:
        logger.error(f"[{source}] Schema validation failed. Missing: {missing}")
        return False
        
    logger.info(f"[{source}] Schema validation passed")
    return True


def staleness_check(df: pl.DataFrame, max_age_hours: int = 24, source: str = "unknown") -> bool:
    """
    Check if data is stale (older than max_age_hours)
    
    Vertical Gate: Each source has staleness monitor
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
    
    Vertical Gate: Row-count sanity bounds per source
    """
    n = len(df)
    if n < min_rows or n > max_rows:
        logger.error(f"[{source}] Row count out of bounds: {n} (expected {min_rows}-{max_rows})")
        return False
        
    logger.info(f"[{source}] Row count OK: {n}")
    return True


if __name__ == "__main__":
    # Test manual entry loader
    loader = ManualEntryLoader()
    loader.create_templates()
    print("Templates created in data/manual/")
    
    # Test FantasyPros client (requires valid API key)
    if FANTASY_PROS_API_KEY:
        client = FantasyProsClient()
        print(f"FantasyPros client initialized. Daily requests: {client._request_count}/50")
    else:
        print("No FantasyPros API key found. Using manual entry mode.")
