"""
Background job scheduler using APScheduler.
Jobs:
  - Daily hotspot report (midnight)
  - Payment reminders (8 AM, for challans due in 3 days)
"""
import os
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_payment_reminders():
    """Send reminders for unpaid challans due in <= 3 days."""
    from utils.database import SessionLocal
    from utils.models import Challan, Violation, Vehicle, User
    from utils.notifications import notify_payment_reminder

    db = SessionLocal()
    try:
        threshold = datetime.utcnow() + timedelta(days=3)
        challans = (
            db.query(Challan)
            .filter(
                Challan.status == "unpaid",
                Challan.due_date <= threshold,
                Challan.due_date >= datetime.utcnow(),
            )
            .all()
        )
        for challan in challans:
            violation = challan.violation
            if violation and violation.vehicle and violation.vehicle.owner:
                user = violation.vehicle.owner
                notify_payment_reminder(db, user, challan)
                logger.info(f"Reminder sent for challan {challan.challan_number} -> {user.email}")
        logger.info(f"[SCHEDULER] Payment reminders: {len(challans)} sent.")
    except Exception as e:
        logger.error(f"[SCHEDULER] Payment reminder error: {e}")
    finally:
        db.close()


def run_daily_hotspot_report():
    """Generate and log daily hotspot summary."""
    from utils.database import SessionLocal
    from utils.models import Violation
    from sqlalchemy import func

    db = SessionLocal()
    try:
        yesterday = datetime.utcnow() - timedelta(days=1)
        hotspots = (
            db.query(Violation.location, func.count(Violation.id).label("count"))
            .filter(Violation.created_at >= yesterday)
            .group_by(Violation.location)
            .order_by(func.count(Violation.id).desc())
            .limit(10)
            .all()
        )
        report_lines = [f"  {loc}: {count} violations" for loc, count in hotspots]
        report = "\n".join(report_lines) or "  No violations in the last 24 hours."
        logger.info(f"[SCHEDULER] Daily Hotspot Report ({datetime.utcnow().date()}):\n{report}")
    except Exception as e:
        logger.error(f"[SCHEDULER] Hotspot report error: {e}")
    finally:
        db.close()


_scheduler = None


def start_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    _scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

    # Payment reminders: every day at 08:00 IST
    _scheduler.add_job(
        run_payment_reminders,
        CronTrigger(hour=8, minute=0),
        id="payment_reminders",
        replace_existing=True,
    )

    # Hotspot report: every day at 00:05 IST
    _scheduler.add_job(
        run_daily_hotspot_report,
        CronTrigger(hour=0, minute=5),
        id="hotspot_report",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info("[SCHEDULER] Background scheduler started.")
    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown()
        logger.info("[SCHEDULER] Scheduler stopped.")
