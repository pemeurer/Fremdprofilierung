#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fremdprofilierung – Bohrkerne und archäologische Profile nebeneinander
Copyright (C) 2026 Peter Meurer

Dieses Programm ist freie Software: Sie können es unter den Bedingungen der
GNU General Public License, Version 3, weitergeben und/oder verändern.

Dieses Programm wird in der Hoffnung verteilt, dass es nützlich ist, aber
OHNE JEDE GEWÄHRLEISTUNG – sogar ohne die implizite Gewährleistung der
MARKTFÄHIGKEIT oder EIGNUNG FÜR EINEN BESTIMMTEN ZWECK. Den vollständigen
Lizenztext enthält die Datei LICENSE; siehe auch
https://www.gnu.org/licenses/gpl-3.0.html

Unterstützung: https://paypal.me/PeMeurer

Version 3
---------
* beliebig viele Bohrkerne bzw. archäologische Profile nebeneinander
* Eingabe je Profil wahlweise als Mächtigkeiten, Tiefen oder Höhen der
  Unterkanten – alle übrigen Werte werden berechnet
* optional OK/UK (z. B. m ü. NHN): die Profile werden höhengerecht versetzt
* der Maßstab (Nivellierlatte) passt Bereich und Teilung automatisch an,
  wenn sich etwas ändert, und kann zwischen beliebige Profile verschoben
  werden (Auswahlliste oder per Maus in der Vorschau)
* Beschriftungen lassen sich in der Vorschau ziehen und per Mausrad
  vergrößern/verkleinern; die Änderungen werden im Projekt gespeichert
* Vorschau und Export sind blattgetreu identisch (PNG, PDF, SVG, TIFF, JPG)

Export ohne Oberfläche (z. B. für Stapelverarbeitung):
    python Fremdprofilierung.py --export bild.png projekt.json [--dpi 300]
"""

from __future__ import annotations

import copy
import csv
import io
import json
import math
import os
import subprocess
import sys
import textwrap
import time
import traceback
import uuid
from dataclasses import dataclass, field
from types import SimpleNamespace

APP_TITLE = "Fremdprofilierung"
APP_VERSION = "3.0"
FILE_FORMAT = "fremdprofilierung"
FILE_VERSION = 3
PAYPAL_URL = "https://paypal.me/PeMeurer"
GPL_URL = "https://www.gnu.org/licenses/gpl-3.0.html"
GPL_NOTICE = ("Dieses Programm ist freie Software unter der GNU General Public License, "
              "Version 3. Sie dürfen es unter den Bedingungen der Lizenz weitergeben und "
              "verändern. Es wird OHNE JEDE GEWÄHRLEISTUNG bereitgestellt; Einzelheiten "
              "stehen im Lizenztext.")


def license_text():
    """Vollständiger GPLv3-Text aus der Datei LICENSE neben dem Programm."""
    here = os.path.dirname(os.path.abspath(__file__))
    for name in ("LICENSE", "LICENSE.txt", "COPYING"):
        path = os.path.join(here, name)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                return handle.read()
    return (GPL_NOTICE + "\n\nDie Datei LICENSE mit dem vollständigen Lizenztext wurde nicht "
            f"gefunden. Sie können ihn hier lesen:\n{GPL_URL}\n")

CM_PER_INCH = 2.54
PT_CM = 2.54 / 72.0  # ein typografischer Punkt in cm
EPS = 1e-9

PALETTE = ["#0b4218", "#a4430d", "#073e50", "#4aaa2d", "#a62696",
           "#08a1d4", "#176b2a", "#f36b2b", "#8b6f47", "#64748b"]

HATCHES = [
    ("keine", ""),
    ("Punkte", ".."),
    ("Dichte Punkte", "..."),
    ("Kreise", "oo"),
    ("Querstriche", "--"),
    ("Senkrechte Striche", "||"),
    ("Schräg /", "//"),
    ("Schräg \\", "\\\\"),
    ("Kreuzschraffur", "xx"),
    ("Gitter", "++"),
    ("Sterne", "**"),
]
HATCH_VALUES = {value for _, value in HATCHES}

INPUT_MODES = [
    ("thickness", "Mächtigkeiten"),
    ("depth", "Tiefen der Unterkanten"),
    ("height", "Höhen der Unterkanten"),
]
LABEL_SIDES = [("auto", "automatisch"), ("left", "links"), ("right", "rechts")]

DEFAULT_SETTINGS = {
    "main_title": "",
    "axis_mode": "auto",          # auto | depth | height
    "height_unit": "m ü. NHN",
    "scale_title": "",            # leer = automatisch
    "range_top": None,            # Tiefe bzw. Höhe am oberen Rand (None = automatisch)
    "range_bottom": None,
    "range_mode": None,           # Darstellung, für die der feste Bereich gilt (depth|height)
    "tick_step": None,            # Teilung in m (None = automatisch)
    "ruler_slot": None,           # 0 = links außen … n = rechts außen, None = Mitte
    "show_ruler": True,
    "show_staff": True,
    "show_grid": True,
    "show_values": True,
    "kote_mode": "profile",       # none | profile | all
    "label_extra": "none",        # none | thickness | depth | height
    "label_layout": "even",       # even | near
    "page_height_cm": 22.9,       # wie die Vorlage (9 Zoll) – gleiche Proportionen
    "print_scale": None,          # z. B. 50 für 1:50 (bestimmt dann die Blatthöhe)
    "bar_width_cm": 2.2,
    "column_gap_cm": 2.0,
    "font_family": "DejaVu Sans",
    "font_scale": 1.0,
    "label_font_pt": 9.5,
    "wrap_chars": 50,
    "export_dpi": 300,
}

# Typ und Grenzen der Einstellungen (für das Laden und die Eingabefelder).
SETTING_RULES = {
    "main_title": ("str",),
    "axis_mode": ("enum", ("auto", "depth", "height")),
    "height_unit": ("str",),
    "scale_title": ("str",),
    "range_top": ("optfloat",),
    "range_bottom": ("optfloat",),
    "range_mode": ("enum", (None, "depth", "height")),
    "tick_step": ("optfloat", 1e-4, 1e5),
    "ruler_slot": ("optint", 0, 10000),
    "show_ruler": ("bool",),
    "show_staff": ("bool",),
    "show_grid": ("bool",),
    "show_values": ("bool",),
    "kote_mode": ("enum", ("none", "profile", "all")),
    "label_extra": ("enum", ("none", "thickness", "depth", "height")),
    "label_layout": ("enum", ("even", "near")),
    "page_height_cm": ("float", 4.0, 300.0),
    "print_scale": ("optfloat", 1.0, 100000.0),
    "bar_width_cm": ("float", 0.2, 10.0),
    "column_gap_cm": ("float", 0.0, 20.0),
    "font_family": ("str",),
    "font_scale": ("float", 0.3, 4.0),
    "label_font_pt": ("float", 3.0, 40.0),
    "wrap_chars": ("int", 8, 300),
    "export_dpi": ("int", 50, 1200),
}

BASE_FONT = {          # an den Proportionen der Vorlage ausgerichtet
    "main_title": 18.0,
    "profile_title": 16.0,
    "scale_title": 10.5,
    "tick_major": 10.0,
    "tick_minor": 8.5,
    "value": 10.0,
    "kote": 7.5,
}

TEXT_DARK = "#202a30"
TEXT_MUTED = "#575f63"
KOTE_COLOR = "#34495e"

# Layoutmaße in cm
MARGIN = 0.5
GAP_MAIN = 0.35
GAP_PTITLE = 0.22
GAP_STITLE = 0.08
GAP_KOTE = 0.08
LEAD_DIAG = 0.55
LEAD_TICK = 0.28
LEAD_GAP = 0.10
LABEL_GAP = 0.10
LABEL_INSET = 0.30
STAFF_W = 0.32
TICK_LONG = 0.17
TICK_SHORT = 0.10
TICK_LABEL_GAP = 0.08
KOTE_TICK = 0.12
KOTE_GAP = 0.06
MIN_VALUE_PT = 4.5

NICE_STEPS = [0.001, 0.002, 0.0025, 0.005, 0.01, 0.02, 0.025, 0.05, 0.1, 0.2,
              0.25, 0.5, 1.0, 2.0, 2.5, 5.0, 10.0, 20.0, 25.0, 50.0, 100.0,
              200.0, 250.0, 500.0, 1000.0, 2000.0, 2500.0, 5000.0, 10000.0]


# ---------------------------------------------------------------------------
# matplotlib wird erst bei Bedarf geladen (die Oberfläche bietet ggf. die
# Installation an).
# ---------------------------------------------------------------------------

_MPL = None


def _mpl():
    global _MPL
    if _MPL is None:
        import matplotlib
        from matplotlib import colors, patches, transforms
        from matplotlib import text as mtext
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
        _MPL = SimpleNamespace(matplotlib=matplotlib, colors=colors,
                               patches=patches, transforms=transforms,
                               mtext=mtext, Figure=Figure,
                               FigureCanvasAgg=FigureCanvasAgg)
    return _MPL


# ---------------------------------------------------------------------------
# Allgemeine Hilfsfunktionen
# ---------------------------------------------------------------------------

def parse_number(value, default=None):
    """Liest Zahlen mit Dezimalkomma oder -punkt. Leere/ungültige Werte -> default."""
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        value = float(value)
        return value if math.isfinite(value) else default
    s = str(value).strip().replace("−", "-").replace(" ", "").replace(" ", "")
    if not s:
        return default
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        number = float(s)
    except ValueError:
        return default
    return number if math.isfinite(number) else default


def fmt_num(value, max_decimals=2):
    """Zahl mit Komma und ohne überflüssige Nullen (0,4 / 2 / 2,85)."""
    if value is None:
        return ""
    v = round(float(value), max_decimals)
    if v == 0:
        v = 0.0
    s = f"{v:.{max_decimals}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s.replace(".", ",")


def fmt_fixed(value, decimals=2):
    v = round(float(value), decimals)
    if v == 0:
        v = 0.0
    return f"{v:.{decimals}f}".replace(".", ",")


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def new_uid():
    return uuid.uuid4().hex[:12]


def mpl_safe(text):
    """Verhindert, dass '$' in Beschriftungen als Formelsatz gedeutet wird."""
    return (text or "").replace("$", r"\$")


def is_color(value):
    if not value or not isinstance(value, str):
        return False
    try:
        return bool(_mpl().colors.is_color_like(value))
    except Exception:
        return False


def normalize_color(value):
    """Farbe als '#rrggbb' (versteht Tk und matplotlib) oder None.
    Akzeptiert auch 'ff0000' ohne #, Farbnamen und matplotlib-Angaben."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    candidates = [value]
    if not value.startswith("#") and len(value) in (3, 6) and \
            all(c in "0123456789abcdefABCDEF" for c in value):
        candidates.insert(0, "#" + value)
    for candidate in candidates:
        try:
            rgba = _mpl().colors.to_rgba(candidate)
        except (ValueError, TypeError):
            continue
        if rgba[3] == 0:
            return None
        return _mpl().colors.to_hex(rgba, keep_alpha=False)
    return None


def to_rgb(color):
    try:
        return _mpl().colors.to_rgb(color)
    except (ValueError, TypeError):
        return (0.5, 0.5, 0.5)


def luminance(color):
    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = to_rgb(color)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast_text_color(color):
    return "white" if luminance(color) < 0.36 else TEXT_DARK


def leader_color_for(color):
    """Führungslinien heller Schichten werden abgedunkelt, damit sie auf
    weißem Grund sichtbar bleiben."""
    lum = luminance(color)
    if lum < 0.45:
        return color
    r, g, b = to_rgb(color)
    factor = 0.5 if lum > 0.8 else 0.65
    return (r * factor, g * factor, b * factor)


def profile_title(profile, index):
    return (profile.get("title") or "").strip() or f"Profil {index + 1}"


# ---------------------------------------------------------------------------
# Datenmodell
# ---------------------------------------------------------------------------

def make_layer(name="", value=None, color=None, details="", hatch="", uid=None):
    return {"uid": uid or new_uid(), "name": name, "details": details,
            "value": value, "color": color or PALETTE[0], "hatch": hatch}


def make_profile(title="", layers=None, input_mode="thickness", ok=None,
                 uk=None, label_side="auto", uid=None):
    return {"uid": uid or new_uid(), "title": title, "input_mode": input_mode,
            "ok": ok, "uk": uk, "label_side": label_side,
            "layers": layers if layers is not None else []}


def default_layers(values=(None, None, None)):
    names = ["A-Horizont", "B-Horizont", "C-Horizont"]
    return [make_layer(names[i], values[i], PALETTE[i]) for i in range(3)]


def default_project():
    return {
        "format": FILE_FORMAT,
        "version": FILE_VERSION,
        "settings": dict(DEFAULT_SETTINGS),
        "profiles": [make_profile("Profil 1", default_layers((0.3, 0.6, 1.1)))],
        "overrides": {},
    }


def coerce_setting(key, value):
    """Gibt (ok, Wert) zurück – Wert ist bereits typgerecht und begrenzt."""
    rule = SETTING_RULES.get(key, ("str",))
    kind = rule[0]
    if kind == "str":
        return True, "" if value is None else str(value)
    if kind == "bool":
        if isinstance(value, str):
            return True, value.strip().lower() in ("1", "true", "ja", "yes", "wahr")
        return True, bool(value)
    if kind == "enum":
        return (value in rule[1]), (value if value in rule[1] else DEFAULT_SETTINGS[key])
    if kind in ("optfloat", "optint"):
        if value is None or (isinstance(value, str) and not value.strip()):
            return True, None
        number = parse_number(value)
        if number is None:
            return False, DEFAULT_SETTINGS[key]
        if kind == "optint":
            number = int(round(number))
        if len(rule) >= 3 and not (rule[1] <= number <= rule[2]):
            return False, DEFAULT_SETTINGS[key]
        return True, number
    if kind in ("float", "int"):
        number = parse_number(value)
        if number is None:
            return False, DEFAULT_SETTINGS[key]
        if kind == "int":
            number = int(round(number))
        if not (rule[1] <= number <= rule[2]):
            return False, type(number)(clamp(number, rule[1], rule[2]))
        return True, number
    return True, value


def _normalize_layer(raw, index, seen):
    if not isinstance(raw, dict):
        raw = {}
    uid = raw.get("uid") if isinstance(raw.get("uid"), str) and raw.get("uid") else new_uid()
    if uid in seen:
        uid = new_uid()
    seen.add(uid)
    hatch = raw.get("hatch") if raw.get("hatch") in HATCH_VALUES else ""
    return {
        "uid": uid,
        "name": str(raw.get("name") or ""),
        "details": str(raw.get("details") or ""),
        "value": parse_number(raw.get("value")),
        "color": normalize_color(raw.get("color")) or PALETTE[index % len(PALETTE)],
        "hatch": hatch,
    }


def _normalize_profile(raw, index, seen):
    if not isinstance(raw, dict):
        raw = {}
    uid = raw.get("uid") if isinstance(raw.get("uid"), str) and raw.get("uid") else new_uid()
    if uid in seen:
        uid = new_uid()
    seen.add(uid)
    mode = raw.get("input_mode") if raw.get("input_mode") in dict(INPUT_MODES) else "thickness"
    side = raw.get("label_side") if raw.get("label_side") in dict(LABEL_SIDES) else "auto"
    layers = [_normalize_layer(layer, i, seen)
              for i, layer in enumerate(raw.get("layers") or [])]
    return {
        "uid": uid,
        "title": str(raw.get("title") or ""),
        "input_mode": mode,
        "ok": parse_number(raw.get("ok")),
        "uk": parse_number(raw.get("uk")),
        "label_side": side,
        "layers": layers,
    }


def _migrate_legacy(data):
    """Übernimmt Projekte der Vorversion (config/profiles mit Mächtigkeiten
    und optionalen Schicht-OK/UK in m ü. NHN). Die Mächtigkeiten bleiben die
    Geometriegrundlage; die erste Höhenangabe bestimmt die OK, die UK der
    letzten Schicht wird als UK übernommen (Abweichungen meldet das Programm)."""
    cfg = data.get("config") or {}
    settings = dict(DEFAULT_SETTINGS)
    settings["main_title"] = cfg.get("main_title", "") or ""
    old_title = (cfg.get("scale_title", "") or "").strip()
    # "Tiefe (m)" war der alte Standardtitel – jetzt automatisch (passt auch zu Höhen)
    settings["scale_title"] = "" if old_title in ("", "Tiefe (m)") else old_title
    settings["show_staff"] = bool(cfg.get("show_staff", True))
    settings["show_grid"] = bool(cfg.get("show_grid", True))
    settings["show_values"] = bool(cfg.get("show_values", True))
    show_nhn = bool(cfg.get("show_nhn", True))
    settings["kote_mode"] = "profile" if show_nhn else "none"
    # Das alte "Rasterintervall" betraf nur die Hilfslinien; die Teilung bleibt automatisch.

    profiles = []
    any_nhn = inner_nhn = False
    for old in data.get("profiles") or []:
        if not isinstance(old, dict):
            continue
        old_layers = [layer for layer in (old.get("layers") or []) if isinstance(layer, dict)]
        layers = []
        depth = 0.0
        ok = None
        last_bottom_nhn = None
        for l_index, old_layer in enumerate(old_layers):
            thickness = parse_number(old_layer.get("thickness"))
            top_nhn = parse_number(old_layer.get("top_nhn"))
            bottom_nhn = parse_number(old_layer.get("bottom_nhn"))
            top = depth
            depth += max(0.0, thickness or 0.0)
            if top_nhn is not None or bottom_nhn is not None:
                any_nhn = True
            if (top_nhn is not None and l_index > 0) or \
                    (bottom_nhn is not None and l_index < len(old_layers) - 1):
                inner_nhn = True
            if ok is None and top_nhn is not None:
                ok = top_nhn + top
            if ok is None and bottom_nhn is not None:
                ok = bottom_nhn + depth
            if l_index == len(old_layers) - 1:
                last_bottom_nhn = bottom_nhn
            layers.append({
                "name": old_layer.get("name", ""),
                "details": old_layer.get("details", ""),
                "value": thickness if thickness else None,
                "color": old_layer.get("color"),
            })
        profiles.append({"title": old.get("title", ""), "input_mode": "thickness",
                         "ok": ok, "uk": last_bottom_nhn, "label_side": "auto",
                         "layers": layers})

    aligned = bool(cfg.get("align_profiles", False)) and any_nhn
    settings["axis_mode"] = "height" if aligned else "depth"
    if not aligned:
        # Früher galten "Von/Bis" als Tiefen – das passt zur Tiefendarstellung.
        settings["range_top"] = parse_number(cfg.get("scale_from"))
        settings["range_bottom"] = parse_number(cfg.get("scale_to"))
        if settings["range_top"] is not None or settings["range_bottom"] is not None:
            settings["range_mode"] = "depth"
    if inner_nhn and show_nhn:
        settings["kote_mode"] = "all"
    return {"settings": settings, "profiles": profiles, "overrides": {}}


KNOWN_FORMATS = {FILE_FORMAT, "bohrprofil-generator", "fremdprofilierung"}


def _layers_use_thickness(data):
    """True, wenn die Schichten im Format der Vorversion vorliegen."""
    found_thickness = found_value = False
    for profile in data.get("profiles") or []:
        if not isinstance(profile, dict):
            continue
        for layer in profile.get("layers") or []:
            if isinstance(layer, dict):
                found_thickness = found_thickness or "thickness" in layer
                found_value = found_value or "value" in layer
    return found_thickness and not found_value


def normalize_project(data):
    """Prüft geladene Daten und bringt sie in das aktuelle Schema."""
    if not isinstance(data, dict):
        raise ValueError("Die Datei enthält kein gültiges Projekt.")
    if "settings" not in data and data.get("format") not in KNOWN_FORMATS and (
            "config" in data or _layers_use_thickness(data)):
        data = _migrate_legacy(data)
    raw_settings = data.get("settings") or {}
    settings = dict(DEFAULT_SETTINGS)
    if isinstance(raw_settings, dict):
        for key in DEFAULT_SETTINGS:
            if key in raw_settings:
                _, settings[key] = coerce_setting(key, raw_settings[key])
    seen = set()
    profiles = [_normalize_profile(p, i, seen)
                for i, p in enumerate(data.get("profiles") or [])]
    if not profiles:
        profiles = [make_profile("Profil 1", default_layers())]
    overrides = {}
    raw_overrides = data.get("overrides") or {}
    if isinstance(raw_overrides, dict):
        for key, value in raw_overrides.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                continue
            dx = parse_number(value.get("dx"), 0.0)
            dy = parse_number(value.get("dy"), 0.0)
            scale = parse_number(value.get("scale"), 1.0)
            if not (0.05 <= scale <= 20):
                scale = 1.0
            overrides[key] = {"dx": dx, "dy": dy, "scale": scale}
    return {"format": FILE_FORMAT, "version": FILE_VERSION, "settings": settings,
            "profiles": profiles, "overrides": overrides}


def prune_overrides(project):
    """Entfernt Beschriftungsanpassungen gelöschter Profile/Schichten."""
    uids = set()
    for profile in project["profiles"]:
        uids.add(profile["uid"])
        for layer in profile["layers"]:
            uids.add(layer["uid"])
    keep = {}
    for key, value in project.get("overrides", {}).items():
        parts = key.split(":")
        if len(parts) == 1 or any(part in uids for part in parts[1:]):
            keep[key] = value
    project["overrides"] = keep
    return project


def load_project_file(path):
    with open(path, "r", encoding="utf-8-sig") as handle:
        return normalize_project(json.load(handle))


def save_project_file(project, path):
    data = prune_overrides(copy.deepcopy(project))
    data["format"] = FILE_FORMAT
    data["version"] = FILE_VERSION
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def duplicate_profile(profile):
    clone = copy.deepcopy(profile)
    clone["uid"] = new_uid()
    for layer in clone["layers"]:
        layer["uid"] = new_uid()
    return clone


def unify_colors_by_name(project):
    """Gleiche Schichtbezeichnung -> gleiche Farbe (erstes Vorkommen gewinnt).
    Gibt die Anzahl geänderter Schichten zurück."""
    colors = {}
    changed = 0
    for profile in project["profiles"]:
        for layer in profile["layers"]:
            key = " ".join((layer.get("name") or "").lower().split())
            if not key:
                continue
            if key in colors:
                if layer["color"] != colors[key]:
                    layer["color"] = colors[key]
                    changed += 1
            else:
                colors[key] = layer["color"]
    return changed


# ---------------------------------------------------------------------------
# Geometrie: aus Mächtigkeiten, Tiefen oder Höhen werden Schichtgrenzen
# ---------------------------------------------------------------------------

@dataclass
class LayerGeom:
    index: int
    layer: dict
    top: float           # Tiefe der Oberkante unter der Profil-OK (m)
    bottom: float        # Tiefe der Unterkante (m)
    missing: bool = False
    error: str = ""
    top_h: float = None
    bottom_h: float = None

    @property
    def thickness(self):
        return self.bottom - self.top


@dataclass
class ProfileGeom:
    profile: dict
    layers: list
    total: float
    top_h: float          # Höhe der Profil-Oberkante oder None
    errors: list
    warnings: list
    ok_problem: bool = False

    @property
    def has_height(self):
        return self.top_h is not None

    @property
    def bottom_h(self):
        return None if self.top_h is None else self.top_h - self.total


def compute_profile_geometry(profile):
    mode = profile.get("input_mode", "thickness")
    ok = parse_number(profile.get("ok"))
    uk = parse_number(profile.get("uk"))
    raw_layers = profile.get("layers") or []
    result = []
    errors, warnings = [], []
    ok_problem = False
    depth = 0.0
    if mode == "height" and ok is None:
        if any(parse_number(layer.get("value")) is not None for layer in raw_layers):
            errors.append("Für die Eingabe als Höhen muss die OK (Oberkante) des "
                          "Profils angegeben werden.")
            ok_problem = True
    for index, layer in enumerate(raw_layers):
        value = parse_number(layer.get("value"))
        geom = LayerGeom(index=index, layer=layer, top=depth, bottom=depth)
        if value is None:
            geom.missing = True
        elif mode == "thickness":
            if value < 0:
                geom.error = "negative Mächtigkeit"
                errors.append(f"Schicht {index + 1}: negative Mächtigkeit.")
            else:
                geom.bottom = depth + value
        elif mode == "depth":
            if value < depth - 1e-7:
                geom.error = "Tiefe liegt über der vorherigen Unterkante"
                errors.append(f"Schicht {index + 1}: Tiefe {fmt_num(value, 3)} m liegt über der "
                              f"Unterkante der vorherigen Schicht ({fmt_num(depth, 3)} m).")
            else:
                geom.bottom = max(value, depth)
        else:  # height
            if ok is None:
                geom.missing = True
            else:
                d = ok - value
                if d < depth - 1e-7:
                    geom.error = "Höhe liegt über der vorherigen Unterkante"
                    errors.append(f"Schicht {index + 1}: Höhe {fmt_num(value, 3)} liegt über der "
                                  f"Unterkante der vorherigen Schicht ({fmt_num(ok - depth, 3)}).")
                else:
                    geom.bottom = max(d, depth)
        depth = geom.bottom
        result.append(geom)
    total = depth
    if ok is not None:
        top_h = ok
    elif uk is not None and mode != "height":
        top_h = uk + total
    else:
        top_h = None
    if top_h is not None:
        for geom in result:
            geom.top_h = top_h - geom.top
            geom.bottom_h = top_h - geom.bottom
    if ok is not None and uk is not None:
        if uk > ok + 1e-7:
            errors.append("Die UK liegt über der OK.")
            ok_problem = True
        elif total > 0 and abs((ok - uk) - total) > 0.005:
            warnings.append(f"OK − UK = {fmt_num(ok - uk, 3)} m, die Schichten ergeben "
                            f"aber {fmt_num(total, 3)} m.")
    return ProfileGeom(profile, result, total, top_h, errors, warnings, ok_problem)


def convert_input_mode(profile, new_mode):
    """Rechnet die eingegebenen Werte in eine andere Eingabeart um, ohne die
    Geometrie zu verändern. Gibt (True, "") oder (False, Begründung) zurück."""
    old_mode = profile.get("input_mode", "thickness")
    if new_mode == old_mode:
        return True, ""
    if new_mode not in dict(INPUT_MODES):
        return False, "Unbekannte Eingabeart."
    geom = compute_profile_geometry(profile)
    if any(g.error for g in geom.layers) or (old_mode == "height" and geom.ok_problem
                                              and profile.get("ok") is None):
        return False, ("Bitte zuerst die markierten Eingabefehler beheben – "
                       "sonst kann nicht verlustfrei umgerechnet werden.")
    known = [parse_number(layer.get("value")) is not None for layer in profile.get("layers") or []]
    last_known = max((i for i, k in enumerate(known) if k), default=-1)
    if not all(known[:last_known + 1]):
        gap = known.index(False) + 1
        return False, (f"Schicht {gap} hat noch keinen Wert. Bitte zuerst die fehlenden (gelb "
                       "markierten) Werte ergänzen – sonst kann nicht verlustfrei umgerechnet werden.")
    if new_mode == "height" and geom.top_h is None:
        return False, ("Für die Eingabe als Höhen wird die OK (oder UK) des Profils "
                       "benötigt. Bitte zuerst eintragen.")
    values = []
    for g in geom.layers:
        if g.missing:
            values.append(None)
        elif new_mode == "thickness":
            values.append(round(g.thickness, 6))
        elif new_mode == "depth":
            values.append(round(g.bottom, 6))
        else:
            values.append(round(geom.top_h - g.bottom, 6))
    for layer, value in zip(profile["layers"], values):
        layer["value"] = value
    if new_mode == "height" and profile.get("ok") is None:
        profile["ok"] = round(geom.top_h, 6)
    profile["input_mode"] = new_mode
    return True, ""


def _write_boundaries(profile, geom, bottoms):
    """Schreibt neue Unterkanten-Tiefen (je Schicht, None = Wert fehlt) als
    Werte in der Eingabeart des Profils zurück."""
    mode = profile.get("input_mode", "thickness")
    top = 0.0
    for layer, bottom in zip(profile["layers"], bottoms):
        if bottom is None:
            layer["value"] = None
            continue
        if mode == "thickness":
            layer["value"] = round(bottom - top, 6)
        elif mode == "depth":
            layer["value"] = round(bottom, 6)
        else:
            layer["value"] = round(geom.top_h - bottom, 6)
        top = bottom


def reorder_layers(profile, new_order):
    """Ordnet die Schichten neu (Liste alter Indizes). Bei Eingabe als Tiefen
    oder Höhen bleiben die Mächtigkeiten erhalten und die Grenzen werden neu
    berechnet. Gibt (True, "") oder (False, Begründung) zurück."""
    layers = profile["layers"]
    if sorted(new_order) != list(range(len(layers))):
        return False, "Ungültige Reihenfolge."
    if profile.get("input_mode", "thickness") == "thickness":
        profile["layers"] = [layers[i] for i in new_order]
        return True, ""
    geom = compute_profile_geometry(profile)
    if any(g.error for g in geom.layers) or geom.ok_problem:
        return False, "Bitte zuerst die markierten Eingabefehler beheben."
    thickness = [None if g.missing else g.thickness for g in geom.layers]
    profile["layers"] = [layers[i] for i in new_order]
    depth = 0.0
    bottoms = []
    for i in new_order:
        if thickness[i] is None:
            bottoms.append(None)
        else:
            depth += thickness[i]
            bottoms.append(depth)
    _write_boundaries(profile, geom, bottoms)
    return True, ""


def move_boundary(profile, layer_index, new_bottom, push=False, min_thickness=0.0):
    """Verschiebt die Unterkante der Schicht *layer_index* auf die Tiefe
    *new_bottom* (m unter OK). Ohne *push* wirkt die Grenze wie ein Teiler
    zwischen den beiden Nachbarschichten (die Gesamttiefe bleibt, außer bei der
    untersten Schicht); mit *push* verschieben sich alle tieferen Grenzen mit.
    Gibt die tatsächlich gesetzte Tiefe zurück oder None."""
    geom = compute_profile_geometry(profile)
    if any(g.error for g in geom.layers) or geom.ok_problem:
        return None
    layers = geom.layers
    if not 0 <= layer_index < len(layers) or layers[layer_index].missing:
        return None
    current = layers[layer_index]
    nxt = next((g for g in layers[layer_index + 1:] if not g.missing and g.thickness > 1e-12),
               None)
    low = current.top + min_thickness
    if push or nxt is None:
        high = math.inf
    else:
        high = nxt.bottom - min_thickness
    new_bottom = max(low, min(high, new_bottom))
    delta = new_bottom - current.bottom
    bottoms = []
    for g in layers:
        if g.missing:
            bottoms.append(None)
        elif g.index < layer_index:
            bottoms.append(g.bottom)
        elif g.index == layer_index:
            bottoms.append(new_bottom)
        elif push:
            bottoms.append(g.bottom + delta)
        elif nxt is not None and g.index < nxt.index:
            bottoms.append(new_bottom)      # Schichten ohne Mächtigkeit dazwischen
        else:
            bottoms.append(g.bottom)
    _write_boundaries(profile, geom, bottoms)
    return new_bottom


# ---------------------------------------------------------------------------
# Maßstab / vertikale Achse
# ---------------------------------------------------------------------------

def _mantissa(step):
    exponent = math.floor(math.log10(step) + 1e-12)
    return round(step / 10 ** exponent, 6)


def nice_step_at_least(raw):
    """Kleinste „runde“ Schrittweite (1, 2, 2,5, 5 × 10^n) ≥ raw."""
    if not raw or raw <= 0 or not math.isfinite(raw):
        return 0.5
    exponent = math.floor(math.log10(raw))
    for base in (1.0, 2.0, 2.5, 5.0, 10.0):
        step = round(base * 10.0 ** exponent, 12)
        if step >= raw * (1 - 1e-9):
            return step
    return round(10.0 ** (exponent + 1), 12)


def choose_label_step(span, plot_h_cm, target_cm=0.75):
    if span <= 0 or plot_h_cm <= 0:
        return 0.5
    return max(0.001, nice_step_at_least(span * target_cm / plot_h_cm))


def major_step_for(step):
    m = _mantissa(step)
    return step * (2 if m in (2.5, 5.0) else 5)


def fine_step_for(step, cm_per_unit):
    m = _mantissa(step)
    if m in (1.0, 5.0):
        fine = step / 5
    elif m == 2.0:
        fine = step / 2
    elif m == 2.5:
        fine = step / 2.5
    else:
        fine = step / 2
    for candidate in (fine, step / 2, step):
        if candidate * cm_per_unit >= 0.1:
            return candidate
    return step


def decimals_for(step):
    for d in range(0, 6):
        if abs(round(step, d) - step) < 1e-9:
            return d
    return 6


@dataclass
class AxisSpec:
    mode: str              # "depth" oder "height"
    v_top: float           # Achswert oben (Tiefe negativ, Höhe positiv)
    v_bot: float
    label_step: float
    major_step: float
    fine_step: float
    decimals: int
    plot_h: float          # Höhe des Zeichenbereichs in cm
    manual: bool = False   # fester Bereich aktiv
    label_every: int = 1   # nur jede n-te Marke beschriften (zu feine Teilung)

    def labeled(self, v):
        if self.label_every <= 1:
            return True
        ratio = v / (self.label_step * self.label_every)
        return abs(ratio - round(ratio)) < 1e-6

    def ticks(self):
        step = self.label_step
        k0 = math.ceil(self.v_bot / step - 1e-7)
        k1 = math.floor(self.v_top / step + 1e-7)
        result = []
        for k in range(k0, k1 + 1):
            v = round(k * step, 10)
            ratio = v / self.major_step
            result.append((v, abs(ratio - round(ratio)) < 1e-6))
        return result

    def value_of(self, v):
        return -v if self.mode == "depth" else v

    def format(self, v):
        return fmt_fixed(self.value_of(v), self.decimals) + " m"


def resolve_axis_mode(settings, geoms, messages):
    mode = settings.get("axis_mode", "auto")
    any_height = any(g.has_height for g in geoms)
    if mode == "auto":
        return "height" if any_height else "depth"
    if mode == "height" and not any_height:
        messages.append(("warning", "Höhendarstellung gewählt, aber kein Profil hat eine OK/UK – "
                                    "es wird nach Tiefe dargestellt."))
        return "depth"
    return mode


def auto_scale_title(mode, settings):
    if mode == "height":
        return f"Höhe ({(settings.get('height_unit') or 'm').strip()})"
    return "Maßstab (m)"


def resolve_axis(settings, mode, tops, geoms, plot_h_fn, messages, min_label_cm=0.0):
    """min_label_cm: kleinster Abstand der Maßstabszahlen auf dem Blatt (aus der
    Schriftgröße), damit sie sich nicht überlappen."""
    if geoms:
        content_top = max(tops)
        content_bot = min(t - g.total for t, g in zip(tops, geoms))
    else:
        content_top, content_bot = 0.0, -1.0
    if content_top - content_bot < 1e-6:
        content_bot = content_top - 1.0
    to_v = (lambda x: -x) if mode == "depth" else (lambda x: x)
    user_top = settings.get("range_top")
    user_bot = settings.get("range_bottom")
    range_mode = settings.get("range_mode")
    if (user_top is not None or user_bot is not None) and range_mode and range_mode != mode:
        entered = "Tiefendarstellung" if range_mode == "depth" else "Höhendarstellung"
        current = "Höhendarstellung" if mode == "height" else "Tiefendarstellung"
        messages.append(("warning", f"Der feste Maßstabsbereich wurde für die {entered} eingegeben "
                                    f"und gilt nicht für die {current} – er wird ignoriert."))
        user_top = user_bot = None
    v_top_user = to_v(user_top) if user_top is not None else None
    v_bot_user = to_v(user_bot) if user_bot is not None else None
    if v_top_user is not None and v_bot_user is not None and v_top_user <= v_bot_user:
        messages.append(("warning", "Maßstabsbereich ungültig („oben“ muss über „unten“ liegen) – "
                                    "der Bereich wird automatisch bestimmt."))
        v_top_user = v_bot_user = None
    raw_top = v_top_user if v_top_user is not None else content_top
    raw_bot = v_bot_user if v_bot_user is not None else content_bot
    if raw_top - raw_bot <= 1e-9:
        raw_bot = raw_top - max(1.0, content_top - content_bot)
    span = raw_top - raw_bot
    plot_h = plot_h_fn(span)
    user_step = settings.get("tick_step")
    target_cm = max(0.75, min_label_cm)
    manual_step = bool(user_step and user_step > 0 and span / user_step <= 400)
    if manual_step:
        step = float(user_step)
    else:
        if user_step and user_step > 0:
            messages.append(("warning", "Die gewählte Teilung ist für den Bereich zu fein – "
                                        "es wird automatisch eingeteilt."))
        step = choose_label_step(span, plot_h, target_cm)
    adjusted = False
    for _ in range(12):
        v_top = v_top_user if v_top_user is not None else math.ceil(content_top / step - 1e-7) * step
        v_bot = v_bot_user if v_bot_user is not None else math.floor(content_bot / step + 1e-7) * step
        if v_top - v_bot <= 1e-9:
            if v_top_user is not None:
                v_bot = v_top - max(step, content_top - content_bot)
            else:
                v_top = v_bot + max(step, content_top - content_bot)
            adjusted = True
        span = v_top - v_bot
        plot_h = plot_h_fn(span)
        # Das Runden des Bereichs kann den Abstand der Zahlen verkleinern.
        if manual_step or step * plot_h / span >= min_label_cm * 0.999 or step >= span:
            break
        step = nice_step_at_least(step * 1.0001)
    if adjusted:
        messages.append(("warning", "Der Maßstabsbereich passt nicht zu den Profilen und wurde angepasst."))
    if settings.get("print_scale"):
        if plot_h > 500:
            messages.append(("warning", "Der Druckmaßstab ergibt eine Zeichnung über 5 m Höhe – "
                                        "sie wird auf 5 m begrenzt."))
            plot_h = 500.0
        elif plot_h < 1:
            messages.append(("warning", "Der Druckmaßstab ergibt eine Zeichnung unter 1 cm Höhe – "
                                        "sie wird 1 cm hoch gezeichnet (nicht maßstäblich)."))
            plot_h = 1.0
    cm_per_unit = plot_h / span
    label_every = 1
    spacing = step * cm_per_unit
    if min_label_cm > 0 and spacing < min_label_cm:
        for k in (2, 4, 5, 10, 20, 25, 50, 100, 200, 500, 1000):
            if k * spacing >= min_label_cm:
                label_every = k
                break
        else:
            label_every = 1000
        messages.append(("warning", f"Die Teilung ist für die Schriftgröße zu fein – nur jede "
                                    f"{label_every}. Marke wird beschriftet."))
    manual = v_top_user is not None or v_bot_user is not None
    return AxisSpec(mode, v_top, v_bot, step, major_step_for(step),
                    fine_step_for(step, cm_per_unit), decimals_for(step), plot_h, manual,
                    label_every)


# ---------------------------------------------------------------------------
# Beschriftungen: Textmaße und überlappungsfreie Verteilung
# ---------------------------------------------------------------------------

class TextMeasurer:
    """Misst Texte unabhängig von der Bildschirmauflösung (in cm)."""

    def __init__(self):
        M = _mpl()
        self.fig = M.Figure(figsize=(4, 4), dpi=72)
        M.FigureCanvasAgg(self.fig)
        self.renderer = self.fig.canvas.get_renderer()
        self.cache = {}

    def size_cm(self, text, size_pt, weight="normal", family="DejaVu Sans", linespacing=1.2):
        if not text:
            return 0.0, 0.0
        key = (text, round(float(size_pt), 3), weight, family, linespacing)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        M = _mpl()
        artist = M.mtext.Text(0, 0, text, fontsize=size_pt, fontweight=weight,
                              fontfamily=family, linespacing=linespacing)
        artist.set_figure(self.fig)
        bbox = artist.get_window_extent(renderer=self.renderer)
        result = (bbox.width * PT_CM, bbox.height * PT_CM)
        if len(self.cache) > 20000:
            self.cache.clear()
        self.cache[key] = result
        return result


_MEASURER = None


def get_measurer():
    global _MEASURER
    if _MEASURER is None:
        _MEASURER = TextMeasurer()
    return _MEASURER


def spread_labels(desired, heights, top_bound, bottom_bound, gap):
    """Verteilt Beschriftungen (Reihenfolge von oben nach unten) so, dass sie
    sich nicht überlappen und möglichst nahe an der Wunschposition liegen.
    Exakte Lösung über isotone Regression (Pool-Adjacent-Violators)."""
    n = len(desired)
    if n == 0:
        return []
    downward = [-y for y in desired]
    offsets = [0.0] * n
    for i in range(1, n):
        offsets[i] = offsets[i - 1] + (heights[i - 1] + heights[i]) / 2.0 + gap
    targets = [downward[i] - offsets[i] for i in range(n)]
    blocks = []  # [Summe, Anzahl]
    for value in targets:
        blocks.append([value, 1])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            s, c = blocks.pop()
            blocks[-1][0] += s
            blocks[-1][1] += c
    solution = []
    for s, c in blocks:
        solution.extend([s / c] * c)
    lower = -top_bound + heights[0] / 2.0
    upper = -bottom_bound - heights[-1] / 2.0 - offsets[-1]
    if lower <= upper:
        solution = [min(max(v, lower), upper) for v in solution]
    else:
        middle = (lower + upper) / 2.0
        solution = [middle] * n
    return [-(solution[i] + offsets[i]) for i in range(n)]


def build_label_text(geom, extra, wrap_chars, height_unit):
    layer = geom.layer
    name = (layer.get("name") or "").strip() or f"Schicht {geom.index + 1}"
    lines = []
    for paragraph in (name, (layer.get("details") or "").strip()):
        for raw in paragraph.splitlines():
            raw = raw.strip()
            if raw:
                lines.extend(textwrap.wrap(raw, width=max(8, int(wrap_chars)),
                                           break_long_words=False) or [raw])
    if extra == "thickness":
        d = thickness_decimals(geom.thickness)
        lines.append(f"Mächtigkeit {fmt_fixed(geom.thickness, d)} m")
    elif extra == "depth":
        d = max(thickness_decimals(geom.top), thickness_decimals(geom.bottom))
        lines.append(f"{fmt_fixed(geom.top, d)}–{fmt_fixed(geom.bottom, d)} m")
    elif extra == "height" and geom.top_h is not None:
        d = max(thickness_decimals(geom.top_h), thickness_decimals(geom.bottom_h))
        lines.append(f"{fmt_fixed(geom.top_h, d)}–{fmt_fixed(geom.bottom_h, d)} {height_unit}")
    return mpl_safe("\n".join(lines))


def thickness_decimals(value):
    """Nachkommastellen für Meterangaben: 2, bei Bedarf bis 4 – eine Schicht
    über 0 m wird nie als „0“ ausgegeben."""
    value = float(value)
    for d in (2, 3, 4):
        rounded = round(value, d)
        if abs(rounded - value) < 5e-7 and (rounded != 0 or value == 0):
            return d
    for d in (2, 3, 4):
        if round(value, d) != 0:
            return d
    return 4


# ---------------------------------------------------------------------------
# Zeichnen
# ---------------------------------------------------------------------------

@dataclass
class DragItem:
    """Eine verschieb- und skalierbare Beschriftung der Vorschau."""
    key: str
    kind: str                    # label | value | title | main_title | scale_title | kote
    artist: object
    base_x: float
    base_y: float
    dx: float = 0.0
    dy: float = 0.0
    base_size: float = 8.0
    scale: float = 1.0
    ha: str = "left"
    va: str = "center"
    width1: float = 0.0          # Textbreite in cm bei scale = 1
    height1: float = 0.0
    leader: object = None
    leader_spec: tuple = None    # (Balkenmitte, halbe Breite, y der Schichtmitte, Strich, Abstand)
    bar_box: tuple = None        # (x0, x1, y0, y1) – Werte wechseln außerhalb die Farbe
    colors: tuple = None         # (Farbe im Balken, Farbe außerhalb)
    profile_uid: str = None
    layer_uid: str = None
    dx_sign: int = 1             # -1: gespeicherter Versatz zeigt „nach außen“ (links)
    box_props: dict = None       # Hintergrund im Balken (entfällt außerhalb)

    def position(self):
        return self.base_x + self.dx, self.base_y + self.dy

    def stored_offset(self):
        """Versatz, wie er im Projekt gespeichert wird (bei seitlichen
        Beschriftungen in Richtung „nach außen“, damit er bei einem
        Seitenwechsel gespiegelt wird)."""
        return float(self.dx) * self.dx_sign, float(self.dy)

    def fontsize(self):
        return self.base_size * self.scale

    def bbox(self):
        x, y = self.position()
        w = self.width1 * self.scale
        h = self.height1 * self.scale
        if self.ha == "left":
            x0, x1 = x, x + w
        elif self.ha == "right":
            x0, x1 = x - w, x
        else:
            x0, x1 = x - w / 2, x + w / 2
        if self.va in ("bottom", "baseline"):
            y0, y1 = y, y + h
        elif self.va == "top":
            y0, y1 = y - h, y
        else:
            y0, y1 = y - h / 2, y + h / 2
        return x0, y0, x1, y1


def leader_points(item):
    """Führungslinie vom Balkenrand (Schichtmitte) zur Beschriftung."""
    bar_cx, half_w, y_mid, tick, gap = item.leader_spec
    x0, _, x1, _ = item.bbox()
    _, y = item.position()
    if (x0 + x1) / 2.0 >= bar_cx:
        edge = bar_cx + half_w
        attach = max(x0 - gap, edge)
        elbow = max(attach - tick, edge)
    else:
        edge = bar_cx - half_w
        attach = min(x1 + gap, edge)
        elbow = min(attach + tick, edge)
    return [edge, elbow, attach], [y_mid, y, y]


def apply_drag_item(item):
    """Überträgt Position/Größe eines DragItems auf die Zeichnung."""
    item.artist.set_position(item.position())
    item.artist.set_fontsize(item.fontsize())
    if item.leader is not None and item.leader_spec is not None:
        xs, ys = leader_points(item)
        item.leader.set_data(xs, ys)
    if item.bar_box is not None and item.colors is not None:
        x0, _, x1, _ = item.bbox()
        _, y = item.position()
        bx0, bx1, by0, by1 = item.bar_box
        inside = bx0 - 1e-6 <= x0 and x1 <= bx1 + 1e-6 and by0 <= y <= by1
        item.artist.set_color(item.colors[0] if inside else item.colors[1])
        if item.box_props is not None:
            item.artist.set_bbox(item.box_props if inside else None)


@dataclass
class RenderResult:
    page_w: float
    page_h: float
    x0: float
    y0: float
    items: list
    messages: list
    ruler: dict
    bar_centers: list
    axis: AxisSpec = None
    bars: list = field(default_factory=list)   # Säulen mit Segmenten (für das Ziehen von Grenzen)

    def y_to_v(self, y):
        """Blattkoordinate (cm) -> Achswert (Tiefe negativ bzw. Höhe)."""
        return self.axis.v_bot + y / self.axis.plot_h * (self.axis.v_top - self.axis.v_bot)

    def v_to_y(self, v):
        return (v - self.axis.v_bot) / (self.axis.v_top - self.axis.v_bot) * self.axis.plot_h


class _Bounds:
    def __init__(self):
        self.x0 = self.y0 = math.inf
        self.x1 = self.y1 = -math.inf

    def add(self, x0, y0, x1, y1):
        self.x0 = min(self.x0, x0, x1)
        self.x1 = max(self.x1, x0, x1)
        self.y0 = min(self.y0, y0, y1)
        self.y1 = max(self.y1, y0, y1)

    @property
    def valid(self):
        return self.x0 <= self.x1 and self.y0 <= self.y1


def render_project(fig, project, measurer=None):
    """Zeichnet das komplette Blatt in *fig*. Alle Maße in cm; die Figur
    erhält die Blattgröße, Vorschau und Export sind daher identisch."""
    M = _mpl()
    st = project["settings"]
    profiles = project["profiles"]
    overrides = project.get("overrides") or {}
    meas = measurer or get_measurer()
    family = st.get("font_family") or "DejaVu Sans"
    fscale = clamp(float(st.get("font_scale") or 1.0), 0.3, 4.0)
    messages = []
    items = []
    bounds = _Bounds()

    def ov(key):
        value = overrides.get(key)
        if not isinstance(value, dict):
            return 0.0, 0.0, 1.0
        return (float(value.get("dx", 0.0) or 0.0), float(value.get("dy", 0.0) or 0.0),
                clamp(float(value.get("scale", 1.0) or 1.0), 0.2, 8.0))

    def measure(text, size, weight="normal"):
        return meas.size_cm(text, size, weight, family)

    size = {key: value * fscale for key, value in BASE_FONT.items()}
    size["label"] = float(st.get("label_font_pt") or 7.5) * fscale

    fig.patch.set_facecolor("white")
    if fig.axes:
        ax = fig.axes[0]
        ax.cla()
    else:
        ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.set_autoscale_on(False)

    def add_item(item, register=True):
        apply_drag_item(item)
        bounds.add(*item.bbox())
        if register:
            items.append(item)
        return item

    geoms = [compute_profile_geometry(p) for p in profiles]
    n = len(geoms)
    for i, g in enumerate(geoms):
        title = profile_title(g.profile, i)
        for text in g.errors:
            messages.append(("error", f"{title}: {text}"))
        for text in g.warnings:
            messages.append(("warning", f"{title}: {text}"))

    if n == 0:
        ax.text(0.5, 0.5, "Noch kein Profil vorhanden", transform=ax.transAxes,
                ha="center", va="center", color="#68737d")
        ax.set_xlim(0, 20)
        ax.set_ylim(0, 10)
        fig.set_size_inches(20 / CM_PER_INCH, 10 / CM_PER_INCH, forward=False)
        return RenderResult(20, 10, 0, 0, [], messages, None, [], None)

    mode = resolve_axis_mode(st, geoms, messages)
    if mode == "height":
        known = [g.top_h for g in geoms if g.has_height]
        reference = max(known)
        tops = []
        for i, g in enumerate(geoms):
            if g.has_height:
                tops.append(g.top_h)
            else:
                tops.append(reference)
                if g.total > 0:
                    messages.append(("warning", f"{profile_title(g.profile, i)}: keine OK/UK angegeben – "
                                                f"oben an der höchsten OK ({fmt_fixed(reference, 2)}) ausgerichtet."))
    else:
        tops = [0.0] * n

    show_ruler = bool(st.get("show_ruler", True))
    show_staff = show_ruler and bool(st.get("show_staff", True))
    height_unit = (st.get("height_unit") or "").strip() or "m"

    # --- Kopfbereich (vertikal) ---------------------------------------------
    main_text = mpl_safe((st.get("main_title") or "").strip())
    m_dx, m_dy, m_sc = ov("main_title")
    main_w, main_h = measure(main_text, size["main_title"] * m_sc, "bold") if main_text else (0.0, 0.0)

    title_texts, title_dims = [], []
    for i, profile in enumerate(profiles):
        text = mpl_safe(profile_title(profile, i))
        _, _, sc = ov("title:" + profile["uid"])
        title_texts.append(text)
        title_dims.append(measure(text, size["profile_title"] * sc, "bold"))
    title_row_h = max(h for _, h in title_dims)

    scale_title = mpl_safe((st.get("scale_title") or "").strip() or auto_scale_title(mode, st))
    s_dx, s_dy, s_sc = ov("scale_title")
    if show_ruler and scale_title:
        stitle_w, stitle_h = measure(scale_title, size["scale_title"] * s_sc, "bold")
    else:
        stitle_w, stitle_h = 0.0, 0.0
    _, _, tick_sc = ov("ticks")          # Größe der Maßstabszahlen (Mausrad auf dem Maßstab)
    size["tick_major"] *= tick_sc
    size["tick_minor"] *= tick_sc
    tick_h = measure("0,0 m", size["tick_major"], "bold")[1] if show_ruler else 0.0
    kote_mode = st.get("kote_mode", "profile")
    any_height = any(g.has_height for g in geoms)
    kote_text_h = measure("OK 0,00", size["kote"])[1]
    kote_row = kote_text_h + GAP_KOTE if (kote_mode == "profile" and any_height) else 0.0
    above_plot = max(tick_h / 2.0, kote_row)

    header = above_plot + ((GAP_STITLE + stitle_h) if stitle_h else 0.0) + GAP_PTITLE + title_row_h
    if main_h:
        header += GAP_MAIN + main_h
    header += MARGIN
    footer = max(tick_h / 2.0, kote_row) + MARGIN

    print_scale = st.get("print_scale")
    if print_scale:
        def plot_h_fn(span):
            return max(1.0, span * 100.0 / float(print_scale))
    else:
        fixed_plot_h = float(st.get("page_height_cm") or 16.0) - header - footer
        if fixed_plot_h < 2.0:
            messages.append(("warning", "Die Blatthöhe ist für Überschriften und Zeichnung zu klein – "
                                        "die Zeichnung wird mindestens 2 cm hoch."))
            fixed_plot_h = 2.0

        def plot_h_fn(span):
            return fixed_plot_h

    min_label_cm = (1.15 * tick_h + 0.05) if show_ruler else 0.0
    axis = resolve_axis(st, mode, tops, geoms, plot_h_fn, messages, min_label_cm)
    plot_h = axis.plot_h
    v_span = axis.v_top - axis.v_bot

    def Y(v):
        return (v - axis.v_bot) / v_span * plot_h

    if axis.manual:
        for i, g in enumerate(geoms):
            if g.total <= 0:
                continue
            top_v, bot_v = tops[i], tops[i] - g.total
            title = profile_title(g.profile, i)
            if bot_v >= axis.v_top - 1e-9 or top_v <= axis.v_bot + 1e-9:
                messages.append(("warning", f"{title}: liegt ganz außerhalb des festen "
                                            "Maßstabsbereichs und wird nicht gezeichnet."))
            elif top_v > axis.v_top + 1e-6 or bot_v < axis.v_bot - 1e-6:
                messages.append(("warning", f"{title}: wird vom festen Maßstabsbereich abgeschnitten "
                                            f"(Profil reicht von {axis.format(top_v)} bis "
                                            f"{axis.format(bot_v)})."))

    # --- Inhalte je Profil vorbereiten --------------------------------------
    wrap_chars = int(st.get("wrap_chars") or 45)
    label_extra = st.get("label_extra", "none")
    bar_w = float(st.get("bar_width_cm") or 1.0)
    half_w = bar_w / 2.0
    lead_total = LEAD_DIAG + LEAD_TICK + LEAD_GAP

    slot = st.get("ruler_slot")
    if slot is None:
        slot = max(1, n // 2) if n > 1 else 0
    slot = int(clamp(int(slot), 0, n))

    sides = []
    for i, profile in enumerate(profiles):
        side = profile.get("label_side", "auto")
        if side == "auto":
            side = "left" if (show_ruler and i < slot) else "right"
        sides.append(1 if side == "right" else -1)

    visible, labels, kotes, profile_kotes, values = [], [], [], [], []
    for i, g in enumerate(geoms):
        vis = []
        for lg in g.layers:
            if lg.thickness <= 1e-9:
                continue
            vt = min(tops[i] - lg.top, axis.v_top)
            vb = max(tops[i] - lg.bottom, axis.v_bot)
            if vt - vb > 1e-9:
                vis.append((lg, vt, vb))
        visible.append(vis)

        lab = []
        for lg, vt, vb in vis:
            text = build_label_text(lg, label_extra, wrap_chars, height_unit)
            key = "layer:" + lg.layer["uid"]
            dx, dy, sc = ov(key)
            w1, h1 = measure(text, size["label"])
            w, h = measure(text, size["label"] * sc)
            lab.append(dict(lg=lg, vt=vt, vb=vb, text=text, key=key, dx=dx, dy=dy,
                            sc=sc, w1=w1, h1=h1, w=w, h=h))
        labels.append(lab)

        vals = []
        if st.get("show_values", True):
            min_pt = MIN_VALUE_PT * fscale
            for lg, vt, vb in vis:
                text = fmt_num(lg.thickness, thickness_decimals(lg.thickness))
                key = "value:" + lg.layer["uid"]
                dx, dy, sc = ov(key)
                overridden = abs(sc - 1.0) > 1e-6 or bool(dx) or bool(dy)
                w0, h0 = measure(text, size["value"])
                avail = Y(vt) - Y(vb)
                avail_eff = avail - PT_CM - 0.01    # Abstand zu den weißen Trennlinien
                # Maßgeblich ist die sichtbare Ziffernhöhe (~0,73 der Schriftgröße).
                digit_h = size["value"] * PT_CM * 0.73
                fit = 1.0
                if digit_h > avail_eff:
                    fit = min(fit, max(avail_eff, 0.0) / digit_h)
                if w0 > bar_w * 0.92:
                    fit = min(fit, bar_w * 0.92 / w0)
                base = size["value"] * fit
                if base < min_pt:
                    base = min_pt
                    too_thin = min_pt * PT_CM * 0.73 > avail_eff
                    too_wide = w0 * base / size["value"] > bar_w * 0.98
                    if (too_thin or too_wide) and not overridden:
                        continue  # passt nicht lesbar in die Schicht
                w1, h1 = w0 * base / size["value"], h0 * base / size["value"]
                box = None
                if lg.layer.get("hatch") and h1 + 0.30 * base * PT_CM <= avail - PT_CM:
                    # auf Schraffuren bleibt die Zahl mit einem Hintergrund lesbar
                    box = dict(boxstyle="round,pad=0.15", facecolor=lg.layer.get("color") or PALETTE[0],
                               edgecolor="none", alpha=0.9)
                vals.append(dict(lg=lg, vt=vt, vb=vb, text=text, key=key, dx=dx, dy=dy,
                                 sc=sc, base=base, w1=w1, h1=h1, box=box))
        values.append(vals)

        kot = []
        if kote_mode == "all" and g.has_height:
            boundary_list = [(tops[i], g.top_h, "kote:" + g.profile["uid"] + ":top")]
            for lg in g.layers:
                if lg.thickness > 1e-9:
                    boundary_list.append((tops[i] - lg.bottom, lg.bottom_h, "kote:" + lg.layer["uid"]))
            for v, h_value, key in boundary_list:
                if axis.v_bot - 1e-7 <= v <= axis.v_top + 1e-7:
                    text = fmt_fixed(h_value, 2)
                    dx, dy, sc = ov(key)
                    w1, h1 = measure(text, size["kote"])
                    kot.append(dict(v=v, text=text, key=key, dx=dx, dy=dy, sc=sc,
                                    w1=w1, h1=h1, w=w1 * sc, h=h1 * sc))
        kotes.append(kot)

        pk = []
        if kote_mode == "profile" and g.has_height and g.total > 0:
            top_v, bottom_v = tops[i], tops[i] - g.total
            if axis.v_bot - 1e-7 <= top_v <= axis.v_top + 1e-7:
                text = mpl_safe(f"OK {fmt_fixed(g.top_h, 2)} {height_unit}")
                dx, dy, sc = ov("ok:" + g.profile["uid"])
                w1, h1 = measure(text, size["kote"])
                pk.append(dict(kind="ok", v=top_v, text=text, key="ok:" + g.profile["uid"],
                               dx=dx, dy=dy, sc=sc, w1=w1, h1=h1))
            if axis.v_bot - 1e-7 <= bottom_v <= axis.v_top + 1e-7:
                text = mpl_safe(f"UK {fmt_fixed(g.bottom_h, 2)} {height_unit}")
                dx, dy, sc = ov("uk:" + g.profile["uid"])
                w1, h1 = measure(text, size["kote"])
                pk.append(dict(kind="uk", v=bottom_v, text=text, key="uk:" + g.profile["uid"],
                               dx=dx, dy=dy, sc=sc, w1=w1, h1=h1))
        profile_kotes.append(pk)

    # --- Spaltenbreiten -----------------------------------------------------
    extents = []
    for i in range(n):
        side = sides[i]
        label_w = max((d["w"] for d in labels[i]), default=0.0)
        label_ext = lead_total + label_w if labels[i] else 0.0
        kote_w = max((d["w"] for d in kotes[i]), default=0.0)
        kote_ext = KOTE_TICK + KOTE_GAP + 0.05 + kote_w if kotes[i] else 0.0
        left = half_w + (label_ext if side < 0 else kote_ext)
        right = half_w + (label_ext if side > 0 else kote_ext)
        need = title_dims[i][0] / 2.0
        for d in profile_kotes[i]:
            need = max(need, d["w1"] * d["sc"] / 2.0)
        for d in values[i]:
            need = max(need, d["w1"] * d["sc"] / 2.0)
        extents.append((max(left, need), max(right, need)))

    ticks = axis.ticks() if show_ruler else []
    tick_texts = [axis.format(v) for v, _ in ticks]
    tick_label_w = 0.0
    for (v, major), text in zip(ticks, tick_texts):
        if not axis.labeled(v):
            continue
        w, _ = measure(text, size["tick_major"] if major else size["tick_minor"],
                       "bold" if major else "normal")
        tick_label_w = max(tick_label_w, w)
    staff_half = STAFF_W / 2.0 if show_staff else 0.0
    ruler_left = max(staff_half + TICK_LONG, stitle_w / 2.0)
    ruler_right = max(staff_half + TICK_LONG + TICK_LABEL_GAP + tick_label_w, stitle_w / 2.0)

    order = []
    for i in range(n + 1):
        if show_ruler and i == slot:
            order.append(("R", -1))
        if i < n:
            order.append(("P", i))
    gap = float(st.get("column_gap_cm") or 0.0)
    x_cursor = 0.0
    centers = {}
    for index, (kind, i) in enumerate(order):
        left, right = (ruler_left, ruler_right) if kind == "R" else extents[i]
        if index > 0:
            x_cursor += gap
        centers[(kind, i)] = x_cursor + left
        x_cursor = centers[(kind, i)] + right
    content_w = x_cursor
    bar_cx = [centers[("P", i)] for i in range(n)]
    ruler_cx = centers.get(("R", -1))
    bounds.add(0.0, 0.0, content_w, plot_h)

    # --- Hilfslinien ----------------------------------------------------------
    if st.get("show_grid", True):
        grid_ticks = ticks if show_ruler else axis.ticks()
        xs = [c - half_w for c in bar_cx] + [c + half_w for c in bar_cx]
        if ruler_cx is not None:
            xs += [ruler_cx - ruler_left, ruler_cx + ruler_right]
        gx0, gx1 = min(xs), max(xs)
        for v, major in grid_ticks:
            y = Y(v)
            if major:
                ax.plot([gx0, gx1], [y, y], color="#cfd8dc", lw=0.75,
                        ls=(0, (4, 3)), zorder=0.5)
            else:
                ax.plot([gx0, gx1], [y, y], color="#e6ebee", lw=0.6, zorder=0.4)

    # --- Balken ---------------------------------------------------------------
    bars = []
    segment_by_uid = {}
    for i in range(n):
        bc = bar_cx[i]
        bar = {"profile_uid": geoms[i].profile["uid"], "index": i, "x0": bc - half_w,
               "x1": bc + half_w, "top_v": tops[i], "segments": []}
        bars.append(bar)
        for lg, vt, vb in visible[i]:
            color = lg.layer.get("color") or PALETTE[0]
            y0, y1 = Y(vb), Y(vt)
            artists = [ax.add_patch(M.patches.Rectangle((bc - half_w, y0), bar_w, y1 - y0,
                                                        facecolor=color, edgecolor="white",
                                                        linewidth=1.0, zorder=2))]
            hatch = lg.layer.get("hatch") or ""
            if hatch:
                hatch_color = M.colors.to_rgba(contrast_text_color(color), 0.75)
                artists.append(ax.add_patch(M.patches.Rectangle(
                    (bc - half_w, y0), bar_w, y1 - y0, fill=False, hatch=hatch,
                    edgecolor=hatch_color, linewidth=0, zorder=2.1)))
            if luminance(color) > 0.8:
                artists.append(ax.add_patch(M.patches.Rectangle(
                    (bc - half_w, y0), bar_w, y1 - y0, fill=False, edgecolor="#9aa5ab",
                    linewidth=0.6, zorder=2.2)))
            clipped_bottom = vb > tops[i] - lg.bottom + 1e-9
            clipped_top = vt < tops[i] - lg.top - 1e-9
            for clipped, y_cut in ((clipped_bottom, y0), (clipped_top, y1)):
                if clipped:
                    # Abbruchsymbol: das Profil geht über den Maßstabsbereich hinaus
                    zig_x = [bc - half_w - 0.08 + k * (bar_w + 0.16) / 6 for k in range(7)]
                    zig_y = [y_cut + (0.07 if k % 2 else -0.07) for k in range(7)]
                    ax.plot(zig_x, zig_y, color="white", lw=3.2, zorder=2.6)
                    ax.plot(zig_x, zig_y, color=TEXT_DARK, lw=1.0, zorder=2.7)
            segment = {"layer_uid": lg.layer["uid"], "index": lg.index, "y0": y0, "y1": y1,
                       "artists": artists, "value_item": None,
                       "draggable_bottom": not clipped_bottom}
            bar["segments"].append(segment)
            segment_by_uid[lg.layer["uid"]] = segment

    # --- Werte im Balken ------------------------------------------------------
    for i in range(n):
        bc = bar_cx[i]
        for d in values[i]:
            color = d["lg"].layer.get("color") or PALETTE[0]
            y_mid = Y((d["vt"] + d["vb"]) / 2.0)
            artist = ax.text(bc, y_mid, d["text"], ha="center", va="center_baseline",
                             fontsize=d["base"] * d["sc"], fontfamily=family, zorder=4,
                             bbox=d["box"])
            item = add_item(DragItem(key=d["key"], kind="value", artist=artist, base_x=bc,
                                     base_y=y_mid, dx=d["dx"], dy=d["dy"], base_size=d["base"],
                                     scale=d["sc"], ha="center", va="center", width1=d["w1"],
                                     height1=d["h1"],
                                     bar_box=(bc - half_w, bc + half_w, Y(d["vb"]), Y(d["vt"])),
                                     colors=(contrast_text_color(color), TEXT_DARK),
                                     box_props=d["box"],
                                     profile_uid=geoms[i].profile["uid"],
                                     layer_uid=d["lg"].layer["uid"]))
            segment = segment_by_uid.get(d["lg"].layer["uid"])
            if segment is not None:
                segment["value_item"] = item

    # --- Schichtbeschriftungen mit Führungslinien ----------------------------
    label_box = (dict(boxstyle="square,pad=0.12", facecolor="white", edgecolor="none", alpha=0.85)
                 if st.get("show_grid", True) else None)
    natural_top = plot_h   # Oberkante der Beschriftungsstapel (ohne Benutzer-Verschiebung)
    for i, g in enumerate(geoms):
        lab = labels[i]
        if not lab:
            continue
        needed = sum(d["h"] for d in lab) + LABEL_GAP * (len(lab) - 1)
        if needed > plot_h:
            messages.append(("warning", f"{profile_title(g.profile, i)}: Die Beschriftungen passen "
                                        "nicht in die Zeichnungshöhe – Blatthöhe vergrößern, Schrift "
                                        "verkleinern oder Zeilenumbruch erhöhen."))
        side = sides[i]
        bc = bar_cx[i]
        y_top_ext = Y(min(tops[i], axis.v_top))
        y_bot_ext = Y(max(tops[i] - g.total, axis.v_bot))
        count = len(lab)
        if st.get("label_layout") == "near":
            desired = [Y((d["vt"] + d["vb"]) / 2.0) for d in lab]
        elif count == 1:
            desired = [(y_top_ext + y_bot_ext) / 2.0]
        else:
            extent = y_top_ext - y_bot_ext
            inset = min(extent / (2.0 * count), LABEL_INSET)
            desired = [y_top_ext - inset - k * (extent - 2 * inset) / (count - 1)
                       for k in range(count)]
        ys = spread_labels(desired, [d["h"] for d in lab], plot_h, 0.0, LABEL_GAP)
        natural_top = max(natural_top, max(y + d["h"] / 2.0 for d, y in zip(lab, ys)))
        anchor_x = bc + side * (half_w + lead_total)
        ha = "left" if side > 0 else "right"
        for d, y in zip(lab, ys):
            color = d["lg"].layer.get("color") or PALETTE[0]
            y_mid = Y((d["vt"] + d["vb"]) / 2.0)
            artist = ax.text(anchor_x, y, d["text"], ha=ha, va="center",
                             fontsize=size["label"] * d["sc"], color=TEXT_DARK,
                             fontfamily=family, linespacing=1.2, zorder=6, bbox=label_box)
            leader = ax.plot([], [], color=leader_color_for(color), lw=1.1, zorder=3,
                             solid_capstyle="round", solid_joinstyle="round")[0]
            add_item(DragItem(key=d["key"], kind="label", artist=artist, base_x=anchor_x,
                              base_y=y, dx=d["dx"] * side, dy=d["dy"], base_size=size["label"],
                              scale=d["sc"], ha=ha, va="center", width1=d["w1"],
                              height1=d["h1"], leader=leader,
                              leader_spec=(bc, half_w, y_mid, LEAD_TICK, LEAD_GAP),
                              profile_uid=g.profile["uid"], layer_uid=d["lg"].layer["uid"],
                              dx_sign=side))

    # --- Höhenkoten -----------------------------------------------------------
    for i, g in enumerate(geoms):
        bc = bar_cx[i]
        for d in profile_kotes[i]:
            if d["kind"] == "ok":
                y, va = Y(d["v"]) + GAP_KOTE, "bottom"
            else:
                y, va = Y(d["v"]) - GAP_KOTE, "top"
            artist = ax.text(bc, y, d["text"], ha="center", va=va,
                             fontsize=size["kote"] * d["sc"], color=KOTE_COLOR,
                             fontfamily=family, zorder=6.5,
                             bbox=dict(boxstyle="square,pad=0.1", facecolor="white",
                                       edgecolor="none", alpha=0.9))
            add_item(DragItem(key=d["key"], kind="kote", artist=artist, base_x=bc, base_y=y,
                              dx=d["dx"], dy=d["dy"], base_size=size["kote"], scale=d["sc"],
                              ha="center", va=va, width1=d["w1"], height1=d["h1"],
                              profile_uid=g.profile["uid"]))
        kot = kotes[i]
        if kot:
            side = -sides[i]
            ys = spread_labels([Y(d["v"]) for d in kot], [d["h"] for d in kot],
                               plot_h + tick_h / 2.0, -tick_h / 2.0, 0.03)
            natural_top = max(natural_top, max(y + d["h"] / 2.0 for d, y in zip(kot, ys)))
            anchor_x = bc + side * (half_w + KOTE_TICK + KOTE_GAP + 0.05)
            ha = "left" if side > 0 else "right"
            for d, y in zip(kot, ys):
                artist = ax.text(anchor_x, y, d["text"], ha=ha, va="center",
                                 fontsize=size["kote"] * d["sc"], color=KOTE_COLOR,
                                 fontfamily=family, zorder=6)
                leader = ax.plot([], [], color="#7d8a92", lw=0.6, zorder=3)[0]
                add_item(DragItem(key=d["key"], kind="kote", artist=artist, base_x=anchor_x,
                                  base_y=y, dx=d["dx"] * side, dy=d["dy"], base_size=size["kote"],
                                  scale=d["sc"], ha=ha, va="center", width1=d["w1"],
                                  height1=d["h1"], leader=leader,
                                  leader_spec=(bc, half_w, Y(d["v"]), KOTE_TICK, KOTE_GAP),
                                  profile_uid=g.profile["uid"], dx_sign=side))

    # Passen die Beschriftungen nicht in die Zeichnungshöhe, rücken die
    # Überschriften nach oben, statt überdeckt zu werden.
    lift = 0.0
    if natural_top > plot_h + 1e-9:
        lift = max(0.0, natural_top + LABEL_GAP - (plot_h + above_plot))

    # --- Maßstab --------------------------------------------------------------
    ruler = None
    y_scale_title = plot_h + above_plot + GAP_STITLE + lift
    if show_ruler:
        rc = ruler_cx
        ruler_artists = []
        y_top, y_bot = Y(axis.v_top), Y(axis.v_bot)
        if show_staff:
            def draw_staff_half(x_left, step, dark_when_odd):
                k0 = math.floor(axis.v_bot / step + 1e-7)
                k1 = math.ceil(axis.v_top / step - 1e-7)
                for k in range(k0, k1):
                    a = max(k * step, axis.v_bot)
                    b = min((k + 1) * step, axis.v_top)
                    if b - a <= 1e-12:
                        continue
                    dark = (k % 2 != 0) if dark_when_odd else (k % 2 == 0)
                    ruler_artists.append(ax.add_patch(M.patches.Rectangle(
                        (x_left, Y(a)), staff_half_w, Y(b) - Y(a),
                        facecolor=TEXT_DARK if dark else "white", edgecolor=TEXT_DARK,
                        linewidth=0.5, zorder=4)))

            staff_half_w = STAFF_W / 2.0
            fine = axis.fine_step
            if v_span / fine > 1500:
                fine = axis.label_step
            draw_staff_half(rc - staff_half_w, axis.label_step, True)
            draw_staff_half(rc, fine, False)
            ruler_artists.append(ax.add_patch(M.patches.Rectangle(
                (rc - staff_half_w, y_bot), STAFF_W, y_top - y_bot, facecolor="none",
                edgecolor=TEXT_DARK, linewidth=1.4, zorder=5)))
        else:
            ruler_artists.extend(ax.plot([rc, rc], [y_bot, y_top], color=TEXT_DARK,
                                         lw=1.2, zorder=5))
        x_right = rc + staff_half
        x_left = rc - staff_half
        label_x = rc + staff_half + TICK_LONG + TICK_LABEL_GAP
        for (v, major), text in zip(ticks, tick_texts):
            y = Y(v)
            length = TICK_LONG if major else TICK_SHORT
            lw = 1.2 if major else 0.8
            ruler_artists.extend(ax.plot([x_right, x_right + length], [y, y],
                                         color=TEXT_DARK, lw=lw, zorder=5))
            if show_staff:
                ruler_artists.extend(ax.plot([x_left - length, x_left], [y, y],
                                             color=TEXT_DARK, lw=lw, zorder=5))
            if not axis.labeled(v):
                continue
            fsize = size["tick_major"] if major else size["tick_minor"]
            weight = "bold" if major else "normal"
            ruler_artists.append(ax.text(
                label_x, y, text, ha="left", va="center", fontsize=fsize, fontweight=weight,
                color=TEXT_DARK if major else TEXT_MUTED, fontfamily=family, zorder=6,
                bbox=dict(boxstyle="round,pad=0.1", facecolor="white", edgecolor="none",
                          alpha=0.9)))
            w, h = measure(text, fsize, weight)
            bounds.add(label_x, y - h / 2, label_x + w, y + h / 2)
        bounds.add(rc - ruler_left, y_bot - tick_h / 2.0, rc + ruler_right, y_top + tick_h / 2.0)
        scale_item = None
        if scale_title:
            w1, h1 = measure(scale_title, size["scale_title"], "bold")
            artist = ax.text(rc, y_scale_title, scale_title, ha="center", va="bottom",
                             fontsize=size["scale_title"] * s_sc, fontweight="bold",
                             color=TEXT_DARK, fontfamily=family, zorder=6)
            scale_item = add_item(DragItem(key="scale_title", kind="scale_title", artist=artist,
                                           base_x=rc, base_y=y_scale_title, dx=s_dx, dy=s_dy,
                                           base_size=size["scale_title"], scale=s_sc,
                                           ha="center", va="bottom", width1=w1, height1=h1))
        ruler = {"artists": ruler_artists, "cx": rc, "x0": rc - ruler_left,
                 "x1": rc + ruler_right, "y0": y_bot, "y1": y_top, "slot": slot,
                 "title_item": scale_item, "tick_scale": tick_sc}

    # --- Profilüberschriften ----------------------------------------------------
    y_ptitle = (plot_h + above_plot + ((GAP_STITLE + stitle_h) if stitle_h else 0.0)
                + GAP_PTITLE + lift)
    for i, profile in enumerate(profiles):
        key = "title:" + profile["uid"]
        dx, dy, sc = ov(key)
        w1, h1 = measure(title_texts[i], size["profile_title"], "bold")
        artist = ax.text(bar_cx[i], y_ptitle, title_texts[i], ha="center", va="bottom",
                         fontsize=size["profile_title"] * sc, fontweight="bold",
                         color=TEXT_DARK, fontfamily=family, zorder=6)
        add_item(DragItem(key=key, kind="title", artist=artist, base_x=bar_cx[i],
                          base_y=y_ptitle, dx=dx, dy=dy, base_size=size["profile_title"],
                          scale=sc, ha="center", va="bottom", width1=w1, height1=h1,
                          profile_uid=profile["uid"]))

    # --- Hauptüberschrift ---------------------------------------------------------
    if main_text:
        y_main = y_ptitle + title_row_h + GAP_MAIN
        w1, h1 = measure(main_text, size["main_title"], "bold")
        artist = ax.text(content_w / 2.0, y_main, main_text, ha="center", va="bottom",
                         fontsize=size["main_title"] * m_sc, fontweight="bold",
                         color=TEXT_DARK, fontfamily=family, zorder=6)
        add_item(DragItem(key="main_title", kind="main_title", artist=artist,
                          base_x=content_w / 2.0, base_y=y_main, dx=m_dx, dy=m_dy,
                          base_size=size["main_title"], scale=m_sc, ha="center",
                          va="bottom", width1=w1, height1=h1))

    # --- Blattgröße -----------------------------------------------------------------
    nominal_top = plot_h + header + lift
    nominal_bottom = -footer
    x0 = bounds.x0 - MARGIN
    x1 = bounds.x1 + MARGIN
    y0 = min(nominal_bottom, bounds.y0 - MARGIN)
    y1 = max(nominal_top, bounds.y1 + MARGIN)
    page_w, page_h = x1 - x0, y1 - y0
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    fig.set_size_inches(page_w / CM_PER_INCH, page_h / CM_PER_INCH, forward=False)
    return RenderResult(page_w, page_h, x0, y0, items, messages, ruler, bar_cx, axis, bars)


def export_figure(project, path, dpi=None):
    """Speichert das Blatt als PNG, PDF, SVG, TIFF oder JPG."""
    M = _mpl()
    fig = M.Figure()
    M.FigureCanvasAgg(fig)
    result = render_project(fig, project)
    dpi = int(dpi or project["settings"].get("export_dpi") or 300)
    ext = os.path.splitext(path)[1].lower()
    kwargs = {}
    title = (project["settings"].get("main_title") or "").strip()
    if ext in (".jpg", ".jpeg"):
        kwargs["pil_kwargs"] = {"quality": 95}
    elif ext in (".tif", ".tiff"):
        kwargs["pil_kwargs"] = {"compression": "tiff_lzw"}
    elif ext == ".png":
        kwargs["metadata"] = {"Title": title, "Software": f"{APP_TITLE} {APP_VERSION}"}
    elif ext in (".pdf", ".svg"):
        kwargs["metadata"] = {"Title": title, "Creator": f"{APP_TITLE} {APP_VERSION}"}
    # PDF: Schriften eingebettet, Texte bleiben bearbeitbar. SVG: Texte als Pfade,
    # damit die Darstellung auch ohne installierte Schrift exakt stimmt.
    with M.matplotlib.rc_context({"pdf.fonttype": 42, "ps.fonttype": 42,
                                  "svg.fonttype": "path"}):
        fig.savefig(path, dpi=dpi, facecolor="white", **kwargs)
    return result


# ---------------------------------------------------------------------------
# Tabellenimport (Excel/CSV)
# ---------------------------------------------------------------------------

class MissingDependency(Exception):
    def __init__(self, packages):
        super().__init__(packages)
        self.packages = packages


def read_table_file(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".csv", ".txt", ".tsv"):
        with open(path, "rb") as handle:
            raw = handle.read()
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = raw.decode("utf-16")          # Excel: „Unicode-Text (*.txt)“
        else:
            text = None
            for encoding in ("utf-8-sig", "cp1252", "latin-1"):
                try:
                    text = raw.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
        delimiter = _guess_delimiter(text)
        return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)]
    if ext in (".xlsx", ".xlsm", ".xltx", ".xltm"):
        try:
            import openpyxl
        except ImportError:
            raise MissingDependency(["openpyxl"])
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            sheet = workbook.worksheets[0]
            return [list(row) for row in sheet.iter_rows(values_only=True)]
        finally:
            workbook.close()
    if ext == ".xls":
        try:
            import pandas as pd
            frame = pd.read_excel(path, sheet_name=0, header=None)
        except ImportError:
            raise MissingDependency(["pandas", "xlrd"])
        return [[None if (isinstance(v, float) and math.isnan(v)) else v for v in row]
                for row in frame.values.tolist()]
    raise ValueError("Bitte eine Excel-Datei (.xlsx, .xls) oder CSV-Datei wählen.")


def _guess_delimiter(text):
    """Semikolon und Tabulator haben Vorrang: deutsche CSV-Dateien trennen mit
    ';' und schreiben Dezimalzahlen mit Komma."""
    lines = [line for line in text.splitlines() if line.strip()][:50]
    if not lines:
        return ";"
    for delimiter in ("\t", ";"):
        with_delim = sum(1 for line in lines if delimiter in line)
        if with_delim >= max(1, len(lines) // 2):
            return delimiter
    if any("," in line for line in lines):
        return ","
    return ";"


def _cell(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _norm_header(value):
    s = str(value).lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    for opener, closer in (("(", ")"), ("[", "]")):
        while opener in s and closer in s and s.index(opener) < s.index(closer):
            s = s[:s.index(opener)] + s[s.index(closer) + 1:]
    return "".join(ch for ch in s if ch.isalnum())


HEADER_ALIASES = {
    "profile": {"profil", "profilnr", "profilbezeichnung", "bohrung", "bohrkern", "bk",
                "aufschluss", "sondierung", "rks", "kern", "profilname"},
    "name": {"schicht", "bezeichnung", "horizont", "name", "befund", "stratum",
             "schichtbezeichnung", "einheit", "schichtname"},
    "details": {"beschreibung", "details", "bemerkung", "bemerkungen", "kommentar",
                "ansprache", "zusatz"},
    "thickness": {"maechtigkeit", "machtigkeit", "mchtigkeit", "dicke", "staerke"},
    "depth": {"tiefe", "tiefeuk", "uktiefe", "tiefebis", "bis", "teufe", "tiefeunterkante"},
    "height": {"hoehe", "hoeheuk", "ukhoehe", "uknhn", "uk", "hoeheunterkante", "uknn"},
    "ok": {"ok", "oknhn", "oknn", "ansatzhoehe", "ansatzpunkt", "gelaendehoehe",
           "okprofil", "profilok", "okhoehe", "hoeheok", "hoeheoberkante"},
    "color": {"farbe", "color", "colour", "farbcode"},
}


def _unit_factor(header):
    """Umrechnung nach m, wenn die Kopfzeile cm oder mm nennt."""
    tokens = "".join(ch if ch.isalnum() else " " for ch in str(header).lower()).split()
    if "cm" in tokens:
        return 0.01
    if "mm" in tokens:
        return 0.001
    return 1.0


def _detect_header(rows):
    """Sucht in den ersten Zeilen eine Kopfzeile (darüber dürfen Titelzeilen
    stehen). Gibt (Zeilenindex, Spaltenzuordnung, Faktoren, ignorierte Spalten)."""
    for index, row in enumerate(rows[:12]):
        if not any(c is not None for c in row):
            continue
        mapping, factors, ignored = {}, {}, []
        for col, value in enumerate(row):
            if value is None or isinstance(value, (int, float)):
                continue
            key = _norm_header(value)
            for field_name, aliases in HEADER_ALIASES.items():
                if key in aliases and field_name not in mapping:
                    mapping[field_name] = col
                    factors[field_name] = _unit_factor(value)
                    break
            else:
                ignored.append(str(value))
        has_value = any(k in mapping for k in ("thickness", "depth", "height"))
        if has_value and len(mapping) >= 2:
            return index, mapping, factors, ignored
    return None, None, None, None


def profiles_from_rows(rows, notes=None):
    """Wandelt Tabellenzeilen in Profile um. Unterstützt
    a) Kopfzeile mit Spalten wie Profil | Schicht | Mächtigkeit/Tiefe/Höhe |
       Beschreibung | Farbe | OK  und
    b) das bisherige Blockformat: Spalte A Bezeichnung, B Mächtigkeit,
       optional C Beschreibung; Leerzeilen trennen Profile.
    Hinweise (z. B. ignorierte Spalten) werden an *notes* angehängt."""
    rows = [[_cell(c) for c in (row or [])] for row in rows]
    header_index, mapping, factors, ignored = _detect_header(rows)
    if header_index is not None:
        if notes is not None and ignored:
            notes.append("Nicht erkannte Spalten wurden ignoriert: " + ", ".join(ignored))
        if notes is not None:
            for field_name, factor in factors.items():
                if factor != 1.0 and field_name in ("thickness", "depth", "height"):
                    notes.append(f"Werte in cm/mm wurden in m umgerechnet ({field_name}).")
        return _profiles_from_header_rows(rows[header_index + 1:], mapping, factors)
    return _profiles_from_blocks(rows)


def _get(row, col):
    return row[col] if col is not None and col < len(row) else None


def _profiles_from_header_rows(rows, mapping, factors=None):
    factors = factors or {}
    groups = []
    by_name = {}
    current = None
    for row in rows:
        relevant = [_get(row, c) for c in mapping.values()]
        if all(v is None for v in relevant):
            current = None  # Leerzeile beendet ein Profil ohne Profilspalte
            continue
        if "profile" in mapping:
            name = _get(row, mapping["profile"])
            key = str(name) if name is not None else (groups[-1]["key"] if groups else "")
            if key not in by_name:
                by_name[key] = {"key": key, "title": str(name or ""), "rows": []}
                groups.append(by_name[key])
            by_name[key]["rows"].append(row)
        else:
            if current is None:
                current = {"key": str(len(groups)), "title": "", "rows": []}
                groups.append(current)
            current["rows"].append(row)
    profiles = []
    for p_index, group in enumerate(groups):
        mode = None
        for candidate in ("thickness", "depth", "height"):
            col = mapping.get(candidate)
            if col is not None and any(parse_number(_get(r, col)) is not None for r in group["rows"]):
                mode = candidate
                break
        mode = mode or "thickness"
        ok = None
        if "ok" in mapping:
            for r in group["rows"]:
                ok = parse_number(_get(r, mapping["ok"]))
                if ok is not None:
                    break
        layers = []
        factor = factors.get(mode, 1.0)
        for l_index, r in enumerate(group["rows"]):
            name = _get(r, mapping.get("name"))
            value = parse_number(_get(r, mapping.get(mode)))
            if name is None and value is None:
                continue
            if value is not None and factor != 1.0:
                value = round(value * factor, 6)
            cell = _get(r, mapping.get("color"))
            color = normalize_color(cell) if isinstance(cell, str) else None
            layers.append(make_layer(str(name or ""), value,
                                     color or PALETTE[len(layers) % len(PALETTE)],
                                     str(_get(r, mapping.get("details")) or "")))
        title = group["title"] or f"Profil {p_index + 1}"
        if mode == "height" and ok is None:
            mode = "height"  # Fehlermeldung erscheint im Editor
        profiles.append(make_profile(title, layers, mode, ok))
    return [p for p in profiles if p["layers"]]


def _profiles_from_blocks(rows):
    profiles = []
    layers, title = [], ""

    def finish():
        nonlocal layers, title
        if layers:
            profiles.append(make_profile(title or f"Profil {len(profiles) + 1}", layers))
        layers, title = [], ""

    for row in rows:
        a = _get(row, 0)
        b = _get(row, 1)
        c = _get(row, 2)
        if a is None and b is None and c is None:
            finish()
            continue
        value = parse_number(b)
        if value is None:
            if a is not None and b is None and not layers and not title:
                title = str(a)
            continue
        layers.append(make_layer("" if a is None else str(a), value,
                                 PALETTE[len(layers) % len(PALETTE)],
                                 "" if c is None else str(c)))
    finish()
    return profiles


# ---------------------------------------------------------------------------
# Kommandozeile
# ---------------------------------------------------------------------------

USAGE = """Fremdprofilierung {version}

Aufruf:
  python Fremdprofilierung.py                     Oberfläche starten
  python Fremdprofilierung.py projekt.json        Projekt in der Oberfläche öffnen
  python Fremdprofilierung.py --export BILD PROJEKT [--dpi N]
                                                     ohne Oberfläche exportieren
                                                     (PNG, PDF, SVG, TIFF, JPG)
"""


EXPORT_EXTENSIONS = (".png", ".pdf", ".svg", ".tif", ".tiff", ".jpg", ".jpeg")


def cli_export(args):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")   # umgeleitete Ausgabe (cp1252) verträgt '−', '×'
        except Exception:
            pass
    args = list(args)
    dpi = None
    if "--dpi" in args:
        i = args.index("--dpi")
        value = parse_number(args[i + 1]) if i + 1 < len(args) else None
        if value is None or value != int(value) or not 20 <= value <= 2400:
            print("FEHLER: --dpi erwartet eine ganze Zahl zwischen 20 und 2400.", file=sys.stderr)
            return 2
        dpi = int(value)
        del args[i:i + 2]
    if len(args) != 2:
        print(USAGE.format(version=APP_VERSION))
        return 2
    out, project_path = args
    ext = os.path.splitext(out)[1].lower()
    if not ext:
        out += ".png"
        ext = ".png"
    if ext not in EXPORT_EXTENSIONS:
        print(f"FEHLER: Dateityp „{ext}“ wird nicht unterstützt (PNG, PDF, SVG, TIFF, JPG).",
              file=sys.stderr)
        return 2
    folder = os.path.dirname(os.path.abspath(out))
    if not os.path.isdir(folder):
        print(f"FEHLER: Der Ordner „{folder}“ existiert nicht.", file=sys.stderr)
        return 2
    if not os.path.isfile(project_path):
        print(f"FEHLER: Projektdatei „{project_path}“ nicht gefunden.", file=sys.stderr)
        return 2
    project = load_project_file(project_path)
    result = export_figure(project, out, dpi)
    for level, message in result.messages:
        print(("FEHLER: " if level == "error" else "Hinweis: ") + message)
    print(f"Gespeichert: {out} ({fmt_num(result.page_w, 1)} × {fmt_num(result.page_h, 1)} cm)")
    return 0


# ===========================================================================
# Oberfläche
# ===========================================================================

try:
    import tkinter as tk
    from tkinter import colorchooser, filedialog, messagebox, ttk
except ImportError:  # pragma: no cover - nur ohne Tk-Installation
    tk = None

UI_FONT = ("Segoe UI", 9)
UI_SMALL = ("Segoe UI", 8)
UI_BOLD = ("Segoe UI", 9, "bold")
INVALID_BG = "#fde2e1"
MISSING_BG = "#fff6dc"
OK_BG = "white"

HELP_TEXT = """Kurzanleitung

Profile
• Jedes Profil (Bohrkern oder archäologisches Profil) steht in der Liste links.
  Die Reihenfolge der Liste ist die Anordnung von links nach rechts.
• Für jedes Profil wählen Sie, wie die Schichten eingegeben werden:
  – Mächtigkeiten: Dicke jeder Schicht in m,
  – Tiefen der Unterkanten: z. B. 0,40 / 0,50 / 1,20 m unter der Oberkante,
  – Höhen der Unterkanten: absolute Höhen (z. B. m ü. NHN); dafür wird die
    OK des Profils benötigt.
  Beim Wechsel der Eingabeart werden die Werte automatisch umgerechnet.
• OK und UK des Profils sind optional. Sobald eine davon eingetragen ist,
  werden die Profile (Einstellung „automatisch“) höhengerecht versetzt
  nebeneinander gezeichnet und der Maßstab zeigt Höhen.

Maßstab
• Bereich und Teilung passen sich automatisch an (z. B. an eine neue
  Gesamttiefe). Unter „Maßstab und Höhen“ können Sie sie festlegen.
• Die Position des Maßstabs wählen Sie in der Liste oder ziehen ihn in der
  Vorschau mit der Maus zwischen zwei Profile.
• Mit einem Druckmaßstab (z. B. 1:20) wird die Zeichnung maßstäblich.
• Ein fester Bereich gilt für die Darstellungsart (Tiefe oder Höhe), in der
  er eingegeben wurde. Wird ein Profil abgeschnitten, erscheint ein Hinweis
  und ein Abbruchzeichen an der Säule.

Vorschau – Auswählen (wie im Windows-Explorer)
• Klick wählt ein Element aus (Beschriftung, Zahl im Balken, Überschrift,
  Kote, Maßstab). Strg+Klick fügt hinzu bzw. entfernt, Umschalt+Klick wählt
  alle Elemente gleicher Art dazwischen (z. B. die Beschriftungen von Schicht
  2 bis 5). Ein Rahmen auf freier Fläche wählt alles darin (mit Umschalt:
  hinzufügen, mit Strg: umschalten). Strg+A wählt alles, Esc hebt auf.

Vorschau – Ändern
• Ausgewählte Elemente gemeinsam mit der Maus ziehen.
• Mausrad über der Auswahl: vergrößern/verkleinern (über dem Maßstab: Größe
  der Maßstabszahlen). Passt das Blatt ganz in die Vorschau, genügt das
  Mausrad über einem Element; sonst blättert das Mausrad.
• Pfeiltasten verschieben die Auswahl (mit Umschalt in größeren Schritten),
  +/− ändern die Größe, Entf setzt sie zurück.
• Schichtgrenze in einer Säule ziehen (Mauszeiger ↕): die Schicht darüber
  wird dicker, die darunter dünner – die Werte im Editor ändern sich mit.
  Mit gedrückter Umschalttaste wandern alle tieferen Grenzen mit.
• Den Maßstab zwischen zwei andere Profile ziehen.
• Rechtsklick: Zurücksetzen und weitere Befehle. Doppelklick auf eine
  Beschriftung oder Grenze öffnet die Schicht im Editor.
• Strg + Mausrad zoomt.  Strg+Z / Strg+Y: Rückgängig / Wiederholen.

Export
• Der Export entspricht exakt der Vorschau (PNG, PDF, SVG, TIFF, JPG).
  In PDF-Dateien bleiben Texte bearbeitbar.
"""


def ensure_matplotlib_gui():
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        answer = messagebox.askyesno(
            "Matplotlib wird benötigt",
            "Für Vorschau und Export wird Matplotlib benötigt.\n"
            "Soll es jetzt automatisch installiert werden?")
        if not answer:
            raise RuntimeError("Matplotlib ist nicht installiert.")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "matplotlib"])
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    return FigureCanvasTkAgg


def available_fonts():
    preferred = ["DejaVu Sans", "Arial", "Calibri", "Segoe UI", "Helvetica",
                 "Liberation Sans", "Verdana", "Tahoma", "Times New Roman",
                 "Cambria", "Georgia", "DejaVu Serif"]
    try:
        from matplotlib import font_manager
        names = {f.name for f in font_manager.fontManager.ttflist}
    except Exception:
        names = {"DejaVu Sans"}
    return [name for name in preferred if name in names] or ["DejaVu Sans"]


def format_input(value):
    return "" if value is None else fmt_num(value, 4)


def make_paypal_button(parent, command):
    """Auffälliger Spenden-Button in PayPal-Farben."""
    button = tk.Button(parent, text="♥  Mit PayPal unterstützen", command=command,
                       bg="#FFC439", fg="#003087", activebackground="#F2B32B",
                       activeforeground="#003087", font=("Segoe UI", 9, "bold"),
                       relief="flat", bd=0, padx=12, pady=3, cursor="hand2",
                       highlightthickness=0)
    button.bind("<Enter>", lambda e: button.configure(bg="#F7BA2E"))
    button.bind("<Leave>", lambda e: button.configure(bg="#FFC439"))
    return button


if tk is not None:

    class ScrollFrame(ttk.Frame):
        """Senkrecht scrollbarer Bereich (Mausrad über App-weiten Verteiler)."""

        def __init__(self, master, background="#f7f8fa", **kw):
            super().__init__(master, **kw)
            self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0,
                                    background=background)
            self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
            self.inner = ttk.Frame(self.canvas)
            self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
            self.inner.bind("<Configure>", lambda e: self.canvas.configure(
                scrollregion=self.canvas.bbox("all")))
            self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(
                self._win, width=e.width))
            self.canvas.configure(yscrollcommand=self.vbar.set)
            self.canvas.pack(side="left", fill="both", expand=True)
            self.vbar.pack(side="right", fill="y")

        def scroll_wheel(self, event):
            first, last = self.canvas.yview()
            if first <= 0.0 and last >= 1.0:
                return
            delta = event.delta
            steps = -int(delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
            self.canvas.yview_scroll(steps, "units")

        def scroll_into_view(self, widget):
            self.update_idletasks()
            total = self.inner.winfo_height()
            if total <= 0:
                return
            y = widget.winfo_rooty() - self.inner.winfo_rooty()
            h = widget.winfo_height()
            view_h = self.canvas.winfo_height()
            first, last = self.canvas.yview()
            top, bottom = first * total, last * total
            if y < top:
                self.canvas.yview_moveto(max(0.0, y / total))
            elif y + h > bottom:
                self.canvas.yview_moveto(max(0.0, (y + h - view_h) / total))

    class ProfileEditor(ttk.Frame):
        """Bearbeitet ein einzelnes Profil (Kopfdaten und Schichten)."""

        def __init__(self, master, app):
            super().__init__(master)
            self.app = app
            self.profile = None
            self.rows = []
            self._loading = False

            head = ttk.Frame(self, padding=(6, 4))
            head.pack(fill="x")
            ttk.Label(head, text="Bezeichnung:").grid(row=0, column=0, sticky="w", pady=2)
            self.title_var = tk.StringVar()
            self.title_entry = ttk.Entry(head, textvariable=self.title_var)
            self.title_entry.grid(row=0, column=1, columnspan=5, sticky="ew", padx=(4, 0), pady=2)
            app.track_entry(self.title_entry)
            self.title_var.trace_add("write", self._on_title)

            ttk.Label(head, text="Eingabe als:").grid(row=1, column=0, sticky="w", pady=2)
            self.mode_combo = ttk.Combobox(head, state="readonly", width=22,
                                           values=[label for _, label in INPUT_MODES])
            self.mode_combo.grid(row=1, column=1, sticky="w", padx=(4, 0))
            self.mode_combo.bind("<<ComboboxSelected>>", self._on_mode)
            ttk.Label(head, text="Beschriftung:").grid(row=1, column=2, sticky="e", padx=(10, 2))
            self.side_combo = ttk.Combobox(head, state="readonly", width=12,
                                           values=[label for _, label in LABEL_SIDES])
            self.side_combo.grid(row=1, column=3, sticky="w")
            self.side_combo.bind("<<ComboboxSelected>>", self._on_side)

            ttk.Label(head, text="OK (optional):").grid(row=2, column=0, sticky="w", pady=2)
            okf = ttk.Frame(head)
            okf.grid(row=2, column=1, columnspan=5, sticky="w", padx=(4, 0))
            self.ok_var = tk.StringVar()
            self.ok_entry = tk.Entry(okf, textvariable=self.ok_var, width=10, justify="right",
                                     relief="solid", bd=1, highlightthickness=0, font=UI_FONT)
            self.ok_entry.pack(side="left")
            self.ok_unit = ttk.Label(okf, text="m ü. NHN")
            self.ok_unit.pack(side="left", padx=(3, 14))
            ttk.Label(okf, text="UK (optional):").pack(side="left")
            self.uk_var = tk.StringVar()
            self.uk_entry = tk.Entry(okf, textvariable=self.uk_var, width=10, justify="right",
                                     relief="solid", bd=1, highlightthickness=0, font=UI_FONT)
            self.uk_entry.pack(side="left", padx=(4, 0))
            self.uk_unit = ttk.Label(okf, text="m ü. NHN")
            self.uk_unit.pack(side="left", padx=(3, 0))
            for entry in (self.ok_entry, self.uk_entry):
                app.track_entry(entry)
            self.ok_var.trace_add("write", lambda *_: self._on_height("ok"))
            self.uk_var.trace_add("write", lambda *_: self._on_height("uk"))

            self.summary = ttk.Label(head, text="", font=UI_BOLD)
            self.summary.grid(row=3, column=0, columnspan=6, sticky="w", pady=(5, 0))
            self.message = tk.Label(head, text="", font=UI_SMALL, fg="#b3261e", anchor="w",
                                    justify="left", wraplength=560)
            self.message.grid(row=4, column=0, columnspan=6, sticky="ew")
            head.columnconfigure(5, weight=1)
            self.message.bind("<Configure>", lambda e: self.message.configure(
                wraplength=max(200, e.width - 4)))

            table_head = ttk.Frame(self, padding=(8, 2, 22, 0))
            table_head.pack(fill="x")
            ttk.Label(table_head, text="#", width=3, anchor="e", font=UI_SMALL,
                      foreground="#555").grid(row=0, column=0)
            ttk.Label(table_head, text="Bezeichnung  (darunter: Beschreibung, optional)",
                      font=UI_SMALL, foreground="#555").grid(row=0, column=1, sticky="w", padx=4)
            self.value_head = ttk.Label(table_head, text="Mächtigkeit (m)", font=UI_SMALL,
                                        foreground="#555", width=24, anchor="e")
            self.value_head.grid(row=0, column=2, sticky="e")
            ttk.Label(table_head, text="Farbe / Muster", font=UI_SMALL, foreground="#555",
                      width=26, anchor="w").grid(row=0, column=3, sticky="w", padx=(8, 0))
            table_head.columnconfigure(1, weight=1)

            self.list = ScrollFrame(self)
            self.list.pack(fill="both", expand=True, padx=4)

            actions = ttk.Frame(self, padding=(6, 5))
            actions.pack(fill="x")
            ttk.Button(actions, text="＋ Schicht unten anfügen",
                       command=lambda: self.add_layer(at_top=False)).pack(side="left")
            ttk.Button(actions, text="＋ Schicht oben einfügen",
                       command=lambda: self.add_layer(at_top=True)).pack(side="left", padx=5)
            ttk.Button(actions, text="Reihenfolge umkehren",
                       command=self.reverse_layers).pack(side="right")

        # ----- Laden -------------------------------------------------------
        def load(self, profile):
            self.profile = profile
            self._loading = True
            try:
                self.title_var.set(profile.get("title", ""))
                modes = [m for m, _ in INPUT_MODES]
                self.mode_combo.current(modes.index(profile.get("input_mode", "thickness")))
                sides = [s for s, _ in LABEL_SIDES]
                self.side_combo.current(sides.index(profile.get("label_side", "auto")))
                self.ok_var.set(format_input(profile.get("ok")))
                self.uk_var.set(format_input(profile.get("uk")))
                self.ok_entry.configure(bg=OK_BG)
                self.uk_entry.configure(bg=OK_BG)
            finally:
                self._loading = False
            self.update_units()
            self.rebuild_rows()

        def update_units(self):
            unit = (self.app.project["settings"].get("height_unit") or "").strip() or "m"
            self.ok_unit.configure(text=unit)
            self.uk_unit.configure(text=unit)
            mode = self.profile.get("input_mode", "thickness") if self.profile else "thickness"
            head = {"thickness": "Mächtigkeit (m)", "depth": "Tiefe UK (m unter OK)",
                    "height": f"Höhe UK ({unit})"}[mode]
            self.value_head.configure(text=head)

        def rebuild_rows(self, focus_index=None):
            for row in self.rows:
                for var, trace_id in row.get("traces", []):
                    try:
                        var.trace_remove("write", trace_id)
                    except tk.TclError:
                        pass
                row["frame"].destroy()
            self.rows = []
            if not self.profile:
                return
            for index, layer in enumerate(self.profile["layers"]):
                self._make_row(index, layer)
            self.refresh_computed()
            if focus_index is not None and 0 <= focus_index < len(self.rows):
                entry = self.rows[focus_index]["name_entry"]
                self.after_idle(lambda: (entry.focus_set(), self.list.scroll_into_view(entry)))

        def _make_row(self, index, layer):
            frame = ttk.Frame(self.list.inner, padding=(2, 3, 2, 3))
            frame.pack(fill="x")
            ttk.Separator(frame, orient="horizontal").grid(row=2, column=0, columnspan=9,
                                                           sticky="ew", pady=(4, 0))
            number = ttk.Label(frame, text=str(index + 1), width=3, anchor="e")
            number.grid(row=0, column=0, sticky="e")
            name_var = tk.StringVar(value=layer.get("name", ""))
            name_entry = ttk.Entry(frame, textvariable=name_var)
            name_entry.grid(row=0, column=1, sticky="ew", padx=4)
            value_var = tk.StringVar(value=format_input(layer.get("value")))
            value_entry = tk.Entry(frame, textvariable=value_var, width=9, justify="right",
                                   relief="solid", bd=1, highlightthickness=0, font=UI_FONT)
            value_entry.grid(row=0, column=2, sticky="e", padx=(0, 4))
            color_btn = tk.Button(frame, text="", width=3, bg=layer.get("color", PALETTE[0]),
                                  activebackground=layer.get("color", PALETTE[0]),
                                  relief="solid", bd=1, cursor="hand2")
            color_btn.grid(row=0, column=3, padx=(4, 2))
            hatch_combo = ttk.Combobox(frame, state="readonly", width=12,
                                       values=[label for label, _ in HATCHES])
            hatch_values = [v for _, v in HATCHES]
            hatch_combo.current(hatch_values.index(layer.get("hatch", "")) if layer.get("hatch", "") in hatch_values else 0)
            hatch_combo.grid(row=0, column=4, padx=2)
            btns = ttk.Frame(frame)
            btns.grid(row=0, column=5, padx=(2, 0))
            up = ttk.Button(btns, text="▲", width=2, command=lambda: self.move_layer(layer, -1))
            down = ttk.Button(btns, text="▼", width=2, command=lambda: self.move_layer(layer, 1))
            delete = ttk.Button(btns, text="✕", width=2, command=lambda: self.delete_layer(layer))
            for b in (up, down, delete):
                b.pack(side="left")
            details_var = tk.StringVar(value=layer.get("details", ""))
            details_entry = tk.Entry(frame, textvariable=details_var, font=UI_SMALL, fg="#4b555c",
                                     relief="solid", bd=1, highlightthickness=0)
            details_entry.grid(row=1, column=1, sticky="ew", padx=4, pady=(3, 0))
            computed = ttk.Label(frame, text="", font=UI_SMALL, foreground="#5b6770")
            computed.grid(row=1, column=2, columnspan=4, sticky="w", padx=(0, 0), pady=(3, 0))
            frame.columnconfigure(1, weight=1)

            row = {"frame": frame, "layer": layer, "name_entry": name_entry,
                   "value_entry": value_entry, "computed": computed, "color_btn": color_btn,
                   "name_var": name_var, "value_var": value_var, "details_var": details_var}
            color_btn.configure(command=lambda: self.pick_color(row))
            for entry in (name_entry, value_entry, details_entry):
                self.app.track_entry(entry)
                # Tab in eine verdeckte Zeile: Liste mitscrollen
                entry.bind("<FocusIn>", lambda e, f=frame: self.list.scroll_into_view(f), add="+")
            row["traces"] = [
                (name_var, name_var.trace_add("write", lambda *_: self._on_layer_text(row, "name"))),
                (details_var, details_var.trace_add("write", lambda *_: self._on_layer_text(row, "details"))),
                (value_var, value_var.trace_add("write", lambda *_: self._on_layer_value(row))),
            ]
            hatch_combo.bind("<<ComboboxSelected>>",
                             lambda e: self._on_hatch(row, hatch_values[hatch_combo.current()]))
            self.rows.append(row)

        # ----- Änderungen --------------------------------------------------
        def _on_title(self, *_):
            if self._loading or not self.profile:
                return
            self.app.note_edit(("title", self.profile["uid"]))
            self.profile["title"] = self.title_var.get()
            self.app.on_profiles_changed(structure=False)

        def _on_mode(self, _event=None):
            if not self.profile:
                return
            new_mode = INPUT_MODES[self.mode_combo.current()][0]
            if new_mode == self.profile.get("input_mode"):
                return
            self.app.checkpoint()
            ok, reason = convert_input_mode(self.profile, new_mode)
            if not ok:
                self.app.discard_checkpoint()
                modes = [m for m, _ in INPUT_MODES]
                self.mode_combo.current(modes.index(self.profile.get("input_mode", "thickness")))
                messagebox.showinfo("Eingabeart", reason, parent=self)
                return
            self.load(self.profile)
            self.app.on_profiles_changed(structure=False)

        def _on_side(self, _event=None):
            if not self.profile:
                return
            side = LABEL_SIDES[self.side_combo.current()][0]
            if side == self.profile.get("label_side", "auto"):
                return
            self.app.checkpoint()
            self.profile["label_side"] = side
            self.app.on_profiles_changed(structure=False)

        def _on_height(self, which):
            if self._loading or not self.profile:
                return
            var = self.ok_var if which == "ok" else self.uk_var
            entry = self.ok_entry if which == "ok" else self.uk_entry
            text = var.get().strip()
            value = parse_number(text)
            if text and value is None:
                entry.configure(bg=INVALID_BG)
                return
            entry.configure(bg=OK_BG)
            self.app.note_edit((which, self.profile["uid"]))
            self.profile[which] = value
            self.refresh_computed()
            self.app.on_profiles_changed(structure=False)

        def _on_layer_text(self, row, key):
            if self._loading:
                return
            self.app.note_edit(("layer", row["layer"]["uid"], key))
            row["layer"][key] = row[key + "_var"].get()
            self.app.on_profiles_changed(structure=False)

        def _on_layer_value(self, row):
            if self._loading:
                return
            text = row["value_var"].get().strip()
            value = parse_number(text)
            if text and value is None:
                row["value_entry"].configure(bg=INVALID_BG)
                return
            self.app.note_edit(("layer", row["layer"]["uid"], "value"))
            row["layer"]["value"] = value
            self.refresh_computed()
            self.app.on_profiles_changed(structure=False)

        def _on_hatch(self, row, value):
            if value == row["layer"].get("hatch", ""):
                return
            self.app.checkpoint()
            row["layer"]["hatch"] = value
            self.app.on_profiles_changed(structure=False)

        def pick_color(self, row):
            selected = colorchooser.askcolor(color=row["layer"].get("color"),
                                             title="Schichtfarbe wählen", parent=self)
            if selected and selected[1]:
                self.app.checkpoint()
                row["layer"]["color"] = selected[1]
                row["color_btn"].configure(bg=selected[1], activebackground=selected[1])
                self.app.on_profiles_changed(structure=False)

        def add_layer(self, at_top=False):
            if not self.profile:
                return
            self.app.checkpoint()
            layers = self.profile["layers"]
            used = {layer.get("color") for layer in layers}
            color = next((c for c in PALETTE if c not in used), PALETTE[len(layers) % len(PALETTE)])
            layer = make_layer("", None, color)
            if at_top:
                layers.insert(0, layer)
                focus = 0
            else:
                layers.append(layer)
                focus = len(layers) - 1
            self.rebuild_rows(focus_index=focus)
            self.app.on_profiles_changed(structure=False)

        def _reorder(self, order, title):
            """Neue Reihenfolge; bei Tiefen/Höhen bleiben die Mächtigkeiten erhalten."""
            self.app.checkpoint()
            ok, reason = reorder_layers(self.profile, order)
            if not ok:
                self.app.discard_checkpoint()
                messagebox.showinfo(title, reason, parent=self)
                return False
            self.rebuild_rows()
            self.app.on_profiles_changed(structure=False)
            return True

        def move_layer(self, layer, delta):
            layers = self.profile["layers"]
            index = layers.index(layer)
            target = index + delta
            if not 0 <= target < len(layers):
                return
            order = list(range(len(layers)))
            order[index], order[target] = order[target], order[index]
            self._reorder(order, "Schicht verschieben")

        def delete_layer(self, layer):
            self.app.checkpoint()
            self.profile["layers"].remove(layer)
            self.rebuild_rows()
            self.app.on_profiles_changed(structure=False)

        def reverse_layers(self):
            if not self.profile or len(self.profile["layers"]) < 2:
                return
            self._reorder(list(range(len(self.profile["layers"])))[::-1], "Reihenfolge umkehren")

        def refresh_computed(self):
            if not self.profile:
                return
            geom = compute_profile_geometry(self.profile)
            unit = (self.app.project["settings"].get("height_unit") or "").strip() or "m"
            mode = self.profile.get("input_mode", "thickness")
            for row, lg in zip(self.rows, geom.layers):
                entry = row["value_entry"]
                text = row["value_var"].get().strip()
                if text and parse_number(text) is None:
                    entry.configure(bg=INVALID_BG)
                elif lg.error:
                    entry.configure(bg=INVALID_BG)
                elif lg.missing:
                    entry.configure(bg=MISSING_BG)
                else:
                    entry.configure(bg=OK_BG)
                if lg.missing or lg.error:
                    info = lg.error or "Wert fehlt"
                else:
                    if mode == "thickness":
                        info = f"{fmt_fixed(lg.top, 2)}–{fmt_fixed(lg.bottom, 2)} m"
                    else:
                        info = f"Mächtigkeit {fmt_num(lg.thickness, 3)} m"
                        if mode == "height":
                            info += f" · {fmt_fixed(lg.top, 2)}–{fmt_fixed(lg.bottom, 2)} m"
                    if lg.top_h is not None and mode != "height":
                        info += f" · {fmt_fixed(lg.top_h, 2)}–{fmt_fixed(lg.bottom_h, 2)}"
                row["computed"].configure(text=info,
                                          foreground="#b3261e" if lg.error else "#5b6770")
            count = len(geom.layers)
            summary = f"{count} Schicht{'en' if count != 1 else ''} · Gesamt {fmt_fixed(geom.total, 2)} m"
            if geom.top_h is not None:
                summary += (f" · OK {fmt_fixed(geom.top_h, 2)} / UK "
                            f"{fmt_fixed(geom.bottom_h, 2)} {unit}")
            self.summary.configure(text=summary)
            problems = geom.errors + geom.warnings
            self.message.configure(text="\n".join(problems),
                                   fg="#b3261e" if geom.errors else "#a05a00")
            for var, entry, flagged in ((self.ok_var, self.ok_entry, geom.ok_problem),
                                        (self.uk_var, self.uk_entry, False)):
                text = var.get().strip()
                invalid = bool(text) and parse_number(text) is None
                entry.configure(bg=INVALID_BG if (invalid or flagged) else OK_BG)

        def focus_layer(self, layer_uid):
            for row in self.rows:
                if row["layer"]["uid"] == layer_uid:
                    entry = row["name_entry"]
                    entry.focus_set()
                    entry.icursor("end")
                    self.list.scroll_into_view(row["frame"])
                    return True
            return False

    class PreviewPanel(ttk.Frame):
        """Blattgetreue Vorschau: Beschriftungen auswählen (Strg/Umschalt wie im
        Explorer), gemeinsam ziehen und skalieren, Schichtgrenzen in den Säulen
        und den Maßstab mit der Maus verschieben."""

        ZOOM_LEVELS = [0.25, 0.33, 0.5, 0.67, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0]
        DRAG_THRESHOLD = 3              # Pixel, ab denen aus einem Klick ein Ziehen wird
        RULER_KEY = "ticks"             # Auswahlschlüssel des Maßstabs (Größe der Zahlen)
        HINT = ("Klick: auswählen · Strg/Umschalt+Klick oder Rahmen: mehrere · Ziehen: verschieben · "
                "Mausrad: Größe · Grenze in einer Säule ziehen: Mächtigkeit ändern · Rechtsklick: Menü")

        def __init__(self, master, app):
            super().__init__(master)
            self.app = app
            M = _mpl()
            self.M = M
            bar = ttk.Frame(self)
            bar.pack(fill="x")
            ttk.Button(bar, text="Einpassen", command=self.zoom_fit).pack(side="left")
            ttk.Button(bar, text="−", width=3, command=lambda: self.zoom_step(-1)).pack(side="left", padx=(6, 0))
            self.zoom_label = ttk.Label(bar, text="100 %", width=7, anchor="center")
            self.zoom_label.pack(side="left")
            ttk.Button(bar, text="+", width=3, command=lambda: self.zoom_step(1)).pack(side="left")
            ttk.Button(bar, text="↶", width=3, command=app.undo).pack(side="left", padx=(12, 0))
            ttk.Button(bar, text="↷", width=3, command=app.redo).pack(side="left")
            ttk.Button(bar, text="Alles auswählen", command=self.select_all).pack(side="left", padx=(12, 0))
            ttk.Button(bar, text="Beschriftungen zurücksetzen",
                       command=app.reset_all_labels).pack(side="left", padx=(6, 0))
            hint = ttk.Label(self, text=self.HINT, foreground="#666", font=UI_SMALL, anchor="w",
                             justify="left")
            hint.pack(fill="x", pady=(2, 4))
            hint.bind("<Configure>", lambda e: hint.configure(wraplength=max(200, e.width - 4)))

            holder = ttk.Frame(self)
            holder.pack(fill="both", expand=True)
            self.container = tk.Canvas(holder, background="#d5dbe0", highlightthickness=0)
            xbar = ttk.Scrollbar(holder, orient="horizontal", command=self.container.xview)
            ybar = ttk.Scrollbar(holder, orient="vertical", command=self.container.yview)
            self.container.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
            self.container.grid(row=0, column=0, sticky="nsew")
            ybar.grid(row=0, column=1, sticky="ns")
            xbar.grid(row=1, column=0, sticky="ew")
            holder.rowconfigure(0, weight=1)
            holder.columnconfigure(0, weight=1)

            self.fig = M.Figure(figsize=(8, 5), dpi=72)
            self.ax = self.fig.add_axes([0, 0, 1, 1])
            self.canvas = app.FigureCanvasTkAgg(self.fig, master=self.container)
            self.widget = self.canvas.get_tk_widget()
            self.window_id = self.container.create_window(0, 0, window=self.widget, anchor="nw")
            self.container.bind("<Configure>", self._on_container_resize)
            self.widget.bind("<Map>", lambda e: self.after_idle(self.apply_zoom), add="+")

            self.zoom = None          # None = einpassen, sonst Faktor (1,0 = 96 dpi)
            self.result = None
            self.selection = []       # Schlüssel der ausgewählten Elemente
            self.anchor = None        # Ausgangspunkt für Umschalt+Klick
            self.drag = None
            self.highlights = []
            self._bboxes = {}
            self._fit_job = None
            self._bg = None
            self._blit_artists = []
            self._blit_region = None
            self._zoom_accum = 0.0
            self._scroll_accum = 0.0
            self.menu = tk.Menu(self, tearoff=False)

            self.canvas.mpl_connect("button_press_event", self.on_press)
            self.canvas.mpl_connect("motion_notify_event", self.on_motion)
            self.canvas.mpl_connect("button_release_event", self.on_release)
            self.canvas.mpl_connect("scroll_event", self.on_scroll)
            self.canvas.mpl_connect("key_press_event", self.on_key)
            self.canvas.mpl_connect("draw_event", self._on_draw)

        # ----- Zeichnen und Zoom ------------------------------------------
        def render(self):
            try:
                result = render_project(self.fig, self.app.project, get_measurer())
            except Exception as exc:
                traceback.print_exc()
                self.ax.cla()
                self.ax.set_axis_off()
                self.ax.text(0.5, 0.5, f"Vorschaufehler:\n{exc}", transform=self.ax.transAxes,
                             ha="center", va="center", color="#b3261e")
                self.result = None
                self.highlights = []
                self.canvas.draw_idle()
                self.app.set_status([("error", f"Vorschaufehler: {exc}")])
                return
            self.result = result
            self.highlights = []          # ax.cla() hat die alten Rahmen entfernt
            valid = {item.key for item in result.items}
            if result.ruler:
                valid.add(self.RULER_KEY)
            self.selection = [key for key in self.selection if key in valid]
            if self.anchor not in valid:
                self.anchor = None
            self._update_highlight(draw=False)
            self.apply_zoom()
            self.canvas.draw_idle()
            self.app.set_status(result.messages)

        def _item(self, key):
            if not self.result or key is None:
                return None
            for item in self.result.items:
                if item.key == key:
                    return item
            return None

        def apply_zoom(self):
            if not self.result:
                return
            w_in = self.result.page_w / CM_PER_INCH
            h_in = self.result.page_h / CM_PER_INCH
            cw = self.container.winfo_width()
            ch = self.container.winfo_height()
            if cw < 30 or ch < 30:
                cw, ch = 900, 700
            if self.zoom is None:
                dpi = min((cw - 16) / w_in, (ch - 16) / h_in)
            else:
                dpi = self.zoom * 96.0
            dpi = max(6.0, min(dpi, 14000 / w_in, 14000 / h_in))
            self.fig.set_dpi(dpi)
            pw = max(1, int(round(w_in * dpi)))
            ph = max(1, int(round(h_in * dpi)))
            if int(self.widget.cget("width")) != pw or int(self.widget.cget("height")) != ph:
                self.widget.configure(width=pw, height=ph)
            x = max(0, (cw - pw) // 2)
            y = max(0, (ch - ph) // 2)
            self.container.coords(self.window_id, x, y)
            self.container.configure(scrollregion=(0, 0, max(cw, pw + 2 * x), max(ch, ph + 2 * y)))
            self.zoom_label.configure(text=f"{dpi / 96.0 * 100:.0f} %")
            self.fig.set_size_inches(w_in, h_in, forward=False)
            self.canvas.draw_idle()

        def _on_container_resize(self, _event):
            if self.zoom is None:
                if self._fit_job:
                    self.after_cancel(self._fit_job)
                self._fit_job = self.after(60, self.apply_zoom)
            elif self.result:
                self.apply_zoom()

        def zoom_fit(self):
            self.zoom = None
            self.apply_zoom()

        def zoom_step(self, direction):
            current = self.fig.dpi / 96.0
            if direction > 0:
                candidates = [z for z in self.ZOOM_LEVELS if z > current * 1.01]
                self.zoom = candidates[0] if candidates else self.ZOOM_LEVELS[-1]
            else:
                candidates = [z for z in self.ZOOM_LEVELS if z < current * 0.99]
                self.zoom = candidates[-1] if candidates else self.ZOOM_LEVELS[0]
            self.apply_zoom()

        def zoom_wheel(self, step):
            """Strg+Mausrad; Touchpads liefern Bruchteile einer Rasterstufe."""
            self._zoom_accum += step
            while self._zoom_accum >= 1:
                self.zoom_step(1)
                self._zoom_accum -= 1
            while self._zoom_accum <= -1:
                self.zoom_step(-1)
                self._zoom_accum += 1

        def scrollable(self):
            x0, x1 = self.container.xview()
            y0, y1 = self.container.yview()
            return (x1 - x0) < 0.999 or (y1 - y0) < 0.999

        def scroll_by(self, step, horizontal=False):
            self._scroll_accum += step
            units = int(self._scroll_accum)
            if not units:
                return
            self._scroll_accum -= units
            if horizontal:
                self.container.xview_scroll(-units * 2, "units")
            else:
                self.container.yview_scroll(-units * 2, "units")

        def scroll_container(self, event):
            step = event.delta / 120.0 if event.delta else 0.0
            if event.state & 0x0004:            # Strg über dem grauen Rand: zoomen
                self.zoom_wheel(step)
                return
            self.scroll_by(step, horizontal=bool(event.state & 0x0001))

        def _on_draw(self, event):
            self._bboxes = {}
            if not self.result:
                return
            renderer = event.renderer
            for item in self.result.items:
                try:
                    self._bboxes[item.key] = item.artist.get_window_extent(renderer=renderer)
                except Exception:
                    pass

        # ----- Auswahl ---------------------------------------------------------
        def _selected_items(self):
            items = []
            for key in self.selection:
                if key == self.RULER_KEY:
                    continue
                item = self._item(key)
                if item is not None:
                    items.append(item)
            return items

        def set_selection(self, keys, anchor=None, draw=True):
            self.selection = list(dict.fromkeys(keys))
            if anchor is not None or not self.selection:
                self.anchor = anchor
            self._update_highlight(draw=draw)

        def _toggle(self, key):
            if key in self.selection:
                self.selection.remove(key)
            else:
                self.selection.append(key)
            self.anchor = key
            self._update_highlight()

        def _range_keys(self, target):
            """Umschalt+Klick: alle Elemente gleicher Art zwischen Anker und Ziel."""
            anchor_item = self._item(self.anchor)
            if anchor_item is None or anchor_item.kind != target.kind:
                return [target.key]
            same = [item.key for item in self.result.items if item.kind == target.kind]
            a, b = same.index(anchor_item.key), same.index(target.key)
            if a > b:
                a, b = b, a
            return same[a:b + 1]

        def select_all(self):
            if not self.result:
                return
            keys = [item.key for item in self.result.items]
            self.set_selection(keys, anchor=keys[0] if keys else None)
            self.widget.focus_set()

        def _update_highlight(self, draw=True):
            for patch in self.highlights:
                try:
                    patch.remove()
                except Exception:
                    pass
            self.highlights = []
            if self.result:
                pad = 0.06
                for key in self.selection:
                    if key == self.RULER_KEY:
                        ruler = self.result.ruler
                        if not ruler:
                            continue
                        box = (ruler["x0"], ruler["y0"] - 0.2, ruler["x1"], ruler["y1"] + 0.2)
                    else:
                        item = self._item(key)
                        if item is None:
                            continue
                        box = item.bbox()
                    x0, y0, x1, y1 = box
                    self.highlights.append(self.ax.add_patch(self.M.patches.Rectangle(
                        (x0 - pad, y0 - pad), x1 - x0 + 2 * pad, y1 - y0 + 2 * pad, fill=False,
                        edgecolor="#1769aa", linewidth=1.0, linestyle=(0, (3, 2)), zorder=50)))
            if draw:
                self.canvas.draw_idle()

        # ----- Trefferprüfung ---------------------------------------------------
        def item_at(self, event):
            if not self.result or event.x is None:
                return None
            for item in reversed(self.result.items):
                bbox = self._bboxes.get(item.key)
                if bbox is None:
                    continue
                if bbox.x0 - 3 <= event.x <= bbox.x1 + 3 and bbox.y0 - 3 <= event.y <= bbox.y1 + 3:
                    return item
            return None

        def _event_xy(self, event):
            if event.xdata is not None and event.ydata is not None:
                return float(event.xdata), float(event.ydata)
            if event.x is None:
                return None
            x, y = self.ax.transData.inverted().transform((event.x, event.y))
            return float(x), float(y)

        def boundary_at(self, event):
            """Unterkante eines Säulensegments in der Nähe des Mauszeigers."""
            if not self.result or not self.result.bars or event.x is None:
                return None
            xy = self._event_xy(event)
            if xy is None:
                return None
            x, y = xy
            tol = 4.0 / (self.fig.dpi / CM_PER_INCH)
            best = None
            for bar in self.result.bars:
                if not bar["x0"] - tol <= x <= bar["x1"] + tol:
                    continue
                for segment in bar["segments"]:
                    if not segment["draggable_bottom"]:
                        continue
                    distance = abs(y - segment["y0"])
                    if distance <= tol and (best is None or distance < best[0]):
                        best = (distance, bar, segment)
            return None if best is None else (best[1], best[2])

        def on_ruler(self, event):
            ruler = self.result.ruler if self.result else None
            if not ruler or event.xdata is None or event.ydata is None:
                return False
            return (ruler["x0"] <= event.xdata <= ruler["x1"]
                    and ruler["y0"] - 0.2 <= event.ydata <= ruler["y1"] + 0.2)

        def _hit(self, event):
            """(Beschriftung, Grenze) unter dem Mauszeiger. In einer Säule haben
            Grenzen Vorrang vor den Zahlen im Balken."""
            item = self.item_at(event)
            boundary = None
            if item is None or item.kind == "value":
                boundary = self.boundary_at(event)
                if boundary is not None:
                    item = None
            return item, boundary

        @staticmethod
        def _mods(event):
            mods = set(getattr(event, "modifiers", None) or ())
            key = str(getattr(event, "key", "") or "")
            if "control" in key or "ctrl" in key:
                mods.add("ctrl")
            if "shift" in key:
                mods.add("shift")
            return mods

        # ----- Maus ---------------------------------------------------------
        def on_press(self, event):
            if not self.result or event.x is None or self.drag is not None:
                return
            self.widget.focus_set()
            mods = self._mods(event)
            item, boundary = self._hit(event)
            if event.button == 3:
                self._context_menu(event, item, boundary)
                return
            if event.button != 1:
                return
            if event.dblclick:
                self.drag = None
                if item is not None:
                    self.app.edit_item_source(item)
                elif boundary is not None:
                    self.app.edit_layer(boundary[0]["profile_uid"], boundary[1]["layer_uid"])
                return
            base = {"x0": event.x, "y0": event.y, "moved": False, "mods": mods,
                    "snapshot": self.app.snapshot()}
            if boundary is not None:
                self.drag = dict(base, type="boundary", bar=boundary[0], segment=boundary[1])
                return
            if item is not None:
                reduce = False
                if "shift" in mods:
                    keys = self._range_keys(item)
                    if "ctrl" in mods:
                        keys = self.selection + [k for k in keys if k not in self.selection]
                    if self.anchor is None:
                        self.anchor = item.key
                    self.set_selection(keys)
                elif "ctrl" in mods:
                    self._toggle(item.key)
                    if item.key not in self.selection:
                        return                       # abgewählt – nichts zu ziehen
                elif item.key in self.selection:
                    reduce = True   # wie im Explorer: ohne Ziehen bleibt nur dieses Element
                else:
                    self.set_selection([item.key], anchor=item.key)
                self.drag = dict(base, type="items", item=item, reduce=reduce)
                return
            if self.on_ruler(event):
                if "ctrl" in mods:
                    self._toggle(self.RULER_KEY)
                elif self.RULER_KEY not in self.selection:
                    self.set_selection([self.RULER_KEY], anchor=self.RULER_KEY)
                self.drag = dict(base, type="ruler")
                return
            self.drag = dict(base, type="rubber", start=self._event_xy(event))

        def on_motion(self, event):
            drag = self.drag
            if drag is None:
                self._hover(event)
                return
            if event.x is None:
                return
            if not drag["moved"]:
                if abs(event.x - drag["x0"]) + abs(event.y - drag["y0"]) < self.DRAG_THRESHOLD:
                    return
                drag["moved"] = True
                self._start_drag(drag)
            px_per_cm = self.fig.dpi / CM_PER_INCH
            ddx = (event.x - drag["x0"]) / px_per_cm
            ddy = (event.y - drag["y0"]) / px_per_cm
            kind = drag["type"]
            if kind == "items":
                for item, (dx0, dy0) in drag["starts"]:
                    item.dx = dx0 + ddx
                    item.dy = dy0 + ddy
                    apply_drag_item(item)
            elif kind == "ruler":
                shift = self.M.transforms.Affine2D().translate(ddx, 0) + self.ax.transData
                for artist in drag["artists"]:
                    artist.set_transform(shift)
                drag["ddx"] = ddx
            elif kind == "boundary":
                self._boundary_motion(drag, event)
            elif kind == "rubber":
                xy = self._event_xy(event)
                if xy is None or drag["start"] is None:
                    return
                (sx, sy), (cx, cy) = drag["start"], xy
                drag["rect"].set_bounds(min(sx, cx), min(sy, cy), abs(cx - sx), abs(cy - sy))
                drag["end"] = xy
            self._blit_draw()

        def _start_drag(self, drag):
            for patch in self.highlights:
                patch.set_visible(False)
            kind = drag["type"]
            if kind == "items":
                items = self._selected_items() or [drag["item"]]
                drag["starts"] = [(item, (item.dx, item.dy)) for item in items]
                artists = []
                for item in items:
                    artists.append(item.artist)
                    if item.leader is not None:
                        artists.append(item.leader)
                self._begin_blit(artists)
            elif kind == "ruler":
                ruler = self.result.ruler
                artists = list(ruler["artists"])
                if ruler.get("title_item") is not None:
                    artists.append(ruler["title_item"].artist)
                drag["artists"] = artists
                self._begin_blit(artists)
            elif kind == "boundary":
                self._boundary_start(drag)
            elif kind == "rubber":
                drag["rect"] = self.ax.add_patch(self.M.patches.Rectangle(
                    (0, 0), 0, 0, facecolor=(0.09, 0.41, 0.67, 0.08), edgecolor="#1769aa",
                    linewidth=0.8, linestyle=(0, (3, 2)), zorder=60))
                drag["end"] = drag["start"]
                self._begin_blit([drag["rect"]])

        def on_release(self, event):
            drag, self.drag = self.drag, None
            if drag is None:
                return
            kind = drag["type"]
            if not drag["moved"]:
                if kind == "items" and drag.get("reduce"):
                    self.set_selection([drag["item"].key], anchor=drag["item"].key)
                elif kind == "rubber" and not ({"ctrl", "shift"} & drag["mods"]) and self.selection:
                    self.set_selection([], anchor=None)
                return
            if kind == "rubber":
                self._end_blit(redraw=False)
                drag["rect"].remove()
                self._finish_rubber(drag)
            elif kind == "items":
                self._end_blit(redraw=False)
                self.app.push_undo(drag["snapshot"])
                for item, _ in drag["starts"]:
                    self.commit_item(item, mark=False)
                self.app.mark_dirty()
                self.app.schedule_render(0)
            elif kind == "ruler":
                self._end_blit(redraw=False)
                ruler = self.result.ruler
                new_x = ruler["cx"] + drag.get("ddx", 0.0)
                slot = sum(1 for c in self.result.bar_centers if c < new_x)
                if slot != ruler["slot"]:
                    self.app.push_undo(drag["snapshot"])
                    self.app.project["settings"]["ruler_slot"] = slot
                    self.app.mark_dirty()
                    self.app.refresh_settings_widgets()
                self.app.schedule_render(0)
            elif kind == "boundary":
                self._end_blit(redraw=False)
                self._boundary_finish(drag)

        def _finish_rubber(self, drag):
            if drag.get("start") is None or drag.get("end") is None:
                self._update_highlight()
                return
            (sx, sy), (ex, ey) = drag["start"], drag["end"]
            x0, x1 = sorted((sx, ex))
            y0, y1 = sorted((sy, ey))
            hits = []
            for item in self.result.items:
                bx0, by0, bx1, by1 = item.bbox()
                if bx1 >= x0 and bx0 <= x1 and by1 >= y0 and by0 <= y1:
                    hits.append(item.key)
            ruler = self.result.ruler
            if ruler and ruler["x1"] >= x0 and ruler["x0"] <= x1 and ruler["y1"] >= y0 and ruler["y0"] <= y1:
                hits.append(self.RULER_KEY)
            mods = drag["mods"]
            if "ctrl" in mods:
                selection = list(self.selection)
                for key in hits:
                    if key in selection:
                        selection.remove(key)
                    else:
                        selection.append(key)
            elif "shift" in mods:
                selection = self.selection + [k for k in hits if k not in self.selection]
            else:
                selection = hits
            self.set_selection(selection, anchor=hits[0] if hits else self.anchor)

        # ----- Schichtgrenzen ziehen ------------------------------------------
        def _boundary_start(self, drag):
            bar, segment = drag["bar"], drag["segment"]
            profile = next((p for p in self.app.project["profiles"] if p["uid"] == bar["profile_uid"]), None)
            geom = compute_profile_geometry(profile) if profile is not None else None
            if geom is None or geom.ok_problem or any(g.error for g in geom.layers):
                drag["invalid"] = True
                self.app.status_message("Grenzen lassen sich erst nach Behebung der Eingabefehler "
                                        "dieses Profils verschieben.", "error")
                self._begin_blit([])
                return
            layer = geom.layers[segment["index"]]
            following = next((g for g in geom.layers[segment["index"] + 1:]
                              if not g.missing and g.thickness > 1e-12), None)
            segments = bar["segments"]
            position = segments.index(segment)
            drag.update(profile=profile, geom=geom, layer=layer, following=following,
                        position=position, push="shift" in drag["mods"], new_bottom=layer.bottom)
            drag["seg_start"] = [(s, [(a, a.get_y(), a.get_height()) for a in s["artists"]])
                                 for s in segments[position:]]
            artists = []
            for s in segments[position:]:
                artists.extend(s["artists"])
                if s["value_item"] is not None:
                    artists.append(s["value_item"].artist)
            drag["tip"] = self.ax.text(0, 0, "", fontsize=8.5, color=TEXT_DARK, zorder=70,
                                       ha="left", va="bottom",
                                       bbox=dict(boxstyle="round,pad=0.3", facecolor="#fffbe6",
                                                 edgecolor="#c9b458", linewidth=0.6))
            drag["guide"] = self.ax.plot([bar["x0"] - 0.3, bar["x1"] + 0.3],
                                         [segment["y0"], segment["y0"]], color="#1769aa", lw=1.0,
                                         ls=(0, (2, 2)), zorder=65)[0]
            self._begin_blit(artists + [drag["tip"], drag["guide"]])

        def _boundary_motion(self, drag, event):
            if drag.get("invalid"):
                return
            xy = self._event_xy(event)
            if xy is None:
                return
            result, axis = self.result, self.result.axis
            bar, layer, following = drag["bar"], drag["layer"], drag["following"]
            depth = bar["top_v"] - result.y_to_v(xy[1])
            m_per_px = (axis.v_top - axis.v_bot) / (axis.plot_h * self.fig.dpi / CM_PER_INCH)
            snap = next((s for s in (0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0)
                         if s >= m_per_px), 10.0)
            depth = round(depth / snap) * snap
            low = layer.top + snap
            high = math.inf if (drag["push"] or following is None) else following.bottom - snap
            depth = max(low, min(high, depth)) if low <= high else layer.bottom
            drag["new_bottom"] = depth
            delta = depth - layer.bottom
            cm_per_m = axis.plot_h / (axis.v_top - axis.v_bot)
            y_new = result.v_to_y(bar["top_v"] - depth)
            shift = delta * cm_per_m
            for k, (segment, rects) in enumerate(drag["seg_start"]):
                is_following = (following is not None and segment["index"] == following.index
                                and not drag["push"])
                for artist, y0, height in rects:
                    if k == 0:
                        artist.set_y(y_new)
                        artist.set_height(max(0.0, y0 + height - y_new))
                    elif drag["push"]:
                        artist.set_y(y0 - shift)
                    elif is_following:
                        artist.set_height(max(0.0, y_new - y0))
                item = segment["value_item"]
                if item is None or not rects:
                    continue
                _, y0, height = rects[0]
                if k == 0:
                    thickness = layer.thickness + delta
                    item.artist.set_text(fmt_num(thickness, thickness_decimals(thickness)))
                    item.base_y = (y0 + height + y_new) / 2.0
                elif drag["push"]:
                    item.base_y = y0 + height / 2.0 - shift
                elif is_following:
                    thickness = following.bottom - depth
                    item.artist.set_text(fmt_num(thickness, thickness_decimals(thickness)))
                    item.base_y = (y0 + y_new) / 2.0
                item.dy = 0.0 if item.dy == 0 else item.dy
                apply_drag_item(item)
            unit = (self.app.project["settings"].get("height_unit") or "").strip() or "m"
            name = (layer.layer.get("name") or "").strip() or f"Schicht {layer.index + 1}"
            lines = [f"{name}: Mächtigkeit {fmt_num(layer.thickness + delta, 3)} m",
                     f"Unterkante {fmt_fixed(depth, 2)} m unter OK"]
            if drag["geom"].top_h is not None:
                lines[-1] += f" ({fmt_fixed(drag['geom'].top_h - depth, 2)} {unit})"
            if following is not None and not drag["push"]:
                other = (following.layer.get("name") or "").strip() or f"Schicht {following.index + 1}"
                lines.append(f"{other}: Mächtigkeit {fmt_num(following.bottom - depth, 3)} m")
            elif drag["push"]:
                lines.append("(Umschalt: tiefere Grenzen wandern mit)")
            drag["tip"].set_text(mpl_safe("\n".join(lines)))
            drag["tip"].set_position((bar["x1"] + 0.3, y_new + 0.1))
            drag["guide"].set_ydata([y_new, y_new])

        def _boundary_finish(self, drag):
            for key in ("tip", "guide"):
                artist = drag.get(key)
                if artist is not None:
                    try:
                        artist.remove()
                    except Exception:
                        pass
            if drag.get("invalid") or abs(drag["new_bottom"] - drag["layer"].bottom) < 1e-9:
                self.app.schedule_render(0)
                return
            self.app.push_undo(drag["snapshot"])
            done = move_boundary(drag["profile"], drag["layer"].index, drag["new_bottom"],
                                 push=drag["push"])
            if done is None:
                self.app.discard_checkpoint()
                self.app.status_message("Die Grenze konnte nicht verschoben werden.", "error")
                self.app.schedule_render(0)
                return
            self.app.on_profile_values_changed(drag["profile"])

        # ----- Mausrad, Tastatur --------------------------------------------
        def on_scroll(self, event):
            if not self.result or self.drag is not None:
                return
            step = float(event.step or 0.0)
            mods = self._mods(event)
            if "ctrl" in mods:
                self.zoom_wheel(step)
                return
            item, _ = self._hit(event)
            on_ruler = item is None and self.on_ruler(event)
            scrollable = self.scrollable()
            targets, ticks = [], False
            if item is not None:
                if item.key in self.selection:
                    targets, ticks = self._selected_items(), self.RULER_KEY in self.selection
                elif not scrollable:
                    self.set_selection([item.key], anchor=item.key, draw=False)
                    targets = [item]
            elif on_ruler:
                if self.RULER_KEY in self.selection:
                    targets, ticks = self._selected_items(), True
                elif not scrollable:
                    self.set_selection([self.RULER_KEY], anchor=self.RULER_KEY, draw=False)
                    ticks = True
            if not targets and not ticks:
                gui = getattr(event, "guiEvent", None)
                horizontal = bool(getattr(gui, "state", 0) & 0x0001)
                self.scroll_by(step, horizontal=horizontal)
                return
            self.widget.focus_set()
            self.app.push_undo(self.app.snapshot(), kind=("wheel", tuple(self.selection)))
            self._scale(targets, 1.1 ** step, ticks)
            self._update_highlight()
            self.app.schedule_render(150 if ticks else 350)

        def _scale(self, items, factor, ticks=False):
            for item in items:
                item.scale = clamp(item.scale * factor, 0.2, 8.0)
                apply_drag_item(item)
                self.commit_item(item, mark=False)
            if ticks:
                overrides = self.app.project.setdefault("overrides", {})
                current = (overrides.get(self.RULER_KEY) or {}).get("scale", 1.0)
                new = clamp(current * factor, 0.3, 5.0)
                if abs(new - 1.0) < 1e-3:
                    overrides.pop(self.RULER_KEY, None)
                else:
                    overrides[self.RULER_KEY] = {"dx": 0.0, "dy": 0.0, "scale": round(new, 4)}
            self.app.mark_dirty()

        def _hover(self, event):
            if not self.result or event.x is None:
                return
            item, boundary = self._hit(event)
            if item is not None:
                cursor = "fleur"
            elif boundary is not None:
                cursor = "sb_v_double_arrow"
            elif self.on_ruler(event):
                cursor = "sb_h_double_arrow"
            else:
                cursor = ""
            if self.widget.cget("cursor") != cursor:
                self.widget.configure(cursor=cursor)

        def on_key(self, event):
            key = str(event.key or "").lower()
            if key in ("ctrl+a", "control+a"):
                self.select_all()
                return
            if key == "escape":
                self.set_selection([], anchor=None)
                return
            items = self._selected_items()
            ticks = self.RULER_KEY in self.selection
            if not items and not ticks:
                return
            base = key.replace("shift+", "")
            step = 0.25 if key.startswith("shift+") else 0.05
            moves = {"left": (-step, 0.0), "right": (step, 0.0), "up": (0.0, step), "down": (0.0, -step)}
            if base in moves and items:
                self.app.push_undo(self.app.snapshot(), kind=("nudge", tuple(self.selection)))
                for item in items:
                    item.dx += moves[base][0]
                    item.dy += moves[base][1]
                    apply_drag_item(item)
                    self.commit_item(item, mark=False)
                self.app.mark_dirty()
            elif base in ("+", "=", "add"):
                self.app.push_undo(self.app.snapshot(), kind=("key-scale", tuple(self.selection)))
                self._scale(items, 1.1, ticks)
            elif base in ("-", "subtract"):
                self.app.push_undo(self.app.snapshot(), kind=("key-scale", tuple(self.selection)))
                self._scale(items, 1 / 1.1, ticks)
            elif base in ("delete", "backspace"):
                self.reset_items(items, position=True, size=True, ticks=ticks)
                return
            else:
                return
            self._update_highlight()
            self.app.schedule_render(400)

        def commit_item(self, item, mark=True):
            overrides = self.app.project.setdefault("overrides", {})
            stored_dx, stored_dy = item.stored_offset()
            dx, dy, scale = round(stored_dx, 4), round(stored_dy, 4), round(float(item.scale), 4)
            if abs(dx) < 1e-4 and abs(dy) < 1e-4 and abs(scale - 1.0) < 1e-4:
                overrides.pop(item.key, None)
            else:
                overrides[item.key] = {"dx": dx, "dy": dy, "scale": scale}
            if mark:
                self.app.mark_dirty()

        def reset_items(self, items, position=True, size=True, ticks=False):
            self.app.push_undo(self.app.snapshot())
            for item in items:
                if position:
                    item.dx = item.dy = 0.0
                if size:
                    item.scale = 1.0
                self.commit_item(item, mark=False)
            if ticks and size:
                self.app.project.setdefault("overrides", {}).pop(self.RULER_KEY, None)
            self.app.mark_dirty()
            self.app.schedule_render(0)

        def reset_ticks(self):
            if self.RULER_KEY not in self.app.project.get("overrides", {}):
                return
            self.app.push_undo(self.app.snapshot())
            self.app.project["overrides"].pop(self.RULER_KEY, None)
            self.app.mark_dirty()
            self.app.schedule_render(0)

        # ----- schnelles Neuzeichnen beim Ziehen (Blitting) ----------------
        def _begin_blit(self, artists):
            self._blit_artists = list(artists)
            for artist in self._blit_artists:
                artist.set_animated(True)
            self.canvas.draw()
            self._bg = self.canvas.copy_from_bbox(self.fig.bbox)
            self._blit_region = None
            self._blit_draw()

        def _artists_extent(self):
            from matplotlib.transforms import Bbox
            renderer = self.canvas.get_renderer()
            boxes = []
            for artist in self._blit_artists:
                try:
                    bbox = artist.get_window_extent(renderer)
                except Exception:
                    return None
                if bbox.width > 0 or bbox.height > 0:
                    boxes.append(bbox)
            if not boxes:
                return None
            union = Bbox.union(boxes)
            return Bbox.from_extents(union.x0 - 8, union.y0 - 8, union.x1 + 8, union.y1 + 8)

        def _blit_draw(self):
            from matplotlib.transforms import Bbox
            if self._bg is None:
                self.canvas.draw_idle()
                return
            self.canvas.restore_region(self._bg)
            for artist in self._blit_artists:
                self.ax.draw_artist(artist)
            current = self._artists_extent()
            region = current
            if current is not None and self._blit_region is not None:
                region = Bbox.union([current, self._blit_region])
            self._blit_region = current
            if region is not None:
                region = Bbox.intersection(region, self.fig.bbox)
            self.canvas.blit(region if region is not None else self.fig.bbox)

        def _end_blit(self, redraw=True):
            for artist in self._blit_artists:
                artist.set_animated(False)
            self._blit_artists = []
            self._bg = None
            self._blit_region = None
            for patch in self.highlights:
                patch.set_visible(True)
            if redraw:
                self.canvas.draw_idle()

        # ----- Kontextmenü --------------------------------------------------
        def _context_menu(self, event, item, boundary):
            menu = self.menu
            menu.delete(0, "end")
            if item is not None:
                if item.key not in self.selection:
                    self.set_selection([item.key], anchor=item.key)
                items = self._selected_items()
                ticks = self.RULER_KEY in self.selection
                suffix = f" ({len(items)} Elemente)" if len(items) > 1 else ""
                menu.add_command(label="Position zurücksetzen" + suffix,
                                 command=lambda: self.reset_items(items, True, False))
                menu.add_command(label="Größe zurücksetzen" + suffix,
                                 command=lambda: self.reset_items(items, False, True, ticks))
                menu.add_command(label="Position und Größe zurücksetzen" + suffix,
                                 command=lambda: self.reset_items(items, True, True, ticks))
                if len(items) == 1 and item.kind in ("label", "value", "title"):
                    menu.add_separator()
                    menu.add_command(label="Im Editor bearbeiten",
                                     command=lambda: self.app.edit_item_source(item))
                menu.add_separator()
            elif boundary is not None:
                bar, segment = boundary
                menu.add_command(label="Schicht im Editor bearbeiten",
                                 command=lambda: self.app.edit_layer(bar["profile_uid"],
                                                                     segment["layer_uid"]))
                menu.add_separator()
            elif self.on_ruler(event):
                menu.add_command(label="Maßstab automatisch positionieren",
                                 command=self.app.reset_ruler_slot)
                menu.add_command(label="Größe der Maßstabszahlen zurücksetzen", command=self.reset_ticks)
                menu.add_command(label="Maßstab ausblenden",
                                 command=lambda: self.app.set_setting("show_ruler", False))
                menu.add_separator()
            menu.add_command(label="Alles auswählen (Strg+A)", command=self.select_all)
            if self.selection:
                menu.add_command(label="Auswahl aufheben (Esc)",
                                 command=lambda: self.set_selection([], anchor=None))
            menu.add_separator()
            menu.add_command(label="Alle Beschriftungen zurücksetzen", command=self.app.reset_all_labels)
            menu.add_command(label="Einpassen", command=self.zoom_fit)
            gui = event.guiEvent
            try:
                menu.tk_popup(gui.x_root, gui.y_root)
            finally:
                menu.grab_release()

    class App(tk.Tk):
        def __init__(self, project_path=None):
            super().__init__()
            self.withdraw()
            self.title(APP_TITLE)
            self.geometry("1600x960")
            self.minsize(1180, 720)
            try:
                self.FigureCanvasTkAgg = ensure_matplotlib_gui()
            except Exception as exc:
                messagebox.showerror("Matplotlib fehlt", str(exc))
                self.destroy()
                raise SystemExit(1)
            self.project = default_project()
            self.path = None
            self.dirty = False
            self.undo_stack = []
            self.redo_stack = []
            self._edit_source = None
            self._last_undo_kind = None
            self._last_undo_time = 0.0
            self._render_job = None
            self._loading = False
            self.current = 0
            self._setting_refreshers = []
            self._setup_style()
            self._build_menu()
            self._build_ui()
            self._bind_keys()
            self.protocol("WM_DELETE_WINDOW", self.on_close)
            self.deiconify()
            self.load_project_data(self.project)
            if project_path:
                self.after(50, lambda: self.open_project(project_path))

        # ----- Aufbau -------------------------------------------------------
        def _setup_style(self):
            style = ttk.Style(self)
            for theme in ("vista", "clam"):
                if theme in style.theme_names():
                    style.theme_use(theme)
                    break
            self.option_add("*Font", UI_FONT)

        def _build_menu(self):
            menubar = tk.Menu(self)
            filemenu = tk.Menu(menubar, tearoff=False)
            filemenu.add_command(label="Neues Projekt", accelerator="Strg+N", command=self.new_project)
            filemenu.add_command(label="Projekt öffnen…", accelerator="Strg+O", command=self.open_project)
            filemenu.add_command(label="Projekt speichern", accelerator="Strg+S", command=self.save_project)
            filemenu.add_command(label="Projekt speichern unter…", accelerator="Strg+Umschalt+S",
                                 command=self.save_project_as)
            filemenu.add_separator()
            filemenu.add_command(label="Excel/CSV importieren…", command=self.import_table)
            filemenu.add_command(label="Grafik exportieren…", accelerator="Strg+E", command=self.export)
            filemenu.add_separator()
            filemenu.add_command(label="Beenden", command=self.on_close)
            menubar.add_cascade(label="Datei", menu=filemenu)
            editmenu = tk.Menu(menubar, tearoff=False)
            editmenu.add_command(label="Rückgängig", accelerator="Strg+Z", command=self.undo)
            editmenu.add_command(label="Wiederholen", accelerator="Strg+Y", command=self.redo)
            editmenu.add_separator()
            editmenu.add_command(label="Alle Beschriftungen zurücksetzen", command=self.reset_all_labels)
            editmenu.add_command(label="Farben nach Bezeichnung angleichen", command=self.unify_colors)
            menubar.add_cascade(label="Bearbeiten", menu=editmenu)
            helpmenu = tk.Menu(menubar, tearoff=False)
            helpmenu.add_command(label="Kurzanleitung", accelerator="F1", command=self.show_help)
            helpmenu.add_command(label="Lizenz (GNU GPL v3)…", command=self.show_license)
            helpmenu.add_command(label="♥ Mit PayPal unterstützen…", command=self.open_paypal)
            helpmenu.add_separator()
            helpmenu.add_command(label="Über", command=self.show_about)
            menubar.add_cascade(label="Hilfe", menu=helpmenu)
            self.configure(menu=menubar)

        def _build_ui(self):
            main = ttk.PanedWindow(self, orient="horizontal")
            main.pack(fill="both", expand=True, padx=6, pady=(6, 0))
            left = ttk.Frame(main, width=660)
            right = ttk.Frame(main)
            main.add(left, weight=2)
            main.add(right, weight=5)

            head = ttk.LabelFrame(left, text="Projekt", padding=(8, 5))
            head.pack(fill="x", padx=3, pady=(3, 2))
            ttk.Label(head, text="Hauptüberschrift:").grid(row=0, column=0, sticky="w")
            self.main_title_entry = self._setting_entry(head, "main_title", width=50, numeric=False)
            self.main_title_entry.grid(row=0, column=1, sticky="ew", padx=(6, 0))
            head.columnconfigure(1, weight=1)

            self.notebook = ttk.Notebook(left)
            self.notebook.pack(fill="both", expand=True, padx=3, pady=2)
            tab_profiles = ttk.Frame(self.notebook, padding=(4, 4))
            self.tab_axis = ttk.Frame(self.notebook, padding=(10, 8))
            tab_style = ttk.Frame(self.notebook, padding=(10, 8))
            self.notebook.add(tab_profiles, text="Profile und Schichten")
            self.notebook.add(self.tab_axis, text="Maßstab und Höhen")
            self.notebook.add(tab_style, text="Darstellung")
            self._build_profiles_tab(tab_profiles)
            self._build_axis_tab(self.tab_axis)
            self._build_style_tab(tab_style)

            actions = ttk.Frame(left)
            actions.pack(fill="x", padx=3, pady=(2, 4))
            ttk.Button(actions, text="Grafik exportieren (PNG / PDF / SVG / TIFF)…",
                       command=self.export).pack(fill="x", pady=(0, 4))
            row = ttk.Frame(actions)
            row.pack(fill="x")
            ttk.Button(row, text="Projekt speichern", command=self.save_project).pack(
                side="left", expand=True, fill="x")
            ttk.Button(row, text="Projekt laden…", command=self.open_project).pack(
                side="left", expand=True, fill="x", padx=4)
            ttk.Button(row, text="Excel/CSV importieren…", command=self.import_table).pack(
                side="left", expand=True, fill="x")

            preview_box = ttk.LabelFrame(right, text="Vorschau (entspricht dem Export)", padding=5)
            preview_box.pack(fill="both", expand=True, padx=3, pady=3)
            self.preview = PreviewPanel(preview_box, self)
            self.preview.pack(fill="both", expand=True)

            footer = ttk.Frame(self)
            footer.pack(fill="x", padx=8, pady=(2, 4))
            self.status = tk.Label(footer, text="", anchor="w", justify="left", font=UI_SMALL,
                                   fg="#555")
            self.status.pack(side="left", fill="x", expand=True)
            make_paypal_button(footer, self.open_paypal).pack(side="right")
            license_link = tk.Label(footer, text="© 2026 Peter Meurer · GNU GPL v3", fg="#1769aa",
                                    cursor="hand2", font=("Segoe UI", 9, "underline"))
            license_link.pack(side="right", padx=(0, 12))
            license_link.bind("<Button-1>", lambda e: self.show_license())

        def _build_profiles_tab(self, parent):
            top = ttk.Frame(parent)
            top.pack(fill="x")
            list_frame = ttk.Frame(top)
            list_frame.pack(side="left", fill="both", expand=True)
            ttk.Label(list_frame, text="Profile (Reihenfolge = Anordnung von links nach rechts):",
                      font=UI_SMALL, foreground="#555").pack(anchor="w")
            inner = ttk.Frame(list_frame)
            inner.pack(fill="both", expand=True)
            self.profile_list = tk.Listbox(inner, height=5, exportselection=False,
                                           activestyle="none", font=UI_FONT,
                                           selectbackground="#1769aa")
            scroll = ttk.Scrollbar(inner, orient="vertical", command=self.profile_list.yview)
            self.profile_list.configure(yscrollcommand=scroll.set)
            self.profile_list.pack(side="left", fill="both", expand=True)
            scroll.pack(side="left", fill="y")
            self.profile_list.bind("<<ListboxSelect>>", self._on_profile_select)
            buttons = ttk.Frame(top)
            buttons.pack(side="left", fill="y", padx=(6, 0))
            for text, command in (("＋ Neues Profil", self.add_profile),
                                  ("⧉ Duplizieren", self.duplicate_current_profile),
                                  ("✕ Entfernen", self.remove_profile),
                                  ("▲ nach links", lambda: self.move_profile(-1)),
                                  ("▼ nach rechts", lambda: self.move_profile(1))):
                ttk.Button(buttons, text=text, command=command, width=15).pack(fill="x", pady=1)
            ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(6, 2))
            self.editor = ProfileEditor(parent, self)
            self.editor.pack(fill="both", expand=True)

        def _grid_label(self, parent, row, text, column=0):
            ttk.Label(parent, text=text).grid(row=row, column=column, sticky="w", pady=3)

        def _hint(self, parent, row, text, column=2, columnspan=2):
            ttk.Label(parent, text=text, foreground="#666", font=UI_SMALL).grid(
                row=row, column=column, columnspan=columnspan, sticky="w", padx=(6, 0))

        def _build_axis_tab(self, p):
            r = 0
            self._grid_label(p, r, "Vertikale Darstellung:")
            self._setting_combo(p, "axis_mode", [
                ("auto", "Automatisch (Höhen, sobald OK/UK vorhanden)"),
                ("depth", "Tiefe – Profile oben bündig"),
                ("height", "Höhe – Profile nach OK/UK versetzt")], width=48).grid(
                row=r, column=1, columnspan=3, sticky="w", padx=(6, 0))
            r += 1
            self._grid_label(p, r, "Höhenbezug (Einheit):")
            self._setting_entry(p, "height_unit", width=14, numeric=False).grid(
                row=r, column=1, sticky="w", padx=(6, 0))
            self._hint(p, r, "z. B. m ü. NHN, m ü. NN, m rel.")
            r += 1
            self._grid_label(p, r, "Maßstabstitel:")
            self._setting_entry(p, "scale_title", width=24, numeric=False).grid(
                row=r, column=1, sticky="w", padx=(6, 0))
            self._hint(p, r, "leer = automatisch")
            r += 1
            self._grid_label(p, r, "Bereich oben / unten:")
            box = ttk.Frame(p)
            box.grid(row=r, column=1, sticky="w", padx=(6, 0))
            self._setting_entry(box, "range_top", width=8).pack(side="left")
            ttk.Label(box, text=" / ").pack(side="left")
            self._setting_entry(box, "range_bottom", width=8).pack(side="left")
            self.range_hint = ttk.Label(p, text="", foreground="#666", font=UI_SMALL)
            self.range_hint.grid(row=r, column=2, columnspan=2, sticky="w", padx=(6, 0))
            self._setting_refreshers.append(self._refresh_range_hint)
            r += 1
            self._grid_label(p, r, "Teilung (m):")
            self._setting_entry(p, "tick_step", width=8).grid(row=r, column=1, sticky="w", padx=(6, 0))
            self._hint(p, r, "leer = automatisch passend zum Bereich")
            r += 1
            self._grid_label(p, r, "Position des Maßstabs:")
            self.ruler_combo = ttk.Combobox(p, state="readonly", width=40)
            self.ruler_combo.grid(row=r, column=1, columnspan=3, sticky="w", padx=(6, 0))
            self.ruler_combo.bind("<<ComboboxSelected>>", self._on_ruler_combo)
            self._setting_refreshers.append(self._refresh_ruler_combo)
            r += 1
            self._hint(p, r, "Der Maßstab lässt sich auch in der Vorschau mit der Maus "
                             "zwischen die Profile ziehen.", column=1, columnspan=3)
            r += 1
            checks = ttk.Frame(p)
            checks.grid(row=r, column=0, columnspan=4, sticky="w", pady=(6, 2))
            self._setting_check(checks, "show_ruler", "Maßstab anzeigen").pack(side="left", padx=(0, 12))
            self._setting_check(checks, "show_staff", "als Nivellierlatte").pack(side="left", padx=(0, 12))
            self._setting_check(checks, "show_grid", "Hilfslinien").pack(side="left")
            r += 1
            ttk.Separator(p, orient="horizontal").grid(row=r, column=0, columnspan=4, sticky="ew", pady=8)
            r += 1
            self._grid_label(p, r, "Blatthöhe (cm):")
            self._setting_entry(p, "page_height_cm", width=8).grid(row=r, column=1, sticky="w", padx=(6, 0))
            self._hint(p, r, "Breite ergibt sich aus Anzahl und Beschriftung der Profile")
            r += 1
            self._grid_label(p, r, "Druckmaßstab 1 :")
            self._setting_entry(p, "print_scale", width=8).grid(row=r, column=1, sticky="w", padx=(6, 0))
            self._hint(p, r, "optional, z. B. 20 oder 50 – bestimmt dann die Höhe")
            r += 1
            self._grid_label(p, r, "Höhenkoten:")
            self._setting_combo(p, "kote_mode", [
                ("none", "keine"), ("profile", "OK und UK je Profil"),
                ("all", "an allen Schichtgrenzen")], width=26).grid(
                row=r, column=1, columnspan=3, sticky="w", padx=(6, 0))
            r += 1
            info = ("OK = Oberkante, UK = Unterkante des Profils (optional). Mit einer der beiden "
                    "Angaben werden die Profile höhengerecht versetzt; ohne Angabe werden sie oben "
                    "bündig nach Tiefe dargestellt. Sind OK und UK angegeben, prüft das Programm, "
                    "ob die Schichten zusammenpassen.")
            ttk.Label(p, text=info, foreground="#555", font=UI_SMALL, wraplength=560,
                      justify="left").grid(row=r, column=0, columnspan=4, sticky="w", pady=(10, 0))
            p.columnconfigure(3, weight=1)

        def _build_style_tab(self, p):
            r = 0
            self._grid_label(p, r, "Schriftart:")
            fonts = available_fonts()
            self._setting_combo(p, "font_family", [(f, f) for f in fonts], width=22).grid(
                row=r, column=1, sticky="w", padx=(6, 0))
            r += 1
            self._grid_label(p, r, "Schriftgröße gesamt (%):")
            self._setting_entry(p, "font_scale", width=8, percent=True).grid(
                row=r, column=1, sticky="w", padx=(6, 0))
            self._hint(p, r, "skaliert alle Texte")
            r += 1
            self._grid_label(p, r, "Schichtbeschriftung (pt):")
            self._setting_entry(p, "label_font_pt", width=8).grid(row=r, column=1, sticky="w", padx=(6, 0))
            r += 1
            self._grid_label(p, r, "Zeilenumbruch nach Zeichen:")
            self._setting_entry(p, "wrap_chars", width=8).grid(row=r, column=1, sticky="w", padx=(6, 0))
            r += 1
            self._grid_label(p, r, "Balkenbreite (cm):")
            self._setting_entry(p, "bar_width_cm", width=8).grid(row=r, column=1, sticky="w", padx=(6, 0))
            r += 1
            self._grid_label(p, r, "Abstand der Spalten (cm):")
            self._setting_entry(p, "column_gap_cm", width=8).grid(row=r, column=1, sticky="w", padx=(6, 0))
            r += 1
            self._grid_label(p, r, "Anordnung der Beschriftungen:")
            self._setting_combo(p, "label_layout", [
                ("even", "gleichmäßig verteilt (wie Vorlage)"),
                ("near", "an der jeweiligen Schicht")], width=32).grid(
                row=r, column=1, columnspan=2, sticky="w", padx=(6, 0))
            r += 1
            self._grid_label(p, r, "Zusatz in der Beschriftung:")
            self._setting_combo(p, "label_extra", [
                ("none", "nichts"), ("thickness", "Mächtigkeit"),
                ("depth", "Tiefe von–bis"), ("height", "Höhe von–bis")], width=32).grid(
                row=r, column=1, columnspan=2, sticky="w", padx=(6, 0))
            r += 1
            self._setting_check(p, "show_values", "Mächtigkeit im Balken anzeigen").grid(
                row=r, column=0, columnspan=3, sticky="w", pady=(6, 2))
            r += 1
            self._grid_label(p, r, "Export-Auflösung (dpi):")
            self._setting_entry(p, "export_dpi", width=8).grid(row=r, column=1, sticky="w", padx=(6, 0))
            self._hint(p, r, "für PNG, TIFF und JPG")
            r += 1
            box = ttk.Frame(p)
            box.grid(row=r, column=0, columnspan=3, sticky="w", pady=(14, 0))
            ttk.Button(box, text="Alle Beschriftungen zurücksetzen",
                       command=self.reset_all_labels).pack(side="left")
            ttk.Button(box, text="Farben nach Bezeichnung angleichen",
                       command=self.unify_colors).pack(side="left", padx=6)
            p.columnconfigure(2, weight=1)

        # ----- Einstellungs-Widgets ---------------------------------------
        def _setting_entry(self, parent, key, width=10, numeric=True, percent=False):
            var = tk.StringVar()
            if numeric:
                entry = tk.Entry(parent, textvariable=var, width=width, justify="right",
                                 relief="solid", bd=1, highlightthickness=0, font=UI_FONT)
            else:
                entry = ttk.Entry(parent, textvariable=var, width=width)

            def refresh():
                value = self.project["settings"].get(key)
                if percent:
                    text = fmt_num(value * 100, 1) if value is not None else ""
                elif value is None:
                    text = ""
                elif isinstance(value, float):
                    text = fmt_num(value, 4)
                else:
                    text = str(value)
                self._loading = True
                try:
                    var.set(text)
                finally:
                    self._loading = False
                if numeric:
                    entry.configure(bg=OK_BG)

            def on_write(*_):
                if self._loading:
                    return
                text = var.get()
                if percent:
                    number = parse_number(text)
                    ok, value = coerce_setting(key, None if number is None else number / 100.0)
                    ok = ok and number is not None
                else:
                    ok, value = coerce_setting(key, text)
                if numeric:
                    entry.configure(bg=OK_BG if ok else INVALID_BG)
                if not ok:
                    return
                self.note_edit(("setting", key))
                self.project["settings"][key] = value
                self.on_settings_changed(key)

            var.trace_add("write", on_write)
            self.track_entry(entry)
            self._setting_refreshers.append(refresh)
            return entry

        def _setting_check(self, parent, key, text):
            var = tk.BooleanVar()

            def command():
                self.set_setting(key, bool(var.get()))

            check = ttk.Checkbutton(parent, text=text, variable=var, command=command)
            self._setting_refreshers.append(lambda: var.set(bool(self.project["settings"].get(key))))
            return check

        def _setting_combo(self, parent, key, options, width=20):
            combo = ttk.Combobox(parent, state="readonly", width=width,
                                 values=[label for _, label in options])

            def selected(_event=None):
                self.set_setting(key, options[combo.current()][0])

            def refresh():
                value = self.project["settings"].get(key)
                values = [v for v, _ in options]
                combo.current(values.index(value) if value in values else 0)

            combo.bind("<<ComboboxSelected>>", selected)
            self._setting_refreshers.append(refresh)
            return combo

        def _ruler_options(self):
            titles = [profile_title(p, i) for i, p in enumerate(self.project["profiles"])]
            options = [(None, "Automatisch (Mitte)")]
            options.append((0, f"Links außen (vor {titles[0]})" if titles else "Links außen"))
            for i in range(1, len(titles)):
                options.append((i, f"Zwischen {titles[i - 1]} und {titles[i]}"))
            if titles:
                options.append((len(titles), f"Rechts außen (nach {titles[-1]})"))
            return options

        def _refresh_ruler_combo(self):
            options = self._ruler_options()
            self.ruler_combo.configure(values=[label for _, label in options])
            slot = self.project["settings"].get("ruler_slot")
            values = [v for v, _ in options]
            if slot is not None:
                slot = int(clamp(slot, 0, len(self.project["profiles"])))
            self.ruler_combo.current(values.index(slot) if slot in values else 0)

        def _on_ruler_combo(self, _event=None):
            options = self._ruler_options()
            self.set_setting("ruler_slot", options[self.ruler_combo.current()][0])

        def refresh_settings_widgets(self):
            for refresh in self._setting_refreshers:
                refresh()

        def set_setting(self, key, value):
            if self.project["settings"].get(key) == value:
                return
            self.checkpoint()
            self.project["settings"][key] = value
            self.refresh_settings_widgets()
            self.on_settings_changed(key)

        def on_settings_changed(self, key):
            self.mark_dirty()
            if key == "height_unit":
                self.editor.update_units()
                self.editor.refresh_computed()
            if key in ("range_top", "range_bottom"):
                # Der feste Bereich gilt für die Darstellung, in der er eingegeben wurde.
                st = self.project["settings"]
                if st.get("range_top") is None and st.get("range_bottom") is None:
                    st["range_mode"] = None
                else:
                    geoms = [compute_profile_geometry(p) for p in self.project["profiles"]]
                    st["range_mode"] = resolve_axis_mode(st, geoms, [])
                self._refresh_range_hint()
            self.schedule_render()

        def _refresh_range_hint(self):
            mode = self.project["settings"].get("range_mode")
            if getattr(self, "range_hint", None) is None:
                return
            if mode == "depth":
                text = "Tiefen in m (gilt für die Tiefendarstellung); leer = automatisch"
            elif mode == "height":
                text = "Höhen (gilt für die Höhendarstellung); leer = automatisch"
            else:
                text = "in m (Tiefe bzw. Höhe); leer = automatisch"
            self.range_hint.configure(text=text)

        # ----- Tastatur und Mausrad -----------------------------------------
        def _bind_keys(self):
            self.bind_all("<Control-n>", lambda e: self.new_project())
            self.bind_all("<Control-o>", lambda e: self.open_project())
            self.bind_all("<Control-s>", lambda e: self.save_project())
            self.bind_all("<Control-S>", lambda e: self.save_project_as())
            self.bind_all("<Control-e>", lambda e: self.export())
            self.bind_all("<Control-z>", lambda e: self.undo())
            self.bind_all("<Control-y>", lambda e: self.redo())
            self.bind_all("<F1>", lambda e: self.show_help())
            self.bind_all("<MouseWheel>", self._on_global_wheel, add="+")
            # Das Mausrad soll Auswahllisten nicht verstellen (z. B. „Eingabe als“),
            # sondern den umgebenden Bereich blättern.
            self.bind_class("TCombobox", "<MouseWheel>", self._combo_wheel)

        def _combo_wheel(self, event):
            self._on_global_wheel(event)
            return "break"

        def _on_global_wheel(self, event):
            try:
                widget = self.winfo_containing(event.x_root, event.y_root)
            except (KeyError, tk.TclError):
                return
            if widget is None or widget is self.preview.widget:
                return
            if widget.winfo_class() in ("TScrollbar", "Scrollbar"):
                return   # Bildlaufleisten blättern selbst
            current = widget
            while current is not None:
                if isinstance(current, ScrollFrame):
                    current.scroll_wheel(event)
                    return
                if current is self.preview.container:
                    self.preview.scroll_container(event)
                    return
                current = getattr(current, "master", None)

        # ----- Rückgängig ---------------------------------------------------
        def snapshot(self):
            return json.dumps(self.project, ensure_ascii=False, sort_keys=True)

        def push_undo(self, snapshot, kind=None):
            """Legt einen Rückgängig-Punkt an. Gleichartige Aktionen kurz
            hintereinander (Mausrad, gehaltene Pfeiltaste) ergeben einen Schritt."""
            now = time.monotonic()
            if kind is not None and kind == self._last_undo_kind and now - self._last_undo_time < 1.5:
                self._last_undo_time = now
                return
            if not (self.undo_stack and self.undo_stack[-1] == snapshot):
                self.undo_stack.append(snapshot)
                del self.undo_stack[:-200]
            self.redo_stack.clear()
            self._last_undo_kind = kind
            self._last_undo_time = now
            self._edit_source = None

        def checkpoint(self):
            """Vor einer Änderung aufrufen (Schaltflächen, Listen, Vorschau)."""
            self.push_undo(self.snapshot())

        def discard_checkpoint(self):
            if self.undo_stack and self.undo_stack[-1] == self.snapshot():
                self.undo_stack.pop()

        def track_entry(self, entry):
            # Ein neu fokussiertes Feld beginnt einen neuen Rückgängig-Schritt.
            entry.bind("<FocusIn>", lambda e: self._reset_edit_source(), add="+")

        def _reset_edit_source(self):
            self._edit_source = None

        def note_edit(self, source=None):
            """Vor dem Übernehmen einer Tastatureingabe aufrufen: Die erste Eingabe
            in einem Feld legt einen Rückgängig-Punkt mit dem Zustand davor an."""
            if source is None or source != self._edit_source:
                self.push_undo(self.snapshot())
                self._edit_source = source

        def _reset_undo_grouping(self):
            self._edit_source = None
            self._last_undo_kind = None

        def undo(self):
            if not self.undo_stack:
                self.bell()
                return
            self.redo_stack.append(self.snapshot())
            data = json.loads(self.undo_stack.pop())
            self.load_project_data(data, keep_history=True, keep_selection=True)
            self._reset_undo_grouping()
            self.mark_dirty()

        def redo(self):
            if not self.redo_stack:
                self.bell()
                return
            self.undo_stack.append(self.snapshot())
            data = json.loads(self.redo_stack.pop())
            self.load_project_data(data, keep_history=True, keep_selection=True)
            self._reset_undo_grouping()
            self.mark_dirty()

        # ----- Projektzustand -----------------------------------------------
        def load_project_data(self, data, keep_history=False, keep_selection=False):
            uid = None
            previous = self.current
            if keep_selection and self.project["profiles"]:
                uid = self.project["profiles"][min(self.current, len(self.project["profiles"]) - 1)]["uid"]
            self.project = normalize_project(data)
            if not keep_history:
                self.undo_stack.clear()
                self.redo_stack.clear()
            self._reset_undo_grouping()
            index = 0
            if keep_selection:
                # gleiches Profil wie vorher, sonst die vorherige Position
                index = min(previous, len(self.project["profiles"]) - 1)
                if uid is not None:
                    for i, profile in enumerate(self.project["profiles"]):
                        if profile["uid"] == uid:
                            index = i
                            break
            self.refresh_profile_list()
            self.select_profile(index)
            self.refresh_settings_widgets()
            self.schedule_render(0)

        def mark_dirty(self):
            if not self.dirty:
                self.dirty = True
                self.update_title()

        def mark_clean(self):
            self.dirty = False
            self.update_title()

        def update_title(self):
            name = os.path.basename(self.path) if self.path else "Unbenannt"
            self.title(f"{'*' if self.dirty else ''}{name} – {APP_TITLE} {APP_VERSION} – Peter Meurer")

        def schedule_render(self, delay=180):
            if self._render_job:
                self.after_cancel(self._render_job)
            self._render_job = self.after(delay, self._render_now)

        def _render_now(self):
            self._render_job = None
            if self.preview.drag is not None:
                # nicht mitten in einem Ziehvorgang neu zeichnen
                self._render_job = self.after(120, self._render_now)
                return
            self.preview.render()

        def set_status(self, messages):
            errors = [text for level, text in messages if level == "error"]
            warnings = [text for level, text in messages if level != "error"]
            lines = errors + warnings
            if not lines:
                count = len(self.project["profiles"])
                self.status.configure(text=f"{count} Profil{'e' if count != 1 else ''} · Vorschau aktuell",
                                      fg="#4d5a62")
                return
            text = "  ·  ".join(lines[:3])
            if len(lines) > 3:
                text += f"  (+{len(lines) - 3} weitere)"
            self.status.configure(text=text, fg="#b3261e" if errors else "#a05a00")

        def status_message(self, text, level="info"):
            colors = {"error": "#b3261e", "warning": "#a05a00", "info": "#2e7d32"}
            self.status.configure(text=text, fg=colors.get(level, "#4d5a62"))

        def on_profile_values_changed(self, profile):
            """Werte eines Profils wurden außerhalb des Editors geändert (Vorschau)."""
            if self.project["profiles"] and self.project["profiles"][self.current] is profile:
                view = self.editor.list.canvas.yview()[0]
                self.editor.load(profile)
                self.after_idle(lambda: self.editor.list.canvas.yview_moveto(view))
            self.mark_dirty()
            self.refresh_profile_list()
            self.schedule_render(0)

        def edit_layer(self, profile_uid, layer_uid):
            for i, profile in enumerate(self.project["profiles"]):
                if profile["uid"] == profile_uid:
                    self.notebook.select(0)
                    if i != self.current:
                        self.select_profile(i)
                    self.after_idle(lambda: self.editor.focus_layer(layer_uid))
                    return

        def _keep_ruler_right(self, old_count):
            """Steht der Maßstab rechts außen, bleibt er beim Anfügen rechts."""
            st = self.project["settings"]
            if st.get("ruler_slot") is not None and st["ruler_slot"] >= old_count:
                st["ruler_slot"] = len(self.project["profiles"])

        # ----- Profile ------------------------------------------------------
        def refresh_profile_list(self):
            lb = self.profile_list
            lb.delete(0, "end")
            for i, profile in enumerate(self.project["profiles"]):
                geom = compute_profile_geometry(profile)
                flag = "  ⚠" if geom.errors else ""
                lb.insert("end", f"{i + 1:>2}.  {profile_title(profile, i)}{flag}")
            if self.project["profiles"]:
                index = min(self.current, len(self.project["profiles"]) - 1)
                lb.selection_clear(0, "end")
                lb.selection_set(index)
                lb.see(index)

        def _on_profile_select(self, _event=None):
            selection = self.profile_list.curselection()
            if selection and selection[0] != self.current:
                self.select_profile(selection[0])

        def select_profile(self, index):
            profiles = self.project["profiles"]
            if not profiles:
                return
            index = int(clamp(index, 0, len(profiles) - 1))
            self.current = index
            self.profile_list.selection_clear(0, "end")
            self.profile_list.selection_set(index)
            self.profile_list.see(index)
            self.editor.load(profiles[index])

        def on_profiles_changed(self, structure=False):
            self.mark_dirty()
            if structure:
                self.refresh_profile_list()
            else:
                self._update_list_entry(self.current)
            self._refresh_ruler_combo()
            self.schedule_render()

        def _update_list_entry(self, index):
            profiles = self.project["profiles"]
            if not 0 <= index < len(profiles):
                return
            geom = compute_profile_geometry(profiles[index])
            flag = "  ⚠" if geom.errors else ""
            text = f"{index + 1:>2}.  {profile_title(profiles[index], index)}{flag}"
            if self.profile_list.get(index) != text:
                self.profile_list.delete(index)
                self.profile_list.insert(index, text)
                self.profile_list.selection_set(index)

        def add_profile(self):
            self.checkpoint()
            profiles = self.project["profiles"]
            mode = profiles[self.current]["input_mode"] if profiles else "thickness"
            if mode == "height":
                mode = "thickness"
            profile = make_profile(f"Profil {len(profiles) + 1}", default_layers(), mode)
            profiles.append(profile)
            self._keep_ruler_right(len(profiles) - 1)
            self.current = len(profiles) - 1
            self.refresh_profile_list()
            self.select_profile(self.current)
            self.on_profiles_changed(structure=True)
            self.editor.title_entry.focus_set()
            self.editor.title_entry.select_range(0, "end")

        def duplicate_current_profile(self):
            profiles = self.project["profiles"]
            if not profiles:
                return
            self.checkpoint()
            clone = duplicate_profile(profiles[self.current])
            clone["title"] = profile_title(profiles[self.current], self.current) + " (Kopie)"
            profiles.insert(self.current + 1, clone)
            slot = self.project["settings"].get("ruler_slot")
            if slot is not None and slot > self.current:
                self.project["settings"]["ruler_slot"] = slot + 1
            self.current += 1
            self.refresh_profile_list()
            self.select_profile(self.current)
            self.on_profiles_changed(structure=True)

        def remove_profile(self):
            profiles = self.project["profiles"]
            if len(profiles) <= 1:
                messagebox.showinfo("Hinweis", "Mindestens ein Profil muss vorhanden sein.", parent=self)
                return
            name = profile_title(profiles[self.current], self.current)
            if not messagebox.askyesno("Profil entfernen", f"„{name}“ wirklich entfernen?", parent=self):
                return
            self.checkpoint()
            removed = self.current
            profiles.pop(removed)
            slot = self.project["settings"].get("ruler_slot")
            if slot is not None and slot > removed:
                self.project["settings"]["ruler_slot"] = slot - 1
            self.current = min(removed, len(profiles) - 1)
            self.refresh_profile_list()
            self.select_profile(self.current)
            self.on_profiles_changed(structure=True)

        def move_profile(self, delta):
            profiles = self.project["profiles"]
            target = self.current + delta
            if not 0 <= target < len(profiles):
                return
            self.checkpoint()
            profiles[self.current], profiles[target] = profiles[target], profiles[self.current]
            self.current = target
            self.refresh_profile_list()
            self.select_profile(self.current)
            self.on_profiles_changed(structure=True)

        def edit_item_source(self, item):
            """Springt von einer Beschriftung der Vorschau in den Editor."""
            if item.kind in ("main_title",):
                self.main_title_entry.focus_set()
                return
            if item.kind == "scale_title":
                self.notebook.select(self.tab_axis)
                return
            if item.profile_uid is None:
                return
            for i, profile in enumerate(self.project["profiles"]):
                if profile["uid"] == item.profile_uid:
                    self.notebook.select(0)
                    if i != self.current:
                        self.select_profile(i)
                    if item.layer_uid:
                        self.after_idle(lambda: self.editor.focus_layer(item.layer_uid))
                    else:
                        self.editor.title_entry.focus_set()
                    return

        def reset_all_labels(self):
            if not self.project.get("overrides"):
                return
            self.checkpoint()
            self.project["overrides"] = {}
            self.mark_dirty()
            self.schedule_render(0)

        def reset_ruler_slot(self):
            self.set_setting("ruler_slot", None)

        def unify_colors(self):
            self.checkpoint()
            changed = unify_colors_by_name(self.project)
            if not changed:
                self.discard_checkpoint()
                messagebox.showinfo("Farben angleichen",
                                    "Alle Schichten mit gleicher Bezeichnung haben bereits dieselbe Farbe.",
                                    parent=self)
                return
            self.editor.load(self.project["profiles"][self.current])
            self.on_profiles_changed(structure=False)
            messagebox.showinfo("Farben angleichen", f"{changed} Schicht(en) umgefärbt.", parent=self)

        # ----- Dateien -----------------------------------------------------
        def _confirm_discard(self):
            if not self.dirty:
                return True
            answer = messagebox.askyesnocancel(
                "Ungespeicherte Änderungen", "Sollen die Änderungen am Projekt gespeichert werden?",
                parent=self)
            if answer is None:
                return False
            if answer:
                return self.save_project()
            return True

        def new_project(self):
            if not self._confirm_discard():
                return
            self.path = None
            self.current = 0
            self.load_project_data(default_project())
            self.mark_clean()

        def open_project(self, path=None):
            if path is None:
                if not self._confirm_discard():
                    return
                path = filedialog.askopenfilename(
                    title="Projekt öffnen", parent=self,
                    filetypes=[("Fremdprofilierung-Projekt", "*.json"), ("Alle Dateien", "*.*")])
                if not path:
                    return
            try:
                data = load_project_file(path)
            except Exception as exc:
                messagebox.showerror("Ladefehler", f"Projekt konnte nicht geladen werden:\n{exc}", parent=self)
                return
            self.path = path
            self.current = 0
            self.load_project_data(data)
            self.mark_clean()

        def save_project(self):
            if not self.path:
                return self.save_project_as()
            try:
                save_project_file(self.project, self.path)
            except Exception as exc:
                messagebox.showerror("Fehler beim Speichern", str(exc), parent=self)
                return False
            self.mark_clean()
            self.status.configure(text=f"Gespeichert: {self.path}", fg="#2e7d32")
            return True

        def save_project_as(self):
            initial = os.path.basename(self.path) if self.path else "Fremdprofilierung_Projekt.json"
            path = filedialog.asksaveasfilename(
                title="Projekt speichern", parent=self, initialfile=initial,
                defaultextension=".json", filetypes=[("Fremdprofilierung-Projekt", "*.json")])
            if not path:
                return False
            self.path = path
            return self.save_project()

        def export(self):
            path = filedialog.asksaveasfilename(
                title="Grafik speichern unter", parent=self, initialfile="Profile.png",
                defaultextension=".png",
                filetypes=[("PNG", "*.png"), ("PDF (Vektor)", "*.pdf"), ("SVG (Vektor)", "*.svg"),
                           ("TIFF", "*.tif"), ("JPEG", "*.jpg")])
            if not path:
                return
            try:
                self.config(cursor="watch")
                self.update_idletasks()
                result = export_figure(self.project, path)
            except Exception as exc:
                traceback.print_exc()
                messagebox.showerror("Exportfehler", str(exc), parent=self)
                return
            finally:
                self.config(cursor="")
            size = f"{fmt_num(result.page_w, 1)} × {fmt_num(result.page_h, 1)} cm"
            if messagebox.askyesno("Gespeichert", f"Grafik gespeichert ({size}):\n{path}\n\nJetzt öffnen?",
                                   parent=self):
                self.open_path(path)

        def import_table(self):
            path = filedialog.askopenfilename(
                title="Excel- oder CSV-Datei auswählen", parent=self,
                filetypes=[("Excel oder CSV", "*.xlsx *.xlsm *.xls *.csv *.txt"),
                           ("Alle Dateien", "*.*")])
            if not path:
                return
            try:
                try:
                    rows = read_table_file(path)
                except MissingDependency as missing:
                    if not messagebox.askyesno(
                            "Zusatzpaket benötigt",
                            f"Für diese Datei wird {', '.join(missing.packages)} benötigt.\n"
                            "Jetzt installieren?", parent=self):
                        return
                    subprocess.check_call([sys.executable, "-m", "pip", "install", *missing.packages])
                    rows = read_table_file(path)
                notes = []
                profiles = profiles_from_rows(rows, notes)
            except Exception as exc:
                messagebox.showerror("Import fehlgeschlagen", str(exc), parent=self)
                return
            if not profiles:
                messagebox.showerror("Import fehlgeschlagen",
                                     "In der Datei wurden keine Schichtdaten gefunden.\n\n"
                                     "Erwartet wird entweder eine Kopfzeile (z. B. Profil | Schicht | "
                                     "Mächtigkeit | Beschreibung | Farbe | OK) oder das Blockformat "
                                     "(Spalte A Bezeichnung, B Mächtigkeit, C Beschreibung; "
                                     "Leerzeilen trennen Profile).", parent=self)
                return
            note_text = ("\n\n" + "\n".join(notes)) if notes else ""
            answer = messagebox.askyesnocancel(
                "Excel/CSV-Import",
                f"{len(profiles)} Profil(e) gefunden.{note_text}\n\nJa = vorhandene Profile ersetzen\n"
                "Nein = an vorhandene Profile anhängen", parent=self)
            if answer is None:
                return
            self.checkpoint()
            if answer:
                self.project["profiles"] = profiles
                self.project["settings"]["ruler_slot"] = None
                first_new = 0
            else:
                old_count = len(self.project["profiles"])
                self.project["profiles"].extend(profiles)
                self._keep_ruler_right(old_count)
                first_new = old_count
            self.load_project_data(self.project, keep_history=True)
            self.select_profile(first_new)
            self.mark_dirty()

        def open_path(self, path):
            try:
                if sys.platform.startswith("win"):
                    os.startfile(path)  # noqa: S606 - bewusst: Datei mit Standardprogramm öffnen
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", path])
                else:
                    subprocess.Popen(["xdg-open", path])
            except Exception as exc:
                messagebox.showerror("Öffnen fehlgeschlagen", str(exc), parent=self)

        def open_url(self, url):
            import webbrowser
            webbrowser.open(url)

        def show_help(self):
            window = tk.Toplevel(self)
            window.title("Kurzanleitung")
            window.geometry("720x640")
            text = tk.Text(window, wrap="word", font=("Segoe UI", 10), padx=14, pady=10,
                           relief="flat", background="#fbfbfc")
            text.insert("1.0", HELP_TEXT)
            text.configure(state="disabled")
            text.pack(fill="both", expand=True)
            ttk.Button(window, text="Schließen", command=window.destroy).pack(pady=6)

        def open_paypal(self):
            self.open_url(PAYPAL_URL)

        def show_license(self):
            window = tk.Toplevel(self)
            window.title("Lizenz – GNU General Public License v3")
            window.geometry("760x680")
            window.transient(self)
            text_widget = tk.Text(window, wrap="word", font=("Consolas", 9), padx=12, pady=10,
                                  relief="flat", background="#fbfbfc")
            scroll = ttk.Scrollbar(window, orient="vertical", command=text_widget.yview)
            text_widget.configure(yscrollcommand=scroll.set)
            text_widget.insert("1.0", license_text())
            text_widget.configure(state="disabled")
            buttons = ttk.Frame(window, padding=6)
            buttons.pack(side="bottom", fill="x")
            ttk.Button(buttons, text="Online lesen (gnu.org)",
                       command=lambda: self.open_url(GPL_URL)).pack(side="left")
            ttk.Button(buttons, text="Schließen", command=window.destroy).pack(side="right")
            scroll.pack(side="right", fill="y")
            text_widget.pack(fill="both", expand=True)

        def show_about(self):
            window = tk.Toplevel(self)
            window.title("Über")
            window.resizable(False, False)
            window.transient(self)
            body = ttk.Frame(window, padding=(22, 18, 22, 14))
            body.pack(fill="both", expand=True)
            ttk.Label(body, text=f"{APP_TITLE} {APP_VERSION}", font=("Segoe UI", 13, "bold")).pack(anchor="w")
            ttk.Label(body, text="© 2026 Peter Meurer", font=UI_FONT).pack(anchor="w", pady=(2, 10))
            ttk.Label(body, text=GPL_NOTICE, font=UI_SMALL, wraplength=420, justify="left").pack(anchor="w")
            row = ttk.Frame(body)
            row.pack(fill="x", pady=(14, 0))
            make_paypal_button(row, self.open_paypal).pack(side="left")
            ttk.Button(row, text="Lizenz anzeigen", command=self.show_license).pack(side="left", padx=8)
            ttk.Button(row, text="Schließen", command=window.destroy).pack(side="right")

        def on_close(self):
            if not self._confirm_discard():
                return
            self.destroy()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help", "/?"):
        print(USAGE.format(version=APP_VERSION))
        return 0
    if argv and argv[0] in ("--export", "-e"):
        try:
            return cli_export(argv[1:])
        except Exception as exc:
            print(f"FEHLER: {exc}", file=sys.stderr)
            return 1
    if tk is None:
        print("Tkinter ist nicht verfügbar – nur der Export per Kommandozeile ist möglich.")
        print(USAGE.format(version=APP_VERSION))
        return 1
    app = App(argv[0] if argv else None)
    app.mainloop()
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        cli_mode = len(sys.argv) > 1 and sys.argv[1] in ("--export", "-e", "-h", "--help", "/?")
        if not cli_mode:
            # Bei Doppelklick bleibt das Fenster offen, damit die Meldung lesbar ist.
            try:
                input("\nFehler aufgetreten. Enter zum Schließen...")
            except EOFError:
                pass
        code = 1
    sys.exit(code)
