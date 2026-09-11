"""Types geometriques fondamentaux.

Convention unique dans tout le projet :
  - unites : millimetres, degres en entree/sortie utilisateur, RADIANS en interne ;
  - un vecteur d'axe outil ``d`` pointe TOUJOURS du bec de l'outil VERS la broche
    (c'est-a-dire vers l'exterieur de la matiere). C'est l'inverse de la direction
    de coupe. Toute fonction qui recoit un ``d`` suppose cette convention.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

Vec3 = np.ndarray  # shape (3,), float64
EPS = 1e-9


def vec3(x: float, y: float, z: float) -> Vec3:
    return np.array([x, y, z], dtype=np.float64)


def normalize(v: np.ndarray) -> np.ndarray:
    """Normalise un vecteur ou un tableau (N,3) de vecteurs."""
    v = np.asarray(v, dtype=np.float64)
    if v.ndim == 1:
        n = float(np.linalg.norm(v))
        if n < EPS:
            raise ValueError("normalize: vecteur nul")
        return v / n
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    if np.any(n < EPS):
        raise ValueError("normalize: au moins un vecteur nul")
    return v / n


def orthonormal_basis(d: Vec3) -> tuple[Vec3, Vec3, Vec3]:
    """Base orthonormee (u, v, d) avec d comme troisieme axe.

    Choix de ``u`` par l'axe cardinal le moins aligne avec ``d`` : evite la
    degenerescence quand ``d`` est proche d'un axe canonique.
    """
    d = normalize(d)
    a = np.eye(3)[int(np.argmin(np.abs(d)))]
    u = normalize(np.cross(a, d))
    v = np.cross(d, u)
    return u, v, d


def angle_between(a: Vec3, b: Vec3) -> float:
    """Angle non signe entre deux directions, en radians. Numeriquement stable."""
    a, b = normalize(a), normalize(b)
    # atan2(|a x b|, a.b) est stable aux deux extremes, contrairement a acos(a.b).
    return math.atan2(float(np.linalg.norm(np.cross(a, b))), float(np.dot(a, b)))


def wrap_pi(a: float) -> float:
    """Ramene un angle dans (-pi, pi]."""
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def unwrap_towards(target: float, reference: float) -> float:
    """Choisit le representant de ``target`` (mod 2pi) le plus proche de ``reference``.

    Brique centrale du traitement de continuite de l'axe C : sans cela, une
    trajectoire traversant +/-180 deg produit un retournement de plateau.
    """
    return reference + wrap_pi(target - reference)


@dataclass(frozen=True)
class Transform:
    """Transformation rigide : ``p_out = R @ p_in + t``."""

    R: np.ndarray  # (3,3)
    t: np.ndarray  # (3,)

    @staticmethod
    def identity() -> "Transform":
        return Transform(np.eye(3), np.zeros(3))

    @staticmethod
    def translation(t: np.ndarray) -> "Transform":
        return Transform(np.eye(3), np.asarray(t, dtype=np.float64))

    @staticmethod
    def rot_x(a: float) -> "Transform":
        c, s = math.cos(a), math.sin(a)
        return Transform(np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float64), np.zeros(3))

    @staticmethod
    def rot_y(a: float) -> "Transform":
        c, s = math.cos(a), math.sin(a)
        return Transform(np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float64), np.zeros(3))

    @staticmethod
    def rot_z(a: float) -> "Transform":
        c, s = math.cos(a), math.sin(a)
        return Transform(np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float64), np.zeros(3))

    def __matmul__(self, other: "Transform") -> "Transform":
        return Transform(self.R @ other.R, self.R @ other.t + self.t)

    def apply(self, p: np.ndarray) -> np.ndarray:
        """Applique aux points (3,) ou (N,3)."""
        p = np.asarray(p, dtype=np.float64)
        if p.ndim == 1:
            return self.R @ p + self.t
        return p @ self.R.T + self.t

    def apply_vector(self, v: np.ndarray) -> np.ndarray:
        """Applique la rotation seule (directions, normales d'une transfo rigide)."""
        v = np.asarray(v, dtype=np.float64)
        return self.R @ v if v.ndim == 1 else v @ self.R.T

    def inverse(self) -> "Transform":
        Rt = self.R.T
        return Transform(Rt, -Rt @ self.t)


@dataclass(frozen=True)
class AABB:
    """Boite englobante alignee sur les axes."""

    lo: np.ndarray
    hi: np.ndarray

    @staticmethod
    def from_points(pts: np.ndarray) -> "AABB":
        pts = np.asarray(pts, dtype=np.float64).reshape(-1, 3)
        return AABB(pts.min(axis=0), pts.max(axis=0))

    @property
    def size(self) -> np.ndarray:
        return self.hi - self.lo

    @property
    def center(self) -> np.ndarray:
        return 0.5 * (self.lo + self.hi)

    @property
    def diagonal(self) -> float:
        return float(np.linalg.norm(self.size))

    def expanded(self, m: float | np.ndarray) -> "AABB":
        m = np.asarray(m, dtype=np.float64) * np.ones(3)
        return AABB(self.lo - m, self.hi + m)
