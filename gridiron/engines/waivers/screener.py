"""
engines/waivers/screener.py
Identifies waiver candidates via usage deltas (snaps/routes/targets).
Detects breakout signals BEFORE box-score points explode.
"""
import polars as pl
import numpy as np
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

class WaiverScreener:
    """
    Screens for waiver wire targets using leading indicators:
    - Snap share increases
    - Route participation jumps
    - Target share growth
    - Depth chart promotions
    - Red zone usage upticks
    """
    
    def __init__(self, config_path: str = "league_config.yaml"):
        self.config_path = config_path
        # Thresholds for "significant" changes
        self.snap_delta_threshold = 0.15  # 15pp increase
        self.route_delta_threshold = 0.20  # 20pp increase
        self.target_delta_threshold = 0.08  # 8pp increase
        
    def calculate_usage_deltas(self,
                              current_week: pl.DataFrame,
                              historical_weeks: pl.DataFrame,
                              lookback: int = 3) -> pl.DataFrame:
        """
        Calculate week-over-week changes in usage metrics.
        
        Args:
            current_week: Current week's snap/route/target data
            historical_weeks: Historical data for trend calculation
            lookback: Number of weeks to average for baseline
            
        Returns:
            DataFrame with delta calculations
        """
        # Calculate historical averages (last `lookback` weeks)
        recent_history = historical_weeks.filter(
            pl.col('week') >= historical_weeks['week'].max() - lookback + 1
        )
        
        baseline = recent_history.group_by('player_id').agg([
            pl.col('snap_share').mean().alias('baseline_snap'),
            pl.col('route_share').mean().alias('baseline_route'),
            pl.col('target_share').mean().alias('baseline_target'),
            pl.col('red_zone_share').mean().alias('baseline_rz')
        ])
        
        # Join with current week
        merged = current_week.join(baseline, on='player_id', how='left')
        
        # Calculate deltas
        deltas = merged.with_columns([
            (pl.col('snap_share') - pl.col('baseline_snap')).alias('snap_delta'),
            (pl.col('route_share') - pl.col('baseline_route')).alias('route_delta'),
            (pl.col('target_share') - pl.col('baseline_target')).alias('target_delta'),
            (pl.col('red_zone_share') - pl.col('baseline_rz')).alias('rz_delta')
        ])
        
        return deltas
    
    def identify_breakout_candidates(self,
                                    usage_data: pl.DataFrame,
                                    depth_chart: pl.DataFrame,
                                    injury_report: pl.DataFrame) -> List[Dict]:
        """
        Identify players with significant usage increases.
        
        Returns list of candidates sorted by breakout signal strength.
        """
        candidates = []
        
        for row in usage_data.iter_rows(named=True):
            player_id = row['player_id']
            
            # Skip if already injured
            injury_status = injury_report.filter(
                pl.col('player_id') == player_id
            )
            if len(injury_status) > 0:
                status = injury_status['status'][0]
                if status in ['OUT', 'DOUBTFUL']:
                    continue
                    
            # Check for depth chart promotion
            dc_row = depth_chart.filter(pl.col('player_id') == player_id)
            is_starter = len(dc_row) > 0 and dc_row['depth_position'][0] == 1
            
            # Calculate breakout score
            breakout_signals = []
            
            # Snap surge
            if row.get('snap_delta', 0) > self.snap_delta_threshold:
                breakout_signals.append(('snap_surge', row['snap_delta']))
                
            # Route participation jump
            if row.get('route_delta', 0) > self.route_delta_threshold:
                breakout_signals.append(('route_jump', row['route_delta']))
                
            # Target share growth
            if row.get('target_delta', 0) > self.target_delta_threshold:
                breakout_signals.append(('target_growth', row['target_delta']))
                
            # Depth chart promotion (big signal)
            if is_starter and row.get('was_starter', False) == False:
                breakout_signals.append(('promotion', 1.0))
                
            if not breakout_signals:
                continue
                
            # Weighted breakout score
            weights = {
                'snap_surge': 0.25,
                'route_jump': 0.20,
                'target_growth': 0.35,
                'promotion': 0.20
            }
            
            score = sum(weights[signal] * value for signal, value in breakout_signals)
            
            candidates.append({
                'player_id': player_id,
                'position': row.get('position', 'UNK'),
                'team': row.get('team', 'UNK'),
                'breakout_score': score,
                'signals': breakout_signals,
                'current_snap': row.get('snap_share', 0),
                'snap_delta': row.get('snap_delta', 0),
                'target_delta': row.get('target_delta', 0)
            })
            
        # Sort by breakout score
        candidates.sort(key=lambda x: x['breakout_score'], reverse=True)
        return candidates
    
    def get_value_adds(self,
                      candidates: List[Dict],
                      ownership_threshold: float = 0.50) -> List[Dict]:
        """
        Filter candidates to those likely available on waivers.
        
        Args:
            candidates: Breakout candidate list
            ownership_threshold: Max ownership % to be considered "available"
            
        Returns filtered list
        """
        # In production, join with league ownership data
        # For now, return all candidates with note
        for candidate in candidates:
            candidate['likely_available'] = True  # Placeholder
            candidate['priority_recommendation'] = self._get_priority_rec(candidate)
            
        return candidates
    
    def _get_priority_rec(self, candidate: Dict) -> str:
        """
        Generate waiver priority recommendation.
        """
        score = candidate['breakout_score']
        signals = [s[0] for s in candidate['signals']]
        
        if 'promotion' in signals and score > 0.7:
            return "SPEND TOP-3 PRIORITY"
        elif score > 0.5:
            return "STRONG ADD (mid priority)"
        elif score > 0.3:
            return "SPECULATIVE ADD (low priority)"
        else:
            return "MONITOR ONLY"
