from __future__ import annotations

import collections
import threading
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone

from dashboard.schemas import (
    SessionState,
    AttemptState,
    GenerationRecord,
    TelemetryEvent,
    ConnectionState,
    AgentStatus,
    current_iso_time,
)


class TelemetryStore:
    """Thread-safe in-memory store for agent telemetry."""

    def __init__(self, max_events: int = 200, max_generations: int = 100):
        self._lock = threading.RLock()
        self.max_events = max_events
        self.max_generations = max_generations

        self.session = SessionState()
        self.current_attempt = AttemptState()
        self.generations_history: List[GenerationRecord] = []
        self.events: collections.deque = collections.deque(maxlen=max_events)
        self.last_seen_event_id: int = 0

    def update_session(self, **kwargs) -> None:
        with self._lock:
            reset_best = kwargs.pop("reset_best", False)
            for k, v in kwargs.items():
                if hasattr(self.session, k):
                    if (
                        not reset_best
                        and k in {"best_completion", "best_fitness"}
                        and v is not None
                    ):
                        current = getattr(self.session, k)
                        if current is not None and v < current:
                            continue
                    setattr(self.session, k, v)
            self.session.last_update = current_iso_time()

    def update_attempt(self, attempt_data: AttemptState) -> None:
        with self._lock:
            self.current_attempt = attempt_data
            if attempt_data.level_progress > self.session.best_completion:
                self.session.best_completion = attempt_data.level_progress
            if attempt_data.fitness is not None:
                if self.session.best_fitness is None or attempt_data.fitness > self.session.best_fitness:
                    self.session.best_fitness = attempt_data.fitness
            self.session.current_attempt = attempt_data.attempt_number
            self.session.current_generation = attempt_data.generation
            self.session.last_update = current_iso_time()

    def add_generation_record(self, record: GenerationRecord) -> None:
        with self._lock:
            # Replace existing generation if already recorded or append
            for idx, existing in enumerate(self.generations_history):
                if existing.generation == record.generation:
                    self.generations_history[idx] = record
                    return
            self.generations_history.append(record)
            if len(self.generations_history) > self.max_generations:
                self.generations_history.pop(0)

    def add_event(self, event: TelemetryEvent) -> None:
        with self._lock:
            self.last_seen_event_id += 1
            event_dict = event.to_dict()
            event_dict["id"] = self.last_seen_event_id
            self.events.append(event_dict)

    def get_status_payload(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "session": self.session.to_dict(),
                "attempt": self.current_attempt.to_dict(),
                "timestamp": current_iso_time(),
            }

    def get_metrics_payload(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "session": self.session.to_dict(),
                "generations": [g.to_dict() for g in self.generations_history],
                "total_generations": len(self.generations_history),
                "timestamp": current_iso_time(),
            }

    def get_events_payload(self, limit: int = 50, since_id: Optional[int] = None) -> Dict[str, Any]:
        with self._lock:
            event_list = list(self.events)
            if since_id is not None:
                event_list = [e for e in event_list if e["id"] > since_id]
            if limit and len(event_list) > limit:
                event_list = event_list[-limit:]
            return {
                "events": event_list,
                "total_events": len(self.events),
                "timestamp": current_iso_time(),
            }

    def get_full_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "session": self.session.to_dict(),
                "attempt": self.current_attempt.to_dict(),
                "generations": [g.to_dict() for g in self.generations_history],
                "events": list(self.events)[-50:],
                "timestamp": current_iso_time(),
            }

    def clear_events(self) -> None:
        with self._lock:
            self.events.clear()

    def set_agent_disconnected(self) -> None:
        with self._lock:
            self.session.connection_state = ConnectionState.DISCONNECTED.value
            self.session.agent_status = AgentStatus.IDLE.value
            self.session.last_update = current_iso_time()
