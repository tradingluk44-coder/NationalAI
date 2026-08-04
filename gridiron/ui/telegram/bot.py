"""
GRIDIRON Phase 7: Telegram Bot & Ops Scheduler
Delivery layer for alerts, lineups, and watchdogs.
"""
import logging
import os
import time
from pathlib import Path
from typing import Optional, Dict
import requests

from gridiron.config.settings import CONFIG

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TelegramBot:
    """
    Handles all push notifications to user.
    Uses provided bot token from config/env.
    """
    
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "8623716485:AAF36YsSI_8ExHa6JaN_lH5XJavuWpYwPxU")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "") # User must set this
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        
    def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """Send text message to configured chat."""
        if not self.chat_id:
            logger.warning("Chat ID not configured. Message skipped.")
            return False
            
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode
        }
        
        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            logger.info(f"Message sent: {text[:50]}...")
            return True
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False
            
    def send_lineup_card(self, lineup: Dict, e_points: float, p_win: float, regime: str):
        """Formatted lineup card."""
        starters = "\n".join([f"{pos}: {pid}" for pos, pid in lineup.items()])
        
        text = (
            f"🏈 *GRIDIRON Lineup Card*\n\n"
            f"*Starters:*\n{starters}\n\n"
            f"📊 *Proj Points:* {e_points:.1f}\n"
            f"🎯 *Win Prob:* {p_win:.1%}\n"
            f"⚙️ *Regime:* {regime}\n\n"
            f"_Good luck!_"
        )
        self.send_message(text)
        
    def send_waiver_alert(self, player_name: str, delta_p: float, priority_rec: str):
        """Waiver wire recommendation."""
        text = (
            f"💰 *Waiver Alert*\n\n"
            f"Target: *{player_name}*\n"
            f"ΔP(Playoffs): *+{delta_p:.2%}*\n"
            f"Rec: *{priority_rec}*\n\n"
            f"Check dashboard for details."
        )
        self.send_message(text)
        
    def send_pivot_alert(self, action: str, reason: str, new_p_win: float):
        """Late-window pivot recommendation."""
        text = (
            f"⚠️ *Pivot Alert*\n\n"
            f"Action: *{action}*\n"
            f"Reason: {reason}\n"
            f"New P(Win): *{new_p_win:.1%}*\n\n"
            f"Execute now before lock!"
        )
        self.send_message(text)

class Scheduler:
    """
    Centralized job runner for all automated tasks.
    Replaces systemd with portable Python CLI.
    """
    
    def __init__(self):
        self.bot = TelegramBot()
        self.jobs = {
            'refresh_data': self.job_refresh_data,
            'waiver_screen': self.job_waiver_screen,
            'final_lock': self.job_final_lock,
            'late_pivot': self.job_late_pivot,
            'post_mortem': self.job_post_mortem
        }
        
    def run_job(self, job_name: str):
        """Execute a specific job with error handling."""
        logger.info(f"Starting job: {job_name}")
        try:
            if job_name in self.jobs:
                self.jobs[job_name]()
                logger.info(f"Job {job_name} completed successfully.")
            else:
                logger.error(f"Unknown job: {job_name}")
        except Exception as e:
            logger.error(f"Job {job_name} failed: {e}")
            self.bot.send_message(f"❌ *SYSTEM FAILURE*\nJob: {job_name}\nError: {str(e)}")
            raise
            
    def job_refresh_data(self):
        """Tue 09:00: Pull all data sources."""
        logger.info("Refreshing data sources...")
        # In real impl: call ingest modules
        time.sleep(1) # Mock
        self.bot.send_message("✅ Data Refresh Complete")
        
    def job_waiver_screen(self):
        """Tue 09:30: Run waiver screener."""
        logger.info("Running waiver screen...")
        # Mock result
        self.bot.send_waiver_alert("Sample Player", 0.042, "Spend Priority")
        
    def job_final_lock(self):
        """Sun 17:00: Final lineup lock & card."""
        logger.info("Generating final lineup...")
        # Mock lineup
        lineup = {'QB': 'Mahomes', 'RB1': 'McCaffrey', 'RB2': 'Breece', 
                  'WR1': 'Jefferson', 'WR2': 'Chase', 'TE': 'Kelce',
                  'FLEX': 'Hill', 'K': 'Tucker', 'DEF': '49ers'}
        self.bot.send_lineup_card(lineup, 124.5, 0.58, "P(Win) Max")
        
    def job_late_pivot(self):
        """Sun 21:30: Check for late pivots."""
        logger.info("Checking late window...")
        # Mock scenario: SNF player has favorable matchup
        self.bot.send_pivot_alert("Start Hurts over Fields", "SNF Matchup Edge", 0.62)
        
    def job_post_mortem(self):
        """Mon 09:00: Calibration report."""
        logger.info("Generating calibration report...")
        self.bot.send_message("📉 *Week 5 Brier Score*: 0.19\nAvg: 0.21\nStatus: On Target")

if __name__ == "__main__":
    # Test run
    scheduler = Scheduler()
    
    print("Testing Telegram Bot...")
    # scheduler.run_job('refresh_data')
    # scheduler.run_job('waiver_screen')
    scheduler.run_job('final_lock')
    # scheduler.run_job('late_pivot')
    # scheduler.run_job('post_mortem')
    
    print("Scheduler test complete.")
