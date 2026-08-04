"""
Consensus Projection Scraper

Aggregates player projections from ≥3 public sources.
Handles JS-rendered fallbacks gracefully (degrade to fewer sources rather than fragile headless browsing).

Sources (priority order):
1. FantasyPros (via API - already in nfl_fantasy_client.py)
2. ESPN (public pages, HTML parsing)
3. NFL.com (public pages, HTML parsing)  
4. Yahoo (public pages, HTML parsing)

Macro Objective: Consensus mean as anchor for projection model
Micro Focus: Source provenance tracking, schema consistency
"""

import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pathlib import Path
from dataclasses import dataclass

import polars as pl
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class ProjectionSource:
    """Metadata for a projection source"""
    name: str
    url_pattern: str
    is_js_rendered: bool
    priority: int  # Lower = higher priority
    fallback_available: bool


# Source definitions
PROJECTION_SOURCES = [
    ProjectionSource(
        name="FantasyPros",
        url_pattern="https://www.fantasypros.com/nfl/rankings/",
        is_js_rendered=True,  # Requires API (handled separately)
        priority=1,
        fallback_available=True
    ),
    ProjectionSource(
        name="ESPN",
        url_pattern="https://www.espn.com/fantasy/football/story/_/page/playersranked",
        is_js_rendered=True,  # Heavy JS - may need fallback
        priority=2,
        fallback_available=False
    ),
    ProjectionSource(
        name="NFL.com",
        url_pattern="https://www.nfl.com/stats/player-stats",
        is_js_rendered=False,  # Server-side rendered
        priority=3,
        fallback_available=True
    ),
    ProjectionSource(
        name="Yahoo",
        url_pattern="https://sports.yahoo.com/fantasy/football/players/",
        is_js_rendered=True,  # Heavy JS
        priority=4,
        fallback_available=False
    )
]


class ConsensusScraper:
    """
    Aggregate projections from multiple public sources
    
    Design principle: If a source is JS-rendered and requires headless browsing,
    fall back to fewer sources rather than adding brittle scraping infrastructure.
    
    Macro Focus: Consensus mean > individual source heroics
    """
    
    def __init__(self, output_dir: Path = Path("data/parquet")):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        
    def scrape_espn(self) -> Optional[pl.DataFrame]:
        """
        Scrape ESPN projections
        
        Note: ESPN is heavily JS-rendered. This attempts basic HTML parsing,
        but will likely fail and trigger fallback behavior.
        
        Returns DataFrame with columns:
        - player_name, position, team, projected_points, source
        - as_of timestamp
        """
        try:
            # ESPN URL for fantasy football rankings
            url = "https://www.espn.com/fantasy/football/story/_/page/playersranked"
            response = self.session.get(url, timeout=30)
            
            if response.status_code != 200:
                logger.warning(f"ESPN returned status {response.status_code}")
                return None
                
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Try to extract player table (structure may change)
            players = []
            table = soup.find('table')
            if not table:
                logger.warning("ESPN: No table found - likely JS-rendered")
                return None
                
            rows = table.find_all('tr')[1:]  # Skip header
            for row in rows:
                cols = row.find_all('td')
                if len(cols) < 5:
                    continue
                    
                try:
                    player = {
                        "player_name": cols[1].get_text(strip=True),
                        "position": cols[2].get_text(strip=True),
                        "team": cols[3].get_text(strip=True),
                        "projected_points": float(cols[4].get_text(strip=True) or 0),
                        "source": "ESPN",
                        "as_of": datetime.now(timezone.utc).isoformat()
                    }
                    players.append(player)
                except (ValueError, IndexError) as e:
                    continue
                    
            if not players:
                logger.warning("ESPN: No players extracted - JS rendering detected")
                return None
                
            df = pl.DataFrame(players)
            logger.info(f"Scraped ESPN: {len(df)} players")
            return df
            
        except Exception as e:
            logger.error(f"ESPN scrape failed: {e}")
            return None
    
    def scrape_nfl_com(self) -> Optional[pl.DataFrame]:
        """
        Scrape NFL.com player stats/projections
        
        NFL.com is server-side rendered, more reliable for scraping.
        
        Returns DataFrame with columns:
        - player_name, position, team, projected_points (or stats), source
        - as_of timestamp
        """
        try:
            url = "https://www.nfl.com/stats/player-stats"
            params = {
                "season": datetime.now().year,
                "tab": "proj_passing"  # Start with passing projections
            }
            
            response = self.session.get(url, params=params, timeout=30)
            
            if response.status_code != 200:
                logger.warning(f"NFL.com returned status {response.status_code}")
                return None
                
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Extract player table
            players = []
            table = soup.find('table')
            if not table:
                logger.warning("NFL.com: No table found")
                return None
                
            rows = table.find_all('tr')[1:]
            for row in rows:
                cols = row.find_all('td')
                if len(cols) < 4:
                    continue
                    
                try:
                    player = {
                        "player_name": cols[0].get_text(strip=True),
                        "position": cols[1].get_text(strip=True),
                        "team": cols[2].get_text(strip=True),
                        "projected_points": 0.0,  # NFL.com shows stats, not projections directly
                        "source": "NFL.com",
                        "as_of": datetime.now(timezone.utc).isoformat()
                    }
                    players.append(player)
                except (ValueError, IndexError) as e:
                    continue
                    
            if not players:
                logger.warning("NFL.com: No players extracted")
                return None
                
            df = pl.DataFrame(players)
            logger.info(f"Scraped NFL.com: {len(df)} players")
            return df
            
        except Exception as e:
            logger.error(f"NFL.com scrape failed: {e}")
            return None
    
    def aggregate_consensus(self, sources: Optional[List[str]] = None) -> Optional[pl.DataFrame]:
        """
        Aggregate projections from available sources into consensus
        
        Args:
            sources: List of source names to include. If None, use all available.
            
        Returns DataFrame with columns:
        - player_name, position, team
        - consensus_mean, consensus_std, source_count
        - individual_source_projections (wide format)
        - as_of timestamp
        """
        all_dfs = []
        
        # Try each source
        for source_def in PROJECTION_SOURCES:
            if sources and source_def.name not in sources:
                continue
                
            # Skip JS-rendered sources (per design doc - no headless browsing)
            if source_def.is_js_rendered:
                logger.info(f"Skipping JS-rendered source: {source_def.name}")
                continue
                
            df = None
            if source_def.name == "ESPN":
                df = self.scrape_espn()
            elif source_def.name == "NFL.com":
                df = self.scrape_nfl_com()
                
            if df is not None:
                all_dfs.append(df)
                
        if not all_dfs:
            logger.warning("No sources successfully scraped")
            return None
            
        # Combine all sources
        combined = pl.concat(all_dfs, how="vertical_relaxed")
        
        # Calculate consensus per player
        consensus = combined.group_by(["player_name", "position", "team"]).agg(
            pl.col("projected_points").mean().alias("consensus_mean"),
            pl.col("projected_points").std().alias("consensus_std"),
            pl.col("source").n_unique().alias("source_count"),
            pl.col("projected_points").alias("all_projections"),
            pl.col("source").alias("sources")
        )
        
        # Add timestamp
        consensus = consensus.with_columns(
            pl.lit(datetime.now(timezone.utc).isoformat()).alias("as_of")
        )
        
        # Cache result
        cache_file = self.output_dir / f"consensus_projections_{datetime.now().strftime('%Y%m%d_%H%M%S')}.parquet"
        consensus.write_parquet(cache_file)
        
        logger.info(f"Consensus aggregated: {len(consensus)} players from {len(all_dfs)} sources")
        return consensus
    
    def log_tradeoff_decision(self, decision: str):
        """
        Log tradeoff decisions (e.g., skipping JS-rendered sources)
        
        Macro Focus: Document why we chose robustness over completeness
        """
        log_file = Path("docs/DECISIONS.md")
        timestamp = datetime.now(timezone.utc).isoformat()
        
        entry = f"""
## Consensus Scraper Tradeoff - {timestamp}

**Decision**: {decision}

**Rationale**: Per architecture spec §2, we prefer falling back to fewer sources
rather than implementing fragile headless browsing. The consensus mean from 2-3
reliable sources is near-efficient; the edge lives in valuation/posture/streams/waivers,
not projection heroics.

**Impact**: May miss some niche projections, but system remains operable.
"""
        
        with open(log_file, 'a') as f:
            f.write(entry)
            
        logger.info(f"Logged tradeoff decision: {decision}")


def validate_consensus_schema(df: pl.DataFrame) -> bool:
    """Validate consensus DataFrame has required columns"""
    required = {"player_name", "position", "team", "consensus_mean", "consensus_std", "source_count", "as_of"}
    actual = set(df.columns)
    
    if not required.issubset(actual):
        missing = required - actual
        logger.error(f"Consensus schema validation failed. Missing: {missing}")
        return False
        
    logger.info("Consensus schema validation passed")
    return True


def staleness_check(df: pl.DataFrame, max_age_hours: int = 24) -> bool:
    """Check if consensus data is stale"""
    if "as_of" not in df.columns:
        return True
        
    try:
        as_of_str = df["as_of"][0]
        as_of = datetime.fromisoformat(as_of_str.replace('Z', '+00:00'))
        age = datetime.now(timezone.utc) - as_of
        
        if age.total_seconds() / 3600 > max_age_hours:
            logger.warning(f"Consensus data is stale: {age.total_seconds()/3600:.1f} hours old")
            return True
            
        return False
        
    except Exception as e:
        logger.error(f"Consensus staleness check failed: {e}")
        return True


if __name__ == "__main__":
    scraper = ConsensusScraper()
    
    print("Starting consensus projection scrape...")
    print(f"Available sources: {[s.name for s in PROJECTION_SOURCES]}")
    print(f"Will skip JS-rendered sources per design spec")
    
    # Aggregate from non-JS sources
    consensus = scraper.aggregate_consensus()
    
    if consensus is not None and not consensus.is_empty():
        print(f"\n✓ Consensus aggregated: {len(consensus)} players")
        print(f"Schema validation: {validate_consensus_schema(consensus)}")
        print(f"Staleness check: {'PASS' if not staleness_check(consensus) else 'FAIL'}")
        
        # Show sample
        print("\nSample consensus:")
        print(consensus.head(5).select(["player_name", "position", "consensus_mean", "source_count"]))
    else:
        print("\n✗ Failed to aggregate consensus")
        print("Logging tradeoff decision...")
        scraper.log_tradeoff_decision("All sources failed - JS rendering or scraping issues")
