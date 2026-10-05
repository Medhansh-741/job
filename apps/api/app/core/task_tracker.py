"""In-memory thread-safe Task Tracker for matching funnel progress.

Tracks live pipeline progress per user:
- status: "idle" | "processing" | "completed" | "failed"
- progress: integer 0 to 100
- step_label: human-readable progress message
- error: optional error string
- updated_at: timestamp
"""
import time
from typing import Dict, Any, Optional
import threading


class TaskTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self._tasks: Dict[str, Dict[str, Any]] = {}

    def set_progress(
        self,
        user_id: str,
        status: str,
        progress: int,
        step_label: str,
        error: Optional[str] = None,
    ) -> None:
        with self._lock:
            self._tasks[user_id] = {
                "status": status,
                "progress": max(0, min(100, progress)),
                "step_label": step_label,
                "error": error,
                "updated_at": time.time(),
            }

    def get_progress(self, user_id: str) -> Dict[str, Any]:
        with self._lock:
            task = self._tasks.get(user_id)
            if not task:
                return {
                    "status": "idle",
                    "progress": 0,
                    "step_label": "",
                    "error": None,
                    "updated_at": time.time(),
                }
            return dict(task)

    def mark_completed(self, user_id: str, count: int = 15) -> None:
        self.set_progress(
            user_id=user_id,
            status="completed",
            progress=100,
            step_label="Matches ready! Loading dashboard...",
            error=None,
        )

    def mark_failed(self, user_id: str, error: str) -> None:
        self.set_progress(
            user_id=user_id,
            status="failed",
            progress=0,
            step_label="Matching pipeline encountered an error.",
            error=error,
        )


# Global singleton instance
task_tracker = TaskTracker()
