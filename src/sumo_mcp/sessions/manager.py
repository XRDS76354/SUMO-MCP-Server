"""Named multi-session TraCI manager.

v0.1 exposes exactly one global TraCI connection (utils/connection.py); that
path is untouched for backward compatibility. This manager adds *named*
sessions on top, using TraCI's native multi-connection support
(``traci.start(..., label=...)`` + ``traci.getConnection(label)``), so an
agent can run e.g. a baseline and an optimized scenario side by side.

Domain access goes through an explicit method whitelist (``ALLOWED_CALLS``):
enough for the industry-relevant read/write surface (signal control, vehicle
intervention, detector reads) without handing an agent the full TraCI API.

Known beta0.2 defects fixed here: session cap (was unbounded), start timeout
(was dropped), idle reaping (was absent).
"""
from __future__ import annotations

import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, FrozenSet, List, Optional

from sumo_mcp.utils.sumo import find_sumo_binary
from sumo_mcp.utils.traci import ensure_traci_start_stdout_suppressed

ALLOWED_CALLS: Dict[str, FrozenSet[str]] = {
    "trafficlight": frozenset({
        "getIDList", "getRedYellowGreenState", "getPhase", "getPhaseDuration",
        "getProgram", "getAllProgramLogics", "getNextSwitch",
        "setPhase", "setProgram", "setPhaseDuration", "setRedYellowGreenState",
    }),
    "vehicle": frozenset({
        "getIDList", "getSpeed", "getPosition", "getAcceleration", "getLaneID", "getRoadID",
        "getRoute", "getWaitingTime", "getAccumulatedWaitingTime", "getCO2Emission",
        "setSpeed", "slowDown", "setStop", "resume", "rerouteTraveltime",
        "changeTarget", "add", "remove", "changeLane", "setRouteID",
    }),
    "inductionloop": frozenset({
        "getIDList", "getLastStepVehicleNumber", "getLastStepMeanSpeed",
        "getLastStepOccupancy",
    }),
    "lanearea": frozenset({
        "getIDList", "getLastStepVehicleNumber", "getLastStepMeanSpeed",
        "getJamLengthMeters", "getLastStepOccupancy",
    }),
    "edge": frozenset({
        "getIDList", "getLastStepVehicleNumber", "getLastStepMeanSpeed",
        "getWaitingTime", "getLastStepHaltingNumber",
    }),
    "lane": frozenset({
        "getIDList", "getLastStepVehicleNumber", "getLastStepMeanSpeed",
    }),
    "simulation": frozenset({
        "getTime", "getMinExpectedNumber", "getDepartedNumber", "getArrivedNumber",
        "getCollidingVehiclesNumber", "getLoadedNumber",
    }),
    "person": frozenset({"getIDList", "getPosition", "getSpeed"}),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gui_allowed() -> bool:
    return os.environ.get("SUMO_MCP_ALLOW_GUI", "").lower() in ("1", "true", "yes")


@dataclass
class SessionInfo:
    label: str
    config_file: Optional[str]
    gui: bool
    created_at: str
    last_used_at: str
    sim_time: float
    status: str  # "active" | "closed"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class _Session:
    def __init__(self, info: SessionInfo, connection: Any) -> None:
        self.info = info
        self.connection = connection


class SessionManager:
    MAX_SESSIONS = 8
    DEFAULT_IDLE_TTL_S = 1800.0

    def __init__(self) -> None:
        self._sessions: Dict[str, _Session] = {}
        self._lock = threading.RLock()
        self._counter = 0

    # -- helpers ---------------------------------------------------------

    def _traci(self) -> Any:
        """Import traci lazily so non-session tools work without it."""
        ensure_traci_start_stdout_suppressed()
        import traci
        return traci

    def _next_label(self) -> str:
        self._counter += 1
        return f"s{self._counter}"

    def _pick(self, label: Optional[str]) -> _Session:
        if label is not None:
            session = self._sessions.get(label)
            if session is None:
                raise KeyError(
                    f"No session labelled {label!r}. Active: {sorted(self._sessions)}"
                )
            return session
        if len(self._sessions) == 1:
            return next(iter(self._sessions.values()))
        if not self._sessions:
            raise KeyError("No active sessions. Open one with action='connect' + session label.")
        raise KeyError(
            f"Multiple sessions active ({sorted(self._sessions)}); "
            "specify which one with the session parameter."
        )

    def _touch(self, session: _Session) -> None:
        session.info.last_used_at = _now()

    def _reap_idle(self, max_idle_s: Optional[float] = None) -> None:
        """Close sessions idle beyond the TTL (lazily invoked, lock held)."""
        ttl = max_idle_s if max_idle_s is not None else self.DEFAULT_IDLE_TTL_S
        now = datetime.now(timezone.utc)
        for label in list(self._sessions):
            session = self._sessions[label]
            last = datetime.fromisoformat(session.info.last_used_at)
            if (now - last).total_seconds() > ttl:
                self._close_session(label)

    def _close_session(self, label: str) -> None:
        session = self._sessions.pop(label, None)
        if session is None:
            return
        session.info.status = "closed"
        try:
            session.connection.close()
        except Exception:
            pass  # already dead — that's fine, we're removing it anyway

    # -- public API -------------------------------------------------------

    def open(
        self,
        config_file: str,
        *,
        label: Optional[str] = None,
        gui: bool = False,
        extra_args: Optional[List[str]] = None,
        timeout_s: float = 60.0,
    ) -> SessionInfo:
        if gui and not _gui_allowed():
            raise PermissionError(
                "GUI sessions are blocked for headless MCP use. "
                "Set SUMO_MCP_ALLOW_GUI=1 in the server environment to allow them."
            )

        with self._lock:
            self._reap_idle()
            if label is None:
                label = self._next_label()
            if label in self._sessions:
                raise ValueError(f"Session label {label!r} already in use.")
            if len(self._sessions) >= self.MAX_SESSIONS:
                raise RuntimeError(
                    f"Session limit reached ({self.MAX_SESSIONS}). "
                    "Close an existing session first."
                )

            binary = find_sumo_binary("sumo-gui" if gui else "sumo")
            if not binary:
                raise FileNotFoundError(
                    "Could not locate the SUMO binary. Set SUMO_HOME or add it to PATH."
                )

            cmd = [binary, "-c", config_file, "--no-step-log", "true", "--start"]
            if extra_args:
                cmd.extend(str(a) for a in extra_args)

            traci = self._traci()

            # traci.start can hang forever on a broken config/port; run it in a
            # worker thread with a join timeout (beta0.2 dropped this — defect).
            start_error: List[BaseException] = []

            def _start() -> None:
                try:
                    import subprocess
                    traci.start(cmd, label=label, stdout=subprocess.DEVNULL)
                except BaseException as exc:  # noqa: BLE001 - reported to caller
                    start_error.append(exc)

            starter = threading.Thread(target=_start, daemon=True)
            starter.start()
            starter.join(timeout_s)
            if starter.is_alive():
                raise TimeoutError(
                    f"traci.start did not complete within {timeout_s:.0f}s "
                    f"for config {config_file!r}."
                )
            if start_error:
                raise RuntimeError(f"Failed to start session: {start_error[0]}")

            connection = traci.getConnection(label)
            info = SessionInfo(
                label=label, config_file=config_file, gui=gui,
                created_at=_now(), last_used_at=_now(),
                sim_time=0.0, status="active",
            )
            self._sessions[label] = _Session(info, connection)
            return info

    def step(self, label: Optional[str] = None, steps: int = 1) -> Dict[str, Any]:
        if steps < 1:
            raise ValueError("steps must be >= 1")
        with self._lock:
            session = self._pick(label)
            for _ in range(steps):
                session.connection.simulationStep()
            sim_time = float(session.connection.simulation.getTime())
            active = list(session.connection.vehicle.getIDList())
            session.info.sim_time = sim_time
            self._touch(session)
            return {
                "label": session.info.label,
                "sim_time": sim_time,
                "active_vehicles": len(active),
            }

    def call(self, label: Optional[str], domain: str, method: str,
             args: Optional[List[Any]] = None) -> Any:
        """Invoke one whitelisted TraCI domain method on a session."""
        allowed = ALLOWED_CALLS.get(domain)
        if allowed is None:
            raise PermissionError(
                f"TraCI domain {domain!r} is not exposed. "
                f"Available domains: {sorted(ALLOWED_CALLS)}"
            )
        if method not in allowed:
            raise PermissionError(
                f"Method {domain}.{method} is not whitelisted. "
                f"Allowed for {domain}: {sorted(allowed)}"
            )
        with self._lock:
            session = self._pick(label)
            domain_obj = getattr(session.connection, domain)
            fn = getattr(domain_obj, method)
            result = fn(*(args or []))
            self._touch(session)
            return result

    def close(self, label: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            session = self._pick(label)
            closed_label = session.info.label
            self._close_session(closed_label)
            return {"label": closed_label, "status": "closed"}

    def close_all(self) -> int:
        with self._lock:
            labels = list(self._sessions)
            for label in labels:
                self._close_session(label)
            return len(labels)

    def list_sessions(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._reap_idle()
            return [s.info.to_dict() for s in self._sessions.values()]

    def get(self, label: str) -> Optional[SessionInfo]:
        with self._lock:
            session = self._sessions.get(label)
            return session.info if session else None


session_manager = SessionManager()
