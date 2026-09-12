"""Vertical slice M9 : du modele machine a la configuration LinuxCNC.

    calibration -> configuration INI/HAL -> depot d'un programme -> refus du cycle

AUCUN mouvement, aucune connexion. LinuxCNC n'est pas installe ici et la
configuration produite n'est donc PAS validee par lui : la commande a lancer sur
la machine de l'utilisateur est affichee a la fin.

Usage :
    python tools/demo_m9_linuxcnc.py [--out DOSSIER] [--calibrer]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xyzac.assembly_calibration import (
    CalibrationRecord,
    calibrate_on_twin,
    record_from_report,
)
from xyzac.linuxcnc_gateway import (
    DepositRefused,
    Target,
    build_config,
    deposit_program,
    start_cycle,
    verification_command,
)
from xyzac.machine_model import MachineGeometry, default_xyzac_kit
from xyzac.machine_model.geometry import AxisLocationError
from xyzac.safety_state_machine import SafetyStateMachine


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out/config-xyzac")
    ap.add_argument("--calibrer", action="store_true",
                    help="calibrer sur le jumeau avant de generer")
    args = ap.parse_args()

    print("=" * 78)
    print("PIPELINE M9 — frontiere LinuxCNC")
    print("=" * 78)

    machine = default_xyzac_kit()
    record = CalibrationRecord(machine_id=machine.machine_id,
                               geometry=MachineGeometry.nominal(machine.machine_id))
    if args.calibrer:
        truth = MachineGeometry(
            machine_id=machine.machine_id, measured=True,
            a_axis=AxisLocationError(offset_mm=[0.10, -0.20, 0.30]),
            c_axis=AxisLocationError(offset_mm=[-0.15, 0.05, 0.0]))
        rep, meas = calibrate_on_twin(machine, truth, probe_noise_mm=0.002)
        record = record_from_report(machine.machine_id, meas, rep)
        print(f"\n[1] Calibration sur le jumeau : "
              f"{record.calibration_hash()[:12]}")
        print(f"    {record.tolerance_statement()}")
    else:
        print("\n[1] Aucune calibration : la configuration sera PROVISOIRE.")
        print("    (relancer avec --calibrer pour voir la difference)")

    cfg = build_config(machine, record if record.geometry.measured else None)
    ecrits = cfg.write(args.out)
    print(f"\n[2] Configuration generee dans {args.out}")
    for nom, p in ecrits.items():
        print(f"    {nom:12s} {p.stat().st_size:6d} octets")
    print("\n    " + cfg.describe().replace("\n", "\n    "))

    print("\n[3] Depot d'un programme")
    gcode = "G21 G90 G94\nG0 X0 Y0 Z10\nM30\n"
    sm = SafetyStateMachine(setup_hash="demo")
    sm.define_setup("demo")
    sm.pass_collision(True, "demo M9")
    sm.pass_kinematics(True)
    sm.pass_simulation(True)
    sm.approve("demo-m9")

    for cible in (Target.SIMULATION, Target.HARDWARE):
        try:
            rec = deposit_program(gcode, Path(args.out) / "nc_files",
                                  target=cible, safety=sm, setup_hash="demo",
                                  calibration=record,
                                  journal=Path(args.out) / "depots.tsv")
            print(f"    {cible.value:12s} ACCEPTE")
            print("      " + rec.describe().replace("\n", "\n      "))
        except DepositRefused as exc:
            print(f"    {cible.value:12s} REFUSE — {exc}")

    print("\n[4] Demarrage de cycle")
    try:
        start_cycle()
        print("    ANOMALIE : un cycle a demarre")
        return 1
    except NotImplementedError as exc:
        print(f"    REFUSE par conception — {str(exc)[:150]}")

    print("\n[5] Ce qui valide reellement cette configuration, SUR VOTRE MACHINE")
    print("    " + verification_command(args.out).replace("\n", "\n    "))
    print("\n    Rien de ce qui precede n'a ete valide par LinuxCNC : il n'est")
    print("    pas installable dans l'environnement de developpement.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
