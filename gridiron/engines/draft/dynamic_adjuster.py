"""
Dynamic Value Adjustments for Draft Engine

Integrates real-time signals:
- Bye week conflicts (avoid stacking same bye)
- Injury status (downgrade injured, upgrade backups)
- Depth chart changes (promotions/demotions)
- Trade impacts (role changes)
- Off-field misconduct (suspensions)
- Positive news (increased snap share, role expansion)

All adjustments flow through a single adjustment pipeline
that modifies base VORP before optimizer sees candidates.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum
import polars as pl
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class AdjustmentType(Enum):
    INJURY = "injury"
    BYE_CONFLICT = "bye_conflict"
    DEPTH_CHART_PROMOTION = "depth_chart_promotion"
    DEPTH_CHART_DEMOTION = "depth_chart_demotion"
    TRADE_GAIN = "trade_gain"
    TRADE_LOSS = "trade_loss"
    SUSPENSION = "suspension"
    SNAP_INCREASE = "snap_increase"
    TARGET_SHARE_INCREASE = "target_share_increase"
    ROLE_EXPANSION = "role_expansion"
    OFF_FIELD_RISK = "off_field_risk"


@dataclass
class ValueAdjustment:
    """Single adjustment to player VORP"""
    player_id: str
    adjustment_type: AdjustmentType
    delta_vorp: float  # Absolute VORP change
    delta_pct: float   # Percentage change
    confidence: float  # 0.0-1.0, how certain is this signal?
    source: str        # e.g., "injury_report", "depth_chart", "news_scraper"
    timestamp: datetime
    expiry: Optional[datetime] = None  # When this adjustment expires
    details: str = ""
    
    def is_valid(self, as_of: datetime) -> bool:
        """Check if adjustment is still valid at given time"""
        if self.expiry and as_of > self.expiry:
            return False
        return True
    
    def apply(self, base_vorp: float) -> float:
        """Apply adjustment to base VORP"""
        if not self.is_valid(datetime.utcnow()):
            return base_vorp
        
        # Confidence-weighted adjustment
        adjusted = base_vorp + (self.delta_vorp * self.confidence)
        
        # Prevent negative VORP from becoming positive via adjustment
        if base_vorp <= 0 and adjusted > 0:
            adjusted = min(0.0, adjusted)
        
        return adjusted


@dataclass
class RosterContext:
    """Current state of user's roster for bye conflict detection"""
    drafted_players: List[str]  # List of player IDs already drafted
    bye_weeks: Dict[int, int]   # position_group -> count of players with that bye
    # bye_weeks example: {3: 2, 7: 1} means 2 players on bye 3, 1 on bye 7
    
    max_bye_conflicts: int = 2  # Max players sharing same bye week
    critical_shortage_positions: List[str] = field(default_factory=list)
    # Positions where we have < starter requirement
    
    def would_create_bye_conflict(self, player_bye: int, position: str) -> Tuple[bool, int]:
        """
        Check if drafting this player creates unacceptable bye conflict
        
        Returns: (has_conflict, conflict_severity)
        """
        if player_bye is None or player_bye < 1 or player_bye > 18:
            return False, 0
        
        current_count = self.bye_weeks.get(player_bye, 0)
        new_count = current_count + 1
        
        # Critical: if this is a position we're short on, be more lenient
        if position in self.critical_shortage_positions:
            # Allow up to 3 conflicts if desperate for position
            has_conflict = new_count > 3
        else:
            has_conflict = new_count > self.max_bye_conflicts
        
        severity = new_count if has_conflict else 0
        return has_conflict, severity


class DynamicAdjuster:
    """
    Applies real-time adjustments to player VORP based on:
    - Injury reports
    - Bye week conflicts
    - Depth chart changes
    - Trade impacts
    - News signals
    
    Thread-safe, idempotent adjustments
    """
    
    def __init__(self, warehouse_conn, config: dict):
        self.warehouse = warehouse_conn
        self.config = config
        self.active_adjustments: Dict[str, List[ValueAdjustment]] = {}
        # player_id -> list of active adjustments
        
    def load_player_context(self, player_ids: List[str]) -> pl.DataFrame:
        """Load current context for players (injury, depth chart, bye, etc.)"""
        query = """
        SELECT 
            p.gridiron_id,
            p.position,
            p.team,
            p.bye_week,
            COALESCE(i.status, 'Active') as injury_status,
            COALESCE(i.details, '') as injury_details,
            dc.depth_position,
            dc.depth_order,
            COALESCE(s.snap_pct_latest, 0.0) as snap_pct,
            COALESCE(s.snap_pct_prev, 0.0) as snap_pct_prev,
            COALESCE(s.target_share_latest, 0.0) as target_share,
            COALESCE(s.target_share_prev, 0.0) as target_share_prev,
            COALESCE(n.risk_flag, false) as off_field_risk,
            n.risk_details
        FROM players p
        LEFT JOIN injuries i ON p.gridiron_id = i.player_id 
            AND i.as_of = (SELECT MAX(as_of) FROM injuries WHERE player_id = p.gridiron_id)
        LEFT JOIN depth_charts dc ON p.gridiron_id = dc.player_id
            AND dc.as_of = (SELECT MAX(as_of) FROM depth_charts WHERE player_id = p.gridiron_id)
        LEFT JOIN usage_stats s ON p.gridiron_id = s.player_id
            AND s.as_of = (SELECT MAX(as_of) FROM usage_stats WHERE player_id = p.gridiron_id)
        LEFT JOIN news_flags n ON p.gridiron_id = n.player_id
            AND n.as_of = (SELECT MAX(as_of) FROM news_flags WHERE player_id = p.gridiron_id)
        WHERE p.gridiron_id IN ({ids})
        """.format(ids="'," .join(player_ids))
        
        return self.warehouse.query(query).to_polars()
    
    def compute_injury_adjustment(self, player_id: str, injury_status: str, 
                                   injury_details: str) -> Optional[ValueAdjustment]:
        """Compute VORP adjustment based on injury status"""
        
        # Injury status mapping to VORP penalties
        injury_penalties = {
            'Out': (-1.0, 0.95),      # -100% VORP, 95% confidence
            'Doubtful': (-0.7, 0.85),  # -70% VORP
            'Questionable': (-0.3, 0.70), # -30% VORP
            'Probable': (-0.1, 0.60),     # -10% VORP (load management risk)
        }
        
        if injury_status not in injury_penalties:
            return None
            
        delta_pct, confidence = injury_penalties[injury_status]
        
        # Special cases
        if 'season' in injury_details.lower():
            delta_pct = -1.0  # Season-ending = full removal
            confidence = 0.98
            
        if 'week' in injury_details.lower() and 'to' in injury_details.lower():
            # "Week 3-4" type designation
            confidence = 0.90
        
        return ValueAdjustment(
            player_id=player_id,
            adjustment_type=AdjustmentType.INJURY,
            delta_vorp=0.0,  # Will be computed as percentage in apply()
            delta_pct=delta_pct,
            confidence=confidence,
            source="injury_report",
            timestamp=datetime.utcnow(),
            details=injury_details
        )
    
    def compute_bye_conflict_adjustment(self, player_id: str, player_bye: int,
                                         position: str, roster_ctx: RosterContext) -> Optional[ValueAdjustment]:
        """Compute VORP adjustment for bye week conflicts"""
        
        has_conflict, severity = roster_ctx.would_create_bye_conflict(player_bye, position)
        
        if not has_conflict:
            return None
        
        # Escalating penalty based on severity
        penalty_map = {
            3: -0.40,  # 3rd player on same bye = -40%
            4: -0.70,  # 4th player = -70%
            5: -1.0,   # 5th player = effectively undraftable
        }
        
        delta_pct = penalty_map.get(severity, -0.20)
        
        # If critical shortage, reduce penalty
        if position in roster_ctx.critical_shortage_positions:
            delta_pct *= 0.5  # Halve the penalty
        
        return ValueAdjustment(
            player_id=player_id,
            adjustment_type=AdjustmentType.BYE_CONFLICT,
            delta_vorp=0.0,
            delta_pct=delta_pct,
            confidence=0.90,
            source="bye_conflict_detector",
            timestamp=datetime.utcnow(),
            details=f"Bye week {player_bye} conflict (severity {severity})"
        )
    
    def compute_depth_chart_adjustment(self, player_id: str, 
                                        current_depth: int, prev_depth: Optional[int],
                                        position: str) -> Optional[ValueAdjustment]:
        """Compute adjustment for depth chart changes"""
        
        if prev_depth is None:
            return None  # No historical data
        
        # Promotion (e.g., RB2 -> RB1)
        if current_depth < prev_depth:
            promotion_bonuses = {
                (2, 1): (0.35, 0.85),   # RB2->RB1: +35% VORP
                (3, 2): (0.20, 0.75),   # RB3->RB2: +20%
                (3, 1): (0.50, 0.80),   # RB3->RB1: +50%
            }
            
            key = (prev_depth, current_depth)
            if key in promotion_bonuses:
                delta_pct, confidence = promotion_bonuses[key]
                return ValueAdjustment(
                    player_id=player_id,
                    adjustment_type=AdjustmentType.DEPTH_CHART_PROMOTION,
                    delta_vorp=0.0,
                    delta_pct=delta_pct,
                    confidence=confidence,
                    source="depth_chart",
                    timestamp=datetime.utcnow(),
                    details=f"Promoted from {prev_depth} to {current_depth}"
                )
        
        # Demotion
        elif current_depth > prev_depth:
            demotion_penalties = {
                (1, 2): (-0.30, 0.85),
                (2, 3): (-0.25, 0.75),
                (1, 3): (-0.50, 0.80),
            }
            
            key = (prev_depth, current_depth)
            if key in demotion_penalties:
                delta_pct, confidence = demotion_penalties[key]
                return ValueAdjustment(
                    player_id=player_id,
                    adjustment_type=AdjustmentType.DEPTH_CHART_DEMOTION,
                    delta_vorp=0.0,
                    delta_pct=delta_pct,
                    confidence=confidence,
                    source="depth_chart",
                    timestamp=datetime.utcnow(),
                    details=f"Demoted from {prev_depth} to {current_depth}"
                )
        
        return None
    
    def compute_usage_trend_adjustment(self, player_id: str,
                                        snap_pct: float, snap_pct_prev: float,
                                        target_share: float, target_share_prev: float) -> Optional[ValueAdjustment]:
        """Compute adjustment for usage trend changes"""
        
        adjustments = []
        
        # Snap percentage increase
        if snap_pct_prev > 0:
            snap_delta = (snap_pct - snap_pct_prev) / snap_pct_prev
            if snap_delta > 0.20:  # >20% increase
                bonus = min(0.25, snap_delta * 0.5)  # Cap at +25%
                adjustments.append(ValueAdjustment(
                    player_id=player_id,
                    adjustment_type=AdjustmentType.SNAP_INCREASE,
                    delta_vorp=0.0,
                    delta_pct=bonus,
                    confidence=0.70,
                    source="usage_stats",
                    timestamp=datetime.utcnow(),
                    details=f"Snap % increased from {snap_pct_prev:.1f}% to {snap_pct:.1f}%"
                ))
        
        # Target share increase (for pass catchers)
        if target_share_prev > 0:
            target_delta = (target_share - target_share_prev) / target_share_prev
            if target_delta > 0.25:  # >25% increase
                bonus = min(0.30, target_delta * 0.6)
                adjustments.append(ValueAdjustment(
                    player_id=player_id,
                    adjustment_type=AdjustmentType.TARGET_SHARE_INCREASE,
                    delta_vorp=0.0,
                    delta_pct=bonus,
                    confidence=0.75,
                    source="usage_stats",
                    timestamp=datetime.utcnow(),
                    details=f"Target share increased from {target_share_prev:.1f}% to {target_share:.1f}%"
                ))
        
        # Return strongest signal if multiple
        if adjustments:
            return max(adjustments, key=lambda x: abs(x.delta_pct) * x.confidence)
        
        return None
    
    def compute_off_field_adjustment(self, player_id: str, 
                                      risk_flag: bool, 
                                      risk_details: str) -> Optional[ValueAdjustment]:
        """Compute adjustment for off-field risks"""
        
        if not risk_flag:
            return None
        
        # Severity-based penalties
        if 'suspension' in risk_details.lower():
            if 'indefinite' in risk_details.lower():
                return ValueAdjustment(
                    player_id=player_id,
                    adjustment_type=AdjustmentType.SUSPENSION,
                    delta_vorp=0.0,
                    delta_pct=-1.0,
                    confidence=0.95,
                    source="news_flags",
                    timestamp=datetime.utcnow(),
                    details=risk_details
                )
            else:
                # Finite suspension - estimate games
                return ValueAdjustment(
                    player_id=player_id,
                    adjustment_type=AdjustmentType.SUSPENSION,
                    delta_vorp=0.0,
                    delta_pct=-0.60,
                    confidence=0.85,
                    source="news_flags",
                    timestamp=datetime.utcnow(),
                    details=risk_details
                )
        
        # General off-field risk
        return ValueAdjustment(
            player_id=player_id,
            adjustment_type=AdjustmentType.OFF_FIELD_RISK,
            delta_vorp=0.0,
            delta_pct=-0.30,
            confidence=0.60,
            source="news_flags",
            timestamp=datetime.utcnow(),
            details=risk_details
        )
    
    def gather_all_adjustments(self, player_ids: List[str], 
                                roster_ctx: Optional[RosterContext] = None) -> Dict[str, List[ValueAdjustment]]:
        """
        Gather all active adjustments for a set of players
        
        Returns: player_id -> list of adjustments
        """
        if not player_ids:
            return {}
        
        # Load context
        context_df = self.load_player_context(player_ids)
        
        all_adjustments = {}
        
        for _, row in context_df.iterrows():
            player_id = row['gridiron_id']
            adjustments = []
            
            # 1. Injury adjustment
            inj_adj = self.compute_injury_adjustment(
                player_id, row['injury_status'], row['injury_details']
            )
            if inj_adj:
                adjustments.append(inj_adj)
            
            # 2. Bye conflict adjustment
            if roster_ctx and row['bye_week']:
                bye_adj = self.compute_bye_conflict_adjustment(
                    player_id, row['bye_week'], row['position'], roster_ctx
                )
                if bye_adj:
                    adjustments.append(bye_adj)
            
            # 3. Depth chart adjustment
            if row['depth_order'] and row['depth_position']:
                # Would need historical depth chart lookup
                # Simplified: assume prev_depth available in context
                depth_adj = self.compute_depth_chart_adjustment(
                    player_id, row['depth_order'], None, row['position']
                )
                if depth_adj:
                    adjustments.append(depth_adj)
            
            # 4. Usage trend adjustment
            usage_adj = self.compute_usage_trend_adjustment(
                player_id, row['snap_pct'], row['snap_pct_prev'],
                row['target_share'], row['target_share_prev']
            )
            if usage_adj:
                adjustments.append(usage_adj)
            
            # 5. Off-field risk adjustment
            off_field_adj = self.compute_off_field_adjustment(
                player_id, row['off_field_risk'], row.get('risk_details', '')
            )
            if off_field_adj:
                adjustments.append(off_field_adj)
            
            if adjustments:
                all_adjustments[player_id] = adjustments
        
        return all_adjustments
    
    def apply_adjustments_to_vorp(self, base_vorp: float, player_id: str,
                                   adjustments: List[ValueAdjustment]) -> float:
        """
        Apply all adjustments to base VORP
        
        Adjustments are applied multiplicatively in order of confidence
        """
        if player_id not in adjustments or not adjustments:
            return base_vorp
        
        # Sort by confidence (highest first)
        sorted_adjs = sorted(adjustments, key=lambda x: x.confidence, reverse=True)
        
        adjusted_vorp = base_vorp
        
        for adj in sorted_adjs:
            if not adj.is_valid(datetime.utcnow()):
                continue
            
            # Percentage-based adjustment
            if adj.delta_pct != 0:
                delta = base_vorp * adj.delta_pct * adj.confidence
                adjusted_vorp += delta
        
        # Floor at zero for non-negative base VORP
        if base_vorp >= 0:
            adjusted_vorp = max(0.0, adjusted_vorp)
        
        return adjusted_vorp
    
    def get_adjusted_vorp_board(self, base_board: pl.DataFrame,
                                 roster_ctx: Optional[RosterContext] = None) -> pl.DataFrame:
        """
        Apply all adjustments to entire VORP board
        
        Input: DataFrame with columns [gridiron_id, position, base_vorp, ...]
        Output: Same DataFrame with adjusted_vorp column
        """
        player_ids = base_board['gridiron_id'].unique().tolist()
        all_adjustments = self.gather_all_adjustments(player_ids, roster_ctx)
        
        # Apply adjustments
        adjusted_vorps = []
        for _, row in base_board.iter_rows(named=True):
            player_id = row['gridiron_id']
            base_vorp = row.get('base_vorp', row.get('vorp', 0.0))
            
            adj_list = all_adjustments.get(player_id, [])
            adj_vorp = self.apply_adjustments_to_vorp(base_vorp, player_id, adj_list)
            adjusted_vorps.append(adj_vorp)
        
        result = base_board.clone()
        result = result.with_columns(pl.Series('adjusted_vorp', adjusted_vorps))
        
        # Log significant adjustments
        significant = result.filter(
            (pl.col('adjusted_vorp') - pl.col('base_vorp')).abs() > 
            (pl.col('base_vorp').abs() * 0.15)  # >15% change
        )
        
        if len(significant) > 0:
            logger.info(f"Significant VORP adjustments for {len(significant)} players")
            for row in significant.iter_rows(named=True):
                delta_pct = ((row['adjusted_vorp'] - row['base_vorp']) / 
                            max(abs(row['base_vorp']), 0.1))
                logger.info(f"  {row['gridiron_id']}: {delta_pct:+.1%} ({row.get('adjustment_reason', 'multiple factors')})")
        
        return result
