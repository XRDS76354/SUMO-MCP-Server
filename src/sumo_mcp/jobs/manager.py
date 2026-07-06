"""Background job registry with on-disk manifests.

Long operations (big simulations, OSM builds, RL training) must not block an
MCP tool call for minutes/hours. A job runs the work in a daemon thread and
persists its state under a per-job directory:

    <jobs_root>/<job_id>/manifest.json   # status, timestamps, request echo
    <jobs_root>/<job_id>/result.json     # full runner result once finished
    <jobs_root>/<job_id>/stdout.log      # output tails for quick inspection
    <jobs_root>/<job_id>/stderr.log

Manifests are the durable source of truth: ``list_jobs`` merges the in-memory
registry with a scan of the jobs root, so jobs from a previous server process
remain visible (their status is whatever was last persisted).

The jobs root is ``$SUMO_MCP_JOBS_DIR`` or ``./sumo_mcp_jobs``.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from sumo_mcp.execution.runner import is_process_alive, kill_process_tree, run_cli

_MANIFEST = "manifest.json"
_RESULT = "result.json"
_TERMINAL = frozenset({"succeeded", "failed", "cancelled"})
_ACTIVE = frozenset({"pending", "running", "cancelling", "orphaned"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _jobs_root() -> Path:
    return Path(os.environ.get("SUMO_MCP_JOBS_DIR", "sumo_mcp_jobs"))


class _Job:
    """In-process bookkeeping for one job (manifest holds the durable copy)."""

    def __init__(self, job_id: str, job_dir: Path, manifest: Dict[str, Any]) -> None:
        self.job_id = job_id
        self.job_dir = job_dir
        self.manifest = manifest
        self.thread: Optional[threading.Thread] = None
        self.cancel_event = threading.Event()


_JobFn = Callable[[_Job], Dict[str, Any]]


class JobManager:
    def __init__(self) -> None:
        self._jobs: Dict[str, _Job] = {}
        self._lock = threading.Lock()

    # -- lifecycle -------------------------------------------------------

    def start_cli_job(
        self,
        kind: str,
        name: str,
        args: List[str],
        *,
        cwd: Optional[str] = None,
        timeout_s: Optional[float] = None,
        expected_outputs: Optional[List[Dict[str, str]]] = None,
        label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Launch ``run_cli(...)`` in a background thread; returns job info."""

        def work(job: _Job) -> Dict[str, Any]:
            return run_cli(
                kind, name, args, cwd=cwd, timeout_s=timeout_s,
                expected_outputs=expected_outputs,
                cancel_event=job.cancel_event,
                process_callback=lambda info: self._record_process(job, info),
            )

        request = {"kind": kind, "name": name, "args": list(args), "cwd": cwd,
                   "timeout_s": timeout_s, "expected_outputs": expected_outputs}
        return self._start(work, label=label or name, request=request)

    def start_callable_job(
        self,
        fn: Callable[[threading.Event], Dict[str, Any]],
        *,
        label: str,
        request: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run an arbitrary callable as a job (used by RL training in stage 5).

        ``fn`` receives the job's cancel event and must return a JSON-safe dict.
        """
        return self._start(lambda job: fn(job.cancel_event), label=label, request=request or {})

    def _start(
        self,
        fn: _JobFn,
        *,
        label: str,
        request: Dict[str, Any],
    ) -> Dict[str, Any]:
        job_id = uuid.uuid4().hex[:12]
        job_dir = _jobs_root() / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        manifest: Dict[str, Any] = {
            "job_id": job_id,
            "label": label,
            "status": "pending",
            "request": request,
            "created_at": _now(),
            "started_at": None,
            "finished_at": None,
        }
        job = _Job(job_id, job_dir, manifest)
        _atomic_write_json(job_dir / _MANIFEST, manifest)

        def runner() -> None:
            with self._lock:
                manifest["status"] = "running"
                manifest["started_at"] = _now()
                _atomic_write_json(job_dir / _MANIFEST, manifest)
            try:
                result = fn(job)
            except Exception as exc:  # job code must not kill the thread silently
                result = {"ok": False, "error": {"code": "EXECUTION_FAILED",
                                                 "message": f"{type(exc).__name__}: {exc}"}}
            with self._lock:
                if job.cancel_event.is_set():
                    manifest["status"] = "cancelled"
                else:
                    manifest["status"] = "succeeded" if result.get("ok") else "failed"
                manifest["finished_at"] = _now()
                _atomic_write_json(job_dir / _MANIFEST, manifest)
                _atomic_write_json(job_dir / _RESULT, result)
                (job_dir / "stdout.log").write_text(
                    str(result.get("stdout_tail", "")), encoding="utf-8")
                (job_dir / "stderr.log").write_text(
                    str(result.get("stderr_tail", "")), encoding="utf-8")

        thread = threading.Thread(target=runner, daemon=True, name=f"sumo-mcp-job-{job_id}")
        job.thread = thread
        with self._lock:
            self._jobs[job_id] = job
        thread.start()

        return {"job_id": job_id, "job_dir": str(job_dir), "label": label, "status": "pending"}

    def _record_process(self, job: _Job, process_info: Dict[str, Any]) -> None:
        with self._lock:
            job.manifest.update({
                "pid": process_info.get("pid"),
                "pgid": process_info.get("pgid"),
                "command": process_info.get("command"),
            })
            _atomic_write_json(job.job_dir / _MANIFEST, job.manifest)

    # -- inspection ------------------------------------------------------

    def get_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                return dict(job.manifest)
        return self._read_manifest(_jobs_root() / job_id, reconcile=True)

    def get_result(self, job_id: str) -> Optional[Dict[str, Any]]:
        status = self.get_status(job_id)
        if status is None:
            return None
        if status["status"] in ("pending", "running", "cancelling", "orphaned"):
            return status
        result_path = _jobs_root() / job_id / _RESULT
        if result_path.is_file():
            try:
                loaded: Dict[str, Any] = json.loads(result_path.read_text(encoding="utf-8"))
                return loaded
            except (OSError, json.JSONDecodeError):
                pass
        return status

    def get_logs(self, job_id: str, tail_lines: int = 100) -> Optional[Dict[str, Any]]:
        if self.get_status(job_id) is None:
            return None
        logs: Dict[str, Any] = {"job_id": job_id}
        for stream in ("stdout", "stderr"):
            path = _jobs_root() / job_id / f"{stream}.log"
            if path.is_file():
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                logs[f"{stream}_tail"] = "\n".join(lines[-tail_lines:])
            else:
                logs[f"{stream}_tail"] = ""
        return logs

    def cancel(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return self._cancel_historic(job_id)
        if job.manifest["status"] in _TERMINAL:
            return dict(job.manifest)
        job.cancel_event.set()
        with self._lock:
            self._kill_manifest_process(job.manifest)
            job.manifest["status"] = "cancelling"
            _atomic_write_json(job.job_dir / _MANIFEST, job.manifest)
        return dict(job.manifest)

    def list_jobs(self) -> List[Dict[str, Any]]:
        """Union of live registry and on-disk manifests (older first)."""
        seen: Dict[str, Dict[str, Any]] = {}
        root = _jobs_root()
        if root.is_dir():
            for job_dir in sorted(root.iterdir()):
                manifest = self._read_manifest(job_dir, reconcile=True)
                if manifest is not None:
                    seen[manifest["job_id"]] = manifest
        with self._lock:
            for job_id, job in self._jobs.items():
                seen[job_id] = dict(job.manifest)
        return sorted(seen.values(), key=lambda m: str(m.get("created_at", "")))

    @staticmethod
    def _read_manifest(job_dir: Path, *, reconcile: bool = False) -> Optional[Dict[str, Any]]:
        path = job_dir / _MANIFEST
        if not path.is_file():
            return None
        try:
            manifest: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            if reconcile:
                JobManager._reconcile_manifest(job_dir, manifest)
            return manifest
        except (OSError, json.JSONDecodeError):
            return None  # corrupted manifest: skip rather than crash listing

    @staticmethod
    def _coerce_pid(value: Any) -> Optional[int]:
        try:
            if value is None:
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _kill_manifest_process(manifest: Dict[str, Any]) -> None:
        pid = JobManager._coerce_pid(manifest.get("pid"))
        pgid = JobManager._coerce_pid(manifest.get("pgid"))
        if pid is not None and is_process_alive(pid):
            kill_process_tree(pid, pgid)

    @staticmethod
    def _reconcile_manifest(job_dir: Path, manifest: Dict[str, Any]) -> None:
        if manifest.get("status") not in _ACTIVE:
            return
        pid = JobManager._coerce_pid(manifest.get("pid"))
        if pid is not None and is_process_alive(pid):
            if manifest.get("status") != "orphaned":
                manifest["status"] = "orphaned"
                manifest["error"] = {
                    "code": "EXECUTION_FAILED",
                    "message": "Job process survived an MCP server restart; cancel it explicitly if unwanted.",
                }
                _atomic_write_json(job_dir / _MANIFEST, manifest)
            return

        manifest["status"] = "failed"
        manifest["finished_at"] = manifest.get("finished_at") or _now()
        manifest["error"] = {
            "code": "EXECUTION_FAILED",
            "message": "Job was left running in a previous server process, but its process is no longer alive.",
        }
        _atomic_write_json(job_dir / _MANIFEST, manifest)

    def _cancel_historic(self, job_id: str) -> Optional[Dict[str, Any]]:
        job_dir = _jobs_root() / job_id
        manifest = self._read_manifest(job_dir, reconcile=True)
        if manifest is None:
            return None
        if manifest.get("status") in _TERMINAL:
            return manifest
        self._kill_manifest_process(manifest)
        manifest["status"] = "cancelled"
        manifest["finished_at"] = _now()
        manifest["error"] = {
            "code": "EXECUTION_FAILED",
            "message": "Historic job process was cancelled and killed.",
        }
        _atomic_write_json(job_dir / _MANIFEST, manifest)
        return manifest


job_manager = JobManager()
