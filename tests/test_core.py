# -*- coding: utf-8 -*-
"""Unit-Tests der Kernlogik (ohne Oberfläche).  Aufruf:  python tests\\test_core.py"""

import copy
import importlib.util
import json
import math
import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "output")
os.makedirs(OUT, exist_ok=True)

spec = importlib.util.spec_from_file_location("bpg", os.path.join(ROOT, "Fremdprofilierung.py"))
bpg = importlib.util.module_from_spec(spec)
sys.modules["bpg"] = bpg
spec.loader.exec_module(bpg)

L, P = bpg.make_layer, bpg.make_profile


def bounds(geom):
    return [(round(g.top, 9), round(g.bottom, 9)) for g in geom.layers]


class NumberTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(bpg.parse_number("0,4"), 0.4)
        self.assertEqual(bpg.parse_number("1.5"), 1.5)
        self.assertEqual(bpg.parse_number(" -2,25 "), -2.25)
        self.assertEqual(bpg.parse_number("−1,5"), -1.5)
        self.assertEqual(bpg.parse_number("1.234,5"), 1234.5)
        self.assertEqual(bpg.parse_number("1,234.5"), 1234.5)
        self.assertIsNone(bpg.parse_number(""))
        self.assertIsNone(bpg.parse_number("abc"))
        self.assertIsNone(bpg.parse_number(float("nan")))
        self.assertIsNone(bpg.parse_number(True))
        self.assertEqual(bpg.parse_number(3), 3.0)

    def test_format(self):
        self.assertEqual(bpg.fmt_num(0.4), "0,4")
        self.assertEqual(bpg.fmt_num(2.0), "2")
        self.assertEqual(bpg.fmt_num(2.85), "2,85")
        self.assertEqual(bpg.fmt_num(-0.001), "0")
        self.assertEqual(bpg.fmt_fixed(-0.0, 1), "0,0")
        self.assertEqual(bpg.fmt_fixed(45.2, 2), "45,20")


class GeometryTests(unittest.TestCase):
    def test_thickness(self):
        g = bpg.compute_profile_geometry(P("x", [L("a", 0.4), L("b", 0.1), L("c", 2.5)]))
        self.assertEqual(bounds(g), [(0, 0.4), (0.4, 0.5), (0.5, 3.0)])
        self.assertAlmostEqual(g.total, 3.0)
        self.assertIsNone(g.top_h)
        self.assertFalse(g.errors)

    def test_depth_and_errors(self):
        g = bpg.compute_profile_geometry(P("x", [L("a", 0.4), L("b", 0.3), L("c", 1.2)], "depth"))
        self.assertTrue(g.errors)
        self.assertEqual(bounds(g), [(0, 0.4), (0.4, 0.4), (0.4, 1.2)])
        self.assertTrue(g.layers[1].error)

    def test_height_requires_ok(self):
        g = bpg.compute_profile_geometry(P("x", [L("a", 44.0)], "height"))
        self.assertTrue(g.errors and g.ok_problem)
        g = bpg.compute_profile_geometry(P("x", [L("a", 44.5), L("b", 43.0)], "height", ok=45.0))
        self.assertEqual(bounds(g), [(0, 0.5), (0.5, 2.0)])
        self.assertAlmostEqual(g.top_h, 45.0)
        self.assertAlmostEqual(g.bottom_h, 43.0)

    def test_heights_below_sea_level(self):
        g = bpg.compute_profile_geometry(P("x", [L("a", -1.5), L("b", -4.0)], "height", ok=-0.5))
        self.assertEqual(bounds(g), [(0, 1.0), (1.0, 3.5)])

    def test_uk_only_and_consistency(self):
        g = bpg.compute_profile_geometry(P("x", [L("a", 1.0), L("b", 2.0)], uk=40.0))
        self.assertAlmostEqual(g.top_h, 43.0)
        g = bpg.compute_profile_geometry(P("x", [L("a", 1.0), L("b", 1.0)], ok=50.0, uk=47.0))
        self.assertTrue(g.warnings)
        g = bpg.compute_profile_geometry(P("x", [L("a", 1.0)], ok=40.0, uk=41.0))
        self.assertTrue(g.errors)

    def test_missing_values(self):
        g = bpg.compute_profile_geometry(P("x", [L("a", 0.5), L("b", None), L("c", 0.5)]))
        self.assertEqual(bounds(g), [(0, 0.5), (0.5, 0.5), (0.5, 1.0)])
        self.assertTrue(g.layers[1].missing)


class ConversionTests(unittest.TestCase):
    def test_round_trips(self):
        profile = P("x", [L("a", 0.4), L("b", 0.35), L("c", 0.75), L("d", 2.0), L("e", None)], ok=45.2)
        reference = bounds(bpg.compute_profile_geometry(profile))
        for mode in ("depth", "height", "thickness", "height", "depth", "thickness"):
            ok, reason = bpg.convert_input_mode(profile, mode)
            self.assertTrue(ok, reason)
            self.assertEqual(profile["input_mode"], mode)
            self.assertEqual(bounds(bpg.compute_profile_geometry(profile)), reference)
        self.assertIsNone(profile["layers"][4]["value"])   # leere Zeile am Ende bleibt leer

    def test_gap_before_known_value_is_refused(self):
        profile = P("x", [L("a", 0.4), L("b", None), L("c", 0.75)])
        ok, reason = bpg.convert_input_mode(profile, "depth")
        self.assertFalse(ok)
        self.assertIn("Schicht 2", reason)
        self.assertEqual(profile["input_mode"], "thickness")

    def test_height_needs_reference(self):
        profile = P("x", [L("a", 1.0)])
        ok, reason = bpg.convert_input_mode(profile, "height")
        self.assertFalse(ok)
        self.assertEqual(profile["input_mode"], "thickness")

    def test_refuses_with_errors(self):
        profile = P("x", [L("a", 1.0), L("b", 0.5)], "depth")
        ok, _ = bpg.convert_input_mode(profile, "thickness")
        self.assertFalse(ok)


class AxisTests(unittest.TestCase):
    def test_steps(self):
        self.assertEqual(bpg.choose_label_step(7.0, 12.0), 0.5)
        self.assertEqual(bpg.choose_label_step(1.0, 12.0), 0.1)
        self.assertEqual(bpg.choose_label_step(30.0, 12.0), 2.0)
        self.assertEqual(bpg.major_step_for(0.5), 1.0)
        self.assertEqual(bpg.major_step_for(0.1), 0.5)
        self.assertAlmostEqual(bpg.major_step_for(0.25), 0.5)
        self.assertAlmostEqual(bpg.fine_step_for(0.5, 2.0), 0.1)
        self.assertEqual(bpg.decimals_for(0.5), 1)
        self.assertEqual(bpg.decimals_for(0.25), 2)
        self.assertEqual(bpg.decimals_for(2.0), 0)

    def resolve(self, geoms, tops, mode="depth", **settings):
        st = dict(bpg.DEFAULT_SETTINGS)
        st.update(settings)
        messages = []
        axis = bpg.resolve_axis(st, mode, tops, geoms, lambda span: 12.0, messages)
        return axis, messages

    def test_auto_range_rounds_outward(self):
        g = bpg.compute_profile_geometry(P("x", [L("a", 6.83)]))
        axis, _ = self.resolve([g], [0.0])
        self.assertEqual((axis.v_top, axis.v_bot), (0.0, -7.0))
        ticks = axis.ticks()
        self.assertEqual(len(ticks), 15)
        self.assertEqual(axis.format(ticks[0][0]), "7,0 m")
        self.assertEqual(axis.format(ticks[-1][0]), "0,0 m")

    def test_manual_and_invalid_range(self):
        g = bpg.compute_profile_geometry(P("x", [L("a", 5.0)]))
        axis, _ = self.resolve([g], [0.0], range_top=1.0, range_bottom=3.0)
        self.assertEqual((axis.v_top, axis.v_bot), (-1.0, -3.0))
        axis, messages = self.resolve([g], [0.0], range_top=3.0, range_bottom=1.0)
        self.assertTrue(messages)
        self.assertEqual((axis.v_top, axis.v_bot), (0.0, -5.0))

    def test_height_mode(self):
        g1 = bpg.compute_profile_geometry(P("a", [L("x", 3.0)], ok=45.2))
        g2 = bpg.compute_profile_geometry(P("b", [L("x", 1.0)], ok=44.1))
        axis, _ = self.resolve([g1, g2], [45.2, 44.1], mode="height")
        self.assertGreaterEqual(axis.v_top, 45.2)
        self.assertLessEqual(axis.v_bot, 42.2)
        self.assertEqual(axis.format(45.0), "45,0 m")

    def test_too_fine_step(self):
        g = bpg.compute_profile_geometry(P("x", [L("a", 30.0)]))
        axis, messages = self.resolve([g], [0.0], tick_step=0.01)
        self.assertGreater(axis.label_step, 0.01)
        self.assertTrue(messages)


class SpreadTests(unittest.TestCase):
    def test_random_no_overlap(self):
        rnd = random.Random(7)
        for _ in range(400):
            n = rnd.randint(1, 12)
            heights = [rnd.uniform(0.2, 0.8) for _ in range(n)]
            desired = sorted((rnd.uniform(0, 10) for _ in range(n)), reverse=True)
            gap = 0.1
            ys = bpg.spread_labels(desired, heights, 10.0, 0.0, gap)
            for i in range(n - 1):
                self.assertGreaterEqual(ys[i] - ys[i + 1] + 1e-9, (heights[i] + heights[i + 1]) / 2 + gap)
            need = sum(heights) + gap * (n - 1)
            if need <= 10.0:
                self.assertLessEqual(ys[0] + heights[0] / 2, 10.0 + 1e-9)
                self.assertGreaterEqual(ys[-1] - heights[-1] / 2, -1e-9)

    def test_keeps_free_positions(self):
        ys = bpg.spread_labels([9.0, 5.0, 1.0], [0.3, 0.3, 0.3], 10.0, 0.0, 0.1)
        self.assertEqual([round(y, 9) for y in ys], [9.0, 5.0, 1.0])


class ProjectFileTests(unittest.TestCase):
    def test_legacy_migration(self):
        legacy = {
            "config": {"main_title": "Alt", "scale_title": "Tiefe (m)", "scale_from": "", "scale_to": "5",
                       "scale_step": "", "show_staff": True, "show_grid": False, "show_values": True,
                       "show_nhn": True, "align_profiles": False},
            "profiles": [{"title": "P1", "layers": [
                {"name": "A", "details": "d", "thickness": 0.5, "top_nhn": 45.0, "bottom_nhn": None,
                 "color": "#123456"},
                {"name": "B", "details": "", "thickness": 1.5, "top_nhn": None, "bottom_nhn": 43.0,
                 "color": "#654321"}]}],
        }
        project = bpg.normalize_project(legacy)
        self.assertEqual(project["settings"]["main_title"], "Alt")
        self.assertEqual(project["settings"]["range_bottom"], 5.0)
        self.assertFalse(project["settings"]["show_grid"])
        profile = project["profiles"][0]
        self.assertEqual(profile["ok"], 45.0)
        self.assertEqual([l["value"] for l in profile["layers"]], [0.5, 1.5])
        self.assertEqual(profile["layers"][0]["color"], "#123456")

    def test_roundtrip_and_prune(self):
        project = bpg.default_project()
        uid = project["profiles"][0]["layers"][0]["uid"]
        project["overrides"] = {"layer:" + uid: {"dx": 1.0, "dy": 0.0, "scale": 1.2},
                                "layer:deadbeef": {"dx": 1.0, "dy": 0.0, "scale": 1.0},
                                "main_title": {"dx": 0.0, "dy": 0.5, "scale": 1.0}}
        path = os.path.join(OUT, "roundtrip.json")
        bpg.save_project_file(project, path)
        loaded = bpg.load_project_file(path)
        self.assertIn("layer:" + uid, loaded["overrides"])
        self.assertIn("main_title", loaded["overrides"])
        self.assertNotIn("layer:deadbeef", loaded["overrides"])
        self.assertEqual(loaded["profiles"], project["profiles"])

    def test_duplicate_uids_fixed(self):
        data = {"settings": {}, "profiles": [{"uid": "a", "layers": [{"uid": "a"}, {"uid": "b"}]},
                                             {"uid": "b", "layers": []}]}
        project = bpg.normalize_project(data)
        uids = [project["profiles"][0]["uid"], project["profiles"][1]["uid"]] + \
               [l["uid"] for l in project["profiles"][0]["layers"]]
        self.assertEqual(len(uids), len(set(uids)))


class ImportTests(unittest.TestCase):
    def test_header_format(self):
        rows = [["Profil", "Schicht", "Tiefe (m)", "Beschreibung", "Farbe", "OK"],
                ["BK 1", "A", "0,3", "x", "ff0000", "45,2"],
                ["BK 1", "B", "1,2", None, None, None],
                ["BK 2", "A", "0,5", None, "#00ff00", None]]
        profiles = bpg.profiles_from_rows(rows)
        self.assertEqual([p["title"] for p in profiles], ["BK 1", "BK 2"])
        self.assertEqual(profiles[0]["input_mode"], "depth")
        self.assertEqual(profiles[0]["ok"], 45.2)
        self.assertEqual(profiles[0]["layers"][0]["color"], "#ff0000")
        self.assertEqual(profiles[1]["layers"][0]["color"], "#00ff00")

    def test_block_format(self):
        rows = [["Bohrung 1", None], ["A", 0.4, "humos"], ["B", "1,5"], [None, None],
                ["C", 2.0], ["D", 1.0]]
        profiles = bpg.profiles_from_rows(rows)
        self.assertEqual(len(profiles), 2)
        self.assertEqual(profiles[0]["title"], "Bohrung 1")
        self.assertEqual([l["value"] for l in profiles[0]["layers"]], [0.4, 1.5])
        self.assertEqual(profiles[0]["layers"][0]["details"], "humos")
        self.assertEqual(profiles[1]["title"], "Profil 2")


class EditingTests(unittest.TestCase):
    def test_reorder_keeps_thickness_in_depth_mode(self):
        profile = P("x", [L("a", 0.3), L("b", 0.85), L("c", 1.05), L("d", 1.8)], "depth")
        ok, _ = bpg.reorder_layers(profile, [0, 2, 1, 3])
        self.assertTrue(ok)
        self.assertEqual([l["name"] for l in profile["layers"]], ["a", "c", "b", "d"])
        self.assertEqual([round(l["value"], 6) for l in profile["layers"]], [0.3, 0.5, 1.05, 1.8])

    def test_reverse_in_height_mode(self):
        profile = P("x", [L("a", 44.5), L("b", 43.0)], "height", ok=45.0)
        ok, _ = bpg.reorder_layers(profile, [1, 0])
        self.assertTrue(ok)
        self.assertEqual([round(l["value"], 6) for l in profile["layers"]], [43.5, 43.0])

    def test_move_boundary_splitter_and_push(self):
        profile = P("x", [L("a", 0.4), L("b", 0.6), L("c", 1.0)])
        self.assertAlmostEqual(bpg.move_boundary(profile, 0, 0.5), 0.5)
        self.assertEqual([round(l["value"], 6) for l in profile["layers"]], [0.5, 0.5, 1.0])
        bpg.move_boundary(profile, 0, 5.0)                 # begrenzt durch die Nachbarschicht
        self.assertEqual([round(l["value"], 6) for l in profile["layers"]], [1.0, 0.0, 1.0])
        profile = P("x", [L("a", 0.4), L("b", 0.6), L("c", 1.0)])
        bpg.move_boundary(profile, 0, 0.6, push=True)
        self.assertEqual([round(l["value"], 6) for l in profile["layers"]], [0.6, 0.6, 1.0])
        profile = P("x", [L("a", 0.4), L("b", 1.0)], "depth")
        bpg.move_boundary(profile, 1, 1.5)                 # unterste Schicht: Gesamttiefe ändert sich
        self.assertEqual([round(l["value"], 6) for l in profile["layers"]], [0.4, 1.5])

    def test_colors_are_normalized_for_tk(self):
        self.assertEqual(bpg.normalize_color("ff0000"), "#ff0000")
        self.assertEqual(bpg.normalize_color("tab:red"), "#d62728")
        self.assertEqual(bpg.normalize_color("0.5"), "#808080")
        self.assertIsNone(bpg.normalize_color("none"))
        self.assertIsNone(bpg.normalize_color("keine Farbe"))
        project = bpg.normalize_project({"settings": {}, "profiles": [{"layers": [{"color": "C1"}]}]})
        self.assertTrue(project["profiles"][0]["layers"][0]["color"].startswith("#"))


class ImportDetailTests(unittest.TestCase):
    def test_semicolon_csv_with_decimal_commas(self):
        path = os.path.join(OUT, "import_semikolon.csv")
        with open(path, "w", encoding="cp1252") as handle:
            handle.write("Mutterboden;0,4;humos\nAuelehm;1,25\n\nKies;2,0\n")
        profiles = bpg.profiles_from_rows(bpg.read_table_file(path))
        self.assertEqual([[l["value"] for l in p["layers"]] for p in profiles], [[0.4, 1.25], [2.0]])
        self.assertEqual(profiles[0]["layers"][0]["details"], "humos")

    def test_title_row_above_header_and_units(self):
        notes = []
        rows = [["Bohrkerne Musterstraße"], [None],
                ["Profil", "Schicht", "Tiefe (cm)", "Bemerkung", "Höhe OK"],
                ["B1", "A", "30", "x", "45,2"], ["B1", "B", "120", None, None]]
        profiles = bpg.profiles_from_rows(rows, notes)
        self.assertEqual(profiles[0]["input_mode"], "depth")
        self.assertEqual([l["value"] for l in profiles[0]["layers"]], [0.3, 1.2])
        self.assertEqual(profiles[0]["ok"], 45.2)
        self.assertTrue(any("cm" in n for n in notes))

    def test_utf16_text_file(self):
        path = os.path.join(OUT, "import_utf16.txt")
        with open(path, "w", encoding="utf-16") as handle:
            handle.write("Schicht\tMächtigkeit\nTorf\t0,5\n")
        profiles = bpg.profiles_from_rows(bpg.read_table_file(path))
        self.assertEqual(profiles[0]["layers"][0]["name"], "Torf")
        self.assertEqual(profiles[0]["layers"][0]["value"], 0.5)


class LegacyTests(unittest.TestCase):
    def test_uk_and_inner_heights_are_kept(self):
        legacy = {"config": {"show_nhn": True, "scale_title": "Tiefe (m)", "scale_step": "0,25"},
                  "profiles": [{"title": "P", "layers": [
                      {"name": "A", "thickness": 1.0, "top_nhn": 50.0, "bottom_nhn": 49.0},
                      {"name": "B", "thickness": 2.0, "top_nhn": None, "bottom_nhn": 46.5}]}]}
        project = bpg.normalize_project(legacy)
        profile = project["profiles"][0]
        self.assertEqual((profile["ok"], profile["uk"]), (50.0, 46.5))
        self.assertEqual(project["settings"]["kote_mode"], "all")
        self.assertIsNone(project["settings"]["tick_step"])       # Rasterintervall ≠ Teilung
        self.assertEqual(project["settings"]["scale_title"], "")  # alter Standardtitel -> automatisch
        geom = bpg.compute_profile_geometry(profile)
        self.assertTrue(geom.warnings)                             # 50 − 46,5 ≠ 3 m

    def test_current_format_without_settings_is_not_legacy(self):
        data = {"format": "fremdprofilierung",
                "profiles": [{"input_mode": "depth", "layers": [{"name": "a", "value": 0.5}]}]}
        project = bpg.normalize_project(data)
        self.assertEqual(project["profiles"][0]["input_mode"], "depth")
        self.assertEqual(project["profiles"][0]["layers"][0]["value"], 0.5)

    def test_range_for_other_mode_is_ignored(self):
        st = dict(bpg.DEFAULT_SETTINGS, range_top=0.0, range_bottom=3.0, range_mode="depth")
        g = bpg.compute_profile_geometry(P("x", [L("a", 5.0)], ok=40.0))
        messages = []
        axis = bpg.resolve_axis(st, "height", [40.0], [g], lambda s: 15.0, messages)
        self.assertFalse(axis.manual)
        self.assertTrue(messages)


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        import subprocess
        return subprocess.run([sys.executable, os.path.join(ROOT, "Fremdprofilierung.py"), *args],
                              capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)

    def test_export_and_errors(self):
        example = os.path.join(ROOT, "Beispiele", "Beispiel_Hoehen_versetzt.json")
        out = os.path.join(OUT, "cli_export")
        result = self.run_cli("--export", out, example)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.path.exists(out + ".png"))
        self.assertEqual(self.run_cli("--export", out + ".bmp", example).returncode, 2)
        self.assertEqual(self.run_cli("--export", out + ".png", "fehlt.json").returncode, 2)
        self.assertEqual(self.run_cli("--export", out + ".png", example, "--dpi", "x").returncode, 2)


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.project = bpg.load_project_file(os.path.join(ROOT, "Beispiele", "Beispiel_Profile.json"))

    def render(self, project):
        M = bpg._mpl()
        fig = M.Figure()
        M.FigureCanvasAgg(fig)
        return fig, bpg.render_project(fig, project)

    def test_page_and_items(self):
        fig, res = self.render(self.project)
        w, h = fig.get_size_inches()
        self.assertAlmostEqual(w * 2.54, res.page_w, places=6)
        self.assertAlmostEqual(h * 2.54, res.page_h, places=6)
        self.assertAlmostEqual(res.page_h, bpg.DEFAULT_SETTINGS["page_height_cm"], places=6)
        keys = [i.key for i in res.items]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(res.axis.v_bot, -6.5)      # tiefstes Profil: 6,50 m
        self.assertEqual(res.ruler["slot"], 1)
        self.assertEqual(len(res.bars), 3)
        self.assertEqual([len(b["segments"]) for b in res.bars], [6, 5, 4])

    def test_left_label_offset_is_mirrored(self):
        uid = self.project["profiles"][0]["layers"][0]["uid"]
        self.project["overrides"]["layer:" + uid] = {"dx": 1.0, "dy": 0.0, "scale": 1.0}
        _, res = self.render(self.project)
        item = next(i for i in res.items if i.key == "layer:" + uid)
        self.assertEqual(item.dx_sign, -1)
        self.assertAlmostEqual(item.dx, -1.0)       # nach außen = nach links
        self.assertEqual(item.stored_offset(), (1.0, 0.0))

    def test_dollar_sign_is_safe(self):
        self.project["settings"]["main_title"] = "Kosten $5 und $6"
        self.project["profiles"][0]["layers"][0]["name"] = "Preis $1"
        _, res = self.render(self.project)
        self.assertTrue(res.items)

    def test_many_profiles(self):
        project = copy.deepcopy(self.project)
        base = project["profiles"][0]
        project["profiles"] = [bpg.duplicate_profile(base) for _ in range(20)]
        _, res = self.render(project)
        self.assertEqual(len(res.bar_centers), 20)
        self.assertTrue(all(b > a for a, b in zip(res.bar_centers, res.bar_centers[1:])))

    def test_export_formats(self):
        for ext in ("png", "pdf", "svg", "tif", "jpg"):
            path = os.path.join(OUT, f"unit_export.{ext}")
            bpg.export_figure(self.project, path, dpi=72)
            self.assertGreater(os.path.getsize(path), 1000, ext)


if __name__ == "__main__":
    unittest.main(verbosity=1)
