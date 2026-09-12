"""Emission du G-code LinuxCNC, DANS UN FICHIER et derriere les portes.

Etat du verrou, revu a ce jalon. Il avait deux moities :

  - **logicielle** : il n'existait ni emetteur, ni modele de calibration auquel
    une approbation puisse se lier. Les parametres cinematiques etaient
    provisoires, et generer depuis un modele provisoire produit un programme
    geometriquement coherent et physiquement faux. **Cette moitie est levee au
    jalon M7** : ``assembly_calibration`` mesure la geometrie, la compensation
    la consomme, et un dossier de calibration entre dans le hash du setup.
  - **physique** : la machine n'est ni construite ni qualifiee. **Inchangee.**

D'ou la separation que ce module impose, et qui est celle des ateliers :

  - **poster un programme** exige des portes franchies et une geometrie
    MESUREE. Pas une machine qualifiee — on poste avant de qualifier.
  - **envoyer a la machine** exige tout, piece d'epreuve comprise. C'est
    ``linuxcnc_gateway``, et il reste verrouille.

Ce que le fichier produit n'autorise donc pas : il n'autorise aucune tolerance.
L'en-tete porte l'enonce de ``CalibrationRecord.tolerance_statement`` mot pour
mot, parce que c'est le seul endroit du projet ou une precision peut etre
enoncee, et parce qu'un operateur qui lit le fichier doit tomber dessus avant
la premiere ligne de mouvement.

Avances et vitesses de broche ne sont PAS qualifiees (``recipe_profiles`` est
toujours une ebauche). Elles sortent avec une valeur prudente et le dire est
la seule chose honnete a faire.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import numpy as np

from ..assembly_calibration.record import CalibrationRecord
from ..geometry_core.types import normalize
from ..kinematics_solver.compensation import compensate_pose
from ..kinematics_solver.solver import KinematicsSolver
from ..safety_state_machine.machine import SafetyStateMachine
from ..strategy_planner.interfaces import Kinematic, ProcessPlan


@dataclass
class EmitReport:
    """Ce que l'emission a produit, et ce qu'elle n'a pas pu compenser."""

    n_lines: int = 0
    n_points: int = 0
    n_not_converged: int = 0
    worst_orientation_residual_deg: float = 0.0
    worst_position_residual_mm: float = 0.0
    skipped: list[str] = field(default_factory=list)

    def describe(self) -> str:
        s = (f"{self.n_points} poses emises sur {self.n_lines} lignes ; "
             f"residu d'orientation max {self.worst_orientation_residual_deg:.6f} deg, "
             f"residu de position max {self.worst_position_residual_mm:.2e} mm")
        if self.n_not_converged:
            s += (f" ; {self.n_not_converged} poses dont la re-resolution n'a pas "
                  "atteint sa tolerance (voir compensation.solve_real_orientation)")
        for k in self.skipped:
            s += f"\n  ecarte : {k}"
        return s


def _fmt(v: float) -> str:
    return f"{v:.4f}".rstrip("0").rstrip(".") or "0"


def post_process(
    plan: ProcessPlan,
    safety: SafetyStateMachine,
    current_setup_hash: str,
    calibration: CalibrationRecord,
    *,
    feed_mm_min: float = 300.0,
) -> tuple[str, EmitReport]:
    """Genere le G-code LinuxCNC d'une gamme approuvee, compense.

    L'ordre des verifications n'est pas indifferent : la porte de securite
    passe AVANT de regarder le plan, et le dossier de calibration avant de
    calculer quoi que ce soit. Si l'etat n'autorise pas la generation, rien
    d'autre n'a de sens ; si la geometrie n'est pas mesuree, tout calcul
    ulterieur serait faux avec elegance.
    """
    safety.require_postprocess(current_setup_hash)

    if not calibration.geometry.measured:
        raise RuntimeError(
            "generation refusee : geometrie machine NON MESUREE. Les pivots A et "
            "C, l'equerrage et les jeux sont provisoires, et sur une cinematique "
            "table/table l'erreur de pivot se propage directement a la piece. "
            "Executer assembly_calibration.calibrate_on_twin (ou la sequence "
            "reelle) avant de poster.")
    if not calibration.geometry_complete:
        raise RuntimeError(
            "generation refusee : calibration geometrique incomplete. Etapes "
            f"bloquantes : {', '.join(calibration.steps_blocking) or 'inconnues'}.")

    declared = plan.setup.calibration_hash
    if declared and declared != calibration.calibration_hash():
        raise RuntimeError(
            "generation refusee : le dossier de calibration fourni n'est pas "
            f"celui sous lequel le montage a ete approuve (setup declare "
            f"{declared[:12]}, fourni {calibration.calibration_hash()[:12]}). "
            "Approuver sous une calibration et poster sous une autre annule la "
            "signification de l'approbation.")

    if Kinematic.TURNING in plan.kinematics_used() and len(plan.kinematics_used()) > 1:
        raise RuntimeError(
            "gamme hybride fraisage + tournage : le basculement de mode C est une "
            "transition verrouillee (ADR-001 / D8) et l'ordonnancement entre les "
            "deux moteurs n'existe pas. Poster les deux moities separement.")

    setup = plan.setup
    machine = setup.machine
    geom = calibration.geometry
    ks = KinematicsSolver(machine)
    rep = EmitReport()
    mount = np.asarray(setup.mount_offset, dtype=np.float64)
    wo = np.asarray(setup.work_offset.origin_mm, dtype=np.float64)
    if not setup.work_offset.probed:
        # Une origine saisie a la main decale TOUTE la gamme. C'est l'entree la
        # plus couteuse du montage, et la seule que le logiciel ne peut pas
        # deduire — d'ou le commentaire dans l'en-tete plutot qu'un silence.
        rep.skipped.append(
            f"origine '{setup.work_offset.name}' NON PALPEE : saisie a la main, "
            "aucune incertitude associee")

    out: list[str] = []
    w = out.append

    w("(G-code LinuxCNC genere par slicer soustractif XYZAC)")
    w(f"(gamme : {plan.plan_id})")
    w(f"(setup : {current_setup_hash[:16]})")
    w(f"(calibration : {calibration.calibration_hash()[:16]} "
      f"machine {calibration.machine_id})")
    for line in calibration.tolerance_statement().split(". "):
        if line.strip():
            w(f"(TOLERANCE : {line.strip().rstrip('.')})")
    w(f"(budget geometrique a 100 mm des pivots : "
      f"{calibration.uncertainty_at_100mm_mm * 1000:.1f} um, pire cas)")
    w("(AVANCES ET VITESSES NON QUALIFIEES : recipe_profiles est une ebauche)")
    w("(APPROCHE ET DEGAGEMENT NON GENERES : ce module ne connait pas le plan de)")
    w("(degagement des operations. Tout mouvement est en avance travail, et les)")
    w("(liaisons doivent etre ajoutees avant tout usage reel.)")
    w("(Ce fichier n'a pas ete envoye a une machine : linuxcnc_gateway est verrouille)")
    w("G21 G90 G94 (mm, absolu, avance par minute)")
    w("G17")

    for op in plan.operations:
        if op.kinematic is Kinematic.TURNING:
            rep.skipped.append(f"{op.op_id} : tournage, emission non implementee")
            continue
        pts = np.asarray(op.toolpath.points, dtype=np.float64).reshape(-1, 3)
        nrm = np.asarray(op.toolpath.normals, dtype=np.float64).reshape(-1, 3)
        if len(pts) == 0:
            continue

        w("")
        w(f"({op.op_id} — {op.kinematic.value}, outil {op.tool.tool_id})")
        if op.notes:
            w(f"({op.notes})")
        rpm = op.spindle_rpm or machine.spindle_min_rpm
        w(f"S{_fmt(rpm)} M3")
        feed = op.feed_mm_min or feed_mm_min

        for i, (p, n) in enumerate(zip(pts, nrm)):
            d = normalize(n)
            sol = ks.ik_best(d, allow_singular=True)
            if sol is None:
                rep.skipped.append(
                    f"{op.op_id} pose {i} : aucune solution (A, C) dans les courses")
                continue
            mv = compensate_pose(machine, geom, p, d,
                                 a_nominal=sol.a_deg, c_nominal=sol.c_deg,
                                 mount_offset=mount, work_offset=wo)
            rep.n_points += 1
            rep.worst_orientation_residual_deg = max(
                rep.worst_orientation_residual_deg, mv.orientation_residual_deg)
            rep.worst_position_residual_mm = max(
                rep.worst_position_residual_mm, mv.position_residual_mm)
            if not mv.converged:
                rep.n_not_converged += 1

            # JAMAIS de G0 vers un point de CONTACT.
            #
            # Une premiere version emettait le premier point de chaque operation
            # en rapide, ce qui est un rapide dans la piece. Les mouvements
            # d'approche et de degagement ne sont pas generes par ce module (il
            # ne connait pas le plan de degagement de l'operation), donc le
            # defaut prudent est l'avance travail partout, et le manque est
            # ecrit dans l'en-tete plutot que comble par une invention.
            rapid = (op.toolpath.is_rapid is not None
                     and bool(np.asarray(op.toolpath.is_rapid).ravel()[i]))
            code = "G0" if rapid else "G1"
            line = (f"{code} X{_fmt(mv.x_mm)} Y{_fmt(mv.y_mm)} Z{_fmt(mv.z_mm)} "
                    f"A{_fmt(mv.a_deg)} C{_fmt(mv.c_deg)}")
            if code == "G1":
                line += f" F{_fmt(feed)}"
            w(line)

        w("M5")

    w("")
    w("M30")
    rep.n_lines = len(out)
    return "\n".join(out) + "\n", rep


_WORD = re.compile(r"([XYZAC])\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)


def parse_poses(text: str) -> list[dict]:
    """Relit les poses d'un G-code emis. Sert a l'ALLER-RETOUR de verification.

    Un emetteur verifie contre son propre calcul ne verifie rien : on relit donc
    le fichier produit, on rejoue la cinematique REELLE sur les valeurs relues,
    et on compare au point de contact demande. C'est la meme discipline que le
    test differentiel de l'ordre des etages (ADR-006 / D49).

    Volontairement minimal — modal sur les mots absents, comme un controleur —
    et pas un interpreteur de G-code : il ne connait ni sous-programmes, ni
    variables, ni compensation de rayon. Il lit ce que ce module ecrit.
    """
    poses: list[dict] = []
    cur = {"X": None, "Y": None, "Z": None, "A": None, "C": None}
    for raw in text.splitlines():
        line = re.sub(r"\(.*?\)", "", raw).strip()
        if not line or line.startswith("%"):
            continue
        words = _WORD.findall(line)
        if not words:
            continue
        if not re.search(r"\bG0?[01]\b", line, re.IGNORECASE):
            continue
        for letter, val in words:
            cur[letter.upper()] = float(val)
        if any(v is None for v in cur.values()):
            continue
        poses.append(dict(cur))
    return poses
