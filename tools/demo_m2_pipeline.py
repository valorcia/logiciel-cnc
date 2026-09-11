"""Vertical slice M2 : STEP -> ... -> VALIDATION -> portes de securite.

Difference avec la demo M1 : la trajectoire est desormais **validee**, et le
resultat traverse reellement les portes de securite. La porte de simulation ne
peut plus etre franchie sans qu'une validation ait eu lieu.

Le script se termine en demontrant que le post-processeur REFUSE de generer du
G-code — soit parce que la validation a echoue, soit, si tout passe, parce que
le verrou du jalon reste actif.

Usage :
    python tools/demo_m2_pipeline.py [ID_CORPUS] [--face N] [--mount-z MM]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xyzac.accessibility_solver import AccessibilityConfig, AccessibilitySolver
from xyzac.geometry_core import brep
from xyzac.kinematics_solver import KinematicsSolver
from xyzac.machine_model import Fixture, FixtureKind, Setup, default_xyzac_kit
from xyzac.orientation_solver import OrientationSolver
from xyzac.postprocessor_linuxcnc import post_process
from xyzac.safety_state_machine import SafetyStateMachine, SafetyViolation
from xyzac.simulation_engine import (
    TrajectoryValidator,
    build_scene,
    make_pose_verifier,
    run_simulation_gate,
)
from xyzac.stock_engine import stock_from_part
from xyzac.tool_model import build_ballnose, build_endmill


def pick_reachable_face(shape, machine, samples, face=None) -> int:
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
            continue
        sols = [b for b in kin.ik_branches(n / nn) if b.within_limits and not b.singular]
        if not sols:
            continue
        score = abs(sols[0].a_deg) + 0.02 * f.area
        if score > best_score:
            best, best_score = f.index, score
    if best is None:
        raise SystemExit("aucune face atteignable dans les courses A/C avec ce bridage")
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("case", nargs="?", default="C08")
    ap.add_argument("--face", type=int, default=None)
    ap.add_argument("--spacing", type=float, default=2.0)
    ap.add_argument("--path-points", type=int, default=20)
    ap.add_argument("--stickout", type=float, default=45.0)
    ap.add_argument("--ballnose", action="store_true")
    ap.add_argument("--mount-z", type=float, default=40.0,
                    help="hauteur de l'origine piece au-dessus du plateau C (mm)")
    ap.add_argument("--material", default="intact", choices=["intact", "finished"],
                    help="etat du brut : intact (conservatif) ou finished (ebauche faite)")
    ap.add_argument("--pitch", type=float, default=1.0, help="pas de la grille voxel (mm)")
    ap.add_argument("--no-refine", action="store_true")
    ap.add_argument("--sweep-step", type=float, default=1.0,
                    help="deplacement max tolere entre deux poses interpolees (mm)")
    args = ap.parse_args()

    step_path = next(iter(sorted((ROOT / "tests/corpus/step").glob(f"{args.case}_*.step"))), None)
    if step_path is None:
        print(f"'{args.case}' introuvable. Lance 'python tools/make_corpus.py'.")
        return 2

    print("=" * 78)
    print(f"PIPELINE M2 — {step_path.name}")
    print("=" * 78)

    shape = brep.load_step(step_path)
    bb = brep.bounding_box(shape)
    stock = stock_from_part(bb, margin_xy=2.0, margin_z_top=2.0, margin_z_bottom=6.0)
    jaw_top = float(stock.lo[2]) + 5.0
    jaws = [
        Fixture(name="mors -X", kind=FixtureKind.VISE,
                lo=[float(stock.lo[0]) - 16, float(stock.lo[1]) - 4, float(stock.lo[2]) - 12],
                hi=[float(stock.lo[0]) + 1, float(stock.hi[1]) + 4, jaw_top], keepout_mm=1.5),
        Fixture(name="mors +X", kind=FixtureKind.VISE,
                lo=[float(stock.hi[0]) - 1, float(stock.lo[1]) - 4, float(stock.lo[2]) - 12],
                hi=[float(stock.hi[0]) + 16, float(stock.hi[1]) + 4, jaw_top], keepout_mm=1.5),
    ]
    make = build_ballnose if args.ballnose else build_endmill
    tool = make("BN6" if args.ballnose else "EM6", 6.0, 20.0,
                stickout=args.stickout, holder_type="ER16", flute_count=3)

    setup = Setup(
        setup_id=f"m2-{args.case}", machine=default_xyzac_kit(),
        part_step_path=str(step_path), stock=stock, fixtures=jaws, tools=[tool],
        # Montage realiste, et ce n'est pas cosmetique : une piece posee a
        # l'origine du plateau est (a) encastree dans lui, (b) decentree de la
        # moitie de sa taille. Des que le berceau bascule, une piece decentree
        # part loin de l'axe A et l'outil percute le berceau — le solveur le
        # signale a juste titre, mais le defaut est au montage. On centre donc
        # la piece sur le plateau et on la surleve.
        part_to_table_mm=[float(-bb.center[0]), float(-bb.center[1]), args.mount_z],
    )
    scene = build_scene(setup, sample_spacing=args.spacing, stock_spacing=3.0,
                        fixture_spacing=2.0, safety_clearance=0.3,
                        material_state=args.material, material_pitch=args.pitch)
    print(f"\n{scene.describe()}")
    print(f"  montage    : origine piece a +{args.mount_z} mm au-dessus du plateau C")

    fidx = pick_reachable_face(shape, setup.machine, scene.part_samples, args.face)
    pts, nrm = scene.face_points(fidx, spacing=args.spacing)
    order = brep.order_points_as_path(pts)
    sel = order[np.linspace(0, len(order) - 1, min(args.path_points, len(order))).astype(int)]
    cc_pts, cc_nrm = pts[sel], nrm[sel]
    print(f"\nFace #{fidx} : {len(pts)} points -> passe de {len(cc_pts)} points de contact")

    cfg = AccessibilityConfig(subdivisions=3, max_lead_deg=45.0, cutting_depth=1.0)
    solver = AccessibilitySolver(tool, setup.machine, scene.obstacles, cfg,
                                 mount_offset_mm=setup.mount_offset)
    t0 = time.perf_counter()
    amaps = solver.solve_points(cc_pts, cc_nrm)
    dt = time.perf_counter() - t0
    print(f"\n[1] Accessibilite : {dt:.2f} s ({dt / len(amaps) * 1000:.0f} ms/point) — "
          f"{sum(m.accessible for m in amaps)}/{len(amaps)} points accessibles")
    print(f"    etages du point median : {amaps[len(amaps) // 2].stage_counts}")

    # Verification exacte partagee par la segmentation 3+2 et le raffinement :
    # une orientation PROPOSEE est toujours re-testee, contre la piece ET
    # contre la machine.
    verify = make_pose_verifier(setup, scene.obstacles, tool, cc_pts, cc_nrm,
                                cutting_depth=1.0, cutting_allowance=solver._cut_allow)

    osolver = OrientationSolver(setup.machine, tool)
    plan = osolver.solve(amaps, path_points=cc_pts, verify=verify)
    print(f"\n[2] Orientation : {'REALISABLE' if plan.feasible else 'INCOMPLET'}, "
          f"couverture 3+2 {plan.indexed_fraction * 100:.0f} %")
    for seg in plan.segments[:4]:
        loc = f" A={seg.a_deg:7.2f} C={seg.c_deg:8.2f}" if seg.mode == "3+2" else ""
        print(f"    [{seg.start:4d}..{seg.end:4d}] {seg.mode:10s}{loc}  {seg.reason}")

    if plan.feasible and not args.no_refine:
        t0 = time.perf_counter()
        refined = osolver.refine(plan, amaps, verify, half_angle_deg=5.0, iterations=1)
        ta, tc = plan.rotary_travel()
        ra, rc = refined.rotary_travel()
        print(f"\n[2b] Raffinement continu en {time.perf_counter() - t0:.2f} s : "
              f"marge min {plan.margin.min():.3f} -> {refined.margin.min():.3f} mm, "
              f"course A+C {ta + tc:.1f} -> {ra + rc:.1f} deg")
        plan = refined

    validator = TrajectoryValidator(
        setup, scene.obstacles, tool, max_sweep_step_mm=args.sweep_step,
        cutting_allowance=solver._cut_allow, cutting_depth=1.0)

    safety = SafetyStateMachine(setup_hash=setup.setup_hash())
    safety.define_setup(setup.setup_hash())

    t0 = time.perf_counter()
    report = validator.validate(plan, cc_pts, cc_nrm)
    print(f"\n[3] Validation en {time.perf_counter() - t0:.2f} s")
    print("    " + report.summary().replace("\n", "\n    "))

    # Les portes sont franchies avec le VERDICT REEL, jamais avec True en dur.
    safety.pass_collision(not [i for i in report.errors if i.check == "poses"],
                          "V1 poses")
    if safety.state.value != "fault":
        safety.pass_kinematics(not [i for i in report.errors if i.check == "cinematique"],
                               "V2 cinematique")
    if safety.state.value != "fault":
        run_simulation_gate(validator, plan, cc_pts, cc_nrm, safety)

    print(f"\n[4] Portes de securite -> etat : {safety.state.value}")
    print("    " + safety.audit_trail().replace("\n", "\n    "))

    # Approbation par un operateur nomme, si et seulement si la simulation est passee.
    if safety.state.value == "simulated":
        safety.approve("operateur-demo")
        print(f"    approbation enregistree -> etat : {safety.state.value}")

    print("\n[5] Tentative de generation de G-code :")
    try:
        post_process(plan=plan, safety=safety, current_setup_hash=setup.setup_hash())
        print("    !!! du G-code a ete genere — cela ne devrait pas arriver a ce jalon")
    except (SafetyViolation, NotImplementedError) as e:
        print(f"    REFUS ({type(e).__name__}) : {str(e).splitlines()[0]}")

    print("\n" + "=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
