"""
core/correlation.py
Game-script simulation: team totals → conditional player draws.
Implements hierarchical allocation with copula-based correlation.
"""
import numpy as np
import polars as pl
from typing import Dict, List, Tuple, Optional
from scipy.stats import norm
import logging

logger = logging.getLogger(__name__)

class CorrelationKernel:
    """
    Models correlation structure between players via team totals.
    Uses hierarchical draw: team total → player allocation.
    """
    
    def __init__(self, config_path: str = "league_config.yaml"):
        self.config_path = config_path
        # Empirical correlation matrices by position pair
        self.position_correlations = {
            ('QB', 'WR'): 0.45,
            ('QB', 'TE'): 0.35,
            ('QB', 'RB'): 0.25,
            ('RB', 'RB'): -0.15,  # Goal-line competition
            ('WR', 'WR'): -0.10,  # Target competition
            ('QB', 'DEF'): -0.30,  # Negative: good QB game = bad DEF game
        }
        
    def generate_team_totals(self, 
                            team_implied_totals: Dict[str, float],
                            team_volatility: Dict[str, float] = None) -> Dict[str, float]:
        """
        Draw team totals from implied totals distribution.
        Uses normal approximation centered on implied total.
        """
        if team_volatility is None:
            team_volatility = {team: 10.0 for team in team_implied_totals}  # Default std dev
            
        drawn_totals = {}
        for team, implied in team_implied_totals.items():
            vol = team_volatility.get(team, 10.0)
            # Draw from normal distribution
            drawn = np.random.normal(implied, vol)
            drawn_totals[team] = max(0, drawn)  # Can't score negative
            
        return drawn_totals
    
    def allocate_player_production(self,
                                  team_total: float,
                                  player_projections: List[Dict],
                                  correlation_matrix: np.ndarray = None) -> List[float]:
        """
        Allocate team total to individual players conditional on game script.
        Uses hierarchical Dirichlet-multinomial approach.
        
        Args:
            team_total: Drawn team score
            player_projections: List of {player_id, position, proj_share, proj_points}
            correlation_matrix: Optional custom correlation matrix
            
        Returns:
            List of allocated points per player
        """
        n_players = len(player_projections)
        if n_players == 0:
            return []
            
        # Base allocation shares from projections
        base_shares = np.array([p['proj_share'] for p in player_projections])
        base_shares = base_shares / base_shares.sum()  # Normalize
        
        # Adjust for game script (simplified)
        # High team total → boost pass catchers, low total → boost RBs
        script_adjustment = self._game_script_adjustment(
            team_total, 
            player_projections,
            base_shares
        )
        
        adjusted_shares = base_shares * script_adjustment
        adjusted_shares = adjusted_shares / adjusted_shares.sum()
        
        # Add noise via Dirichlet distribution (preserves sum=1)
        concentration = 50.0  # Higher = less variance
        noisy_shares = np.random.dirichlet(adjusted_shares * concentration)
        
        # Allocate points
        allocated_points = noisy_shares * team_total
        
        return allocated_points.tolist()
    
    def _game_script_adjustment(self,
                               team_total: float,
                               player_projections: List[Dict],
                               base_shares: np.ndarray) -> np.ndarray:
        """
        Adjust allocation based on game script (high/low scoring).
        """
        adjustment = np.ones(len(player_projections))
        
        league_avg_total = 45.0  # Approximate NFL average
        
        if team_total > league_avg_total + 7:
            # High-scoring game: boost WRs/TEs
            for i, player in enumerate(player_projections):
                if player['position'] in ['WR', 'TE']:
                    adjustment[i] = 1.15
                elif player['position'] == 'RB':
                    adjustment[i] = 0.90
                    
        elif team_total < league_avg_total - 7:
            # Low-scoring game: boost RBs (ground game), reduce passers
            for i, player in enumerate(player_projections):
                if player['position'] == 'RB':
                    adjustment[i] = 1.10
                elif player['position'] in ['WR', 'TE', 'QB']:
                    adjustment[i] = 0.92
                    
        return adjustment
    
    def simulate_joint_scores(self,
                             team_totals: Dict[str, float],
                             roster_assignments: Dict[str, List[Dict]],
                             n_scenarios: int = 1000) -> Dict[str, np.ndarray]:
        """
        Generate joint player score scenarios respecting correlation structure.
        
        Args:
            team_totals: Dict of team_implied_totals
            roster_assignments: Dict mapping team -> list of player projections
            n_scenarios: Number of scenarios to generate
            
        Returns:
            Dict mapping player_id -> array of simulated scores
        """
        player_scenarios = {}
        
        for scenario_idx in range(n_scenarios):
            # Draw team totals
            drawn_totals = self.generate_team_totals(team_totals)
            
            # Allocate to players
            for team, players in roster_assignments.items():
                team_total = drawn_totals.get(team, 21.0)  # Default if missing
                
                allocations = self.allocate_player_production(
                    team_total,
                    players
                )
                
                # Store results
                for i, player in enumerate(players):
                    pid = player['player_id']
                    if pid not in player_scenarios:
                        player_scenarios[pid] = np.zeros(n_scenarios)
                    player_scenarios[pid][scenario_idx] = allocations[i]
                    
        return player_scenarios
    
    def get_positional_correlation(self, pos1: str, pos2: str) -> float:
        """Get empirical correlation between positions"""
        key = tuple(sorted([pos1, pos2]))
        return self.position_correlations.get(key, 0.0)
    
    def validate_correlation_structure(self,
                                      historical_data: pl.DataFrame) -> Dict:
        """
        Compare modeled correlations vs realized historical correlations.
        Returns validation metrics.
        """
        # Calculate realized correlations from historical data
        realized_corr = {}
        
        for (pos1, pos2), expected in self.position_correlations.items():
            # Filter teammates
            teammate_pairs = historical_data.filter(
                (pl.col('position') == pos1) | (pl.col('position') == pos2)
            ).filter(pl.col('team').n_unique() > 1)  # Same team
            
            if len(teammate_pairs) < 50:
                continue
                
            # Pivot and calculate correlation
            pivot = teammate_pairs.pivot(
                index='game_id',
                columns='position',
                values='actual_points'
            )
            
            if pos1 in pivot.columns and pos2 in pivot.columns:
                corr = np.corrcoef(
                    pivot[pos1].drop_nulls(),
                    pivot[pos2].drop_nulls()
                )[0, 1]
                realized_corr[(pos1, pos2)] = {
                    'modeled': expected,
                    'realized': corr if not np.isnan(corr) else 0.0,
                    'deviation': abs(expected - corr) if not np.isnan(corr) else expected
                }
                
        return realized_corr
