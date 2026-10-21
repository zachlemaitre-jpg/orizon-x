"""The arithmetic behind the performance blocks of the Actions mode (spec 2026-10-21 perf-blocks §2), without ctypes.

* ``engine_busy``: the Task Manager's percentage of one graphics adapter, from the ``\\GPU Engine(*)\\Utilization
  Percentage`` instances (``pid_<pid>_luid_0x<high>_0x<low>_phys_<n>_eng_<n>_engtype_<type>``): the per-process instances of
  one engine are summed, the busiest engine wins, the result is clamped to 0..100;
* ``engine_types`` / ``pick_npu`` / ``pick_gpu``: which LUID is the GPU (the largest DXGI hardware adapter that is not the
  Virtual Display Driver) and which one is the NPU (a LUID with only ``compute*`` engines that DXGI does not list);
* ``History``: the ring of the last 60 points of a curve;
* ``build_section``: the ``perf`` section of the state; a measure that is missing is left out.

A LUID is written without its ``luid_`` prefix, lower case: ``0x00000000_0x00015cba``.
"""
from __future__ import annotations

import re
from collections import deque
from typing import Iterable, Optional

ENGINE_RE = re.compile(r"luid_(0x[0-9a-fA-F]+_0x[0-9a-fA-F]+)_phys_(\d+)_eng_(\d+)_engtype_(.*)$")
VIRTUAL_DISPLAY = "virtual display"  # Orizon X's own Virtual Display Driver, never the GPU to show
HISTORY_SIZE = 60


def engine_busy(samples: "dict[str, float]", luid: str) -> Optional[int]:
    """Task-manager style % of one adapter: sum the per-process instances of each engine (phys, eng), keep the busiest
    engine, clamp 0..100, round. None when no instance of that luid exists."""
    wanted = luid.lower()
    per_engine: "dict[tuple[str, str], float]" = {}
    for name, value in samples.items():
        found = ENGINE_RE.search(name)
        if not found or found.group(1).lower() != wanted:
            continue
        key = (found.group(2), found.group(3))
        per_engine[key] = per_engine.get(key, 0.0) + float(value)
    if not per_engine:
        return None
    return int(round(max(0.0, min(100.0, max(per_engine.values())))))


def engine_types(instance_names: Iterable[str]) -> "dict[str, set[str]]":
    """luid -> set of engtype strings (lower-cased, e.g. {'3d', 'copy', 'compute 0'})."""
    types: "dict[str, set[str]]" = {}
    for name in instance_names:
        found = ENGINE_RE.search(name)
        if found:
            types.setdefault(found.group(1).lower(), set()).add(found.group(4).strip().lower())
    return types


def pick_npu(engines: "dict[str, set[str]]", dxgi_luids: "set[str]") -> Optional[str]:
    """A luid not among the DXGI adapters whose engine types all start with 'compute'."""
    for luid, kinds in engines.items():
        if luid in dxgi_luids or not kinds:
            continue
        if all(kind.startswith("compute") for kind in kinds):
            return luid
    return None


def pick_gpu(adapters: "list[dict]") -> Optional[str]:
    """adapters: {'luid','description','software':bool,'dedicated':int,'shared':int}. Drop software ones and any whose
    description contains 'Virtual Display' ; keep the largest dedicated+shared. Returns its luid string 'luid_0x..._0x...'
    form without the 'luid_' prefix, i.e. '0x00000000_0x00015cba'."""
    best: Optional[dict] = None
    for adapter in adapters:
        if adapter.get("software") or VIRTUAL_DISPLAY in str(adapter.get("description", "")).lower():
            continue
        if best is None or _memory(adapter) > _memory(best):
            best = adapter
    return best["luid"] if best is not None else None


def _memory(adapter: dict) -> int:
    return int(adapter.get("dedicated", 0)) + int(adapter.get("shared", 0))


class History:
    """The last ``size`` points of a curve, oldest first."""

    def __init__(self, size: int = HISTORY_SIZE) -> None:
        self._values: "deque[int]" = deque(maxlen=size)

    def push(self, v: int) -> None:
        self._values.append(v)

    def values(self) -> "list[int]":
        """Oldest first, at most ``size`` entries."""
        return list(self._values)


def build_section(cpu, gpu, ram, net, npu) -> dict:
    """Each arg a dict or None; None ones are left out. Always 'available': True when at least one is present, else
    {'available': False}."""
    section = {name: measure for name, measure in (("cpu", cpu), ("gpu", gpu), ("ram", ram), ("net", net), ("npu", npu))
               if measure is not None}
    if not section:
        return {"available": False}
    return dict({"available": True}, **section)
