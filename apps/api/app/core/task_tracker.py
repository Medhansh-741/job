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
        analysis_pending: bool = False,
        retry_in: Optional[float] = None,
    ) -> None:
        with self._lock:
            self._tasks[user_id] = {
                "status": status,
                "progress": max(0, min(100, progress)),
                "step_label": step_label,
                "error": error,
                # True while the AI explanations for some jobs are still being (re)tried in the background
                "analysis_pending": analysis_pending,
                "retry_in": retry_in,
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
                    "analysis_pending": False,
                    "retry_in": None,
                    "updated_at": time.time(),
                }
            return dict(task)

    def clear(self, user_id: str) -> None:
        with self._lock:
            self._tasks.pop(user_id, None)

    def mark_completed(self, user_id: str, count: int = 10) -> None:
        self.set_progress(
            user_id=user_id,
            status="completed",
            progress=100,
            step_label="Matches ready! Loading dashboard...",
            error=None,
        )

    def mark_analysis_pending(self, user_id: str, explained: int, retry_in: float) -> None:
        """Run finished but some AI explanations are missing; a background retry is scheduled.

        Reported as "completed" so the upload dialog can hand over to the dashboard, which keeps
        showing an 'analysis in progress' state until analysis_pending flips back to False.
        """
        self.set_progress(
            user_id=user_id,
            status="completed",
            progress=100,
            step_label=(
                f"The AI service is slow or busy right now. Retrying automatically in about {max(1, int(round(retry_in)))} seconds"
                + (f" ({explained} matches ready so far)." if explained else ".")
            ),
            error=None,
            analysis_pending=True,
            retry_in=retry_in,
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
