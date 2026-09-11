"""Machine d'etat de securite : la derniere porte avant le post-processeur.

Regle fondatrice (ADR-001 / D9) : **l'IA ne pilote jamais les moteurs.** Aucune
trajectoire ne devient executable sans avoir traverse, dans l'ordre, les portes
collision -> cinematique -> simulation, et sans qu'une approbation soit
enregistree CONTRE LE HASH DU SETUP.

La consequence pratique, et c'est tout l'interet du mecanisme : deplacer un
mors, remesurer un outil ou corriger l'origine piece change le hash, et
l'approbation tombe d'elle-meme. Il n'existe aucun chemin de code permettant de
rejouer un programme approuve sous un autre setup — c'est verifie par un test,
pas seulement enonce dans un document.

Ce module ne connait ni LinuxCNC, ni le reseau, ni les moteurs. Il ne sait que
dire oui ou non, et pourquoi.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class SafetyState(str, Enum):
    IDLE = "idle"                  # rien a valider
    SETUP_DEFINED = "setup"        # setup pose, rien de verifie
    COLLISION_CHECKED = "collision"
    KINEMATICS_CHECKED = "kinematics"
    SIMULATED = "simulated"
    APPROVED = "approved"          # seul etat depuis lequel un post-processeur peut tourner
    INVALIDATED = "invalidated"    # setup modifie apres approbation
    FAULT = "fault"                # une porte a echoue


#: Enchainement autorise. Toute transition absente de ce graphe est refusee.
_ALLOWED: dict[SafetyState, set[SafetyState]] = {
    SafetyState.IDLE: {SafetyState.SETUP_DEFINED},
    SafetyState.SETUP_DEFINED: {SafetyState.COLLISION_CHECKED, SafetyState.FAULT,
                                SafetyState.SETUP_DEFINED},
    SafetyState.COLLISION_CHECKED: {SafetyState.KINEMATICS_CHECKED, SafetyState.FAULT,
                                    SafetyState.INVALIDATED},
    SafetyState.KINEMATICS_CHECKED: {SafetyState.SIMULATED, SafetyState.FAULT,
                                     SafetyState.INVALIDATED},
    SafetyState.SIMULATED: {SafetyState.APPROVED, SafetyState.FAULT,
                            SafetyState.INVALIDATED},
    SafetyState.APPROVED: {SafetyState.INVALIDATED, SafetyState.FAULT},
    SafetyState.INVALIDATED: {SafetyState.SETUP_DEFINED},
    SafetyState.FAULT: {SafetyState.SETUP_DEFINED},
}


class SafetyViolation(RuntimeError):
    """Levee des qu'une transition interdite ou une approbation caduque est tentee."""


@dataclass
class GateRecord:
    """Trace horodatee du passage d'une porte. Constitue le journal d'audit."""

    gate: str
    passed: bool
    setup_hash: str
    detail: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class SafetyStateMachine:
    """Sequenceur des portes de securite, lie a un hash de setup."""

    setup_hash: str
    state: SafetyState = SafetyState.IDLE
    journal: list[GateRecord] = field(default_factory=list)

    #: Les interlocks materiels sont INDEPENDANTS du logiciel (ADR-001 / D9).
    #: Ce drapeau n'est qu'un reflet informatif : le logiciel ne peut ni les
    #: armer, ni les masquer, ni les reinitialiser, et ne doit jamais dependre
    #: d'eux pour sa propre surete.
    hardware_estop_is_independent: bool = True

    def _transition(self, target: SafetyState, gate: str, passed: bool, detail: str = "") -> None:
        if target not in _ALLOWED.get(self.state, set()):
            raise SafetyViolation(
                f"transition interdite {self.state.value} -> {target.value} "
                f"(porte '{gate}'). Les portes ne peuvent pas etre sautees."
            )
        self.journal.append(GateRecord(gate=gate, passed=passed,
                                       setup_hash=self.setup_hash, detail=detail))
        self.state = target

    # -- portes ------------------------------------------------------------

    def define_setup(self, setup_hash: str) -> None:
        """(Re)definit le setup. Repart systematiquement de zero."""
        self.setup_hash = setup_hash
        if self.state in (SafetyState.INVALIDATED, SafetyState.FAULT, SafetyState.IDLE,
                          SafetyState.SETUP_DEFINED):
            self._transition(SafetyState.SETUP_DEFINED, "setup", True, setup_hash[:16])
        else:
            # Redefinir un setup alors qu'une validation est en cours n'est pas
            # une erreur d'usage : c'est le cas normal. Mais tout ce qui a ete
            # valide avant devient caduc.
            self.invalidate("setup redefini")
            self._transition(SafetyState.SETUP_DEFINED, "setup", True, setup_hash[:16])

    def pass_collision(self, ok: bool, detail: str = "") -> None:
        self._transition(SafetyState.COLLISION_CHECKED if ok else SafetyState.FAULT,
                         "collision_engine", ok, detail)

    def pass_kinematics(self, ok: bool, detail: str = "") -> None:
        self._transition(SafetyState.KINEMATICS_CHECKED if ok else SafetyState.FAULT,
                         "kinematics_solver", ok, detail)

    def pass_simulation(self, ok: bool, detail: str = "") -> None:
        self._transition(SafetyState.SIMULATED if ok else SafetyState.FAULT,
                         "simulation_engine", ok, detail)

    def approve(self, operator: str) -> None:
        """Approbation finale. Exige un operateur nomme : une approbation
        anonyme n'est pas une approbation."""
        if not operator or not operator.strip():
            raise SafetyViolation("approbation refusee : operateur non identifie")
        self._transition(SafetyState.APPROVED, "approbation", True, f"par {operator}")

    def invalidate(self, reason: str) -> None:
        if self.state is SafetyState.INVALIDATED:
            return
        self.journal.append(GateRecord("invalidation", False, self.setup_hash, reason))
        self.state = SafetyState.INVALIDATED

    # -- interrogation ------------------------------------------------------

    def check_setup_unchanged(self, current_hash: str) -> None:
        """Invalide l'approbation si le setup a bouge depuis.

        A appeler AVANT toute generation de programme. C'est le mecanisme qui
        rend l'exigence « une modification de setup invalide l'approbation »
        effective plutot que declarative.
        """
        if current_hash != self.setup_hash:
            self.invalidate(
                f"setup modifie : {self.setup_hash[:12]} -> {current_hash[:12]}")

    def may_postprocess(self, current_hash: str) -> bool:
        """Seule reponse qui autorise le post-processeur a produire du G-code."""
        self.check_setup_unchanged(current_hash)
        return self.state is SafetyState.APPROVED

    def require_postprocess(self, current_hash: str) -> None:
        """Variante levant une exception : c'est celle qu'utilise le code de
        production, pour qu'un oubli de verification du booleen soit impossible."""
        if not self.may_postprocess(current_hash):
            raise SafetyViolation(
                f"generation refusee : etat '{self.state.value}'. "
                "Une trajectoire doit passer collision + cinematique + simulation "
                "et etre approuvee sous le setup courant."
            )

    def audit_trail(self) -> str:
        lines = [f"Machine d'etat de securite — etat : {self.state.value}",
                 f"  setup : {self.setup_hash[:16]}"]
        for r in self.journal:
            lines.append(f"  [{'OK ' if r.passed else 'NOK'}] {r.gate:20s} "
                         f"{r.setup_hash[:8]}  {r.detail}")
        return "\n".join(lines)
