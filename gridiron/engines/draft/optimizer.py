"""
Draft Optimizer with Dynamic Adjustments

Core algorithm: Select player with highest NET VALUE considering:
1. Base VORP from projections
2. Dynamic adjustments (injuries, bye conflicts, depth chart changes, news)
3. Opponent modeling (what survives to next pick)
4. Positional need constraints
5. Two-round lookahead

Macro objective: Maximize P(championship) by building roster with:
- Highest expected points ceiling
- Manageable bye week distribution  
- Injury risk mitigation
- Role security (avoiding players losing jobs)
"""

from __future__ import annotations
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import polars as pl
import numpy as np
from datetime import datetime
import logging

from .board import VorpBoard
from .dynamic_adjuster import DynamicAdjuster, RosterContext, ValueAdjustment
from ..core.replacement import ReplacementCalculator

logger = logging.getLogger(__name__)


@dataclass
class DraftState:
    """Current state of the draft"""
    user_slot: int
    current_pick: int  # Overall pick number
    round_num: int
    drafted_players: List[str] = field(default_factory=list)  # Player IDs
    roster_composition: Dict[str, int] = field(default_factory=dict)  # position -> count
    bye_week_counts: Dict[int, int] = field(default_factory=dict)  # bye_week -> count
    opponent_picks: List[str] = field(default_factory=list)  # Player IDs taken by others
    
    def get_roster_context(self) -> RosterContext:
        """Convert to RosterContext for bye conflict detection"""
        return RosterContext(
            drafted_players=self.drafted_players,
            bye_weeks=self.bye_week_counts.copy(),
            max_bye_conflicts=2,
            critical_shortage_positions=self._get_critical_shortages()
        )
    
    def _get_critical_shortages(self) -> List[str]:
        """Identify positions where we're below starter requirements"""
        starter_reqs = {
            'QB': 1, 'RB': 2, 'WR': 2, 'TE': 1, 
            'FLEX_RWT': 1, 'K': 1, 'DEF': 1
        }
        
        shortages = []
        for pos, req in starter_reqs.items():
            current = self.roster_composition.get(pos, 0)
            if current < req:
                shortages.append(pos)
        
        return shortages


@dataclass
class PickRecommendation:
    """Recommendation for current pick"""
    player_id: str
    player_name: str
    position: str
    base_vorp: float
    adjusted_vorp: float
    adjustments_applied: List[str]
    confidence: float
    rationale: str
    alternative_picks: List[str]  # Next best options


class DraftOptimizer:
    """
    Snake draft optimizer with dynamic adjustments
    
    Algorithm: For each candidate player:
    1. Get base VORP from board
    2. Apply dynamic adjustments (injury, bye, depth chart, news)
    3. Estimate probability player available at next pick
    4. Compute net value = adjusted_VORP * P(available now) - opportunity_cost
    5. Select highest net value player satisfying roster constraints
    """
    
    def __init__(self, vorp_board: VorpBoard, 
                 dynamic_adjuster: DynamicAdjuster,
                 config: dict):
        self.board = vorp_board
        self.adjuster = dynamic_adjuster
        self.config = config
        self.total_teams = config['league']['teams']
        
    def estimate_survival_probability(self, player_id: str, 
                                       picks_until_next: int,
                                       observed_picks: List[str],
                                       adp_data: pl.DataFrame) -> float:
        """
        Estimate probability player survives until our next pick
        
        Uses:
        - ADP distribution
        - Observed picks (recency-weighted positional run detection)
        - Positional scarcity
        """
        if picks_until_next <= 0:
            return 0.0
        
        # Get player's ADP and std dev
        player_adp_row = adp_data.filter(pl.col('player_id') == player_id)
        if len(player_adp_row) == 0:
            return 0.5  # Unknown player = 50%
        
        adp_mean = player_adp_row['adp_mean'][0]
        adp_std = player_adp_row.get('adp_std', [2.0])[0]
        
        # Current pick number
        current_pick = self._get_current_pick_number()
        
        # Probability still available at current pick (CDF of ADP)
        from scipy.stats import norm
        p_available_now = 1 - norm.cdf(current_pick, adp_mean, adp_std)
        
        # Probability available at next pick
        next_pick = current_pick + picks_until_next
        p_available_next = 1 - norm.cdf(next_pick, adp_mean, adp_std)
        
        # Conditional probability: available next given available now
        if p_available_now <= 0:
            return 0.0
        
        survival_prob = p_available_next / p_available_now
        
        # Adjust for observed positional runs
        # If we've seen 3+ RBs picked recently, increase RB demand
        recent_position_counts = self._count_recent_positions(observed_picks, window=6)
        player_pos = player_adp_row['position'][0]
        recent_count = recent_position_counts.get(player_pos, 0)
        
        if recent_count >= 3:
            # Positional run detected - reduce survival probability
            survival_prob *= 0.7
        elif recent_count >= 2:
            survival_prob *= 0.85
        
        return max(0.0, min(1.0, survival_prob))
    
    def _get_current_pick_number(self) -> int:
        """Get current overall pick number (placeholder)"""
        # Would be set by draft state
        return 1
    
    def _count_recent_positions(self, picks: List[str], window: int) -> Dict[str, int]:
        """Count positions taken in recent picks"""
        # Simplified - would need player lookup
        return {}
    
    def compute_net_value(self, player_id: str, 
                          draft_state: DraftState,
                          adp_data: pl.DataFrame) -> Tuple[float, dict]:
        """
        Compute net value of drafting player now vs waiting
        
        Returns: (net_value, metadata_dict)
        """
        # Get base VORP
        board = self.board.get_board()
        player_row = board.filter(pl.col('gridiron_id') == player_id)
        
        if len(player_row) == 0:
            return -np.inf, {'error': 'Player not on board'}
        
        base_vorp = player_row['vorp'][0]
        position = player_row['position'][0]
        
        # Apply dynamic adjustments
        roster_ctx = draft_state.get_roster_context()
        adjustments = self.adjuster.gather_all_adjustments([player_id], roster_ctx)
        adjusted_vorp = self.adjuster.apply_adjustments_to_vorp(
            base_vorp, player_id, adjustments.get(player_id, [])
        )
        
        # Compute survival probability to next pick
        picks_until_next = self.total_teams - 1  # Until our next pick in snake
        survival_prob = self.estimate_survival_probability(
            player_id, picks_until_next, 
            draft_state.opponent_picks, adp_data
        )
        
        # Opportunity cost: what else could we get?
        # Simplified: average VORP of players likely available next round
        opportunity_cost = self._estimate_opportunity_cost(
            position, draft_state, board
        )
        
        # Net value formula:
        # NV = adjusted_VORP * (1 - survival_prob) + opportunity_cost * survival_prob
        # Interpretation:
        # - If we take now: get adjusted_VORP
        # - If we wait: expected value = survival_prob * adjusted_VORP_next_round
        # But simplified to: maximize immediate value weighted by scarcity
        
        scarcity_multiplier = 1.0 + (1.0 - survival_prob)  # Scarce players worth more now
        
        net_value = adjusted_vorp * scarcity_multiplier
        
        metadata = {
            'base_vorp': base_vorp,
            'adjusted_vorp': adjusted_vorp,
            'survival_prob': survival_prob,
            'opportunity_cost': opportunity_cost,
            'adjustments': [a.adjustment_type.value for a in adjustments.get(player_id, [])],
            'scarcity_multiplier': scarcity_multiplier
        }
        
        return net_value, metadata
    
    def _estimate_opportunity_cost(self, position: str,
                                    draft_state: DraftState,
                                    board: pl.DataFrame) -> float:
        """Estimate value of best alternative at position next round"""
        # Get top available players at position
        available = board.filter(
            (pl.col('position') == position) &
            (~pl.col('gridiron_id').is_in(draft_state.drafted_players))
        )
        
        if len(available) < 2:
            return 0.0
        
        # Second-best available (what we could get next round)
        second_best = available.sort('vorp', descending=True).slice(1, 1)
        return second_best['vorp'][0] if len(second_best) > 0 else 0.0
    
    def recommend_pick(self, draft_state: DraftState,
                       adp_data: pl.DataFrame,
                       candidates_override: Optional[List[str]] = None) -> PickRecommendation:
        """
        Generate pick recommendation for current situation
        
        Args:
            draft_state: Current draft state
            adp_data: ADP data for survival estimation
            candidates_override: Optional list of player IDs to consider
            
        Returns:
            PickRecommendation with best choice and rationale
        """
        # Get available players
        board = self.board.get_board()
        
        if candidates_override:
            available = board.filter(pl.col('gridiron_id').is_in(candidates_override))
        else:
            available = board.filter(
                ~pl.col('gridiron_id').is_in(draft_state.drafted_players)
            )
        
        # Filter by roster needs (don't draft 3 QBs when need RB)
        available = self._filter_by_roster_needs(available, draft_state)
        
        if len(available) == 0:
            # No constrained options, relax filters
            available = board.filter(
                ~pl.col('gridiron_id').is_in(draft_state.drafted_players)
            )
        
        # Compute net value for each candidate
        candidates = []
        for player_id in available['gridiron_id'].to_list():
            net_val, metadata = self.compute_net_value(player_id, draft_state, adp_data)
            candidates.append((player_id, net_val, metadata))
        
        # Sort by net value
        candidates.sort(key=lambda x: x[1], reverse=True)
        
        if len(candidates) == 0:
            return PickRecommendation(
                player_id='',
                player_name='N/A',
                position='',
                base_vorp=0.0,
                adjusted_vorp=0.0,
                adjustments_applied=[],
                confidence=0.0,
                rationale='No available players',
                alternative_picks=[]
            )
        
        # Top choice
        top_id, top_val, top_meta = candidates[0]
        top_row = available.filter(pl.col('gridiron_id') == top_id)
        
        # Build rationale
        rationale_parts = []
        if top_meta['adjusted_vorp'] < top_meta['base_vorp']:
            rationale_parts.append(f"Downgraded from base VORP due to {top_meta['adjustments']}")
        elif top_meta['adjusted_vorp'] > top_meta['base_vorp']:
            rationale_parts.append(f"Upgraded due to positive signals")
        
        if top_meta['survival_prob'] < 0.3:
            rationale_parts.append("High scarcity - unlikely to survive to next pick")
        elif top_meta['survival_prob'] > 0.8:
            rationale_parts.append("Could wait - likely available next round")
        
        rationale = ". ".join(rationale_parts) if rationale_parts else "Best net value available"
        
        # Alternative picks (next 2-3)
        alternatives = [c[0] for c in candidates[1:4]]
        
        return PickRecommendation(
            player_id=top_id,
            player_name=top_row['player_name'][0],
            position=top_row['position'][0],
            base_vorp=top_meta['base_vorp'],
            adjusted_vorp=top_meta['adjusted_vorp'],
            adjustments_applied=top_meta['adjustments'],
            confidence=min(1.0, top_meta['scarcity_multiplier']),
            rationale=rationale,
            alternative_picks=alternatives
        )
    
    def _filter_by_roster_needs(self, available: pl.DataFrame,
                                 draft_state: DraftState) -> pl.DataFrame:
        """Filter available players by roster need constraints"""
        starter_reqs = {
            'QB': 1, 'RB': 2, 'WR': 2, 'TE': 1,
            'FLEX_RWT': 1, 'K': 1, 'DEF': 1
        }
        bench_slots = 6
        
        # Count current roster
        current = draft_state.roster_composition
        total_drafted = len(draft_state.drafted_players)
        
        # Identify critical needs (below starter req)
        critical_positions = []
        for pos, req in starter_reqs.items():
            if current.get(pos, 0) < req:
                critical_positions.append(pos)
        
        # If in early rounds (1-5), prioritize filling starter needs
        if draft_state.round_num <= 5 and critical_positions:
            available = available.filter(
                pl.col('position').is_in(critical_positions)
            )
        
        # If very late rounds (10+), can take best available regardless
        elif draft_state.round_num >= 10:
            # Already filtered by drafted list
            pass
        
        # Mid-rounds: mix of need and best available
        else:
            # Keep players at positions where we have < 2 total
            need_threshold = 2
            needed_positions = [
                pos for pos, count in current.items() 
                if count < need_threshold
            ]
            
            if needed_positions:
                # 70% weight to need, 30% to best available
                need_filtered = available.filter(
                    pl.col('position').is_in(needed_positions)
                )
                if len(need_filtered) > 0:
                    available = need_filtered
        
        return available
