"""
TheOdds API Client - Betting Odds for Implied Totals

Free tier: 500 requests/month
Planned usage: ≤2 pulls/week (Thu + Sun) = ~8-10/month, well within budget

Provides:
- Game moneylines, spreads, totals
- Implied team totals (derived from game totals)
- Historical odds for backtesting

Macro Objective: Odds-implied totals drive correlation kernel and DEF stream boards
Micro Focus: Exact market mapping, rate limit enforcement
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Any
from pathlib import Path

import polars as pl
import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Constants
THE_ODDS_API_KEY = os.getenv("THE_ODDS_API_KEY", "")
BASE_URL = "https://api.the-odds-api.com/v4"
MONTHLY_BUDGET = 500  # requests/month
PLANNED_WEEKLY_PULLS = 2  # Thu + Sun


class TheOddsClient:
    """
    Client for TheOdds API free tier
    
    Rate limiting:
    - 500 requests/month hard cap
    - Track usage across sessions
    - Assert ≤2 calls/week in code (per spec §1)
    
    Failure modes documented in RISKS.md:
    - Budget exhaustion
    - API endpoint changes
    - Market availability gaps
    """
    
    def __init__(self, api_key: str = THE_ODDS_API_KEY):
        self.api_key = api_key
        self.session = requests.Session()
        self.base_url = BASE_URL
        
        # Usage tracking
        self._usage_file = Path("data/odds_usage.json")
        self._monthly_count = 0
        self._weekly_count = 0
        self._last_reset = None
        self._load_usage()
        
    def _load_usage(self):
        """Load usage tracking from file"""
        if self._usage_file.exists():
            try:
                import json
                with open(self._usage_file, 'r') as f:
                    data = json.load(f)
                    self._monthly_count = data.get("monthly_count", 0)
                    self._weekly_count = data.get("weekly_count", 0)
                    self._last_reset = datetime.fromisoformat(data.get("last_reset")) if data.get("last_reset") else None
            except Exception as e:
                logger.warning(f"Failed to load usage tracking: {e}")
                
    def _save_usage(self):
        """Save usage tracking to file"""
        import json
        data = {
            "monthly_count": self._monthly_count,
            "weekly_count": self._weekly_count,
            "last_reset": self._last_reset.isoformat() if self._last_reset else None
        }
        with open(self._usage_file, 'w') as f:
            json.dump(data, f)
            
    def _check_budget(self) -> bool:
        """
        Check if we're within budget constraints
        
        Vertical Gate: Assert ≤2 calls/week planned, ≤500/month hard cap
        """
        now = datetime.now(timezone.utc)
        
        # Reset monthly counter at start of month
        if self._last_reset is None or now.month != self._last_reset.month:
            self._monthly_count = 0
            self._last_reset = now
            
        # Reset weekly counter on Thursday (planned pull day)
        if now.weekday() == 3:  # Thursday
            self._weekly_count = 0
            
        # Check weekly limit (planned: ≤2/week)
        if self._weekly_count >= PLANNED_WEEKLY_PULLS:
            logger.warning(f"Weekly pull limit reached ({self._weekly_count}/{PLANNED_WEEKLY_PULLS})")
            return False
            
        # Check monthly budget
        if self._monthly_count >= MONTHLY_BUDGET:
            logger.error(f"Monthly budget exhausted ({self._monthly_count}/{MONTHLY_BUDGET})")
            return False
            
        return True
        
    def _increment_usage(self):
        """Increment usage counters"""
        self._monthly_count += 1
        self._weekly_count += 1
        self._save_usage()
        logger.info(f"Usage: {self._monthly_count}/{MONTHLY_BUDGET} monthly, {self._weekly_count}/{PLANNED_WEEKLY_PULLS} weekly")
        
    def get_odds(self, sport: str = "americanfootball_nfl", region: str = "us") -> Optional[pl.DataFrame]:
        """
        Fetch current NFL odds
        
        Returns DataFrame with columns:
        - game_id, commence_time, home_team, away_team
        - bookmaker, market (h2h, spreads, totals)
        - home_price, away_price, home_spread, away_spread, total_points
        - implied_home_total, implied_away_total (derived)
        - as_of timestamp (UTC)
        """
        if not self._check_budget():
            logger.error("Budget constraint violated - cannot fetch odds")
            return None
            
        try:
            url = f"{self.base_url}/sports/{sport}/odds"
            params = {
                "apiKey": self.api_key,
                "regions": region,
                "markets": "h2h,spreads,totals",
                "oddsFormat": "american"
            }
            
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            self._increment_usage()
            
            data = response.json()
            
            # Parse odds into flat DataFrame
            games = []
            for game in data:
                game_id = game.get("id")
                commence_time = game.get("commence_time")
                home_team = game.get("home_team")
                away_team = game.get("away_team")
                
                # Extract bookmaker odds (use first available)
                bookmakers = game.get("bookmakers", [])
                if not bookmakers:
                    continue
                    
                primary = bookmakers[0]  # Use first bookmaker
                markets = {m["key"]: m for m in primary.get("markets", [])}
                
                # H2H (moneyline)
                h2h = markets.get("h2h", {})
                h2h_outcomes = {o["name"]: o["price"] for o in h2h.get("outcomes", [])}
                
                # Spreads
                spreads = markets.get("spreads", {})
                spread_outcomes = {o["name"]: {"point": o["point"], "price": o["price"]} 
                                   for o in spreads.get("outcomes", [])}
                
                # Totals
                totals = markets.get("totals", {})
                total_outcomes = {o["name"]: {"point": o["point"], "price": o["price"]} 
                                  for o in totals.get("outcomes", [])}
                
                # Calculate implied team totals
                game_total = total_outcomes.get("Over", {}).get("point", 0)
                home_spread = spread_outcomes.get(home_team, {}).get("point", 0)
                
                implied_home_total = (game_total + home_spread) / 2
                implied_away_total = (game_total - home_spread) / 2
                
                game_record = {
                    "game_id": game_id,
                    "commence_time": commence_time,
                    "home_team": home_team,
                    "away_team": away_team,
                    "bookmaker": primary.get("title", ""),
                    "home_moneyline": h2h_outcomes.get(home_team),
                    "away_moneyline": h2h_outcomes.get(away_team),
                    "home_spread": home_spread,
                    "away_spread": spread_outcomes.get(away_team, {}).get("point"),
                    "spread_price_home": spread_outcomes.get(home_team, {}).get("price"),
                    "spread_price_away": spread_outcomes.get(away_team, {}).get("price"),
                    "total_points": game_total,
                    "implied_home_total": implied_home_total,
                    "implied_away_total": implied_away_total,
                    "as_of": datetime.now(timezone.utc).isoformat()
                }
                games.append(game_record)
                
            df = pl.DataFrame(games)
            logger.info(f"Fetched odds for {len(df)} games")
            return df
            
        except Exception as e:
            logger.error(f"Failed to fetch odds: {e}")
            return None
    
    def get_historical_odds(self, sport: str = "americanfootball_nfl", 
                           date_from: Optional[str] = None, 
                           date_to: Optional[str] = None) -> Optional[pl.DataFrame]:
        """
        Fetch historical odds for backtesting
        
        Args:
            date_from: ISO format datetime (e.g., "2024-09-01T00:00:00Z")
            date_to: ISO format datetime
            
        Note: Historical access may require paid tier. Log failure mode.
        """
        logger.warning("Historical odds may require paid tier - checking availability")
        
        if not self._check_budget():
            return None
            
        try:
            url = f"{self.base_url}/sports/{sport}/odds/history"
            params = {
                "apiKey": self.api_key,
            }
            
            if date_from:
                params["dateFrom"] = date_from
            if date_to:
                params["dateTo"] = date_to
                
            response = self.session.get(url, params=params, timeout=30)
            
            if response.status_code == 403:
                logger.warning("Historical odds not available on free tier")
                return None
                
            response.raise_for_status()
            self._increment_usage()
            
            # Parse historical data (similar structure to current odds)
            data = response.json()
            # ... parsing logic similar to get_odds() ...
            
            logger.info(f"Fetched historical odds")
            return None  # Placeholder - full implementation needed
            
        except Exception as e:
            logger.error(f"Failed to fetch historical odds: {e}")
            return None


def validate_odds_schema(df: pl.DataFrame) -> bool:
    """Validate odds DataFrame has required columns"""
    required = {
        "game_id", "commence_time", "home_team", "away_team",
        "implied_home_total", "implied_away_total", "as_of"
    }
    actual = set(df.columns)
    
    if not required.issubset(actual):
        missing = required - actual
        logger.error(f"Odds schema validation failed. Missing: {missing}")
        return False
        
    logger.info("Odds schema validation passed")
    return True


def staleness_check(df: pl.DataFrame, max_age_hours: int = 6) -> bool:
    """
    Check if odds data is stale
    
    Odds have shorter useful life than other data (games lock weekly)
    """
    if "as_of" not in df.columns:
        return True
        
    try:
        as_of_str = df["as_of"][0]
        as_of = datetime.fromisoformat(as_of_str.replace('Z', '+00:00'))
        age = datetime.now(timezone.utc) - as_of
        
        if age.total_seconds() / 3600 > max_age_hours:
            logger.warning(f"Odds data is stale: {age.total_seconds()/3600:.1f} hours old")
            return True
            
        return False
        
    except Exception as e:
        logger.error(f"Odds staleness check failed: {e}")
        return True


if __name__ == "__main__":
    if not THE_ODDS_API_KEY:
        print("No TheOdds API key found. Set THE_ODDS_API_KEY environment variable.")
        print("Using mock data for testing...")
        
        # Create mock odds data for testing
        mock_data = {
            "game_id": ["mock_game_1"],
            "commence_time": ["2025-09-07T17:00:00Z"],
            "home_team": ["KC"],
            "away_team": ["BAL"],
            "implied_home_total": [24.5],
            "implied_away_total": [23.5],
            "total_points": [48.0],
            "as_of": [datetime.now(timezone.utc).isoformat()]
        }
        df = pl.DataFrame(mock_data)
        print(f"Mock odds created: {len(df)} games")
    else:
        client = TheOddsClient()
        print(f"TheOdds client initialized")
        print(f"Usage: {client._monthly_count}/{MONTHLY_BUDGET} monthly, {client._weekly_count}/{PLANNED_WEEKLY_PULLS} weekly")
        
        # Fetch current odds
        odds = client.get_odds()
        if odds:
            print(f"\n✓ Fetched {len(odds)} games")
            print(f"Schema validation: {validate_odds_schema(odds)}")
            print(f"Staleness check: {'PASS' if not staleness_check(odds) else 'FAIL'}")
            
            # Show sample
            print("\nSample odds:")
            print(odds.select(["home_team", "away_team", "implied_home_total", "implied_away_total", "total_points"]))
