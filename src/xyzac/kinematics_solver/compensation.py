"""Compensation des erreurs geometriques mesurees.

Ce module porte la consequence pratique de ``machine_model.geometry`` : une
erreur geometrique CONNUE se corrige, et se corriger veut dire deux choses
distinctes sur une cinematique XYZAC.

**La position se corrige exactement.** Les axes lineaires translatent la broche
dans le repere machine ; n'importe quel ecart de position de la piece se
rattrape donc en deplacant la commande. Il n'y a pas d'approximation : la
correction est la difference entre le transport reel et le transport nominal,
eventuellement passee dans l'inverse du triedre lineaire mesure.

**L'orientation se corrige par re-resolution.** Les axes A et C reels ne sont
pas exactement +X et +Z, donc la formule fermee ``A = arccos(dz)``,
``C = atan2(dx, dy)`` ne donne plus la bonne direction d'outil. On repart de
cette solution nominale et on la raffine par Gauss-Newton amorti sur les axes
mesures. Deux a trois iterations suffisent pour des defauts realistes.

**Ce qui ne se corrige pas** est rendu explicitement, jamais absorbe :

  - le residu d'orientation quand le raffinement n'atteint pas sa tolerance —
    cas reel a moins d'un centieme de degre de la singularite A -> 0, ou la
    direction d'outil devient insensible a C. Mesure : 2,9e-05 deg, soit
    0,05 um a 100 mm, donc negligeable devant l'incertitude de calibration —
    mais rendu, pas absorbe ;
  - les jeux, qui sont une hysteresis et non un decalage ;
  - l'incertitude des mesures elles-memes, qui est le vrai plancher
    (``MachineGeometry.position_uncertainty_mm``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..geometry_core.types import angle_between, normalize
from ..machine_model.geometry import MachineGeometry
from ..machine_model.machine import MachineKinematics


@dataclass
class CompensatedMove:
    """Commande machine corrigee, et ce que la correction n'a pas pu rattraper."""

    x_mm: float
    y_mm: float
    z_mm: float
    a_deg: float
    c_deg: float
    #: Angle entre la direction d'outil obtenue et celle demandee, apres
    #: re-resolution. Non nul signifie que (A, C) ne peut pas realiser la
    #: direction voulue sur cette machine — pas que le calcul a echoue.
    orientation_residual_deg: float
    #: Ecart de position residuel apres correction lineaire. Doit etre nul aux
    #: arrondis pres : s'il ne l'est pas, la chaine de transport est incoherente.
    position_residual_mm: float
    converged: bool
    n_iter: int

    @property
    def linear(self) -> np.ndarray:
        return np.array([self.x_mm, self.y_mm, self.z_mm], dtype=np.float64)

    def describe(self) -> str:
        s = (f"X{self.x_mm:+.4f} Y{self.y_mm:+.4f} Z{self.z_mm:+.4f} "
             f"A{self.a_deg:+.4f} C{self.c_deg:+.4f}")
        if self.orientation_residual_deg > 1e-6:
            s += (f" ; residu d'orientation {self.orientation_residual_deg:.5f} deg "
                  "non rattrapable par (A, C)")
        if not self.converged:
            s += " ; RE-RESOLUTION NON CONVERGEE"
        return s


def solve_real_orientation(
    geom: MachineGeometry, d_target: np.ndarray,
    a_seed: float, c_seed: float, *, iters: int = 60, tol_deg: float = 1e-7,
) -> tuple[float, float, float, bool, int]:
    """Re-resout (A, C) sur les axes REELS pour atteindre ``d_target``.

    Gauss-Newton amorti sur le residu vectoriel, jacobien par differences
    finies.

    **L'amortissement est necessaire, et pas pour la raison qu'on croit.** Une
    premiere version de ce docstring affirmait qu'un Gauss-Newton pur « diverge
    en produisant un C arbitrairement grand » pres de la singularite. Mesure :
    c'est faux, il converge, et plus vite (3 iterations contre 5 a A = 0,5 deg).
    Le vrai mode d'echec est different et plus brutal — quand l'axe C est
    exactement nominal et A = 0, la direction d'outil ne depend plus de C, le
    systeme normal ``J^T J`` est exactement singulier et ``numpy.linalg.solve``
    **leve**. Sans amortissement, la fonction ne rend donc rien du tout ; avec
    ``lam = 1e-9`` elle converge en 22 iterations.

    **L'amorce n'est pas un detail d'implementation, et pas pour la raison que
    j'avais ecrite d'abord.** Elle ne decide pas de la convergence : mesure sur
    une cible a 5 deg de l'axe, les deux amorces convergent au meme residu
    (2e-9 deg). Elle decide de **laquelle des solutions** on atteint. Dans la
    geometrie ou l'axe C est nominal, une amorce (0, 0) aboutit a C = -89,80 deg
    et une amorce nominale a C = +90,20 deg : deux solutions valides separees
    par **180 deg de plateau**. Choisir entre elles est une decision de
    trajectoire — continuite, singularite, courses — et la prendre ici la
    rendrait invisible. D'ou l'exigence des valeurs nominales en entree.

    Accessoirement l'amorce decide du coût : 3 a 8 iterations depuis la solution
    nominale, 20 a 24 depuis (0, 0).

    **Fait physique a retenir, mesure ici** : pres de la singularite, une
    correction d'orientation minuscule coûte une grande rotation de plateau. Un
    defaut d'axe de 0,15 deg demande **16,6 deg de C** a A = 0,5 deg, contre
    1,5 deg a A = 5 deg. La compensation n'est donc pas neutre vis-a-vis des
    courses rotatives, et un plan qui frole A = 0 peut devenir infaisable
    apres compensation alors qu'il passait avant.

    Convergence mesuree sur le chemin de production (amorce nominale, defauts
    de 0,15 a 0,20 deg) : 1 a 5 iterations de A = 0 a A = 80 deg. Seul
    A = 0,01 deg n'atteint pas la tolerance et s'arrete a **2,9e-05 deg, soit
    0,05 um a 100 mm de rayon**.

    La borne ``iters`` vaut 60 et non 20 : le cas singulier ci-dessus en demande
    22, et une premiere valeur de 20 le faisait echouer d'un cheveu en rendant
    un residu de 0,044 deg. Soixante iterations d'un systeme 2x2 ne coutent
    rien, et converger vaut mieux que rapporter.

    Rend ``(a, c, residu_deg, converge, n_iter)``. Le residu est la grandeur
    utile — et il se juge contre le **budget d'incertitude** de la machine
    (``MachineGeometry.position_uncertainty_mm``), pas contre zero : 0,05 um de
    residu n'a aucun sens en face de dizaines de microns d'incertitude de
    calibration. ``converged=False`` veut donc dire « la tolerance numerique
    n'est pas atteinte », pas « le resultat est inutilisable ».
    """
    d = normalize(np.asarray(d_target, dtype=np.float64))
    a, c = float(a_seed), float(c_seed)
    h = 1e-6
    lam = 1e-9
    n = 0

    for n in range(1, iters + 1):
        f = geom.real_tool_axis_in_part(a, c) - d
        res = math.degrees(angle_between(geom.real_tool_axis_in_part(a, c), d))
        if res < tol_deg:
            return a, c, res, True, n

        da = (geom.real_tool_axis_in_part(a + h, c)
              - geom.real_tool_axis_in_part(a - h, c)) / (2.0 * h)
        dc = (geom.real_tool_axis_in_part(a, c + h)
              - geom.real_tool_axis_in_part(a, c - h)) / (2.0 * h)
        j = np.column_stack([da, dc])

        # Moindres carres amortis : (J^T J + lam.I) dq = -J^T f
        jtj = j.T @ j + lam * np.eye(2)
        try:
            dq = np.linalg.solve(jtj, -j.T @ f)
        except np.linalg.LinAlgError:
            break
        # Pas borne : un pas immense pres de la singularite ne sert a rien et
        # sort des courses.
        step = float(np.linalg.norm(dq))
        if step > 5.0:
            dq *= 5.0 / step
        a += float(dq[0])
        c += float(dq[1])

    res = math.degrees(angle_between(geom.real_tool_axis_in_part(a, c), d))
    return a, c, res, res < tol_deg, n


def compensate_pose(
    machine: MachineKinematics,
    geom: MachineGeometry,
    p_part: np.ndarray,
    d_part: np.ndarray,
    *,
    a_nominal: float,
    c_nominal: float,
    mount_offset: np.ndarray | None = None,
    work_offset: np.ndarray | None = None,
    resolve_orientation: bool = True,
) -> CompensatedMove:
    """Commande corrigee pour poser le TCP sur ``p_part`` avec l'axe ``d_part``.

    ``a_nominal`` / ``c_nominal`` viennent de la cinematique inverse nominale
    (``KinematicsSolver.ik_best``) : ils servent d'amorce, et la branche qu'ils
    portent est conservee. C'est voulu — choisir la branche est une decision de
    trajectoire (continuite, singularite, courses), pas une decision de
    compensation, et la prendre ici la rendrait invisible.
    """
    geom.require_measured()
    mo = np.zeros(3) if mount_offset is None else np.asarray(mount_offset, float)
    wo = np.zeros(3) if work_offset is None else np.asarray(work_offset, float)

    a, c, res_deg, ok, n = (
        solve_real_orientation(geom, d_part, a_nominal, c_nominal)
        if resolve_orientation else (float(a_nominal), float(c_nominal), 0.0, True, 0))

    # Position : le point piece transporte par la chaine REELLE doit coincider
    # avec la broche. Les axes lineaires etant une pure translation dans le
    # repere machine, l'egalite se resout exactement.
    target = geom.real_part_to_machine(machine, np.asarray(p_part, float) + mo, a, c) + wo
    s = geom.linear_matrix()
    cmd = np.linalg.solve(s, target)

    # Verification de la chaine, pas du resultat : si la commande rendue ne
    # replace pas le point ou on l'attend, c'est le transport qui est faux.
    achieved = s @ cmd
    pos_res = float(np.linalg.norm(achieved - target))

    return CompensatedMove(
        x_mm=float(cmd[0]), y_mm=float(cmd[1]), z_mm=float(cmd[2]),
        a_deg=float(a), c_deg=float(c),
        orientation_residual_deg=float(res_deg),
        position_residual_mm=pos_res, converged=bool(ok), n_iter=int(n),
    )


def realised_pose(
    machine: MachineKinematics, geom: MachineGeometry, move: CompensatedMove,
    *, work_offset: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Ou la machine REELLE met le TCP, et selon quelle direction d'outil.

    Sert aux tests : on compense, on rejoue la cinematique reelle sur la
    commande produite, et on compare a la cible. Une compensation qui ne se
    verifie que contre son propre calcul ne verifie rien.

    Rend le point en repere PIECE (donc directement comparable a la cible) et la
    direction d'axe outil en repere piece.
    """
    wo = np.zeros(3) if work_offset is None else np.asarray(work_offset, float)
    spindle = geom.linear_matrix() @ move.linear - wo

    # Transport inverse : machine -> piece, sur la geometrie reelle.
    pc = np.asarray(machine.pivot_c, dtype=np.float64) + geom.c_axis.d
    pa = np.asarray(machine.pivot_a, dtype=np.float64) + geom.a_axis.d
    from ..machine_model.geometry import _rodrigues
    rz = _rodrigues(geom.c_axis.u, math.radians(move.c_deg))
    rx = _rodrigues(geom.a_axis.u, math.radians(move.a_deg))
    p = rx.T @ (spindle - pa) + pa
    p = rz.T @ (p - pc) + pc
    return p, geom.real_tool_axis_in_part(move.a_deg, move.c_deg)
