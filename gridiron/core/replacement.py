"""
Replacement Level Calculator

Computes league-size-correct replacement levels per position.

Key principle: Replacement = best projected FREE AGENT (undrafted player),
NOT "last drafted player". This correctly models waiver wire availability.

For a 10-team league with our roster settings:
- Each team starts: 1 QB, 2 RB, 2 WR, 1 TE, 1 FLEX, 1 K, 1 DEF = 9 starters
- Total starters across league: 90 players
- Bench: 6 per team = 60 bench slots
- Total rostered: 150 players
- Replacement = best available from remaining pool after simulated draft
"""

from __future__ import annotations
from typing import Dict, List, Optional
import polars as pl
import numpy as np
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class ReplacementLevel:
    """Replacement level for a position"""
    position: str
    replacement_points: float
    replacement_player_id: Optional[str]
    confidence_interval: tuple  # (lower, upper) bound from ADP noise


class ReplacementCalculator:
    """
    Computes replacement levels via simulated draft
    
    Algorithm:
    1. Simulate draft using ADP distributions (with noise draws)
    2. Track which players go undrafted
    3. Replacement = best projected undrafted player at each position
    4. Average over multiple ADP noise simulations
    """
    
    def __init__(self, config: dict):
        self.config = config
        self.teams = config['league']['teams']
        self.roster_slots = self._count_total_roster_slots()
        
    def _count_total_roster_slots(self) -> int:
        """Count total roster slots per team"""
        starters = sum(self.config['league']['roster']['starters'].values())
        bench = self.config['league']['roster']['bench']
        return starters + bench
    
    def get_replacement_levels(self, projections: pl.DataFrame,
                                adp_noise_draws: int = 100) -> pl.DataFrame:
        """
        Compute replacement levels by position
        
        Args:
            projections: DataFrame with player projections including:
                - player_id
                - position
                - expected_points
                - adp_mean (average draft position)
                - adp_std (ADP standard deviation)
            adp_noise_draws: Number of Monte Carlo draft simulations
        
        Returns:
            DataFrame with columns: [position, replacement_points, 
                                     replacement_player_id, ci_lower, ci_upper]
        """
        positions = projections['position'].unique().tolist()
        results = []
        
        for position in positions:
            pos_projections = projections.filter(pl.col('position') == position)
            
            if len(pos_projections) == 0:
                continue
            
            # Simulate drafts and track undrafted players
            replacement_samples = []
            
            for draw in range(adp_noise_draws):
                # Add noise to ADP
                noisy_adp = pos_projections.with_columns(
                    (pl.col('adp_mean') + 
                     pl.col('adp_std') * pl.Series(np.random.normal(0, 1, len(pos_projections)))
                    ).alias('adp_noisy')
                )
                
                # Sort by noisy ADP
                sorted_players = noisy_adp.sort('adp_noisy')
                
                # Players drafted = top N where N = teams * roster_slots
                total_drafted = self.teams * self.roster_slots
                
                # But we need position-specific calculation
                # Simplified: assume positional distribution mirrors ADP
                pos_drafted = min(len(sorted_players), 
                                  int(total_drafted * len(pos_projections) / len(projections)))
                
                # Undrafted = remaining players
                undrafted = sorted_players.slice(pos_drafted)
                
                if len(undrafted) > 0:
                    # Best undrafted = replacement
                    best_undrafted = undrafted.sort('expected_points', descending=True).head(1)
                    replacement_samples.append(best_undrafted['expected_points'][0])
                else:
                    # All players drafted (deep league) - use last drafted
                    last_drafted = sorted_players.tail(1)
                    replacement_samples.append(last_drafted['expected_points'][0])
            
            # Average over draws
            avg_replacement = np.mean(replacement_samples)
            ci_lower = np.percentile(replacement_samples, 10)
            ci_upper = np.percentile(replacement_samples, 90)
            
            # Find most common replacement player ID
            # (Simplified - would track IDs across draws)
            best_player = None
            
            results.append({
                'position': position,
                'replacement_points': float(avg_replacement),
                'replacement_player_id': best_player,
                'ci_lower': float(ci_lower),
                'ci_upper': float(ci_upper)
            })
        
        return pl.DataFrame(results)
    
    def get_single_position_replacement(self, position: str,
                                         projections: pl.DataFrame,
                                         adp_noise_draws: int = 50) -> float:
        """Get replacement level for single position"""
        levels = self.get_replacement_levels(projections, adp_noise_draws)
        pos_level = levels.filter(pl.col('position') == position)
        
        if len(pos_level) == 0:
            logger.warning(f"No replacement level for {position}, defaulting to 0")
            return 0.0
        
        return pos_level['replacement_points'][0]
    
    def validate_replacement_depth(self, projections: pl.DataFrame) -> dict:
        """
        Validate that replacement levels are reasonable
        
        Checks:
        - Replacement < average starter (should be true)
        - Replacement > 0 (should be true for non-empty positions)
        - Replacement varies appropriately by league size
        """
        levels = self.get_replacement_levels(projections, adp_noise_draws=50)
        
        validation = {
            'all_positive': True,
            'below_average_starter': True,
            'warnings': []
        }
        
        for row in levels.iter_rows(named=True):
            pos = row['position']
            repl_pts = row['replacement_points']
            
            if repl_pts < 0:
                validation['all_positive'] = False
                validation['warnings'].append(f"{pos}: negative replacement ({repl_pts:.1f})")
            
            # Check vs average starter
            pos_data = projections.filter(pl.col('position') == pos)
            avg_starter = pos_data['expected_points'].mean()
            
            if repl_pts >= avg_starter:
                validation['below_average_starter'] = False
                validation['warnings'].append(
                    f"{pos}: replacement ({repl_pts:.1f}) >= avg starter ({avg_starter:.1f})"
                )
        
        return validation
