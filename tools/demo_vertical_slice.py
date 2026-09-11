"""Vertical slice M1 : STEP -> scene -> accessibilite -> orientation -> images.

Ce script est la demonstration du jalon. Il ne genere AUCUNE commande machine,
et n'importe aucun module de la chaine d'execution.

Enchainement :
  1. charge une geometrie du corpus ;
  2. derive un brut et pose un bridage ;
  3. monte un outil COMPLET (bec -> nez de broche) ;
  4. calcule le champ d'accessibilite sur une face ;
  5. optimise la sequence A/C sur une passe ;
  6. produit les visualisations.

Usage :
    python tools/demo_vertical_slice.py [ID_CORPUS] [--face N] [--spacing MM]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xyzac.accessibility_solver import AccessibilityConfig, AccessibilitySolver, tcp_from_contact
from xyzac.geometry_core import brep
from xyzac.kinematics_solver import KinematicsSolver
from xyzac.machine_model import Fixture, FixtureKind, Setup, default_xyzac_kit
from xyzac.orientation_solver import OrientationSolver, OrientationWeights
from xyzac.simulation_engine import build_scene
from xyzac.stock_engine import stock_from_part
from xyzac.tool_model import build_ballnose, build_endmill
from xyzac.ui import render


def pick_face(shape, machine, samples, face: int | None = None) -> int:
    """Choisit une face de travail REELLEMENT atteignable par la cinematique.

    Choisir "la plus grande face" est un piege : sur une piece posee a plat,
    c'est la face du dessous, qui demanderait A = 180 deg. Le berceau ne
    l'atteint pas, et la demonstration porterait alors sur un refus trivial.

    On classe donc les faces par leur interet pour un essai 5 axes :
    atteignable par au moins une branche (A, C), et exigeant le plus de
    basculement — c'est la que l'orientation solver a quelque chose a dire.
    """
    if face is not None:
        return face

    kin = KinematicsSolver(machine)
    best, best_score = None, -np.inf
    for f in brep.face_info(shape):
        m = samples.face_ids == f.index
        if not np.any(m):
            continue
        n = samples.normals[m].mean(axis=0)
        nn = float(np.linalg.norm(n))
        if nn < 1e-6:
            continue  # face trop courbe pour une normale moyenne : hors portee du choix auto
        n = n / nn
        sols = [b for b in kin.ik_branches(n) if b.within_limits and not b.singular]
        if not sols:
            continue
        tilt = abs(sols[0].a_deg)
        score = tilt + 0.02 * f.area   # le basculement prime, l'aire departage
        if score > best_score:
            best, best_score = f.index, score

    if best is None:
        raise SystemExit(
            "Aucune face de cette piece n'est atteignable dans les courses A/C "
            "de la machine avec ce bridage. C'est un resultat valide : il faut "
            "rebrider ou reorienter la piece."
        )
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("case", nargs="?", default="C06")
    ap.add_argument("--face", type=int, default=None)
    ap.add_argument("--spacing", type=float, default=2.0)
    ap.add_argument("--path-points", type=int, default=28)
    ap.add_argument("--stickout", type=float, default=45.0)
    ap.add_argument("--holder", default="ER16")
    ap.add_argument("--ballnose", action="store_true",
                    help="fraise hemispherique (necessaire pour incliner sur une face plane)")
    ap.add_argument("--subdiv", type=int, default=3)
    ap.add_argument("--out", default="out")
    args = ap.parse_args()

    corpus = ROOT / "tests/corpus/step"
    matches = sorted(corpus.glob(f"{args.case}_*.step"))
    if not matches:
        print(f"Geometrie '{args.case}' introuvable. Lance d'abord "
              f"'python tools/make_corpus.py'.")
        return 2
    step_path = matches[0]
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    print(f"VERTICAL SLICE — {step_path.name}")
    print("=" * 78)

    # --- 1..3 : setup -------------------------------------------------
    shape = brep.load_step(step_path)
    bb = brep.bounding_box(shape)
    stock = stock_from_part(bb, margin_xy=2.0, margin_z_top=2.0, margin_z_bottom=6.0)

    # Bridage : etau a DEUX mors pincant la base du brut sur X. Un pave
    # enveloppant toute l'empreinte serait plus simple a ecrire, mais il
    # interdirait des orientations qu'un vrai etau laisse libres — et le
    # solveur conclurait a une inaccessibilite qui n'existe pas sur la machine.
    jaw_h = float(stock.lo[2]) + 5.0
    jaws = [
        Fixture(name="mors -X", kind=FixtureKind.VISE,
                lo=[float(stock.lo[0]) - 16.0, float(stock.lo[1]) - 4.0,
                    float(stock.lo[2]) - 12.0],
                hi=[float(stock.lo[0]) + 1.0, float(stock.hi[1]) + 4.0, jaw_h],
                keepout_mm=1.5),
        Fixture(name="mors +X", kind=FixtureKind.VISE,
                lo=[float(stock.hi[0]) - 1.0, float(stock.lo[1]) - 4.0,
                    float(stock.lo[2]) - 12.0],
                hi=[float(stock.hi[0]) + 16.0, float(stock.hi[1]) + 4.0, jaw_h],
                keepout_mm=1.5),
    ]

    make = build_ballnose if args.ballnose else build_endmill
    tool = make("BN6" if args.ballnose else "EM6", 6.0, 20.0, stickout=args.stickout,
                holder_type=args.holder, flute_count=3)

    setup = Setup(setup_id=f"demo-{args.case}", machine=default_xyzac_kit(),
                  part_step_path=str(step_path), stock=stock,
                  fixtures=jaws, tools=[tool])

    t0 = time.perf_counter()
    scene = build_scene(setup, sample_spacing=args.spacing, stock_spacing=3.0,
                        fixture_spacing=2.0, safety_clearance=0.3)
    print(f"\n{scene.describe()}")
    print(f"  (scene construite en {time.perf_counter() - t0:.2f} s)")
    print(f"\n{tool.describe()}")

    # --- 4 : accessibilite --------------------------------------------
    fidx = pick_face(shape, setup.machine, scene.part_samples, face=args.face)
    finfo = [f for f in brep.face_info(shape) if f.index == fidx][0]
    pts, nrm = scene.face_points(fidx, spacing=args.spacing)
    order = brep.order_points_as_path(pts)
    sel = order[np.linspace(0, len(order) - 1, min(args.path_points, len(order))).astype(int)]
    cc_pts, cc_nrm = pts[sel], nrm[sel]

    print(f"\nFace de travail : #{fidx} ({finfo.surface_type}, {finfo.area:.0f} mm2)")
    print(f"  {len(pts)} points echantillonnes -> passe de {len(cc_pts)} points de contact")

    cfg = AccessibilityConfig(subdivisions=args.subdiv, max_lead_deg=45.0,
                              safety_clearance=0.0, cutting_depth=1.0)
    solver = AccessibilitySolver(tool, setup.machine, scene.obstacles, cfg)

    t0 = time.perf_counter()
    amaps = solver.solve_points(cc_pts, cc_nrm)
    dt = time.perf_counter() - t0
    print(f"\nAccessibilite : {len(amaps)} points x {len(solver.grid)} directions "
          f"en {dt:.2f} s ({dt / len(amaps) * 1000:.0f} ms/point)")
    print("\n" + amaps[len(amaps) // 2].summary())

    n_acc = sum(1 for m in amaps if m.accessible)
    print(f"\n  points accessibles : {n_acc}/{len(amaps)}")
    if n_acc < len(amaps):
        print("  ATTENTION : certains points n'ont AUCUNE orientation admissible.")
        for m in amaps:
            if not m.accessible:
                r = m.dominant_reason()
                print(f"    {np.round(m.point, 1)} -> {r.name if r else '?'}")
                break

    # --- 5 : orientation ----------------------------------------------
    osolver = OrientationSolver(setup.machine, tool, OrientationWeights(),
                                candidates_per_point=20, preferred_lead_deg=8.0)
    t0 = time.perf_counter()
    plan = osolver.solve(amaps, path_points=cc_pts)
    print(f"\nOrientation (Viterbi) en {time.perf_counter() - t0:.2f} s")
    print("\n" + plan.summary())

    # --- 6 : rendus ----------------------------------------------------
    print("\nRendus :")
    mid = len(amaps) // 2
    amid = amaps[mid]
    b = amid.best()
    axis = amid.directions[b] if b is not None else amid.normal
    tcp = tcp_from_contact(amid.point, amid.normal, axis, tool)

    for p in [
        render.render_tool_profile(tool, out / f"{args.case}_outil.png"),
        render.render_scene(scene, tcp=tcp, axis=axis,
                            out_path=out / f"{args.case}_scene.png",
                            title=f"{step_path.stem} — digital twin + outil complet "
                                  f"(A={amid.a_deg[b]:.1f} C={amid.c_deg[b]:.1f})"
                                  if b is not None else step_path.stem),
        render.render_orientation_sphere(
            amid, out / f"{args.case}_orientations.png",
            title=f"{step_path.stem} — face #{fidx}, point {mid}/{len(amaps)} : "
                  f"{amid.n_feasible}/{len(amid.directions)} directions admissibles"),
        render.render_ac_sequence(plan, out / f"{args.case}_sequence_ac.png"),
    ]:
        print(f"  {p}")

    print("\n" + "=" * 78)
    print("RAPPEL : aucun G-code n'a ete produit. Les portes de securite "
          "(collision/cinematique/\n         simulation/machine d'etat) ne sont pas "
          "encore implementees — voir ADR-001 §6.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
