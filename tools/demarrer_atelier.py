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
import platform
import subprocess
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
VENV = RACINE / ".venv"
#: Tout ce qui s'affiche est AUSSI ecrit ici.
#:
#: Motif, rapporte par le premier essai sur une vraie machine : « il dit
#: appuyer sur une touche pour continuer puis plus rien ». Sous Windows, une
#: fenetre lancee au double-clic se referme des qu'on appuie sur une touche —
#: et elle emporte le message. L'utilisateur ne peut alors meme pas dire ce
#: qui s'est passe, ce qui rend le probleme indiagnosticable. Un journal ecrit
#: a cote du logiciel survit a la fermeture de la fenetre.
JOURNAL = RACINE / "demarrage.log"
#: Versions de Python pour lesquelles les roues de TOUTES les dependances
#: existent sur les trois systemes. Verifie sur PyPI, pas suppose : cadquery-ocp
#: ne publie pas de roue pour n'importe quelle version, et une compilation
#: d'OCCT depuis les sources n'est pas quelque chose qu'on demande a quelqu'un
#: qui voulait regarder une piece tourner.
VERSIONS_SURES = ((3, 11), (3, 12), (3, 13))

#: En dessous de ce temps, un atelier qui se termine ne s'est pas ARRETE : il
#: n'a pas demarre. La distinction n'est pas cosmetique — c'est elle qui decide
#: si l'on affiche « la page ne repond plus » (vrai seulement s'il y a eu une
#: page) ou la raison de l'echec.
DUREE_MINIMALE = 3.0


def python_du_venv() -> Path:
    return VENV / ("Scripts" if os.name == "nt" else "bin") / (
        "python.exe" if os.name == "nt" else "python")


def noter(ligne: str) -> None:
    """Ecrit dans le journal, sans jamais faire echouer le demarrage.

    Un journal qu'on n'arrive pas a ouvrir (dossier en lecture seule, cle USB
    retiree) ne doit pas empecher l'atelier de demarrer : il sert a expliquer
    une panne, il ne doit pas en creer une.
    """
    try:
        with JOURNAL.open("a", encoding="utf-8", errors="replace") as fh:
            fh.write(ligne if ligne.endswith("\n") else ligne + "\n")
    except OSError:
        pass


def dire(texte: str) -> None:
    print(f"  {texte}", flush=True)
    noter(f"  {texte}")


def titre(texte: str) -> None:
    bloc = f"\n{'=' * 62}\n  {texte}\n{'=' * 62}"
    print(bloc, flush=True)
    noter(bloc)


def lancer(cmd: list, *, quoi: str) -> None:
    """Execute en montrant la sortie A L'ECRAN **et** en la gardant.

    Ni ``subprocess.run(cmd)`` seul — qui affiche sans garder — ni
    ``capture_output`` — qui garde sans afficher. Les deux sont necessaires :
    on regarde pendant que ca tourne, et on relit apres que la fenetre s'est
    fermee.
    """
    noter(f"\n$ {' '.join(str(c) for c in cmd)}")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            errors="replace", bufsize=1)
    for ligne in proc.stdout:
        print(ligne, end="", flush=True)
        noter(ligne.rstrip("\n"))
    r = proc.wait()
    if r != 0:
        raise SystemExit(
            f"\n  ECHEC : {quoi}\n"
            f"  La commande exacte etait :\n    {' '.join(str(c) for c in cmd)}\n"
            f"  Tout est note dans :\n    {JOURNAL}\n"
            f"  Ouvrez ce fichier et envoyez-le si vous demandez de l'aide :\n"
            f"  il contient la raison, et elle est rarement celle qu'on "
            f"devine.\n")


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
    # Ce controle fabrique une vraie image, donc il charge VTK : mesure, une
    # quinzaine de secondes la premiere fois. Sans cette ligne, l'ecran reste
    # muet pendant tout ce temps et on croit que rien ne se passe — ce qui est
    # exactement l'impression qu'on cherche a eviter.
    dire("Verification de l'installation (quelques secondes)...")
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


def ouvrir_journal() -> None:
    """Entete de session : ce qu'on demanderait toujours en premier.

    Systeme, version de Python, dossier. Trois lignes qui evitent trois
    allers-retours de questions quand quelque chose se passe mal.
    """
    try:
        if JOURNAL.exists() and JOURNAL.stat().st_size > 1_000_000:
            JOURNAL.unlink()          # on garde l'historique, pas l'infini
    except OSError:
        pass
    noter("\n\n" + "#" * 62)
    noter(f"# {time.strftime('%Y-%m-%d %H:%M:%S')}  demarrage de l'atelier")
    noter(f"# systeme : {platform.platform()}")
    noter(f"# python  : {sys.version.splitlines()[0]}")
    noter(f"# dossier : {RACINE}")
    noter("#" * 62)


def main() -> int:
    ouvrir_journal()
    titre("ATELIER XYZAC — preparation")
    controler_version()
    py = preparer_venv()
    installer(py)
    corpus(py)
    echecs = 0
    while True:
        titre("ATELIER XYZAC — demarrage")
        dire("La page s'ouvre dans votre navigateur.")
        dire("Pour arreter : revenez ici et faites Ctrl+C.")
        print()
        debut = time.monotonic()
        try:
            code, lignes = suivre(
                [str(py), "-m", "xyzac.ui.atelier"] + sys.argv[1:])
        except KeyboardInterrupt:
            # Ctrl+C dans une console va a TOUT le groupe de processus : le
            # lanceur le recoit en meme temps que l'atelier. Sans ce filet, la
            # facon NORMALE d'arreter l'atelier — celle qu'on ecrit a l'ecran
            # deux lignes plus haut — se terminait par une trace Python.
            code, lignes = 0, []
        duree = time.monotonic() - debut

        # Un arret NORMAL, c'est un atelier qui a d'abord TOURNE. Un processus
        # qui se termine en une demi-seconde n'a pas ete arrete : il n'a pas
        # demarre. Confondre les deux faisait afficher « la page de votre
        # navigateur ne repond plus » a quelqu'un qui n'a jamais eu de page —
        # et cette phrase, en plus d'etre fausse, poussait la vraie raison hors
        # de l'ecran.
        anormal = code != 0 or duree < DUREE_MINIMALE
        if not anormal:
            echecs = 0
        else:
            echecs += 1
            rapporter_echec(code, duree, lignes)
            if echecs >= 2:
                dire("Deux echecs de suite : reessayer a l'identique donnera")
                dire("le meme resultat. Envoyez le journal ci-dessus.")
                return code or 1
        if not relancer(anormal):
            return code


def suivre(cmd: list) -> tuple[int, list]:
    """Comme ``lancer``, mais sans lever : l'atelier a le droit de s'arreter.

    Rend aussi les lignes produites, pour pouvoir les REMONTRER en cas
    d'echec : le temps qu'on lise le message d'arret, la raison est deja
    remontee hors de l'ecran.
    """
    noter(f"\n$ {' '.join(str(c) for c in cmd)}")
    lignes: list = []
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            errors="replace", bufsize=1)
    try:
        for ligne in proc.stdout:
            print(ligne, end="", flush=True)
            ligne = ligne.rstrip("\n")
            noter(ligne)
            lignes.append(ligne)
    except KeyboardInterrupt:
        proc.terminate()
        raise
    return proc.wait(), lignes


def rapporter_echec(code: int, duree: float, lignes: list) -> None:
    """Remontre la raison, au lieu de la laisser defiler hors de l'ecran."""
    titre("L'ATELIER NE S'EST PAS LANCE")
    if duree < DUREE_MINIMALE:
        dire(f"Il s'est termine au bout de {duree:.1f} s "
             f"(code de sortie {code}).")
        dire("Ce n'est pas un arret : un atelier qu'on arrete a la main a")
        dire("d'abord tourne. Celui-ci n'a pas demarre.")
    else:
        dire(f"Il s'est termine sur une erreur (code de sortie {code}).")
    utiles = [l for l in lignes if l.strip()]
    if utiles:
        print()
        dire("Les dernieres lignes qu'il a ecrites :")
        print()
        for l in utiles[-15:]:
            print(f"    | {l}")
    else:
        print()
        dire("Il n'a rien ecrit du tout, ce qui est inhabituel.")
    print()
    dire(f"Tout est note dans ce fichier, qui survit a la fermeture :")
    dire(f"  {JOURNAL}")


def relancer(anormal: bool = False) -> bool:
    """Propose de repartir plutot que de laisser une fenetre morte.

    Quand l'atelier s'arrete, la page du navigateur reste affichee et ne
    repond plus. Elle le DIT desormais, mais il faut encore pouvoir repartir —
    et « rouvrez le dossier et double-cliquez a nouveau » est une manoeuvre
    qu'on n'a pas envie de faire dix fois dans une soiree d'essais.

    Apres un ECHEC, la proposition change de sens et de defaut : relancer a
    l'identique ce qui vient de ne pas marcher n'a aucune raison de marcher, et
    proposer « oui » par defaut enverrait quelqu'un tourner en rond.

    Rien n'est demande quand personne ne peut repondre (script lance par un
    autre programme, integration continue) : une invite sans clavier derriere
    bloquerait pour toujours, ce qui est la pire facon d'echouer.
    """
    if not (sys.stdin and sys.stdin.isatty()):
        return False
    if anormal:
        print()
        try:
            reponse = input("  Reessayer quand meme ? [o/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        return reponse in ("o", "oui", "y", "yes")
    titre("ATELIER XYZAC — arrete")
    dire("La page de votre navigateur ne repond plus : elle vous le dit.")
    dire(f"Journal de cette session : {JOURNAL.name}")
    print()
    try:
        reponse = input("  Relancer l'atelier ? [O/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return reponse in ("", "o", "oui", "y", "yes")


if __name__ == "__main__":
    raise SystemExit(main())
