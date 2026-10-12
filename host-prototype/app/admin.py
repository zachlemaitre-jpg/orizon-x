"""Administrator commands of OrizonX.exe, run by the installer or after a UAC prompt (no Qt, no window).

    --cleanup                 turn the virtual screen off (its display path), like the app does at start-up
    --configure-vdd [--restart]
                              write the VDD XML: GPU of the primary display, one monitor, <global> refresh rates
                              limited to 60 Hz, common tablet resolutions;
                              give the Users group Modify rights on the XML's folder (icacls), so the app can edit
                              it without admin rights; with --restart, also restart an existing VDD device so it
                              reads them (admin)
    --install-driver <inf>    create the Root\\MttVDD device and install its driver (admin)
    --remove-driver           remove the device and its driver package (admin)
    --add-resolution WxH      add WxH at 60 Hz to the XML (rates limited to 60 Hz), then restart the device (admin, "Add exact resolution")

Exit code 0 on success, 1 on failure (2: wrong command line, see app/main.py), 3010 (ERROR_SUCCESS_REBOOT_REQUIRED) when
the command worked but Windows says a restart is needed to finish (--install-driver, --remove-driver, and the device
restart of --configure-vdd --restart / --add-resolution): the caller (the installer) treats it as a success. The exe is windowed (no console):
nothing is printed, details go to the admin log (relay-admin.log). The XML is the driver's own file (VDDPATH).
Every Windows-touching piece is a parameter of run() so tests use fakes.
"""
from __future__ import annotations

import argparse
import ctypes
import logging
import os
import re
import subprocess
from ctypes import wintypes
from pathlib import Path
from typing import Any, Callable

import tools
import vdd

DISPLAY_DEVICE_ATTACHED_TO_DESKTOP = 0x1
DISPLAY_DEVICE_PRIMARY_DEVICE = 0x4
EXIT_REBOOT_REQUIRED = 3010   # ERROR_SUCCESS_REBOOT_REQUIRED
VDD_HARDWARE_ID = "root\\mttvdd"
USERS_MODIFY_GRANT = "*S-1-5-32-545:(OI)(CI)M"   # BUILTIN\Users (SID, so any Windows language): Modify, inherited
ICACLS_TIMEOUT_S = 60
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


def _is_real_gpu(name: str, device_id: str) -> bool:
    """False for the virtual display itself and for adapters that are not a GPU: the RDP / Hyper-V / Sandbox indirect
    display (``SWD\\RemoteDisplayEnum...``, "Microsoft Remote Display Adapter") and "Microsoft Basic Display Adapter"."""
    device_id, lowered = device_id.strip().lower(), name.strip().lower()
    return (bool(lowered) and device_id != VDD_HARDWARE_ID
            and not device_id.startswith("swd\\remotedisplayenum")
            and "remote display adapter" not in lowered and "basic display" not in lowered)


def primary_gpu_name(adapters: Callable[[], list[Adapter]] = enum_display_adapters) -> str | None:
    """Friendly name of the GPU driving the primary display; None if unknown.

    Adapters that are not real GPUs (the virtual display, a remote-desktop display, the basic display adapter) are
    skipped; when the primary display is one of them, the first real GPU attached to the desktop is used instead.
    """
    listed = adapters()
    for name, device_id, flags in listed:
        if flags & DISPLAY_DEVICE_PRIMARY_DEVICE and _is_real_gpu(name, device_id):
            return name.strip()
    for name, device_id, flags in listed:
        if flags & DISPLAY_DEVICE_ATTACHED_TO_DESKTOP and _is_real_gpu(name, device_id):
            return name.strip()
    return None


# --- commandes ---

def system_command(args: list[str]) -> tuple[int, str]:
    """Runs a command without a window, without stdin; (exit code, its output). Raises OSError / TimeoutExpired."""
    result = subprocess.run(args, capture_output=True, creationflags=tools.NO_WINDOW, stdin=subprocess.DEVNULL,
                            timeout=ICACLS_TIMEOUT_S, cwd=tools.tool_cwd(args[0]))
    return result.returncode, (result.stdout + result.stderr).decode("oem", errors="replace").strip()


def grant_users_modify(folder: str, *, run_command: Callable[[list[str]], tuple[int, str]],
                       log: logging.Logger) -> None:
    """``icacls <folder> /grant *S-1-5-32-545:(OI)(CI)M``. Never raises: the XML is written either way, only the
    app's own later edits without admin rights depend on this, so a failure is logged and the command goes on."""
    icacls = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "icacls.exe")
    try:
        code, output = run_command([icacls, folder, "/grant", USERS_MODIFY_GRANT])
    except Exception as e:  # noqa: BLE001 - OSError (introuvable), TimeoutExpired...
        log.warning("Configure VDD: cannot give Users modify rights on %s: %s", folder, e)
        return
    if code == 0:
        log.info("Configure VDD: Users have modify rights on %s (%s)", folder, output)
    else:
        log.warning("Configure VDD: icacls on %s failed (exit code %d): %s", folder, code, output)


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
                  log: logging.Logger, run_command: Callable[[list[str]], tuple[int, str]] = system_command) -> int:
    log.info("VDD settings file: %s", controller.settings_path)
    try:
        gpu = gpu_name()
        if gpu is None:
            log.warning("Configure VDD: no real GPU found for the primary display (remote or virtual display only?), "
                        "the XML keeps its GPU setting")
        else:
            changed = controller.set_gpu_in_xml(gpu)
            log.info("Configure VDD: GPU %r%s", gpu, "" if changed else " (unchanged)")
        controller.ensure_single_monitor()
        # Before the resolutions: every <global> rate multiplies the mode count, and too many modes make the driver
        # create no monitor (vdd.limit_global_refresh_rates).
        changed = controller.limit_global_refresh_rates()
        log.info("Configure VDD: global refresh rates limited to 60 Hz%s", "" if changed else " (unchanged)")
        changed = controller.add_resolutions(vdd.COMMON_RESOLUTIONS)
        log.info("Configure VDD: common tablet resolutions %s", "added" if changed else "already present")
    finally:
        # The folder is the resolved settings path's (VDDPATH included), not a fixed one. Tried even when an XML
        # step failed (the exception still propagates: exit code 1); a grant failure alone never fails the command.
        grant_users_modify(str(Path(controller.settings_path).parent), run_command=run_command, log=log)
    if restart:
        if device.find_device() is None:
            log.info("Configure VDD: no virtual display device yet, nothing to restart")
        else:
            reboot = bool(device.restart_device())
            log.info("Configure VDD: device restarted")
            if reboot:
                log.warning("Configure VDD: Windows must restart before the device restart is complete")
                return EXIT_REBOOT_REQUIRED
    return 0


def install_driver(inf: str, *, device: Any, log: logging.Logger) -> int:
    reboot = device.install_driver(inf)
    log.info("Virtual display driver installed from %s", inf)
    if reboot:
        log.warning("Virtual display driver: Windows must restart before the driver is fully installed")
        return EXIT_REBOOT_REQUIRED
    return 0


def remove_driver(*, device: Any, log: logging.Logger) -> int:
    reboot = bool(device.remove_driver())
    log.info("Virtual display driver removed")
    if reboot:
        log.warning("Virtual display driver: Windows must restart before the driver is fully removed")
        return EXIT_REBOOT_REQUIRED
    return 0


def add_resolution(size: tuple[int, int], *, controller: Any, device: Any, log: logging.Logger) -> int:
    width, height = size
    if not device.is_admin():
        # Sans droits, le redémarrage du périphérique échouerait : le XML resterait changé sans effet.
        log.error("--add-resolution needs administrator rights: the VDD settings are left untouched")
        return 1
    log.info("VDD settings file: %s", controller.settings_path)
    if controller.limit_global_refresh_rates():  # first: it frees the mode budget (vdd.MAX_MODES)
        log.info("Global refresh rates limited to 60 Hz")
    changed = controller.add_resolutions([(width, height, 60)])
    log.info("Resolution %dx%d@60 %s", width, height, "added" if changed else "already in the XML")
    reboot = bool(device.restart_device())  # même déjà présente : le pilote ne l'a pas chargée, sinon on ne serait pas là
    log.info("Virtual display device restarted")
    if reboot:
        log.warning("Virtual display device: Windows must restart before the restart is complete")
        return EXIT_REBOOT_REQUIRED
    return 0


def run(args: argparse.Namespace, *, log: logging.Logger, vdd_factory: Callable[[], Any] | None = None,
        device: Any = None, display_factory: Callable[..., Any] | None = None,
        gpu_name: Callable[[], str | None] = primary_gpu_name,
        run_command: Callable[[list[str]], tuple[int, str]] | None = None) -> int:
    """Runs the admin command of `args`; 0 on success, 3010 on success needing a Windows restart, 1 on any
    failure (logged with its traceback)."""
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
                                 log=log, run_command=run_command or system_command)
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
