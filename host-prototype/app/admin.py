"""Administrator commands of OrizonX.exe, run by the installer or after a UAC prompt (no Qt, no window).

    --cleanup                 turn the virtual screen off (its display path), like the app does at start-up
    --configure-vdd [--restart]
                              write the VDD XML: GPU of the primary display, one monitor, common tablet resolutions;
                              with --restart, also restart an existing VDD device so it reads them (admin)
    --install-driver <inf>    create the Root\\MttVDD device and install its driver (admin)
    --remove-driver           remove the device and its driver package (admin)
    --add-resolution WxH      add WxH at 60 Hz to the XML, then restart the device (admin, "Add exact resolution")

Exit code 0 on success, 1 on failure (2: wrong command line, see app/main.py). The exe is windowed (no console):
nothing is printed, details go to the admin log (relay-admin.log). The XML is the driver's own file (VDDPATH).
Every Windows-touching piece is a parameter of run() so tests use fakes.
"""
from __future__ import annotations

import argparse
import ctypes
import logging
import re
from ctypes import wintypes
from typing import Any, Callable

import vdd

DISPLAY_DEVICE_PRIMARY_DEVICE = 0x4
VDD_HARDWARE_ID = "root\\mttvdd"
MIN_SIDE, MAX_SIDE = 320, 16384
_SIZE = re.compile(r"^\s*(\d+)\s*[xX×]\s*(\d+)\s*$")

Adapter = tuple[str, str, int]  # (DeviceString, DeviceID, StateFlags)


def parse_size(text: str) -> tuple[int, int]:
    """'2560x1600' -> (2560, 1600) (argparse type)."""
    match = _SIZE.match(text)
    if match is None:
        raise argparse.ArgumentTypeError(f"expected WIDTHxHEIGHT, got {text!r}")
    width, height = int(match.group(1)), int(match.group(2))
    if not (MIN_SIDE <= width <= MAX_SIDE and MIN_SIDE <= height <= MAX_SIDE):
        raise argparse.ArgumentTypeError(f"unsupported size {width}x{height}")
    return width, height


def add_arguments(parser: argparse.ArgumentParser) -> None:
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument("--cleanup", action="store_true", help="turn the virtual screen off, then exit")
    commands.add_argument("--configure-vdd", action="store_true",
                          help="write the virtual display settings (GPU, resolutions), then exit")
    commands.add_argument("--install-driver", metavar="INF", help="install the virtual display driver (admin)")
    commands.add_argument("--remove-driver", action="store_true", help="remove the virtual display driver (admin)")
    commands.add_argument("--add-resolution", metavar="WxH", type=parse_size,
                          help="add a resolution to the virtual display and restart it (admin)")
    parser.add_argument("--restart", action="store_true",
                        help="with --configure-vdd: restart the existing virtual display device (admin)")


def requested(args: argparse.Namespace) -> bool:
    """True if the command line asks for an admin command instead of the app (--restart alone: an error there)."""
    return bool(args.cleanup or args.configure_vdd or args.install_driver or args.remove_driver
                or args.add_resolution or args.restart)


# --- GPU de l'écran principal ---

class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("DeviceName", ctypes.c_wchar * 32), ("DeviceString", ctypes.c_wchar * 128),
                ("StateFlags", wintypes.DWORD), ("DeviceID", ctypes.c_wchar * 128),
                ("DeviceKey", ctypes.c_wchar * 128)]


def enum_display_adapters() -> list[Adapter]:
    """Every display adapter output Windows lists (EnumDisplayDevicesW, read-only)."""
    enum = ctypes.windll.user32.EnumDisplayDevicesW
    adapters: list[Adapter] = []
    index = 0
    while True:
        device = DISPLAY_DEVICEW()
        device.cb = ctypes.sizeof(device)
        if not enum(None, index, ctypes.byref(device), 0):
            return adapters
        adapters.append((device.DeviceString, device.DeviceID, device.StateFlags))
        index += 1


def primary_gpu_name(adapters: Callable[[], list[Adapter]] = enum_display_adapters) -> str | None:
    """Friendly name of the GPU driving the primary display, never the virtual display itself; None if unknown."""
    for name, device_id, flags in adapters():
        if flags & DISPLAY_DEVICE_PRIMARY_DEVICE and device_id.strip().lower() != VDD_HARDWARE_ID and name.strip():
            return name.strip()
    return None


# --- commandes ---

def _default_display_factory(controller: Any, log: Callable[[str], None]) -> Any:
    from virtual_display import VirtualDisplay  # import tardif : display_layout/injector ne servent qu'ici
    return VirtualDisplay(controller, log=log)


def _default_device() -> Any:
    import vdd_device
    return vdd_device


def cleanup(*, vdd_factory: Callable[[], Any], display_factory: Callable[..., Any], log: logging.Logger) -> int:
    display_factory(vdd_factory(), log.info).cleanup_on_start()
    return 0


def configure_vdd(*, controller: Any, device: Any, gpu_name: Callable[[], str | None], restart: bool,
                  log: logging.Logger) -> int:
    log.info("VDD settings file: %s", controller.settings_path)
    gpu = gpu_name()
    if gpu is None:
        log.warning("Configure VDD: GPU of the primary display not found, the XML keeps its GPU setting")
    else:
        changed = controller.set_gpu_in_xml(gpu)
        log.info("Configure VDD: GPU %r%s", gpu, "" if changed else " (unchanged)")
    controller.ensure_single_monitor()
    changed = controller.add_resolutions(vdd.COMMON_RESOLUTIONS)
    log.info("Configure VDD: common tablet resolutions %s", "added" if changed else "already present")
    if restart:
        if device.find_device() is None:
            log.info("Configure VDD: no virtual display device yet, nothing to restart")
        else:
            device.restart_device()
            log.info("Configure VDD: device restarted")
    return 0


def install_driver(inf: str, *, device: Any, log: logging.Logger) -> int:
    reboot = device.install_driver(inf)
    log.info("Virtual display driver installed from %s", inf)
    if reboot:
        log.warning("Virtual display driver: Windows must restart before the driver is fully installed")
    return 0


def remove_driver(*, device: Any, log: logging.Logger) -> int:
    device.remove_driver()
    log.info("Virtual display driver removed")
    return 0


def add_resolution(size: tuple[int, int], *, controller: Any, device: Any, log: logging.Logger) -> int:
    width, height = size
    if not device.is_admin():
        # Sans droits, le redémarrage du périphérique échouerait : le XML resterait changé sans effet.
        log.error("--add-resolution needs administrator rights: the VDD settings are left untouched")
        return 1
    log.info("VDD settings file: %s", controller.settings_path)
    changed = controller.add_resolutions([(width, height, 60)])
    log.info("Resolution %dx%d@60 %s", width, height, "added" if changed else "already in the XML")
    device.restart_device()  # même déjà présente : le pilote ne l'a pas chargée, sinon on ne serait pas là
    log.info("Virtual display device restarted")
    return 0


def run(args: argparse.Namespace, *, log: logging.Logger, vdd_factory: Callable[[], Any] | None = None,
        device: Any = None, display_factory: Callable[..., Any] | None = None,
        gpu_name: Callable[[], str | None] = primary_gpu_name) -> int:
    """Runs the admin command of `args`; 0 on success, 1 on any failure (logged with its traceback)."""
    vdd_factory = vdd_factory or vdd.VddController  # fichier du pilote, VDDPATH compris
    if args.restart and not args.configure_vdd:
        log.error("--restart only goes with --configure-vdd")
        return 1
    try:
        device = device or _default_device()
        if args.cleanup:
            log.info("Admin command: --cleanup")
            return cleanup(vdd_factory=vdd_factory, display_factory=display_factory or _default_display_factory,
                           log=log)
        if args.configure_vdd:
            log.info("Admin command: --configure-vdd%s", " --restart" if args.restart else "")
            return configure_vdd(controller=vdd_factory(), device=device, gpu_name=gpu_name, restart=args.restart,
                                 log=log)
        if args.install_driver:
            log.info("Admin command: --install-driver %s", args.install_driver)
            return install_driver(args.install_driver, device=device, log=log)
        if args.remove_driver:
            log.info("Admin command: --remove-driver")
            return remove_driver(device=device, log=log)
        if args.add_resolution:
            log.info("Admin command: --add-resolution %dx%d", *args.add_resolution)
            return add_resolution(args.add_resolution, controller=vdd_factory(), device=device, log=log)
    except Exception as e:  # noqa: BLE001 — code de sortie 1, détails dans le journal
        log.exception("Admin command failed: %s", e)
        return 1
    log.error("No admin command given")
    return 1
