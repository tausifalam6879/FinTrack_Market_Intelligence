"""Bounded process-wide admission control; no untrusted proxy IP headers."""
from collections import deque
from threading import Lock
import time


class RequestBudget:
    def __init__(self, per_minute=30, concurrent=2):
        self.per_minute = max(1, per_minute)
        self.concurrent = max(1, concurrent)
        self.active = 0
        self.started = deque()
        self.lock = Lock()

    def acquire(self):
        now = time.monotonic()
        with self.lock:
            while self.started and self.started[0] <= now - 60:
                self.started.popleft()
            if self.active >= self.concurrent or len(self.started) >= self.per_minute:
                return False
            self.started.append(now)
            self.active += 1
            return True

    def release(self):
        with self.lock:
            self.active = max(0, self.active - 1)
