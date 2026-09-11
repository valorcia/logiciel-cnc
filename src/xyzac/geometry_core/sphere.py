"""Discretisation de la sphere des directions S2.

Toute la strategie d'orientation repose sur une question : "quelles directions
d'axe outil sont admissibles ici ?". Cela demande un echantillonnage de S2
quasi uniforme (une grille lat/lon concentrerait les points aux poles, et le
pole est precisement la zone de singularite A -> 0 : on y aurait une resolution
absurde la ou elle ne sert a rien, et une resolution grossiere a l'equateur ou
elle est critique).

On utilise donc une subdivision d'icosaedre : uniformite a ~15 % pres, et un
graphe d'adjacence naturel dont le solveur se sert pour extraire les cones
d'accessibilite par composantes connexes.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from .types import normalize

_PHI = (1.0 + 5.0**0.5) / 2.0


@dataclass(frozen=True)
class SphereGrid:
    """Directions unitaires + adjacence. Immuable et mise en cache."""

    directions: np.ndarray   # (N,3) unitaires
    neighbors: tuple[tuple[int, ...], ...]
    subdivisions: int

    def __len__(self) -> int:
        return int(self.directions.shape[0])

    @property
    def mean_spacing_deg(self) -> float:
        """Ecart angulaire moyen entre voisins : resolution effective de la grille."""
        acc, n = 0.0, 0
        for i, nb in enumerate(self.neighbors):
            for j in nb:
                acc += float(np.degrees(np.arccos(np.clip(
                    self.directions[i] @ self.directions[j], -1, 1))))
                n += 1
        return acc / max(n, 1)

    def restrict(self, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Sous-ensemble des directions verifiant ``mask``. Retourne (indices, directions)."""
        idx = np.flatnonzero(mask)
        return idx, self.directions[idx]

    def connected_components(self, mask: np.ndarray) -> list[np.ndarray]:
        """Composantes connexes des directions admissibles.

        Chaque composante est un CONE D'ACCESSIBILITE : un ensemble d'orientations
        que l'on peut parcourir continument sans jamais traverser une collision.
        Passer d'un cone a un autre impose un degagement — information que le
        planner doit connaitre, et qui serait perdue avec un simple masque.
        """
        mask = np.asarray(mask, dtype=bool)
        seen = np.zeros(len(self), dtype=bool)
        out: list[np.ndarray] = []
        for s in np.flatnonzero(mask):
            if seen[s]:
                continue
            stack, comp = [int(s)], []
            seen[s] = True
            while stack:
                i = stack.pop()
                comp.append(i)
                for j in self.neighbors[i]:
                    if mask[j] and not seen[j]:
                        seen[j] = True
                        stack.append(j)
            out.append(np.array(sorted(comp), dtype=np.int64))
        out.sort(key=len, reverse=True)
        return out


@lru_cache(maxsize=8)
def icosphere(subdivisions: int = 3) -> SphereGrid:
    """Grille icospherique. 0 -> 12 dir, 1 -> 42, 2 -> 162, 3 -> 642, 4 -> 2562.

    Le niveau 3 (642 directions, ~8 deg) est le defaut : assez fin pour decider
    l'accessibilite, assez grossier pour rester temps-interactif. Le raffinement
    fin est fait localement par l'orientation solver, pas globalement ici.
    """
    verts = np.array([
        [-1, _PHI, 0], [1, _PHI, 0], [-1, -_PHI, 0], [1, -_PHI, 0],
        [0, -1, _PHI], [0, 1, _PHI], [0, -1, -_PHI], [0, 1, -_PHI],
        [_PHI, 0, -1], [_PHI, 0, 1], [-_PHI, 0, -1], [-_PHI, 0, 1],
    ], dtype=np.float64)
    verts = normalize(verts)
    faces = np.array([
        [0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11],
        [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
        [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9],
        [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1],
    ], dtype=np.int64)

    for _ in range(int(subdivisions)):
        verts, faces = _subdivide(verts, faces)

    nb: list[set[int]] = [set() for _ in range(len(verts))]
    for a, b, c in faces:
        nb[a] |= {int(b), int(c)}
        nb[b] |= {int(a), int(c)}
        nb[c] |= {int(a), int(b)}

    return SphereGrid(
        directions=verts,
        neighbors=tuple(tuple(sorted(s)) for s in nb),
        subdivisions=int(subdivisions),
    )


def _subdivide(verts: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    vlist = [v for v in verts]
    cache: dict[tuple[int, int], int] = {}

    def mid(a: int, b: int) -> int:
        key = (min(a, b), max(a, b))
        if key not in cache:
            m = normalize(vlist[a] + vlist[b])
            cache[key] = len(vlist)
            vlist.append(m)
        return cache[key]

    new_faces = []
    for a, b, c in faces:
        ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
        new_faces += [[a, ab, ca], [b, bc, ab], [c, ca, bc], [ab, bc, ca]]
    return np.array(vlist, dtype=np.float64), np.array(new_faces, dtype=np.int64)


def local_refine(center: np.ndarray, half_angle_deg: float, n_rings: int = 4,
                 n_per_ring: int = 12) -> np.ndarray:
    """Directions finement reparties dans un cone autour de ``center``.

    Sert au raffinement de l'orientation solver : on ne raffine pas toute la
    sphere, seulement le voisinage de la solution retenue par la DP.
    """
    from .types import orthonormal_basis

    u, v, d = orthonormal_basis(center)
    out = [d]
    for k in range(1, n_rings + 1):
        a = np.radians(half_angle_deg) * k / n_rings
        for t in np.linspace(0, 2 * np.pi, n_per_ring, endpoint=False):
            out.append(np.cos(a) * d + np.sin(a) * (np.cos(t) * u + np.sin(t) * v))
    return normalize(np.array(out))
