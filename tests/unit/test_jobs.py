"""Unit tests for the background job manager (no SUMO required)."""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict

import pytest

import sumo_mcp.execution.runner as runner_mod
import sumo_mcp.jobs.manager as jm
from sumo_mcp.catalog.registry import CommandSpec
from sumo_mcp.jobs.manager import JobManager


@pytest.fixture(autouse=True)
def _jobs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "jobs"
    monkeypatch.setenv("SUMO_MCP_JOBS_DIR", str(root))
    return root


def _wait_status(manager: JobManager, job_id: str, wanted: set[str], timeout: float = 10.0) -> Dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = manager.get_status(job_id)
        assert status is not None
        if status["status"] in wanted:
            return status
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} never reached {wanted}")


def test_full_lifecycle_success(_jobs_dir: Path) -> None:
    manager = JobManager()

    def work(cancel: threading.Event) -> Dict[str, Any]:
        return {"ok": True, "stdout_tail": "hello", "stderr_tail": "", "value": 42}

    info = manager.start_callable_job(work, label="demo", request={"x": 1})
    assert set(info) == {"job_id", "job_dir", "label", "status"}

    status = _wait_status(manager, info["job_id"], {"succeeded"})
    assert status["label"] == "demo"
    assert status["request"] == {"x": 1}
    assert status["created_at"] and status["started_at"] and status["finished_at"]

    result = manager.get_result(info["job_id"])
    assert result is not None and result["ok"] is True and result["value"] == 42

    logs = manager.get_logs(info["job_id"])
    assert logs is not None and logs["stdout_tail"] == "hello"

    # durable manifest on disk
    manifest = json.loads((Path(info["job_dir"]) / "manifest.json").read_text())
    assert manifest["status"] == "succeeded"
    assert not list(Path(info["job_dir"]).glob("*.tmp"))  # atomic writes cleaned up


def test_failed_job_and_exception_capture(_jobs_dir: Path) -> None:
    manager = JobManager()

    def fails(cancel: threading.Event) -> Dict[str, Any]:
        return {"ok": False, "error": {"code": "EXECUTION_FAILED", "message": "nope"}}

    info = manager.start_callable_job(fails, label="failing")
    assert _wait_status(manager, info["job_id"], {"failed"})["status"] == "failed"

    def raises(cancel: threading.Event) -> Dict[str, Any]:
        raise RuntimeError("crashed inside job")

    info = manager.start_callable_job(raises, label="raising")
    _wait_status(manager, info["job_id"], {"failed"})
    result = manager.get_result(info["job_id"])
    assert result is not None
    assert "crashed inside job" in result["error"]["message"]


def test_result_before_completion_returns_status(_jobs_dir: Path) -> None:
    manager = JobManager()
    release = threading.Event()

    def slow(cancel: threading.Event) -> Dict[str, Any]:
        release.wait(10)
        return {"ok": True}

    info = manager.start_callable_job(slow, label="slow")
    early = manager.get_result(info["job_id"])
    assert early is not None and early["status"] in ("pending", "running")
    release.set()
    _wait_status(manager, info["job_id"], {"succeeded"})


def test_cancel_running_job(_jobs_dir: Path) -> None:
    manager = JobManager()
    started = threading.Event()

    def cancellable(cancel: threading.Event) -> Dict[str, Any]:
        started.set()
        cancel.wait(30)
        return {"ok": False, "error": {"code": "EXECUTION_FAILED", "message": "cancelled"}}

    info = manager.start_callable_job(cancellable, label="c")
    assert started.wait(5)
    cancelled = manager.cancel(info["job_id"])
    assert cancelled is not None and cancelled["status"] == "cancelling"
    # stays cancelled even after the thread returns
    time.sleep(0.3)
    status = manager.get_status(info["job_id"])
    assert status is not None and status["status"] == "cancelled"


def test_cancel_finished_job_is_noop(_jobs_dir: Path) -> None:
    manager = JobManager()
    info = manager.start_callable_job(lambda c: {"ok": True}, label="done")
    _wait_status(manager, info["job_id"], {"succeeded"})
    assert manager.cancel(info["job_id"])["status"] == "succeeded"  # type: ignore[index]


def test_unknown_job_returns_none(_jobs_dir: Path) -> None:
    manager = JobManager()
    assert manager.get_status("nope") is None
    assert manager.get_result("nope") is None
    assert manager.get_logs("nope") is None
    assert manager.cancel("nope") is None


def test_list_jobs_sees_disk_jobs_from_previous_process(_jobs_dir: Path) -> None:
    first = JobManager()
    info = first.start_callable_job(lambda c: {"ok": True}, label="old-run")
    _wait_status(first, info["job_id"], {"succeeded"})

    # a fresh manager (≈ server restart) must still see it via the manifest
    second = JobManager()
    listed = second.list_jobs()
    assert any(j["job_id"] == info["job_id"] and j["status"] == "succeeded" for j in listed)
    status = second.get_status(info["job_id"])
    assert status is not None and status["status"] == "succeeded"
    result = second.get_result(info["job_id"])
    assert result is not None and result["ok"] is True


def test_list_jobs_skips_corrupted_manifest(_jobs_dir: Path) -> None:
    manager = JobManager()
    info = manager.start_callable_job(lambda c: {"ok": True}, label="good")
    _wait_status(manager, info["job_id"], {"succeeded"})

    bad_dir = _jobs_dir / "corrupt"
    bad_dir.mkdir(parents=True)
    (bad_dir / "manifest.json").write_text("{not json")

    listed = manager.list_jobs()
    assert any(j["job_id"] == info["job_id"] for j in listed)
    assert all(j["job_id"] != "corrupt" for j in listed)


def test_cli_job_runs_runner(monkeypatch: pytest.MonkeyPatch, _jobs_dir: Path) -> None:
    calls: Dict[str, Any] = {}

    def fake_run_cli(kind: str, name: str, args, **kwargs) -> Dict[str, Any]:
        calls.update(kind=kind, name=name, args=args, **kwargs)
        return {"ok": True, "stdout_tail": "ran", "stderr_tail": ""}

    import sumo_mcp.jobs.manager as jm
    monkeypatch.setattr(jm, "run_cli", fake_run_cli)

    manager = JobManager()
    info = manager.start_cli_job("binary", "netgenerate", ["--grid"],
                                 timeout_s=5, label="gen")
    status = _wait_status(manager, info["job_id"], {"succeeded"})
    assert status["request"]["name"] == "netgenerate"
    assert calls["kind"] == "binary" and calls["args"] == ["--grid"] and calls["timeout_s"] == 5


def test_cli_job_cancel_kills_subprocess(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _jobs_dir: Path) -> None:
    script = tmp_path / "sleep_tool.py"
    script.write_text("import time\nprint('started', flush=True)\ntime.sleep(30)\n", encoding="utf-8")

    def fake_resolve(name: str, kind: str | None = None) -> CommandSpec | None:
        if name == "sleep_tool.py":
            return CommandSpec(
                name=name, kind="tool", tier=1, category="test", description="",
                available=True, path=str(script),
            )
        return None

    monkeypatch.setattr(runner_mod, "resolve_command", fake_resolve)
    manager = JobManager()
    info = manager.start_cli_job("tool", "sleep_tool.py", [], timeout_s=30, label="sleep")

    status = _wait_status(manager, info["job_id"], {"running"})
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and "pid" not in status:
        time.sleep(0.05)
        status = manager.get_status(info["job_id"]) or {}
    pid = int(status["pid"])
    assert runner_mod.is_process_alive(pid)

    cancelling = manager.cancel(info["job_id"])
    assert cancelling is not None and cancelling["status"] == "cancelling"
    final = _wait_status(manager, info["job_id"], {"cancelled"})
    assert final["finished_at"]
    assert not runner_mod.is_process_alive(pid)


def test_historic_running_job_reconciles_and_can_be_cancelled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _jobs_dir: Path
) -> None:
    command = [sys.executable, "-c", "import time; time.sleep(30)"]
    proc = __import__("subprocess").Popen(
        command,
        stdout=__import__("subprocess").DEVNULL,
        stderr=__import__("subprocess").DEVNULL,
    )
    job_dir = _jobs_dir / "historic"
    job_dir.mkdir(parents=True)
    (job_dir / "manifest.json").write_text(json.dumps({
        "job_id": "historic",
        "label": "old",
        "status": "running",
        "request": {},
        "pid": proc.pid,
        "pgid": None,
        "command": command,
        "created_at": "2026-01-01T00:00:00+00:00",
        "started_at": "2026-01-01T00:00:01+00:00",
        "finished_at": None,
    }), encoding="utf-8")

    manager = JobManager()
    status = manager.get_status("historic")
    assert status is not None and status["status"] == "orphaned"
    cancelled = manager.cancel("historic")
    assert cancelled is not None and cancelled["status"] == "cancelled"
    proc.wait(timeout=10)
    assert not runner_mod.is_process_alive(proc.pid)


def test_historic_running_job_refuses_unverified_pid(tmp_path: Path, _jobs_dir: Path) -> None:
    proc = __import__("subprocess").Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=__import__("subprocess").DEVNULL,
        stderr=__import__("subprocess").DEVNULL,
    )
    try:
        job_dir = _jobs_dir / "stale"
        job_dir.mkdir(parents=True)
        (job_dir / "manifest.json").write_text(json.dumps({
            "job_id": "stale",
            "label": "old",
            "status": "running",
            "request": {},
            "pid": proc.pid,
            "pgid": None,
            "command": [sys.executable, "-c", "print('different job')"],
            "created_at": "2026-01-01T00:00:00+00:00",
            "started_at": "2026-01-01T00:00:01+00:00",
            "finished_at": None,
        }), encoding="utf-8")

        manager = JobManager()
        status = manager.get_status("stale")
        assert status is not None and status["status"] == "stale_manual_review"
        cancelled = manager.cancel("stale")
        assert cancelled is not None and cancelled["status"] == "stale_manual_review"
        assert runner_mod.is_process_alive(proc.pid)
    finally:
        proc.kill()
        try:
            proc.wait(timeout=10)
        except Exception:
            pass


def test_stale_historic_job_cancel_retries_identity_check(
    tmp_path: Path, _jobs_dir: Path
) -> None:
    command = [sys.executable, "-c", "import time; time.sleep(30)"]
    proc = __import__("subprocess").Popen(
        command,
        stdout=__import__("subprocess").DEVNULL,
        stderr=__import__("subprocess").DEVNULL,
    )
    job_dir = _jobs_dir / "retry-stale"
    job_dir.mkdir(parents=True)
    (job_dir / "manifest.json").write_text(json.dumps({
        "job_id": "retry-stale",
        "label": "old",
        "status": "stale_manual_review",
        "request": {},
        "pid": proc.pid,
        "pgid": None,
        "command": command,
        "created_at": "2026-01-01T00:00:00+00:00",
        "started_at": "2026-01-01T00:00:01+00:00",
        "finished_at": None,
    }), encoding="utf-8")

    cancelled = JobManager().cancel("retry-stale")
    assert cancelled is not None and cancelled["status"] == "cancelled"
    proc.wait(timeout=10)
    assert not runner_mod.is_process_alive(proc.pid)


def test_historic_identity_requires_exact_command_match(
    monkeypatch: pytest.MonkeyPatch, _jobs_dir: Path
) -> None:
    job_dir = _jobs_dir / "substring"
    job_dir.mkdir(parents=True)
    (job_dir / "manifest.json").write_text(json.dumps({
        "job_id": "substring",
        "label": "old",
        "status": "running",
        "request": {},
        "pid": 12345,
        "pgid": None,
        "command": ["/python", "-m", "sumo_mcp.rl.train_entry", "/run"],
        "created_at": "2026-01-01T00:00:00+00:00",
        "started_at": "2026-01-01T00:00:01+00:00",
        "finished_at": None,
    }), encoding="utf-8")
    killed: list[tuple[int, int | None]] = []
    monkeypatch.setattr(jm, "is_process_alive", lambda pid: True)
    monkeypatch.setattr(JobManager, "_read_process_argv", staticmethod(lambda pid: None))
    monkeypatch.setattr(
        JobManager,
        "_read_process_command",
        staticmethod(lambda pid: "bash -c '/python -m sumo_mcp.rl.train_entry /run; cleanup'"),
    )
    monkeypatch.setattr(jm, "kill_process_tree", lambda pid, pgid: killed.append((pid, pgid)))

    cancelled = JobManager().cancel("substring")
    assert cancelled is not None and cancelled["status"] == "stale_manual_review"
    assert killed == []


def test_windows_process_command_uses_powershell_cim(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    class Result:
        stdout = "python -m sumo_mcp.rl.train_entry C:\\run\n"

    def fake_run(command, **kwargs):
        calls.append(command)
        return Result()

    monkeypatch.setattr(jm.sys, "platform", "win32")
    monkeypatch.setattr(jm.subprocess, "run", fake_run)
    assert JobManager._read_process_command(42) == "python -m sumo_mcp.rl.train_entry C:\\run"
    assert calls[0][0] == "powershell"


def test_windows_process_command_falls_back_to_wmic(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    class Result:
        stdout = "CommandLine=python -m sumo_mcp.rl.train_entry C:\\run\n"

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[0] == "powershell":
            raise OSError("missing")
        return Result()

    monkeypatch.setattr(jm.sys, "platform", "win32")
    monkeypatch.setattr(jm.subprocess, "run", fake_run)
    assert JobManager._read_process_command(42) == "python -m sumo_mcp.rl.train_entry C:\\run"
    assert [call[0] for call in calls] == ["powershell", "wmic"]


def test_historic_dead_running_job_becomes_failed(_jobs_dir: Path) -> None:
    job_dir = _jobs_dir / "dead"
    job_dir.mkdir(parents=True)
    (job_dir / "manifest.json").write_text(json.dumps({
        "job_id": "dead",
        "label": "old",
        "status": "running",
        "request": {},
        "pid": 99999999,
        "created_at": "2026-01-01T00:00:00+00:00",
        "started_at": "2026-01-01T00:00:01+00:00",
        "finished_at": None,
    }), encoding="utf-8")

    status = JobManager().get_status("dead")
    assert status is not None
    assert status["status"] == "failed"
    assert "no longer alive" in status["error"]["message"]


def test_windows_quoted_command_line_still_matches(monkeypatch: pytest.MonkeyPatch, _jobs_dir: Path) -> None:
    # FIX #2: On Windows the OS CommandLine quotes tokens containing spaces
    # (e.g. "C:\\Program Files\\Python\\python.exe"), while our manifest argv is
    # joined with plain spaces. Normalization must strip quotes so a legitimate
    # job installed under a spaced path is NOT wrongly marked stale.
    job_dir = _jobs_dir / "quoted"
    job_dir.mkdir(parents=True)
    (job_dir / "manifest.json").write_text(json.dumps({
        "job_id": "quoted",
        "label": "old",
        "status": "running",
        "request": {},
        "pid": 4242,
        "pgid": None,
        "command": ["C:\\Program Files\\Python\\python.exe", "-m", "sumo_mcp.rl.train_entry", "C:\\my run"],
        "created_at": "2026-01-01T00:00:00+00:00",
        "started_at": "2026-01-01T00:00:01+00:00",
        "finished_at": None,
    }), encoding="utf-8")
    killed: list[tuple[int, int | None]] = []
    monkeypatch.setattr(jm.sys, "platform", "win32")
    monkeypatch.setattr(jm, "is_process_alive", lambda pid: True)
    monkeypatch.setattr(JobManager, "_read_process_argv", staticmethod(lambda pid: None))
    monkeypatch.setattr(
        JobManager,
        "_read_process_command",
        staticmethod(
            lambda pid: '"C:\\Program Files\\Python\\python.exe" -m sumo_mcp.rl.train_entry "C:\\my run"'
        ),
    )
    monkeypatch.setattr(jm, "kill_process_tree", lambda pid, pgid: killed.append((pid, pgid)))

    cancelled = JobManager().cancel("quoted")
    assert cancelled is not None and cancelled["status"] == "cancelled"
    assert killed == [(4242, None)]


def test_historic_cancel_reverifies_identity_before_kill(monkeypatch: pytest.MonkeyPatch, _jobs_dir: Path) -> None:
    # FIX #3 (TOCTOU): identity passes during the initial check, but the PID is
    # reused (identity no longer matches) by the time we are about to kill. The
    # kill must be skipped and the job marked stale, never killing the reused PID.
    job_dir = _jobs_dir / "toctou"
    job_dir.mkdir(parents=True)
    (job_dir / "manifest.json").write_text(json.dumps({
        "job_id": "toctou",
        "label": "old",
        "status": "running",
        "request": {},
        "pid": 5555,
        "pgid": None,
        "command": ["/python", "-m", "sumo_mcp.rl.train_entry", "/run"],
        "created_at": "2026-01-01T00:00:00+00:00",
        "started_at": "2026-01-01T00:00:01+00:00",
        "finished_at": None,
    }), encoding="utf-8")
    killed: list[tuple[int, int | None]] = []
    monkeypatch.setattr(jm, "is_process_alive", lambda pid: True)
    monkeypatch.setattr(JobManager, "_read_process_argv", staticmethod(lambda pid: None))

    # First identity read (in _cancel_historic) matches; second read (inside
    # _kill_manifest_process re-verification) reflects a reused PID and differs.
    reads = iter([
        "/python -m sumo_mcp.rl.train_entry /run",
        "/usr/bin/some-unrelated-process --serve",
    ])
    monkeypatch.setattr(
        JobManager,
        "_read_process_command",
        staticmethod(lambda pid: next(reads, "/usr/bin/some-unrelated-process --serve")),
    )
    monkeypatch.setattr(jm, "kill_process_tree", lambda pid, pgid: killed.append((pid, pgid)))

    cancelled = JobManager().cancel("toctou")
    assert cancelled is not None and cancelled["status"] == "stale_manual_review"
    assert killed == []
