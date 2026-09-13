#!/usr/bin/env python3
"""Demarre l'atelier, en installant ce qui manque. A executer tel quel.

    python tools/demarrer_atelier.py

**Pourquoi ce fichier existe.** L'atelier est destine a quelqu'un qui monte une
machine en kit, pas a quelqu'un qui tient un terminal toute la journee. La
sequence « creer un environnement, l'activer, installer le bon extra, lancer le
module » est quatre occasions de se tromper, et les quatre echouent avec des
messages que seul un developpeur sait lire. Ce script la fait une fois pour
toutes, et chacune de ses etapes dit ce qu'elle fait pendant qu'elle le fait.

**Pourquoi en Python et pas en .bat ou en .ps1.** Un script systeme aurait du
etre ecrit en trois versions — Windows, macOS, Linux — dont deux ne seraient
jamais eprouvees ici. Celui-ci est le meme partout et se teste. Les lanceurs
``demarrer-atelier.bat`` et ``demarrer-atelier.command`` ne font donc rien
d'autre que l'appeler.

Il n'installe RIEN a l'exterieur : tout va dans un dossier ``.venv`` a cote du
logiciel, que l'on peut effacer d'un coup pour tout annuler.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
VENV = RACINE / ".venv"
#: Versions de Python pour lesquelles les roues de TOUTES les dependances
#: existent sur les trois systemes. Verifie sur PyPI, pas suppose : cadquery-ocp
#: ne publie pas de roue pour n'importe quelle version, et une compilation
#: d'OCCT depuis les sources n'est pas quelque chose qu'on demande a quelqu'un
#: qui voulait regarder une piece tourner.
VERSIONS_SURES = ((3, 11), (3, 12), (3, 13))


def python_du_venv() -> Path:
    return VENV / ("Scripts" if os.name == "nt" else "bin") / (
        "python.exe" if os.name == "nt" else "python")


def dire(texte: str) -> None:
    print(f"  {texte}", flush=True)


def titre(texte: str) -> None:
    print(f"\n{'=' * 62}\n  {texte}\n{'=' * 62}", flush=True)


def lancer(cmd: list, *, quoi: str) -> None:
    r = subprocess.run(cmd)
    if r.returncode != 0:
        raise SystemExit(
            f"\n  ECHEC : {quoi}\n"
            f"  La commande exacte etait :\n    {' '.join(str(c) for c in cmd)}\n"
            f"  Recopiez le message ci-dessus tel quel si vous demandez de "
            f"l'aide :\n  il contient la raison, et elle est rarement celle "
            f"qu'on devine.\n")


def controler_version() -> None:
    v = sys.version_info[:2]
    if v < (3, 11):
        raise SystemExit(
            f"\n  Votre Python est le {v[0]}.{v[1]}, et il en faut au moins "
            f"3.11.\n  Installez-le depuis https://www.python.org/downloads/ "
            f"puis relancez.\n")
    if v not in VERSIONS_SURES:
        dire(f"Python {v[0]}.{v[1]} : plus recent que les versions eprouvees "
             f"ici ({', '.join(f'{a}.{b}' for a, b in VERSIONS_SURES)}).")
        dire("On continue — mais si l'installation echoue sur cadquery-ocp,")
        dire("c'est qu'il n'existe pas encore de version prete pour ce "
             "Python-la.")


def preparer_venv() -> Path:
    py = python_du_venv()
    if py.exists():
        dire(f"Environnement deja present : {VENV}")
        return py
    dire(f"Creation de l'environnement dans {VENV}")
    dire("(un dossier a part ; l'effacer annule tout, sans rien laisser)")
    lancer([sys.executable, "-m", "venv", str(VENV)],
           quoi="creation de l'environnement")
    return py


def installer(py: Path) -> None:
    # On demande a l'atelier lui-meme s'il peut afficher : c'est le seul
    # controle qui porte sur la chose voulue. Un ``import`` qui reussit ne dit
    # pas qu'une image sortira.
    sonde = (
        "import sys;"
        "sys.path.insert(0, r'" + str(RACINE / 'src') + "');"
        "from xyzac.ui.atelier.session import rendu_3d;"
        "sys.exit(1 if rendu_3d() else 0)"
    )
    if subprocess.run([str(py), "-c", sonde],
                      capture_output=True).returncode == 0:
        dire("Tout est deja installe.")
        return
    # Le volume est MESURE sur une installation neuve (301 Mo de roues, dont
    # 146 pour VTK et 67 pour OCCT), pas estime. La duree, elle, ne peut pas
    # l'etre d'ici : elle depend de la ligne de celui qui installe. Annoncer
    # « une minute » parce que c'est le temps qu'il faut sur un serveur serait
    # une mesure faite sur la mauvaise machine.
    dire("Installation des bibliotheques : environ 300 Mo a telecharger,")
    dire("une seule fois. Comptez quelques minutes selon votre connexion.")
    dire("Beaucoup de lignes vont defiler : c'est normal, laissez faire.")
    print()
    lancer([str(py), "-m", "pip", "install", "--upgrade", "pip", "-q"],
           quoi="mise a jour de pip")
    lancer([str(py), "-m", "pip", "install", "-e", f"{RACINE}[atelier]"],
           quoi="installation des bibliotheques de l'atelier")


def corpus(py: Path) -> None:
    dossier = RACINE / "tests" / "corpus" / "step"
    if dossier.exists() and any(dossier.glob("*.step")):
        return
    dire("Fabrication des pieces d'exemple...")
    # Facultatif : sans elles, la liste d'exemples est vide, mais glisser son
    # propre STEP marche — et c'est le chemin normal. On ne bloque donc pas
    # le demarrage la-dessus.
    if subprocess.run([str(py), str(RACINE / "tools" / "make_corpus.py")],
                      capture_output=True).returncode != 0:
        dire("(les exemples n'ont pas pu etre fabriques — sans importance :")
        dire(" glissez votre propre fichier STEP sur la page)")


def main() -> int:
    titre("ATELIER XYZAC — preparation")
    controler_version()
    py = preparer_venv()
    installer(py)
    corpus(py)
    titre("ATELIER XYZAC — demarrage")
    dire("La page s'ouvre dans votre navigateur.")
    dire("Pour arreter : revenez ici et faites Ctrl+C.")
    print()
    return subprocess.run([str(py), "-m", "xyzac.ui.atelier"] + sys.argv[1:]).returncode


if __name__ == "__main__":
    raise SystemExit(main())
