#!/usr/bin/env python3
"""Recoupement chiffre : la cinematique de ce projet contre celle de LinuxCNC.

POURQUOI CET OUTIL EXISTE
-------------------------
Le jalon M9 a montre que la configuration demarre. Demarrer ne dit rien de
l'endroit ou LinuxCNC place reellement la pointe d'outil : un mauvais offset de
pivot demarre parfaitement et usine faux. Il faut donc comparer des NOMBRES.

La comparaison se fait en deux etages, et les deux sont necessaires :

  1. ``formule`` — mon modele contre une transcription de
     ``xyzacKinematicsInverse`` (src/emc/kinematics/trtfuncs.c). Rapide, sans
     rien installer, mais elle ne prouve que l'accord avec MA LECTURE de la
     source. Seule, c'est un miroir : une erreur de transcription rendrait
     l'accord parfait et faux.
  2. ``source`` — la meme comparaison contre la fonction de LinuxCNC
     COMPILEE. ``trtfuncs.c`` est compile tel quel avec quatre bouchons HAL,
     et sa fonction est appelee. C'est ce qui valide l'etage 1, et il ne
     demande ni arret d'urgence, ni prise d'origine, ni mouvement.

CE QUE CET OUTIL NE COUVRE PAS
------------------------------
Que le HAL porte bien les valeurs mesurees jusqu'a ces broches dans un systeme
qui tourne. Cela se lit par ``halcmd show pin xyzac`` sur une instance vivante,
et c'est consigne dans ``docs/validation-linuxcnc.md``.

Et le SIGNE des axes sur la machine reelle, qu'aucun calcul n'etablit.

EXIGENCES
---------
L'etage 1 ne demande rien. L'etage 2 demande un arbre source LinuxCNC et
``gcc`` ; la procedure pour l'obtenir est dans ``docs/validation-linuxcnc.md``.

Cet outil ne touche aucune machine et ne lance aucun mouvement : il compile
une fonction et l'appelle.
"""

from __future__ import annotations

import argparse
import itertools
import math
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from xyzac.kinematics_solver.solver import KinematicsSolver          # noqa: E402
from xyzac.machine_model import default_xyzac_kit                    # noqa: E402


# --------------------------------------------------------------- transcription

def linuxcnc_inverse(pos, a_deg, c_deg, *, x_rp, y_rp, z_rp, dy, dz, dt=0.0):
    """Transcription LITTERALE de ``xyzacKinematicsInverse`` (trtfuncs.c).

    Recopiee terme par terme, y compris l'ordre des termes, pour qu'une
    relecture cote a cote de la source soit possible. Sa fidelite n'est pas
    supposee : l'etage ``source`` la mesure.
    """
    a = math.radians(a_deg)
    c = math.radians(c_deg)
    dz = dz + dt
    px, py, pz = pos
    x = (+ math.cos(c) * (px - x_rp)
         - math.sin(c) * (py - y_rp)
         + x_rp)
    y = (+ math.sin(c) * math.cos(a) * (px - x_rp)
         + math.cos(c) * math.cos(a) * (py - y_rp)
         - math.sin(a) * (pz - z_rp)
         - math.cos(a) * dy
         + math.sin(a) * dz
         + dy
         + y_rp)
    z = (+ math.sin(c) * math.sin(a) * (px - x_rp)
         + math.cos(c) * math.sin(a) * (py - y_rp)
         + math.cos(a) * (pz - z_rp)
         - math.sin(a) * dy
         - math.cos(a) * dz
         + dz
         + z_rp)
    return np.array([x, y, z])


def hal_mapping(machine):
    """La correspondance que ``config.py`` ecrit dans le HAL.

    C'est l'objet reel du test : ni mon modele ni LinuxCNC ne sont en cause
    isolement, c'est le passage de l'un a l'autre qui se trompait.
    """
    pa = np.asarray(machine.pivot_a, dtype=float)
    pc = np.asarray(machine.pivot_c, dtype=float)
    return dict(x_rp=pc[0], y_rp=pc[1], z_rp=0.0, dy=pa[1] - pc[1], dz=pa[2])


# ------------------------------------------------------------------- les poses

POINTS = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (0.0, 12.0, 0.0),
          (0.0, 0.0, 15.0), (7.0, -3.0, 11.0), (-18.0, 22.0, -8.0),
          (23.3, 12.7, 5.5)]
ANGLES = [(0.0, 0.0), (0.0, 90.0), (0.0, -37.0), (-30.0, 0.0),
          (-75.0, 120.0), (-45.0, -160.0), (-12.5, 33.3), (25.0, 210.0)]


def machine_under_test(exagere: bool):
    """Machine d'epreuve.

    ``--exagere`` porte les pivots a des valeurs volontairement grandes. Ce
    n'est pas de la coquetterie : avec des pivots nuls, TOUTE correspondance de
    broches, juste ou fausse, donne le meme resultat. Le test ne serait alors
    pas faux, il serait aveugle — c'est la forme d'echec la plus courante de ce
    projet, une grandeur qui ne varie pas quand son parametre varie.
    """
    m = default_xyzac_kit().model_copy(deep=True)
    if exagere:
        m.pivot_c = [1.5, -2.5, 4.0]
        m.pivot_a = [0.7, 3.1, -39.2]
    return m


# ------------------------------------------------------------ etage 1 : formule

def etage_formule(machine) -> float:
    ks = KinematicsSolver(machine)
    m = hal_mapping(machine)
    pire = 0.0
    pire_cas = None
    for p, (a, c) in itertools.product(POINTS, ANGLES):
        mine = ks.part_to_machine_point(np.asarray(p, dtype=float), a, c)
        leur = linuxcnc_inverse(p, a, c, **m)
        e = float(np.max(np.abs(mine - leur)))
        if e > pire:
            pire, pire_cas = e, (p, a, c, mine, leur)
    n = len(POINTS) * len(ANGLES)
    print(f"  {n} poses, ecart max = {pire:.3e} mm")
    if pire > 1e-9 and pire_cas is not None:
        p, a, c, mine, leur = pire_cas
        print(f"    pire cas : p={p} A={a} C={c}")
        print(f"      modele   {np.array2string(mine, precision=6)}")
        print(f"      formule  {np.array2string(leur, precision=6)}")
    return pire


# ------------------------------------------------ etage 2 : la source compilee
#
# POURQUOI PAS EN PILOTANT L'IHM. La premiere version de cet etage lancait
# LinuxCNC, levait l'arret d'urgence, passait en MDI et relisait les
# articulations. Elle n'a jamais abouti, et le detail vaut d'etre garde :
# l'obstacle n'etait pas la cinematique mais tout ce qui l'entoure — memoire
# partagee residuelle d'une instance tuee, objet ``stat()`` construit avant
# que le serveur existe, garde-fou de processus qui se declenchait sur sa
# propre ligne de commande, et enfin un refus de mise en marche qui est un
# defaut reel de la configuration (voir docs/validation-linuxcnc.md).
#
# Or ce que cet etage devait etablir est precis : que la transcription de
# l'etage 1 est fidele. Compiler ``trtfuncs.c`` et APPELER sa fonction
# l'etablit directement, sans arret d'urgence, sans prise d'origine, sans NML.
# La complexite du pilotage etait accidentelle au regard de la question posee.
#
# Ce que cet etage ne couvre pas, et qu'il faut donc verifier ailleurs : que
# le HAL porte bien ces valeurs jusqu'a ces broches dans un systeme qui
# tourne. Cela se lit par ``halcmd show pin xyzac`` sur une instance vivante,
# et c'est consigne dans la note de validation.

BENCH_C = Path(__file__).resolve().parent / "kins_bench.c"

#: Fichiers source de LinuxCNC dont le banc a besoin, relativement a la racine
#: de l'arbre source.
SOURCES_LINUXCNC = ("src/emc/kinematics/trtfuncs.c",
                    "src/emc/kinematics/kins_util.c")
INCLUDES_LINUXCNC = ("src/emc/kinematics", "src/emc/nml_intf", "src/hal",
                     "src/rtapi", "include", "src")


def _compiler_bench(racine: Path, sortie: Path) -> Path:
    manquants = [f for f in SOURCES_LINUXCNC if not (racine / f).exists()]
    if manquants:
        raise FileNotFoundError(
            f"{racine} ne ressemble pas a un arbre source LinuxCNC : "
            f"{manquants} absent(s)")
    exe = sortie / "kins_bench"
    sortie.mkdir(parents=True, exist_ok=True)
    cmd = ["gcc", "-O2", "-o", str(exe), str(BENCH_C)]
    cmd += [str(racine / f) for f in SOURCES_LINUXCNC]
    for inc in INCLUDES_LINUXCNC:
        cmd += ["-I", str(racine / inc)]
    cmd += ["-DULAPI", "-lm"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("compilation du banc echouee :\n" + r.stderr[-2000:])
    return exe


def etage_source(machine, racine: Path, sortie: Path, *, tolerance: float) -> float:
    exe = _compiler_bench(racine, sortie)

    noms = subprocess.run([str(exe), "--pins"], capture_output=True,
                          text=True).stdout.split()
    print(f"  broches publiees par le module : {len(noms)}")
    for n in noms:
        print(f"    {n}")

    m = hal_mapping(machine)
    ks = KinematicsSolver(machine)
    poses = list(itertools.product(POINTS, ANGLES))
    entree = "\n".join(f"{p[0]} {p[1]} {p[2]} {a} {c}" for p, (a, c) in poses)
    r = subprocess.run(
        [str(exe), str(m["x_rp"]), str(m["y_rp"]), str(m["z_rp"]),
         str(m["dy"]), str(m["dz"])],
        input=entree, capture_output=True, text=True)
    lignes = [l for l in r.stdout.splitlines() if l.strip()]
    if len(lignes) != len(poses):
        raise RuntimeError(
            f"{len(lignes)} reponses pour {len(poses)} poses ; stderr : "
            f"{r.stderr[-500:]}")

    pire = 0.0
    pire_cas = None
    for (p, (a, c)), ligne in zip(poses, lignes):
        if ligne.strip() == "ERREUR":
            raise RuntimeError(f"la cinematique de LinuxCNC refuse p={p} A={a} C={c}")
        leur = np.array([float(v) for v in ligne.split()])
        mine = ks.part_to_machine_point(np.asarray(p, dtype=float), a, c)
        e = float(np.max(np.abs(mine - leur)))
        if e > pire:
            pire, pire_cas = e, (p, a, c, mine, leur)
    print(f"  {len(poses)} poses, ecart max = {pire:.3e} mm")
    if pire > tolerance and pire_cas is not None:
        p, a, c, mine, leur = pire_cas
        print(f"    pire cas : p={p} A={a} C={c}")
        print(f"      modele   {np.array2string(mine, precision=9)}")
        print(f"      LinuxCNC {np.array2string(leur, precision=9)}")
    return pire


# ------------------------------------------------------------------------ main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--etage", choices=["formule", "source", "les-deux"],
                    default="les-deux")
    ap.add_argument("--linuxcnc-source", default="",
                    help="racine d'un arbre source LinuxCNC (requis pour "
                         "l'etage 'source')")
    ap.add_argument("--exagere", action="store_true",
                    help="pivots volontairement grands : sans cela le test est "
                         "aveugle a la correspondance des broches")
    ap.add_argument("--out", default="out/epreuve-kins")
    ap.add_argument("--tolerance", type=float, default=1e-6,
                    help="ecart accepte, en mm")
    args = ap.parse_args()

    machine = machine_under_test(args.exagere)
    print("=" * 78)
    print("RECOUPEMENT DE CINEMATIQUE — projet contre LinuxCNC")
    print("=" * 78)
    print(f"pivot_c = {machine.pivot_c}    pivot_a = {machine.pivot_a}")
    if not args.exagere:
        print("  NOTE : pivots quasi nuls. Le resultat sera juste mais peu")
        print("  informatif sur la correspondance des broches — relancer avec")
        print("  --exagere pour un test qui voit quelque chose.")
    print(f"correspondance HAL : {hal_mapping(machine)}")
    print()

    ecarts = []
    if args.etage in ("formule", "les-deux"):
        print("[1] contre la TRANSCRIPTION de trtfuncs.c")
        ecarts.append(("formule", etage_formule(machine)))
        print()
    if args.etage in ("source", "les-deux"):
        print("[2] contre xyzacKinematicsInverse COMPILEE depuis trtfuncs.c")
        if not args.linuxcnc_source:
            print("  IGNORE : --linuxcnc-source non fourni.")
            print("  Cet etage compile la fonction de LinuxCNC et l'appelle ;")
            print("  il lui faut donc l'arbre source. Voir")
            print("  docs/validation-linuxcnc.md pour l'obtenir.")
            ecarts.append(("source", float("nan")))
        else:
            ecarts.append(("source",
                           etage_source(machine, Path(args.linuxcnc_source),
                                        Path(args.out),
                                        tolerance=args.tolerance)))
        print()

    print("=" * 78)
    code = 0
    for nom, e in ecarts:
        if e != e:                                  # NaN : etage ignore
            print(f"  {nom:12s} IGNORE")
            continue
        verdict = "ACCORD" if e <= args.tolerance else "DESACCORD"
        print(f"  {nom:12s} {verdict:9s} ecart max {e:.3e} mm "
              f"(tolerance {args.tolerance:.0e})")
        if e > args.tolerance:
            code = 1
    if code == 0:
        print()
        print("  Ce que cela etablit : les deux implementations calculent la")
        print("  MEME fonction. Ce que cela n'etablit pas : le SIGNE des axes")
        print("  sur la machine reelle, qui exige AXIS_DIRECTION.")
    print("=" * 78)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
