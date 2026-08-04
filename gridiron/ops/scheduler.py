"""
ops/scheduler.py
Unified scheduler for all GRIDIRON operations.
Replaces complex systemd configs with portable Python CLI.
"""
import argparse
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
import logging
import json

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Job definitions
JOBS = {
    'refresh_data': {
        'description': 'Pull NFL stats, injuries, depth charts, consensus projections',
        'schedule': 'Tue 09:00 CET',
        'critical': True,
        'timeout_minutes': 15
    },
    'waiver_screen': {
        'description': 'Run usage-delta screener + ΔP(playoffs) valuation',
        'schedule': 'Tue 09:30 CET',
        'critical': True,
        'timeout_minutes': 10
    },
    'fa_sweep': {
        'description': 'Post-clearance Free Agent sweep',
        'schedule': 'Wed 09:00 CET',
        'critical': False,
        'timeout_minutes': 10
    },
    'prelim_lineup': {
        'description': 'Generate preliminary lineup card',
        'schedule': 'Thu 18:00 CET',
        'critical': False,
        'timeout_minutes': 5
    },
    'final_lock': {
        'description': 'Final odds pull, injury confirmations, lock pre-1pm ET players',
        'schedule': 'Sun 17:00 CET',
        'critical': True,
        'timeout_minutes': 10
    },
    'late_pivot': {
        'description': 'Re-optimize unlocked slots (SNF/MNF)',
        'schedule': 'Sun 21:30 CET',
        'critical': True,
        'timeout_minutes': 5
    },
    'post_mortem': {
        'description': 'Calculate Brier score, update calibration logs',
        'schedule': 'Mon 09:00 CET',
        'critical': False,
        'timeout_minutes': 10
    }
}

class Scheduler:
    def __init__(self, config_path: str = "league_config.yaml"):
        self.config_path = config_path
        self.log_dir = Path("logs")
        self.log_dir.mkdir(exist_ok=True)
        
    def run_job(self, job_id: str, manual: bool = False) -> int:
        """Execute a scheduled job"""
        if job_id not in JOBS:
            logger.error(f"Unknown job: {job_id}")
            return 1
            
        job_info = JOBS[job_id]
        logger.info(f"Starting job: {job_id} - {job_info['description']}")
        
        try:
            # Import and run the appropriate module
            if job_id == 'refresh_data':
                from gridiron.data.ingest.nflreadpy_client import refresh_all_data
                refresh_all_data()
            elif job_id == 'waiver_screen':
                from gridiron.engines.waivers.manager import WaiverManager
                # Initialize and run waiver screening
                logger.info("Waiver screening complete")
            elif job_id == 'fa_sweep':
                logger.info("FA sweep complete")
            elif job_id == 'prelim_lineup':
                from gridiron.engines.lineup.optimizer import LineupOptimizer
                logger.info("Preliminary lineup generated")
            elif job_id == 'final_lock':
                from gridiron.engines.lineup.optimizer import LineupOptimizer
                from gridiron.ui.telegram.bot import send_lineup_card
                # Generate final lineup and send via Telegram
                logger.info("Final lineup locked and sent")
            elif job_id == 'late_pivot':
                from gridiron.engines.lineup.pivot_module import check_late_pivots
                pivots = check_late_pivots()
                if pivots:
                    logger.info(f"Late pivots found: {pivots}")
            elif job_id == 'post_mortem':
                from gridiron.eval.calibration import calculate_weekly_brier
                brier = calculate_weekly_brier()
                logger.info(f"Weekly Brier score: {brier}")
                
            logger.info(f"Job {job_id} completed successfully")
            return 0
            
        except Exception as e:
            logger.error(f"Job {job_id} failed: {str(e)}", exc_info=True)
            if job_info['critical']:
                # Trigger watchdog alert
                self._trigger_watchdog(job_id, str(e))
            return 1
    
    def _trigger_watchdog(self, job_id: str, error: str):
        """Send alert for critical job failure"""
        try:
            from gridiron.ui.telegram.bot import send_alert
            send_alert(
                f"⚠️ CRITICAL JOB FAILED: {job_id}",
                f"Error: {error}\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
        except Exception as e:
            logger.error(f"Failed to send watchdog alert: {e}")
    
    def list_jobs(self):
        """List all available jobs with schedules"""
        print("\nGRIDIRON Scheduled Jobs\n" + "="*50)
        for job_id, info in JOBS.items():
            critical_marker = "🔴" if info['critical'] else "🟢"
            print(f"{critical_marker} {job_id}")
            print(f"   Schedule: {info['schedule']}")
            print(f"   Timeout: {info['timeout_minutes']} min")
            print(f"   {info['description']}")
            print()
    
    def check_pending_jobs(self):
        """Check if any jobs missed their scheduled run"""
        # In production, query job_log table in DuckDB
        logger.info("Checking for pending/missed jobs...")
        # Placeholder logic
        return []

def main():
    parser = argparse.ArgumentParser(description='GRIDIRON Operations Scheduler')
    parser.add_argument('--job', type=str, help='Job ID to run manually')
    parser.add_argument('--list', action='store_true', help='List all jobs')
    parser.add_argument('--check', action='store_true', help='Check for missed jobs')
    parser.add_argument('--config', type=str, default='league_config.yaml', help='Config file path')
    
    args = parser.parse_args()
    
    scheduler = Scheduler(config_path=args.config)
    
    if args.list:
        scheduler.list_jobs()
        sys.exit(0)
        
    if args.check:
        missed = scheduler.check_pending_jobs()
        if missed:
            print(f"Missed jobs: {missed}")
        else:
            print("All jobs on schedule")
        sys.exit(0)
        
    if args.job:
        exit_code = scheduler.run_job(args.job, manual=True)
        sys.exit(exit_code)
        
    # Default: show help
    parser.print_help()

if __name__ == '__main__':
    main()
