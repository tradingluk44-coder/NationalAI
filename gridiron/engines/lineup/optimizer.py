"""
GRIDIRON Phase 5: Lineup Optimizer & Posture Logic
Implements I5 (E[pts] vs P(win) switching) and I6 (Playoff overrides).
"""
import numpy as np
import polars as pl
from typing import List, Dict, Optional, Tuple
from itertools import combinations
import logging

from gridiron.sim.kernel import SimulationKernel, SimConfig
from gridiron.core.scoring import compute_player_score
from gridiron.config.settings import CONFIG

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LineupOptimizer:
    """
    Optimizes weekly lineup based on posture logic.
    Default: Maximize E[Points] (protects points_for tiebreaker).
    Toss-up (40-60% win prob): Maximize P(Win) (variance seeking).
    """
    
    def __init__(self, kernel: SimulationKernel, scoring: any):
        self.kernel = kernel
        self.scoring = scoring
        self.roster_constraints = CONFIG['roster']['starters']
        
    def generate_legal_lineups(self, eligible_players: pl.DataFrame) -> List[List[str]]:
        """
        Generate all legal starting lineups from eligible pool.
        Handles FLEX logic (RB/WR/TE).
        """
        # Separate by position
        qb = eligible_players.filter(pl.col('position') == 'QB')['player_id'].to_list()
        rb = eligible_players.filter(pl.col('position') == 'RB')['player_id'].to_list()
        wr = eligible_players.filter(pl.col('position') == 'WR')['player_id'].to_list()
        te = eligible_players.filter(pl.col('position') == 'TE')['player_id'].to_list()
        k = eligible_players.filter(pl.col('position') == 'K')['player_id'].to_list()
        def_ = eligible_players.filter(pl.col('position') == 'DEF')['player_id'].to_list()
        flex_eligible = eligible_players.filter(
            pl.col('position').is_in(['RB', 'WR', 'TE'])
        )['player_id'].to_list()
        
        lineups = []
        
        # Simple combinatorial generation (optimize with constraint solver for prod)
        for q in qb[:1]: # 1 QB
            for rbs in combinations(rb, 2): # 2 RB
                for wrs in combinations(wr, 2): # 2 WR
                    for t in te[:1]: # 1 TE
                        for k_pos in k[:1]: # 1 K
                            for d in def_[:1]: # 1 DEF
                                # FLEX: Must be remaining RB/WR/TE not already started
                                started = set([q] + list(rbs) + list(wrs) + [t] + [k_pos] + [d])
                                flex_options = [p for p in flex_eligible if p not in started]
                                
                                if not flex_options:
                                    continue
                                    
                                for f in flex_options[:1]: # 1 FLEX
                                    lineup = {
                                        'QB': q, 'RB1': rbs[0], 'RB2': rbs[1],
                                        'WR1': wrs[0], 'WR2': wrs[1], 'TE': t,
                                        'FLEX': f, 'K': k_pos, 'DEF': d
                                    }
                                    lineups.append(lineup)
                                    
        return lineups

    def evaluate_lineup(self, lineup: Dict[str, str], 
                        projections: pl.DataFrame, 
                        opp_projections: Optional[pl.DataFrame] = None) -> Dict:
        """
        Simulate a specific lineup.
        Returns E[Points], P(Win), and distribution stats.
        """
        # Extract player IDs
        pids = list(lineup.values())
        
        # Get projections for these players
        player_proj = projections.filter(pl.col('player_id').is_in(pids))
        
        # Run simulation (simplified: using mean of sims as proxy)
        # In full impl: use kernel.run_full_simulation and sum specific columns
        sim_scores = []
        n_sims = 1000 # Subset for speed
        
        # Mock simulation loop
        for _ in range(n_sims):
            total = 0
            for pid in pids:
                row = player_proj.filter(pl.col('player_id') == pid)
                if len(row) == 0: continue
                # Sample from triangular dist approx
                p25 = row['proj_p25'][0]
                p50 = row['proj_p50'][0]
                p85 = row['proj_p85'][0]
                score = np.random.triangular(p25, p50, p85)
                total += score
            sim_scores.append(total)
            
        sim_scores = np.array(sim_scores)
        e_points = np.mean(sim_scores)
        std_dev = np.std(sim_scores)
        
        result = {
            'lineup': lineup,
            'e_points': e_points,
            'std_dev': std_dev,
            'p25': np.percentile(sim_scores, 25),
            'p85': np.percentile(sim_scores, 85)
        }
        
        # If opponent provided, calc P(Win)
        if opp_projections is not None:
            # Mock opponent sim
            opp_scores = []
            for _ in range(n_sims):
                o_total = 0
                # Simplified: random draw from opponent avg
                o_total = np.random.normal(110, 15) 
                opp_scores.append(o_total)
            
            wins = np.sum(sim_scores > opp_scores)
            result['p_win'] = wins / n_sims
        else:
            result['p_win'] = 0.5 # Unknown
            
        return result

    def optimize(self, eligible_players: pl.DataFrame, 
                 opponent_roster: Optional[pl.DataFrame] = None,
                 week: int = 1, 
                 playoff_status: str = "regular") -> Dict:
        """
        Main optimization routine.
        Implements I5 and I6 logic.
        """
        lineups = self.generate_legal_lineups(eligible_players)
        logger.info(f"Evaluating {len(lineups)} legal lineups...")
        
        results = []
        for lu in lineups:
            res = self.evaluate_lineup(lu, eligible_players, 
                                       opp_projections=opponent_roster)
            results.append(res)
            
        results_df = pl.DataFrame(results)
        
        # POSTURE LOGIC (I5)
        # Find median P(Win) to determine regime
        median_pwin = results_df['p_win'].median()
        
        target_col = 'e_points' # Default: Maximize Expectation (Tiebreaker protection)
        
        # Check for Toss-up (40-60%)
        if 0.40 <= median_pwin <= 0.60 and playoff_status != "final":
            logger.info("Toss-up detected: Switching to P(Win) maximization.")
            target_col = 'p_win'
            
        # Playoff Overrides (I6)
        if playoff_status == "semifinal":
            # Week 15: Single week, allow variance if underdog
            if median_pwin < 0.5:
                logger.info("Semifinal Underdog: Variance seeking enabled.")
                # Custom objective: Maximize P(Win) + Lambda * StdDev
                results_df = results_df.with_columns(
                    (pl.col('p_win') + 0.1 * pl.col('std_dev')).alias('objective')
                )
                target_col = 'objective'
                
        elif playoff_status == "final":
            # Weeks 16-17: Two-week aggregate -> Lower variance, Max Expectation
            logger.info("Finals: Two-week aggregate. Maximizing Expectation strictly.")
            target_col = 'e_points'
            
        # Select best lineup
        best_row = results_df.sort(target_col, descending=True).head(1)
        
        return {
            'best_lineup': best_row['lineup'][0],
            'e_points': best_row['e_points'][0],
            'p_win': best_row['p_win'][0],
            'regime': target_col,
            'all_candidates': results_df
        }

if __name__ == "__main__":
    # Test harness
    config = SimConfig(n_iterations=100, seed=42)
    kernel = SimulationKernel(config)
    scoring = ScoringEngine()
    optimizer = LineupOptimizer(kernel, scoring)
    
    # Mock eligible players
    mock_players = pl.DataFrame({
        'player_id': ['qb1', 'rb1', 'rb2', 'rb3', 'wr1', 'wr2', 'wr3', 'te1', 'te2', 'k1', 'def1'],
        'position': ['QB', 'RB', 'RB', 'RB', 'WR', 'WR', 'WR', 'TE', 'TE', 'K', 'DEF'],
        'proj_p25': [15]*11,
        'proj_p50': [20]*11,
        'proj_p85': [28]*11
    })
    
    result = optimizer.optimize(mock_players)
    print(f"Best Lineup: {result['best_lineup']}")
    print(f"Expected Points: {result['e_points']:.2f}")
    print(f"Regime: {result['regime']}")
