"""Test de collision outil COMPLET / champ d'obstacles, vectorise NumPy.

Principe (ADR-001 / D4) : l'outil est une pile de troncons coaxiaux. Dans le
repere outil (origine au bec, +z vers la broche), un point obstacle se reduit a
un couple ``(r, z)``, et l'appartenance au troncon se teste par ``r < R(z)``.

Le cout est donc O(N_points x N_troncons) sans BVH, sans maillage et sans
allocation par orientation. C'est ce qui rend l'exploration de centaines
d'orientations par point de contact tenable sur Raspberry Pi 5.

La sortie n'est jamais un simple booleen : on retourne QUEL troncon touche QUEL
obstacle. Sans cela, l'UI ne pourrait pas dire "le porte-outil touche, allonge
la tige de 10 mm" et se contenterait de "echec".
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..tool_model.assembly import SegmentRole, ToolAssembly
from .field import PENETRATION_ALLOWED, ObstacleClass, ObstacleField  # noqa: F401


@dataclass
class CollisionReport:
    """Diagnostic complet d'un placement d'outil."""

    collided: bool
    #: Marge signee minimale (mm) sur les couples interdits. > 0 = degage.
    min_margin: float
    worst_role: SegmentRole | None = None
    worst_class: ObstacleClass | None = None
    worst_point: np.ndarray | None = None
    #: Nombre de points en violation, par role. Sert au diagnostic UI.
    violations_by_role: dict[SegmentRole, int] = field(default_factory=dict)

    def reason(self) -> str:
        if not self.collided:
            return f"degage (marge {self.min_margin:.3f} mm)"
        role = self.worst_role.value if self.worst_role else "?"
        cls = self.worst_class.name if self.worst_class is not None else "?"
        return (f"collision {role} / {cls} "
                f"(penetration {-self.min_margin:.3f} mm)")


def signed_clearance_to_segment(
    r: np.ndarray, z: np.ndarray, z0: float, z1: float, r0: float, r1: float
) -> np.ndarray:
    """Distance signee point -> troncon tronconique. Negatif = a l'interieur.

    Approximation assumee : la distance radiale est mesuree horizontalement et
    non perpendiculairement a la paroi conique. Pour une paroi inclinee d'un
    angle ``alpha``, cela SURESTIME la distance d'un facteur ``1/cos(alpha)``.
    On corrige donc par ``cos(alpha)``, ce qui rend la mesure conservative
    (sous-estimee) plutot que optimiste. Une marge sous-estimee rejette parfois
    a tort ; une marge surestimee laisse passer une collision.
    """
    slope = (r1 - r0) / max(z1 - z0, 1e-12)
    cos_alpha = 1.0 / np.sqrt(1.0 + slope * slope)

    z_clamped = np.clip(z, z0, z1)
    r_env = r0 + (z_clamped - z0) * slope

    d_radial = (r - r_env) * cos_alpha          # > 0 : en dehors radialement
    d_axial_out = np.maximum(z0 - z, z - z1)    # > 0 : en dehors axialement

    outside_axially = d_axial_out > 0.0
    outside_radially = d_radial > 0.0

    ext = np.where(
        outside_axially & outside_radially,
        np.hypot(np.maximum(d_axial_out, 0.0), np.maximum(d_radial, 0.0)),
        np.where(outside_axially, d_axial_out, d_radial),
    )
    # A l'interieur : distance (negative) a la paroi la plus proche.
    inside = np.maximum(d_radial, d_axial_out)
    return np.where(outside_axially | outside_radially, ext, inside)


class ToolCollisionChecker:
    """Teste un ``ToolAssembly`` place en (tcp, axe) contre un ``ObstacleField``.

    **Deux physiques distinctes, deux traitements distincts.**

    Le degagement du col, de la tige, du porte-outil et du nez de broche se joue
    au millimetre : le test discret conservatif (nuage inflate de ``delta``) y est
    parfaitement adapte, et son pessimisme est une qualite.

    Le contact de l'arete de coupe avec la face usinee se joue au centieme, et
    il est VOULU : en fraisage de flanc, la coupe est tangente a la face sur
    toute sa longueur. Appliquer la meme inflation a ce couple ferait declarer
    toute passe de flanc "en collision avec la piece" — un faux positif
    systematique qui rendrait le solveur inutilisable.

    D'ou ``cutting_allowance`` : la tolerance de penetration accordee au seul
    couple (COUPE, PIECE). Elle vaut typiquement l'incertitude d'echantillonnage
    plus la surepaisseur de finition.

    **Limite assumee et documentee** : ce mecanisme rend la detection de gouge
    FINE de l'arete de coupe hors de portee d'un test par nuage de points, dont
    la resolution est bornee par le pas d'echantillonnage. La detection de gouge
    au centieme exige des requetes de distance exactes sur le B-Rep (OCCT
    ``BRepExtrema``) et est explicitement reportee a un jalon ulterieur
    (voir docs/testplan). Ce qui EST garanti ici : aucun organe non coupant ne
    penetre la matiere, et l'arete de coupe ne laboure pas grossierement.
    """

    def __init__(self, tool: ToolAssembly):
        self.tool = tool
        self._segs = [
            (s.role, s.z_start, s.z_end, s.r_start, s.r_end) for s in tool.segments
        ]
        self._reach = float(np.hypot(tool.total_length, tool.max_radius))

        # Troncons qui SUIVENT l'outil dans le canal qu'il vient de couper.
        #
        # Regle physique, et elle manquait : un troncon dont le rayon ne depasse
        # pas le rayon de coupe tient forcement dans le passage ouvert par
        # l'arete, des lors que l'outil progresse le long de son propre chemin.
        # La tige d'une fraise 2 tailles est dans ce cas — elle a exactement le
        # diametre de coupe.
        #
        # Sans cette regle, le test discret la declare en collision avec le brut
        # a chaque passe profonde : elle se trouve au bord EXACT du canal, et la
        # moindre inflation d'echantillonnage suffit a la faire toucher. Mesuree
        # sur une poche : 4 couches sur 12 refusees pour 0,226 mm de penetration
        # d'une tige qui, en realite, descend dans un trou qu'elle remplit.
        #
        # La condition sur le rayon est essentielle : un porte-outil, lui, ne
        # tient pas dans le canal, et reste donc un obstacle a part entiere.
        eps = 1e-6
        self._trails_in_cut = tuple(
            seg.role is not SegmentRole.SPINDLE_NOSE
            and seg.role is not SegmentRole.HOLDER
            and seg.r_max <= tool.radius + eps
            for seg in tool.segments
        )

    @property
    def reach(self) -> float:
        """Rayon de la sphere contenant l'outil place. Pre-filtre spatial."""
        return self._reach

    def check(
        self,
        tcp: np.ndarray,
        axis: np.ndarray,
        obstacles: ObstacleField,
        *,
        cutting_depth: float = 0.0,
        margin_only: bool = False,
        margin_band: float = 10.0,
        cutting_allowance: float = 0.0,
    ) -> CollisionReport:
        """Teste un placement unique.

        ``cutting_depth`` est la profondeur (mm depuis le bec) sur laquelle le
        troncon de coupe est en prise volontaire : sur cette hauteur, le contact
        avec la PIECE est tolere, puisque c'est precisement la matiere que l'on
        enleve. Au-dela, un contact piece est une gouge.

        ``margin_band`` elargit le pre-filtre spatial pour que la marge reportee
        reste informative quand l'outil est largement degage. Sans cette bande,
        la marge sauterait brutalement a ``inf`` des que plus rien ne peut
        toucher, ce qui empecherait de comparer deux placements tous deux sains.

        ``cutting_allowance`` (mm) : tolerance de penetration accordee au SEUL
        couple (arete de coupe, piece). Voir ``ToolCollisionChecker`` pour la
        justification — c'est le parametre qui separe "l'outil usine la face"
        de "l'outil laboure la face".
        """
        tcp = np.asarray(tcp, dtype=np.float64)
        axis = np.asarray(axis, dtype=np.float64)
        axis = axis / np.linalg.norm(axis)

        if len(obstacles) == 0:
            return CollisionReport(collided=False, min_margin=np.inf)

        v = obstacles.points - tcp
        z = v @ axis
        radial_vec = v - np.outer(z, axis)
        r = np.linalg.norm(radial_vec, axis=1)

        # Pre-filtre : hors du cylindre englobant de l'outil, rien ne peut toucher.
        band = obstacles.inflation + margin_band
        near = (z >= -band) & (z <= self.tool.total_length + band) \
            & (r <= self.tool.max_radius + band)
        if not np.any(near):
            return CollisionReport(collided=False, min_margin=np.inf)

        zi, ri = z[near], r[near]
        cls_i = obstacles.classes[near]
        inf_i = obstacles.inflation[near]
        pts_i = obstacles.points[near]

        min_margin = np.inf
        worst_role = worst_class = worst_point = None
        violations: dict[SegmentRole, int] = {}
        collided = False

        for si, (role, z0, z1, r0, r1) in enumerate(self._segs):
            d = signed_clearance_to_segment(ri, zi, z0, z1, r0, r1) - inf_i

            trails = self._trails_in_cut[si] if si < len(self._trails_in_cut) else False
            for oc in ObstacleClass:
                if PENETRATION_ALLOWED[(role, oc)]:
                    continue  # penetration toleree : ce couple n'est pas une contrainte
                if trails and oc is ObstacleClass.STOCK:
                    continue  # le troncon suit l'outil dans le canal deja coupe

                sel = cls_i == int(oc)
                if role is SegmentRole.CUTTING and oc is ObstacleClass.PART and cutting_depth > 0:
                    # En prise volontaire : on exclut la zone de coupe active.
                    sel = sel & ~(zi <= cutting_depth)
                if not np.any(sel):
                    continue

                if role is SegmentRole.CUTTING and oc is ObstacleClass.PART:
                    d_eff = d + cutting_allowance
                else:
                    d_eff = d
                ds = d_eff[sel]
                k = int(np.argmin(ds))
                if ds[k] < min_margin:
                    min_margin = float(ds[k])
                    worst_role, worst_class = role, oc
                    worst_point = pts_i[sel][k]

                n_viol = int(np.count_nonzero(ds < 0.0))
                if n_viol:
                    collided = True
                    violations[role] = violations.get(role, 0) + n_viol
                    if margin_only:
                        # Sortie anticipee : l'appelant ne veut qu'un booleen.
                        return CollisionReport(
                            collided=True, min_margin=min_margin,
                            worst_role=worst_role, worst_class=worst_class,
                            worst_point=worst_point, violations_by_role=violations,
                        )

        return CollisionReport(
            collided=collided,
            min_margin=float(min_margin),
            worst_role=worst_role,
            worst_class=worst_class,
            worst_point=worst_point,
            violations_by_role=violations,
        )

    def check_many(
        self,
        tcp: np.ndarray,
        axes: np.ndarray,
        obstacles: ObstacleField,
        *,
        cutting_depth: float = 0.0,
        cutting_allowance: float = 0.0,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Teste M orientations en un point de contact. Boucle chaude du solveur.

        ``tcp`` accepte un point unique (3,) ou UN TCP PAR ORIENTATION (M,3).
        Le second cas est le cas reel : des qu'un outil a un rayon de bec, ou
        que l'axe n'est pas normal a la surface, le bec se deplace avec
        l'orientation. Traiter un TCP unique donnerait une reponse fausse d'un
        rayon d'outil.

        L'astuce qui rend le TCP variable gratuit : on n'a jamais besoin du
        vecteur ``p - tcp_m``, seulement de ses projections. Or

            z[n,m] = p_n . d_m  -  tcp_m . d_m
            |p_n - tcp_m|^2     = |p_n|^2 - 2 p_n . tcp_m + |tcp_m|^2

        soit deux produits matriciels (N,3)x(3,M) au lieu d'un tenseur
        (N,M,3). On garde le cout memoire en O(N.M) et on evite une allocation
        de plusieurs dizaines de Mo par point de contact.

        Retourne ``(feasible (M,), margin (M,), blocking (M,))`` ou ``blocking``
        vaut -1 si degage, sinon l'indice du troncon fautif.
        """
        axes = np.asarray(axes, dtype=np.float64).reshape(-1, 3)
        axes = axes / np.linalg.norm(axes, axis=1, keepdims=True)
        M = axes.shape[0]

        tcps = np.asarray(tcp, dtype=np.float64).reshape(-1, 3)
        if tcps.shape[0] == 1:
            tcps = np.repeat(tcps, M, axis=0)
        elif tcps.shape[0] != M:
            raise ValueError(f"check_many : {tcps.shape[0]} TCP pour {M} orientations")

        center = tcps.mean(axis=0)
        spread = float(np.linalg.norm(tcps - center, axis=1).max(initial=0.0))
        inf_max = float(obstacles.inflation.max(initial=0.0))
        sub = obstacles.subset_near(center, self._reach + spread + inf_max)
        if len(sub) == 0:
            return (np.ones(M, bool), np.full(M, np.inf), np.full(M, -1, np.int8))

        # Pre-filtre CONIQUE, en plus du pre-filtre spherique.
        #
        # La sphere de rayon ``reach`` est tres large (l'outil complet fait plus
        # de 100 mm avec son nez de broche), et elle garde tout ce qui se trouve
        # DERRIERE le point de contact — c'est-a-dire dans la matiere, ou aucune
        # orientation ne peut aller. Comme toutes les orientations testees sont
        # regroupees autour d'une direction moyenne, l'outil balaie en realite un
        # cone, pas une sphere.
        #
        # Un point a la distance D ne peut etre atteint que si son angle a l'axe
        # moyen est inferieur a l'ouverture du faisceau, elargie de l'angle
        # sous-tendu par le rayon de l'outil a cette distance. Test exact au sens
        # conservatif, et O(N).
        mean_axis = axes.mean(axis=0)
        na = float(np.linalg.norm(mean_axis))
        if na > 1e-9:
            mean_axis /= na
            half_spread = float(np.arccos(np.clip((axes @ mean_axis).min(), -1.0, 1.0)))
            v = sub.points - center
            dist = np.linalg.norm(v, axis=1)
            ok_near = dist <= (self.tool.max_radius + inf_max + spread)
            with np.errstate(invalid="ignore", divide="ignore"):
                ang = np.arccos(np.clip((v @ mean_axis) / np.maximum(dist, 1e-12), -1.0, 1.0))
                widen = np.arcsin(np.clip(
                    (self.tool.max_radius + inf_max + spread) / np.maximum(dist, 1e-12), 0.0, 1.0))
            keep = ok_near | (ang <= half_spread + widen)
            if not keep.all():
                sub = ObstacleField(sub.points[keep], sub.classes[keep], sub.inflation[keep])
            if len(sub) == 0:
                return (np.ones(M, bool), np.full(M, np.inf), np.full(M, -1, np.int8))

        pts = sub.points                                   # (N,3)
        z_all = pts @ axes.T - np.sum(tcps * axes, axis=1)[None, :]   # (N,M)
        d2 = (np.sum(pts * pts, axis=1)[:, None]
              - 2.0 * (pts @ tcps.T)
              + np.sum(tcps * tcps, axis=1)[None, :])       # (N,M)
        r_all = np.sqrt(np.maximum(d2 - z_all * z_all, 0.0))

        inf = sub.inflation[:, None]
        margin = np.full((M,), np.inf)
        blocking = np.full((M,), -1, np.int8)

        # Bande radiale PAR TRONCON, independante de l'orientation.
        #
        # Le gain vient d'une observation simple : ``|p - tcp|`` ne depend pas de
        # la direction testee (a ``spread`` pres, l'ecart entre les TCP). Or un
        # point ne peut etre a portee du troncon [z0, z1] x [r0, r1] que si
        #
        #     z0 - inf - spread  <=  |p - tcp|  <=  sqrt((z1+inf)^2 + (rmax+inf)^2) + spread
        #
        # puisque |p - tcp|^2 = z^2 + r^2. Chaque troncon ne voit donc qu'une
        # COQUILLE du nuage, calculee une seule fois pour toutes les orientations.
        #
        # L'effet est tres inegal selon le troncon, et c'est tout l'interet :
        # l'arete de coupe (z <= 20 mm, r = 3 mm) ne voit qu'une petite boule,
        # alors que sans cette bande elle balayait les memes milliers de points
        # que le nez de broche.
        dist_mean = np.linalg.norm(pts - center, axis=1)  # (N,), calcule une fois

        for si, (role, z0, z1, r0, r1) in enumerate(self._segs):
            trails = self._trails_in_cut[si] if si < len(self._trails_in_cut) else False
            forbidden = np.zeros(len(sub), dtype=bool)
            for oc in ObstacleClass:
                if PENETRATION_ALLOWED[(role, oc)]:
                    continue
                if trails and oc is ObstacleClass.STOCK:
                    continue
                forbidden |= sub.classes == int(oc)
            if not forbidden.any():
                continue

            rmax = max(r0, r1)
            d_hi = float(np.hypot(z1 + inf_max, rmax + inf_max) + spread)
            d_lo = float(max(0.0, z0 - inf_max - spread))
            rows = np.flatnonzero(forbidden & (dist_mean <= d_hi) & (dist_mean >= d_lo))
            if rows.size == 0:
                continue

            zs, rs = z_all[rows], r_all[rows]
            d = signed_clearance_to_segment(rs, zs, z0, z1, r0, r1) - inf[rows]

            if role is SegmentRole.CUTTING:
                part_rows = (sub.classes[rows] == int(ObstacleClass.PART))[:, None]
                if cutting_allowance > 0.0:
                    d = np.where(part_rows, d + cutting_allowance, d)
                if cutting_depth > 0:
                    d = np.where(part_rows & (zs <= cutting_depth), np.inf, d)

            seg_min = d.min(axis=0)                        # (M,)
            improved = seg_min < margin
            blocking = np.where(improved, si, blocking).astype(np.int8)
            margin = np.minimum(margin, seg_min)

        feasible = margin >= 0.0
        blocking = np.where(feasible, -1, blocking).astype(np.int8)
        return feasible, margin, blocking


def check_path_poses(
    checker: ToolCollisionChecker, tcps: np.ndarray, axes: np.ndarray,
    obstacles: ObstacleField, *, chunk: int = 64, **kw,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Teste les poses d'un CHEMIN, par blocs de points consecutifs.

    ``check_many`` amortit l'extraction du voisinage sur toutes les poses qu'on
    lui donne — mais deux de ses pre-filtres, le cone et la coquille radiale par
    troncon, sont elargis de ``spread``, l'etendue spatiale des TCP fournis.

    Lui passer une trajectoire entiere est donc contre-productif : sur une
    couche d'ebauche, les poses couvrent 60 mm, le ``spread`` atteint 35 mm, et
    les deux pre-filtres ne prunent plus rien. Mesure : 4,1 s pour 368 poses
    contre 13 520 obstacles.

    Les points d'un chemin etant ordonnes, des blocs de points CONSECUTIFS sont
    spatialement compacts. On retrouve un ``spread`` de quelques millimetres, et
    donc tout l'effet des pre-filtres.
    """
    tcps = np.asarray(tcps, float).reshape(-1, 3)
    axes = np.asarray(axes, float).reshape(-1, 3)
    n = len(tcps)
    feas = np.ones(n, dtype=bool)
    marg = np.full(n, np.inf)
    blk = np.full(n, -1, np.int8)

    for i0 in range(0, n, chunk):
        i1 = min(i0 + chunk, n)
        f, m, b = checker.check_many(tcps[i0:i1], axes[i0:i1], obstacles, **kw)
        feas[i0:i1], marg[i0:i1], blk[i0:i1] = f, m, b
    return feas, marg, blk
