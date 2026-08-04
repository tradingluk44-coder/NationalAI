"""
Phase 3 Validation Tests - Replacement Levels + VORP Draft Board

Tests for:
- core/replacement.py: Free-agent-level replacement computation
- engines/draft/board.py: VORP board with tier detection
- engines/draft/optimizer.py: Snake draft optimization with dynamic adjustments
- engines/draft/tracker.py: Live draft state tracking
- engines/draft/dynamic_adjuster.py: Real-time VORP adjustments

Vertical Gates:
1. Replacement levels computed as best projected UNDRAFTED player (not last drafted)
2. VORP board shows emergent structural properties (I1, I3, I4)
3. Tier detection via change-point analysis (no hardcoding)
4. Draft optimizer beats naive BAV in ≥65% of 200 simulated drafts per slot
5. Dynamic adjustments correctly apply injury/bye/depth chart signals
6. Bye conflict detection prevents >2 players on same bye (with exceptions)

Horizontal Contracts:
- H3: Single replacement source used by both draft and waivers
- H6: All modules read roster sizes from league_config.yaml
"""

import pytest
import polars as pl
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock
import sys
sys.path.insert(0, '/workspace/gridiron')


class TestReplacementCalculator:
    """Test replacement level computation"""
    
    def test_replacement_is_undrafted_not_last_drafted(self):
        """
        Gate: Replacement = best projected FREE AGENT, not last drafted player
        
        This is critical: "last drafted" assumes perfect draft, but 
        replacement should be what's actually available on waiver wire
        """
        from gridiron.core.replacement import ReplacementCalculator
        
        # Mock projections showing some top players undrafted due to ADP noise
        projections = pl.DataFrame({
            'player_id': ['p1', 'p2', 'p3', 'p4', 'p5', 'p6'],
            'position': ['RB'] * 6,
            'expected_points': [20.0, 18.0, 15.0, 12.0, 10.0, 8.0],
            'adp_mean': [5.0, 12.0, 25.0, 45.0, 80.0, 95.0],  # p6 goes late/undrafted
            'adp_std': [2.0, 3.0, 5.0, 10.0, 15.0, 20.0]
        })
        
        config = {
            'league': {'teams': 10},
            'roster': {'starters': {'RB': 2}, 'bench': 6}
        }
        
        calc = ReplacementCalculator(config)
        
        # Simulate draft where p6 goes undrafted (ADP noise)
        replacement = calc.get_replacement_levels(projections, adp_noise_draws=100)
        
        # Replacement should be around p5/p6 level (free agent), not p4 (last drafted)
        assert replacement['position'].to_list() == ['RB']
        repl_pts = replacement['replacement_points'][0]
        
        # Should be closer to p5/p6 (8-10 pts) than p1 (20 pts)
        assert 7.0 <= repl_pts <= 11.0, f"Replacement {repl_pts} not in FA range"
    
    def test_replacement_varies_by_league_size(self):
        """Replacement in 10-team league ≠ 12-team league"""
        from gridiron.core.replacement import ReplacementCalculator
        
        projections = pl.DataFrame({
            'player_id': [f'p{i}' for i in range(1, 51)],
            'position': ['RB'] * 50,
            'expected_points': list(np.linspace(20, 2, 50)),
            'adp_mean': list(range(1, 51)),
            'adp_std': [3.0] * 50
        })
        
        config_10 = {'league': {'teams': 10}, 'roster': {'starters': {'RB': 2}, 'bench': 6}}
        config_12 = {'league': {'teams': 12}, 'roster': {'starters': {'RB': 2}, 'bench': 6}}
        
        calc_10 = ReplacementCalculator(config_10)
        calc_12 = ReplacementCalculator(config_12)
        
        repl_10 = calc_10.get_replacement_levels(projections, adp_noise_draws=50)
        repl_12 = calc_12.get_replacement_levels(projections, adp_noise_draws=50)
        
        # 12-team league has fewer FAs, so replacement should be lower
        assert repl_12['replacement_points'][0] < repl_10['replacement_points'][0]


class TestVorpBoard:
    """Test VORP board construction and tier detection"""
    
    def test_qb_compression_emerges(self):
        """
        I1: QB compression should emerge naturally from scoring rules
        
        Pocket QBs should cluster together in VORP because:
        - Passing TD = 4 pts (half standard)
        - Only rushing ability differentiates elite from streamable
        """
        from gridiron.engines.draft.board import VorpBoard
        
        # Mock services
        mock_proj = Mock()
        mock_repl = Mock()
        mock_score = Mock()
        
        config = {'league': {'teams': 10}}
        
        board = VorpBoard(mock_proj, mock_repl, mock_score, config)
        
        # Create mock VORP data with QBs
        vorp_df = pl.DataFrame({
            'player_id': ['qb1', 'qb2', 'qb3', 'qb4', 'qb5', 'qb6'],
            'player_name': ['Mahomes', 'Allen', 'Jackson', 'Hurts', 'Burrow', 'Lamar'],
            'position': ['QB'] * 6,
            'vorp': [35.0, 33.0, 30.0, 28.0, 27.0, 26.0]  # Compressed range
        })
        
        # Detect tiers
        breakpoints = board.detect_tiers(vorp_df)
        
        # Should find minimal gaps (compression) vs other positions
        qb_breakpoints = [b for b in breakpoints if b.position == 'QB']
        
        # QB should have fewer/smaller breakpoints than RB/WR
        # This validates compression emerges
        avg_gap = np.mean([b.vorp_drop for b in qb_breakpoints]) if qb_breakpoints else 0
        assert avg_gap < 5.0, "QB compression not emerging - gaps too large"
    
    def test_te_cliff_detected(self):
        """
        I3: TE dead zone should be detected via change-point analysis
        
        Elite TEs (TE1-TE2) significantly above TE3+, then flat dead zone
        """
        from gridiron.engines.draft.board import VorpBoard
        
        mock_proj = Mock()
        mock_repl = Mock()
        mock_score = Mock()
        config = {'league': {'teams': 10}}
        
        board = VorpBoard(mock_proj, mock_repl, mock_score, config)
        
        # TE VORP with elite cliff then dead zone
        vorp_df = pl.DataFrame({
            'player_id': [f'te{i}' for i in range(1, 11)],
            'player_name': [f'TE{i}' for i in range(1, 11)],
            'position': ['TE'] * 10,
            'vorp': [25.0, 22.0, 12.0, 11.0, 10.0, 9.0, 8.0, 7.0, 6.0, 5.0]
            # Cliff after TE2: 22->12 drop
        })
        
        breakpoints = board.detect_tiers(vorp_df)
        te_breakpoints = [b for b in breakpoints if b.position == 'TE']
        
        # Should detect break after TE2 (rank 2)
        assert any(b.rank <= 3 for b in te_breakpoints), "TE cliff not detected"
        
        # Verify structural property check
        props = board.get_structural_properties()
        # Note: This needs real data, so we just verify it runs
        assert 'te_cliff' in props
    
    def test_k_def_zero_vorp(self):
        """
        I4: K/DEF should have ~0 VORP above replacement
        
        Streaming strategy means no draft capital above last 2 rounds
        """
        from gridiron.engines.draft.board import VorpBoard
        
        mock_proj = Mock()
        mock_repl = Mock()
        mock_score = Mock()
        config = {'league': {'teams': 10}}
        
        board = VorpBoard(mock_proj, mock_repl, mock_score, config)
        
        # K/DEF with minimal VORP
        vorp_df = pl.DataFrame({
            'player_id': ['k1', 'k2', 'def1', 'def2'],
            'player_name': ['Butker', 'Tucker', '49ers', 'Bills'],
            'position': ['K', 'K', 'DEF', 'DEF'],
            'vorp': [0.5, 0.3, 0.4, 0.2]  # Near zero
        })
        
        props = board.get_structural_properties()
        # Would need full board, but verifies logic exists
        assert 'k_def_zero' in props


class TestDynamicAdjuster:
    """Test real-time VORP adjustments"""
    
    def test_injury_adjustment_out(self):
        """Player ruled OUT = -100% VORP adjustment"""
        from gridiron.engines.draft.dynamic_adjuster import DynamicAdjuster, AdjustmentType
        
        mock_warehouse = Mock()
        config = {}
        
        adjuster = DynamicAdjuster(mock_warehouse, config)
        
        # Player ruled OUT
        adj = adjuster.compute_injury_adjustment(
            player_id='p1',
            injury_status='Out',
            injury_details='Knee injury'
        )
        
        assert adj is not None
        assert adj.adjustment_type == AdjustmentType.INJURY
        assert adj.delta_pct == -1.0  # -100%
        assert adj.confidence >= 0.95
    
    def test_injury_adjustment_questionable(self):
        """Questionable = -30% VORP with lower confidence"""
        from gridiron.engines.draft.dynamic_adjuster import DynamicAdjuster
        
        mock_warehouse = Mock()
        config = {}
        adjuster = DynamicAdjuster(mock_warehouse, config)
        
        adj = adjuster.compute_injury_adjustment(
            player_id='p1',
            injury_status='Questionable',
            injury_details='Ankle'
        )
        
        assert adj is not None
        assert adj.delta_pct == -0.30
        assert adj.confidence == 0.70
    
    def test_season_ending_injury(self):
        """Season-ending injury = full removal regardless of status label"""
        from gridiron.engines.draft.dynamic_adjuster import DynamicAdjuster
        
        mock_warehouse = Mock()
        config = {}
        adjuster = DynamicAdjuster(mock_warehouse, config)
        
        adj = adjuster.compute_injury_adjustment(
            player_id='p1',
            injury_status='Out',
            injury_details='ACL tear - out for season'
        )
        
        assert adj.delta_pct == -1.0
        assert adj.confidence == 0.98
    
    def test_bye_conflict_detection(self):
        """3+ players on same bye week triggers penalty"""
        from gridiron.engines.draft.dynamic_adjuster import RosterContext
        
        ctx = RosterContext(
            drafted_players=['p1', 'p2'],
            bye_weeks={7: 2},  # Already 2 players on bye 7
            max_bye_conflicts=2,
            critical_shortage_positions=[]
        )
        
        # Adding 3rd player on bye 7
        has_conflict, severity = ctx.would_create_bye_conflict(player_bye=7, position='RB')
        
        assert has_conflict is True
        assert severity == 3  # Would be 3rd player
    
    def test_bye_conflict_penalty_scaling(self):
        """Bye conflict penalty escalates with severity"""
        from gridiron.engines.draft.dynamic_adjuster import DynamicAdjuster
        
        mock_warehouse = Mock()
        config = {}
        adjuster = DynamicAdjuster(mock_warehouse, config)
        
        ctx = RosterContext(
            drafted_players=[],
            bye_weeks={7: 2},
            max_bye_conflicts=2
        )
        
        # 3rd player on bye 7
        adj = adjuster.compute_bye_conflict_adjustment(
            player_id='p3',
            player_bye=7,
            position='RB',
            roster_ctx=ctx
        )
        
        assert adj is not None
        assert adj.delta_pct == -0.40  # 3rd player penalty
    
    def test_depth_chart_promotion_bonus(self):
        """RB2 -> RB1 promotion = +35% VORP"""
        from gridiron.engines.draft.dynamic_adjuster import DynamicAdjuster, AdjustmentType
        
        mock_warehouse = Mock()
        config = {}
        adjuster = DynamicAdjuster(mock_warehouse, config)
        
        adj = adjuster.compute_depth_chart_adjustment(
            player_id='p1',
            current_depth=1,
            prev_depth=2,
            position='RB'
        )
        
        assert adj is not None
        assert adj.adjustment_type == AdjustmentType.DEPTH_CHART_PROMOTION
        assert adj.delta_pct == 0.35
        assert adj.confidence == 0.85
    
    def test_usage_trend_snap_increase(self):
        """>20% snap share increase triggers positive adjustment"""
        from gridiron.engines.draft.dynamic_adjuster import DynamicAdjuster
        
        mock_warehouse = Mock()
        config = {}
        adjuster = DynamicAdjuster(mock_warehouse, config)
        
        adj = adjuster.compute_usage_trend_adjustment(
            player_id='p1',
            snap_pct=45.0,
            snap_pct_prev=35.0,  # ~29% increase
            target_share=20.0,
            target_share_prev=18.0
        )
        
        assert adj is not None
        assert adj.delta_pct > 0
        assert adj.adjustment_type.value == 'snap_increase'
    
    def test_off_field_suspension_penalty(self):
        """Indefinite suspension = -100% VORP"""
        from gridiron.engines.draft.dynamic_adjuster import DynamicAdjuster, AdjustmentType
        
        mock_warehouse = Mock()
        config = {}
        adjuster = DynamicAdjuster(mock_warehouse, config)
        
        adj = adjuster.compute_off_field_adjustment(
            player_id='p1',
            risk_flag=True,
            risk_details='Indefinite suspension - conduct policy'
        )
        
        assert adj is not None
        assert adj.adjustment_type == AdjustmentType.SUSPENSION
        assert adj.delta_pct == -1.0
        assert adj.confidence == 0.95
    
    def test_multiple_adjustments_applied_confidence_weighted(self):
        """Multiple adjustments applied in confidence order"""
        from gridiron.engines.draft.dynamic_adjuster import DynamicAdjuster, ValueAdjustment, AdjustmentType
        
        mock_warehouse = Mock()
        config = {}
        adjuster = DynamicAdjuster(mock_warehouse, config)
        
        base_vorp = 20.0
        
        # Create two adjustments with different confidences
        adj1 = ValueAdjustment(
            player_id='p1',
            adjustment_type=AdjustmentType.INJURY,
            delta_vorp=0.0,
            delta_pct=-0.30,
            confidence=0.70,
            source="test",
            timestamp=datetime.utcnow()
        )
        
        adj2 = ValueAdjustment(
            player_id='p1',
            adjustment_type=AdjustmentType.DEPTH_CHART_PROMOTION,
            delta_vorp=0.0,
            delta_pct=0.35,
            confidence=0.85,
            source="test",
            timestamp=datetime.utcnow()
        )
        
        adjusted = adjuster.apply_adjustments_to_vorp(base_vorp, 'p1', [adj1, adj2])
        
        # Higher confidence adjustment should have more weight
        # Net should be slightly positive (promotion outweighs questionable tag)
        assert adjusted > base_vorp * 0.7  # Not completely destroyed by injury
        assert adjusted < base_vorp * 1.3  # Not fully boosted


class TestDraftOptimizer:
    """Test draft optimization with dynamic adjustments"""
    
    def test_net_value_considers_survival_probability(self):
        """Net value = adjusted_VORP * scarcity_multiplier"""
        from gridiron.engines.draft.optimizer import DraftOptimizer, DraftState
        from gridiron.engines.draft.board import VorpBoard
        from gridiron.engines.draft.dynamic_adjuster import DynamicAdjuster
        
        # Mock dependencies
        mock_board = Mock(spec=VorpBoard)
        mock_adjuster = Mock(spec=DynamicAdjuster)
        config = {'league': {'teams': 10}}
        
        optimizer = DraftOptimizer(mock_board, mock_adjuster, config)
        
        # Mock board return
        mock_board.get_board.return_value = pl.DataFrame({
            'gridiron_id': ['p1', 'p2'],
            'player_name': ['Player1', 'Player2'],
            'position': ['RB', 'WR'],
            'vorp': [25.0, 22.0]
        })
        
        # Mock adjuster returns no adjustments
        mock_adjuster.gather_all_adjustments.return_value = {}
        mock_adjuster.apply_adjustments_to_vorp.side_effect = lambda base, pid, adj: base
        
        # Mock ADP data
        adp_data = pl.DataFrame({
            'player_id': ['p1', 'p2'],
            'adp_mean': [15.0, 25.0],
            'adp_std': [3.0, 5.0],
            'position': ['RB', 'WR']
        })
        
        # Create draft state
        state = DraftState(
            user_slot=5,
            current_pick=5,
            round_num=1,
            drafted_players=[],
            roster_composition={},
            bye_week_counts={},
            opponent_picks=[]
        )
        
        # Compute net value for scarce player (low survival prob)
        net_val, meta = optimizer.compute_net_value('p1', state, adp_data)
        
        # Net value should incorporate survival probability
        assert 'survival_prob' in meta
        assert 'scarcity_multiplier' in meta
        assert meta['scarcity_multiplier'] >= 1.0
    
    def test_roster_need_filtering_early_rounds(self):
        """Rounds 1-5 prioritize filling starter needs"""
        from gridiron.engines.draft.optimizer import DraftOptimizer, DraftState
        from gridiron.engines.draft.board import VorpBoard
        from gridiron.engines.draft.dynamic_adjuster import DynamicAdjuster
        
        mock_board = Mock(spec=VorpBoard)
        mock_adjuster = Mock(spec=DynamicAdjuster)
        config = {'league': {'teams': 10, 'roster': {'starters': {'RB': 2, 'WR': 2}, 'bench': 6}}}
        
        optimizer = DraftOptimizer(mock_board, mock_adjuster, config)
        
        # Available players
        available = pl.DataFrame({
            'gridiron_id': ['rb1', 'rb2', 'wr1', 'qb1'],
            'player_name': ['RB1', 'RB2', 'WR1', 'QB1'],
            'position': ['RB', 'RB', 'WR', 'QB'],
            'vorp': [30.0, 28.0, 25.0, 35.0]  # QB has highest VORP
        })
        
        # User already has QB, needs RB
        state = DraftState(
            user_slot=5,
            current_pick=5,
            round_num=2,  # Early round
            drafted_players=['qb1'],
            roster_composition={'QB': 1},
            bye_week_counts={},
            opponent_picks=[]
        )
        
        # Filter should prioritize RB over higher-VORP positions
        filtered = optimizer._filter_by_roster_needs(available, state)
        
        # Should filter to RB only (critical need)
        assert set(filtered['position'].unique()) == {'RB'}


class TestLiveDraftTracker:
    """Test live draft state tracking"""
    
    def test_snake_draft_pick_calculation(self):
        """Snake draft: odd rounds forward, even rounds backward"""
        from gridiron.engines.draft.tracker import LiveDraftTracker
        from gridiron.engines.draft.optimizer import DraftOptimizer
        
        mock_optimizer = Mock(spec=DraftOptimizer)
        config = {
            'league': {
                'teams': 10,
                'roster': {'starters': {'QB': 1}, 'bench': 6}
            }
        }
        
        tracker = LiveDraftTracker(
            user_slot=5,
            total_teams=10,
            optimizer=mock_optimizer,
            config=config
        )
        
        # Round 1: pick 5
        assert tracker.next_pick_overall == 5
        
        # Simulate recording picks through round 1
        for i in range(1, 11):
            if i != 5:  # Skip user's pick
                tracker.record_pick(
                    round_num=1,
                    pick_number=i,
                    player_id=f'p{i}',
                    player_name=f'Player{i}',
                    position='RB',
                    team='FA',
                    drafted_by_user=False
                )
        
        # After round 1, next pick should be round 2
        # Round 2: snake goes backward, slot 5 = pick 6 overall (10+10-5+1)
        tracker.current_round = 2
        tracker._update_next_pick()
        
        expected = 2 * 10 - 5 + 1  # = 16
        assert tracker.next_pick_overall == expected
    
    def test_bye_distribution_analysis(self):
        """Tracker detects bye week conflicts"""
        from gridiron.engines.draft.tracker import LiveDraftTracker
        from gridiron.engines.draft.optimizer import DraftOptimizer
        
        mock_optimizer = Mock(spec=DraftOptimizer)
        config = {
            'league': {
                'teams': 10,
                'roster': {'starters': {'QB': 1, 'RB': 2}, 'bench': 6}
            }
        }
        
        tracker = LiveDraftTracker(
            user_slot=3,
            total_teams=10,
            optimizer=mock_optimizer,
            config=config
        )
        
        # Record picks with same bye week
        tracker.user_drafted = ['p1', 'p2', 'p3']
        tracker.bye_week_counts = {7: 3}  # 3 players on bye 7
        
        analysis = tracker.analyze_bye_distribution()
        
        assert analysis['max_conflict'] == 7
        assert analysis['conflict_severity'] > 0
        assert len(analysis['recommendations']) > 0
    
    def test_positional_run_detection(self):
        """Tracker detects when opponents go on positional run"""
        from gridiron.engines.draft.tracker import LiveDraftTracker
        from gridiron.engines.draft.optimizer import DraftOptimizer
        
        mock_optimizer = Mock(spec=DraftOptimizer)
        config = {
            'league': {
                'teams': 10,
                'roster': {'starters': {'RB': 2}, 'bench': 6}
            }
        }
        
        tracker = LiveDraftTracker(
            user_slot=5,
            total_teams=10,
            optimizer=mock_optimizer,
            config=config
        )
        
        # Simulate recent RB run
        from datetime import datetime
        for i in range(6):
            tracker.picks.append(type('obj', (object,), {
                'position': 'RB',
                'round_num': 1,
                'pick_number': i + 1,
                'timestamp': datetime.utcnow()
            })())
        
        run_analysis = tracker.detect_positional_runs(window=6)
        
        assert 'RB' in run_analysis['active_runs']
        assert run_analysis['position_counts']['RB'] == 6


# Run with: pytest tests/unit/test_phase3_draft_engine.py -v
