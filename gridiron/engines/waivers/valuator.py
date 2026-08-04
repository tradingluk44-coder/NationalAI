"""
engines/waivers/valuator.py
Calculates ΔP(playoffs) for waiver candidates.
Uses season Monte Carlo to estimate playoff probability impact.
"""
import numpy as np
import polars as pl
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

class WaiverValuator:
    """
    Values waiver adds by their impact on playoff probability.
    Core insight: Not all points are equal - points that move you from 6th to 4th are worth more than 3rd to 2nd.
    """
    
    def __init__(self, season_simulator, config_path: str = "league_config.yaml"):
        self.season_simulator = season_simulator
        self.config_path = config_path
        
    def calculate_delta_playoff_prob(self,
                                    current_roster: List[str],
                                    candidate_player: Dict,
                                    drop_player: Optional[str] = None,
                                    league_state: Dict = None) -> float:
        """
        Calculate change in playoff probability from adding a player.
        
        Args:
            current_roster: List of current player IDs
            candidate_player: Dict with candidate info (player_id, proj_p50, etc.)
            drop_player: Player ID to drop (or None for bench add)
            league_state: Current standings, remaining schedules, etc.
            
        Returns:
            ΔP(playoffs) in percentage points
        """
        # Simulate rest of season WITHOUT the add
        base_scenario = self._build_roster_scenario(
            current_roster,
            drop_player=None,
            add_player=None,
            league_state=league_state
        )
        p_playoffs_base = self.season_simulator.run_simulation(base_scenario)['P(playoffs)']
        
        # Simulate WITH the add
        if drop_player:
            new_roster = [p for p in current_roster if p != drop_player] + [candidate_player['player_id']]
        else:
            new_roster = current_roster + [candidate_player['player_id']]
            
        add_scenario = self._build_roster_scenario(
            new_roster,
            drop_player=None,
            add_player=candidate_player,
            league_state=league_state
        )
        p_playoffs_add = self.season_simulator.run_simulation(add_scenario)['P(playoffs)']
        
        delta = p_playoffs_add - p_playoffs_base
        return delta * 100  # Return as percentage points
    
    def _build_roster_scenario(self,
                              roster: List[str],
                              drop_player: Optional[str],
                              add_player: Optional[Dict],
                              league_state: Dict) -> Dict:
        """Build scenario dict for season simulator"""
        # In production, this constructs full roster projection object
        # For now, simplified placeholder
        return {
            'roster': roster,
            'add_player': add_player,
            'league_state': league_state or {}
        }
    
    def evaluate_waiver_class(self,
                             candidates: List[Dict],
                             current_roster: List[str],
                             league_state: Dict,
                             priority_position: int,
                             total_teams: int = 10) -> List[Dict]:
        """
        Evaluate full waiver class and generate recommendations.
        
        Args:
            candidates: List of available players
            current_roster: User's current roster
            league_state: League context
            priority_position: User's waiver priority (1 = first)
            total_teams: Number of teams in league
            
        Returns annotated candidate list
        """
        results = []
        
        # Determine threshold based on priority position
        # Top-3 priority requires higher bar (I8 invariant)
        is_top3_priority = priority_position <= 3
        min_delta_threshold = 4.0 if is_top3_priority else 1.5
        
        for candidate in candidates:
            # Find reasonable drop candidate (worst bench player)
            drop_candidate = self._find_drop_target(current_roster, candidate)
            
            # Calculate ΔP(playoffs)
            delta = self.calculate_delta_playoff_prob(
                current_roster,
                candidate,
                drop_candidate,
                league_state
            )
            
            candidate['delta_playoff_prob'] = delta
            candidate['drop_candidate'] = drop_candidate
            candidate['meets_threshold'] = delta >= min_delta_threshold
            
            # Generate recommendation
            if is_top3_priority and delta < min_delta_threshold:
                candidate['recommendation'] = f"SKIP (need ≥{min_delta_threshold}pp for top-3 priority)"
            elif delta >= min_delta_threshold:
                candidate['recommendation'] = f"ADD ({delta:.1f}pp playoff boost)"
            else:
                candidate['recommendation'] = f"BENCH ADD / MONITOR ({delta:.1f}pp)"
                
            results.append(candidate)
            
        # Sort by delta
        results.sort(key=lambda x: x['delta_playoff_prob'], reverse=True)
        return results
    
    def _find_drop_target(self,
                         roster: List[str],
                         candidate: Dict) -> Optional[str]:
        """
        Identify worst bench player to drop.
        Simplified logic - in production uses VORP ranking.
        """
        # Placeholder: return last bench player
        # Real implementation would rank by rest-of-season VORP
        if len(roster) > 9:  # Assuming 9 starters
            return roster[-1]  # Drop last bench player
        return None
    
    def get_priority_value_report(self,
                                 candidates: List[Dict],
                                 priority_position: int) -> Dict:
        """
        Generate report on value of waiver priority position.
        Helps decide whether to use priority or let roll.
        """
        top_candidates = [c for c in candidates if c.get('meets_threshold', False)]
        
        if not top_candidates:
            return {
                'priority_value': 'LOW',
                'recommendation': 'Let priority roll - no impactful adds',
                'best_delta': 0.0
            }
            
        best_delta = max(c['delta_playoff_prob'] for c in top_candidates)
        
        if priority_position <= 3:
            if best_delta >= 6.0:
                value = 'HIGH'
                rec = 'USE PRIORITY - championship-caliber add available'
            elif best_delta >= 4.0:
                value = 'MEDIUM'
                rec = 'CONSIDER USING - solid starter upgrade'
            else:
                value = 'LOW'
                rec = 'Let priority roll - marginal upgrade only'
        else:
            value = 'N/A'
            rec = f'Priority #{priority_position} - target: {top_candidates[0]["player_id"]}'
            
        return {
            'priority_value': value,
            'recommendation': rec,
            'best_delta': best_delta,
            'top_target': top_candidates[0]['player_id'] if top_candidates else None
        }
