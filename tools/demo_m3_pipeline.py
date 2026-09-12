"""Vertical slice M3 : STEP -> GAMME -> validation -> portes de securite.

Difference avec M2 : il n'y a plus de passe construite a la main. Le
planificateur decide seul quelles indexations employer, le slicer produit les
trajectoires, et chaque operation est validee **couche par couche** contre
l'etat reel de la matiere.

C'est la premiere fois que la chaine va de bout en bout sans intervention :
  import controle -> brut -> gamme -> trajectoires -> validation -> approbation
  -> refus de generer du G-code (le verrou tient, voir ADR-002/ADR-003).

Usage :
    python tools/demo_m3_pipeline.py [ID_CORPUS] [--pitch MM] [--mount-z MM]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xyzac.geometry_core import brep
from xyzac.geometry_core.healing import UnusableShapeError, load_step_checked, require_usable
from xyzac.machine_model import Fixture, FixtureKind, Setup, default_xyzac_kit
from xyzac.postprocessor_linuxcnc import post_process
from xyzac.safety_state_machine import SafetyStateMachine, SafetyViolation
from xyzac.simulation_engine import validate_roughing_progressive
from xyzac.stock_engine import stock_from_part
from xyzac.stock_engine.material import MaterialState
from xyzac.strategy_planner import candidate_directions, evaluate_candidates
from xyzac.subtractive_slicer import simulate_removal, slice_for_direction
from xyzac.tool_model import build_endmill


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("case", nargs="?", default="C02")
    ap.add_argument("--pitch", type=float, default=1.5, help="pas de la grille voxel")
    ap.add_argument("--layer", type=float, default=2.5, help="epaisseur de couche (mm)")
    ap.add_argument("--mount-z", type=float, default=25.0,
                    help="hauteur des cales sous la piece (mm)")
    ap.add_argument("--max-setups", type=int, default=3)
    ap.add_argument("--point-spacing", type=float, default=2.0)
    ap.add_argument("--clearance", type=float, default=0.3)
    args = ap.parse_args()

    step = next(iter(sorted((ROOT / "tests/corpus/step").glob(f"{args.case}_*.step"))), None)
    if step is None:
        print(f"'{args.case}' introuvable. Lance 'python tools/make_corpus.py'.")
        return 2

    print("=" * 78)
    print(f"PIPELINE M3 — {step.name}")
    print("=" * 78)

    # --- 1. import controle -------------------------------------------
    shape, diag, heal = load_step_checked(step)
    print("\n[1] Import\n    " + diag.describe().replace("\n", "\n    "))
    print(f"    {heal.describe()}")
    try:
        require_usable(shape, heal.after or diag)
    except UnusableShapeError as e:
        print(f"\n    REFUS : {e}")
        return 1

    # --- 2. brut, bridage, outil --------------------------------------
    bb = brep.bounding_box(shape)
    stock = stock_from_part(bb, margin_xy=2.0, margin_z_top=2.0, margin_z_bottom=2.0)
    jaw_top = float(stock.lo[2]) + 4.0
    jaws = [
        Fixture(name="mors -X", kind=FixtureKind.VISE,
                lo=[float(stock.lo[0]) - 14, float(stock.lo[1]) - 4, float(stock.lo[2]) - 14],
                hi=[float(stock.lo[0]) + 1, float(stock.hi[1]) + 4, jaw_top], keepout_mm=1.5),
        Fixture(name="mors +X", kind=FixtureKind.VISE,
                lo=[float(stock.hi[0]) - 1, float(stock.lo[1]) - 4, float(stock.lo[2]) - 14],
                hi=[float(stock.hi[0]) + 14, float(stock.hi[1]) + 4, jaw_top], keepout_mm=1.5),
    ]
    tool = build_endmill("EM6", 6.0, 20.0, stickout=45.0, holder_type="ER16", flute_count=3)
    setup = Setup(
        setup_id=f"m3-{args.case}", machine=default_xyzac_kit(),
        part_step_path=str(step), stock=stock, fixtures=jaws, tools=[tool],
        part_to_table_mm=[float(-bb.center[0]), float(-bb.center[1]), args.mount_z],
    )
    fixture_pts = np.vstack([f.surface_samples(2.0)[0] for f in jaws])

    verts, tris, _ = brep.tessellate(shape, deflection=args.pitch * 0.25)
    material = MaterialState.from_setup(stock, verts, tris, pitch=args.pitch)
    # Les bridages sont de la matiere qu'on ne touche pas et qui masque : ils
    # entrent donc dans le masque protege, exactement comme la piece. Sans cela
    # le slicer descend jusqu'au fond du brut, c'est-a-dire dans l'etau.
    n_fix = material.protect_fixtures(setup)
    initial = material.removable().sum() * material.grid.voxel_volume
    print(f"\n[2] Montage\n    {material.describe()}")
    print(f"    a enlever : {initial:.0f} mm3 ; cales +{args.mount_z} mm ; "
          f"{n_fix} voxels de bridage proteges ; hash {setup.setup_hash()[:12]}")

    # --- 3. gamme (couverture gloutonne) ------------------------------
    cands = evaluate_candidates(candidate_directions(shape, setup), material, setup)
    print(f"\n[3] Indexations candidates ({len(cands)}, filtrees par les courses A/C)")
    for c in cands:
        print(f"    {c.describe()}")

    safety = SafetyStateMachine(setup_hash=setup.setup_hash())
    safety.define_setup(setup.setup_hash())

    reports = []
    pool = [c.direction for c in cands]
    total_removed = 0.0
    t_all = time.perf_counter()

    for step_i in range(args.max_setups):
        ranked = evaluate_candidates(pool, material, setup)
        if not ranked or ranked[0].reachable_mm3 < 50.0:
            break
        best = ranked[0]
        pool = [d for d in pool if not np.allclose(d, best.direction)]

        sl = slice_for_direction(material, best.direction, tool,
                                 layer_thickness=args.layer,
                                 safety_clearance=args.clearance)
        if not sl.layers:
            continue

        print(f"\n[4.{step_i + 1}] Ebauche indexee {best.label} "
              f"(A={best.a_deg:.2f} C={best.c_deg:.2f}) — "
              f"{len(sl.layers)} couches de {args.layer} mm")
        t0 = time.perf_counter()
        rep = validate_roughing_progressive(
            setup, material, sl, tool, point_spacing=args.point_spacing,
            sweep_step_mm=max(args.layer, 3.0), fixture_points=fixture_pts,
            safety_clearance=args.clearance, op_id=f"ebauche-{best.label}")
        print("     " + rep.describe().replace("\n", "\n     "))
        print(f"     [{time.perf_counter() - t0:.0f}s]")
        reports.append(rep)
        total_removed += rep.removed_mm3

    left = material.removable().sum() * material.grid.voxel_volume
    print(f"\n[5] Bilan matiere ({time.perf_counter() - t_all:.0f}s) : "
          f"{total_removed:.0f} mm3 enleves sur {initial:.0f} "
          f"({100 * total_removed / max(initial, 1):.1f} %), {left:.0f} mm3 restants")

    # --- 6. portes de securite ----------------------------------------
    all_ok = bool(reports) and all(r.passed for r in reports)
    safety.pass_collision(all_ok, f"{len(reports)} operation(s)")
    if safety.state.value != "fault":
        safety.pass_kinematics(all_ok, "indexations dans les courses")
    if safety.state.value != "fault":
        safety.pass_simulation(all_ok, f"{sum(r.layers_ok for r in reports)} couches validees")
    if safety.state.value == "simulated":
        safety.approve("operateur-demo")

    print(f"\n[6] Portes de securite -> {safety.state.value}")
    print("    " + safety.audit_trail().replace("\n", "\n    "))

    print("\n[7] Tentative de generation de G-code :")
    try:
        post_process(plan=None, safety=safety, current_setup_hash=setup.setup_hash())
        print("    !!! du G-code est sorti — cela ne doit pas arriver")
    except (SafetyViolation, NotImplementedError) as e:
        print(f"    REFUS ({type(e).__name__}) : {str(e).splitlines()[0]}")

    print("\n" + "=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
