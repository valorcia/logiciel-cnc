"""Modele de brut et derivation automatique depuis la piece.

Le brut n'est pas un decor : c'est le domaine de matiere a enlever, et c'est
aussi un OBSTACLE. Une orientation peut etre admissible sur la piece finie et
en collision avec le brut a l'instant t. Le collision engine doit donc pouvoir
raisonner sur l'etat courant de la matiere, pas seulement sur l'etat final.
"""

from __future__ import annotations

from enum import Enum

import numpy as np
from pydantic import BaseModel, Field, model_validator

from ..geometry_core.types import AABB


class StockKind(str, Enum):
    BLOCK = "block"          # brut parallelepipedique
    CYLINDER = "cylinder"    # barre : le cas naturel du tournage sur C
    FROM_STEP = "from_step"  # brut fourni par l'utilisateur (piece brute, moulage)


class Stock(BaseModel):
    """Brut, exprime dans le repere PIECE.

    Tout est en repere piece : c'est le repere dans lequel l'accessibilite est
    calculee. La conversion vers le repere machine depend de (A, C) et de
    l'origine du montage, et releve du ``Setup``.
    """

    kind: StockKind
    # BLOCK
    lo: list[float] | None = None
    hi: list[float] | None = None
    # CYLINDER
    axis_point: list[float] | None = None
    axis_dir: list[float] | None = None
    radius: float | None = None
    length: float | None = None
    # FROM_STEP
    step_path: str | None = None

    material: str = "aluminium-6061"
    #: Surepaisseur laissee sur la piece finie, en mm. Zero = finition directe.
    finish_allowance_mm: float = Field(0.2, ge=0.0)

    @model_validator(mode="after")
    def _check(self) -> "Stock":
        if self.kind is StockKind.BLOCK and (self.lo is None or self.hi is None):
            raise ValueError("Stock BLOCK exige lo et hi")
        if self.kind is StockKind.CYLINDER and (self.radius is None or self.length is None):
            raise ValueError("Stock CYLINDER exige radius et length")
        if self.kind is StockKind.FROM_STEP and not self.step_path:
            raise ValueError("Stock FROM_STEP exige step_path")
        return self

    @property
    def bbox(self) -> AABB:
        if self.kind is StockKind.BLOCK:
            return AABB(np.array(self.lo, dtype=float), np.array(self.hi, dtype=float))
        if self.kind is StockKind.CYLINDER:
            p = np.array(self.axis_point or [0, 0, 0], dtype=float)
            d = np.array(self.axis_dir or [0, 0, 1], dtype=float)
            d = d / np.linalg.norm(d)
            ends = np.vstack([p, p + d * self.length])
            r = abs(self.radius) * np.sqrt(np.maximum(0.0, 1.0 - d**2))
            return AABB((ends - r).min(axis=0), (ends + r).max(axis=0))
        raise NotImplementedError("bbox FROM_STEP : lire le STEP via stock_engine.load_stock_shape")

    def contains(self, pts: np.ndarray) -> np.ndarray:
        """Masque des points situes DANS le brut. Vectorise."""
        pts = np.asarray(pts, dtype=np.float64).reshape(-1, 3)
        if self.kind is StockKind.BLOCK:
            lo, hi = np.array(self.lo), np.array(self.hi)
            return np.all((pts >= lo) & (pts <= hi), axis=1)
        if self.kind is StockKind.CYLINDER:
            p = np.array(self.axis_point or [0, 0, 0], dtype=float)
            d = np.array(self.axis_dir or [0, 0, 1], dtype=float)
            d = d / np.linalg.norm(d)
            v = pts - p
            t = v @ d
            radial = np.linalg.norm(v - np.outer(t, d), axis=1)
            return (t >= 0) & (t <= self.length) & (radial <= self.radius)
        raise NotImplementedError("contains FROM_STEP")

    def surface_samples(self, spacing: float = 2.0) -> tuple[np.ndarray, np.ndarray]:
        """Points + normales sortantes sur la peau du brut, espacement borne.

        Sert d'obstacle au collision engine tant que le suivi de matiere
        enlevee (dexels) n'est pas implemente : a ce jalon, on considere le
        brut INTACT, ce qui est l'hypothese la plus conservative possible.
        """
        if self.kind is StockKind.BLOCK:
            return _box_samples(np.array(self.lo, float), np.array(self.hi, float), spacing)
        if self.kind is StockKind.CYLINDER:
            return _cylinder_samples(
                np.array(self.axis_point or [0, 0, 0], float),
                np.array(self.axis_dir or [0, 0, 1], float),
                float(self.radius), float(self.length), spacing,
            )
        raise NotImplementedError("surface_samples FROM_STEP")


def _box_samples(lo, hi, spacing):
    pts, nrm = [], []
    for ax in range(3):
        u, v = [i for i in range(3) if i != ax]
        nu = max(2, int(np.ceil((hi[u] - lo[u]) / spacing)) + 1)
        nv = max(2, int(np.ceil((hi[v] - lo[v]) / spacing)) + 1)
        gu, gv = np.meshgrid(np.linspace(lo[u], hi[u], nu), np.linspace(lo[v], hi[v], nv))
        for side, val in ((-1.0, lo[ax]), (1.0, hi[ax])):
            p = np.zeros((gu.size, 3))
            p[:, u], p[:, v], p[:, ax] = gu.ravel(), gv.ravel(), val
            n = np.zeros((gu.size, 3)); n[:, ax] = side
            pts.append(p); nrm.append(n)
    return np.vstack(pts), np.vstack(nrm)


def _cylinder_samples(p0, d, radius, length, spacing):
    d = d / np.linalg.norm(d)
    a = np.eye(3)[int(np.argmin(np.abs(d)))]
    u = np.cross(a, d); u /= np.linalg.norm(u)
    v = np.cross(d, u)

    n_theta = max(8, int(np.ceil(2 * np.pi * radius / spacing)))
    n_z = max(2, int(np.ceil(length / spacing)) + 1)
    th = np.linspace(0, 2 * np.pi, n_theta, endpoint=False)
    zz = np.linspace(0, length, n_z)
    T, Z = np.meshgrid(th, zz)
    radial = np.cos(T).ravel()[:, None] * u + np.sin(T).ravel()[:, None] * v
    side_p = p0 + radial * radius + Z.ravel()[:, None] * d

    caps_p, caps_n = [], []
    n_r = max(2, int(np.ceil(radius / spacing)) + 1)
    for zc, sign in ((0.0, -1.0), (length, 1.0)):
        for r in np.linspace(0, radius, n_r):
            nt = max(1, int(np.ceil(2 * np.pi * max(r, 1e-6) / spacing)))
            t = np.linspace(0, 2 * np.pi, nt, endpoint=False)
            rr = np.cos(t)[:, None] * u + np.sin(t)[:, None] * v
            caps_p.append(p0 + rr * r + zc * d)
            caps_n.append(np.tile(sign * d, (nt, 1)))

    return (np.vstack([side_p] + caps_p),
            np.vstack([radial] + caps_n))


def stock_from_part(
    part_bbox: AABB,
    margin_xy: float = 2.0,
    margin_z_top: float = 2.0,
    margin_z_bottom: float = 5.0,
    material: str = "aluminium-6061",
) -> Stock:
    """Derive un brut parallelepipedique depuis la boite de la piece.

    ``margin_z_bottom`` est volontairement plus grand : c'est la zone de
    bridage, celle qui ne sera pas usinee et qui sera tronconnee. La rendre
    egale aux autres marges est l'erreur qui fait usiner dans les mors.
    """
    lo = part_bbox.lo - np.array([margin_xy, margin_xy, margin_z_bottom])
    hi = part_bbox.hi + np.array([margin_xy, margin_xy, margin_z_top])
    return Stock(kind=StockKind.BLOCK, lo=lo.tolist(), hi=hi.tolist(), material=material)


def bar_stock_from_part(part_bbox: AABB, margin_r: float = 2.0, margin_l: float = 5.0,
                        material: str = "aluminium-6061") -> Stock:
    """Derive un brut barre autour de l'axe Z piece — le cas naturel du tournage."""
    r = 0.5 * float(np.hypot(part_bbox.size[0], part_bbox.size[1])) + margin_r
    return Stock(
        kind=StockKind.CYLINDER,
        axis_point=[float(part_bbox.center[0]), float(part_bbox.center[1]),
                    float(part_bbox.lo[2] - margin_l)],
        axis_dir=[0.0, 0.0, 1.0],
        radius=r,
        length=float(part_bbox.size[2] + 2 * margin_l),
        material=material,
    )
