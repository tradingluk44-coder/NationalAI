"""
Live Draft Tracker - Real-time Draft State Management

Tracks:
- All picks made (user + opponents)
- Current roster composition
- Bye week distribution
- Positional runs detection
- Time between picks (pace monitoring)

Integrates with optimizer for real-time recommendations.
"""

from __future__ import annotations
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import logging

from .optimizer import DraftOptimizer, DraftState, PickRecommendation
from .board import VorpBoard
from .dynamic_adjuster import DynamicAdjuster

logger = logging.getLogger(__name__)


@dataclass
class DraftPick:
    """Single draft pick"""
    round_num: int
    pick_number: int  # Overall pick number
    player_id: str
    player_name: str
    position: str
    team: str
    drafted_by_user: bool
    timestamp: datetime
    time_since_last_pick: Optional[float] = None  # Seconds


class LiveDraftTracker:
    """
    Real-time draft state tracker
    
    Maintains complete draft history and provides:
    - Current roster composition
    - Bye week distribution analysis
    - Positional run detection
    - Integration with optimizer for live recommendations
    """
    
    def __init__(self, user_slot: int, total_teams: int,
                 optimizer: DraftOptimizer, config: dict):
        self.user_slot = user_slot
        self.total_teams = total_teams
        self.optimizer = optimizer
        self.config = config
        
        self.picks: List[DraftPick] = []
        self.user_drafted: List[str] = []  # Player IDs
        self.opponent_drafted: List[str] = []  # Player IDs
        self.roster_composition: Dict[str, int] = {}
        self.bye_week_counts: Dict[int, int] = {}
        
        self.last_pick_time: Optional[datetime] = None
        self.current_round = 1
        self.next_pick_overall: int = user_slot  # First pick
        
        # Starter requirements from config
        self.starter_reqs = config['league']['roster']['starters']
        self.bench_slots = config['league']['roster']['bench']
    
    def record_pick(self, round_num: int, pick_number: int, 
                    player_id: str, player_name: str, position: str,
                    team: str, drafted_by_user: bool) -> DraftPick:
        """
        Record a draft pick (user or opponent)
        
        Updates internal state: roster composition, bye weeks, etc.
        """
        # Calculate time since last pick
        now = datetime.utcnow()
        time_delta = None
        if self.last_pick_time:
            time_delta = (now - self.last_pick_time).total_seconds()
        
        pick = DraftPick(
            round_num=round_num,
            pick_number=pick_number,
            player_id=player_id,
            player_name=player_name,
            position=position,
            team=team,
            drafted_by_user=drafted_by_user,
            timestamp=now,
            time_since_last_pick=time_delta
        )
        
        self.picks.append(pick)
        self.last_pick_time = now
        
        # Update tracking
        if drafted_by_user:
            self.user_drafted.append(player_id)
            self._update_roster_composition(position)
        else:
            self.opponent_drafted.append(player_id)
        
        # Update current round and next pick
        self.current_round = round_num
        self._update_next_pick()
        
        logger.info(f"Pick recorded: R{round_num} P{pick_number} - {player_name} ({position})")
        
        return pick
    
    def _update_roster_composition(self, position: str):
        """Update roster composition after drafting player"""
        self.roster_composition[position] = self.roster_composition.get(position, 0) + 1
    
    def _update_next_pick(self):
        """Calculate overall pick number for user's next selection"""
        # Snake draft logic
        if self.current_round % 2 == 1:
            # Odd rounds: pick order 1, 2, 3, ..., N
            self.next_pick_overall = (self.current_round - 1) * self.total_teams + self.user_slot
        else:
            # Even rounds: pick order N, N-1, ..., 1
            self.next_pick_overall = self.current_round * self.total_teams - self.user_slot + 1
    
    def get_draft_state(self) -> DraftState:
        """Convert current state to DraftState for optimizer"""
        return DraftState(
            user_slot=self.user_slot,
            current_pick=self.next_pick_overall,
            round_num=self.current_round,
            drafted_players=self.user_drafted.copy(),
            roster_composition=self.roster_composition.copy(),
            bye_week_counts=self.bye_week_counts.copy(),
            opponent_picks=self.opponent_drafted.copy()
        )
    
    def get_recommendation(self, adp_data) -> PickRecommendation:
        """Get optimizer recommendation for current pick"""
        draft_state = self.get_draft_state()
        return self.optimizer.recommend_pick(draft_state, adp_data)
    
    def analyze_bye_distribution(self) -> dict:
        """
        Analyze bye week distribution of current roster
        
        Returns dict with:
        - bye_week_counts: {week: count}
        - max_conflict: week with most players
        - conflict_severity: how problematic is the worst week
        - recommendations: which bye weeks to target/avoid
        """
        # Load bye weeks for drafted players
        # (Would query from database - simplified here)
        
        bye_counts = self.bye_week_counts
        
        if not bye_counts:
            return {
                'bye_week_counts': {},
                'max_conflict': None,
                'conflict_severity': 0,
                'recommendations': ['No bye data yet']
            }
        
        max_week = max(bye_counts, key=bye_counts.get)
        max_count = bye_counts[max_week]
        
        # Severity: >2 players on same bye is problematic
        severity = max(0, max_count - 2)
        
        # Recommendations
        recs = []
        if severity > 0:
            recs.append(f"Avoid players on bye week {max_week} - already have {max_count}")
        
        # Find empty bye weeks
        all_weeks = set(range(1, 19))  # Weeks 1-18
        taken_weeks = set(bye_counts.keys())
        empty_weeks = all_weeks - taken_weeks
        
        if empty_weeks:
            recs.append(f"Target players on bye weeks: {sorted(empty_weeks)[:3]}")
        
        return {
            'bye_week_counts': bye_counts,
            'max_conflict': max_week,
            'conflict_severity': severity,
            'recommendations': recs
        }
    
    def detect_positional_runs(self, window: int = 6) -> dict:
        """
        Detect positional runs in recent picks
        
        Returns dict with:
        - position_counts: {position: count} in recent window
        - active_runs: positions being drafted heavily
        - recommendations: whether to join/fade runs
        """
        if len(self.picks) < window:
            recent_picks = self.picks
        else:
            recent_picks = self.picks[-window:]
        
        # Count positions
        pos_counts = {}
        for pick in recent_picks:
            pos = pick.position
            pos_counts[pos] = pos_counts.get(pos, 0) + 1
        
        # Identify active runs (>2 in window)
        active_runs = [pos for pos, count in pos_counts.items() if count >= 3]
        
        # Recommendations
        recs = []
        for pos in active_runs:
            # If we need this position, consider joining run
            current_need = self.starter_reqs.get(pos, 0) - self.roster_composition.get(pos, 0)
            if current_need > 0:
                recs.append(f"Consider joining {pos} run - you still need {current_need}")
            else:
                recs.append(f"Fading {pos} run - value may emerge later")
        
        return {
            'position_counts': pos_counts,
            'active_runs': active_runs,
            'recommendations': recs
        }
    
    def get_roster_summary(self) -> dict:
        """Get current roster summary"""
        total_drafted = len(self.user_drafted)
        starters_filled = sum(
            min(self.roster_composition.get(pos, 0), req)
            for pos, req in self.starter_reqs.items()
        )
        bench_filled = total_drafted - starters_filled
        
        return {
            'total_drafted': total_drafted,
            'starters_filled': starters_filled,
            'bench_filled': bench_filled,
            'positions': self.roster_composition.copy(),
            'current_round': self.current_round,
            'next_pick': self.next_pick_overall
        }
    
    def export_draft_log(self, output_path: str) -> str:
        """Export complete draft log to file"""
        lines = []
        lines.append(f"DRAFT LOG - User Slot {self.user_slot}")
        lines.append("=" * 50)
        
        current_round = 0
        for pick in sorted(self.picks, key=lambda p: (p.round_num, p.pick_number)):
            if pick.round_num != current_round:
                current_round = pick.round_num
                lines.append(f"\nRound {current_round}")
                lines.append("-" * 30)
            
            marker = "*" if pick.drafted_by_user else " "
            time_str = f" ({pick.time_since_last_pick:.0f}s)" if pick.time_since_last_pick else ""
            
            lines.append(
                f"{marker} Pick {pick.pick_number:3d}: {pick.player_name:25s} ({pick.position:2s}) {time_str}"
            )
        
        # Summary
        lines.append("\n" + "=" * 50)
        lines.append("ROSTER SUMMARY")
        summary = self.get_roster_summary()
        lines.append(f"Total Players: {summary['total_drafted']}")
        lines.append(f"Starters: {summary['starters_filled']}/{sum(self.starter_reqs.values())}")
        lines.append(f"Bench: {summary['bench_filled']}/{self.bench_slots}")
        lines.append("\nBy Position:")
        for pos, count in sorted(summary['positions'].items()):
            req = self.starter_reqs.get(pos, 0)
            lines.append(f"  {pos}: {count} (need {req})")
        
        content = "\n".join(lines)
        with open(output_path, 'w') as f:
            f.write(content)
        
        logger.info(f"Draft log exported to {output_path}")
        return output_path
    
    def update_bye_weeks(self, player_bye_map: Dict[str, int]):
        """Update bye week counts from player map"""
        for player_id in self.user_drafted:
            if player_id in player_bye_map:
                bye_week = player_bye_map[player_id]
                self.bye_week_counts[bye_week] = self.bye_week_counts.get(bye_week, 0) + 1
