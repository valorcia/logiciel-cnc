#!/usr/bin/env python3
"""Banc de performance portable : mesurer, ici et sur le Raspberry Pi 5.

CE QUE CET OUTIL EST, ET CE QU'IL N'EST PAS
-------------------------------------------
Le projet vise un Raspberry Pi 5, et depuis le jalon M6 la documentation
repete « jamais mesure sur Pi 5 : l'extrapolation x3-5 reste une
extrapolation ». Cet outil ne supprime pas ce manque, il le rend
FRANCHISSABLE : il produit exactement les memes mesures sur deux machines, de
sorte que le rapport soit mesure et non devine.

Il ne predit rien. Un chiffre d'extrapolation n'apparait nulle part.

CE QUE LA COMPOSITION DU COUT IMPOSE DE MESURER
-----------------------------------------------
Profilage de la boucle chaude (verification d'une orientation sur 1 500
points, x86_64) :

    signed_clearance_to_segment      36 %   1 222 appels
    corps de check_many              36 %     282 appels
    reductions numpy (ufunc.reduce)  12 %   7 334 appels
    subset_near                       6 %     282 appels

Le travail porte sur des tableaux de ~1 980 x 16 float64, soit 256 ko : ils
tiennent dans le cache L2. Ce n'est donc **pas** un regime limite par la bande
passante memoire principale, et la transposition d'une machine a l'autre
depend du debit SIMD et du cout d'appel de numpy, pas du debit DDR. Les
micro-noyaux ci-dessous reproduisent ces tailles, et le triade memoire est
mesure a part pour qu'on puisse verifier cette lecture sur la machine cible.

**Portee des micro-noyaux.** Additionnes avec leurs multiplicites reelles
(1 fois les tableaux d'avant-boucle, 4,3 fois le noyau geometrique), ils
rendent compte d'environ la MOITIE du cout mesure d'un appel de
``check_many`` (4,1 ms sur 8,5 ms, x86_64). Le reste est le prefiltre conique
(arccos/arcsin), les masques de classe par tronçon, ``subset_near`` et
l'interpreteur. Les micro-noyaux servent donc a comprendre POURQUOI le rapport
entre deux machines est ce qu'il est ; la ligne qui tranche reste
``verify_ms_par_point`` de la chaine reelle.

USAGE
-----
    python tools/bench_platform.py                       # mesure + affiche
    python tools/bench_platform.py --json mesure.json    # enregistre
    python tools/bench_platform.py --compare ref.json    # rapport mesure/ref

Sur le Pi 5 :
    pip install -e ".[dev]"        # cadquery-ocp a une roue aarch64, voir §
    python tools/make_corpus.py
    python tools/bench_platform.py --compare docs/bench/x86_64.json
"""

from __future__ import annotations

import argparse
import json
import platform
import resource
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

#: Tailles MESUREES dans la boucle chaude, et non choisies pour faire joli.
#:
#: ``N_OBST`` est la mediane du champ d'obstacles apres prefiltre spherique
#: (1 980 sur 282 appels, min 1 817) : c'est la taille des tableaux (N, M)
#: construits AVANT la boucle par tronçon.
#:
#: ``N_ROWS`` est la mediane des lignes que la bande par coquille laisse
#: passer a ``signed_clearance_to_segment`` : 691 sur 1 980, et 4,3 tronçons
#: sur 13 sont evalues. Employer N_OBST ici surestimait le cout de ce noyau
#: d'un facteur 3,5 — le banc mesurait alors une taille qui n'existe pas.
#: La distribution est tres dissymetrique (moyenne 1 368, min 27, max 8 038),
#: d'ou la mesure aux deux tailles.
N_OBST = 1980
N_ROWS = 691
M_POSES = 16


def _chrono(f, *, cible_s: float = 0.4) -> float:
    """Temps par appel, avec un nombre de repetitions adapte a la machine.

    Un nombre fixe de repetitions donne soit une mesure bruitee sur une
    machine lente, soit un banc interminable sur une machine rapide. On calibre
    donc sur une premiere passe.
    """
    f()                                     # rechauffement
    t0 = time.perf_counter()
    f()
    seul = time.perf_counter() - t0
    n = max(1, min(20000, int(cible_s / max(seul, 1e-9))))
    t0 = time.perf_counter()
    for _ in range(n):
        f()
    return (time.perf_counter() - t0) / n


def plateforme() -> dict:
    import numpy
    info = {
        "machine": platform.machine(),
        "processeur": platform.processor() or "?",
        "systeme": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "numpy": numpy.__version__,
    }
    try:
        with open("/proc/cpuinfo") as f:
            for l in f:
                if l.startswith(("model name", "Model")):
                    info["cpu"] = l.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    try:
        import os
        info["coeurs"] = os.cpu_count()
        with open("/proc/meminfo") as f:
            for l in f:
                if l.startswith("MemTotal:"):
                    info["ram_go"] = round(int(l.split()[1]) / 1e6, 1)
                    break
    except OSError:
        pass
    try:
        cfg = numpy.show_config(mode="dicts")
        blas = cfg.get("Build Dependencies", {}).get("blas", {})
        info["blas"] = f"{blas.get('name','?')} {blas.get('version','')}".strip()
    except Exception:
        info["blas"] = "?"
    return info


def micro() -> dict:
    """Micro-noyaux aux tailles reelles de la boucle chaude."""
    from xyzac.collision_engine.tool_collision import signed_clearance_to_segment

    rng = np.random.default_rng(12345)
    pts = rng.random((N_OBST, 3)) * 60.0
    axes = rng.random((M_POSES, 3)); axes /= np.linalg.norm(axes, axis=1, keepdims=True)
    tcps = rng.random((M_POSES, 3)) * 5.0
    z = pts @ axes.T - np.sum(tcps * axes, axis=1)[None, :]
    r = np.abs(rng.random((N_OBST, M_POSES))) * 30.0

    out = {}
    # noyau geometrique, aux DEUX tailles reelles : la mediane et la moyenne
    # de la distribution des lignes retenues par la bande par coquille.
    for n in (N_ROWS, 1368):
        zr, rr = z[:n], r[:n]
        out[f"clearance_{n}x{M_POSES}_us"] = _chrono(
            lambda: signed_clearance_to_segment(rr, zr, 0.0, 20.0, 3.0, 3.0)) * 1e6
    out["z_all_us"] = _chrono(
        lambda: pts @ axes.T - np.sum(tcps * axes, axis=1)[None, :]) * 1e6
    out["d2_us"] = _chrono(
        lambda: np.sum(pts * pts, axis=1)[:, None] - 2.0 * (pts @ tcps.T)
        + np.sum(tcps * tcps, axis=1)[None, :]) * 1e6
    out["r_all_us"] = _chrono(lambda: np.sqrt(np.maximum(r - z * z, 0.0))) * 1e6
    out["min_axis0_us"] = _chrono(lambda: r.min(axis=0)) * 1e6
    out["norm_axis1_us"] = _chrono(
        lambda: np.linalg.norm(pts - pts[0], axis=1)) * 1e6
    # surcout d'appel numpy : le meme calcul sur un tableau minuscule
    petit = rng.random((16, 3))
    out["surcout_appel_numpy_us"] = _chrono(
        lambda: np.linalg.norm(petit, axis=1)) * 1e6
    # triade memoire, hors cache : dit si la machine est limitee par la DDR
    for mo in (4, 64):
        n = int(mo * 1e6 / 8)
        a = rng.random(n); b = rng.random(n)
        dt = _chrono(lambda: a + b, cible_s=0.6)
        out[f"triade_{mo}Mo_Go_par_s"] = 3 * n * 8 / dt / 1e9
    return out


def macro(corpus: Path) -> dict:
    """Chaine reelle sur une geometrie du corpus."""
    from xyzac.accessibility_solver.solver import (AccessibilityConfig,
                                                   AccessibilitySolver)
    from xyzac.geometry_core import brep
    from xyzac.strategy_planner.indexed_pass import decide_indexed_pass
    from xyzac.subtractive_slicer.finishing import (generate_finishing_passes,
                                                    group_faces_by_normal)
    from xyzac.ui.debug.state import BenchState

    step = corpus / "C10_dome_convexe.step"
    if not step.exists():
        raise FileNotFoundError(
            f"{step} absent : lancer d'abord python tools/make_corpus.py")

    out = {}
    t0 = time.perf_counter()
    st = BenchState()
    st.load_step(step)
    st.set_default_tool("ballnose")
    out["import_step_s"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    setup = st.build_setup()
    obst = st.obstacle_field()
    out["champ_obstacles_s"] = time.perf_counter() - t0
    out["n_obstacles"] = len(obst)

    t0 = time.perf_counter()
    shared = brep.sample_surface(st.part_shape, spacing=0.2)
    out["echantillonnage_surface_s"] = time.perf_counter() - t0
    out["n_echantillons"] = len(shared.points)

    t0 = time.perf_counter()
    passes = []
    for g in group_faces_by_normal(st.part_shape, tol_deg=20.0):
        fp = generate_finishing_passes(st.part_shape, g, st.tool,
                                       scallop_mm=0.01, samples=shared)
        if fp is not None and fp.n_points:
            passes.append((g, fp))
    out["generation_passes_s"] = time.perf_counter() - t0
    out["n_points_gamme"] = sum(f.n_points for _, f in passes)

    cfg = AccessibilityConfig(subdivisions=3, max_lead_deg=45.0,
                              cutting_depth=0.0)
    solver = AccessibilitySolver(st.tool, setup.machine, obst, cfg,
                                 mount_offset_mm=setup.mount_offset)
    passes.sort(key=lambda x: -x[1].n_points)
    g, fp = [p for p in passes if p[1].n_points == 3213][0]
    pts, nrm = fp.points, fp.normals

    # exploration : le cout de DECOUVRIR
    t0 = time.perf_counter()
    n = 8
    inter = None
    for k in np.linspace(0, len(pts) - 1, n).astype(int):
        m = solver.solve_point(pts[k], nrm[k])
        if m.accessible:
            f = m.feasible_mask_full()
            inter = f if inter is None else (inter & f)
    out["solve_point_ms_par_point"] = (time.perf_counter() - t0) / n * 1000

    # verification : le cout de CONCLURE
    if inter is None or not inter.any():
        out["verify_ms_par_point"] = None
    else:
        d = solver.grid.directions[np.flatnonzero(inter)[0]]
        t0 = time.perf_counter()
        solver.verify_direction(pts[:1500], nrm[:1500], d)
        out["verify_ms_par_point"] = (time.perf_counter() - t0) / 1500 * 1000

    t0 = time.perf_counter()
    v = decide_indexed_pass(solver, pts, nrm, n_probe=24, max_candidates=2)
    out["verdict_passe_3213_s"] = time.perf_counter() - t0
    out["verdict"] = v.verdict
    out["pic_memoire_mo"] = resource.getrusage(
        resource.RUSAGE_SELF).ru_maxrss / 1024.0
    return out


def afficher(mesure: dict, ref: dict | None) -> None:
    print("=" * 74)
    print("BANC DE PERFORMANCE — " + mesure["plateforme"]["machine"])
    print("=" * 74)
    for k, v in mesure["plateforme"].items():
        print(f"  {k:12s} {v}")
    if ref:
        print(f"\n  reference    {ref['plateforme'].get('machine')} / "
              f"{ref['plateforme'].get('cpu', '?')}")

    for titre, cle in (("MICRO-NOYAUX (tailles de la boucle chaude)", "micro"),
                       ("CHAINE REELLE (dome C10)", "macro")):
        print(f"\n{titre}")
        for k, v in mesure[cle].items():
            if v is None:
                print(f"  {k:34s} {'non mesure':>12s}")
                continue
            if isinstance(v, str):
                print(f"  {k:34s} {v:>12s}")
                continue
            ligne = f"  {k:34s} {v:12.3f}"
            if ref and isinstance(ref.get(cle, {}).get(k), (int, float)):
                r = ref[cle][k]
                if r:
                    rap = v / r
                    sens = "plus lent" if "Go_par_s" not in k else "du debit"
                    if "Go_par_s" in k:
                        rap = v / r
                    ligne += f"   x{rap:6.2f} {sens}"
            print(ligne)
    print("=" * 74)
    if ref:
        print("  Les rapports sont MESURES, pas extrapoles. Un rapport proche")
        print("  de 1 sur le triade memoire et plus grand sur les micro-noyaux")
        print("  confirmerait que le regime est SIMD/appel et non DDR.")
    print("=" * 74)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", default="", help="enregistrer la mesure")
    ap.add_argument("--compare", default="", help="mesure de reference a comparer")
    ap.add_argument("--corpus",
                    default=str(Path(__file__).resolve().parents[1]
                                / "tests" / "corpus" / "step"))
    ap.add_argument("--micro-seulement", action="store_true",
                    help="sauter la chaine reelle (pas besoin du corpus)")
    args = ap.parse_args()

    mesure = {"plateforme": plateforme(), "micro": micro(), "macro": {}}
    if not args.micro_seulement:
        mesure["macro"] = macro(Path(args.corpus))

    ref = None
    if args.compare:
        ref = json.loads(Path(args.compare).read_text(encoding="utf-8"))
    afficher(mesure, ref)

    if args.json:
        Path(args.json).write_text(
            json.dumps(mesure, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nmesure enregistree dans {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
