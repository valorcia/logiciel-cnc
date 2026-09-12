"""Execution des etapes de calibration, et ce qu'aucune simulation ne remplace.

Ce module implemente les etapes dont la METHODE peut etre validee sans machine,
et refuse explicitement les autres. La distinction est la seule chose qui rend
ce jalon honnete, donc elle est portee par une donnee et non par un commentaire :
``CalibrationStep`` a desormais un attribut ``hardware_required``.

Ce qu'on valide sans machine : la mathematique d'une procedure — l'ajustement,
la propagation d'incertitude, la sensibilite au bruit et au nombre de points. On
injecte dans le jumeau une erreur geometrique CONNUE, on simule le palpage, et
on exige que la procedure la retrouve.

Ce qu'on ne valide pas : tout ce qui depend d'un materiel qui n'existe pas. Un
test de cablage, un sens d'axe, une course reelle, une camera, et surtout la
piece d'epreuve usinee puis mesuree. Ces etapes rendent ``passed=False`` avec
leur remede, jamais un succes fabrique.
"""

from __future__ import annotations

import math

import numpy as np

from ..machine_model.geometry import AxisLocationError, MachineGeometry
from ..machine_model.machine import MachineKinematics
from ..probing_service.fitting import fit_axis_from_rotation, fit_plane_normal
from ..probing_service.simulator import DatumSphere, ProbeSimulator
from .interfaces import CalibrationResult, CalibrationStep

#: Etapes qui exigent la machine physique. Aucune simulation ne les remplace, et
#: les declarer simulables serait la fabrication de confiance que tout ce projet
#: cherche a eviter.
HARDWARE_ONLY: frozenset[CalibrationStep] = frozenset({
    CalibrationStep.WIRING_TEST,        # continuite, phases, fins de course
    CalibrationStep.AXIS_DIRECTION,     # exige de VOIR bouger un axe
    CalibrationStep.TRAVEL_LIMITS,      # exige d'aller au bout des courses
    CalibrationStep.CAMERA_CALIBRATION,  # exige une camera
    CalibrationStep.QUALIFICATION_PART,  # exige d'usiner ET de mesurer
})

_REMEDY = {
    CalibrationStep.WIRING_TEST:
        "brancher la machine et executer le test de continuite guide",
    CalibrationStep.AXIS_DIRECTION:
        "commander un deplacement de 10 mm par axe et confirmer le sens observe",
    CalibrationStep.TRAVEL_LIMITS:
        "approcher chaque fin de course en mode manuel et enregistrer la cote",
    CalibrationStep.CAMERA_CALIBRATION:
        "presenter une mire a la camera dans au moins 12 poses",
    CalibrationStep.QUALIFICATION_PART:
        "usiner la piece d'epreuve puis la MESURER sur un moyen independant",
}


def run_hardware_step(step: CalibrationStep) -> CalibrationResult:
    """Etape qui exige la machine : refus motive, jamais un succes fabrique."""
    return CalibrationResult(
        step=step, passed=False,
        detail=("cette etape exige la machine physique : aucune simulation ne la "
                "remplace, et la declarer reussie serait fabriquer de la "
                "confiance"),
        remedy=_REMEDY.get(step, "executer l'etape sur la machine"),
    )


def measure_rotary_axes(
    machine: MachineKinematics, sim: ProbeSimulator,
    *, sphere_radius_from_axis_mm: float = 70.0, n_angles: int = 8,
    a_span_deg: float = 100.0, c_span_deg: float = 160.0,
) -> CalibrationResult:
    """Localise les axes A et C par palpage d'une sphere a plusieurs rotations.

    **C'est l'etape qui leve le verrou nomme par le post-processeur.** Sur une
    cinematique table/table, l'erreur de position des pivots se propage
    directement a la piece, et aucun calcul ne la remplace.

    Deux leviers, tous deux mesures :

      - le RAYON auquel on place la sphere. L'incertitude d'orientation vaut
        residu / rayon du cercle decrit : passer de 30 a 70 mm la divise par
        deux (0,0122 -> 0,0052 deg a 10 um de bruit de palpage). C'est le seul
        levier gratuit de la procedure.
      - l'ETENDUE angulaire balayee. Le pas doit rester sous 180 deg, sinon le
        sens de rotation n'est pas deductible des positions.

    L'etendue de A est bornee par sa course reelle, ce qui rend la localisation
    de A structurellement moins bonne que celle de C sur cette machine : le
    berceau ne fait pas le tour.
    """
    # Sphere placee loin de l'axe C (donc en X) et surelevee, pour que la
    # rotation de A la fasse aussi decrire un grand cercle.
    sphere = DatumSphere(centre_part=np.array([sphere_radius_from_axis_mm, 0.0, 40.0]))

    # --- axe C : A fixe a 0, C balaye
    c_angles = np.linspace(0.0, c_span_deg, n_angles)
    c_centres = np.array([sim.measure_sphere_centre(sphere, 0.0, float(cc)).centre
                          for cc in c_angles])
    c_fit = fit_axis_from_rotation(c_centres, c_angles,
                                   np.asarray(machine.pivot_c, float),
                                   np.array([0.0, 0.0, 1.0]))

    # --- axe A : C fixe a 0, A balaye dans sa course reelle
    a_lo = max(float(machine.a.min_deg), -a_span_deg / 2.0)
    a_hi = min(float(machine.a.max_deg), a_span_deg / 2.0)
    a_angles = np.linspace(a_lo, a_hi, n_angles)
    a_centres = np.array([sim.measure_sphere_centre(sphere, float(aa), 0.0).centre
                          for aa in a_angles])
    a_fit = fit_axis_from_rotation(a_centres, a_angles,
                                   np.asarray(machine.pivot_a, float),
                                   np.array([1.0, 0.0, 0.0]))

    return CalibrationResult(
        step=CalibrationStep.ROTARY_AC, passed=True,
        measured={
            "a_offset_perp_mm": [float(v) for v in a_fit.offset_perp_mm],
            "a_direction": [float(v) for v in a_fit.direction],
            "a_direction_error_deg": a_fit.direction_error_deg,
            "a_circle_radius_mm": a_fit.circle_radius_mm,
            "c_offset_perp_mm": [float(v) for v in c_fit.offset_perp_mm],
            "c_direction": [float(v) for v in c_fit.direction],
            "c_direction_error_deg": c_fit.direction_error_deg,
            "c_circle_radius_mm": c_fit.circle_radius_mm,
        },
        uncertainty={
            "a_point_mm": a_fit.point_uncertainty_mm,
            "a_direction_deg": a_fit.direction_uncertainty_deg,
            "c_point_mm": c_fit.point_uncertainty_mm,
            "c_direction_deg": c_fit.direction_uncertainty_deg,
        },
        detail=(f"axe C : cercle R={c_fit.circle_radius_mm:.2f} mm, residu "
                f"{c_fit.residual_rms_mm * 1000:.2f} um sur {c_fit.n_points} positions ; "
                f"axe A : cercle R={a_fit.circle_radius_mm:.2f} mm, residu "
                f"{a_fit.residual_rms_mm * 1000:.2f} um sur {a_fit.n_points} positions "
                f"(etendue bornee par la course du berceau)"),
    )


def measure_squareness(machine: MachineKinematics, sim: ProbeSimulator,
                       *, span_mm: float = 60.0, n_points: int = 8
                       ) -> CalibrationResult:
    """Equerrage du triedre lineaire, par palpage d'un CUBE etalon.

    **On mesure l'angle ENTRE DEUX FACES, jamais l'orientation d'une seule.**
    C'est la seule mesure qui ait un sens ici, et une premiere version se
    trompait de cible :

      - la normale d'un plan unique, comparee a sa normale nominale, porte
        l'orientation du MONTAGE de l'etalon autant que l'equerrage machine.
        Les deux sont indiscernables sur une seule face.
      - pire, elle ne voit meme pas l'equerrage. Un plan a z constant subit une
        distorsion UNIFORME du triedre — tous ses points se decalent pareil —
        donc sa normale lue est inchangee. Mesure : un equerrage XZ injecte de
        0,30 deg donnait une valeur bit pour bit identique a celle d'une machine
        droite. La procedure avait l'air de mesurer sans mesurer.

    L'angle entre deux faces, lui, est **invariant par rotation de l'etalon** :
    si le cube est pose de travers, les deux normales tournent ensemble et leur
    angle ne change pas. Il ne reste donc que le defaut machine.

    Les trois paires donnent les trois angles SEPAREMENT, ce qui leve la limite
    d'une version precedente qui n'en rendait qu'une combinaison.
    """
    # Cube etalon solidaire de la piece : trois faces nominalement a 90 deg.
    faces = {
        "X": np.array([1.0, 0.0, 0.0]),
        "Y": np.array([0.0, 1.0, 0.0]),
        "Z": np.array([0.0, 0.0, 1.0]),
    }
    origin = np.array([0.0, 0.0, 20.0])
    normals: dict[str, np.ndarray] = {}
    residuals: dict[str, float] = {}
    for name, n0 in faces.items():
        pts = sim.touch_plane(origin + n0 * 10.0, n0, 0.0, 0.0,
                              n_points=n_points, span_mm=span_mm)
        n_meas, res = fit_plane_normal(pts)
        if float(n_meas @ n0) < 0.0:
            n_meas = -n_meas
        normals[name] = n_meas
        residuals[name] = res

    pairs = {"xy": ("X", "Y"), "xz": ("X", "Z"), "yz": ("Y", "Z")}
    measured: dict[str, float] = {}
    for key, (a, b) in pairs.items():
        cos = float(np.clip(normals[a] @ normals[b], -1.0, 1.0))
        measured[f"squareness_{key}_deg"] = 90.0 - math.degrees(math.acos(cos))

    unc = math.degrees(max(residuals.values()) / max(span_mm * 0.5, 1e-6)) * math.sqrt(2.0)
    return CalibrationResult(
        step=CalibrationStep.SQUARENESS, passed=True,
        measured=measured | {"separates_three_angles": True},
        uncertainty={"squareness_deg": unc},
        detail=(f"cube etalon, 3 faces de {n_points} points sur {span_mm:.0f} mm ; "
                f"ecarts a 90 deg : XY {measured['squareness_xy_deg']:+.4f}, "
                f"XZ {measured['squareness_xz_deg']:+.4f}, "
                f"YZ {measured['squareness_yz_deg']:+.4f} deg (+/-{unc:.4f})"),
    )


def measure_backlash(machine: MachineKinematics, sim: ProbeSimulator,
                     *, true_backlash: dict[str, float] | None = None
                     ) -> CalibrationResult:
    """Jeux par approche bidirectionnelle.

    Un jeu ne se voit qu'a l'INVERSION : approcher la meme cote depuis un seul
    sens ne le detecte pas, ce qui est la raison pour laquelle un controle de
    position ordinaire passe a cote.
    """
    truth = true_backlash or {}
    measured, unc = {}, {}
    for axis in ("X", "Y", "Z", "A", "C"):
        r = sim.measure_backlash(axis, true_backlash_mm=float(truth.get(axis, 0.0)))
        measured[axis] = float(r.value_mm[0])
        unc[axis] = float(r.uncertainty_mm)
    return CalibrationResult(
        step=CalibrationStep.BACKLASH, passed=True,
        measured=measured, uncertainty=unc,
        detail="jeux mesures par inversion, 5 reprises par axe",
    )


def measure_homing(machine: MachineKinematics, sim: ProbeSimulator,
                   *, true_repeatability_mm: float = 0.01, n_cycles: int = 10
                   ) -> CalibrationResult:
    """Repetabilite de prise d'origine : un PLANCHER, pas une correction.

    Une origine qui se reprend a 0,02 mm pres interdit d'annoncer mieux que
    0,02 mm, quelle que soit la qualite du reste de la chaine.
    """
    r = sim.measure_homing_repeatability(
        true_repeatability_mm=true_repeatability_mm, n_cycles=n_cycles)
    return CalibrationResult(
        step=CalibrationStep.HOMING, passed=True,
        measured={"repeatability_mm": float(r.value_mm[0])},
        uncertainty={"repeatability_mm": float(r.uncertainty_mm)},
        detail=r.detail,
    )


def measure_probe(machine: MachineKinematics, sim: ProbeSimulator,
                  *, ring_gauge_radius_mm: float = 12.5) -> CalibrationResult:
    """Rayon de bille du palpeur, par palpage d'une bague etalon.

    Le rayon de bille est un decalage systematique : non mesure, il se retrouve
    tel quel sur toute origine palpee. C'est l'erreur la plus facile a corriger
    et la plus penible a oublier.
    """
    sphere = DatumSphere(centre_part=np.array([0.0, 0.0, 30.0]),
                         radius_mm=ring_gauge_radius_mm)
    fit = sim.measure_sphere_centre(sphere, 0.0, 0.0, n_points=13)
    err = fit.radius_mm - ring_gauge_radius_mm
    return CalibrationResult(
        step=CalibrationStep.PROBE_CALIBRATION, passed=True,
        measured={"measured_radius_mm": fit.radius_mm,
                  "reference_radius_mm": float(ring_gauge_radius_mm),
                  "radius_error_mm": float(err)},
        uncertainty={"radius_mm": fit.residual_rms_mm},
        detail=(f"bague etalon R={ring_gauge_radius_mm:.3f} mm, mesure "
                f"R={fit.radius_mm:.4f} mm sur {fit.n_points} points, residu "
                f"{fit.residual_rms_mm * 1000:.2f} um"),
    )


def calibrate_on_twin(
    machine: MachineKinematics,
    true_geometry: MachineGeometry,
    *,
    probe_noise_mm: float = 0.003,
    sphere_radius_from_axis_mm: float = 70.0,
    n_angles: int = 8,
    true_backlash: dict[str, float] | None = None,
    true_homing_repeatability_mm: float = 0.01,
    seed: int = 12345,
):
    """Execute la sequence complete sur le jumeau, et rend ce qu'elle a mesure.

    ``true_geometry`` est la machine REELLE que le jumeau simule : la procedure
    ne la lit jamais, elle ne fait que palper a travers elle. C'est le dispositif
    qui permet de verifier la procedure — on injecte une erreur connue et on
    exige qu'elle soit retrouvee.

    Rend ``(CalibrationReport, MachineGeometry mesuree)``. La geometrie rendue
    est construite **a partir des mesures**, jamais copiee de
    ``true_geometry`` : un test qui recopierait la verite terrain ne testerait
    rien.

    Le rapport n'est pas complet et ne peut pas l'etre : les cinq etapes de
    ``HARDWARE_ONLY`` y figurent en echec avec leur remede. C'est le resultat
    correct, pas une lacune.
    """
    from .interfaces import CalibrationReport

    sim = ProbeSimulator(machine, true_geometry, noise_mm=probe_noise_mm, seed=seed)
    report = CalibrationReport(machine_id=machine.machine_id)

    for step in CalibrationStep:
        if step in HARDWARE_ONLY:
            report.results.append(run_hardware_step(step))
        elif step is CalibrationStep.HOMING:
            report.results.append(measure_homing(
                machine, sim, true_repeatability_mm=true_homing_repeatability_mm))
        elif step is CalibrationStep.SQUARENESS:
            report.results.append(measure_squareness(machine, sim))
        elif step is CalibrationStep.BACKLASH:
            report.results.append(measure_backlash(
                machine, sim, true_backlash=true_backlash))
        elif step is CalibrationStep.ROTARY_AC:
            report.results.append(measure_rotary_axes(
                machine, sim,
                sphere_radius_from_axis_mm=sphere_radius_from_axis_mm,
                n_angles=n_angles))
        elif step is CalibrationStep.PROBE_CALIBRATION:
            report.results.append(measure_probe(machine, sim))

    by_step = {r.step: r for r in report.results}
    rot = by_step[CalibrationStep.ROTARY_AC]
    sq = by_step[CalibrationStep.SQUARENESS]
    hm = by_step[CalibrationStep.HOMING]

    measured = MachineGeometry(
        machine_id=machine.machine_id,
        measured=True,
        a_axis=AxisLocationError(
            offset_mm=list(rot.measured["a_offset_perp_mm"]),
            direction=list(rot.measured["a_direction"]),
            offset_uncertainty_mm=float(rot.uncertainty["a_point_mm"]),
            direction_uncertainty_deg=float(rot.uncertainty["a_direction_deg"]),
        ),
        c_axis=AxisLocationError(
            offset_mm=list(rot.measured["c_offset_perp_mm"]),
            direction=list(rot.measured["c_direction"]),
            offset_uncertainty_mm=float(rot.uncertainty["c_point_mm"]),
            direction_uncertainty_deg=float(rot.uncertainty["c_direction_deg"]),
        ),
        squareness_xy_deg=float(sq.measured["squareness_xy_deg"]),
        squareness_xz_deg=float(sq.measured["squareness_xz_deg"]),
        squareness_yz_deg=float(sq.measured["squareness_yz_deg"]),
        squareness_uncertainty_deg=float(sq.uncertainty["squareness_deg"]),
        homing_repeatability_mm=float(hm.measured["repeatability_mm"]),
    )
    return report, measured
