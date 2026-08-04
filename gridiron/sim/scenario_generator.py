"""
sim/scenario_generator.py
Generates N=10k joint player-score scenarios per week.
Integrates projections, correlation kernel, and team totals.
"""
import numpy as np
import polars as pl
from typing import Dict, List, Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class ScenarioGenerator:
    """
    Generates joint score scenarios for all players in a given week.
    Used by lineup optimizer, season sim, and waiver valuation.
    """
    
    def __init__(self, 
                 projection_engine,
                 correlation_kernel,
                 config_path: str = "league_config.yaml"):
        self.projection_engine = projection_engine
        self.correlation_kernel = correlation_kernel
        self.config_path = config_path
        self.n_scenarios = 10000
        
    def generate_weekly_scenarios(self,
                                 player_data: pl.DataFrame,
                                 odds_data: Optional[pl.DataFrame] = None,
                                 n_scenarios: int = None) -> Dict[str, np.ndarray]:
        """
        Generate full joint distribution of player scores for the week.
        
        Args:
            player_data: DataFrame with player projections and metadata
            odds_data: Optional DataFrame with betting odds (implied totals)
            n_scenarios: Override default scenario count
            
        Returns:
            Dict mapping player_id -> array of simulated scores (n_scenarios,)
        """
        if n_scenarios is None:
            n_scenarios = self.n_scenarios
            
        # Extract team implied totals from odds
        team_totals = self._extract_team_totals(player_data, odds_data)
        
        # Group players by team
        roster_by_team = {}
        for team in player_data['team'].unique():
            team_players = player_data.filter(pl.col('team') == team)
            roster_by_team[team] = []
            
            for row in team_players.iter_rows(named=True):
                roster_by_team[team].append({
                    'player_id': row['player_id'],
                    'position': row['position'],
                    'proj_share': row.get('proj_share', 1.0),
                    'proj_points': row.get('proj_p50', row.get('consensus_mean', 10.0))
                })
                
        # Generate scenarios via correlation kernel
        scenarios = self.correlation_kernel.simulate_joint_scores(
            team_totals,
            roster_by_team,
            n_scenarios=n_scenarios
        )
        
        # Add individual variance (uncorrelated component)
        scenarios = self._add_individual_variance(scenarios, player_data)
        
        return scenarios
    
    def _extract_team_totals(self,
                            player_data: pl.DataFrame,
                            odds_data: Optional[pl.DataFrame]) -> Dict[str, float]:
        """Extract implied team totals from odds data or use projections"""
        team_totals = {}
        
        if odds_data is not None and len(odds_data) > 0:
            # Use betting market implied totals
            for row in odds_data.iter_rows(named=True):
                team_totals[row['team']] = row['implied_total']
        else:
            # Fallback: sum of player projections
            grouped = player_data.group_by('team').agg(
                pl.col('proj_p50').sum().alias('total_proj')
            )
            for row in grouped.iter_rows(named=True):
                team_totals[row['team']] = row['total_proj'] * 1.1  # Slight upward adjustment
                
        return team_totals
    
    def _add_individual_variance(self,
                                scenarios: Dict[str, np.ndarray],
                                player_data: pl.DataFrame) -> Dict[str, np.ndarray]:
        """
        Add uncorrelated individual variance to scenarios.
        Calibrated to historical prediction errors.
        """
        # Historical RMSE by position (approximate)
        position_rmse = {
            'QB': 4.5,
            'RB': 3.8,
            'WR': 4.2,
            'TE': 3.0,
            'K': 2.5,
            'DEF': 4.0
        }
        
        result = {}
        for pid, scores in scenarios.items():
            # Get player position
            player_row = player_data.filter(pl.col('player_id') == pid)
            if len(player_row) == 0:
                result[pid] = scores
                continue
                
            pos = player_row['position'][0]
            rmse = position_rmse.get(pos, 4.0)
            
            # Add noise
            noise = np.random.normal(0, rmse, len(scores))
            result[pid] = np.maximum(0, scores + noise)  # Floor at 0
            
        return result
    
    def get_scenario_statistics(self,
                               scenarios: Dict[str, np.ndarray]) -> Dict[str, Dict]:
        """
        Calculate summary statistics for each player's scenario distribution.
        """
        stats = {}
        for pid, scores in scenarios.items():
            stats[pid] = {
                'mean': float(np.mean(scores)),
                'std': float(np.std(scores)),
                'p25': float(np.percentile(scores, 25)),
                'p50': float(np.percentile(scores, 50)),
                'p75': float(np.percentile(scores, 75)),
                'p90': float(np.percentile(scores, 90)),
                'ceiling': float(np.percentile(scores, 95)),
                'floor': float(np.percentile(scores, 10))
            }
        return stats
    
    def simulate_matchup(self,
                        user_lineup: List[str],
                        opponent_lineup: List[str],
                        scenarios: Dict[str, np.ndarray]) -> Dict:
        """
        Simulate head-to-head matchup between two lineups.
        
        Returns:
            Dict with P(win), E[user_score], E[opponent_score], score distributions
        """
        # Aggregate lineup scores
        user_scores = np.zeros(len(list(scenarios.values())[0]))
        opponent_scores = np.zeros(len(user_scores))
        
        for pid in user_lineup:
            if pid in scenarios:
                user_scores += scenarios[pid]
                
        for pid in opponent_lineup:
            if pid in scenarios:
                opponent_scores += scenarios[pid]
                
        # Calculate metrics
        wins = user_scores > opponent_scores
        ties = user_scores == opponent_scores
        
        return {
            'P(win)': float(np.mean(wins)),
            'P(tie)': float(np.mean(ties)),
            'P(loss)': float(np.mean(~wins & ~ties)),
            'E[user_score]': float(np.mean(user_scores)),
            'E[opponent_score]': float(np.mean(opponent_scores)),
            'user_score_dist': user_scores,
            'opponent_score_dist': opponent_scores,
            'score_diff': user_scores - opponent_scores
        }
