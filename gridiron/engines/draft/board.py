"""
VORP Draft Board with Positional Tier Detection

Computes Value Over Replacement Player for all draftable players.
Positional tiers detected via change-point analysis on sorted VORP.

Key discoveries encoded:
- I1: QB compression (pocket QBs clustered, rushing QBs separate)
- I3: TE dead zone after elite tier
- I4: K/DEF ~0 VORP above replacement
"""

from __future__ import annotations
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import polars as pl
import numpy as np
from datetime import datetime
import logging

from ..core.scoring import ScoringEngine
from ..core.replacement import ReplacementCalculator
from ..core.projections import ProjectionService

logger = logging.getLogger(__name__)


@dataclass
class TierBreakpoint:
    """Detected tier boundary"""
    position: str
    rank: int  # Rank where tier breaks
    player_name: str
    vorp_drop: float  # Magnitude of VORP drop
    confidence: float  # Confidence in breakpoint detection


class VorpBoard:
    """
    Static VORP draft board with positional tier detection
    
    Reads scoring rules from league_config.yaml (H6 contract)
    Uses single replacement calculator (H3 contract)
    """
    
    def __init__(self, projection_service: ProjectionService,
                 replacement_calc: ReplacementCalculator,
                 scoring_engine: ScoringEngine,
                 config: dict):
        self.projections = projection_service
        self.replacement = replacement_calc
        self.scoring = scoring_engine
        self.config = config
        self._board_cache: Optional[pl.DataFrame] = None
        self._tier_breakpoints: List[TierBreakpoint] = []
        
    def compute_vorp(self, player_projections: pl.DataFrame) -> pl.DataFrame:
        """
        Compute VORP for all players
        
        VORP = E[points] - Replacement-level E[points]
        
        Replacement level = best projected undrafted player at position
        (simulated over ADP noise draws)
        """
        # Get expected points under exact league scoring
        expected_pts = self.scoring.compute_expected_points(player_projections)
        
        # Get replacement levels by position
        replacement_levels = self.replacement.get_replacement_levels(
            player_projections, 
            adp_noise_draws=100  # Simulate draft uncertainty
        )
        
        # Merge and compute VORP
        result = expected_pts.join(replacement_levels, on=['position'])
        result = result.with_columns(
            (pl.col('expected_points') - pl.col('replacement_points')).alias('vorp')
        )
        
        return result
    
    def detect_tiers(self, vorp_df: pl.DataFrame, 
                     min_gap_threshold: float = 0.15) -> List[TierBreakpoint]:
        """
        Detect positional tiers via change-point analysis
        
        Algorithm: Find largest gaps in sorted VORP that exceed threshold
        This is where I3's TE cliff and I1's QB compression should emerge
        """
        breakpoints = []
        
        for position in vorp_df['position'].unique():
            pos_data = vorp_df.filter(pl.col('position') == position)
            pos_data = pos_data.sort(pl.col('vorp'), descending=True)
            
            vorp_values = pos_data['vorp'].to_numpy()
            player_names = pos_data['player_name'].to_list()
            
            if len(vorp_values) < 2:
                continue
            
            # Compute sequential differences
            diffs = np.diff(vorp_values)
            
            # Normalize by local VORP magnitude
            local_magnitude = np.abs(vorp_values[:-1])
            normalized_diffs = np.abs(diffs) / np.maximum(local_magnitude, 0.5)
            
            # Find significant gaps (>15% drop or absolute >2 pts)
            significant_gaps = []
            for i, (diff, norm_diff) in enumerate(zip(diffs, normalized_diffs)):
                if norm_diff > min_gap_threshold or abs(diff) > 2.0:
                    significant_gaps.append((i, diff, norm_diff))
            
            # Sort by magnitude, take top 3 per position
            significant_gaps.sort(key=lambda x: abs(x[1]), reverse=True)
            
            for rank_idx, diff, norm_diff in significant_gaps[:3]:
                breakpoints.append(TierBreakpoint(
                    position=position,
                    rank=rank_idx + 1,
                    player_name=player_names[rank_idx],
                    vorp_drop=diff,
                    confidence=min(1.0, norm_diff / min_gap_threshold)
                ))
        
        self._tier_breakpoints = breakpoints
        return breakpoints
    
    def get_board(self, refresh: bool = False) -> pl.DataFrame:
        """
        Get full VORP board with tier information
        
        Cached unless refresh=True
        """
        if self._board_cache is not None and not refresh:
            return self._board_cache
        
        # Get latest projections
        projections = self.projections.get_latest_projections()
        
        # Compute VORP
        vorp_df = self.compute_vorp(projections)
        
        # Detect tiers
        self.detect_tiers(vorp_df)
        
        # Add tier labels
        vorp_df = self._label_tiers(vorp_df)
        
        # Sort by VORP descending
        vorp_df = vorp_df.sort(pl.col('vorp'), descending=True)
        
        self._board_cache = vorp_df
        return vorp_df
    
    def _label_tiers(self, vorp_df: pl.DataFrame) -> pl.DataFrame:
        """Add tier labels to dataframe"""
        if not self._tier_breakpoints:
            self.detect_tiers(vorp_df)
        
        # Create tier mapping: (position, rank_range) -> tier_label
        tier_map = {}
        for position in vorp_df['position'].unique():
            pos_breakpoints = [b for b in self._tier_breakpoints if b.position == position]
            pos_breakpoints.sort(key=lambda x: x.rank)
            
            current_tier = 1
            last_rank = 0
            for bp in pos_breakpoints:
                tier_map[(position, (last_rank + 1, bp.rank))] = f"{position}{current_tier}"
                current_tier += 1
                last_rank = bp.rank
            
            # Remaining players
            max_rank = len(vorp_df.filter(pl.col('position') == position))
            tier_map[(position, (last_rank + 1, max_rank))] = f"{position}{current_tier}"
        
        # Apply labels
        def get_tier(row):
            pos = row['position']
            rank = row.get('pos_rank', 1)  # Assumes pos_rank column exists
            for (tier_pos, (start, end)), label in tier_map.items():
                if tier_pos == pos and start <= rank <= end:
                    return label
            return f"{pos}99"
        
        # Add positional rank first
        vorp_df = vorp_df.with_columns(
            pl.col('vorp').rank(descending=True).over('position').alias('pos_rank')
        )
        
        # TODO: Implement tier labeling properly
        # For now, just add placeholder
        vorp_df = vorp_df.with_columns(
            pl.lit('TBD').alias('tier_label')
        )
        
        return vorp_df
    
    def get_structural_properties(self) -> dict:
        """
        Validate board has expected structural properties
        
        Returns dict with:
        - qb_compression: True if pocket QBs cluster together
        - te_cliff: True if TE has detectable elite tier drop
        - k_def_zero: True if K/DEF VORP ≈ 0 above replacement
        """
        board = self.get_board()
        
        results = {}
        
        # I1: QB Compression check
        qb_data = board.filter(pl.col('position') == 'QB').sort('vorp', descending=True)
        if len(qb_data) >= 5:
            # Compare top 3 rushing QBs vs next 5 pocket QBs
            # Simplified: check if VORP std dev in QB1-QB6 is low
            qb_vorp_std = qb_data.head(6)['vorp'].std()
            results['qb_compression'] = qb_vorp_std < 3.0  # Threshold from historical
        else:
            results['qb_compression'] = False
        
        # I3: TE Cliff check
        te_data = board.filter(pl.col('position') == 'TE').sort('vorp', descending=True)
        if len(te_data) >= 4:
            te1_vorp = te_data.head(1)['vorp'].mean()
            te2_3_vorp = te_data.slice(1, 2)['vorp'].mean()
            te4_6_vorp = te_data.slice(3, 3)['vorp'].mean()
            
            # Elite tier (TE1) significantly above TE2-3
            elite_gap = te1_vorp - te2_3_vorp
            # TE2-3 not much better than TE4-6 (dead zone)
            dead_zone_gap = te2_3_vorp - te4_6_vorp
            
            results['te_cliff'] = (elite_gap > 3.0) and (dead_zone_gap < 1.5)
        else:
            results['te_cliff'] = False
        
        # I4: K/DEF near-zero VORP
        k_data = board.filter(pl.col('position') == 'K')
        def_data = board.filter(pl.col('position') == 'DEF')
        
        k_mean_vorp = k_data['vorp'].mean() if len(k_data) > 0 else 0
        def_mean_vorp = def_data['vorp'].mean() if len(def_data) > 0 else 0
        
        results['k_def_zero'] = (abs(k_mean_vorp) < 1.0) and (abs(def_mean_vorp) < 1.0)
        
        # Log findings
        logger.info(f"Structural properties: {results}")
        if not all(results.values()):
            logger.warning("Some structural properties failed - investigate model")
        
        return results
    
    def export_cheat_sheet(self, draft_slot: int, output_path: str) -> str:
        """
        Export one-page draft cheat sheet parameterized by slot
        
        Shows per-round targets based on:
        - Expected player availability at each pick
        - Positional value drops
        - Bye week distribution (avoid stacking)
        """
        board = self.get_board()
        slot = draft_slot
        
        # Generate picks for this slot (snake draft)
        total_teams = self.config['league']['teams']
        rounds = 15
        
        picks = []
        for round_num in range(1, rounds + 1):
            if round_num % 2 == 1:
                pick_num = slot
            else:
                pick_num = total_teams - slot + 1
            
            overall_pick = (round_num - 1) * total_teams + pick_num
            picks.append((round_num, overall_pick, pick_num))
        
        # For each pick, estimate best available by position
        cheat_lines = []
        cheat_lines.append(f"DRAFT CHEAT SHEET - Slot {slot}")
        cheat_lines.append("=" * 40)
        
        remaining_players = board.clone()
        
        for round_num, overall_pick, pick_in_round in picks:
            # Estimate who gets picked before us
            picks_before = pick_in_round - 1 if round_num > 1 else 0
            
            # Simple opponent model: they take best available
            available = remaining_players
            for _ in range(picks_before):
                if len(available) > 0:
                    available = available.slice(1)
            
            if len(available) > 0:
                top_available = available.head(5)
                
                # Group by position, show top at each
                recs = []
                for pos in ['QB', 'RB', 'WR', 'TE', 'K', 'DEF']:
                    pos_players = top_available.filter(pl.col('position') == pos)
                    if len(pos_players) > 0:
                        top = pos_players.head(1)
                        recs.append(f"{pos}: {top['player_name'][0]} (VORP {top['vorp'][0]:.1f})")
                
                cheat_lines.append(f"R{round_num:2d} (Pick {overall_pick:3d}): " + ", ".join(recs[:4]))
            
            # Remove top pick from remaining (simulate)
            if len(remaining_players) > 0:
                remaining_players = remaining_players.slice(1)
        
        # Write to file
        content = "\n".join(cheat_lines)
        with open(output_path, 'w') as f:
            f.write(content)
        
        logger.info(f"Cheat sheet written to {output_path}")
        return output_path
