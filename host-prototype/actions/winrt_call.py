"""Synchronous, time-bounded WinRT calls for the Actions providers (radios, bt_info).

How the WinRT async operations are made synchronous
----------------------------------------------------
Every WinRT call of the providers runs on ONE process-wide worker thread (``orizonx-winrt``) that joins the
multithreaded apartment (``CoInitializeEx(COINIT_MULTITHREADED)``) once and lives until the process exits.
On that thread an ``IAsyncOperation`` is waited for with pywinrt's blocking ``op.wait(timeout_s)`` (allowed in the
MTA), cancelled if it is still running at the deadline, then read with ``op.get_results()``. The calling thread
(the ActionsHub thread, whatever its apartment) only waits on a Future, itself bounded by ``timeout_s + grace_s``.
WinRT objects never leave the worker: the callables return plain Python data.

Why not ``asyncio.run`` / a private event loop in the provider thread (measured with pywinrt 3.2.1 on Windows 11):
* pywinrt caches each activation factory (``Radio``, ``DeviceInformation`` statics) in the apartment of the first
  thread that uses it. When that thread is gone, the next call from another thread can crash the process with an
  access violation (reproduced: MTA thread A calls ``Radio.get_radios_async()`` and exits, MTA thread B calls it
  -> segmentation fault). The hub thread ends with each Actions session, so the WinRT calls must all happen on a
  thread that never ends: this worker.
* In an STA (the hub thread if comtypes initialised COM there), ``op.wait()`` / ``op.get()`` raise
  "Cannot call blocking method from single-threaded apartment"; the MTA worker has no such limit and needs no
  event loop.
"""
from __future__ import annotations

import concurrent.futures
import ctypes
import threading
from typing import Any, Callable, TypeVar

from actions.base import ProviderError

T = TypeVar("T")

# Windows.Foundation.AsyncStatus
STARTED, COMPLETED, CANCELED, ERROR = 0, 1, 2, 3

COINIT_MULTITHREADED = 0x0
DEFAULT_TIMEOUT_S = 2.0


class WinRTCallError(ProviderError):
    """A WinRT operation timed out, was cancelled, or its worker did not answer in time."""


def wait_op(op: Any, timeout_s: float) -> Any:
    """Block (on the MTA worker) until the IAsyncOperation `op` ends, at most timeout_s; return its results.

    Still running at the deadline -> cancelled and WinRTCallError. Failed -> get_results() raises the WinRT error
    (OSError with its HRESULT)."""
    status = op.wait(timeout_s)
    if status == STARTED:
        try:
            op.cancel()
        except Exception:  # noqa: BLE001 - the operation may have ended in the meantime
            pass
        raise WinRTCallError(f"WinRT operation still running after {timeout_s:g} s (cancelled)")
    if status == CANCELED:
        raise WinRTCallError("WinRT operation was cancelled")
    return op.get_results()


def _coinit_mta() -> None:
    ctypes.windll.ole32.CoInitializeEx(None, COINIT_MULTITHREADED)


class WinRTWorker:
    """One long-lived thread that runs the WinRT callables in order (see the module docstring)."""

    def __init__(self, coinit: Callable[[], None] = _coinit_mta, grace_s: float = 1.0,
                 name: str = "orizonx-winrt") -> None:
        self._coinit = coinit
        self._grace_s = grace_s
        self._name = name
        self._lock = threading.Lock()
        self._executor: concurrent.futures.ThreadPoolExecutor | None = None

    def run(self, fn: Callable[[], T], timeout_s: float = DEFAULT_TIMEOUT_S) -> T:
        """fn() on the worker thread; its exception is re-raised here. WinRTCallError if no answer in
        timeout_s + grace (fn itself should bound its WinRT waits with wait_op(op, timeout_s))."""
        with self._lock:
            if self._executor is None:
                self._executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix=self._name, initializer=self._coinit)
            future = self._executor.submit(fn)
        try:
            return future.result(timeout=timeout_s + self._grace_s)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise WinRTCallError(f"WinRT worker did not answer within {timeout_s + self._grace_s:g} s") from None

    def shutdown(self) -> None:
        """For tests: stop the thread (the process-wide WORKER is never shut down)."""
        with self._lock:
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)


WORKER = WinRTWorker()


def call(fn: Callable[[], T], timeout_s: float = DEFAULT_TIMEOUT_S) -> T:
    """fn() on the process-wide WinRT worker (MTA), bounded by timeout_s (+ grace)."""
    return WORKER.run(fn, timeout_s)
