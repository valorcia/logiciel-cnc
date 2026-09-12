"""Assemblage et auto-calibration de la machine en kit.

Specificite produit : l'acheteur imprime et assemble sa machine. Le logiciel ne
peut donc PAS partir de cotes nominales de plan — il doit mesurer la machine
qu'il a reellement devant lui. C'est aussi la raison pour laquelle
``MachineKinematics`` livre ses jeux (backlash) a 0.0 : declarer une valeur non
mesuree serait pire que de n'en declarer aucune.

Chaque etape produit une mesure AVEC son incertitude, et chaque etape peut
echouer sans bloquer les precedentes. L'ordre n'est pas negociable : verifier la
geometrie avant de connaitre le sens des axes n'a aucun sens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto


class CalibrationStep(Enum):
    """Sequence d'assemblage et de calibration, dans l'ordre obligatoire."""

    WIRING_TEST = auto()        # continuite, phases moteur, fins de course
    AXIS_DIRECTION = auto()     # sens de chaque axe (piege n1 du montage)
    HOMING = auto()             # prise d'origine repetable
    TRAVEL_LIMITS = auto()      # courses reelles mesurees, pas celles du plan
    SQUARENESS = auto()         # geometrie : equerrage, planeite
    BACKLASH = auto()           # jeux mesures par inversion
    ROTARY_AC = auto()          # centres et orientations des axes A et C
    PROBE_CALIBRATION = auto()  # rayon bille, excentration
    CAMERA_CALIBRATION = auto()  # intrinseques + main-oeil
    QUALIFICATION_PART = auto()  # piece d'epreuve usinee puis MESUREE


@dataclass
class CalibrationResult:
    step: CalibrationStep
    passed: bool
    measured: dict = field(default_factory=dict)
    uncertainty: dict = field(default_factory=dict)
    detail: str = ""
    remedy: str = ""


@dataclass
class CalibrationReport:
    """Rapport d'assemblage. Sert de piece justificative de la machine livree."""

    machine_id: str
    results: list[CalibrationResult] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        done = {r.step for r in self.results if r.passed}
        return done == set(CalibrationStep)

    def blocking(self) -> list[CalibrationStep]:
        return [r.step for r in self.results if not r.passed]

    def precision_statement(self) -> str:
        """Ce que l'on a le droit d'affirmer sur la precision de CETTE machine.

        Point non negociable (ADR-001 / R3) : **+/-0,02 mm n'est pas un acquis.**
        C'est un objectif de qualification physique, a demontrer sur piece
        d'epreuve mesuree, machine par machine. Le logiciel ne peut garantir que
        sa propre erreur numerique ; il ne peut rien garantir de la chaine
        mecanique d'un kit assemble par l'acheteur. Aucune documentation ni
        interface ne doit annoncer un chiffre que cette methode ne renvoie pas.
        """
        qual = [r for r in self.results if r.step is CalibrationStep.QUALIFICATION_PART]
        if not qual or not qual[0].passed:
            return ("Precision NON QUALIFIEE sur cette machine. Aucune tolerance "
                    "ne peut etre annoncee tant que la piece d'epreuve n'a pas "
                    "ete usinee ET mesuree.")
        m = qual[0].measured
        return (f"Precision qualifiee sur piece d'epreuve : "
                f"ecart max mesure {m.get('max_deviation_mm', '?')} mm "
                f"(incertitude {qual[0].uncertainty.get('measurement_mm', '?')} mm, "
                f"methode : {m.get('method', 'non precisee')}). "
                f"Valable pour CETTE machine, dans CET etat de calibration.")


def run_step(step: CalibrationStep, gateway, machine) -> CalibrationResult:
    """Execution d'une etape sur la MACHINE REELLE. Exige ``linuxcnc_gateway``.

    Implementee sur le jumeau numerique depuis le jalon M7 : voir
    ``procedures.calibrate_on_twin``, qui execute la sequence contre un palpeur
    simule et permet de verifier chaque procedure en lui injectant une erreur
    connue. Le jumeau valide la MATHEMATIQUE d'une procedure ; il ne remplace
    aucune mesure.

    Cette entree-ci vise la machine physique, et elle reste donc fermee :
    ``linuxcnc_gateway`` est verrouille tant qu'aucune machine n'existe.
    """
    raise NotImplementedError(
        f"etape '{step.name}' sur machine reelle : linuxcnc_gateway est "
        "verrouille. Pour valider la procedure sans machine, employer "
        "assembly_calibration.calibrate_on_twin, qui la verifie en lui "
        "injectant une erreur geometrique connue."
    )
