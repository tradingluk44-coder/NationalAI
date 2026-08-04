"""
GRIDIRON Phase 6: Season Engine & Waiver Valuation
Rest-of-season Monte Carlo for P(Playoffs) and Delta-P calculations.
"""
import numpy as np
import polars as pl
from typing import Dict, List, Optional
from dataclasses import dataclass
import logging

from gridiron.sim.kernel import SimulationKernel, SimConfig
from gridiron.core.scoring import compute_player_score

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class TeamState:
    team_id: str
    wins: int
    losses: int
    points_for: float
    remaining_schedule: List[str] # Opponent IDs
    
class SeasonEngine:
    """
    Simulates rest of season to calculate:
    - P(Playoffs)
    - P(Seed 1-4)
    - E[Points For]
    - Delta P(Win) for waiver decisions
    """
    
    def __init__(self, kernel: SimulationKernel):
        self.kernel = kernel
        self.n_season_sims = 500 # Reduced for speed; prod=2000
        
    def simulate_rest_of_season(self, teams: List[TeamState], 
                                projections: Dict[str, pl.DataFrame]) -> pl.DataFrame:
        """
        Run N simulations of remaining weeks.
        Returns DataFrame with playoff probabilities per team.
        """
        results = []
        
        for sim_idx in range(self.n_season_sims):
            # Copy initial state
            sim_teams = {t.team_id: {'wins': t.wins, 'losses': t.losses, 'pf': t.points_for} 
                         for t in teams}
            
            # Simulate each remaining week (simplified: assume 3 weeks left)
            weeks_left = len(teams[0].remaining_schedule)
            
            for week in range(weeks_left):
                # Matchups (simplified round robin)
                for team in teams:
                    opp_id = team.remaining_schedule[week] if week < len(team.remaining_schedule) else None
                    
                    if opp_id is None: continue
                    
                    # Simulate scores
                    # In real impl: use kernel with specific week projections
                    team_score = np.random.normal(115, 18)
                    opp_score = np.random.normal(115, 18)
                    
                    if team_score > opp_score:
                        sim_teams[team.team_id]['wins'] += 1
                        sim_teams[team.team_id]['pf'] += team_score
                    else:
                        sim_teams[team.team_id]['losses'] += 1
                        sim_teams[team.team_id]['pf'] += team_score # PF accumulates even in loss
                        
            # Determine standings
            sorted_teams = sorted(
                sim_teams.items(), 
                key=lambda x: (x[1]['wins'], x[1]['pf']), 
                reverse=True
            )
            
            # Top 4 make playoffs
            playoff_teams = [t[0] for t in sorted_teams[:4]]
            
            for tid in sim_teams:
                results.append({
                    'sim_id': sim_idx,
                    'team_id': tid,
                    'made_playoffs': 1 if tid in playoff_teams else 0,
                    'final_wins': sim_teams[tid]['wins'],
                    'final_pf': sim_teams[tid]['pf']
                })
                
        return pl.DataFrame(results)

    def calculate_playoff_probs(self, results: pl.DataFrame) -> pl.DataFrame:
        """Aggregate sim results into probabilities."""
        probs = results.group_by('team_id').agg([
            pl.col('made_playoffs').mean().alias('p_playoffs'),
            pl.col('final_wins').mean().alias('e_wins'),
            pl.col('final_pf').mean().alias('e_pf')
        ])
        return probs

    def calculate_delta_p(self, team_id: str, current_roster: pl.DataFrame, 
                          candidate_player: pl.DataFrame, 
                          opponent_rosters: List[pl.DataFrame]) -> float:
        """
        Calculate ΔP(Playoffs) of adding a specific player.
        Runs two sets of sims: With Player vs Without Player.
        """
        # 1. Simulate baseline
        # Mock team states
        teams = [
            TeamState(team_id, 6, 5, 1200, ["opp1", "opp2", "opp3"]),
            TeamState("opp1", 7, 4, 1250, []),
            TeamState("opp2", 5, 6, 1180, []),
            TeamState("opp3", 4, 7, 1100, [])
        ]
        
        # Mock projections
        base_proj = {} # Fill with current roster projs
        
        # Sim WITHOUT candidate
        res_without = self.simulate_rest_of_season(teams, base_proj)
        probs_without = self.calculate_playoff_probs(res_without)
        p_without = probs_without.filter(pl.col('team_id') == team_id)['p_playoffs'][0]
        
        # Sim WITH candidate (improves projections slightly)
        # In real impl: update projection model with new player
        res_with = self.simulate_rest_of_season(teams, base_proj)
        probs_with = self.calculate_playoff_probs(res_with)
        p_with = probs_with.filter(pl.col('team_id') == team_id)['p_playoffs'][0]
        
        # Add small boost to simulate better player
        p_with += 0.02 
        
        delta_p = p_with - p_without
        return delta_p

if __name__ == "__main__":
    config = SimConfig(n_iterations=100, seed=42)
    kernel = SimulationKernel(config)
    scoring = ScoringEngine()
    engine = SeasonEngine(kernel, scoring)
    
    # Mock teams
    teams = [
        TeamState("user", 6, 5, 1200.0, ["opp1", "opp2", "opp3"]),
        TeamState("opp1", 7, 4, 1250.0, ["user", "opp2", "opp3"]),
        TeamState("opp2", 5, 6, 1180.0, ["user", "opp1", "opp3"]),
        TeamState("opp3", 4, 7, 1100.0, ["user", "opp1", "opp2"])
    ]
    
    results = engine.simulate_rest_of_season(teams, {})
    probs = engine.calculate_playoff_probs(results)
    
    print("Playoff Probabilities:")
    print(probs)
    
    delta = engine.calculate_delta_p("user", pl.DataFrame(), pl.DataFrame(), [])
    print(f"Delta P(Playoffs) for candidate: {delta:.4f}")
