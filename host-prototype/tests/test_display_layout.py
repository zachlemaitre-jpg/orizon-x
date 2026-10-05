import ctypes
import sys
import unittest

import display_layout as dl
from display_layout import MonitorKey, Rect

INVALID = dl.DISPLAYCONFIG_PATH_MODE_IDX_INVALID
SDC_EXPECTED = 0x80 | 0x20 | 0x200 | 0x400   # APPLY | USE_SUPPLIED | SAVE_TO_DATABASE | ALLOW_CHANGES

# Topologie inspirée du PC de l'utilisateur (notes vdd-control.md §5)
PANEL = (0x15D7E, 256)      # écran interne, principal, 2560x1600 en (0,0)
SIDE = (0x43F5D2, 409857)   # 24" à gauche, 1920x1080 en (-1920,0)
VDD = (0x7E6D58, 256)       # écran virtuel, même target id que l'écran interne
SPARE = (0x15D7E, 257)      # sortie inactive sans moniteur
VDD_KEY = MonitorKey(VDD[0], 0, VDD[1])
VDD_PATH = r"\\?\DISPLAY#MTT1337#1&28a6823a&0&UID256#{e6f07b5f-ee97-4a90-b076-33f57bf4eaa7}"


class PlaceTest(unittest.TestCase):
    PRIMARY = Rect(0, 0, 2560, 1600)

    def test_four_sides_with_primary_at_origin(self):
        size = (2880, 1800)
        self.assertEqual(dl.place(self.PRIMARY, size, "right"), (2560, -100))
        self.assertEqual(dl.place(self.PRIMARY, size, "left"), (-2880, -100))
        self.assertEqual(dl.place(self.PRIMARY, size, "above"), (-160, -1800))
        self.assertEqual(dl.place(self.PRIMARY, size, "below"), (-160, 1600))

    def test_smaller_screen_is_centred(self):
        self.assertEqual(dl.place(self.PRIMARY, (1280, 800), "right"), (2560, 400))
        self.assertEqual(dl.place(self.PRIMARY, (1280, 800), "below"), (640, 1600))

    def test_primary_not_at_origin_with_negative_coordinates(self):
        primary = Rect(-1920, -300, 1920, 1080)
        size = (1280, 800)
        self.assertEqual(dl.place(primary, size, "right"), (0, -160))
        self.assertEqual(dl.place(primary, size, "left"), (-3200, -160))
        self.assertEqual(dl.place(primary, size, "above"), (-1600, -1100))
        self.assertEqual(dl.place(primary, size, "below"), (-1600, 780))

    def test_unknown_side_is_rejected(self):
        with self.assertRaises(ValueError):
            dl.place(self.PRIMARY, (100, 100), "middle")

    def test_primary_alone_in_the_monitor_list_is_the_old_behaviour(self):
        size = (2880, 1800)
        for side in dl.SIDES:
            with self.subTest(side=side):
                self.assertEqual(dl.place(self.PRIMARY, size, side, [self.PRIMARY]),
                                 dl.place(self.PRIMARY, size, side))

    def test_second_monitor_on_the_chosen_side_is_never_overlapped(self):
        # 24" à droite du principal, plus haut que lui : l'écran virtuel va après lui, centré sur le principal.
        side = Rect(2560, -200, 1920, 1080)
        size = (2880, 1800)
        others = [self.PRIMARY, side]
        self.assertEqual(dl.place(self.PRIMARY, size, "right", others), (4480, -100))
        self.assertEqual(dl.place(self.PRIMARY, size, "left", others), (-2880, -100))   # rien à gauche
        self.assertEqual(dl.place(self.PRIMARY, size, "above", others), (-160, -2000))  # bord haut du 24"
        self.assertEqual(dl.place(self.PRIMARY, size, "below", others), (-160, 1600))

    def test_monitors_left_of_and_below_the_primary(self):
        left = Rect(-1920, 400, 1920, 1080)       # bas à 1480
        below = Rect(0, 1600, 1920, 1200)         # bas à 2800
        others = [left, self.PRIMARY, below]
        size = (1280, 800)
        self.assertEqual(dl.place(self.PRIMARY, size, "left", others), (-3200, 400))
        self.assertEqual(dl.place(self.PRIMARY, size, "below", others), (640, 2800))
        self.assertEqual(dl.place(self.PRIMARY, size, "right", others), (2560, 400))
        self.assertEqual(dl.place(self.PRIMARY, size, "above", others), (640, -800))

    def test_rects_never_overlap_for_any_side(self):
        side = Rect(2560, 0, 1920, 1080)
        others = [self.PRIMARY, side, Rect(-1920, -1080, 1920, 1080)]
        for name in dl.SIDES:
            with self.subTest(side=name):
                x, y = dl.place(self.PRIMARY, (2880, 1800), name, others)
                placed = Rect(x, y, 2880, 1800)
                for other in others:
                    overlap = (placed.left < other.left + other.width and other.left < placed.left + placed.width
                               and placed.top < other.top + other.height and other.top < placed.top + placed.height)
                    self.assertFalse(overlap, (placed, other))


class ScaleMathsTest(unittest.TestCase):
    def test_auto_scale_table(self):
        for dpi, expected in ((96, 100), (160, 125), (274, 200), (400, 300), (60, 100)):
            with self.subTest(dpi=dpi):
                self.assertEqual(dl.auto_scale(dpi), expected)

    def test_auto_scale_always_returns_a_step(self):
        for dpi in range(1, 1000, 7):
            self.assertIn(dl.auto_scale(dpi), dl.SCALE_STEPS)

    def test_scale_steps(self):
        self.assertEqual(dl.SCALE_STEPS, (100, 125, 150, 175, 200, 225, 250, 300))

    def test_relative_scale_index_table(self):
        table = (((200, 150), 2), ((150, 150), 0), ((100, 150), -2), ((300, 150), 5),
                 ((125, 100), 1), ((100, 100), 0), ((250, 200), 2), ((175, 250), -3))
        for (target, recommended), expected in table:
            with self.subTest(target=target, recommended=recommended):
                self.assertEqual(dl.relative_scale_index(target, recommended), expected)

    def test_relative_scale_index_rejects_unknown_values(self):
        with self.assertRaises(ValueError):
            dl.relative_scale_index(130, 100)


class PickModeTest(unittest.TestCase):
    def test_exact_match(self):
        self.assertEqual(dl.pick_mode([(1920, 1080), (2880, 1800)], 2880, 1800), (2880, 1800))

    def test_accepts_modes_with_refresh_rate(self):
        self.assertEqual(dl.pick_mode([(2880, 1800, 60)], 2880, 1800), (2880, 1800))

    def test_same_aspect_largest_that_fits(self):
        available = [(1280, 800), (2560, 1600), (1920, 1200), (2800, 1700), (3840, 2400)]
        self.assertEqual(dl.pick_mode(available, 2880, 1800), (2560, 1600))

    def test_same_aspect_within_one_percent(self):
        # 2944x1840 = 1,6 ; 2800x1752 = 1,598 (écart 0,1 %) ; 2900x1700 = 1,706, plus grand mais autre format
        self.assertEqual(dl.pick_mode([(2800, 1752), (2900, 1700)], 2944, 1840), (2800, 1752))

    def test_falls_back_to_largest_that_fits(self):
        available = [(1920, 1080), (2560, 1440), (3840, 2160)]
        self.assertEqual(dl.pick_mode(available, 2880, 1800), (2560, 1440))

    def test_none_when_nothing_fits(self):
        self.assertIsNone(dl.pick_mode([(3840, 2160), (2560, 1440)], 1280, 800))
        self.assertIsNone(dl.pick_mode([], 1280, 800))


class StructSizeTest(unittest.TestCase):
    def test_sizes_match_the_research_notes(self):
        self.assertEqual(ctypes.sizeof(ctypes.c_void_p), 8, "Python 64 bits requis")
        self.assertEqual(ctypes.sizeof(dl.PATH_INFO), 72)
        self.assertEqual(ctypes.sizeof(dl.MODE_INFO), 64)
        self.assertEqual(ctypes.sizeof(dl.DEVICE_INFO_HEADER), 20)
        self.assertEqual(ctypes.sizeof(dl.SOURCE_DEVICE_NAME), 84)
        self.assertEqual(ctypes.sizeof(dl.TARGET_DEVICE_NAME), 420)
        self.assertEqual(ctypes.sizeof(dl.SOURCE_DPI_SCALE_GET), 32)
        self.assertEqual(ctypes.sizeof(dl.SOURCE_DPI_SCALE_SET), 24)
        self.assertEqual(ctypes.sizeof(dl.VIDEO_SIGNAL_INFO), 48)
        self.assertEqual(ctypes.sizeof(dl.DEVMODEW), 220)

    def test_flag_constants(self):
        self.assertEqual(dl.SDC_FLAGS, SDC_EXPECTED)
        self.assertEqual((dl.QDC_ALL_PATHS, dl.QDC_ONLY_ACTIVE_PATHS), (1, 2))


# ---------- fake api ----------

def _path(target, source_id, active, src_idx=INVALID, tgt_idx=INVALID, available=True):
    adapter, target_id = target
    p = dl.PATH_INFO()
    p.sourceInfo.adapterId.LowPart = adapter
    p.sourceInfo.id = source_id
    p.sourceInfo.modeInfoIdx = src_idx
    p.targetInfo.adapterId.LowPart = adapter
    p.targetInfo.id = target_id
    p.targetInfo.modeInfoIdx = tgt_idx
    p.targetInfo.targetAvailable = available
    p.flags = dl.DISPLAYCONFIG_PATH_ACTIVE if active else 0
    return p


def _source_mode(adapter, source_id, w, h, x, y):
    m = dl.MODE_INFO()
    m.infoType = dl.DISPLAYCONFIG_MODE_INFO_TYPE_SOURCE
    m.id = source_id
    m.adapterId.LowPart = adapter
    m.sourceMode.width, m.sourceMode.height = w, h
    m.sourceMode.position.x, m.sourceMode.position.y = x, y
    return m


def _target_mode(adapter, target_id, w, h):
    m = dl.MODE_INFO()
    m.infoType = dl.DISPLAYCONFIG_MODE_INFO_TYPE_TARGET
    m.id = target_id
    m.adapterId.LowPart = adapter
    m.targetVideoSignalInfo.activeSize.cx, m.targetVideoSignalInfo.activeSize.cy = w, h
    return m


def _copy(items):
    return [type(item).from_buffer_copy(item) for item in items]


class FakeApi:
    """In-memory CCD: never touches Windows. Records every mutating call."""

    def __init__(self, vdd_active=True, vdd_available=True, with_side=True):
        self.active_paths = [_path(PANEL, 0, True, 0, 1)]
        self.modes = [_source_mode(PANEL[0], 0, 2560, 1600, 0, 0), _target_mode(PANEL[0], PANEL[1], 2560, 1600)]
        if with_side:
            self.active_paths.append(_path(SIDE, 0, True, 2, 3))
            self.modes += [_source_mode(SIDE[0], 0, 1920, 1080, -1920, 0), _target_mode(SIDE[0], SIDE[1], 1920, 1080)]
        inactive = [_path(SPARE, 0, False)]
        if vdd_active:
            n = len(self.modes)
            self.active_paths.append(_path(VDD, 0, True, n, n + 1))
            self.modes += [_source_mode(VDD[0], 0, 2880, 1800, 2560, -207), _target_mode(VDD[0], VDD[1], 2880, 1800)]
        else:
            inactive.append(_path(VDD, 0, False, available=vdd_available))
        self.all_paths = self.active_paths + inactive
        self.targets = {PANEL: ("NE160QDM-NYJ", r"\\?\DISPLAY#BOE0CB4#..."),
                        SIDE: ("24E6C", r"\\?\DISPLAY#AOC2406#..."),
                        VDD: ("VDD by MTT", VDD_PATH)}
        self.sources = {(PANEL[0], 0): r"\\.\DISPLAY1", (SIDE[0], 0): r"\\.\DISPLAY6", (VDD[0], 0): r"\\.\DISPLAY10"}
        self.dpi = {(PANEL[0], 0): (-2, 0, 4), (SIDE[0], 0): (0, 0, 3), (VDD[0], 0): (-2, 2, 5)}
        self.display_modes = {r"\\.\DISPLAY10": [(2880, 1800, 60), (2880, 1800, 30), (2560, 1600, 60), (800, 600, 60)]}
        self.query_rc = 0
        self.get_rc = 0
        self.set_rc = 0
        self.set_device_rc = 0
        self.queries = []
        self.set_calls = []
        self.device_sets = []

    def query(self, flags):
        self.queries.append(flags)
        if self.query_rc:
            return self.query_rc, [], []
        paths = self.all_paths if flags == dl.QDC_ALL_PATHS else self.active_paths
        return 0, _copy(paths), _copy(self.modes)

    def set_config(self, paths, modes, flags):
        self.set_calls.append((_copy(paths), _copy(modes), flags))
        return self.set_rc

    def get_device_info(self, packet):
        h = packet.header
        where = (h.adapterId.LowPart, h.id)
        if self.get_rc:
            return self.get_rc
        if h.type == dl.DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME and where in self.sources:
            packet.viewGdiDeviceName = self.sources[where]
        elif h.type == dl.DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME and where in self.targets:
            packet.monitorFriendlyDeviceName, packet.monitorDevicePath = self.targets[where]
        elif h.type == dl.DISPLAYCONFIG_DEVICE_INFO_GET_DPI_SCALE and where in self.dpi:
            packet.minScaleRel, packet.curScaleRel, packet.maxScaleRel = self.dpi[where]
        else:
            return 87
        return 0

    def set_device_info(self, packet):
        self.device_sets.append(type(packet).from_buffer_copy(packet))
        return self.set_device_rc

    def enum_modes(self, gdi_name):
        return list(self.display_modes.get(gdi_name, []))


def _keys(paths):
    return [(p.targetInfo.adapterId.LowPart, p.targetInfo.id) for p in paths]


class ReadTest(unittest.TestCase):
    def test_active_monitors(self):
        monitors = dl.active_monitors(FakeApi())
        self.assertEqual(len(monitors), 3)
        panel, side, vdd = monitors
        self.assertTrue(panel.is_primary)
        self.assertFalse(side.is_primary or vdd.is_primary)
        self.assertEqual(panel.rect, Rect(0, 0, 2560, 1600))
        self.assertEqual(side.rect, Rect(-1920, 0, 1920, 1080))
        self.assertEqual(vdd.rect, Rect(2560, -207, 2880, 1800))
        self.assertEqual(vdd.gdi_name, r"\\.\DISPLAY10")
        self.assertEqual(vdd.key, VDD_KEY)
        self.assertNotEqual(panel.key, vdd.key)   # même target id, LUID différent
        self.assertTrue(all(m.active for m in monitors))

    def test_find_vdd_monitor_active(self):
        found = dl.find_vdd_monitor(FakeApi())
        self.assertEqual(found.key, VDD_KEY)
        self.assertTrue(found.active)
        self.assertEqual(found.rect, Rect(2560, -207, 2880, 1800))
        self.assertEqual(found.name, "VDD by MTT")

    def test_find_vdd_monitor_inactive_uses_all_paths(self):
        api = FakeApi(vdd_active=False)
        found = dl.find_vdd_monitor(api)
        self.assertEqual(found.key, VDD_KEY)
        self.assertFalse(found.active)
        self.assertIsNone(found.rect)
        self.assertEqual(api.queries, [dl.QDC_ALL_PATHS])

    def test_find_vdd_monitor_none(self):
        api = FakeApi()
        del api.targets[VDD]
        self.assertIsNone(dl.find_vdd_monitor(api))

    def test_query_failure_raises_with_code(self):
        api = FakeApi()
        api.query_rc = 5
        with self.assertRaises(dl.DisplayLayoutError) as caught:
            dl.active_monitors(api)
        self.assertEqual(caught.exception.code, 5)
        self.assertIn("5", str(caught.exception))

    def test_available_modes_unique_sizes(self):
        self.assertEqual(dl.available_modes(VDD_KEY, FakeApi()), [(2880, 1800), (2560, 1600), (800, 600)])

    def test_available_modes_unknown_monitor(self):
        with self.assertRaises(dl.MonitorNotFoundError):
            dl.available_modes(MonitorKey(1, 2, 3), FakeApi())

    def test_get_scale(self):
        self.assertEqual(dl.get_scale(VDD_KEY, FakeApi()), (200, 150))

    def test_get_scale_failure_raises_with_code(self):
        api = FakeApi()
        api.get_rc = 31
        with self.assertRaises(dl.DisplayLayoutError) as caught:
            dl.get_scale(VDD_KEY, api)
        self.assertEqual(caught.exception.code, 31)


class SetPositionTest(unittest.TestCase):
    def test_moves_only_the_vdd_source_mode(self):
        api = FakeApi()
        dl.set_position(VDD_KEY, 2560, -100, api)
        self.assertEqual(len(api.set_calls), 1)
        paths, modes, flags = api.set_calls[0]
        self.assertEqual(flags, SDC_EXPECTED)
        self.assertEqual(_keys(paths), [PANEL, SIDE, VDD])
        vdd_mode = modes[paths[2].sourceInfo.modeInfoIdx].sourceMode
        self.assertEqual((vdd_mode.position.x, vdd_mode.position.y), (2560, -100))
        self.assertEqual((vdd_mode.width, vdd_mode.height), (2880, 1800))
        for before, after in zip(api.modes[:4], modes[:4]):
            self.assertEqual(bytes(before), bytes(after))

    def test_inactive_screen_is_an_error_without_any_call(self):
        api = FakeApi(vdd_active=False)
        with self.assertRaises(dl.MonitorNotFoundError):
            dl.set_position(VDD_KEY, 0, 0, api)
        self.assertEqual(api.set_calls, [])

    def test_failure_raises_with_code(self):
        api = FakeApi()
        api.set_rc = 87
        with self.assertRaises(dl.DisplayLayoutError) as caught:
            dl.set_position(VDD_KEY, 1, 2, api)
        self.assertEqual(caught.exception.code, 87)
        self.assertIn("SetDisplayConfig", str(caught.exception))
        self.assertIn("87", str(caught.exception))


class SetPathActiveTest(unittest.TestCase):
    def test_deactivate_submits_the_other_paths_with_compacted_modes(self):
        api = FakeApi()
        self.assertTrue(dl.set_path_active(VDD_KEY, False, api=api))
        self.assertEqual(len(api.set_calls), 1)
        paths, modes, flags = api.set_calls[0]
        self.assertEqual(flags, SDC_EXPECTED)
        self.assertEqual(_keys(paths), [PANEL, SIDE])
        self.assertEqual(len(modes), 4)
        for p in paths:
            self.assertTrue(p.flags & dl.DISPLAYCONFIG_PATH_ACTIVE)
            self.assertEqual(modes[p.sourceInfo.modeInfoIdx].infoType, dl.DISPLAYCONFIG_MODE_INFO_TYPE_SOURCE)
            self.assertEqual(modes[p.targetInfo.modeInfoIdx].id, p.targetInfo.id)

    def test_deactivate_compacts_modes_when_vdd_is_not_last(self):
        api = FakeApi()
        # Le VDD en tête : ses modes sont aux indices 0-1 après réordonnancement
        api.active_paths = [api.active_paths[2], api.active_paths[0], api.active_paths[1]]
        dl.set_path_active(VDD_KEY, False, api=api)
        paths, modes, _flags = api.set_calls[0]
        self.assertEqual(_keys(paths), [PANEL, SIDE])
        self.assertEqual(len(modes), 4)
        panel_mode = modes[paths[0].sourceInfo.modeInfoIdx].sourceMode
        side_mode = modes[paths[1].sourceInfo.modeInfoIdx].sourceMode
        self.assertEqual((panel_mode.width, side_mode.position.x), (2560, -1920))

    def test_deactivate_when_already_inactive_does_nothing(self):
        api = FakeApi(vdd_active=False)
        self.assertFalse(dl.set_path_active(VDD_KEY, False, api=api))
        self.assertEqual(api.set_calls, [])

    def test_refuses_to_disconnect_the_last_display(self):
        api = FakeApi()
        api.active_paths = [api.active_paths[2]]
        with self.assertRaises(dl.DisplayLayoutError):
            dl.set_path_active(VDD_KEY, False, api=api)
        self.assertEqual(api.set_calls, [])

    def test_activate_without_mode_lets_windows_choose(self):
        api = FakeApi(vdd_active=False)
        self.assertTrue(dl.set_path_active(VDD_KEY, True, api=api))
        paths, modes, flags = api.set_calls[0]
        self.assertEqual(flags, SDC_EXPECTED)
        self.assertEqual(_keys(paths), [PANEL, SIDE, VDD])
        vdd = paths[2]
        self.assertTrue(vdd.flags & dl.DISPLAYCONFIG_PATH_ACTIVE)
        self.assertEqual((vdd.sourceInfo.modeInfoIdx, vdd.targetInfo.modeInfoIdx), (INVALID, INVALID))
        self.assertEqual(len(modes), 4)
        self.assertNotIn(SPARE, _keys(paths))

    def test_activate_with_mode_adds_a_source_mode_right_of_the_desktop(self):
        api = FakeApi(vdd_active=False)
        dl.set_path_active(VDD_KEY, True, mode=(2560, 1600), api=api)
        paths, modes, _flags = api.set_calls[0]
        vdd = paths[2]
        self.assertEqual(vdd.sourceInfo.modeInfoIdx, 4)
        self.assertEqual(vdd.targetInfo.modeInfoIdx, INVALID)
        mode = modes[4]
        self.assertEqual(mode.infoType, dl.DISPLAYCONFIG_MODE_INFO_TYPE_SOURCE)
        self.assertEqual((mode.id, mode.adapterId.LowPart), (0, VDD[0]))
        self.assertEqual((mode.sourceMode.width, mode.sourceMode.height), (2560, 1600))
        self.assertEqual(mode.sourceMode.pixelFormat, dl.DISPLAYCONFIG_PIXELFORMAT_32BPP)
        self.assertEqual((mode.sourceMode.position.x, mode.sourceMode.position.y), (2560, 0))

    def test_activate_with_mode_and_position(self):
        api = FakeApi(vdd_active=False)
        dl.set_path_active(VDD_KEY, True, mode=(2880, 1800), position=(-160, -1800), api=api)
        paths, modes, _flags = api.set_calls[0]
        pos = modes[paths[2].sourceInfo.modeInfoIdx].sourceMode.position
        self.assertEqual((pos.x, pos.y), (-160, -1800))

    def test_position_without_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            dl.set_path_active(VDD_KEY, True, position=(0, 0), api=FakeApi(vdd_active=False))

    def test_activate_when_already_active_without_mode_does_nothing(self):
        api = FakeApi()
        self.assertFalse(dl.set_path_active(VDD_KEY, True, api=api))
        self.assertEqual(api.set_calls, [])

    def test_activate_when_already_active_with_mode_changes_size_in_place(self):
        api = FakeApi()
        self.assertTrue(dl.set_path_active(VDD_KEY, True, mode=(2560, 1600), api=api))
        paths, modes, flags = api.set_calls[0]
        self.assertEqual(flags, SDC_EXPECTED)
        self.assertEqual(len(paths), 3)
        self.assertEqual(paths[2].targetInfo.modeInfoIdx, INVALID)
        mode = modes[paths[2].sourceInfo.modeInfoIdx].sourceMode
        self.assertEqual((mode.width, mode.height, mode.position.x, mode.position.y), (2560, 1600, 2560, -207))

    def _vdd_source_0_taken(self, candidates):
        """Inactive VDD whose source 0 is already driven by another output of the same adapter."""
        api = FakeApi(vdd_active=False)
        other = (VDD[0], 257)
        n = len(api.modes)
        api.active_paths.append(_path(other, 0, True, n, n + 1))
        api.modes += [_source_mode(VDD[0], 0, 1920, 1080, 2560, 0), _target_mode(VDD[0], 257, 1920, 1080)]
        api.all_paths = api.active_paths + [_path(VDD, source, False) for source in candidates]
        return api

    def test_activation_takes_the_first_candidate_whose_source_is_free(self):
        api = self._vdd_source_0_taken(candidates=(0, 1, 2))
        self.assertTrue(dl.set_path_active(VDD_KEY, True, mode=(2880, 1800), api=api))
        paths, modes, _flags = api.set_calls[0]
        vdd = [p for p in paths if (p.targetInfo.adapterId.LowPart, p.targetInfo.id) == VDD]
        self.assertEqual(len(vdd), 1)
        self.assertEqual(vdd[0].sourceInfo.id, 1)
        self.assertTrue(vdd[0].flags & dl.DISPLAYCONFIG_PATH_ACTIVE)
        self.assertEqual(modes[vdd[0].sourceInfo.modeInfoIdx].id, 1)

    def test_activation_fails_only_when_every_candidate_source_is_taken(self):
        api = self._vdd_source_0_taken(candidates=(0,))
        with self.assertRaises(dl.DisplayLayoutError) as caught:
            dl.set_path_active(VDD_KEY, True, api=api)
        self.assertIn("already used", str(caught.exception))
        self.assertEqual(api.set_calls, [])

    def test_unavailable_monitor_is_an_error(self):
        api = FakeApi(vdd_active=False, vdd_available=False)
        with self.assertRaises(dl.DisplayLayoutError):
            dl.set_path_active(VDD_KEY, True, api=api)
        self.assertEqual(api.set_calls, [])

    def test_unknown_monitor(self):
        api = FakeApi()
        with self.assertRaises(dl.MonitorNotFoundError):
            dl.set_path_active(MonitorKey(9, 0, 9), True, api=api)
        self.assertEqual(api.set_calls, [])

    def test_failure_raises_with_code(self):
        api = FakeApi(vdd_active=False)
        api.set_rc = 1610
        with self.assertRaises(dl.DisplayLayoutError) as caught:
            dl.set_path_active(VDD_KEY, True, api=api)
        self.assertEqual(caught.exception.code, 1610)


class SetScaleTest(unittest.TestCase):
    def _sent(self, api):
        self.assertEqual(len(api.device_sets), 1)
        packet = api.device_sets[0]
        self.assertEqual(packet.header.type, dl.DISPLAYCONFIG_DEVICE_INFO_SET_DPI_SCALE)
        self.assertEqual(packet.header.size, 24)
        self.assertEqual((packet.header.adapterId.LowPart, packet.header.id), (VDD[0], 0))   # la source
        return packet.scaleRel

    def test_sets_relative_value(self):
        api = FakeApi()
        self.assertEqual(dl.set_scale(VDD_KEY, 175, api), 175)
        self.assertEqual(self._sent(api), 1)

    def test_clamps_to_the_maximum(self):
        api = FakeApi()
        self.assertEqual(dl.set_scale(VDD_KEY, 400, api), 300)
        self.assertEqual(self._sent(api), 5)

    def test_clamps_to_100(self):
        api = FakeApi()
        self.assertEqual(dl.set_scale(VDD_KEY, 90, api), 100)
        self.assertEqual(self._sent(api), -2)

    def test_failure_raises_with_code(self):
        api = FakeApi()
        api.set_device_rc = 87
        with self.assertRaises(dl.DisplayLayoutError) as caught:
            dl.set_scale(VDD_KEY, 200, api)
        self.assertEqual(caught.exception.code, 87)
        self.assertIn("DisplayConfigSetDeviceInfo", str(caught.exception))

    def test_inactive_screen_is_an_error(self):
        api = FakeApi(vdd_active=False)
        with self.assertRaises(dl.MonitorNotFoundError):
            dl.set_scale(VDD_KEY, 200, api)
        self.assertEqual(api.device_sets, [])


def _vdd_installed() -> bool:
    import winreg
    base = r"SYSTEM\CurrentControlSet\Enum\ROOT\DISPLAY"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                with winreg.OpenKey(root, winreg.EnumKey(root, i)) as sub:
                    try:
                        ids, _kind = winreg.QueryValueEx(sub, "HardwareID")
                    except OSError:
                        continue
                    if any(str(x).lower() == r"root\mttvdd" for x in ids):
                        return True
    except OSError:
        return False
    return False


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class WindowsReadOnlySmokeTest(unittest.TestCase):
    """Real QueryDisplayConfig / DisplayConfigGetDeviceInfo / EnumDisplaySettings only: nothing is changed."""

    def test_active_monitors_has_a_primary(self):
        monitors = dl.active_monitors()
        self.assertGreaterEqual(len(monitors), 1)
        self.assertEqual(sum(1 for m in monitors if m.is_primary), 1)
        primary = next(m for m in monitors if m.is_primary)
        self.assertEqual((primary.rect.left, primary.rect.top), (0, 0))
        self.assertTrue(primary.gdi_name.startswith("\\\\.\\DISPLAY"))

    def test_find_vdd_monitor_on_this_pc(self):
        if not _vdd_installed():
            self.skipTest("VDD is not installed on this PC")
        found = dl.find_vdd_monitor()
        self.assertIsNotNone(found)
        self.assertIn("MTT1337", found.device_path.upper())
        if found.active:
            current, recommended = dl.get_scale(found.key)
            self.assertIn(current, dl.DPI_VALS)
            self.assertIn(recommended, dl.DPI_VALS)
            modes = dl.available_modes(found.key)
            self.assertIn((found.rect.width, found.rect.height), modes)


if __name__ == "__main__":
    unittest.main()
