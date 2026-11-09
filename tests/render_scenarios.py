# -*- coding: utf-8 -*-
"""Rendert typische und extreme Szenarien als PNG nach tests/output (Sichtprüfung)."""

import copy
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "output")
os.makedirs(OUT, exist_ok=True)

spec = importlib.util.spec_from_file_location("bpg", os.path.join(ROOT, "Fremdprofilierung.py"))
bpg = importlib.util.module_from_spec(spec)
sys.modules["bpg"] = bpg
spec.loader.exec_module(bpg)

L = bpg.make_layer
P = bpg.make_profile
PAL = bpg.PALETTE


def project(profiles, **settings):
    data = bpg.default_project()
    data["profiles"] = profiles
    data["settings"].update(settings)
    return bpg.normalize_project(data)


def core(title, thicknesses, names=None, **kw):
    names = names or [f"Schicht {i + 1}" for i in range(len(thicknesses))]
    layers = [L(n, t, PAL[i % len(PAL)]) for i, (n, t) in enumerate(zip(names, thicknesses))]
    return P(title, layers, **kw)


SOIL = ["Mutterboden, humos", "Auelehm, schluffig", "Sand, fein- bis mittelsandig",
        "Kies, sandig", "Ton, plastisch", "Schluff, tonig", "Mittelsand mit Kies",
        "Grobkies mit Steinen", "Torf", "Verwitterungslehm"]

SCENARIOS = {}

SCENARIOS["six_profiles"] = project([
    core("BK 1", [0.3, 0.9, 1.3], SOIL[:3]),
    core("BK 2", [0.25, 0.55, 1.2, 2.0], SOIL[:4]),
    core("BK 3", [0.4, 1.1, 2.3, 1.5, 2.0], SOIL[:5]),
    core("BK 4", [0.3, 0.8, 2.0], SOIL[1:4]),
    core("BK 5", [0.35, 1.65, 3.0], SOIL[:3]),
    core("BK 6", [0.2, 1.0], SOIL[:2]),
], main_title="Sechs Bohrkerne – Maßstab automatisch in der Mitte")

heights = [
    P("RKS 1", [L("Oberboden", 0.3, PAL[0]), L("Kolluvium", 0.7, PAL[1]),
                L("Auelehm", 1.2, PAL[2]), L("Kies", 1.8, PAL[7])], "thickness", ok=45.20),
    P("RKS 2", [L("Oberboden", 0.25, PAL[0]), L("Kolluvium", 0.9, PAL[1]),
                L("Auelehm", 1.8, PAL[2]), L("Kies", 3.0, PAL[7])], "depth", ok=44.65),
    P("RKS 3", [L("Oberboden", 45.50, PAL[0]), L("Auffüllung, Bauschutt", 44.90, PAL[9]),
                L("Auelehm", 43.70, PAL[2]), L("Kies", 42.40, PAL[7])], "height", ok=45.80),
    P("RKS 4", [L("Oberboden", 0.2, PAL[0]), L("Auelehm", 1.4, PAL[2]),
                L("Kies", 1.6, PAL[7])], "thickness", uk=40.90),
]
SCENARIOS["heights_offset"] = project(heights, main_title="Höhengerechte Darstellung nach OK/UK",
                                      ruler_slot=2)

SCENARIOS["heights_offset_kote_all"] = project(copy.deepcopy(heights),
                                               main_title="Koten an allen Schichtgrenzen",
                                               kote_mode="all", label_extra="height",
                                               ruler_slot=0)

SCENARIOS["archaeo_small"] = project([
    P("Profil A", [L("Ap-Horizont", 0.18, PAL[0], "dunkelbraun, humos"),
                   L("Befund 12, Grubenverfüllung", 0.22, PAL[1], "mit HK und Keramik"),
                   L("Befund 13", 0.07, PAL[2]),
                   L("Anstehender Löss", 0.33, "#e8c872")], "thickness"),
    P("Profil B", [L("Ap-Horizont", 0.2, PAL[0]), L("Kolluvium", 0.35, PAL[1], hatch=".."),
                   L("Löss", 0.25, "#e8c872", hatch="//")], "thickness"),
], main_title="Kleines archäologisches Profil, Druckmaßstab 1:10", print_scale=10)

SCENARIOS["deep_core"] = project([
    core("B 1", [0.5, 2.5, 4.0, 6.0, 3.0, 5.5, 8.5], SOIL[:7]),
    core("B 2", [0.4, 1.6, 6.0, 9.0, 4.0], SOIL[2:7]),
], main_title="Tiefe Bohrungen (30 m)")

SCENARIOS["near_labels_left_ruler"] = project([
    core("P 1", [0.3, 0.12, 0.08, 0.9, 0.15, 0.1, 1.8, 2.9], SOIL[:8]),
    core("P 2", [0.25, 0.3, 0.04, 0.2, 0.12, 0.3, 2.6, 2.7], SOIL[2:10]),
    core("P 3", [1.0, 2.0, 1.5], SOIL[:3]),
], main_title="Beschriftung an der Schicht, Maßstab links, Zusatz Tiefe",
    label_layout="near", ruler_slot=0, label_extra="depth")

SCENARIOS["no_staff_no_grid"] = project([
    core("A", [1.0, 2.0]), core("B", [0.5, 2.5, 1.0])],
    main_title="Ohne Latte und Hilfslinien", show_staff=False, show_grid=False)

SCENARIOS["default"] = bpg.default_project()

SCENARIOS["empty_values"] = project([P("Leer", bpg.default_layers()),
                                     core("Voll", [1.0, 1.0])], main_title="Profil ohne Werte")

SCENARIOS["errors"] = project([
    P("Fehler Tiefe", [L("a", 0.5), L("b", 0.3), L("c", 1.2)], "depth"),
    P("Höhe ohne OK", [L("a", 44.0), L("b", 43.0)], "height"),
    P("OK/UK passt nicht", [L("a", 1.0), L("b", 1.0)], "thickness", ok=50.0, uk=47.0),
], main_title="Fehlerfälle")

SCENARIOS["dragged_labels"] = copy.deepcopy(SCENARIOS["six_profiles"])
_p = SCENARIOS["dragged_labels"]["profiles"]
SCENARIOS["dragged_labels"]["overrides"] = {
    "main_title": {"dx": 0.0, "dy": 0.0, "scale": 0.7},
    "layer:" + _p[0]["layers"][0]["uid"]: {"dx": 1.5, "dy": 1.0, "scale": 1.5},
    "layer:" + _p[1]["layers"][2]["uid"]: {"dx": 3.0, "dy": -2.0, "scale": 1.0},
    "title:" + _p[2]["uid"]: {"dx": 0.0, "dy": 0.5, "scale": 0.6},
    "value:" + _p[2]["layers"][2]["uid"]: {"dx": 1.4, "dy": 0.0, "scale": 1.0},
}
SCENARIOS["dragged_labels"]["settings"]["main_title"] = "Verschobene Beschriftungen"


def main(names=None):
    names = names or list(SCENARIOS)
    for name in names:
        result = bpg.export_figure(SCENARIOS[name], os.path.join(OUT, f"sc_{name}.png"), dpi=130)
        print(f"{name:28s} {result.page_w:6.1f} x {result.page_h:5.1f} cm  "
              f"items={len(result.items):3d}  messages={result.messages}")


if __name__ == "__main__":
    main(sys.argv[1:] or None)
