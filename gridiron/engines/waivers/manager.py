"""
engines/waivers/manager.py
Manages rolling waiver priority as a stored option.
Implements I8 invariant: forbid spending top-3 priority below threshold.
"""
import polars as pl
from typing import Dict, List, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class WaiverManager:
    """
    Orchestrates waiver workflow:
    1. Receives screened candidates from screener.py
    2. Values adds via valuator.py (ΔP(playoffs))
    3. Applies I8 priority threshold logic
    4. Executes claims or lets priority roll
    5. Tracks priority position over time
    """
    
    def __init__(self, 
                 screener,
                 valuator,
                 config_path: str = "league_config.yaml"):
        self.screener = screener
        self.valuator = valuator
        self.config_path = config_path
        
        # Track state
        self.current_priority = 1  # Default starting position
        self.priority_history = []
        self.claim_history = []
        
    def process_waiver_wave(self,
                           usage_data: pl.DataFrame,
                           depth_chart: pl.DataFrame,
                           injury_report: pl.DataFrame,
                           current_roster: List[str],
                           league_state: Dict,
                           week: int) -> Dict:
        """
        Full waiver processing pipeline for a given week.
        
        Returns decision package with recommendations and actions.
        """
        # Step 1: Screen for breakout candidates
        deltas = self.screener.calculate_usage_deltas(usage_data, pl.DataFrame(), lookback=3)
        candidates = self.screener.identify_breakout_candidates(
            deltas, depth_chart, injury_report
        )
        
        if not candidates:
            return {
                'week': week,
                'action': 'NO_ADDS',
                'message': 'No breakout candidates identified',
                'priority_preserved': True
            }
            
        # Step 2: Filter to likely available players
        available = self.screener.get_value_adds(candidates)
        
        # Step 3: Value each candidate (ΔP(playoffs))
        valued = self.valuator.evaluate_waiver_class(
            available,
            current_roster,
            league_state,
            self.current_priority
        )
        
        # Step 4: Apply I8 threshold logic
        actionable = [c for c in valued if c.get('meets_threshold', False)]
        
        if not actionable:
            return {
                'week': week,
                'action': 'ROLL_PRIORITY',
                'message': 'No candidates meet threshold for current priority position',
                'priority_preserved': True,
                'candidates_screened': len(candidates),
                'top_delta': max(c['delta_playoff_prob'] for c in valued) if valued else 0
            }
            
        # Step 5: Generate claim recommendations
        top_candidate = actionable[0]
        
        decision = {
            'week': week,
            'action': 'CLAIM',
            'player_id': top_candidate['player_id'],
            'drop_player': top_candidate['drop_candidate'],
            'delta_playoff_prob': top_candidate['delta_playoff_prob'],
            'priority_used': self.current_priority if top_candidate['recommendation'].startswith('ADD') else None,
            'new_priority_estimate': self._estimate_new_priority(top_candidate),
            'rationale': top_candidate['recommendation'],
            'all_candidates': [
                {
                    'player_id': c['player_id'],
                    'position': c['position'],
                    'delta': c['delta_playoff_prob'],
                    'rec': c['recommendation']
                }
                for c in actionable[:5]  # Top 5
            ]
        }
        
        # Record history
        self.claim_history.append({
            'week': week,
            'timestamp': datetime.now(),
            'decision': decision
        })
        
        return decision
    
    def _estimate_new_priority(self, claimed_candidate: Dict) -> int:
        """
        Estimate new waiver priority after claim.
        Simplified - assumes worst-case (last priority).
        """
        # In reality, depends on how many teams also claim
        # Conservative estimate: move to back of line
        return 10  # Last priority
    
    def update_priority_position(self, new_position: int):
        """Update current priority position (called after waivers clear)"""
        self.priority_history.append({
            'week': len(self.priority_history) + 1,
            'old_position': self.current_priority,
            'new_position': new_position,
            'timestamp': datetime.now()
        })
        self.current_priority = new_position
        
    def get_priority_strategy_report(self) -> Dict:
        """
        Generate report on waiver priority strategy effectiveness.
        """
        if not self.claim_history:
            return {
                'total_claims': 0,
                'avg_delta_playoffs': 0,
                'strategy': 'No claims made yet'
            }
            
        claims_with_impact = [
            c for c in self.claim_history
            if c['decision'].get('delta_playoff_prob', 0) > 0
        ]
        
        avg_delta = sum(
            c['decision']['delta_playoff_prob'] for c in claims_with_impact
        ) / len(claims_with_impact) if claims_with_impact else 0
        
        top3_spends = sum(
            1 for c in self.claim_history
            if c['decision'].get('priority_used', 99) <= 3
        )
        
        return {
            'total_claims': len(self.claim_history),
            'impactful_claims': len(claims_with_impact),
            'avg_delta_playoffs': avg_delta,
            'top3_priority_spends': top3_spends,
            'current_priority': self.current_priority,
            'strategy_note': f'Averaging {avg_delta:.1f}pp playoff boost per claim'
        }
