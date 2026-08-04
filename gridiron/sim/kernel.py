"""
GRIDIRON Phase 2: Correlation & Simulation Kernel
Shared simulation engine for lineup, season, and waiver modules.
Implements hierarchical draw for team totals -> player allocation.
"""
import numpy as np
import polars as pl
from typing import Dict, List, Tuple
from dataclasses import dataclass
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class SimConfig:
    n_iterations: int = 10000
    seed: int = 42
    correlation_method: str = "hierarchical" # 'hierarchical' or 'copula'

class SimulationKernel:
    """
    Centralized Monte Carlo engine.
    Generates N joint scenarios for all players in a given week.
    Ensures H4: Reproducibility via seed discipline.
    """
    
    def __init__(self, config: SimConfig):
        self.config = config
        self.rng = np.random.default_rng(config.seed)
        
    def set_seed(self, seed: int):
        """Reset seed for reproducibility."""
        self.rng = np.random.default_rng(seed)
        
    def simulate_team_totals(self, teams: List[str], implied_totals: np.ndarray, 
                             std_devs: np.ndarray) -> Dict[str, np.ndarray]:
        """
        Simulate team point totals based on odds-implied distributions.
        Returns dict of {team_id: array_of_scores}
        """
        results = {}
        for i, team in enumerate(teams):
            # Normal approximation for team totals (can be upgraded to Student-t)
            scores = self.rng.normal(implied_totals[i], std_devs[i], self.config.n_iterations)
            results[team] = np.maximum(scores, 0) # Floor at 0
        return results

    def allocate_player_production(self, team_scores: np.ndarray, 
                                   player_shares: Dict[str, float],
                                   player_stds: Dict[str, float],
                                   correlation_factor: float = 0.6) -> Dict[str, np.ndarray]:
        """
        Hierarchical allocation: Distribute team score to players.
        Uses correlation factor to model game script dependency.
        
        Args:
            team_scores: Simulated team totals (N,)
            player_shares: Expected % of team points for each player
            player_stds: Expected volatility for each player
            correlation_factor: How tightly player scores track team total (0-1)
            
        Returns:
            Dict of {player_id: simulated_scores (N,)}
        """
        results = {}
        
        for pid, share in player_shares.items():
            base_mean = team_scores * share
            base_std = player_stds.get(pid, 0.3) * base_mean
            
            if correlation_factor > 0:
                # Add noise independent of team total
                noise = self.rng.normal(0, base_std * (1 - correlation_factor), self.config.n_iterations)
                # Scale with team performance
                player_scores = base_mean + noise
            else:
                player_scores = self.rng.normal(base_mean, base_std, self.config.n_iterations)
                
            results[pid] = np.maximum(player_scores, 0)
            
        return results

    def run_full_simulation(self, projections: pl.DataFrame, 
                            team_mappings: Dict[str, str]) -> pl.DataFrame:
        """
        End-to-end simulation for a full slate of players.
        
        Args:
            projections: DataFrame with p25, p50, p85 cols
            team_mappings: {player_id: team_id}
            
        Returns:
            DataFrame with N rows (scenarios) x Players columns
        """
        unique_teams = list(set(team_mappings.values()))
        
        # Mock implied totals (in real impl: fetch from odds_client)
        implied_totals = np.array([24.5] * len(unique_teams))
        std_devs = np.array([7.0] * len(unique_teams))
        
        # 1. Simulate Team Totals
        team_sims = self.simulate_team_totals(unique_teams, implied_totals, std_devs)
        
        # 2. Allocate to Players
        player_results = {}
        positions = projections['position'].unique()
        
        for pos in positions:
            pos_players = projections.filter(pl.col('position') == pos)
            
            # Group by team for allocation
            for team in unique_teams:
                team_pids = pos_players.filter(
                    pl.col('player_id').is_in([p for p, t in team_mappings.items() if t == team])
                )['player_id'].to_list()
                
                if not team_pids:
                    continue
                    
                # Mock shares (real impl: use usage data)
                n_players = len(team_pids)
                shares = {pid: 1.0/n_players for pid in team_pids}
                stds = {pid: 0.4 for pid in team_pids}
                
                team_scores = team_sims[team]
                allocated = self.allocate_player_production(team_scores, shares, stds)
                player_results.update(allocated)
                
        # Convert to DataFrame
        sim_df = pl.DataFrame(player_results)
        return sim_df

    def calculate_win_probability(self, user_scores: np.ndarray, 
                                  opp_scores: np.ndarray) -> float:
        """Calculate P(Win) from simulated score arrays."""
        wins = np.sum(user_scores > opp_scores)
        ties = np.sum(user_scores == opp_scores)
        return (wins + 0.5 * ties) / len(user_scores)

if __name__ == "__main__":
    config = SimConfig(n_iterations=1000, seed=42)
    kernel = SimulationKernel(config)
    
    # Mock projections
    mock_proj = pl.DataFrame({
        "player_id": ["p1", "p2", "p3"],
        "position": ["QB", "RB", "WR"],
        "proj_p25": [15, 10, 8],
        "proj_p50": [20, 14, 12],
        "proj_p85": [28, 20, 18]
    })
    mappings = {"p1": "KC", "p2": "KC", "p3": "BUF"}
    
    sims = kernel.run_full_simulation(mock_proj, mappings)
    print(f"Generated {len(sims)} scenarios")
    print(sims.head())
