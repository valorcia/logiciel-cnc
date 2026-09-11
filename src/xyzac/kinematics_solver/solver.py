"""Cinematique inverse XYZAC et sequencage des axes rotatifs.

Deux resultats importants sont encodes ici, et ils gouvernent tout l'aval :

1. **Double solution.** Toute direction d'axe outil admet DEUX couples (A, C) :
   ``(A, C)`` et ``(-A, C + 180)``. Choisir localement est une erreur : le bon
   choix depend des butees et du point precedent. D'ou ``ik_branches`` qui
   retourne les deux, et un solveur de sequence en aval (ADR-001 / D6).

2. **Singularite en A -> 0.** Quand l'axe outil est aligne sur Z piece, C est
   indetermine : deux directions voisines peuvent exiger 180 deg de plateau.
   ``singularity_severity`` quantifie ce mauvais conditionnement pour que
   l'optimiseur le paie au lieu de le decouvrir sur la machine.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..geometry_core.types import normalize, unwrap_towards
from ..machine_model.machine import MachineKinematics


@dataclass(frozen=True)
class AxisSolution:
    """Un couple (A, C) realisable, avec son diagnostic."""

    a_deg: float
    c_deg: float
    branch: int                 # 0 = A >= 0, 1 = branche miroir
    within_limits: bool
    singular: bool
    singularity_severity: float  # 0 = sain, 1 = singularite franche
    residual_deg: float          # ecart angulaire entre l'axe obtenu et l'axe demande

    @property
    def feasible(self) -> bool:
        return self.within_limits and not self.singular


class KinematicsSolver:
    """CI/CD XYZAC : direction <-> (A, C), avec butees et continuite."""

    def __init__(self, machine: MachineKinematics):
        self.m = machine

    # -- cinematique directe ---------------------------------------------

    def forward(self, a_deg: float, c_deg: float) -> np.ndarray:
        return self.m.tool_axis_in_part(a_deg, c_deg)

    # -- cinematique inverse ---------------------------------------------

    def ik_branches(self, d_part: np.ndarray) -> list[AxisSolution]:
        """Les deux branches (A, C) realisant la direction ``d_part``.

        ``d_part`` pointe du bec vers la broche. Retourne les branches triees :
        realisables d'abord, puis par severite de singularite croissante.
        """
        d = normalize(np.asarray(d_part, dtype=np.float64))
        dz = float(np.clip(d[2], -1.0, 1.0))

        a0 = math.degrees(math.acos(dz))              # dans [0, 180]
        c0 = math.degrees(math.atan2(d[0], d[1]))     # atan2(dx, dy) : cf. D5

        cands = [(a0, c0, 0), (-a0, c0 + 180.0, 1)]

        out: list[AxisSolution] = []
        for a, c, br in cands:
            c = ((c + 180.0) % 360.0) - 180.0  # representant canonique dans (-180, 180]
            sev = self.singularity_severity(a)
            achieved = self.forward(a, c)
            resid = math.degrees(
                math.atan2(float(np.linalg.norm(np.cross(achieved, d))), float(np.dot(achieved, d)))
            )
            out.append(
                AxisSolution(
                    a_deg=a, c_deg=c, branch=br,
                    within_limits=self.m.within_limits(a, c),
                    singular=self.m.is_singular(a),
                    singularity_severity=sev,
                    residual_deg=resid,
                )
            )
        out.sort(key=lambda s: (not s.feasible, s.singularity_severity, abs(s.a_deg)))
        return out

    def ik_best(self, d_part: np.ndarray) -> AxisSolution | None:
        """Meilleure branche isolee. A n'utiliser que hors sequence.

        Pour une trajectoire, passer par ``orientation_solver`` : un choix
        point par point produit des retournements de plateau.
        """
        br = self.ik_branches(d_part)
        return br[0] if br and br[0].feasible else None

    def singularity_severity(self, a_deg: float) -> float:
        """Severite de singularite dans [0, 1].

        Vaut 1 quand A = 0 (C totalement indetermine) et decroit en ``|sin A|``
        rapporte au seuil machine. Au-dela du seuil, 0.
        """
        thr = math.radians(max(self.m.singularity_a_deg, 1e-6))
        s = abs(math.sin(math.radians(a_deg)))
        s_thr = math.sin(thr)
        return float(max(0.0, 1.0 - s / s_thr)) if s < s_thr else 0.0

    def conditioning(self, a_deg: float) -> float:
        """Gain ``dC / d(direction)`` : amplification de l'axe C.

        Vaut ``1 / |sin A|``. Pour A = 1 deg, une variation de 1 deg de l'axe
        outil peut demander 57 deg de plateau. C'est la mesure physique de la
        singularite, utilisee comme cout dans l'optimiseur.
        """
        s = abs(math.sin(math.radians(a_deg)))
        return float(1.0 / max(s, 1e-6))

    # -- continuite -------------------------------------------------------

    def unwrap_sequence(self, a_seq: np.ndarray, c_seq: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Deroule C pour supprimer les sauts de +/-360, en respectant les butees.

        Un plateau declare continu peut accumuler les tours ; un plateau borne
        doit rester dans sa course, quitte a garder un saut que le planner
        devra traiter par un mouvement de degagement.
        """
        a_seq = np.asarray(a_seq, dtype=np.float64).copy()
        c_out = np.asarray(c_seq, dtype=np.float64).copy()
        for i in range(1, len(c_out)):
            cand = math.degrees(
                unwrap_towards(math.radians(c_out[i]), math.radians(c_out[i - 1]))
            )
            if self.m.c.continuous or self.m.c.contains(cand):
                c_out[i] = cand
            # sinon : on conserve le representant canonique et on laisse le saut
            # visible, plutot que de sortir silencieusement de la course.
        return a_seq, c_out

    def rotary_travel(self, a_seq: np.ndarray, c_seq: np.ndarray) -> tuple[float, float]:
        """Course rotative cumulee (deg) sur A et C. Proxy d'usure et de temps."""
        a_seq, c_seq = np.asarray(a_seq), np.asarray(c_seq)
        return (float(np.abs(np.diff(a_seq)).sum()), float(np.abs(np.diff(c_seq)).sum()))

    def violates_rotary_rate(
        self, a0: float, c0: float, a1: float, c1: float, linear_step_mm: float
    ) -> bool:
        """Transition rotative trop brutale pour le deplacement lineaire associe.

        Sur une machine table/table, une grande rotation sur un petit pas
        lineaire signifie que la piece balaie vite sous l'outil : l'avance au
        point de contact explose meme si l'avance programmee est modeste.
        """
        rot = math.hypot(a1 - a0, c1 - c0)
        return rot > self.m.max_rotary_per_linear_deg_mm * max(linear_step_mm, 1e-3)

    def part_to_machine_point(self, p_part: np.ndarray, a_deg: float, c_deg: float) -> np.ndarray:
        """Transporte un point du repere piece vers le repere machine.

        Tient compte des deux pivots : le plateau C tourne autour de ``pivot_c``,
        le berceau A autour de ``pivot_a``. Les offsets de pivot sont des
        grandeurs calibrees ; les ignorer est l'erreur classique qui donne une
        simulation juste et une piece fausse.
        """
        m = self.m
        a, c = math.radians(a_deg), math.radians(c_deg)
        pc = np.asarray(m.pivot_c, dtype=np.float64)
        pa = np.asarray(m.pivot_a, dtype=np.float64)

        ca, sa, cc, sc = math.cos(a), math.sin(a), math.cos(c), math.sin(c)
        rz = np.array([[cc, -sc, 0], [sc, cc, 0], [0, 0, 1]])
        rx = np.array([[1, 0, 0], [0, ca, -sa], [0, sa, ca]])

        p = np.asarray(p_part, dtype=np.float64)
        p = rz @ (p - pc) + pc     # rotation plateau C
        p = rx @ (p - pa) + pa     # rotation berceau A
        return p
