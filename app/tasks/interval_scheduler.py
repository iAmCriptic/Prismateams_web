"""Shared interval-thread scheduler (app context + interruptible wait)."""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)


class IntervalScheduler:
    """Daemon thread: run_job() in app context, then wait interval_seconds()."""

    name = "scheduler"
    start_delay_seconds = 0
    wait_step_seconds = 5
    error_wait_seconds = 60

    def __init__(self, app=None):
        self.app = app
        self.running = False
        self.thread = None
        if app:
            self.init_app(app)

    def init_app(self, app):
        self.app = app
        self.start()

    def interval_seconds(self) -> int:
        return 300

    def run_job(self) -> None:
        raise NotImplementedError

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(
            target=self._run_scheduler,
            daemon=True,
            name=self.name,
        )
        self.thread.start()
        logger.info("%s gestartet", self.name)

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("%s gestoppt", self.name)

    def _sleep_interruptible(self, seconds: int) -> None:
        remaining = max(0, int(seconds or 0))
        step = max(1, int(self.wait_step_seconds or 1))
        slept = 0
        while self.running and slept < remaining:
            chunk = min(step, remaining - slept)
            time.sleep(chunk)
            slept += chunk

    def _run_scheduler(self):
        if self.start_delay_seconds:
            time.sleep(self.start_delay_seconds)
        while self.running:
            interval = 300
            try:
                with self.app.app_context():
                    self.run_job()
                    interval = self.interval_seconds()
            except Exception:
                logger.exception("%s Fehler", self.name)
                self._sleep_interruptible(self.error_wait_seconds)
                continue
            self._sleep_interruptible(interval)
