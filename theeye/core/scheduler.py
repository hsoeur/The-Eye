"""Planificateur de tâches périodiques : pas de chevauchement, erreurs isolées et tracées."""
import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Dict, List

log = logging.getLogger("eye.scheduler")


class Job:
    def __init__(self, name: str, interval: float, fn: Callable[[], None], immediate: bool):
        self.name, self.interval, self.fn = name, interval, fn
        self.next_run = time.monotonic() + (0 if immediate else interval)
        self.running = False
        self.runs = 0
        self.last_start = 0.0
        self.last_duration = 0.0
        self.last_error = ""

    def status(self) -> Dict[str, Any]:
        return {"name": self.name, "interval": self.interval, "running": self.running, "runs": self.runs,
                "last_run": self.last_start, "last_duration_ms": round(self.last_duration * 1000),
                "last_error": self.last_error}


class Scheduler:
    def __init__(self, workers: int = 16):
        self._pool = ThreadPoolExecutor(workers, thread_name_prefix="eye-job")
        self._jobs: List[Job] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="eye-scheduler", daemon=True)

    def every(self, name: str, seconds: float, fn: Callable[[], None], immediate: bool = True) -> Job:
        job = Job(name, seconds, fn, immediate)
        with self._lock:
            self._jobs.append(job)
        return job

    def submit(self, fn: Callable[..., Any], *args: Any) -> Future:
        return self._pool.submit(self._guard, getattr(fn, "__name__", "task"), fn, *args)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def status(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [j.status() for j in self._jobs]

    @staticmethod
    def _guard(name, fn, *args):
        try:
            return fn(*args)
        except Exception:
            log.exception("tâche %s en erreur", name)

    def _run(self, job: Job) -> None:
        t0 = time.monotonic()
        job.last_start = time.time()
        try:
            job.fn()
            job.last_error = ""
        except Exception as e:
            job.last_error = f"{type(e).__name__}: {e}"[:300]
            log.exception("job %s en erreur", job.name)
        finally:
            job.last_duration = time.monotonic() - t0
            job.runs += 1
            job.running = False

    def _loop(self) -> None:
        while not self._stop.wait(0.5):
            now = time.monotonic()
            with self._lock:
                due = [j for j in self._jobs if not j.running and j.next_run <= now]
            for job in due:
                job.running = True
                job.next_run = now + job.interval
                try:
                    self._pool.submit(self._run, job)
                except RuntimeError:
                    return
