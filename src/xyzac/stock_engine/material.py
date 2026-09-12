"""Suivi de la matiere restante. Leve l'hypothese « brut intact » du jalon M1.

Le probleme que cela resout, mesure sur le corpus : avec un brut intact, usiner
une face enterree sous 2 mm de surepaisseur fait declarer la TIGE en collision,
puisqu'elle occupe l'espace que les passes precedentes ont deja vide. Le
solveur rejetait donc des orientations parfaitement saines — 5 points
accessibles sur 20 sur le cas C08.

Representation retenue : grille voxel booleenne de la matiere restante.

Pourquoi le voxel plutot que le dexel : un champ de dexels est indexe par une
direction, et notre outil change d'orientation en permanence. Un dexel Z serait
faux des qu'on bascule le berceau. Le voxel est isotrope, donc indifferent a
l'orientation — c'est exactement la propriete qu'il nous faut en 5 axes.

Cout memoire : a 1 mm de pas, un brut de 100 x 100 x 80 mm tient dans 800 Ko.
A 0,5 mm, 6,4 Mo. Les deux passent sur Raspberry Pi 5.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..geometry_core.voxelize import VoxelGrid, solid_mask
from .stock import Stock


@dataclass
class MaterialState:
    """Etat de la matiere restante a un instant de la gamme."""

    grid: VoxelGrid
    remaining: np.ndarray       # (nx, ny, nz) bool — matiere encore presente
    protected: np.ndarray       # (nx, ny, nz) bool — piece finale + surepaisseur

    @property
    def remaining_volume_mm3(self) -> float:
        return float(self.remaining.sum()) * self.grid.voxel_volume

    @property
    def protected_volume_mm3(self) -> float:
        return float(self.protected.sum()) * self.grid.voxel_volume

    def describe(self) -> str:
        return (f"Matiere : {self.remaining_volume_mm3:.0f} mm3 restants "
                f"(dont {self.protected_volume_mm3:.0f} mm3 de piece protegee), "
                f"grille {self.grid.shape} a {self.grid.pitch} mm")

    # -- construction ------------------------------------------------------

    @staticmethod
    def from_setup(stock: Stock, part_verts: np.ndarray, part_tris: np.ndarray,
                   *, pitch: float = 1.0, finish_allowance: float | None = None
                   ) -> "MaterialState":
        """Brut INTACT, avec la piece finale marquee comme protegee."""
        bb = stock.bbox
        grid = VoxelGrid.covering(bb.lo, bb.hi, pitch, margin=pitch)
        centers = grid.centers()

        remaining = stock.contains(centers).reshape(grid.shape)
        part = solid_mask(part_verts, part_tris, grid)

        allow = stock.finish_allowance_mm if finish_allowance is None else finish_allowance
        if allow > 0.0:
            part = _offset_by_distance(part, allow, grid.pitch)

        # La piece est aussi de la matiere : un brut qui ne contiendrait pas la
        # piece signalerait un montage incoherent, pas une piece a usiner.
        return MaterialState(grid=grid, remaining=remaining | part, protected=part)

    def protect_fixtures(self, setup, *, extra_keepout: float = 0.0) -> int:
        """Marque les BRIDAGES comme matiere protegee. Retourne les voxels ajoutes.

        Defaut trouve en validation, et il etait grave : le slicer ne connait
        que deux choses, la matiere a enlever et la piece a conserver. Les mors
        n'etant ni l'une ni l'autre, il planifiait des passes qui descendent
        jusqu'au fond du brut — c'est-a-dire **dans l'etau**. Le validateur les
        refusait ensuite, a juste titre, avec des penetrations de plusieurs
        millimetres.

        Les traiter comme « protege » est la bonne semantique, et pas seulement
        un raccourci : un bridage ne s'enleve pas, et il bloque la visibilite
        d'une direction exactement comme la piece. Les deux proprietes dont on a
        besoin sont deja celles du masque protege.
        """
        added = 0
        centers = self.grid.centers()
        for f in getattr(setup, "fixtures", []):
            if f.lo is None or f.hi is None:
                continue
            keep = f.keepout_mm + extra_keepout
            lo = np.asarray(f.lo, float) - keep - self.mount_offset_of(setup)
            hi = np.asarray(f.hi, float) + keep - self.mount_offset_of(setup)
            inside = np.all((centers >= lo) & (centers <= hi), axis=1).reshape(self.grid.shape)
            new = inside & ~self.protected
            added += int(new.sum())
            self.protected |= inside
            self.remaining |= inside
        return added

    @staticmethod
    def mount_offset_of(setup) -> np.ndarray:
        """Les bridages sont decrits dans le repere PIECE, comme la grille :
        aucun decalage n'est donc a appliquer. La methode existe pour rendre
        cette hypothese explicite plutot que implicite — si les bridages
        passaient un jour dans le repere du plateau, c'est ici que la conversion
        se ferait."""
        return np.zeros(3)

    # -- enlevement --------------------------------------------------------

    def remove_tool_sweep(self, tcps: np.ndarray, axes: np.ndarray, tool,
                          *, only_cutting: bool = True) -> int:
        """Enleve la matiere balayee par l'outil. Retourne le nombre de voxels.

        La matiere PROTEGEE n'est jamais enlevee, meme si l'outil la traverse
        dans le modele : si c'etait le cas, ce serait une gouge, et le role de
        ce module est de suivre la matiere, pas de masquer un defaut. Le nombre
        de voxels proteges touches est retourne par ``count_gouged_voxels``.

        **Restriction a la boite englobante** : une premiere version testait
        chaque pose contre TOUS les voxels vivants, soit O(poses x voxels). Sur
        une trajectoire d'ebauche de quelques milliers de points et une grille
        de 200 000 voxels, cela ne se terminait pas en un temps utile. L'outil
        n'occupe qu'une boite de quelques centaines de voxels ; on n'indexe
        donc que celle-la.
        """
        tcps = np.asarray(tcps, float).reshape(-1, 3)
        axes = np.asarray(axes, float).reshape(-1, 3)
        axes = axes / np.linalg.norm(axes, axis=1, keepdims=True)

        segs = [s for s in tool.segments
                if (not only_cutting) or s.role.value in ("cutting", "flute")]
        if not segs:
            return 0

        z_hi = max(s.z_end for s in segs)
        r_hi = max(s.r_max for s in segs)
        # Rayon du voxel : on enleve un voxel des que son CENTRE entre dans
        # l'outil. Ne pas compenser sous-estimerait l'enlevement d'un demi-pas.
        vr = 0.5 * self.grid.pitch * np.sqrt(3.0)
        pitch, origin = self.grid.pitch, self.grid.origin
        nx, ny, nz = self.grid.shape
        removed_total = 0

        for i in range(len(tcps)):
            tcp, d = tcps[i], axes[i]
            # Boite englobante du cylindre [0, z_hi] x r_hi autour de l'axe.
            far = tcp + d * z_hi
            lo = np.minimum(tcp, far) - (r_hi + vr)
            hi = np.maximum(tcp, far) + (r_hi + vr)
            i0 = np.maximum(0, np.floor((lo - origin) / pitch).astype(np.int64))
            i1 = np.minimum([nx, ny, nz], np.ceil((hi - origin) / pitch).astype(np.int64) + 1)
            if np.any(i1 <= i0):
                continue

            sub_rem = self.remaining[i0[0]:i1[0], i0[1]:i1[1], i0[2]:i1[2]]
            sub_prot = self.protected[i0[0]:i1[0], i0[1]:i1[1], i0[2]:i1[2]]
            live = sub_rem & ~sub_prot
            if not live.any():
                continue

            loc = np.argwhere(live)
            pts = origin + (loc + i0 + 0.5) * pitch
            v = pts - tcp
            z = v @ d
            r = np.sqrt(np.maximum(np.sum(v * v, axis=1) - z * z, 0.0))

            hit = np.zeros(len(pts), dtype=bool)
            for sg in segs:
                inside = (z >= sg.z_start - vr) & (z <= sg.z_end + vr)
                if not np.any(inside):
                    continue
                t = np.clip((z - sg.z_start) / max(sg.length, 1e-12), 0.0, 1.0)
                r_env = sg.r_start + t * (sg.r_end - sg.r_start)
                hit |= inside & (r <= r_env + vr)

            if not hit.any():
                continue
            cut = loc[hit] + i0
            self.remaining[cut[:, 0], cut[:, 1], cut[:, 2]] = False
            removed_total += int(hit.sum())

        return removed_total

    def count_gouged_voxels(self, tcps: np.ndarray, axes: np.ndarray, tool) -> int:
        """Voxels PROTEGES qu'une passe traverserait. Non nul = gouge."""
        probe = MaterialState(self.grid, self.protected.copy(), np.zeros_like(self.protected))
        return probe.remove_tool_sweep(tcps, axes, tool, only_cutting=True)

    def carve_to_finished(self) -> int:
        """Enleve TOUT ce qui n'est pas la piece protegee.

        Modelise l'etat « ebauche terminee, il ne reste que la surepaisseur ».
        C'est l'hypothese realiste pour calculer l'accessibilite d'une passe de
        FINITION, et elle est explicitement optimiste : elle suppose qu'une
        ebauche a reellement degage la zone. Elle ne doit pas servir a valider
        une gamme complete, seulement a etudier une passe de finition.
        """
        before = int(self.remaining.sum())
        self.remaining = self.protected.copy()
        return before - int(self.remaining.sum())


    # -- visibilite directionnelle ----------------------------------------

    def removable(self) -> np.ndarray:
        """Matiere encore presente qui N'EST PAS la piece a conserver."""
        return self.remaining & ~self.protected

    def reachable_from(self, direction: np.ndarray, *, step_ratio: float = 0.5) -> np.ndarray:
        """Masque des voxels enlevables ATTEIGNABLES depuis ``direction``.

        Un voxel est atteignable si le rayon partant de son centre vers
        ``direction`` (donc vers l'exterieur, sens de retrait de l'outil) sort de
        la grille sans traverser de matiere PROTEGEE.

        Trois choix qui meritent d'etre explicites :

        - la matiere **enlevable** rencontree en chemin ne bloque pas. Elle sera
          partie quand on arrivera la, puisqu'on usine de l'exterieur vers
          l'interieur. Compter le brut comme obstacle declarerait tout
          inaccessible des le premier voxel ;
        - la matiere **protegee** bloque. C'est la piece : passer au travers
          serait une gouge ;
        - la geometrie de l'outil n'intervient PAS ici. C'est deliberé :
          cette fonction repond a « la matiere voit-elle la sortie », question de
          volume, et non a « l'outil complet passe-t-il », question que traite
          l'accessibility solver avec le porte-outil et le nez de broche. Melanger
          les deux rendrait le planificateur a la fois lent et faux.

        C'est donc une borne SUPERIEURE de ce qu'une direction permet d'enlever :
        elle sert a classer des candidats, pas a valider une trajectoire.
        """
        d = np.asarray(direction, dtype=np.float64)
        d = d / np.linalg.norm(d)

        rem = self.removable()
        if not rem.any():
            return np.zeros_like(rem)

        idx = np.argwhere(rem)
        pts = self.grid.origin + (idx + 0.5) * self.grid.pitch

        # Longueur de rayon suffisante pour traverser la grille dans n'importe
        # quelle direction : la diagonale.
        span = np.array(self.grid.shape) * self.grid.pitch
        n_steps = int(np.ceil(float(np.linalg.norm(span)) / (self.grid.pitch * step_ratio)))
        step = d * self.grid.pitch * step_ratio

        blocked = np.zeros(len(pts), dtype=bool)
        cur = pts.copy()
        alive = np.ones(len(pts), dtype=bool)
        prot = self.protected
        nx, ny, nz = self.grid.shape

        for _ in range(n_steps):
            cur[alive] += step
            ijk = np.floor((cur[alive] - self.grid.origin) / self.grid.pitch).astype(np.int64)
            inside = ((ijk[:, 0] >= 0) & (ijk[:, 0] < nx)
                      & (ijk[:, 1] >= 0) & (ijk[:, 1] < ny)
                      & (ijk[:, 2] >= 0) & (ijk[:, 2] < nz))

            alive_idx = np.flatnonzero(alive)
            # Sorti de la grille = sorti de la matiere : le rayon a abouti.
            alive[alive_idx[~inside]] = False

            still = alive_idx[inside]
            if still.size == 0:
                break
            good = ijk[inside]
            hit = prot[good[:, 0], good[:, 1], good[:, 2]]
            blocked[still[hit]] = True
            alive[still[hit]] = False

            if not alive.any():
                break

        out = np.zeros_like(rem)
        keep = idx[~blocked]
        if len(keep):
            out[keep[:, 0], keep[:, 1], keep[:, 2]] = True
        return out

    def reachable_volume_mm3(self, direction: np.ndarray) -> float:
        return float(self.reachable_from(direction).sum()) * self.grid.voxel_volume

    # -- lecture -----------------------------------------------------------

    @staticmethod
    def _skin(mask: np.ndarray) -> np.ndarray:
        """Voxels de ``mask`` touchant un voxel vide. Bord de grille = vide."""
        interior = np.ones_like(mask)
        for ax in range(3):
            interior &= _shift(mask, ax, 1) & _shift(mask, ax, -1)
        return mask & ~interior

    def protected_boundary_points(self) -> tuple[np.ndarray, float]:
        """Peau de la matiere PROTEGEE. C'est elle, l'obstacle « piece ».

        Envoyer tous les voxels proteges au moteur de collision — interieur
        compris — est inutile et coûteux : un point enfoui dans la piece ne sera
        jamais le plus proche de l'outil, mais il est teste comme les autres.
        Mesure sur une poche : 21 622 points contre 5 000 environ pour la seule
        peau, et 4,8 s de validation par couche au lieu d'une fraction de
        seconde.
        """
        idx = np.argwhere(self._skin(self.protected))
        pts = self.grid.origin + (idx + 0.5) * self.grid.pitch
        return pts, float(0.5 * self.grid.pitch * np.sqrt(3.0))

    def boundary_points(self) -> tuple[np.ndarray, float]:
        """Centres des voxels de PEAU + rayon d'inflation conservatif.

        Un voxel est en peau s'il contient de la matiere et touche un voxel
        vide. Le rayon retourne est le demi-diagonal du voxel : c'est ce qui
        garantit que la matiere reelle est entierement couverte par les boules
        centrees sur les centres, donc que le test reste un majorant.
        """
        idx = np.argwhere(self._skin(self.remaining))
        pts = self.grid.origin + (idx + 0.5) * self.grid.pitch
        return pts, float(0.5 * self.grid.pitch * np.sqrt(3.0))


def _shift(a: np.ndarray, axis: int, k: int) -> np.ndarray:
    """Decalage avec bord considere VIDE : la peau inclut donc le bord de
    grille, ce qui est correct — au-dela, on ne sait pas, et l'ignorer
    creerait un trou dans l'enveloppe des obstacles."""
    out = np.zeros_like(a)
    sl_dst = [slice(None)] * 3
    sl_src = [slice(None)] * 3
    if k > 0:
        sl_dst[axis] = slice(k, None)
        sl_src[axis] = slice(None, -k)
    elif k < 0:
        sl_dst[axis] = slice(None, k)
        sl_src[axis] = slice(-k, None)
    else:
        return a.copy()
    out[tuple(sl_dst)] = a[tuple(sl_src)]
    return out


def _offset_by_distance(mask: np.ndarray, distance_mm: float, pitch: float) -> np.ndarray:
    """Offset d'un masque volumique d'une distance METRIQUE.

    Materialise la surepaisseur de finition sans calculer d'offset B-Rep,
    operation lente et fragile sur une geometrie quelconque.

    **Pourquoi pas une dilatation par nombre entier de voxels** : elle quantifie
    la distance au pas de la grille, ce qui rend un parametre UTILISATEUR
    dependant d'un reglage numerique sans rapport. Mesure du defaut avant
    correction — une surepaisseur demandee a 0,2 mm devenait :

        pitch 1,5 mm -> 1,5 mm   (x7,5)
        pitch 1,0 mm -> 1,0 mm   (x5)
        pitch 0,6 mm -> 0,6 mm   (x3)

    L'utilisateur reglait sa finition, et c'etait la resolution du solveur qui
    decidait. La transformee de distance euclidienne, elle, respecte la valeur
    demandee a la resolution de la grille pres — et l'erreur ne depasse jamais
    un demi-voxel au lieu d'un voxel entier arrondi au-dessus.
    """
    if distance_mm <= 0.0 or not mask.any():
        return mask
    from scipy.ndimage import distance_transform_edt

    dist = distance_transform_edt(~mask, sampling=pitch)
    return mask | (dist <= distance_mm)
