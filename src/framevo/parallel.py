"""Process-per-task execution with a hard timeout.

Every task runs in its own spawned subprocess; a task that exceeds the
timeout is terminated and reported as failed. Concurrency is capped at the
configured worker count (auto = cpu count).
"""
from __future__ import annotations

import multiprocessing as mp
import time
from dataclasses import dataclass
from typing import Any

_CTX = mp.get_context("spawn")


@dataclass
class TaskOutcome:
    ok: bool
    value: Any = None
    error: str | None = None


def _runner(fn_name: str, args: tuple, queue: Any) -> None:
    try:
        from . import evaluate
        fn = getattr(evaluate, fn_name)
        queue.put(("ok", fn(*args)))
    except BaseException as exc:  # report, parent decides
        queue.put(("err", f"{type(exc).__name__}: {exc}"))
    finally:
        queue.close()
        queue.join_thread()


def run_tasks(fn_name: str, args_list: list[tuple], workers: int,
              timeout_s: float, label: str = "") -> list[TaskOutcome]:
    """Run evaluate.<fn_name>(*args) for each args tuple; ordered results."""
    results: list[TaskOutcome] = [TaskOutcome(False, error="not run")
                                  for _ in args_list]
    pending = list(enumerate(args_list))
    running: dict[int, tuple[Any, Any, float]] = {}  # idx -> (proc, queue, deadline)

    while pending or running:
        while pending and len(running) < workers:
            idx, args = pending.pop(0)
            queue = _CTX.Queue()
            proc = _CTX.Process(target=_runner, args=(fn_name, args, queue),
                                daemon=True)
            proc.start()
            running[idx] = (proc, queue, time.monotonic() + timeout_s)

        time.sleep(0.02)
        for idx in list(running):
            proc, queue, deadline = running[idx]
            got = None
            try:
                got = queue.get_nowait()
            except Exception:
                pass
            if got is not None:
                status, payload = got
                results[idx] = (TaskOutcome(True, value=payload) if status == "ok"
                                else TaskOutcome(False, error=payload))
                proc.join(timeout=5.0)
                if proc.is_alive():
                    proc.terminate()
                del running[idx]
            elif not proc.is_alive():
                # the child may have exited between our queue poll and here;
                # drain once more before declaring it dead
                try:
                    status, payload = queue.get(timeout=0.25)
                    results[idx] = (TaskOutcome(True, value=payload)
                                    if status == "ok"
                                    else TaskOutcome(False, error=payload))
                except Exception:
                    results[idx] = TaskOutcome(False, error="worker died")
                del running[idx]
            elif time.monotonic() > deadline:
                proc.terminate()
                proc.join(timeout=5.0)
                results[idx] = TaskOutcome(False, error=f"timeout after {timeout_s:.0f}s")
                del running[idx]
    return results
