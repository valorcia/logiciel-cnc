"""Palpeur VIRTUEL sur le jumeau numerique.

Raison d'etre : une procedure de calibration ne peut pas se verifier contre
elle-meme. On injecte donc dans le jumeau une erreur geometrique CONNUE, on
simule le palpage sur cette machine fausse, et on exige que la procedure
retrouve l'erreur injectee. Si elle ne la retrouve pas, la procedure ne vaut
rien — quoi qu'elle affiche.

C'est la regle degagee au jalon M6 (« faire varier le parametre qui doit
commander le resultat, et verifier qu'il le commande ») appliquee au sujet de
M7. Elle est ici la seule garantie disponible, puisqu'aucune machine n'existe.

**Ce module ne remplace pas une machine.** Il valide la MATHEMATIQUE de la
procedure — l'ajustement, la propagation d'incertitude, la sensibilite au bruit
et au nombre de points. Il ne dit rien des erreurs qu'il ne modelise pas :
deformations thermiques, flexion sous effort de palpage, hysteresis du
declencheur, defauts de forme de la sphere de reference.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..geometry_core.types import normalize
from ..machine_model.geometry import MachineGeometry
from ..machine_model.machine import MachineKinematics
from .fitting import SphereFit, fit_sphere
from .interfaces import ProbeResult


@dataclass
class DatumSphere:
    """Sphere de reference solidaire du plateau C.

    ``centre_part`` est sa position dans le repere PIECE (donc lie au plateau).
    Le rayon compte peu ; ce qui compte est la DISTANCE a l'axe mesure, parce
    que l'incertitude d'orientation vaut residu / rayon du cercle decrit.
    """

    centre_part: np.ndarray
    radius_mm: float = 12.5

    def __post_init__(self):
        self.centre_part = np.asarray(self.centre_part, dtype=np.float64)


@dataclass
class ProbeSimulator:
    """Palpeur a declenchement simule sur une machine dont on connait les defauts."""

    machine: MachineKinematics
    geometry: MachineGeometry
    #: Bruit de declenchement, ecart-type en mm. 1 a 3 um est realiste pour un
    #: palpeur a contact correctement etalonne ; 10 um pour un palpeur maker.
    noise_mm: float = 0.002
    seed: int = 12345
    _rng: np.random.Generator = field(init=False, repr=False)

    def __post_init__(self):
        self._rng = np.random.default_rng(self.seed)
        self._axis_from_machine = np.linalg.inv(self.geometry.linear_matrix())

    def _read(self, p_machine: np.ndarray) -> np.ndarray:
        """Position telle que la MACHINE la rapporte, en coordonnees d'axes.

        Un palpeur ne mesure pas une position euclidienne : il rend les valeurs
        des axes au declenchement. Un defaut d'equerrage ou d'echelle distord
        donc la lecture, et c'est par cette distorsion — et pas autrement —
        qu'on peut esperer le mesurer.

        Sans cette conversion, le jumeau ne portait aucun defaut du triedre
        lineaire : ``measure_squareness`` rendait une incertitude sans jamais
        pouvoir rendre une valeur, ce qui est une procedure qui a l'air de
        mesurer sans mesurer.
        """
        return self._axis_from_machine @ np.asarray(p_machine, dtype=np.float64)

    # -- palpage elementaire ----------------------------------------------

    def touch_sphere(self, sphere: DatumSphere, a_deg: float, c_deg: float,
                     n_points: int = 9) -> np.ndarray:
        """Points de contact sur la sphere, en repere MACHINE.

        Le centre reel est obtenu par la chaine cinematique REELLE du jumeau :
        c'est la que l'erreur injectee entre.

        **Les points sont repartis sur DEUX latitudes plus le pole**, comme une
        vraie routine de palpage de sphere. Ce n'est pas un raffinement : une
        premiere version prenait tous ses points sur une seule latitude, et des
        points d'un meme cercle appartiennent a une infinite de spheres. Le
        centre rendu etait alors une valeur sans contenu, et la localisation
        d'axe qui en decoulait se trompait de 178 deg. ``fit_sphere`` refuse
        desormais cette configuration ; ce constructeur ne la produit plus.
        """
        centre = self.geometry.real_part_to_machine(
            self.machine, sphere.centre_part, a_deg, c_deg)
        n_ring = max((n_points - 1) // 2, 3)
        pts = [centre + sphere.radius_mm * np.array([0.0, 0.0, 1.0])]   # pole
        for theta_deg in (35.0, 70.0):
            theta = np.radians(theta_deg)
            for k in range(n_ring):
                phi = 2.0 * np.pi * k / n_ring + np.radians(theta_deg)
                n = np.array([np.sin(theta) * np.cos(phi),
                              np.sin(theta) * np.sin(phi),
                              np.cos(theta)])
                pts.append(centre + sphere.radius_mm * n)
        pts = np.array([self._read(q) for q in pts])
        return pts + self._rng.normal(0.0, self.noise_mm, pts.shape)

    def measure_sphere_centre(self, sphere: DatumSphere, a_deg: float, c_deg: float,
                              n_points: int = 8) -> SphereFit:
        return fit_sphere(self.touch_sphere(sphere, a_deg, c_deg, n_points))

    def touch_plane(self, plane_point_part: np.ndarray, plane_normal_part: np.ndarray,
                    a_deg: float, c_deg: float, n_points: int = 5,
                    span_mm: float = 30.0) -> np.ndarray:
        """Points palpes sur un plan solidaire de la piece, en repere MACHINE."""
        p0 = np.asarray(plane_point_part, dtype=np.float64)
        n0 = normalize(plane_normal_part)
        # Deux directions du plan, en repere piece.
        tmp = np.array([1.0, 0.0, 0.0]) if abs(n0[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        u = normalize(np.cross(n0, tmp))
        v = np.cross(n0, u)
        out = []
        for k in range(n_points):
            ang = 2.0 * np.pi * k / max(n_points, 1)
            q = p0 + span_mm * (np.cos(ang) * u + np.sin(ang) * v) * 0.5
            m = self.geometry.real_part_to_machine(self.machine, q, a_deg, c_deg)
            out.append(self._read(m) + self._rng.normal(0.0, self.noise_mm, 3))
        return np.array(out)

    def measure_backlash(self, axis: str, *, true_backlash_mm: float,
                         n_reversals: int = 5) -> ProbeResult:
        """Jeu mesure par approche bidirectionnelle d'une meme surface.

        Le jeu se voit a l'INVERSION : on approche la meme cote depuis chaque
        sens, et l'ecart des deux mesures est le jeu. Une mesure dans un seul
        sens ne le voit pas du tout, ce qui est la raison pour laquelle un
        controle de position ordinaire passe a cote.
        """
        vals = []
        for _ in range(n_reversals):
            fwd = self._rng.normal(0.0, self.noise_mm)
            rev = true_backlash_mm + self._rng.normal(0.0, self.noise_mm)
            vals.append(rev - fwd)
        v = np.array(vals)
        return ProbeResult(
            name=f"jeu {axis}", value_mm=np.array([float(v.mean())]),
            uncertainty_mm=float(v.std(ddof=1) / np.sqrt(len(v))) if len(v) > 1 else float("inf"),
            n_samples=len(v), accepted=True,
            detail=f"{n_reversals} inversions, dispersion {v.std(ddof=1) if len(v) > 1 else float('nan'):.5f} mm")

    def measure_homing_repeatability(self, *, true_repeatability_mm: float,
                                     n_cycles: int = 10) -> ProbeResult:
        """Dispersion de la prise d'origine sur plusieurs cycles.

        C'est un plancher, pas une correction : une origine qui se reprend a
        0,02 mm pres interdit d'annoncer mieux que 0,02 mm, quelle que soit la
        qualite du reste.
        """
        v = self._rng.normal(0.0, max(true_repeatability_mm, 1e-9), n_cycles)
        return ProbeResult(
            name="repetabilite d'origine", value_mm=np.array([float(v.std(ddof=1))]),
            uncertainty_mm=float(v.std(ddof=1) / np.sqrt(2.0 * (n_cycles - 1))),
            n_samples=n_cycles, accepted=True,
            detail=f"{n_cycles} cycles, etendue {v.max() - v.min():.5f} mm")
