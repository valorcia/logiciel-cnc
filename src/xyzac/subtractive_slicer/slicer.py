"""Slicer soustractif : decoupe du volume ``brut \\ piece`` en couches usinables.

C'est l'analogue soustractif du slicing additif, et l'analogie s'arrete tot — il
vaut mieux le dire que de la filer. En additif la couche est DEPOSEE et rien ne
s'oppose a la buse ; en soustractif la couche est ENLEVEE, l'outil doit y entrer,
et son corps doit y tenir. Une couche n'est donc pas une tranche geometrique,
c'est une tranche ACCESSIBLE.

Principe retenu, pour une direction d'indexation ``d`` donnee :

  1. on se place dans le repere ou ``d`` devient ``+Z`` (repere indexe) ;
  2. on tranche la matiere enlevable en couches perpendiculaires a ``d`` ;
  3. pour chaque couche, on calcule la region 2D des positions de CENTRE d'outil
     admissibles, puis on la couvre par un zigzag.

Le point qui n'a rien d'evident et qui gouverne toute la justesse du resultat :
la region interdite d'une couche n'est pas la projection de la piece a CETTE
cote, mais sa projection **depuis cette cote jusqu'au sommet**. L'outil monte
vers la broche ; tout ce qui est protege au-dessus du plan de coupe est sur son
chemin. Ne projeter que la couche courante ferait plonger l'outil dans une
contre-depouille des la premiere passe.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..geometry_core.types import normalize, orthonormal_basis
from ..stock_engine.material import MaterialState
from ..tool_model.assembly import ToolAssembly


@dataclass
class LayerToolpath:
    """Une couche de matiere a enlever, et le chemin qui la couvre."""

    index: int
    depth_from_top: float          # mm sous la surface, dans le repere indexe
    polylines: list[np.ndarray] = field(default_factory=list)  # (N,3) repere PIECE
    target_area_mm2: float = 0.0
    covered_area_mm2: float = 0.0

    @property
    def n_points(self) -> int:
        return int(sum(len(p) for p in self.polylines))

    @property
    def coverage(self) -> float:
        return self.covered_area_mm2 / self.target_area_mm2 if self.target_area_mm2 else 1.0


@dataclass
class SliceResult:
    """Resultat du tranchage pour UNE direction d'indexation."""

    direction: np.ndarray
    layers: list[LayerToolpath] = field(default_factory=list)
    layer_thickness: float = 0.0
    stepover: float = 0.0
    reachable_mm3: float = 0.0
    uncovered_mm3: float = 0.0
    #: Cote du plan de degagement dans le repere INDEXE. Les liaisons entre
    #: passes s'y effectuent.
    clearance_z: float = 0.0
    #: Rotation repere piece -> repere indexe, conservee pour reconstruire le
    #: chemin continu sans avoir a la recalculer.
    frame: np.ndarray = field(default_factory=lambda: np.eye(3))
    #: Marge de securite employee. La validation verifie qu'elle correspond a la
    #: sienne : deux modeles conservatifs qui ne partagent pas leurs marges
    #: divergent, et c'est le validateur qui refuse.
    safety_clearance: float = 0.0
    #: Sens de balayage employe. Porte par le resultat et non seulement passe
    #: en argument : un chemin dont on ne sait pas dans quel sens il a ete
    #: genere n'est pas auditable, et le sens de coupe se relit sur la piece.
    balayage: str = "zigzag"

    @property
    def n_points(self) -> int:
        return int(sum(l.n_points for l in self.layers))

    @property
    def coverage(self) -> float:
        """Part du volume atteignable balayee par les passes.

        **A lire avec precaution** : cet indicateur est structurellement < 1, et
        une valeur basse n'est pas forcement mauvaise. Il melange deux choses
        tres differentes :

        - la matiere que l'outil ne peut PAS atteindre (angles rentrants plus
          petits que son rayon) — un vrai probleme, qui se corrige par un outil
          plus fin ;
        - la matiere volontairement LAISSEE le long des parois — le rayon de
          l'outil plus la marge de discretisation — que la passe de finition
          enlevera. Ce n'est pas un defaut, c'est le principe de l'ebauche.

        L'indicateur qui tranche entre les deux est ``simulate_removal``, qui
        mesure la surepaisseur REELLEMENT restante apres passage de l'outil.
        """
        if self.reachable_mm3 <= 0:
            return 1.0
        return max(0.0, 1.0 - self.uncovered_mm3 / self.reachable_mm3)

    def describe(self) -> str:
        return (f"Tranchage selon {np.round(self.direction, 3)} : "
                f"{len(self.layers)} couches, {self.n_points} points, "
                f"balayage {self.coverage * 100:.1f} % du volume atteignable")


def indexed_frame(direction: np.ndarray) -> np.ndarray:
    """Rotation ``R`` telle que ``R @ direction = +Z``.

    Les lignes de R sont la base (u, v, d) : travailler dans ce repere ramene le
    probleme 5 axes indexe a un probleme 3 axes classique, ou tout le savoir-faire
    du fraisage en Z s'applique tel quel.
    """
    u, v, d = orthonormal_basis(direction)
    return np.stack([u, v, d], axis=0)


def _disc(radius_px: float) -> np.ndarray:
    """Element structurant circulaire (et non losange).

    Une dilatation 4-connexe repetee ``n`` fois donne la boule L1 de rayon ``n``,
    c'est-a-dire un LOSANGE strictement PLUS PETIT que le disque euclidien dans
    les diagonales (dx = dy = 2 est a 2,83 du centre, donc dans le disque de
    rayon 3, mais a 4 en L1, donc hors du losange).

    La distinction n'est pas cosmetique : appliquee a la zone interdite, elle
    autoriserait des positions d'outil qui gougent reellement la piece. Le
    raccourci va dans le mauvais sens, on ne le prend pas.
    """
    r = int(np.ceil(radius_px))
    if r <= 0:
        return np.ones((1, 1), dtype=bool)
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return (x * x + y * y) <= radius_px * radius_px


def _dilate2d(mask: np.ndarray, radius_px: float) -> np.ndarray:
    """Dilatation 2D par un disque exact."""
    if radius_px <= 0 or not mask.any():
        return mask
    from scipy.ndimage import binary_dilation

    return binary_dilation(mask, structure=_disc(radius_px))


def _segment_stays_inside(region: np.ndarray, a_px: tuple[float, float],
                          b_px: tuple[float, float]) -> bool:
    """Le segment [a, b] reste-t-il dans la region valide ? (en coordonnees pixel)

    Echantillonne au demi-pixel : plus fin ne changerait rien, la region etant
    elle-meme definie a la cellule pres.
    """
    ny, nx = region.shape
    n = int(np.ceil(2.0 * max(abs(b_px[0] - a_px[0]), abs(b_px[1] - a_px[1])))) + 1
    xs = np.linspace(a_px[0], b_px[0], n)
    ys = np.linspace(a_px[1], b_px[1], n)
    ix = np.clip(np.round(xs).astype(int), 0, nx - 1)
    iy = np.clip(np.round(ys).astype(int), 0, ny - 1)
    return bool(region[iy, ix].all())


#: Les deux sens de balayage possibles, nommes.
#:
#: Defaut signale par l'utilisateur : « attention au sens de l'attaque de
#: l'outil ». Mesure sur une ebauche du corpus, avant toute correction :
#: 4 634 segments de coupe dans un sens et 4 634 dans l'autre — exactement
#: moitie-moitie, parce que le zigzag inverse chaque rangee. En fraisage cela
#: signifie alterner l'avalant et l'opposition a chaque passe, ce qui change
#: l'effort, l'etat de surface et le cote de la bavure.
#:
#: Le defaut n'etait pas l'alternance — c'est un choix defendable en ebauche —
#: mais le fait que PERSONNE ne l'ait choisie : aucun parametre, aucune trace,
#: aucune validation. Le mode est donc desormais nomme, transmis, et ECRIT
#: dans les notes de l'operation, donc auditable.
#: Nombre maximal d'allers-retours d'une rampe d'entree.
#:
#: Une rampe descend de ``standoff`` mm en restant sous l'angle que l'outil
#: declare. Quand le premier segment de coupe est court, il faut plusieurs
#: allers-retours ; au-dela de cette borne, le segment est trop court pour
#: qu'une rampe ait un sens et le cas est refuse plutot que resolu en silence.
RAMPE_MAX_ALLERS = 40

BALAYAGE_ALTERNE = "zigzag"
BALAYAGE_UNIDIRECTIONNEL = "unidirectionnel"
BALAYAGES = (BALAYAGE_ALTERNE, BALAYAGE_UNIDIRECTIONNEL)


def _zigzag(region: np.ndarray, pitch: float, stepover: float,
            origin_xy: np.ndarray, *,
            balayage: str = BALAYAGE_ALTERNE) -> list[np.ndarray]:
    """Couvre une region 2D par des passes CHAINEES.

    ``balayage`` decide du SENS de coupe :

      - ``"zigzag"`` inverse une rangee sur deux. Peu de remontees, mais
        l'avalant et l'opposition alternent a chaque passe ;
      - ``"unidirectionnel"`` parcourt toutes les rangees dans le meme sens,
        donc un effort de coupe constant — au prix d'une remontee au plan de
        degagement par rangee, puisque le retour a vide ne peut pas se faire
        a la profondeur de coupe (il traverserait la matiere de la rangee
        suivante).

    Choix du zigzag plutot que du contour-parallele a ce jalon : il est robuste
    a toute topologie (trous, regions multiples), il n'exige aucun offset de
    polygone, et son comportement est previsible. Le contour-parallele donne un
    meilleur etat de surface et une charge d'outil plus reguliere — il releve de
    la finition, pas de l'ebauche.

    **Les rangees sont chainees quand c'est sûr.** Une premiere version emettait
    des segments independants ; chaque changement de rangee imposait alors une
    remontee au plan de degagement, soit 36 869 points de liaison pour 2 200
    points de coupe — 94 % du programme passe a monter et descendre. On relie
    donc deux rangees successives a la profondeur de coupe des que le trajet
    reste dans la region valide, et on ne remonte que lorsqu'il en sort.
    """
    if balayage not in BALAYAGES:
        raise ValueError(f"balayage inconnu : {balayage!r}")
    alterne = balayage == BALAYAGE_ALTERNE
    ny, nx = region.shape
    row_step = max(1, int(round(stepover / pitch)))
    chains: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    last_px: tuple[float, float] | None = None
    flip = False

    for j in range(0, ny, row_step):
        row = region[j]
        if not row.any():
            continue
        padded = np.concatenate(([False], row, [False]))
        edges = np.flatnonzero(padded[1:] != padded[:-1])
        runs = []
        for k in range(0, len(edges), 2):
            i0, i1 = int(edges[k]), int(edges[k + 1]) - 1
            if i1 >= i0:
                runs.append((i1, i0) if flip else (i0, i1))
        if flip:
            runs.reverse()

        for i_start, i_end in runs:
            a_px = (float(i_start), float(j))
            b_px = (float(i_end), float(j))
            if last_px is not None and _segment_stays_inside(region, last_px, a_px):
                current.append(a_px)
            else:
                if len(current) >= 2:
                    chains.append(current)
                current = [a_px]
            current.append(b_px)
            last_px = b_px
        if alterne:
            flip = not flip
        else:
            # Sans alternance, le retour a vide partirait de la fin d'une
            # rangee vers le debut de la suivante en traversant toute la
            # largeur — a la profondeur de coupe, donc DANS la matiere. On
            # coupe la chaine : ``continuous_path`` reliera les deux rangees
            # par le plan de degagement, avec son approche en avance.
            if len(current) >= 2:
                chains.append(current)
            current = []
            last_px = None

    if len(current) >= 2:
        chains.append(current)

    out = []
    for ch in chains:
        arr = np.array(ch, dtype=np.float64)
        xy = np.column_stack([origin_xy[0] + (arr[:, 0] + 0.5) * pitch,
                              origin_xy[1] + (arr[:, 1] + 0.5) * pitch])
        out.append(xy)
    return out


def slice_for_direction(
    material: MaterialState,
    direction: np.ndarray,
    tool: ToolAssembly,
    *,
    layer_thickness: float = 1.0,
    stepover_ratio: float = 0.45,
    grid_pitch: float | None = None,
    max_layers: int = 200,
    safety_clearance: float = 0.3,
    balayage: str = BALAYAGE_ALTERNE,
) -> SliceResult:
    """Tranche la matiere enlevable atteignable depuis ``direction``.

    ``stepover_ratio`` est la fraction du diametre entre deux passes. 0,45 est
    un point de depart prudent pour l'aluminium ; il n'est PAS qualifie sur
    machine (voir ``recipe_profiles``).

    ``safety_clearance`` DOIT valoir celle du champ d'obstacles qui servira a la
    validation. Le slicer et le collision engine sont deux modeles conservatifs
    independants ; s'ils ne partent pas des memes marges, ils divergent sur une
    frange de positions, et le validateur refuse des trajectoires que le slicer
    croyait sûres. Mesure de cette divergence avant correction : une pose sur
    270, pour 0,226 mm — soit exactement l'ecart de marge entre les deux.

    Faire du slicer le plus conservatif des deux est le bon sens d'arrondi : il
    perd un peu de matiere, la ou l'inverse produirait un plan refuse en aval.
    """
    d = normalize(direction)
    R = indexed_frame(d)

    reach = material.reachable_from(d)
    result = SliceResult(direction=d, layer_thickness=layer_thickness,
                         stepover=tool.diameter * stepover_ratio,
                         safety_clearance=safety_clearance, balayage=balayage,
                         reachable_mm3=float(reach.sum()) * material.grid.voxel_volume)
    if not reach.any():
        return result

    pitch = grid_pitch or material.grid.pitch
    # Centres des voxels enlevables atteignables et proteges, vus dans le repere
    # indexe. On resample plutot que de trancher obliquement la grille d'origine :
    # une tranche oblique d'une grille cartesienne a des bords en escalier dont
    # l'epaisseur depend de l'angle, ce qui rendrait la couche non reproductible.
    centers = material.grid.centers().reshape(material.grid.shape + (3,))
    rem_pts = centers[reach] @ R.T
    prot_pts = centers[material.protected] @ R.T if material.protected.any() else np.zeros((0, 3))

    lo = rem_pts.min(axis=0)
    hi = rem_pts.max(axis=0)
    if prot_pts.size:
        lo = np.minimum(lo, prot_pts.min(axis=0))
        hi = np.maximum(hi, prot_pts.max(axis=0))

    # La grille doit deborder du brut d'un rayon d'outil, et non d'un pas.
    #
    # Pour profiler un flanc, le CENTRE de l'outil se trouve a l'exterieur de la
    # matiere — a plus d'un rayon de la piece, donc souvent hors du brut. Une
    # grille calee sur l'etendue de la matiere n'a tout simplement pas de
    # cellule ou poser ce centre, et le flanc reste intact.
    #
    # Mesure du defaut avant correction, sur un simple pave : les 8 000 mm3 de
    # surepaisseur laterale n'etaient jamais touches, faute de cellules pour
    # accueillir les positions valides.
    pad = tool.radius + 2.0 * pitch
    lo = lo - pad
    hi = hi + pad

    nx = max(1, int(np.ceil((hi[0] - lo[0]) / pitch)) + 1)
    ny = max(1, int(np.ceil((hi[1] - lo[1]) / pitch)) + 1)

    def rasterize(pts: np.ndarray, z0: float, z1: float) -> np.ndarray:
        """Masque 2D (ny, nx) des points dont la cote est dans [z0, z1)."""
        m = np.zeros((ny, nx), dtype=bool)
        if pts.size == 0:
            return m
        sel = (pts[:, 2] >= z0) & (pts[:, 2] < z1)
        if not np.any(sel):
            return m
        ij = np.floor((pts[sel, :2] - lo[:2]) / pitch).astype(np.int64)
        ij[:, 0] = np.clip(ij[:, 0], 0, nx - 1)
        ij[:, 1] = np.clip(ij[:, 1], 0, ny - 1)
        m[ij[:, 1], ij[:, 0]] = True
        return m

    z_top, z_bot = hi[2], lo[2]
    n_layers = min(max_layers, max(1, int(np.ceil((z_top - z_bot) / layer_thickness))))

    # Asymetrie deliberee des deux rayons : on SURESTIME le danger et on
    # SOUS-ESTIME le benefice.
    #
    # ``voxel_margin`` est la demi-diagonale du voxel — exactement l'inflation
    # qu'emploie ``MaterialState.remove_tool_sweep`` pour decider qu'un voxel est
    # touche. Prendre ici une marge PLUS FAIBLE creerait une fenetre ou le
    # slicer autorise une position que le verificateur de gouge signale ensuite.
    # C'est ce qui se produisait avant correction : 422 voxels proteges touches
    # par une trajectoire pourtant issue de la region « valide ».
    # La marge du slicer reprend celle du champ d'obstacles, plus la clearance
    # de securite : c'est ce qui garantit qu'il ne propose pas une position que
    # le validateur refusera.
    voxel_margin = 0.5 * pitch * np.sqrt(3.0) + safety_clearance

    # Deuxieme marge, sur la CELLULE DE POSITION cette fois, et il faut les deux.
    #
    # Une dilatation de rayon R sur une grille ne marque que les cellules dont
    # le CENTRE est a moins de R. Or un centre d'outil peut se trouver n'importe
    # ou dans sa cellule : une cellule dont le centre est a 4 pas d'un voxel
    # protege a son bord a 3,5. Avec R = 3,87, la cellule est declaree libre et
    # l'outil gouge malgre tout.
    #
    # C'est exactement le defaut mesure avant correction : 108 poses sur 3428
    # touchaient la paroi de la poche, toutes a une distance comprise entre
    # R - 0,5 et R. On ajoute donc la demi-diagonale de cellule 2D.
    cell_margin_px = 0.5 * np.sqrt(2.0)
    r_forbid_px = (tool.radius + voxel_margin) / pitch + cell_margin_px

    # TROIS rayons, et non deux : « ou l'outil peut-il aller », « ou est-il
    # utile », et « qu'a-t-il reellement enleve » ne demandent pas le meme sens
    # d'arrondi.
    #
    #  - interdit : majore   (une position douteuse est refusee)
    #  - utile    : majore   (une position qui effleure la matiere est gardee ;
    #                         au pire on fait un mouvement pour rien)
    #  - couvert  : minore   (on ne se cree pas de couverture fictive)
    #
    # Les confondre a un coût mesurable : en prenant le rayon MINORE pour la
    # zone utile, la surepaisseur exterieure de 2 mm devenait inatteignable —
    # l'outil aurait du se placer a 3,9 mm de la piece, donc hors du brut, et
    # une position hors du brut etait jugee « inutile ». La moitie de la matiere
    # restait en place.
    r_useful_px = (tool.radius + voxel_margin) / pitch + cell_margin_px
    r_covered_px = max(0.0, (tool.radius - voxel_margin) / pitch - cell_margin_px)

    # Projection cumulee de la matiere protegee DEPUIS LE SOMMET. C'est le point
    # cle : l'outil monte vers la broche, donc tout ce qui est protege au-dessus
    # du plan de coupe est sur son chemin.
    forbidden_above = np.zeros((ny, nx), dtype=bool)
    Rt = R.T
    cell_area = pitch * pitch
    uncovered_px = 0

    for k in range(n_layers):
        z1 = z_top - k * layer_thickness
        z0 = z1 - layer_thickness

        # Le bord bas est etendu de ``voxel_margin`` pour la meme raison : un
        # voxel protege dont le centre tombe juste sous le plan de coupe a son
        # corps AU-DESSUS de ce plan, donc sur le chemin de l'outil.
        forbidden_above |= rasterize(prot_pts, z0 - voxel_margin, z1 + 1e-9)
        target = rasterize(rem_pts, z0, z1 + 1e-9)
        if not target.any():
            continue

        # Positions de centre d'outil qui ne gouge pas ce qui est protege.
        valid = ~_dilate2d(forbidden_above, r_forbid_px)
        # Positions utiles : le disque de l'outil y rencontre de la matiere cible.
        useful = _dilate2d(target, r_useful_px)
        region = valid & useful
        if not region.any():
            uncovered_px += int(target.sum())
            continue

        polys2d = _zigzag(region, pitch, result.stepover, lo[:2],
                          balayage=balayage)
        if not polys2d:
            uncovered_px += int(target.sum())
            continue

        z_cut = z0
        polylines = []
        for seg in polys2d:
            pts3 = np.column_stack([seg, np.full(len(seg), z_cut)])
            polylines.append(pts3 @ Rt.T)  # retour au repere PIECE

        covered = (_dilate2d(region, r_covered_px) & target).sum()
        uncovered_px += int(target.sum() - covered)

        result.layers.append(LayerToolpath(
            index=k, depth_from_top=z_top - z_cut, polylines=polylines,
            target_area_mm2=float(target.sum()) * cell_area,
            covered_area_mm2=float(covered) * cell_area,
        ))

    result.uncovered_mm3 = float(uncovered_px) * cell_area * layer_thickness
    result.frame = R
    # Plan de degagement : au-dessus de TOUTE la matiere vue dans ce repere,
    # plus une garde. Un degagement cale sur la couche courante suffirait pour
    # elle et percuterait la matiere restee en place ailleurs.
    result.clearance_z = float(z_top) + max(2.0, layer_thickness)
    return result


def _resample(a: np.ndarray, b: np.ndarray, spacing: float) -> np.ndarray:
    n = max(2, int(np.ceil(float(np.linalg.norm(b - a)) / spacing)) + 1)
    t = np.linspace(0.0, 1.0, n)[:, None]
    return a[None, :] * (1 - t) + b[None, :] * t


def _entree_en_matiere(p_index: np.ndarray, standoff: float,
                       tool: ToolAssembly | None,
                       journal: list | None = None) -> np.ndarray:
    """Points d'entree en matiere, du palier d'approche au point de coupe.

    Rend les points dans le repere INDEXE, le dernier etant exactement le
    premier point de coupe a sa profondeur. Tous se parcourent en avance
    travail : c'est l'appelant qui pose les drapeaux.

    ``journal``, s'il est fourni, recoit une ligne par passe ou la rampe n'a
    pas pu etre construite. Un compte plutot qu'une exception : ces passes
    existent reellement — mesure sur le corpus — et refuser toute la gamme
    pour l'une d'elles serait disproportionne. Mais les resoudre en silence
    serait pire : le planner ecrit le compte dans les notes de l'operation.
    """
    start = p_index[0]
    if tool is None or tool.can_plunge:
        # Plongee en AVANCE : legitime pour un outil qui le declare (une
        # hemispherique coupe au centre).
        return np.array([start])

    angle = float(tool.max_ramp_angle_deg)
    if angle <= 0.0:
        raise ValueError(
            f"outil {tool.tool_id} : can_plunge=False et "
            f"max_ramp_angle_deg={angle} — il ne peut ni plonger ni ramper, "
            f"donc il ne peut pas entrer en matiere. Corriger la description "
            f"de l'outil.")

    # Le PREMIER POINT DISTINCT, et non ``p_index[1]`` : mesure sur le corpus,
    # des passes commencent par deux points confondus, et prendre l'indice 1
    # donnait une direction de rampe nulle.
    u = None
    for q in p_index[1:]:
        v = q - start
        if float(np.linalg.norm(v)) > 1e-9:
            u = v
            break
    if u is None:
        if journal is not None:
            journal.append("passe reduite a un point : entree en plongee")
        return np.array([start])
    longueur = float(np.linalg.norm(u))
    u = u / longueur
    # On reste sur les neuf dixiemes du segment : ramper jusqu'a son extremite
    # exacte ferait coincider le point de retournement avec un point de coupe,
    # et deux points confondus a des profondeurs differentes decrivent un
    # mouvement vertical — precisement ce qu'on evite.
    portee = 0.9 * longueur
    descente_par_aller = portee * math.tan(math.radians(angle))
    n = max(2, int(math.ceil(standoff / max(descente_par_aller, 1e-12))))
    if n % 2:
        n += 1                      # pair : on revient sur ``start``
    if n > RAMPE_MAX_ALLERS:
        if journal is not None:
            journal.append(
                f"segment de {longueur:.2f} mm trop court pour une rampe a "
                f"{angle:.0f} deg ({n} allers-retours) : entree en plongee")
        return np.array([start])

    pts = []
    for k in range(n + 1):
        loin = (k % 2) == 1
        p = start + (portee * u if loin else 0.0)
        p = np.asarray(p, dtype=float).copy()
        p[2] = start[2] + standoff * (1.0 - k / n)
        pts.append(p)
    return np.array(pts)


def continuous_path(result: SliceResult, point_spacing: float = 2.0,
                    layers: list[LayerToolpath] | None = None,
                    *, standoff_mm: float | None = None,
                    tool: ToolAssembly | None = None,
                    journal: list | None = None
                    ) -> tuple[np.ndarray, np.ndarray]:
    """Chemin CONTINU d'une operation : passes de coupe ET liaisons.

    Defaut trouve a la validation, et il etait grave : le zigzag produit des
    segments de coupe independants, et tout ce qui les relie etait implicite. Le
    validateur, lui, reliait les extremites en ligne droite — et cette droite
    traverse la matiere entre deux rangees. Le balayage signalait donc des
    collisions bien reelles : la trajectoire, telle qu'elle etait decrite,
    passait effectivement dans la piece.

    Un chemin d'usinage n'est pas une suite de segments de coupe. Entre deux
    passes il faut REMONTER au plan de degagement, se deplacer, puis replonger.
    C'est ce que fait cette fonction, et c'est pour cela qu'elle remplace
    l'ancien reechantillonnage naif.

    **Chaque passe est ABORDEE en avance travail**, jamais en rapide.

    Defaut signale par l'utilisateur — « attention au sens de l'attaque de
    l'outil » — puis mesure : sur une ebauche du corpus, 1 615 passes sur
    1 615 arrivaient a la profondeur de coupe par une descente verticale EN
    RAPIDE, s'arretant exactement sur le premier point de coupe, sans aucune
    marge.

    Le plus instructif est que la regle etait deja ecrite dans ce fichier.
    ``with_approach_retract`` dit, mot pour mot : « un rapide qui finit
    exactement sur la surface n'a aucune marge pour une erreur d'origine
    palpee, et c'est le mouvement qui casse les outils ». Elle etait appliquee
    UNE fois — au tout premier point de l'operation — et les liaisons entre
    passes, qui sont des centaines, l'ignoraient. Un principe juste applique
    une fois sur mille n'est pas un principe, c'est une exception.

    La liaison compte donc cinq sommets au lieu de trois :

      1. ``sortie``  — on quitte la matiere de ``standoff`` mm EN AVANCE ;
      2. ``up``      — rapide jusqu'au plan de degagement ;
      3. ``over``    — rapide au-dessus du point de depart suivant ;
      4. ``haut``    — rapide jusqu'a ``standoff`` mm au-dessus de lui ;
      5. ``start``   — **AVANCE TRAVAIL** jusqu'au point de coupe.

    Un drapeau de rapide decrit le mouvement qui ARRIVE sur son point : c'est
    la convention de ``with_approach_retract``, et la respecter est ce qui
    fait que le dernier segment se parcourt en avance.

    **Et l'entree est une RAMPE quand l'outil declare ne pas savoir plonger.**

    Second defaut, trouve en ecrivant le test du premier : ``ToolAssembly``
    porte depuis le debut ``can_plunge`` et ``max_ramp_angle_deg`` — et
    personne ne les lisait. Une recherche sur tout le code source ne trouvait
    aucune lecture de ces deux champs hors du module qui les definit. Le
    slicer produisait donc des plongees avec une fraise a trois dents, qui
    declare ``can_plunge = False``, c'est-a-dire un mouvement que l'outil dit
    lui-meme ne pas pouvoir executer. Une donnee juste, presente, et ignoree
    est pire qu'une donnee absente : on croit l'avoir prise en compte.

    Quand ``tool.can_plunge`` est faux, l'entree devient une rampe en
    ALLERS-RETOURS sur le premier segment de coupe, sous l'angle que l'outil
    declare. Les allers-retours plutot qu'une descente oblique unique : une
    rampe oblique arriverait a la profondeur APRES le point de depart, et
    laisserait derriere elle un coin de matiere que ``simulate_removal`` ne
    compte pas — le volume enleve rapporte deviendrait optimiste, et c'est
    exactement le genre de silence que ce projet refuse. Les allers-retours
    reviennent sur le point de depart a la profondeur voulue, en ayant
    degage ce coin au passage : rien ne reste, et la mesure de matiere
    enlevee reste juste.

    Retourne ``(points, is_rapid)``. Les points rapides ne coupent pas, mais ils
    doivent evidemment rester sans collision : ils sont valides comme les autres.
    """
    R = np.asarray(result.frame, float)
    d = normalize(result.direction)
    zc = float(result.clearance_z)
    # Hauteur a partir de laquelle on ralentit. Reprise de la marge de
    # securite du tranchage, pour que les deux modeles conservatifs partagent
    # la meme, et jamais nulle : a zero il n'y a plus de marge du tout, ce qui
    # est precisement le defaut corrige ici.
    so = float(standoff_mm) if standoff_mm is not None else max(
        float(result.safety_clearance), 1.0)
    so = max(so, 1e-3)

    def to_part(p_index: np.ndarray) -> np.ndarray:
        return np.asarray(p_index, float) @ R

    chunks: list[np.ndarray] = []
    rapid: list[np.ndarray] = []
    prev_end_index: np.ndarray | None = None

    for layer in (result.layers if layers is None else layers):
        for poly in layer.polylines:
            p_index = np.asarray(poly, float) @ R.T   # repere PIECE -> INDEXE
            start, end = p_index[0], p_index[-1]

            if prev_end_index is not None:
                # Liaisons : on emet les SOMMETS, pas un echantillonnage dense.
                #
                # Une liaison est une droite dans le vide ; la densifier au pas
                # des points de coupe gonflait le programme sans rien apporter
                # (86 % des points pour 0 % de la matiere enlevee). La
                # subdivision d'un segment est le travail du verificateur de
                # balayage, qui la calcule sur une borne prouvee du deplacement
                # — et la fait donc mieux, et seulement quand il le faut.
                sortie = prev_end_index.copy(); sortie[2] += so
                up = prev_end_index.copy(); up[2] = max(zc, sortie[2])
                over = start.copy(); over[2] = up[2]
                haut = start.copy(); haut[2] += so
                if haut[2] > over[2]:
                    over[2] = haut[2]
                    up[2] = haut[2]
                link = np.array([sortie, up, over, haut])
                # Un drapeau decrit le mouvement qui ARRIVE sur son point :
                # la sortie de matiere est donc en AVANCE, le reste en rapide.
                drapeaux = np.array([False, True, True, True])
                keep = [0] + [k for k in range(1, len(link))
                              if np.linalg.norm(link[k] - link[k - 1]) > 1e-9]
                seg = link[keep]
                chunks.append(to_part(seg))
                rapid.append(drapeaux[keep])

                # L'entree en matiere : rampe si l'outil ne sait pas plonger,
                # descente en avance sinon. Dans les deux cas on FINIT sur
                # ``start`` a la profondeur de coupe, en avance travail.
                entree = _entree_en_matiere(p_index, so, tool, journal)
                chunks.append(to_part(entree))
                rapid.append(np.zeros(len(entree), dtype=bool))

            else:
                # La toute premiere passe de l'operation entre en matiere
                # exactement comme les autres. ``with_approach_retract``
                # amenera ensuite l'outil au-dessus du premier point de ces
                # mouvements, qui est deja a distance de la matiere.
                entree = _entree_en_matiere(p_index, so, tool, journal)
                if len(entree) > 1:
                    chunks.append(to_part(entree))
                    rapid.append(np.zeros(len(entree), dtype=bool))

            for a, b in zip(p_index[:-1], p_index[1:]):
                seg = _resample(a, b, point_spacing)
                chunks.append(to_part(seg))
                rapid.append(np.zeros(len(seg), dtype=bool))
            prev_end_index = end

    if not chunks:
        return np.zeros((0, 3)), np.zeros(0, dtype=bool)
    return np.vstack(chunks), np.concatenate(rapid)


def toolpath_points(result: SliceResult, point_spacing: float = 2.0
                    ) -> tuple[np.ndarray, np.ndarray]:
    """Points de COUPE seuls, avec leurs normales.

    Utilise par la simulation d'enlevement de matiere, qui ne doit compter que
    la coupe : un mouvement de liaison au plan de degagement n'enleve rien.

    La normale retournee est ``direction`` : en ebauche a fond plat, la surface
    rencontree est le fond de la couche, dont la normale sortante pointe vers
    l'outil.
    """
    P, rapid = continuous_path(result, point_spacing)
    if len(P) == 0:
        return np.zeros((0, 3)), np.zeros((0, 3))
    P = P[~rapid]
    return P, np.tile(normalize(result.direction), (len(P), 1))


@dataclass
class RemovalStats:
    """Ce qui reste apres passage de l'outil. La mesure qui compte vraiment.

    Le reste est separe en deux, parce que les deux appellent des actions
    opposees :

    - ``leftover_reachable_mm3`` : matiere que CETTE direction voyait et que
      l'outil n'a pas prise. C'est la responsabilite de la passe — un outil trop
      gros, un pas trop grand, ou un angle rentrant ;
    - ``leftover_blind_mm3`` : matiere que cette direction ne voit pas du tout.
      Aucune passe selon cet axe n'y changera rien ; il faut une AUTRE
      indexation, ou un autre montage.

    Les confondre mene a la mauvaise conclusion : sur un simple pave, le dessous
    du brut (zone de bridage) represente l'essentiel du reste, et il serait
    absurde d'en deduire que l'ebauche par le dessus a echoue.
    """

    removed_mm3: float
    leftover_reachable_mm3: float
    leftover_blind_mm3: float
    max_stock_left_mm: float
    gouged_voxels: int

    @property
    def leftover_mm3(self) -> float:
        return self.leftover_reachable_mm3 + self.leftover_blind_mm3

    def describe(self) -> str:
        txt = (f"Ebauche simulee : {self.removed_mm3:.0f} mm3 enleves ; "
               f"reste {self.leftover_reachable_mm3:.0f} mm3 vus par cet axe "
               f"(surepaisseur max {self.max_stock_left_mm:.2f} mm) "
               f"et {self.leftover_blind_mm3:.0f} mm3 hors de sa vue")
        if self.gouged_voxels:
            txt += f" — {self.gouged_voxels} VOXELS GOUGES"
        return txt


def simulate_removal(material: MaterialState, result: SliceResult, tool: ToolAssembly,
                     *, point_spacing: float = 1.0) -> RemovalStats:
    """Applique les passes a l'etat matiere et mesure ce qu'il reste.

    C'est la reponse honnete a « l'ebauche a-t-elle fait son travail » — bien
    meilleure que le taux de balayage, parce qu'elle repond dans l'unite qui
    interesse l'utilisateur : **combien de surepaisseur reste-t-il, et ou**.

    ``max_stock_left_mm`` ne porte que sur la matiere que la direction VOYAIT :
    c'est la distance maximale, depuis la surface de la piece, d'un voxel de brut
    encore present et pourtant atteignable. Une valeur de l'ordre du rayon
    d'outil est normale le long des parois (c'est ce que la finition reprendra) ;
    une valeur proche de l'epaisseur initiale du brut signale que l'ebauche n'a
    pas fait son travail.
    """
    from scipy.ndimage import distance_transform_edt

    reach_before = material.reachable_from(result.direction)

    pts, _ = toolpath_points(result, point_spacing)
    if len(pts) == 0:
        rem = material.removable()
        vv = material.grid.voxel_volume
        return RemovalStats(0.0, float((rem & reach_before).sum()) * vv,
                            float((rem & ~reach_before).sum()) * vv, 0.0, 0)

    axes = np.tile(normalize(result.direction), (len(pts), 1))
    gouged = material.count_gouged_voxels(pts, axes, tool)
    removed = material.remove_tool_sweep(pts, axes, tool, only_cutting=True)

    left = material.removable()
    left_reach = left & reach_before
    left_blind = left & ~reach_before

    max_left = 0.0
    if left_reach.any():
        dist = distance_transform_edt(~material.protected, sampling=material.grid.pitch)
        max_left = float(dist[left_reach].max())

    vv = material.grid.voxel_volume
    return RemovalStats(
        removed_mm3=float(removed) * vv,
        leftover_reachable_mm3=float(left_reach.sum()) * vv,
        leftover_blind_mm3=float(left_blind.sum()) * vv,
        max_stock_left_mm=max_left,
        gouged_voxels=gouged,
    )


def with_approach_retract(
    points: np.ndarray, is_rapid: np.ndarray, direction: np.ndarray,
    clearance_z: float, frame: np.ndarray, *,
    standoff_mm: float = 2.0, plunge_feed: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    """Encadre un chemin par son approche et son degagement.

    Trou reste ouvert jusqu'ici, et il rendait tout programme emis
    inexecutable : le chemin commencait AU premier point de coupe et finissait
    AU dernier. Un controleur qui recoit cela amene l'outil au premier point
    par un mouvement non decrit — au mieux depuis la position courante, en
    ligne droite a travers la piece — puis le laisse dans la matiere a la fin.

    Ce que cette fonction ajoute, dans le repere INDEXE ou le plan de
    degagement est defini :

      approche : rapide au plan de degagement au-dessus du premier point,
                 rapide jusqu'a ``standoff_mm`` au-dessus de lui,
                 puis AVANCE TRAVAIL jusqu'au point ;
      degagement : avance travail de ``standoff_mm``, puis rapide au plan.

    Le dernier segment de l'approche est en avance travail et non en rapide :
    un rapide qui finit exactement sur la surface n'a aucune marge pour une
    erreur d'origine palpee, et c'est le mouvement qui casse les outils.
    ``standoff_mm`` est la hauteur a partir de laquelle on ralentit ; la mettre
    a zero supprimerait cette marge.

    **Ces mouvements sont du MOUVEMENT** : ils sont marques rapides ou non,
    mais ils passent les memes portes que les autres. Le balayage les subdivise
    et le validateur les refuse s'ils traversent quoi que ce soit. Les ajouter
    sans les faire valider serait exactement la faute que ce projet refuse.
    """
    P = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    R = np.asarray(is_rapid, dtype=bool).reshape(-1)
    if len(P) == 0:
        return P, R
    if len(P) != len(R):
        raise ValueError(f"{len(P)} points pour {len(R)} indicateurs de rapide")

    F = np.asarray(frame, dtype=np.float64).reshape(3, 3)
    d = normalize(np.asarray(direction, dtype=np.float64))
    so = max(float(standoff_mm), 0.0)

    def to_indexed(p: np.ndarray) -> np.ndarray:
        return F @ p

    def to_part(p: np.ndarray) -> np.ndarray:
        return F.T @ p

    first_i = to_indexed(P[0])
    last_i = to_indexed(P[-1])
    # Le plan de degagement doit etre AU-DESSUS du point, sinon l'approche
    # descendrait depuis sous la matiere.
    cz = max(float(clearance_z), float(first_i[2]) + so, float(last_i[2]) + so)

    pre = [
        to_part(np.array([first_i[0], first_i[1], cz])),
        to_part(np.array([first_i[0], first_i[1], first_i[2] + so])),
    ]
    pre_rapid = [True, True]
    post = [
        to_part(np.array([last_i[0], last_i[1], last_i[2] + so])),
        to_part(np.array([last_i[0], last_i[1], cz])),
    ]
    post_rapid = [not plunge_feed, True]

    pts = np.vstack([np.array(pre), P, np.array(post)])
    rap = np.concatenate([np.array(pre_rapid, dtype=bool), R,
                          np.array(post_rapid, dtype=bool)])
    return pts, rap
