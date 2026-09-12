"""Vertical slice M7 : injecter une erreur -> calibrer -> compenser -> poster.

Montre la chaine que le jalon M7 ajoute, et ce qu'elle refuse encore :

  erreur injectee -> palpage simule -> dossier de calibration -> compensation
  -> G-code DANS UN FICHIER -> relecture et verification -> envoi REFUSE

La machine est fausse volontairement : on lui injecte des defauts geometriques
connus, et on verifie que la procedure les retrouve. C'est le seul dispositif de
verification disponible tant qu'aucune machine n'existe.

Usage :
    python tools/demo_m7_calibration.py [ID_CORPUS] [--noise UM] [--out FICHIER]
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xyzac.assembly_calibration import calibrate_on_twin, record_from_report
from xyzac.geometry_core import brep
from xyzac.geometry_core.types import angle_between, normalize
from xyzac.kinematics_solver.compensation import CompensatedMove, realised_pose
from xyzac.machine_model import Setup, default_xyzac_kit
from xyzac.machine_model.geometry import AxisLocationError, MachineGeometry, _rodrigues
from xyzac.postprocessor_linuxcnc import parse_poses, post_process
from xyzac.safety_state_machine import SafetyStateMachine
from xyzac.stock_engine import stock_from_part
from xyzac.strategy_planner.interfaces import Kinematic, Operation, ProcessPlan, Toolpath
from xyzac.tool_model import build_ballnose


def _tilt(u, axis, deg):
    return _rodrigues(axis, math.radians(deg)) @ np.asarray(u, dtype=float)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("case", nargs="?", default="C10")
    ap.add_argument("--noise", type=float, default=3.0, help="bruit de palpage (um)")
    ap.add_argument("--points", type=int, default=40)
    ap.add_argument("--out", default="", help="ecrire le G-code dans ce fichier")
    args = ap.parse_args()

    step = next(iter(sorted((ROOT / "tests/corpus/step").glob(f"{args.case}_*.step"))), None)
    if step is None:
        print(f"'{args.case}' introuvable. Lance 'python tools/make_corpus.py'.")
        return 2

    print("=" * 78)
    print(f"PIPELINE M7 — {step.name}")
    print("=" * 78)

    machine = default_xyzac_kit()

    # --- 1. la machine REELLE, avec ses defauts -----------------------
    truth = MachineGeometry(
        machine_id=machine.machine_id, measured=True,
        a_axis=AxisLocationError(offset_mm=[0.10, -0.20, 0.30],
                                 direction=list(_tilt([1, 0, 0], [0, 0, 1], 0.20))),
        c_axis=AxisLocationError(offset_mm=[-0.15, 0.05, 0.0],
                                 direction=list(_tilt([0, 0, 1], [1, 0, 0], 0.15))))
    print("\n[1] Machine reelle simulee (defauts INJECTES, jamais lus par la procedure)")
    print(f"    axe A incline de 0,200 deg, pivot decale de "
          f"{np.linalg.norm(truth.a_axis.d):.3f} mm")
    print(f"    axe C incline de 0,150 deg, pivot decale de "
          f"{np.linalg.norm(truth.c_axis.d):.3f} mm")

    print("\n    Etat du modele AVANT calibration :")
    print("    " + MachineGeometry.nominal(machine.machine_id).describe())

    # --- 2. calibration sur le jumeau ---------------------------------
    report, measured = calibrate_on_twin(
        machine, truth, probe_noise_mm=args.noise * 1e-3,
        true_backlash={"X": 0.02, "Y": 0.03, "Z": 0.015, "A": 0.0, "C": 0.0},
        true_homing_repeatability_mm=0.008)
    record = record_from_report(machine.machine_id, measured, report)

    print(f"\n[2] Calibration (palpeur a {args.noise:.1f} um)")
    for r in report.results:
        mark = "OK " if r.passed else "NON"
        line = f"    [{mark}] {r.step.name:20s}"
        print(line + (f" {r.detail[:90]}" if r.passed else f" {r.remedy}"))

    ea = math.degrees(angle_between(measured.a_axis.u, truth.a_axis.u))
    ec = math.degrees(angle_between(measured.c_axis.u, truth.c_axis.u))
    print(f"\n    Erreur RETROUVEE : axe A a {ea:.5f} deg de la verite "
          f"(incertitude annoncee {measured.a_axis.direction_uncertainty_deg:.5f}), "
          f"axe C a {ec:.5f} deg (annoncee "
          f"{measured.c_axis.direction_uncertainty_deg:.5f})")
    print(f"    {record.tolerance_statement()}")

    # --- 3. montage lie au dossier de calibration ---------------------
    shape = brep.load_step(step)
    bb = brep.bounding_box(shape)
    tool = build_ballnose("BN6", 6.0, 20.0, stickout=45.0, holder_type="ER16")
    stock = stock_from_part(bb, margin_xy=2.0, margin_z_top=2.0, margin_z_bottom=2.0)
    setup = Setup(setup_id=f"m7-{args.case}", machine=machine,
                  part_step_path=str(step), stock=stock, tools=[tool],
                  part_to_table_mm=[float(-bb.center[0]), float(-bb.center[1]), 25.0],
                  calibration_hash=record.calibration_hash())
    h = setup.setup_hash()
    print(f"\n[3] Montage {h[:12]} lie a la calibration "
          f"{record.calibration_hash()[:12]}")
    print("    une recalibration change ce hash, donc invalide l'approbation")

    samp = brep.sample_surface(shape, spacing=3.0)
    pts, nrm = samp.points[:args.points], samp.normals[:args.points]
    plan = ProcessPlan(plan_id=f"m7-{args.case}", setup=setup, operations=[Operation(
        op_id="finition", kinematic=Kinematic.MILLING_5AXIS, tool=tool,
        toolpath=Toolpath(points=pts, normals=nrm, label="demo"),
        spindle_rpm=12000.0, feed_mm_min=250.0)])

    safety = SafetyStateMachine(setup_hash=h)
    safety.define_setup(h)
    safety.pass_collision(True, "demo M7 : portes franchies pour la demonstration")
    safety.pass_kinematics(True)
    safety.pass_simulation(True)
    safety.approve("demo-m7")

    # --- 4. emission ---------------------------------------------------
    gcode, emit = post_process(plan, safety, h, record, feed_mm_min=250.0)
    print(f"\n[4] Emission\n    {emit.describe()}")
    print("\n    En-tete du fichier :")
    for line in gcode.splitlines():
        if not line.startswith("("):
            break
        print("      " + line)

    # --- 5. aller-retour -----------------------------------------------
    poses = parse_poses(gcode)
    wo = np.asarray(setup.work_offset.origin_mm, dtype=float)
    mount = np.asarray(setup.mount_offset, dtype=float)

    def worst_against(geom):
        wp = wd = 0.0
        for (p, n), q in zip(zip(pts, nrm), poses):
            mv = CompensatedMove(q["X"], q["Y"], q["Z"], q["A"], q["C"],
                                 0.0, 0.0, True, 0)
            gp, gd = realised_pose(machine, geom, mv, work_offset=wo)
            wp = max(wp, float(np.linalg.norm(gp - (p + mount))))
            wd = max(wd, math.degrees(angle_between(gd, normalize(n))))
        return wp, wd

    p_meas, d_meas = worst_against(measured)
    p_true, d_true = worst_against(truth)
    print(f"\n[5] Aller-retour ({len(poses)} poses relues)")
    print(f"    contre la geometrie MESUREE : {p_meas * 1000:8.3f} um, "
          f"{d_meas:.6f} deg   (fidelite numerique + quantification du format)")
    print(f"    contre la geometrie VRAIE   : {p_true * 1000:8.3f} um, "
          f"{d_true:.6f} deg   (erreur residuelle de calibration)")
    print(f"    budget annonce a 100 mm     : "
          f"{record.uncertainty_at_100mm_mm * 1000:8.1f} um   "
          f"-> {'MAJORE' if p_true <= record.uncertainty_at_100mm_mm else 'NE MAJORE PAS'}")

    if args.out:
        Path(args.out).write_text(gcode, encoding="utf-8")
        print(f"\n    G-code ecrit dans {args.out}")

    # --- 6. ce qui reste refuse ----------------------------------------
    print("\n[6] Ce qui reste refuse")
    from xyzac.linuxcnc_gateway import LinuxCncGateway
    try:
        LinuxCncGateway().connect()
        print("    ANOMALIE : la passerelle a accepte de se connecter")
        return 1
    except NotImplementedError as e:
        print(f"    envoi a LinuxCNC : REFUSE — {str(e)[:120]}")
    print(f"    qualification    : {'oui' if record.qualified else 'NON'} "
          f"({len(record.steps_blocking)} etapes exigent la machine)")
    print("\n    +-0,02 mm reste un objectif de qualification physique.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
