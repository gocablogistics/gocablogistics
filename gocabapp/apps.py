# gocabapp/apps.py
from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)


class GocabappConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "gocabapp"

    def ready(self):
        # Import and connect signals
        import gocabapp.signals.ride_signals
        import gocabapp.signals.driver_signals

        # Start background tasks for automatic ride cleanup
        self.start_background_tasks()

    def start_background_tasks(self):
        """
        Start background tasks for automatic ride cleanup
        """
        try:
            # Import here to avoid circular imports
            from .tasks import cleanup_old_rides

            # Check if we're in a management command (like migrate)
            import sys

            if "manage.py" in sys.argv and "migrate" in sys.argv:
                logger.info("⏸️ Skipping background task setup during migrations")
                return

            # Check if task is already scheduled to avoid duplicates
            from background_task.models import Task

            existing_tasks = Task.objects.filter(
                task_name="gocabapp.tasks.cleanup_old_rides"
            )

            if not existing_tasks.exists():
                # Schedule the cleanup task to run every 30 minutes
                # First run after 2 minutes to let the app fully start
                cleanup_old_rides(schedule=120)  # 2 minutes
                logger.info(
                    "🚀 Scheduled background ride cleanup task (every 30 minutes)"
                )
            else:
                logger.info("✅ Background ride cleanup task already scheduled")

        except Exception as e:
            logger.warning(f"⚠️ Could not schedule background tasks: {e}")
            # Don't crash the app if background tasks can't be scheduled
