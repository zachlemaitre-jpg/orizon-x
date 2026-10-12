"""Talks to the VDD virtual display driver (no Qt here): pipe PING for detection, and its XML settings file.

Facts this module relies on (docs/notes/vdd-control.md):
- the pipe takes ONE UTF-16LE command per connection; the server replies with WriteFile and disconnects at once,
  which throws away anything the client has not read yet, so the client arms an overlapped read BEFORE writing;
- every reload command (RELOAD_DRIVER, SETDISPLAYCOUNT, SETGPU…) crashes the driver host (upstream issue #351):
  this module only ever sends PING;
- the driver reads the XML only when the device starts, so XML edits take effect after a device restart
  (vdd_device.restart_device, admin);
- the XML is <folder>\\vdd_settings.xml, the folder being HKLM\\SOFTWARE\\MikeTheTech\\VirtualDisplayDriver\\VDDPATH
  when set, else C:\\VirtualDisplayDriver (resolve_settings_path).

XML limits: ElementTree keeps elements, attributes, text and comments inside <vdd_settings>, but not comments or
processing instructions outside the root element, nor the original declaration quoting and attribute order. The
driver does not care. Empty elements are written <x></x>, never <x/>, because the driver's own XML rewriter breaks on
self-closing elements.
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable, Iterable

PIPE_NAME = r"\\.\pipe\MTTVirtualDisplayPipe"
SETTINGS_FILE_NAME = "vdd_settings.xml"
DEFAULT_SETTINGS_PATH = Path(r"C:\VirtualDisplayDriver") / SETTINGS_FILE_NAME
# Dossier des réglages choisi à l'installation du pilote (son « confpath ») ; il y lit VDDPATH\vdd_settings.xml.
VDDPATH_KEY = r"SOFTWARE\MikeTheTech\VirtualDisplayDriver"
VDDPATH_VALUE = "VDDPATH"
BACKUP_SUFFIX = ".bak-orizonx"
_log = logging.getLogger("orizonx.vdd")
PIPE_TIMEOUT_S = 2.0
# Le serveur n'a aucune instance de canal pendant quelques ms entre deux clients : on réessaie un peu, pas 2 s,
# sinon chaque test « pilote absent » coûterait 2 s.
CONNECT_RETRY_S = 0.5
MAX_COMMAND_CHARS = 127  # le pilote lit au plus 254 octets ; au-delà la commande est ignorée sans réponse

# Résolutions de tablettes courantes (spec §8), écrites dans le XML par l'installateur.
COMMON_RESOLUTIONS: tuple[tuple[int, int, int], ...] = tuple((w, h, 60) for w, h in (
    (2880, 1800), (2560, 1600), (1920, 1200), (1280, 800), (2000, 1200), (2800, 1752), (2960, 1848),
    (2944, 1840), (3000, 1876), (3200, 2000), (2304, 1440), (2048, 1536), (2732, 2048), (2224, 1668),
    (2360, 1640), (2388, 1668), (2160, 1620), (2400, 1080), (1920, 1080), (2560, 1440), (1600, 2560),
))

# Fichier créé quand le XML n'existe pas encore (installation neuve) : un seul écran, GPU au choix du pilote,
# 60 Hz seulement (chaque g_refresh_rate multiplie le nombre de modes, issue #254), 1920×1080 par défaut.
MINIMAL_XML = """<?xml version='1.0' encoding='utf-8'?>
<vdd_settings>
    <monitors>
        <count>1</count>
    </monitors>
    <gpu>
        <friendlyname>default</friendlyname>
    </gpu>
    <global>
        <g_refresh_rate>60</g_refresh_rate>
    </global>
    <resolutions>
        <resolution>
            <width>1920</width>
            <height>1080</height>
            <refresh_rate>60</refresh_rate>
        </resolution>
    </resolutions>
    <options>
        <CustomEdid>false</CustomEdid>
        <PreventSpoof>false</PreventSpoof>
        <EdidCeaOverride>false</EdidCeaOverride>
        <HardwareCursor>true</HardwareCursor>
        <SDR10bit>false</SDR10bit>
        <HDRPlus>false</HDRPlus>
        <logging>false</logging>
        <debuglogging>false</debuglogging>
    </options>
</vdd_settings>
"""

_INDENT = "    "

Resolution = tuple[int, int, int]

# Refresh rates kept in <global> (VddController.limit_global_refresh_rates): 60 Hz only.
GLOBAL_REFRESH_RATES: tuple[int, ...] = (60,)
# Conservative cap on the number of display modes the driver is asked to create (see add_resolutions).
# Measured on the user's PC: 26 resolutions x 6 global rates = 156 modes made the driver silently create NO monitor
# (device "OK", DISPLAY\MTT1337 absent); 7 resolutions x 6 rates and 26 resolutions x 1 rate both worked.
MAX_MODES = 64


class VddError(Exception):
    """The VDD pipe or settings file could not be used (log text, plain English)."""


class PipeError(VddError):
    """A pipe operation failed; `winerror` is the Windows error code when there is one."""

    def __init__(self, message: str, winerror: int | None = None) -> None:
        super().__init__(message if winerror is None else f"{message} (Windows error {winerror})")
        self.winerror = winerror


def read_vddpath() -> str | None:
    """HKLM\\SOFTWARE\\MikeTheTech\\VirtualDisplayDriver\\VDDPATH (64-bit view, read-only), or None if absent."""
    try:
        import winreg
    except ImportError:  # pas Windows
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, VDDPATH_KEY, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            value, kind = winreg.QueryValueEx(key, VDDPATH_VALUE)
    except OSError:
        return None
    if not isinstance(value, str):
        return None
    return winreg.ExpandEnvironmentStrings(value) if kind == winreg.REG_EXPAND_SZ else value


def resolve_settings_path(read_registry: Callable[[], str | None] = read_vddpath) -> Path:
    """Where the driver reads its XML: <VDDPATH>\\vdd_settings.xml when VDDPATH is set (a folder, as in the
    driver's initpath(): docs/notes/vdd-control.md §2), else C:\\VirtualDisplayDriver\\vdd_settings.xml."""
    try:
        folder = read_registry()
    except OSError:
        folder = None
    folder = (folder or "").strip().strip('"').strip()
    return Path(folder) / SETTINGS_FILE_NAME if folder else DEFAULT_SETTINGS_PATH


class VddController:
    """Detects the driver (pipe PING) and edits its XML settings (effective at the next device start).

    settings_path None (the app, the admin commands): the driver's own file, VDDPATH override included.
    """

    def __init__(self, settings_path: Path | None = None,
                 transport: Callable[[str], bytes] | None = None, pipe_name: str = PIPE_NAME,
                 timeout: float = PIPE_TIMEOUT_S, read_registry: Callable[[], str | None] = read_vddpath) -> None:
        self.settings_path = (Path(settings_path) if settings_path is not None
                              else resolve_settings_path(read_registry))
        self.backup_path = self.settings_path.with_name(self.settings_path.name + BACKUP_SUFFIX)
        self._transport = transport or (lambda message: pipe_transport(message, pipe_name=pipe_name,
                                                                       timeout=timeout))

    # --- pipe ---

    def is_installed(self) -> bool:
        """True when the driver answers PING. False while it is absent, disabled or restarting. Never raises."""
        try:
            reply = self._transport("PING")
        except Exception:  # noqa: BLE001 - toute erreur de canal veut dire « pilote injoignable »
            return False
        # Avec la journalisation du pilote active, des lignes de log précèdent la réponse.
        if isinstance(reply, str):
            return "PONG" in reply
        return isinstance(reply, (bytes, bytearray)) and b"PONG" in reply

    # --- XML ---

    def read_resolutions(self) -> list[Resolution]:
        """(width, height, refresh) of every valid <resolution>, in file order; [] when the file does not exist."""
        if not self.settings_path.exists():
            return []
        return _resolutions(self._load().getroot())

    def limit_global_refresh_rates(self, rates: Iterable[int] = GLOBAL_REFRESH_RATES) -> bool:
        """Makes <global> hold exactly the given <g_refresh_rate> entries (default: 60 only). True if the file changed.

        Why: the driver replicates every <resolution> at every <global><g_refresh_rate>, so modes = resolutions x
        rates. A file with 26 resolutions and the rates 60, 90, 120, 144, 165, 244 (156 modes) made the driver
        silently stop creating its monitor (device "OK", monitor DISPLAY\\MTT1337 absent); the same 26 resolutions
        with only 60 work (docs/superpowers/specs/2026-10-05-installer-virtual-display-design.md §8). Comments and
        other elements of <global> are kept; <global> is created when missing.
        """
        wanted = []
        for rate in rates:
            rate = int(rate)
            if rate <= 0:
                raise ValueError(f"invalid refresh rate: {rate!r}")
            if rate not in wanted:
                wanted.append(rate)
        if not wanted:
            raise ValueError("no refresh rate given")
        tree = self._load_or_template()
        root = tree.getroot()
        section = root.find("global")
        changed = section is None
        if section is None:
            section = _child(root, "global", level=1)
        closing = section[-1].tail if len(section) else None
        kept: set[int] = set()
        removed = False
        for entry in list(section.iterfind("g_refresh_rate")):
            try:
                rate = int((entry.text or "").strip())
            except ValueError:
                rate = None
            if rate in wanted and rate not in kept:
                kept.add(rate)
            else:
                section.remove(entry)
                removed = True
        if removed and len(section) and closing is not None:
            section[-1].tail = closing  # the closing indentation followed the last child, which may be gone
        for rate in wanted:
            if rate not in kept:
                _append(section, _leaf("g_refresh_rate", str(rate)), level=2)
                changed = True
        if not (changed or removed):
            return False
        self._save(tree)
        return True

    def add_resolutions(self, resolutions: Iterable[Resolution], max_modes: int = MAX_MODES) -> bool:
        """Adds the missing (w, h, hz) entries, keeping everything else. True if the file changed.

        The entries are taken in the given order, which is their priority (the tablet's exact resolution first, then
        COMMON_RESOLUTIONS). An entry that would bring the driver's mode count above `max_modes` is skipped with a
        warning. The driver creates one mode per resolution for each of its own refresh rate and the <global> rates,
        so a resolution costs len({global rates} | {its own rate}) modes. Too many modes make the driver create no
        monitor at all (see limit_global_refresh_rates); the cap is deliberately far below that failure point.
        """
        wanted = [_check_resolution(r) for r in resolutions]
        tree = self._load_or_template()
        root = tree.getroot()
        present = set(_resolutions(root))
        rates = _global_rates(root)
        modes = _mode_count(root)
        added = []
        for resolution in wanted:
            if resolution in present:
                continue
            cost = len(rates | {resolution[2]})
            if modes + cost > max_modes:
                _log.warning("VDD: resolution %dx%d@%d skipped, the settings file would exceed %d display modes "
                             "(now %d): too many modes make the driver create no monitor",
                             *resolution, max_modes, modes)
                continue
            present.add(resolution)
            modes += cost
            added.append(resolution)
        if not added:
            return False
        section = _child(root, "resolutions", level=1)
        for width, height, refresh in added:
            entry = ET.Element("resolution")
            for tag, value in (("width", width), ("height", height), ("refresh_rate", refresh)):
                _append(entry, _leaf(tag, str(value)), level=3)
            _append(section, entry, level=2)
        self._save(tree)
        return True

    def ensure_single_monitor(self) -> bool:
        """<monitors><count> = 1 (the app shows/hides the screen by its display path, never by count)."""
        return self._set_text(("monitors", "count"), "1")

    def set_gpu_in_xml(self, friendly_name: str) -> bool:
        """<gpu><friendlyname> = the adapter that renders the virtual screen. True if the file changed."""
        name = friendly_name.strip()
        if not name:
            raise ValueError("empty GPU name")
        return self._set_text(("gpu", "friendlyname"), name)

    # --- internes ---

    def _set_text(self, path: tuple[str, str], value: str) -> bool:
        tree = self._load_or_template()
        section = _child(tree.getroot(), path[0], level=1)
        leaf = section.find(path[1])
        if leaf is None:
            _append(section, _leaf(path[1], value), level=2)
        elif (leaf.text or "").strip() == value:
            return False
        else:
            leaf.text = value
        self._save(tree)
        return True

    def _load(self) -> ET.ElementTree:
        # insert_comments : sans ça ElementTree jette les commentaires du fichier.
        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
        try:
            return ET.parse(self.settings_path, parser=parser)
        except ET.ParseError as error:
            raise VddError(f"invalid VDD settings file {self.settings_path}: {error}") from error
        except OSError as error:
            raise VddError(f"cannot read {self.settings_path}: {error}") from error

    def _load_or_template(self) -> ET.ElementTree:
        if self.settings_path.exists():
            return self._load()
        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
        return ET.ElementTree(ET.fromstring(MINIMAL_XML, parser=parser))

    def _save(self, tree: ET.ElementTree) -> None:
        """Atomic write (temp file in the same folder, then os.replace), after a one-time backup of the original."""
        folder = self.settings_path.parent
        temp_name = None
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if self.settings_path.exists() and not self.backup_path.exists():
                shutil.copy2(self.settings_path, self.backup_path)
            fd, temp_name = tempfile.mkstemp(prefix=self.settings_path.name + ".", suffix=".tmp", dir=folder)
            with os.fdopen(fd, "wb") as stream:
                tree.write(stream, encoding="utf-8", xml_declaration=True, short_empty_elements=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.settings_path)
            temp_name = None
        except OSError as error:
            raise VddError(f"cannot write {self.settings_path}: {error}") from error
        finally:
            if temp_name is not None:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass


def _check_resolution(resolution: Resolution) -> Resolution:
    width, height, refresh = (int(v) for v in resolution)
    if width <= 0 or height <= 0 or refresh <= 0:
        raise ValueError(f"invalid resolution: {resolution!r}")
    return width, height, refresh


def _resolutions(root: ET.Element) -> list[Resolution]:
    found = []
    for entry in root.iterfind("resolutions/resolution"):
        try:
            found.append((int(entry.findtext("width", "")), int(entry.findtext("height", "")),
                          int(entry.findtext("refresh_rate", ""))))
        except ValueError:
            continue  # entrée incomplète ou illisible : on la laisse telle quelle, on ne la compte pas
    return found


def _global_rates(root: ET.Element) -> set[int]:
    found = set()
    for entry in root.iterfind("global/g_refresh_rate"):
        try:
            rate = int((entry.text or "").strip())
        except ValueError:
            continue
        if rate > 0:
            found.add(rate)
    return found


def _mode_count(root: ET.Element) -> int:
    """Display modes the driver will create: per resolution, its own rate plus the <global> rates (deduplicated)."""
    rates = _global_rates(root)
    return sum(len(rates | {refresh}) for _w, _h, refresh in _resolutions(root))


def _leaf(tag: str, text: str) -> ET.Element:
    element = ET.Element(tag)
    element.text = text
    return element


def _child(parent: ET.Element, tag: str, level: int) -> ET.Element:
    """The first <tag> under parent, created (empty, indented) when missing."""
    element = parent.find(tag)
    if element is None:
        element = ET.Element(tag)
        _append(parent, element, level=level)
    return element


def _append(parent: ET.Element, child: ET.Element, level: int) -> None:
    """Appends child at depth `level` with the file's 4-space indentation, so the result stays readable."""
    inner = "\n" + _INDENT * level
    closing = "\n" + _INDENT * (level - 1)
    if len(parent):
        parent[-1].tail = inner
    else:
        parent.text = inner
    child.tail = closing
    parent.append(child)


# --- client du canal nommé (ctypes, E/S « overlapped ») ---

def pipe_transport(message: str, *, pipe_name: str = PIPE_NAME, timeout: float = PIPE_TIMEOUT_S,
                   connect_retry: float = CONNECT_RETRY_S) -> bytes:
    """Sends one command (UTF-16LE, no terminator) and returns the raw reply bytes (b"" when the server answers
    nothing). PING is answered in ASCII, GETSETTINGS in UTF-16LE: decoding is up to the caller.

    Raises PipeError (with the Windows error code) when the pipe is absent, busy beyond the retry window, or silent
    beyond `timeout`; ValueError for a command the driver would silently drop.
    """
    if len(message) > MAX_COMMAND_CHARS:
        raise ValueError(f"command longer than {MAX_COMMAND_CHARS} characters")
    if os.name != "nt":
        raise PipeError("named pipes need Windows")
    return _Win32Pipe(pipe_name, timeout, connect_retry).exchange(message.encode("utf-16le"))


class _Win32Pipe:
    ERROR_FILE_NOT_FOUND = 2
    ERROR_BROKEN_PIPE = 109
    ERROR_PIPE_BUSY = 231
    ERROR_NO_DATA = 232
    ERROR_PIPE_NOT_CONNECTED = 233
    ERROR_MORE_DATA = 234
    ERROR_IO_PENDING = 997
    WAIT_OBJECT_0 = 0
    WAIT_TIMEOUT = 0x102
    _ENDED = (ERROR_BROKEN_PIPE, ERROR_NO_DATA, ERROR_PIPE_NOT_CONNECTED)  # le serveur a raccroché : fin normale

    _api = None

    def __init__(self, name: str, timeout: float, connect_retry: float) -> None:
        self.name = name
        self.timeout = timeout
        self.connect_retry = connect_retry
        self.k32, self.OVERLAPPED = _Win32Pipe._load_api()

    @classmethod
    def _load_api(cls):
        if cls._api is None:
            import ctypes
            from ctypes import wintypes

            class OVERLAPPED(ctypes.Structure):
                _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                            ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                            ("hEvent", wintypes.HANDLE)]

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            lp_ov = ctypes.POINTER(OVERLAPPED)
            lp_dword = ctypes.POINTER(wintypes.DWORD)
            signatures = {
                "CreateFileW": ([wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                 wintypes.DWORD, wintypes.HANDLE], wintypes.HANDLE),
                "CreateEventW": ([wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
                "ReadFile": ([wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, lp_dword, lp_ov], wintypes.BOOL),
                "WriteFile": ([wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD, lp_dword, lp_ov], wintypes.BOOL),
                "GetOverlappedResult": ([wintypes.HANDLE, lp_ov, lp_dword, wintypes.BOOL], wintypes.BOOL),
                "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
                "CancelIoEx": ([wintypes.HANDLE, lp_ov], wintypes.BOOL),
                "WaitNamedPipeW": ([wintypes.LPCWSTR, wintypes.DWORD], wintypes.BOOL),
                "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
            }
            for name, (argtypes, restype) in signatures.items():
                function = getattr(k32, name)
                function.argtypes = argtypes
                function.restype = restype
            cls._api = (k32, OVERLAPPED)
        return cls._api

    def exchange(self, payload: bytes) -> bytes:
        import ctypes
        from ctypes import wintypes

        deadline = time.monotonic() + self.timeout
        handle = self._connect(deadline)
        read_event = write_event = None
        read_pending = False
        try:
            read_event = self._event()
            write_event = self._event()
            read_ov = self.OVERLAPPED(hEvent=read_event)
            write_ov = self.OVERLAPPED(hEvent=write_event)
            buffer = ctypes.create_string_buffer(4096)
            count = wintypes.DWORD()
            reply = bytearray()
            # 1) lecture armée AVANT l'écriture : le serveur répond puis raccroche aussitôt.
            read_pending = self._arm_read(handle, buffer, read_ov)
            # 2) écriture de la commande.
            if not self.k32.WriteFile(handle, payload, len(payload), None, ctypes.byref(write_ov)):
                error = ctypes.get_last_error()
                if error != self.ERROR_IO_PENDING:
                    raise PipeError("pipe write failed", error)
                if self.k32.WaitForSingleObject(write_event, self._remaining_ms(deadline)) != self.WAIT_OBJECT_0:
                    self._cancel(handle, write_ov)
                    raise PipeError("pipe write timed out")
                if not self.k32.GetOverlappedResult(handle, ctypes.byref(write_ov), ctypes.byref(count), False):
                    raise PipeError("pipe write failed", ctypes.get_last_error())
            # 3) collecte jusqu'à ce que le serveur raccroche.
            while read_pending:
                if self.k32.WaitForSingleObject(read_event, self._remaining_ms(deadline)) != self.WAIT_OBJECT_0:
                    self._cancel(handle, read_ov)
                    read_pending = False
                    if reply:
                        return bytes(reply)  # réponse reçue mais pas de raccrochage : on s'en contente
                    raise PipeError(f"no reply from the pipe within {self.timeout:g} s")
                ok = self.k32.GetOverlappedResult(handle, ctypes.byref(read_ov), ctypes.byref(count), False)
                error = 0 if ok else ctypes.get_last_error()
                read_pending = False
                if ok or error == self.ERROR_MORE_DATA:
                    reply += buffer.raw[:count.value]
                    read_pending = self._arm_read(handle, buffer, read_ov)
                elif error not in self._ENDED:
                    raise PipeError("pipe read failed", error)
            return bytes(reply)
        finally:
            if read_pending:
                self._cancel(handle, read_ov)
            self.k32.CloseHandle(handle)
            for event in (read_event, write_event):
                if event:
                    self.k32.CloseHandle(event)

    def _connect(self, deadline: float):
        import ctypes

        generic_rw = 0x80000000 | 0x40000000
        open_existing = 3
        file_flag_overlapped = 0x40000000
        invalid = ctypes.c_void_p(-1).value
        retry_until = min(deadline, time.monotonic() + self.connect_retry)
        while True:
            handle = self.k32.CreateFileW(self.name, generic_rw, 0, None, open_existing, file_flag_overlapped, None)
            if handle and handle != invalid:
                return handle
            error = ctypes.get_last_error()
            if error not in (self.ERROR_FILE_NOT_FOUND, self.ERROR_PIPE_BUSY) or time.monotonic() >= retry_until:
                raise PipeError("cannot open the VDD pipe", error)
            if error == self.ERROR_PIPE_BUSY:
                self.k32.WaitNamedPipeW(self.name, max(1, min(200, self._remaining_ms(retry_until))))
            else:
                time.sleep(0.02)  # pas d'instance entre deux clients : elle revient en quelques ms

    def _arm_read(self, handle, buffer, overlapped) -> bool:
        """Starts an overlapped read; False when the server already hung up."""
        import ctypes

        if self.k32.ReadFile(handle, buffer, len(buffer), None, ctypes.byref(overlapped)):
            return True  # terminée tout de suite : l'événement est signalé, GetOverlappedResult la récupère
        error = ctypes.get_last_error()
        if error in (self.ERROR_IO_PENDING, self.ERROR_MORE_DATA):
            return True
        if error in self._ENDED:
            return False
        raise PipeError("pipe read failed", error)

    def _cancel(self, handle, overlapped) -> None:
        """Cancels a pending operation and waits for it, so Windows never writes into freed buffers."""
        import ctypes
        from ctypes import wintypes

        self.k32.CancelIoEx(handle, ctypes.byref(overlapped))
        ignored = wintypes.DWORD()
        self.k32.GetOverlappedResult(handle, ctypes.byref(overlapped), ctypes.byref(ignored), True)

    def _event(self):
        handle = self.k32.CreateEventW(None, True, False, None)
        if not handle:
            import ctypes
            raise PipeError("CreateEventW failed", ctypes.get_last_error())
        return handle

    @staticmethod
    def _remaining_ms(deadline: float) -> int:
        return max(0, int((deadline - time.monotonic()) * 1000))
