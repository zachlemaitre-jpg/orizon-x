"""The performance numbers of the Actions mode (spec 2026-10-21 perf-blocks §2): CPU, GPU, RAM, Wi-Fi throughput and NPU, read
once a second from the Windows performance counters (PDH, the Task Manager's own) and kept as 60-point curves.

* ``PdhReader`` (``pdh.dll``, ctypes): ``open(paths)`` opens a query with ``PdhAddEnglishCounterW`` (counter names do not
  depend on the Windows language) and takes a first sample (rate counters need two); ``collect``, ``value`` (one number) and
  ``array`` (wildcard instances -> ``{instance name: value}``); ``PdhError`` carries any non-zero status. Read-only.
* ``DxgiAdapters.list()`` (``dxgi.dll``, the COM helpers of ``dxgi_outputs``): the graphics adapters with their LUID,
  description, software flag and memory; the GPU is the biggest hardware one (``perf_math.pick_gpu``).
* ``system_memory()`` (``GlobalMemoryStatusEx``) and ``active_wifi_description()`` (``GetAdaptersAddresses``: the
  description of the wireless adapter that is up, which PDH writes with ``(``->``[``, ``)``->``]``, ``#`` and ``/`` -> ``_``).
* ``PerfSampler``: a daemon thread ``orizonx-perf`` that ticks every second and keeps the last section for ``latest()``. The
  GPU, the NPU (the compute-only LUID that DXGI does not list) and the Wi-Fi instance are looked for at start, every 60 s and
  when the one in use disappears from the counters. A measure that fails is absent for that tick (logged once a minute at
  most); the others go on. ``tick()`` is public so the tests drive it without the thread.
* ``PerfProvider``: the hub provider (section ``perf``). The sampler starts at the first ``snapshot()`` and stops with
  ``stop()`` (``close()`` is the same). It has no action.

Snapshot: see ``perf_math.build_section``. The reader, adapters, memory, Wi-Fi lookup, clock and sleep are injectable for the
tests, which never need a counter of their own.
"""
from __future__ import annotations

import copy
import ctypes
import logging
import re
import threading
import time
from ctypes import wintypes
from typing import Any, Callable, Optional

from actions.perf_math import History, build_section, engine_busy, engine_types, pick_gpu, pick_npu

_log = logging.getLogger("orizonx.actions.perf")

PDH_FMT_DOUBLE = 0x00000200
PDH_FMT_NOCAP100 = 0x00008000
PDH_MORE_DATA = 0x800007D2
PDH_CSTATUS_VALID_DATA = 0
PDH_CSTATUS_NEW_DATA = 1

TICK_S = 1.0
DISCOVERY_S = 60.0
LOG_EVERY_S = 60.0
STOP_JOIN_S = 2.0
GIB = 2 ** 30

CPU_UTILITY = r"\Processor Information(_Total)\% Processor Utility"
CPU_TIME = r"\Processor Information(_Total)\% Processor Time"
CPU_FREQUENCY = r"\Processor Information(_Total)\Processor Frequency"
CPU_PERFORMANCE = r"\Processor Information(_Total)\% Processor Performance"
GPU_ENGINE = r"\GPU Engine(*)\Utilization Percentage"
GPU_DEDICATED = r"\GPU Adapter Memory(*)\Dedicated Usage"
GPU_SHARED = r"\GPU Adapter Memory(*)\Shared Usage"
NET_RECEIVED = r"\Network Interface(*)\Bytes Received/sec"
NET_SENT = r"\Network Interface(*)\Bytes Sent/sec"

_MEMORY_RE = re.compile(r"luid_(0x[0-9a-fA-F]+_0x[0-9a-fA-F]+)_phys_(\d+)$")


class PdhError(OSError):
    """A PDH call failed (its status is in ``status``)."""

    def __init__(self, call: str, status: int) -> None:
        super().__init__(f"{call} failed (PDH status 0x{status & 0xFFFFFFFF:08X})")
        self.status = status & 0xFFFFFFFF


# --- PDH (pdh.dll through ctypes) ---

class _CounterValue(ctypes.Structure):  # PDH_FMT_COUNTERVALUE, read as a double
    _fields_ = [("CStatus", wintypes.DWORD), ("doubleValue", ctypes.c_double)]


class _CounterValueItem(ctypes.Structure):  # PDH_FMT_COUNTERVALUE_ITEM_W: the name points inside the same buffer
    _fields_ = [("szName", ctypes.c_void_p), ("FmtValue", _CounterValue)]


class PdhQuery:
    """An open PDH query: ``counters`` maps each path given to ``PdhReader.open`` to its counter handle."""

    def __init__(self, handle: Any, counters: "dict[str, Any]") -> None:
        self.handle = handle
        self.counters = counters


class PdhReader:
    def __init__(self) -> None:
        dll = ctypes.WinDLL("pdh.dll")  # OSError -> no performance numbers
        status = ctypes.c_uint32
        self._open = dll.PdhOpenQueryW
        self._open.argtypes = [wintypes.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p)]
        self._open.restype = status
        self._add = dll.PdhAddEnglishCounterW
        self._add.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p)]
        self._add.restype = status
        self._collect = dll.PdhCollectQueryData
        self._collect.argtypes = [ctypes.c_void_p]
        self._collect.restype = status
        self._value = dll.PdhGetFormattedCounterValue
        self._value.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                ctypes.POINTER(_CounterValue)]
        self._value.restype = status
        self._array = dll.PdhGetFormattedCounterArrayW
        self._array.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        self._array.restype = status
        self._close = dll.PdhCloseQuery
        self._close.argtypes = [ctypes.c_void_p]
        self._close.restype = status

    def open(self, paths: "list[str]") -> PdhQuery:
        """A query with one counter per path, already sampled once. PdhError when a path cannot be added."""
        handle = ctypes.c_void_p()
        code = self._open(None, 0, ctypes.byref(handle))
        if code:
            raise PdhError("PdhOpenQuery", code)
        counters: "dict[str, Any]" = {}
        try:
            for path in paths:
                counter = ctypes.c_void_p()
                code = self._add(handle, path, 0, ctypes.byref(counter))
                if code:
                    raise PdhError(f"PdhAddEnglishCounter({path})", code)
                counters[path] = counter
            self.collect(PdhQuery(handle, counters))
        except PdhError:
            self._close(handle)
            raise
        return PdhQuery(handle, counters)

    def collect(self, query: PdhQuery) -> None:
        code = self._collect(query.handle)
        if code:
            raise PdhError("PdhCollectQueryData", code)

    def value(self, counter: Any) -> Optional[float]:
        """The counter's current value, or None when it has no valid sample yet."""
        out = _CounterValue()
        code = self._value(counter, PDH_FMT_DOUBLE | PDH_FMT_NOCAP100, None, ctypes.byref(out))
        if code:
            raise PdhError("PdhGetFormattedCounterValue", code)
        if out.CStatus not in (PDH_CSTATUS_VALID_DATA, PDH_CSTATUS_NEW_DATA):
            return None
        return float(out.doubleValue)

    def array(self, counter: Any) -> "dict[str, float]":
        """Every instance of a wildcard counter: ``{instance name: value}`` (instances without a valid sample left out)."""
        size, count = wintypes.DWORD(0), wintypes.DWORD(0)
        flags = PDH_FMT_DOUBLE | PDH_FMT_NOCAP100
        code = self._array(counter, flags, ctypes.byref(size), ctypes.byref(count), None)
        for _ in range(3):  # the instances may change between the two calls
            if code != PDH_MORE_DATA:
                break
            buffer = ctypes.create_string_buffer(size.value)
            code = self._array(counter, flags, ctypes.byref(size), ctypes.byref(count), buffer)
            if code == 0:
                items = (_CounterValueItem * count.value).from_buffer(buffer)
                return {ctypes.wstring_at(item.szName): float(item.FmtValue.doubleValue) for item in items
                        if item.szName and item.FmtValue.CStatus in (PDH_CSTATUS_VALID_DATA, PDH_CSTATUS_NEW_DATA)}
        if code:
            raise PdhError("PdhGetFormattedCounterArray", code)
        return {}

    def close(self, query: PdhQuery) -> None:
        self._close(query.handle)


# --- DXGI adapters ---

class DxgiAdapters:
    """The graphics adapters, through the COM helpers of ``dxgi_outputs`` (a new factory at each call)."""

    SOFTWARE = 2  # DXGI_ADAPTER_FLAG_SOFTWARE

    def list(self) -> "list[dict]":
        """``[{"luid": "0x00000000_0x00015cba", "description", "software": bool, "dedicated": int, "shared": int}]`` in
        enumeration order (memory in bytes). Raises ``dxgi_outputs.DxgiError`` (an OSError) on failure."""
        import dxgi_outputs as dx
        dxgi = ctypes.WinDLL("dxgi")
        create = dxgi.CreateDXGIFactory1
        create.restype = ctypes.c_long
        create.argtypes = [ctypes.POINTER(dx._GUID), ctypes.POINTER(ctypes.c_void_p)]
        factory = ctypes.c_void_p()
        dx._check(create(ctypes.byref(dx.IID_IDXGIFactory1), ctypes.byref(factory)) & 0xFFFFFFFF, "CreateDXGIFactory1")
        found: "list[dict]" = []
        try:
            for index in range(dx.MAX_ADAPTERS):
                adapter = ctypes.c_void_p()
                hresult = dx._call(factory, dx._FACTORY1_ENUM_ADAPTERS1, (wintypes.UINT, ctypes.POINTER(ctypes.c_void_p)),
                                   index, ctypes.byref(adapter))
                if hresult == dx.DXGI_ERROR_NOT_FOUND:
                    break
                dx._check(hresult, f"EnumAdapters1({index})")
                try:
                    desc = dx.DXGI_ADAPTER_DESC1()
                    dx._check(dx._call(adapter, dx._ADAPTER1_GET_DESC1, (ctypes.POINTER(dx.DXGI_ADAPTER_DESC1),),
                                       ctypes.byref(desc)), f"IDXGIAdapter1::GetDesc1({index})")
                finally:
                    dx._release(adapter)
                high, low = desc.AdapterLuid.HighPart & 0xFFFFFFFF, desc.AdapterLuid.LowPart & 0xFFFFFFFF
                found.append({"luid": f"0x{high:08x}_0x{low:08x}", "description": desc.Description,
                              "software": bool(desc.Flags & self.SOFTWARE), "dedicated": int(desc.DedicatedVideoMemory),
                              "shared": int(desc.SharedSystemMemory)})
        finally:
            dx._release(factory)
        return found


# --- memory and the Wi-Fi adapter ---

class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD), ("ullTotalPhys", ctypes.c_uint64),
                ("ullAvailPhys", ctypes.c_uint64), ("ullTotalPageFile", ctypes.c_uint64),
                ("ullAvailPageFile", ctypes.c_uint64), ("ullTotalVirtual", ctypes.c_uint64),
                ("ullAvailVirtual", ctypes.c_uint64), ("ullAvailExtendedVirtual", ctypes.c_uint64)]


def system_memory() -> dict:
    """``{"load": percent used, "total": bytes, "avail": bytes}`` of the physical memory (``GlobalMemoryStatusEx``)."""
    status = _MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(_MEMORYSTATUSEX)]
    kernel32.GlobalMemoryStatusEx.restype = wintypes.BOOL
    if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise ctypes.WinError(ctypes.get_last_error())
    return {"load": int(status.dwMemoryLoad), "total": int(status.ullTotalPhys), "avail": int(status.ullAvailPhys)}


class _IP_ADAPTER_ADDRESSES(ctypes.Structure):  # the head of IP_ADAPTER_ADDRESSES_LH, up to OperStatus
    pass


_IP_ADAPTER_ADDRESSES._fields_ = [
    ("Length", wintypes.DWORD), ("IfIndex", wintypes.DWORD), ("Next", ctypes.POINTER(_IP_ADAPTER_ADDRESSES)),
    ("AdapterName", ctypes.c_void_p), ("FirstUnicastAddress", ctypes.c_void_p), ("FirstAnycastAddress", ctypes.c_void_p),
    ("FirstMulticastAddress", ctypes.c_void_p), ("FirstDnsServerAddress", ctypes.c_void_p),
    ("DnsSuffix", ctypes.c_void_p), ("Description", ctypes.c_void_p), ("FriendlyName", ctypes.c_void_p),
    ("PhysicalAddress", ctypes.c_ubyte * 8), ("PhysicalAddressLength", wintypes.DWORD), ("Flags", wintypes.DWORD),
    ("Mtu", wintypes.DWORD), ("IfType", wintypes.DWORD), ("OperStatus", wintypes.DWORD)]

IF_TYPE_IEEE80211 = 71
IF_OPER_STATUS_UP = 1
_GAA_SKIP_ALL_ADDRESSES = 0x0001 | 0x0002 | 0x0004 | 0x0008  # unicast, anycast, multicast, DNS servers: only the head is read
_ERROR_BUFFER_OVERFLOW = 111


def active_wifi_description() -> Optional[str]:
    """The ``InterfaceDescription`` of the first wireless adapter that is up (``GetAdaptersAddresses``), or None."""
    iphlpapi = ctypes.WinDLL("iphlpapi")
    iphlpapi.GetAdaptersAddresses.argtypes = [wintypes.ULONG, wintypes.ULONG, ctypes.c_void_p, ctypes.c_void_p,
                                              ctypes.POINTER(wintypes.ULONG)]
    iphlpapi.GetAdaptersAddresses.restype = wintypes.ULONG
    size = wintypes.ULONG(16 * 1024)
    for _ in range(3):
        buffer = ctypes.create_string_buffer(size.value)
        code = iphlpapi.GetAdaptersAddresses(0, _GAA_SKIP_ALL_ADDRESSES, None, buffer, ctypes.byref(size))
        if code == _ERROR_BUFFER_OVERFLOW:
            continue
        if code:
            raise OSError(f"GetAdaptersAddresses failed (error {code})")
        node = ctypes.cast(buffer, ctypes.POINTER(_IP_ADAPTER_ADDRESSES))
        while node:
            adapter = node.contents
            if adapter.IfType == IF_TYPE_IEEE80211 and adapter.OperStatus == IF_OPER_STATUS_UP and adapter.Description:
                return ctypes.wstring_at(adapter.Description)
            node = adapter.Next
        return None
    raise OSError("GetAdaptersAddresses: buffer kept growing")


def pdh_instance_name(description: str) -> str:
    """An adapter description as PDH writes an instance name (``(``->``[``, ``)``->``]``, ``#`` and ``/`` -> ``_``), lower case."""
    return description.translate({ord("("): "[", ord(")"): "]", ord("#"): "_", ord("/"): "_"}).strip().lower()


def _adapter_memory(samples: "dict[str, float]", luid: str) -> float:
    """The value of the ``phys_0`` instance of ``luid`` in a ``GPU Adapter Memory`` array (KeyError when it has none)."""
    wanted = luid.lower()
    for name, value in samples.items():
        found = _MEMORY_RE.search(name)
        if found and found.group(1).lower() == wanted and found.group(2) == "0":
            return value
    raise KeyError(luid)


# --- the sampler ---

class PerfSampler:
    def __init__(self, reader: Any, adapters: Any, memory: Callable[[], dict], clock: Callable[[], float] = time.monotonic,
                 sleep: Optional[Callable[[float], Any]] = None, wifi: Callable[[], Optional[str]] = active_wifi_description,
                 log: Optional[Callable[[str], None]] = None) -> None:
        self._reader = reader
        self._adapters = adapters
        self._memory = memory
        self._clock = clock
        self._wifi = wifi
        self._log = log or _log.info
        self._stop = threading.Event()
        self._sleep = sleep or self._stop.wait
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._latest: dict = build_section(None, None, None, None, None)

        self._queries: "dict[str, Optional[PdhQuery]]" = {"cpu": None, "gpu": None, "net": None}
        self._cpu_paths: "tuple[Optional[str], Optional[str], Optional[str]]" = (None, None, None)  # utility, freq, perf
        self._histories = {name: History() for name in ("cpu", "gpu", "ram", "net_down", "net_up", "npu")}
        self._gpu_luid: Optional[str] = None
        self._npu_luid: Optional[str] = None
        self._gpu_memory_total: Optional[float] = None
        self._wifi_instance: Optional[str] = None
        self._next_discovery = 0.0
        self._rediscover = True
        self._last_logged: "dict[str, float]" = {}

    # --- public API ---

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="orizonx-perf", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(STOP_JOIN_S)
            if thread.is_alive():
                self._log("perf: sampler thread did not stop within %.0f s" % STOP_JOIN_S)
                return  # it may still be reading the queries: leave them open rather than close them under it
        self._close_queries()

    def latest(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._latest)

    def tick(self) -> None:
        """One sample of every measure; a measure that fails is absent for this tick."""
        now = self._clock()
        due = self._rediscover or now >= self._next_discovery
        if due:
            self._open_missing()  # a group that could not be opened is tried again at the next discovery
        errors = self._collect()
        engines = self._read_array("gpu", GPU_ENGINE, errors)
        if engines is None:
            engines = {}
        if due:
            self._discover(engines, now)
        section = build_section(
            self._measure("cpu", lambda: self._cpu(errors)), self._measure("gpu", lambda: self._gpu(engines, errors)),
            self._measure("ram", self._ram), self._measure("net", lambda: self._net(errors)),
            self._measure("npu", lambda: self._npu(engines)))
        with self._lock:
            self._latest = section

    # --- thread ---

    def _run(self) -> None:
        try:
            self._open_missing()  # the first sample of the rate counters is taken here, one tick before the first read
            deadline = self._clock() + TICK_S
            while not self._stop.is_set():
                self._sleep(max(0.0, deadline - self._clock()))
                if self._stop.is_set():
                    break
                try:
                    self.tick()
                except Exception as e:  # noqa: BLE001 - never die silently
                    self._note("tick", e)
                deadline = max(deadline + TICK_S, self._clock())
        except Exception as e:  # noqa: BLE001
            self._log(f"perf: sampler crashed: {e!r}")

    # --- queries ---

    def _open_missing(self) -> None:
        if self._queries["cpu"] is None:
            for paths in ([CPU_UTILITY, CPU_FREQUENCY, CPU_PERFORMANCE], [CPU_TIME, CPU_FREQUENCY, CPU_PERFORMANCE],
                          [CPU_UTILITY], [CPU_TIME]):
                try:
                    self._queries["cpu"] = self._reader.open(paths)
                except OSError as e:
                    self._note("cpu", e)
                    continue
                self._cpu_paths = (paths[0], paths[1] if len(paths) > 1 else None, paths[2] if len(paths) > 2 else None)
                break
        for group, paths in (("gpu", [GPU_ENGINE, GPU_DEDICATED, GPU_SHARED]), ("net", [NET_RECEIVED, NET_SENT])):
            if self._queries[group] is None:
                try:
                    self._queries[group] = self._reader.open(paths)
                except OSError as e:
                    self._note(group, e)

    def _close_queries(self) -> None:
        for group, query in list(self._queries.items()):
            self._queries[group] = None
            if query is not None:
                try:
                    self._reader.close(query)
                except Exception as e:  # noqa: BLE001
                    self._note(group, e)

    def _collect(self) -> "dict[str, Exception]":
        errors: "dict[str, Exception]" = {}
        for group, query in self._queries.items():
            if query is None:
                continue
            try:
                self._reader.collect(query)
            except Exception as e:  # noqa: BLE001 - the measures of this group fail for this tick
                errors[group] = e
        return errors

    def _counter(self, group: str, path: str, errors: "dict[str, Exception]") -> Any:
        if group in errors:
            raise errors[group]
        query = self._queries[group]
        if query is None or path not in query.counters:
            raise PdhError(f"{path} (not opened)", 0)
        return query.counters[path]

    def _read_array(self, group: str, path: str, errors: "dict[str, Exception]") -> Optional["dict[str, float]"]:
        try:
            return self._reader.array(self._counter(group, path, errors))
        except Exception as e:  # noqa: BLE001
            self._note(group, e)
            return None

    # --- discovery ---

    def _discover(self, engines: "dict[str, float]", now: float) -> None:
        """The GPU and NPU LUIDs and the Wi-Fi instance; at start, every 60 s, and when one of them vanished."""
        self._rediscover = False
        self._next_discovery = now + DISCOVERY_S
        self._gpu_luid = self._npu_luid = self._gpu_memory_total = None
        try:
            adapters = self._adapters.list()
        except Exception as e:  # noqa: BLE001 - without DXGI neither the GPU nor the NPU can be told apart
            self._note("gpu", e)
        else:
            self._gpu_luid = pick_gpu(adapters)
            if self._gpu_luid is not None:
                chosen = next(a for a in adapters if a["luid"] == self._gpu_luid)
                self._gpu_memory_total = (chosen["dedicated"] + chosen["shared"]) / GIB
            self._npu_luid = pick_npu(engine_types(engines), {a["luid"].lower() for a in adapters})
        self._wifi_instance = None
        try:
            description = self._wifi()
            if description:
                wanted = pdh_instance_name(description)
                names = self._reader.array(self._counter("net", NET_RECEIVED, {}))
                self._wifi_instance = next((name for name in names if pdh_instance_name(name) == wanted), None)
        except Exception as e:  # noqa: BLE001
            self._note("net", e)

    # --- the measures ---

    def _measure(self, name: str, compute: Callable[[], Optional[dict]]) -> Optional[dict]:
        try:
            return compute()
        except Exception as e:  # noqa: BLE001 - this measure is absent for this tick, the others go on
            self._note(name, e)
            return None

    def _cpu(self, errors: "dict[str, Exception]") -> dict:
        utility, frequency, performance = self._cpu_paths
        value = self._reader.value(self._counter("cpu", utility, errors))
        if value is None:
            raise ValueError("no sample yet")
        busy = int(round(max(0.0, min(100.0, value))))
        self._histories["cpu"].push(busy)
        cpu: dict = {"value": busy}
        if frequency and performance:
            try:
                mhz = self._reader.value(self._counter("cpu", frequency, errors))
                percent = self._reader.value(self._counter("cpu", performance, errors))
                if mhz is not None and percent is not None:
                    cpu["ghz"] = round(mhz * percent / 100 / 1000, 1)
            except Exception as e:  # noqa: BLE001 - the load without its frequency
                self._note("cpu", e)
        cpu["history"] = self._histories["cpu"].values()
        return cpu

    def _gpu(self, engines: "dict[str, float]", errors: "dict[str, Exception]") -> Optional[dict]:
        if self._gpu_luid is None:
            return None
        busy = engine_busy(engines, self._gpu_luid)
        if busy is None:
            self._rediscover = True  # the adapter's instances are gone (driver reloaded): look again next tick
            return None
        self._histories["gpu"].push(busy)
        gpu: dict = {"value": busy}
        try:
            used = (_adapter_memory(self._reader.array(self._counter("gpu", GPU_DEDICATED, errors)), self._gpu_luid)
                    + _adapter_memory(self._reader.array(self._counter("gpu", GPU_SHARED, errors)), self._gpu_luid))
            gpu["mem_used"] = round(used / GIB, 1)
            if self._gpu_memory_total is not None:
                gpu["mem_total"] = round(self._gpu_memory_total, 1)
        except Exception as e:  # noqa: BLE001 - the load without its memory
            self._note("gpu_memory", e)
            gpu.pop("mem_used", None)
        gpu["history"] = self._histories["gpu"].values()
        return gpu

    def _ram(self) -> dict:
        status = self._memory()
        value = int(status["load"])
        self._histories["ram"].push(value)
        return {"value": value, "used": round((status["total"] - status["avail"]) / GIB, 1),
                "total": round(status["total"] / GIB, 1), "history": self._histories["ram"].values()}

    def _net(self, errors: "dict[str, Exception]") -> Optional[dict]:
        if self._wifi_instance is None:
            return None
        received = self._reader.array(self._counter("net", NET_RECEIVED, errors))
        sent = self._reader.array(self._counter("net", NET_SENT, errors))
        if self._wifi_instance not in received or self._wifi_instance not in sent:
            self._rediscover = True  # the adapter went away or came back under another name
            return None
        down, up = max(0, int(round(received[self._wifi_instance]))), max(0, int(round(sent[self._wifi_instance])))
        self._histories["net_down"].push(down)
        self._histories["net_up"].push(up)
        return {"down": down, "up": up, "down_history": self._histories["net_down"].values(),
                "up_history": self._histories["net_up"].values()}

    def _npu(self, engines: "dict[str, float]") -> Optional[dict]:
        if self._npu_luid is None:
            return None
        busy = engine_busy(engines, self._npu_luid)
        if busy is None:
            self._rediscover = True
            return None
        self._histories["npu"].push(busy)
        return {"value": busy, "history": self._histories["npu"].values()}

    # --- log ---

    def _note(self, name: str, error: Exception) -> None:
        """Logs a failure of measure ``name``, at most once a minute."""
        now = self._clock()
        if now - self._last_logged.get(name, -LOG_EVERY_S) >= LOG_EVERY_S:
            self._last_logged[name] = now
            self._log(f"perf: {name} unavailable ({type(error).__name__}: {error})")


class PerfProvider:
    """The ``perf`` section of the hub: the latest sample of a sampler that starts at the first ``snapshot()``."""

    def __init__(self, log: Optional[Callable[[str], None]] = None, sampler_factory: Optional[Callable[[], Any]] = None) -> None:
        self._log = log or _log.info
        self._factory = sampler_factory or self._real_sampler
        self._sampler: Any = None
        self._lock = threading.Lock()

    def _real_sampler(self) -> PerfSampler:
        return PerfSampler(PdhReader(), DxgiAdapters(), system_memory, log=self._log)

    def snapshot(self) -> dict:
        with self._lock:
            if self._sampler is None:
                sampler = self._factory()
                sampler.start()
                self._sampler = sampler
            sampler = self._sampler
        return sampler.latest()

    def stop(self) -> None:
        with self._lock:
            sampler, self._sampler = self._sampler, None
        if sampler is not None:
            sampler.stop()

    close = stop

    def handle(self, action: dict) -> Optional[str]:
        """No action here: any id is logged and ignored."""
        self._log(f"perf: unknown action {action.get('id')!r} ignored")
        return None
