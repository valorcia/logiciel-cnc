"""python -m xyzac.ui.atelier — ouvre l'atelier dans le navigateur."""

import argparse
import os
import threading
import webbrowser

# Sans ecran, VTK tente d'ouvrir une connexion X, echoue, et imprime un
# avertissement en jaune avant de se rabattre tout seul sur le rendu logiciel.
# L'image sort quand meme — mais quelqu'un qui monte un kit et qui lit
# « bad X server connection » croit que le logiciel est casse. On choisit donc
# le rendu logiciel d'entree, et UNIQUEMENT s'il n'y a effectivement pas
# d'ecran : sur un poste qui en a un, forcer le logiciel serait plus lent pour
# rien.
if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
    os.environ.setdefault("VTK_DEFAULT_OPENGL_WINDOW", "vtkOSOpenGLRenderWindow")

from .server import servir
from .session import rendu_3d


def _plier(texte: str, largeur: int) -> list[str]:
    """Coupe un message pour un terminal etroit, sans dependance."""
    lignes, courante = [], ""
    for mot in texte.split():
        if courante and len(courante) + 1 + len(mot) > largeur:
            lignes.append(courante)
            courante = mot
        else:
            courante = f"{courante} {mot}".strip()
    if courante:
        lignes.append(courante)
    return lignes


def main() -> int:
    ap = argparse.ArgumentParser(description="Atelier XYZAC (simulation seule)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--sans-navigateur", action="store_true")
    a = ap.parse_args()

    srv = servir(a.port)
    url = f"http://127.0.0.1:{a.port}/"
    print("=" * 62)
    print("  ATELIER XYZAC — SIMULATION UNIQUEMENT")
    print("  Aucune machine n'est pilotee par cette fenetre.")
    print("=" * 62)
    print(f"  Ouvrez : {url}")
    print("  Pour arreter : Ctrl+C")
    print("=" * 62)
    # Controle au demarrage, et non a la premiere image : decouvrir qu'il
    # manque une bibliotheque APRES avoir choisi sa piece fait perdre le
    # fil, et la panne arrive alors sous une forme (image vide) qui ne dit
    # pas ce qu'il faut faire.
    manque = rendu_3d()
    if manque:
        print("  ATTENTION — les vues 3D ne marcheront pas :")
        for ligne in _plier(manque, 58):
            print(f"    {ligne}")
        print("  Le reste de l'atelier fonctionne : vous pouvez charger une")
        print("  piece et lancer la verification, mais sans image.")
        print("=" * 62)
    if not a.sans_navigateur:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\natelier ferme.")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
