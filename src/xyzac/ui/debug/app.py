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
    ap.add_argument("--tool", choices=("ballnose", "endmill"), default="ballnose",
                    help="type d'outil (hemispherique par defaut : voir "
                         "set_default_tool)")
    ap.add_argument("--analyse-face", type=int, default=-1,
                    help="analyse l'accessibilite de cette face et affiche le "
                         "resultat ; avec --capture, dessine les orientations")
    ap.add_argument("--points", type=int, default=8,
                    help="points de contact analyses (~70 ms chacun)")
    ap.add_argument("--reject-singular", action="store_true",
                    help="rejeter la singularite A=0 (par defaut elle est "
                         "permise : c'est un probleme de mouvement, pas de "
                         "position)")
    ap.add_argument("--pose", choices=("best", "worst", "none"), default="best",
                    help="place l'outil a la meilleure orientation admissible "
                         "('best'), a la plus mauvaise ('worst'), ou le laisse "
                         "au-dessus de la piece ('none')")
    ap.add_argument("--faces", action="store_true",
                    help="liste les faces de la piece et sort")
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
        state.set_default_tool(args.tool)
        for k, v in info.lines():
            print(f"  {k:20s} {v}")

    if args.faces:
        if state.part is None:
            print("--faces exige --step", file=sys.stderr)
            return 2
        print("\n  index  type        aire (mm2)")
        for idx, stype, area in state.face_list():
            print(f"  {idx:5d}  {stype:10s} {area:10.1f}")
        return 0

    # --- analyse d'accessibilite, avec ou sans ecran
    result = None
    if args.analyse_face >= 0:
        if state.part is None:
            print("--analyse-face exige --step", file=sys.stderr)
            return 2
        os.environ.setdefault("VTK_DEFAULT_OPENGL_WINDOW", "vtkOSOpenGLRenderWindow")
        try:
            result = state.analyse_face(
                args.analyse_face, max_points=args.points,
                reject_singular=args.reject_singular)
        except Exception as exc:                                 # noqa: BLE001
            print(f"analyse impossible : {exc}", file=sys.stderr)
            return 1
        print(f"\n{result.verdict()}")
        for k, v in result.summary_lines():
            print(f"  {k:26s} {v}")

        admis = [c for c in result.candidates if c.feasible]
        if admis and args.pose != "none":
            chosen = (max(admis, key=lambda c: c.margin_mm) if args.pose == "best"
                      else min(admis, key=lambda c: c.margin_mm))
            state.set_inspect_from_candidate(result, chosen)
            print(f"\n  outil place a l'orientation "
                  f"{'la plus degagee' if args.pose == 'best' else 'la plus juste'} :")
            for k, v in chosen.lines():
                print(f"    {k:20s} {v}")
        elif result.candidates:
            # Aucune orientation admissible : on place l'outil a une orientation
            # REFUSEE de la cause dominante. C'est la question que l'operateur
            # se pose devant une face inaccessible — « montre-moi pourquoi » —
            # et la pose de repos n'y repond pas.
            dominant = max((f for f in result.counts if f != "admissible"),
                           key=lambda f: result.counts[f], default=None)
            refuses = [c for c in result.candidates
                       if not c.feasible and c.family == dominant]
            if refuses:
                chosen = refuses[0]
                state.set_inspect_from_candidate(result, chosen)
                print(f"\n  aucune orientation admissible. Outil place a une "
                      f"orientation REFUSEE de la cause dominante "
                      f"({dominant}), pour montrer ce qui touche :")
                for k, v in chosen.lines():
                    print(f"    {k:20s} {v}")

        print("\n  collisions a la pose affichee, troncon par classe d'obstacle :")
        try:
            for a, b, c in state.collision_matrix():
                print(f"    {a:14s} {b:9s} {c}")
        except Exception as exc:                                 # noqa: BLE001
            print(f"    non disponible : {exc}")

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
                      zoom=args.zoom, fit=args.fit, accessibility=result)
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
