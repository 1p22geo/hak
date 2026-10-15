from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, Dict, Any


class ConnectionState(str, Enum):
    CONNECTED = "Connected"
    DISCONNECTED = "Disconnected"
    SIMULATED = "Simulated"


class AgentStatus(str, Enum):
    IDLE = "Idle"
    INITIALIZING = "Initializing"
    RUNNING = "Running"
    PAUSED = "Paused"
    EVALUATING = "Evaluating"
    ERROR = "Error"


class AttemptOutcome(str, Enum):
    RUNNING = "Running"
    CRASHED = "Crashed"
    COMPLETED = "Completed"
    UNKNOWN = "Unknown"


class EventSeverity(str, Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class TelemetryEvent:
    timestamp: str  # ISO 8601 string
    category: str
    message: str
    severity: str = EventSeverity.INFO.value
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class JumpTiming:
    planned_time: float  # In seconds from attempt start
    executed_time: Optional[float] = None  # None if not executed yet
    action: str = "jump"  # "jump", "hold", "release"
    delta_ms: Optional[float] = None  # Timing error in ms if executed

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GenerationRecord:
    generation: int
    best_completion: float
    avg_completion: float
    best_fitness: Optional[float] = None
    avg_fitness: Optional[float] = None
    attempts_count: int = 0
    success_count: int = 0
    completed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AttemptState:
    attempt_number: int = 0
    generation: int = 0
    level_progress: float = 0.0  # Percentage 0.0 - 100.0
    elapsed_time: float = 0.0    # Seconds
    outcome: str = AttemptOutcome.UNKNOWN.value
    latest_action: Optional[str] = "None"
    planned_jumps_count: int = 0
    executed_jumps_count: int = 0
    jumps: List[JumpTiming] = field(default_factory=list)
    fitness: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempt_number": self.attempt_number,
            "generation": self.generation,
            "level_progress": round(self.level_progress, 2),
            "elapsed_time": round(self.elapsed_time, 2),
            "outcome": self.outcome,
            "latest_action": self.latest_action,
            "planned_jumps_count": self.planned_jumps_count,
            "executed_jumps_count": self.executed_jumps_count,
            "jumps": [j.to_dict() for j in self.jumps],
            "fitness": round(self.fitness, 4) if self.fitness is not None else None,
        }


@dataclass
class SessionState:
    session_id: str = "session_default"
    project_name: str = "Geometry Dash AI / Stereo Madness"
    connection_state: str = ConnectionState.DISCONNECTED.value
    agent_status: str = AgentStatus.IDLE.value
    is_simulated: bool = True
    session_start_time: Optional[str] = None
    uptime_seconds: float = 0.0
    last_update: Optional[str] = None
    current_generation: int = 0
    current_attempt: int = 0
    total_attempts: int = 0
    successful_completions: int = 0
    best_completion: float = 0.0
    best_fitness: Optional[float] = None
    live_frame_url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "project_name": self.project_name,
            "connection_state": self.connection_state,
            "agent_status": self.agent_status,
            "is_simulated": self.is_simulated,
            "session_start_time": self.session_start_time,
            "uptime_seconds": round(self.uptime_seconds, 1),
            "last_update": self.last_update,
            "current_generation": self.current_generation,
            "current_attempt": self.current_attempt,
            "total_attempts": self.total_attempts,
            "successful_completions": self.successful_completions,
            "best_completion": round(self.best_completion, 2),
            "best_fitness": round(self.best_fitness, 4) if self.best_fitness is not None else None,
            "live_frame_url": self.live_frame_url,
        }


def current_iso_time() -> str:
    return datetime.now(timezone.utc).isoformat()
