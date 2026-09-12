"""Point d'entree du banc de debug.

    python -m xyzac.ui.debug                      # fenetre interactive
    python -m xyzac.ui.debug --step FICHIER.step  # ouvre un STEP au demarrage
    python -m xyzac.ui.debug --capture out/x.png --step F.step   # sans ecran

Le mode ``--capture`` n'est pas un mode degrade mais le mode utile sur une
machine sans interface graphique — un Raspberry Pi en SSH, ou une integration
continue. Il emprunte exactement le meme chemin de construction de scene que la
fenetre, donc il montre la meme chose.

**Regle de securite, non negociable** : ce programme n'importe pas
``linuxcnc_gateway`` et ne peut donc envoyer aucune commande a une machine. Le
bandeau « SIMULATION » de la fenetre n'est pas un etat mais une constante.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _has_display() -> bool:
    if sys.platform == "darwin" or os.name == "nt":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m xyzac.ui.debug",
        description="Banc de debug visuel XYZAC (V0). 100 % simulation.")
    ap.add_argument("--step", default="", help="STEP a ouvrir au demarrage")
    ap.add_argument("--capture", default="",
                    help="ecrit une capture PNG et sort, sans ouvrir de fenetre")
    ap.add_argument("--hide", default="",
                    help="calques a masquer dans la capture, separes par des virgules")
    ap.add_argument("--azimuth", type=float, default=0.0)
    ap.add_argument("--elevation", type=float, default=0.0)
    ap.add_argument("--zoom", type=float, default=1.0)
    ap.add_argument("--fit", choices=("part", "all"), default="part")
    args = ap.parse_args(argv)

    from .state import BenchState

    state = BenchState()
    if args.step:
        p = Path(args.step)
        if not p.exists():
            print(f"STEP introuvable : {p}", file=sys.stderr)
            return 2
        try:
            info = state.load_step(p)
        except Exception as exc:                                 # noqa: BLE001
            print(f"import refuse : {exc}", file=sys.stderr)
            return 1
        state.set_default_tool()
        for k, v in info.lines():
            print(f"  {k:20s} {v}")

    # --- mode capture : aucun ecran requis
    if args.capture:
        if state.part is None:
            print("--capture exige --step : il n'y a rien a capturer.",
                  file=sys.stderr)
            return 2
        os.environ.setdefault("VTK_DEFAULT_OPENGL_WINDOW", "vtkOSOpenGLRenderWindow")
        from .scene import capture

        hidden = {s.strip() for s in args.hide.split(",") if s.strip()}
        out = capture(state, args.capture, hidden=hidden,
                      azimuth_deg=args.azimuth, elevation_deg=args.elevation,
                      zoom=args.zoom, fit=args.fit)
        print(f"capture : {out.resolve()}")
        return 0

    # --- mode fenetre
    if not _has_display():
        print(
            "Aucun affichage detecte (DISPLAY vide).\n"
            "Le banc n'ouvre pas de fenetre sans ecran — il le dit plutot que de\n"
            "planter dans VTK. Deux options :\n"
            "  - sur une machine avec ecran : relancer sans --capture ;\n"
            "  - a distance ou en SSH : utiliser le mode capture, par exemple\n"
            "    python -m xyzac.ui.debug --step piece.step --capture out/vue.png",
            file=sys.stderr)
        return 3

    from PySide6 import QtWidgets

    from .window import DebugWindow

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    win = DebugWindow(state)
    if state.part is not None:
        win.rebuild_scene()
    win.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
