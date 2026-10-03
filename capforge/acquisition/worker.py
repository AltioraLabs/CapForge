"""CapForge Autonomous Asynchronous Job Worker Daemon (discussion.mdx §19, §33).

Processes queued capability acquisition jobs in the background with worker concurrency,
thread safety, heartbeat tracking, and graceful shutdown.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from capforge.acquisition.jobs import LearningJob, LearningJobManager

logger = logging.getLogger("capforge.acquisition.worker")


class LearningJobWorker:
    """Background worker daemon for asynchronous processing of learning jobs."""

    def __init__(
        self,
        manager: LearningJobManager,
        max_workers: int = 2,
        poll_interval_sec: float = 0.5,
    ):
        self.manager = manager
        self.max_workers = max_workers
        self.poll_interval_sec = poll_interval_sec

        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=self.max_workers)
        self._active_jobs: dict[str, LearningJob] = {}

    def start(self) -> None:
        """Start the background worker polling thread."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(
                target=self._worker_loop,
                name="CapForge-LearningJobWorker",
                daemon=True,
            )
            self._thread.start()
            logger.info("Started CapForge LearningJobWorker daemon.")

    def stop(self, timeout_sec: float = 5.0) -> None:
        """Gracefully stop the background worker."""
        with self._lock:
            self._running = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout_sec)
        self._executor.shutdown(wait=False)
        logger.info("CapForge LearningJobWorker daemon stopped.")

    def is_running(self) -> bool:
        return self._running

    def _worker_loop(self) -> None:
        """Polling loop that claims and executes QUEUED jobs."""
        while self._running:
            try:
                # Find queued jobs
                queued = self.manager.list_jobs(status="QUEUED")
                for job in queued:
                    if not self._running:
                        break
                    with self._lock:
                        if job.job_id in self._active_jobs:
                            continue
                        if len(self._active_jobs) >= self.max_workers:
                            break
                        self._active_jobs[job.job_id] = job
                        job.status = "RUNNING"

                    # Submit to thread pool
                    self._executor.submit(self._process_job, job.job_id)

            except Exception as e:
                logger.error(f"Error in job worker polling loop: {e}")

            time.sleep(self.poll_interval_sec)

    def _process_job(self, job_id: str) -> None:
        """Process a single job on the thread pool."""
        try:
            logger.info(f"Worker executing job {job_id}")
            self.manager.execute_job_sync(job_id)
        except Exception as e:
            logger.exception(f"Unhandled error in worker executing job {job_id}: {e}")
        finally:
            with self._lock:
                self._active_jobs.pop(job_id, None)

    def wait_idle(self, timeout_sec: float = 10.0) -> bool:
        """Wait until all queued and running jobs have finished."""
        start = time.time()
        while time.time() - start < timeout_sec:
            queued = self.manager.list_jobs(status="QUEUED")
            with self._lock:
                active = len(self._active_jobs)
            if not queued and active == 0:
                return True
            time.sleep(0.05)
        return False
