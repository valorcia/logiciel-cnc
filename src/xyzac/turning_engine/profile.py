"""Tournage sur l'axe C : profil de revolution et generation de passes.

Le tournage n'est pas du fraisage avec une autre trajectoire, et c'est pourquoi
il a son module. Trois differences gouvernent tout :

1. **La piece tourne.** Les obstacles ne sont plus quasi statiques dans le
   repere piece, donc le collision engine par nuage de points ne s'applique pas.
2. **Le probleme redevient 2D.** Une piece en rotation autour de C est decrite
   par sa SILHOUETTE dans le plan (z, r). Le contact outil/piece, l'engagement
   et le degagement se lisent dans ce plan — exactement, sans discretisation
   conservative. C'est plus simple ET plus rigoureux que le cas fraisage.
3. **L'outil est un bec oriente.** Un outil de tour a un angle de direction et
   un angle de degagement ; ce sont eux qui decident quelles pentes du profil il
   peut suivre, et un profil trop raide n'est pas une question de trajectoire
   mais d'outil.

Le point 2 explique pourquoi ce module ne reutilise pas ``collision_engine`` :
ce ne serait pas une simplification mais une degradation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..geometry_core import brep
from ..geometry_core.types import normalize, orthonormal_basis


def _basis(d: np.ndarray):
    return orthonormal_basis(d)


@dataclass
class RevolutionProfile:
    """Silhouette d'une piece en rotation : rayon maximal selon la cote axiale.

    ``r`` est le rayon de l'enveloppe de revolution, c'est-a-dire ce que la
    piece balaie en tournant. Une piece non exactement de revolution y apparait
    donc plus grosse qu'elle n'est — ce qui est la bonne lecture pour du
    tournage : on ne peut pas tourner une matiere qui n'est pas la partout.
    """

    axis_point: np.ndarray
    axis_dir: np.ndarray
    z: np.ndarray                 # cotes le long de l'axe, croissantes
    r: np.ndarray                 # rayon d'enveloppe en chaque cote
    #: Defaut de circularite par cote : ecart de rayon ENTRE SECTEURS
    #: ANGULAIRES d'une meme tranche. Voir ``out_of_round``.
    ovality: np.ndarray = field(default_factory=lambda: np.zeros(0))

    @property
    def length(self) -> float:
        return float(self.z[-1] - self.z[0]) if len(self.z) > 1 else 0.0

    @property
    def max_radius(self) -> float:
        return float(self.r.max()) if len(self.r) else 0.0

    def radius_at(self, z: float | np.ndarray) -> np.ndarray:
        return np.interp(z, self.z, self.r)

    def out_of_round(self) -> np.ndarray:
        """Defaut de circularite par cote : ecart de rayon entre secteurs.

        Non nul signifie qu'un tour laisserait de la matiere a cette cote — un
        meplat, une lumiere, un percage lateral. Le planner doit le savoir :
        tourner une telle zone est possible, la FINIR au tour ne l'est pas.

        **Mesure sur theta, et non sur l'etendue de la tranche.** Une premiere
        version comparait le rayon maximal au minimal parmi les points de la
        tranche. Elle confondait deux choses tres differentes :

          - la variation AXIALE du rayon — un epaulement, un cone — qui est
            parfaitement tournable ;
          - la variation ANGULAIRE — un meplat — qui ne l'est pas.

        Un simple arbre etage etait ainsi declare non revolutif a 6 mm pres,
        soit exactement l'ecart entre deux de ses diametres : l'indicateur
        mesurait la geometrie de la piece au lieu de son defaut. On compare donc
        le rayon d'enveloppe entre SECTEURS ANGULAIRES d'une meme tranche, ou un
        epaulement donne le meme rayon dans tous les secteurs.
        """
        if len(self.ovality) != len(self.r):
            return np.zeros_like(self.r)
        return self.ovality

    def describe(self) -> str:
        oor = self.out_of_round()
        return (f"Profil de revolution autour de {np.round(self.axis_dir, 3)} : "
                f"L = {self.length:.2f} mm, R_max = {self.max_radius:.2f} mm, "
                f"defaut de circularite {np.percentile(oor, 95) if oor.size else 0.0:.3f} mm "
                f"(95e centile)")


def revolution_profile(shape, axis_point: np.ndarray, axis_dir: np.ndarray,
                       *, n_z: int = 200, n_theta: int = 24,
                       sample_spacing: float = 0.5) -> RevolutionProfile:
    """Extrait la silhouette de revolution d'une forme autour d'un axe.

    Methode : on echantillonne la surface, on projette chaque point en
    coordonnees cylindriques ``(z, r)`` autour de l'axe, puis on prend le rayon
    MAXIMAL par tranche de cote — c'est l'enveloppe balayee en rotation.

    On conserve aussi le rayon minimal par tranche. L'ecart entre les deux
    mesure la part de la piece qui n'est pas de revolution, information que le
    planner ne peut pas deviner autrement.
    """
    d = normalize(np.asarray(axis_dir, dtype=np.float64))
    p0 = np.asarray(axis_point, dtype=np.float64)

    s = brep.sample_surface(shape, spacing=sample_spacing)
    v = s.points - p0
    z = v @ d
    r = np.linalg.norm(v - np.outer(z, d), axis=1)

    # Secteur angulaire de chaque point : c'est sur theta que se mesure le
    # defaut de circularite (voir RevolutionProfile.out_of_round).
    u, v, _ = _basis(d)
    theta = np.arctan2(v @ (s.points - p0).T, u @ (s.points - p0).T)
    th_idx = np.clip(((theta + np.pi) / (2 * np.pi) * n_theta).astype(int),
                     0, n_theta - 1)

    z_lo, z_hi = float(z.min()), float(z.max())
    edges = np.linspace(z_lo, z_hi, n_z + 1)
    idx = np.clip(np.digitize(z, edges) - 1, 0, n_z - 1)

    centers = 0.5 * (edges[:-1] + edges[1:])
    r_max = np.zeros(n_z)
    oval = np.zeros(n_z)
    for k in range(n_z):
        sel = idx == k
        if not np.any(sel):
            # Tranche vide : on interpolera. Marquer 0 creerait un faux creux.
            r_max[k] = np.nan
            oval[k] = np.nan
            continue
        r_max[k] = r[sel].max()
        # Rayon d'enveloppe par secteur angulaire, puis ecart ROBUSTE entre
        # secteurs.
        #
        # Le min-max est trop fragile : sur une tranche qui chevauche un
        # epaulement, un secteur peut n'attraper que l'interieur de l'annulaire
        # et rendre un rayon trop faible. Une seule tranche sur 120 affichait
        # ainsi 3,3 mm de defaut sur un arbre parfaitement revolutif, alors que
        # la mediane valait 0,008 mm — du bruit d'echantillonnage pris pour un
        # meplat.
        #
        # L'ecart interpercentile (5-95) est insensible a un secteur isole tout
        # en restant sensible a un vrai meplat, qui couvre une large plage
        # angulaire. On exige aussi un nombre minimal de secteurs peuples :
        # en deca, la tranche n'est pas mesurable et on ne conclut pas.
        per_sector = []
        for t in range(n_theta):
            m2 = sel & (th_idx == t)
            if np.any(m2):
                per_sector.append(r[m2].max())
        if len(per_sector) >= max(8, n_theta // 3):
            ps = np.asarray(per_sector)
            oval[k] = float(np.percentile(ps, 95) - np.percentile(ps, 5))
        else:
            oval[k] = 0.0

    good = ~np.isnan(r_max)
    if good.sum() >= 2:
        r_max = np.interp(centers, centers[good], r_max[good])
        oval = np.interp(centers, centers[good], oval[good])
    else:
        r_max = np.nan_to_num(r_max)
        oval = np.nan_to_num(oval)

    return RevolutionProfile(axis_point=p0, axis_dir=d, z=centers,
                             r=r_max, ovality=oval)


@dataclass
class TurningTool:
    """Outil de tour : bec, angle de direction, angle de degagement.

    Modele volontairement reduit a ce qui decide l'accessibilite d'un profil :
    le rayon de bec fixe le rayon minimal des conges obtenables, et les deux
    angles bornent les pentes suivables. Un modele plus riche (plaquette,
    porte-plaquette) n'ajouterait rien tant qu'on ne simule pas les efforts.
    """

    tool_id: str
    nose_radius: float = 0.4
    #: Angle de direction d'arete (deg) : 0 = perpendiculaire a l'axe.
    lead_angle_deg: float = 0.0
    #: Angle de degagement lateral (deg). Borne la pente du profil suivable.
    clearance_angle_deg: float = 7.0
    #: Angle de pointe (deg). Un profil plus ferme que lui n'est pas realisable.
    included_angle_deg: float = 80.0
    max_depth_of_cut_mm: float = 1.5
    feed_mm_rev: float = 0.1

    def max_followable_slope_deg(self) -> float:
        """Pente maximale du profil que l'outil peut suivre sans talonner.

        Au-dela, le flanc de la plaquette frotte avant l'arete. C'est une limite
        d'OUTIL, pas de trajectoire : aucun recalcul de passes n'y remedie.
        """
        return 90.0 - self.clearance_angle_deg


@dataclass
class TurningToolBody:
    """Silhouette du porte-plaquette dans le plan (z, r), bec a l'origine.

    Limite explicitement ouverte au jalon M5 : le profil de revolution etait
    verifie contre le BEC seul. Or ce qui interdit de finir une gorge etroite
    n'est pas le bec, c'est le corps derriere lui. Le cas se produit des qu'une
    gorge est plus etroite que la plaquette, et il ne se voit sur aucun
    indicateur de pente.

    **Le moteur ne devine pas la geometrie d'un porte-plaquette.** Il verifie
    celle qu'on lui donne. ``iso_external`` fournit une silhouette par defaut
    plausible pour un outil de tournage exterieur, mais un outil reel se decrit
    par son catalogue, et une silhouette inventee qui passerait pour mesuree
    serait pire que pas de verification du tout.

    Convention : ``outline`` est une polyligne ``(K, 2)`` en ``(dz, dr)``
    relative au bec. ``dr > 0`` s'eloigne de l'axe (vers l'outil), ``dz`` suit
    l'axe de la piece. ``feed`` dit de quel cote le corps traine.
    """

    outline: np.ndarray
    label: str = "porte-plaquette"

    def __post_init__(self):
        self.outline = np.asarray(self.outline, float).reshape(-1, 2)

    @staticmethod
    def external(*, nose_offset_mm: float = 6.0, width_front_mm: float = 1.5,
                 width_back_mm: float = 25.0, height_mm: float = 20.0,
                 feed: int = -1) -> "TurningToolBody":
        """Corps d'un outil de tournage exterieur sur queue carree.

        ``nose_offset_mm`` est la hauteur radiale de la PLAQUETTE : le corps
        commence au-dela. ``width_front_mm`` est le debord du corps du cote de
        l'avance (petit sur un outil de tournage : c'est le cote qui doit
        degager), ``width_back_mm`` du cote qui traine.

        **La plaquette elle-meme n'est pas dans la silhouette, et c'est
        deliberé.** Son flanc contre la pente locale du profil est deja mesure
        par ``TurningTool.max_followable_slope_deg`` et rapporte en
        ``too_steep_zones``. L'y remettre fait mesurer deux fois la meme limite
        physique : la premiere version de ce constructeur incluait le flanc, et
        tout devenait infaisable — y compris un outil a gorge de 2 mm dans une
        gorge de 3 mm. Le signe qui l'a revele est que la penetration rapportee
        ne dependait PAS de la taille du corps, alors que c'est le seul
        parametre qui devrait la faire varier.
        """
        sgn = -1.0 if feed < 0 else 1.0
        front, back = float(width_front_mm), float(width_back_mm)
        lo, hi = float(nose_offset_mm), float(nose_offset_mm + height_mm)
        # dz > 0 du cote qui traine (oppose a l'avance).
        z_lead, z_trail = -sgn * front, sgn * back
        return TurningToolBody(
            np.array([(z_lead, lo), (z_trail, lo), (z_trail, hi), (z_lead, hi)],
                     float),
            label=f"corps exterieur {height_mm:.0f} mm, debord avant "
                  f"{front:.1f} mm")

    @staticmethod
    def grooving(*, blade_width_mm: float = 3.0, nose_offset_mm: float = 1.0,
                 depth_mm: float = 15.0) -> "TurningToolBody":
        """Lame a gorger : etroite en z, profonde en radial.

        C'est l'outil qui rend une gorge faisable, et le seul cas ou le debord
        avant est symetrique du debord arriere.
        """
        h = float(blade_width_mm) / 2.0
        lo, hi = float(nose_offset_mm), float(nose_offset_mm + depth_mm)
        return TurningToolBody(
            np.array([(-h, lo), (h, lo), (h, hi), (-h, hi)], float),
            label=f"lame a gorger {blade_width_mm:.1f} mm")

    def sampled(self, spacing: float = 0.5) -> tuple[np.ndarray, float]:
        """Polyligne echantillonnee a pas borne, et le pas effectif.

        Tester les seuls SOMMETS laisserait une arete traverser un epaulement
        sans qu'aucun sommet n'y entre. On echantillonne donc les aretes, et le
        pas retourne sert a majorer le test — meme discipline que le champ
        d'obstacles discret (ADR-001 / D2).
        """
        pts = self.outline
        closed = np.vstack([pts, pts[:1]])
        out = []
        eff = 0.0
        for a, b in zip(closed[:-1], closed[1:]):
            L = float(np.linalg.norm(b - a))
            n = max(int(np.ceil(L / max(spacing, 1e-6))), 1)
            eff = max(eff, L / n)
            for k in range(n):
                out.append(a + (b - a) * (k / n))
        return np.array(out, float), eff


@dataclass
class BodyInterference:
    """Zone ou le corps de l'outil entre dans la matiere a conserver."""

    z_contact: float             # cote du point de contact du bec
    z_hit: float                 # cote ou le corps touche
    penetration_mm: float

    def describe(self) -> str:
        return (f"bec en z={self.z_contact:.2f} : le corps entre de "
                f"{self.penetration_mm:.3f} mm dans la matiere en z={self.z_hit:.2f}")


def check_body_clearance(
    profile: RevolutionProfile, body: TurningToolBody,
    z: np.ndarray, r: np.ndarray,
    *, clearance_mm: float = 0.2, spacing: float = 0.5,
) -> list[BodyInterference]:
    """Le corps de l'outil degage-t-il, le bec etant sur ``(z, r)`` ?

    Test dans le plan (z, r), donc exact a la discretisation de la silhouette
    pres. Chaque point echantillonne du corps est compare au rayon du profil a
    sa cote : il interfere si son rayon passe sous ``profil + clearance_mm``.

    Le pas d'echantillonnage de la silhouette est ajoute a la penetration
    mesuree, de sorte que le resultat MAJORE l'interference reelle. Un test qui
    sous-estimerait l'interference donnerait le mauvais sens d'erreur, celui qui
    laisse passer un talonnage.
    """
    pts, eff = body.sampled(spacing)
    z = np.asarray(z, float).ravel()
    r = np.asarray(r, float).ravel()
    z0, z1 = float(profile.z[0]), float(profile.z[-1])

    hits: list[BodyInterference] = []
    for zc, rc in zip(z, r):
        zz = zc + pts[:, 0]
        rr = rc + pts[:, 1]
        inside = (zz >= z0) & (zz <= z1)
        if not inside.any():
            continue
        need = profile.radius_at(zz[inside]) + clearance_mm
        pen = need - rr[inside]
        k = int(np.argmax(pen))
        if pen[k] > 0.0:
            hits.append(BodyInterference(
                z_contact=float(zc), z_hit=float(zz[inside][k]),
                penetration_mm=float(pen[k] + eff * 0.5)))
    return hits


@dataclass
class TurningPass:
    """Une passe de tournage, en coordonnees (z, r)."""

    z: np.ndarray
    r: np.ndarray
    kind: str                      # "ebauche" | "finition"
    depth_of_cut: float = 0.0

    @property
    def n_points(self) -> int:
        return int(len(self.z))


@dataclass
class TurningPlanReport:
    """Verdict sur la faisabilite d'un tournage, et ce qui le limite."""

    profile: RevolutionProfile
    passes: list[TurningPass] = field(default_factory=list)
    removed_area_mm2: float = 0.0
    too_steep_zones: list[tuple[float, float]] = field(default_factory=list)
    #: Defaut de circularite au 95e centile des cotes, et non au maximum.
    #:
    #: Le maximum reste sensible a une tranche isolee mal echantillonnee : sur
    #: un arbre parfaitement revolutif il atteignait 2,8 mm alors que la mediane
    #: valait 0,003 mm. Rapporter le maximum ferait signaler un meplat sur toutes
    #: les pieces tournees. Un centile eleve garde la sensibilite a un vrai
    #: meplat — qui court sur toute la longueur, donc sur presque toutes les
    #: tranches — sans compter le bruit.
    out_of_round_p95_mm: float = 0.0
    out_of_round_max_mm: float = 0.0
    #: Interferences du CORPS de l'outil, quand une silhouette a ete fournie.
    #: Vide ne signifie pas « degage » si aucune silhouette n'a ete donnee :
    #: voir ``body_checked``.
    body_interferences: list = field(default_factory=list)
    body_checked: bool = False
    feasible: bool = True
    detail: str = ""

    def describe(self) -> str:
        lines = [
            f"Tournage : {'REALISABLE' if self.feasible else 'REFUSE'} — "
            f"{len(self.passes)} passes "
            f"({sum(1 for p in self.passes if p.kind == 'ebauche')} ebauche, "
            f"{sum(1 for p in self.passes if p.kind == 'finition')} finition)",
            f"  {self.profile.describe()}",
            f"  section enlevee : {self.removed_area_mm2:.1f} mm2 "
            f"(x 2.pi.r pour le volume)",
        ]
        # Seuil a un dixieme : en deca, l'ecart releve de la discretisation de
        # l'echantillonnage et non d'un meplat. Un arbre parfaitement revolutif
        # mesure 0,05 mm au 95e centile avec le pas d'echantillonnage courant.
        if self.out_of_round_p95_mm > 0.1:
            lines.append(
                f"  defaut de circularite {self.out_of_round_p95_mm:.3f} mm "
                f"(95e centile ; max isole {self.out_of_round_max_mm:.3f}) : "
                "la piece n'est pas de revolution a cette cote (meplat, lumiere, "
                "percage lateral). Le tour degrossira, mais la finition de cette "
                "zone releve du fraisage")
        if not self.body_checked:
            lines.append("  corps de l'outil NON verifie : aucune silhouette de "
                         "porte-plaquette fournie (le bec seul est degage)")
        elif self.body_interferences:
            lines.append(f"  corps de l'outil en interference sur "
                         f"{len(self.body_interferences)} positions de bec :")
            for b in self.body_interferences[:3]:
                lines.append("    " + b.describe())
        for z0, z1 in self.too_steep_zones[:5]:
            lines.append(f"  pente trop raide entre z={z0:.2f} et z={z1:.2f} : "
                         "outil inadapte, pas un probleme de trajectoire")
        if self.detail:
            lines.append(f"  {self.detail}")
        return "\n".join(lines)


def plan_turning_passes(
    profile: RevolutionProfile, tool: TurningTool,
    *,
    stock_radius: float,
    finish_allowance: float = 0.2,
    depth_of_cut: float | None = None,
    body: "TurningToolBody | None" = None,
    body_clearance_mm: float = 0.2,
) -> TurningPlanReport:
    """Genere des passes d'ebauche a rayon decroissant, puis une finition.

    L'ebauche travaille a rayon CONSTANT par passe (cylindrage successif) : le
    mode le plus simple, le plus previsible et celui qui charge l'outil de
    façon reguliere. La finition suit le profil.

    Le controle de pente est fait AVANT de generer quoi que ce soit : un profil
    plus raide que l'outil ne peut pas etre suivi, et proposer des passes qui le
    traversent serait produire un programme qui talonne.

    ``body`` donne la silhouette du porte-plaquette. Sans elle, seul le bec est
    verifie, et le rapport le DIT au lieu de laisser croire a un degagement : une
    gorge plus etroite que la plaquette passe tous les controles de pente.
    """
    doc = depth_of_cut or tool.max_depth_of_cut_mm
    target = profile.r + finish_allowance
    report = TurningPlanReport(profile=profile)
    oor = profile.out_of_round()
    report.out_of_round_p95_mm = float(np.percentile(oor, 95)) if oor.size else 0.0
    report.out_of_round_max_mm = float(oor.max()) if oor.size else 0.0

    # Pente du profil, en degres par rapport au plan perpendiculaire a l'axe.
    if len(profile.z) > 2:
        dz = np.gradient(profile.z)
        dr = np.gradient(profile.r)
        slope = np.degrees(np.arctan2(np.abs(dr), np.maximum(np.abs(dz), 1e-9)))
        bad = slope > tool.max_followable_slope_deg()
        if np.any(bad):
            edges = np.flatnonzero(np.diff(bad.astype(int)) != 0) + 1
            bounds = np.concatenate(([0], edges, [len(bad)]))
            for a, b in zip(bounds[:-1], bounds[1:]):
                if bad[a]:
                    report.too_steep_zones.append(
                        (float(profile.z[a]), float(profile.z[min(b, len(bad) - 1)])))

    if stock_radius <= target.min():
        report.feasible = False
        report.detail = (f"le brut (R = {stock_radius:.2f} mm) est deja sous le "
                         f"profil vise (R_min = {target.min():.2f} mm) : rien a tourner, "
                         "ou brut inadapte")
        return report

    # Ebauche : cylindrages successifs de l'exterieur vers le profil.
    #
    # Chaque passe travaille a rayon CONSTANT et ne couvre que l'etendue axiale
    # ou il reste de la matiere a ce rayon. C'est le tournage d'epaulements
    # classique, et il descend jusqu'au rayon MINIMAL du profil.
    #
    # Une premiere version s'arretait au rayon maximal du profil : sur un arbre
    # etage de R20 a R4, elle produisait deux passes et laissait les etages
    # intacts. L'erreur etait de raisonner sur l'enveloppe globale au lieu de
    # l'etendue reellement usinable a chaque rayon.
    r_cur = float(stock_radius)
    r_floor = float(target.min())
    guard = 0
    while r_cur - doc > r_floor and guard < 10000:
        guard += 1
        r_next = r_cur - doc
        active = target < r_next
        if np.any(active):
            report.passes.append(TurningPass(
                z=profile.z[active].copy(),
                r=np.full(int(active.sum()), r_next),
                kind="ebauche", depth_of_cut=doc))
        r_cur = r_next

    # Derniere passe d'ebauche : le profil a la surepaisseur pres, la ou le
    # cylindrage n'a pas pu descendre.
    r_semi = np.maximum(target, r_floor)
    if np.any(r_semi < r_cur - 1e-9):
        report.passes.append(TurningPass(z=profile.z.copy(), r=r_semi,
                                         kind="ebauche", depth_of_cut=doc))

    # Finition : le profil lui-meme.
    report.passes.append(TurningPass(z=profile.z.copy(), r=profile.r.copy(),
                                     kind="finition", depth_of_cut=finish_allowance))

    # Section enlevee, dans le plan (z, r). Le volume s'en deduit par rotation.
    report.removed_area_mm2 = float(np.trapezoid(
        np.maximum(stock_radius - profile.r, 0.0), profile.z))

    # Degagement du CORPS, sur la passe de finition : c'est elle qui approche le
    # profil final, donc elle qui contraint. Les ebauches restent en retrait.
    if body is not None:
        report.body_checked = True
        fin = next((p for p in report.passes if p.kind == "finition"), None)
        if fin is not None:
            report.body_interferences = check_body_clearance(
                profile, body, fin.z, fin.r, clearance_mm=body_clearance_mm)

    if report.too_steep_zones:
        report.feasible = False
        report.detail = (
            f"l'outil suit au plus {tool.max_followable_slope_deg():.0f} deg de "
            f"pente (degagement {tool.clearance_angle_deg:.0f} deg)")
    elif report.body_interferences:
        worst = max(report.body_interferences, key=lambda b: b.penetration_mm)
        report.feasible = False
        report.detail = (
            f"le corps de l'outil ({body.label}) talonne : au pire "
            f"{worst.penetration_mm:.3f} mm dans la matiere a conserver. "
            "Il faut un outil plus etroit ou une reprise au fraisage, pas une "
            "autre trajectoire")
    return report
