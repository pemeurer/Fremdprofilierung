# -*- coding: utf-8 -*-
"""Automatischer Oberflächentest: startet die App, simuliert Maus- und
Tastaturaktionen in der Vorschau und prüft die Wirkung. Screenshots in tests/output.
Aufruf:  python tests/gui_smoke.py   (öffnet kurz ein Fenster)"""

import importlib.util
import json
import math
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "output")
os.makedirs(OUT, exist_ok=True)

PROGRAM = os.path.join(ROOT, "Fremdprofilierung.py")
if not os.path.exists(PROGRAM):
    PROGRAM = os.path.join(ROOT, "Bohrprofil_Generator.py")
spec = importlib.util.spec_from_file_location("fp", PROGRAM)
fp = importlib.util.module_from_spec(spec)
sys.modules["fp"] = fp
spec.loader.exec_module(fp)

from matplotlib.backend_bases import KeyEvent, MouseEvent  # noqa: E402

# Dialoge nicht blockieren lassen
fp.messagebox.askyesno = lambda *a, **k: True
fp.messagebox.askyesnocancel = lambda *a, **k: False
fp.messagebox.showinfo = lambda *a, **k: None
fp.messagebox.showerror = lambda *a, **k: print("SHOWERROR", a, k)

FAILS = []
EXAMPLE = os.path.join(ROOT, "Beispiele", "Beispiel_Profile.json")


def check(cond, text):
    print(("OK   " if cond else "FAIL ") + text)
    if not cond:
        FAILS.append(text)


def pump(app, seconds=0.5):
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.02)


def screenshot(app, name):
    from PIL import ImageGrab
    app.update()
    x, y = app.winfo_rootx(), app.winfo_rooty()
    w, h = app.winfo_width(), app.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(os.path.join(OUT, name))


def center_px(pv, key):
    bbox = pv._bboxes[key]
    return (bbox.x0 + bbox.x1) / 2, (bbox.y0 + bbox.y1) / 2


def mouse(canvas, kind, x, y, button=None, step=0, dblclick=False, modifiers=None):
    if kind == "scroll_event":
        event = MouseEvent(kind, canvas, x, y, step=step, modifiers=modifiers)
    else:
        event = MouseEvent(kind, canvas, x, y, button=button, dblclick=dblclick, modifiers=modifiers)
    event._process()


def drag(canvas, x0, y0, x1, y1, modifiers=None, steps=8):
    mouse(canvas, "button_press_event", x0, y0, button=1, modifiers=modifiers)
    for i in range(1, steps + 1):
        mouse(canvas, "motion_notify_event", x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps,
              modifiers=modifiers)
    mouse(canvas, "button_release_event", x1, y1, button=1, modifiers=modifiers)


def click(canvas, x, y, modifiers=None):
    mouse(canvas, "button_press_event", x, y, button=1, modifiers=modifiers)
    mouse(canvas, "button_release_event", x, y, button=1, modifiers=modifiers)


def key(canvas, name):
    KeyEvent("key_press_event", canvas, name, 0, 0)._process()


def values(profile):
    return [layer["value"] for layer in profile["layers"]]


def main():
    app = fp.App()
    app.geometry("1600x960+20+20")
    app.attributes("-topmost", True)
    pump(app, 0.8)
    app.open_project(EXAMPLE)
    pump(app, 1.0)
    pv = app.preview
    canvas = pv.canvas
    check(pv.result is not None and len(pv.result.items) > 10, "Vorschau gerendert")
    w_in, h_in = pv.fig.get_size_inches()
    check(abs(w_in * 2.54 - pv.result.page_w) < 0.1 and abs(h_in * 2.54 - pv.result.page_h) < 0.1,
          "Figurgröße = Blattgröße")
    check("Fremdprofilierung" in app.title() or "Bohrprofil" in app.title(), f"Fenstertitel: {app.title()}")
    screenshot(app, "gui_01_start.png")
    project = app.project
    p0 = project["profiles"][0]
    k1 = "layer:" + p0["layers"][0]["uid"]
    k2 = "layer:" + p0["layers"][1]["uid"]
    k4 = "layer:" + p0["layers"][3]["uid"]

    # --- Einzelauswahl + Ziehen
    x, y = center_px(pv, k1)
    drag(canvas, x, y, x - 40, y + 30)
    pump(app, 0.4)
    ov = project["overrides"].get(k1)
    px_per_cm = pv.fig.dpi / 2.54
    check(ov is not None and abs(ov["dx"] - 40 / px_per_cm) < 0.05 and abs(ov["dy"] - 30 / px_per_cm) < 0.05,
          f"Ziehen speichert Versatz (nach außen): {ov}")
    check(pv.selection == [k1], f"Gezogenes Element ist ausgewählt ({pv.selection})")
    project["overrides"].pop(k1, None)
    app.schedule_render(0)
    pump(app, 0.4)

    # --- Strg+Klick: Mehrfachauswahl, Strg+Klick erneut: abwählen
    click(canvas, *center_px(pv, k1))
    click(canvas, *center_px(pv, k2), modifiers={"ctrl"})
    check(set(pv.selection) == {k1, k2}, f"Strg+Klick ergänzt die Auswahl ({len(pv.selection)})")
    check(len(pv.highlights) == 2, f"Zwei Auswahlrahmen ({len(pv.highlights)})")
    click(canvas, *center_px(pv, k2), modifiers={"ctrl"})
    check(pv.selection == [k1], "Strg+Klick auf Ausgewähltes wählt ab")

    # --- Umschalt+Klick: Bereich gleicher Art (Anker = zuletzt angeklicktes Element)
    click(canvas, *center_px(pv, k1))
    click(canvas, *center_px(pv, k4), modifiers={"shift"})
    expected = {"layer:" + p0["layers"][i]["uid"] for i in range(4)}
    check(set(pv.selection) == expected, f"Umschalt+Klick wählt Bereich ({len(pv.selection)} Beschriftungen)")

    # --- Gruppe gemeinsam ziehen
    x, y = center_px(pv, k2)
    drag(canvas, x, y, x, y - 25)
    pump(app, 0.5)
    moved = [project["overrides"].get(k, {}).get("dy") for k in expected]
    check(all(m is not None and abs(m + 25 / px_per_cm) < 0.05 for m in moved),
          f"Alle ausgewählten Beschriftungen verschoben ({moved})")

    # --- Mausrad skaliert die Auswahl, ein Rückgängig-Schritt für die Serie
    undo_len = len(app.undo_stack)
    x, y = center_px(pv, k2)
    mouse(canvas, "scroll_event", x, y, step=1)
    mouse(canvas, "scroll_event", x, y, step=1)
    pump(app, 0.6)
    scales = [project["overrides"][k]["scale"] for k in expected]
    check(all(abs(s - 1.21) < 0.01 for s in scales), f"Mausrad skaliert alle Ausgewählten ({scales})")
    check(len(app.undo_stack) == undo_len + 1, "Mausrad-Serie = ein Rückgängig-Schritt")

    # --- Entf setzt die Auswahl zurück
    key(canvas, "delete")
    pump(app, 0.5)
    check(not any(k in project["overrides"] for k in expected), "Entf setzt alle Ausgewählten zurück")

    # --- Rahmen auf freier Fläche
    r = pv.result
    xs = [it.bbox() for it in r.items if it.kind == "title"]
    x0c = min(b[0] for b in xs) - 0.3
    x1c = max(b[2] for b in xs) + 0.3
    yc = max(b[3] for b in xs) + 0.05
    y0c = min(b[1] for b in xs) - 0.05
    (sx, sy) = pv.ax.transData.transform((x0c, yc))
    (ex, ey) = pv.ax.transData.transform((x1c, y0c))
    drag(canvas, sx, sy, ex, ey)
    pump(app, 0.3)
    titles = {it.key for it in r.items if it.kind == "title"}
    check(set(pv.selection) >= titles, f"Rahmen wählt alle Profilüberschriften ({len(pv.selection)})")

    # --- Strg+A, Esc
    key(canvas, "ctrl+a")
    check(len(pv.selection) == len(pv.result.items), "Strg+A wählt alles")
    key(canvas, "escape")
    check(pv.selection == [], "Esc hebt die Auswahl auf")

    # --- Schichtgrenze ziehen (Teiler): Schicht 1 dicker, Schicht 2 dünner, Summe gleich
    bar = pv.result.bars[0]
    seg = bar["segments"][0]
    bx = (bar["x0"] + bar["x1"]) / 2
    px, py = pv.ax.transData.transform((bx, seg["y0"]))
    before = values(p0)
    total_before = sum(before)
    cm_per_m = pv.result.axis.plot_h / (pv.result.axis.v_top - pv.result.axis.v_bot)
    shift_px = 0.20 * cm_per_m * px_per_cm           # 20 cm tiefer
    drag(canvas, px, py, px, py - shift_px)
    pump(app, 0.6)
    after = values(app.project["profiles"][0])
    check(abs(after[0] - (before[0] + 0.2)) < 0.011 and abs(after[1] - (before[1] - 0.2)) < 0.011,
          f"Grenze ziehen ändert Mächtigkeiten ({before[:2]} -> {after[:2]})")
    check(abs(sum(after) - total_before) < 1e-6, "Gesamttiefe bleibt beim Teiler gleich")
    check(app.editor.rows[0]["value_var"].get() == fp.fmt_num(after[0], 4),
          f"Editor zeigt neuen Wert ({app.editor.rows[0]['value_var'].get()})")

    # --- Umschalt: tiefere Grenzen wandern mit (Gesamttiefe ändert sich)
    bar = pv.result.bars[0]
    seg = bar["segments"][1]
    px, py = pv.ax.transData.transform(((bar["x0"] + bar["x1"]) / 2, seg["y0"]))
    before = values(app.project["profiles"][0])
    drag(canvas, px, py, px, py - shift_px, modifiers={"shift"})
    pump(app, 0.6)
    after = values(app.project["profiles"][0])
    check(abs(after[1] - (before[1] + 0.2)) < 0.011 and abs(after[2] - before[2]) < 1e-9,
          f"Umschalt+Ziehen schiebt tiefere Schichten mit ({before[1:3]} -> {after[1:3]})")
    check(abs(sum(after) - (sum(before) + 0.2)) < 0.011, "Gesamttiefe wächst um 0,2 m")

    # --- Grenze in einem Profil mit Tiefen-Eingabe: nur die eine Tiefe ändert sich
    p2 = app.project["profiles"][2]
    bar = pv.result.bars[2]
    seg = bar["segments"][1]
    px, py = pv.ax.transData.transform(((bar["x0"] + bar["x1"]) / 2, seg["y0"]))
    before = values(p2)
    drag(canvas, px, py, px, py + 0.10 * cm_per_m * px_per_cm)   # 10 cm höher
    pump(app, 0.6)
    after = values(app.project["profiles"][2])
    check(abs(after[1] - (before[1] - 0.1)) < 0.011 and after[2] == before[2] and after[0] == before[0],
          f"Tiefen-Eingabe: nur die gezogene Unterkante ändert sich ({before} -> {after})")

    # --- Rückgängig stellt die Werte wieder her
    app.undo()
    pump(app, 0.5)
    check(values(app.project["profiles"][2]) == before, "Rückgängig nach Grenzverschiebung")

    # --- Maßstab ziehen nach links außen
    ruler = pv.result.ruler
    rx, ry = pv.ax.transData.transform((ruler["cx"], (ruler["y0"] + ruler["y1"]) / 2))
    tx, _ = pv.ax.transData.transform((pv.result.bar_centers[0] - 2.5, 0))
    drag(canvas, rx, ry, tx, ry)
    pump(app, 0.6)
    check(app.project["settings"]["ruler_slot"] == 0, f"Maßstab nach links ({app.project['settings']['ruler_slot']})")

    # --- Maßstabszahlen per Mausrad vergrößern (Maßstab ausgewählt)
    ruler = pv.result.ruler
    rx, ry = pv.ax.transData.transform((ruler["cx"], (ruler["y0"] + ruler["y1"]) / 2))
    click(canvas, rx, ry)
    check(pv.selection == [pv.RULER_KEY], "Klick wählt den Maßstab")
    mouse(canvas, "scroll_event", rx, ry, step=1)
    pump(app, 0.5)
    check(abs(app.project["overrides"].get("ticks", {}).get("scale", 1) - 1.1) < 1e-6,
          f"Mausrad vergrößert die Maßstabszahlen ({app.project['overrides'].get('ticks')})")

    # --- Texteingabe nach Rückgängig erzeugt neuen Schritt (Fokus bleibt im Feld)
    app.select_profile(0)
    pump(app, 0.2)
    var = app.editor.title_var
    var.set("BK 1a")
    n1 = len(app.undo_stack)
    app.undo()
    pump(app, 0.3)
    app.editor.title_var.set("BK 1b")
    check(len(app.undo_stack) >= n1 and not app.redo_stack, "Eingabe nach Rückgängig legt neuen Schritt an")

    # --- Editor: Wert ändern -> Maßstab passt sich an
    rows = app.editor.rows
    rows[-1]["value_var"].set("5,8")
    pump(app, 0.6)
    total = sum(v for v in values(app.project["profiles"][0]) if v)
    check(abs(pv.result.axis.v_bot + math.ceil(total * 2 - 1e-9) / 2) < 1e-6 or pv.result.axis.v_bot <= -total,
          f"Maßstab passt sich der Gesamttiefe {total:.2f} m an (unten {pv.result.axis.v_bot})")

    # --- Schicht verschieben bei Tiefen-Eingabe behält Mächtigkeiten
    app.select_profile(2)
    pump(app, 0.3)
    prof = app.project["profiles"][2]
    th_before = [round(g.thickness, 6) for g in fp.compute_profile_geometry(prof).layers]
    app.editor.move_layer(prof["layers"][1], 1)
    pump(app, 0.3)
    th_after = [round(g.thickness, 6) for g in fp.compute_profile_geometry(app.project["profiles"][2]).layers]
    check(th_after == [th_before[0], th_before[2], th_before[1], th_before[3]],
          f"▼ bei Tiefen-Eingabe tauscht Schichten mit ihren Mächtigkeiten ({th_before} -> {th_after})")

    # --- Profil hinzufügen bei Maßstab rechts außen
    app.set_setting("ruler_slot", len(app.project["profiles"]))
    app.add_profile()
    pump(app, 0.4)
    check(app.project["settings"]["ruler_slot"] == len(app.project["profiles"]),
          "Maßstab bleibt beim Anfügen rechts außen")

    # --- Rückgängig von „Neues Profil“ kehrt zum vorher bearbeiteten Profil zurück
    app.select_profile(1)
    pump(app, 0.2)
    count = len(app.project["profiles"])
    app.add_profile()
    pump(app, 0.3)
    app.undo()
    pump(app, 0.4)
    check(len(app.project["profiles"]) == count and app.current == 1,
          f"Rückgängig wählt wieder das vorher bearbeitete Profil (aktuell {app.current + 1})")
    app.redo()
    pump(app, 0.4)
    check(len(app.project["profiles"]) == count + 1, "Wiederholen legt das Profil erneut an")

    # --- Mit gedrücktem Mausrad (mittlere Taste) die Ansicht verschieben
    for _ in range(3):
        pv.zoom_step(1)
    pump(app, 0.6)
    check(pv.scrollable(), "Ansicht nach dem Zoomen verschiebbar")
    pv.container.xview_moveto(0.3)
    pv.container.yview_moveto(0.0)      # oben: nach unten ist Platz zum Verschieben
    pump(app, 0.2)
    x0, y0 = pv.container.xview()[0], pv.container.yview()[0]
    v_scroll = (pv.container.yview()[1] - pv.container.yview()[0]) < 0.999
    w = pv.widget
    rx, ry = w.winfo_rootx() + 200, w.winfo_rooty() + 200
    w.event_generate("<ButtonPress-2>", x=200, y=200, rootx=rx, rooty=ry)
    w.event_generate("<B2-Motion>", x=120, y=150, rootx=rx - 80, rooty=ry - 50)
    w.event_generate("<ButtonRelease-2>", x=120, y=150, rootx=rx - 80, rooty=ry - 50)
    pump(app, 0.3)
    x1, y1 = pv.container.xview()[0], pv.container.yview()[0]
    check(x1 > x0 and (y1 > y0 or not v_scroll),
          f"Gedrücktes Mausrad verschiebt die Ansicht ({x0:.3f}/{y0:.3f} -> {x1:.3f}/{y1:.3f})")
    check(w.cget("cursor") == "" and pv._pan is None, "Verschieben beendet, Mauszeiger zurückgesetzt")
    check(pv.selection == [] or pv.drag is None, "Mittlere Taste startet kein Ziehen von Elementen")
    # auch über dem grauen Rand
    c = pv.container
    crx, cry = c.winfo_rootx() + 5, c.winfo_rooty() + 5
    c.event_generate("<ButtonPress-2>", x=5, y=5, rootx=crx, rooty=cry)
    c.event_generate("<B2-Motion>", x=45, y=35, rootx=crx + 40, rooty=cry + 30)
    c.event_generate("<ButtonRelease-2>", x=45, y=35, rootx=crx + 40, rooty=cry + 30)
    pump(app, 0.3)
    x2, y2 = pv.container.xview()[0], pv.container.yview()[0]
    check(x2 < x1 and (y2 < y1 or not v_scroll),
          f"Verschieben auch über dem grauen Rand ({x1:.3f}/{y1:.3f} -> {x2:.3f}/{y2:.3f})")
    pv.zoom_fit()
    pump(app, 0.4)

    # --- Speichern / Laden / Export
    path = os.path.join(OUT, "gui_projekt.json")
    app.path = path
    check(app.save_project() is True and os.path.exists(path), "Projekt gespeichert")
    snap = app.snapshot()
    app.open_project(path)
    pump(app, 0.6)
    check(json.loads(app.snapshot())["profiles"] == json.loads(snap)["profiles"], "Laden ergibt identische Profile")
    res = fp.export_figure(app.project, os.path.join(OUT, "gui_export.png"), dpi=110)
    check(abs(res.page_w - pv.result.page_w) < 1e-6 and abs(res.page_h - pv.result.page_h) < 1e-6,
          "Export hat exakt die Blattgröße der Vorschau")
    screenshot(app, "gui_02_end.png")
    app.dirty = False
    app.destroy()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        FAILS.append("Ausnahme")
    print("\nERGEBNIS:", "alles OK" if not FAILS else f"{len(FAILS)} Fehler: {FAILS}")
    sys.exit(1 if FAILS else 0)
