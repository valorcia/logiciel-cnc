"""Recettes de coupe : vitesse de broche et avance, avec leur provenance.

Trou identifie depuis M1 et reste ouvert jusqu'ici : le post-processeur ecrivait
``F300`` par defaut. Un nombre invente dans du code livre, exactement ce que ce
projet refuse partout ailleurs.

Ce module le comble, sous quatre contraintes qui decident de sa forme :

1. **Aucune interpolation entre matieres.** Une matiere absente de la table
   fait LEVER, elle ne se devine pas depuis sa voisine. Usiner de l'inox avec
   des parametres d'aluminium casse l'outil au premier engagement.
2. **Les valeurs sont des POINTS DE DEPART**, jamais des garanties. Elles sont
   generiques et conservatrices, et chacune porte sa source et sa bande
   d'incertitude. Ce ne sont pas les donnees d'un fabricant pour un outil
   precis, et le dire fait partie du resultat.
3. **Le bridage par les limites machine est rapporte, pas silencieux.** Une
   broche qui plafonne a 24 000 tr/min ne peut pas tenir la vitesse de coupe
   d'une fraise de 2 mm : la recette baisse alors la vitesse de coupe reelle et
   l'ANNONCE. Un plafonnement tu ferait croire a une vitesse de coupe qu'on
   n'atteint pas.
4. **Sur une machine en kit, la rigidite depend de l'assemblage de
   l'acheteur.** Aucune recette ne peut donc etre qualifiee par le logiciel :
   ``qualified`` vaut False jusqu'a une qualification physique, et le G-code
   emis le porte dans son en-tete.

Deux effets physiques sont pris en compte parce que les ignorer casse des
outils dans le sens le plus courant — celui ou l'on croit couper moins qu'on
ne coupe :

  - **diametre effectif d'un bec rond.** Une fraise hemispherique engagee sur
    une profondeur ``ap`` inferieure a son rayon ne coupe pas a son diametre
    nominal mais a ``D_eff = 2.sqrt(D.ap - ap^2)``. A 0,2 mm de profondeur, une
    fraise de 6 mm coupe a 2,15 mm de diametre : appliquer la vitesse de broche
    du diametre nominal divise la vitesse de coupe reelle par trois.
  - **amincissement radial du copeau.** Sous un engagement radial ``ae``
    inferieur au rayon, l'epaisseur de copeau reelle est plus faible que
    l'avance par dent programmee. Le facteur correctif est
    ``D / (2.sqrt(ae.(D - ae)))``, qui vaut 1 a ``ae = D/2``. Ne pas le poser
    fait travailler l'outil en frottement.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..machine_model.machine import MachineKinematics
from ..tool_model.assembly import ToolAssembly
from .interfaces import MaterialProfile, Quality


@dataclass(frozen=True)
class MaterialData:
    """Donnees de coupe d'une matiere, avec ce qui les fonde.

    ``uncertainty`` n'est pas decoratif : il dit de combien ces valeurs peuvent
    se tromper, et c'est ce qui interdit de les presenter comme un reglage
    optimal. Une bande de +/-50 % signifie « commence la, ecoute la machine ».
    """

    name: str
    #: Vitesse de coupe, m/min, par qualite.
    vc_m_min: dict[str, float]
    #: Avance par dent, mm, pour un outil de 6 mm ; mise a l'echelle du diametre.
    fz_mm_at_d6: dict[str, float]
    max_depth_ratio: float          # x diametre
    max_width_ratio: float          # x diametre
    source: str
    uncertainty: str = "+/-50 % : point de depart generique, non qualifie"
    notes: str = ""


#: Table des matieres connues.
#:
#: Valeurs GENERIQUES et CONSERVATRICES, de l'ordre de ce qu'on emploie sur une
#: machine legere peu rigide — pas les donnees d'un fabricant pour un outil
#: precis. Une machine en kit est deux a dix fois moins rigide qu'un centre
#: industriel, et les tables industrielles y font brouter puis casser.
#:
#: Un deploiement reel doit charger les donnees du fabricant de l'outil employe.
#: Cette table est un defaut utilisable, pas une reference.
MATERIALS: dict[str, MaterialData] = {
    "aluminium-6061": MaterialData(
        name="aluminium-6061",
        vc_m_min={"ebauche": 120.0, "equilibre": 150.0, "finition": 180.0},
        fz_mm_at_d6={"ebauche": 0.040, "equilibre": 0.030, "finition": 0.020},
        max_depth_ratio=0.5, max_width_ratio=0.4,
        source="pratique courante fraisage alu sur machine legere",
        notes="collant : exige de l'air ou du lubrifiant, sinon l'arete charge",
    ),
    "laiton": MaterialData(
        name="laiton",
        vc_m_min={"ebauche": 100.0, "equilibre": 130.0, "finition": 160.0},
        fz_mm_at_d6={"ebauche": 0.035, "equilibre": 0.025, "finition": 0.015},
        max_depth_ratio=0.5, max_width_ratio=0.4,
        source="pratique courante fraisage laiton sur machine legere",
    ),
    "acier-s235": MaterialData(
        name="acier-s235",
        vc_m_min={"ebauche": 40.0, "equilibre": 55.0, "finition": 70.0},
        fz_mm_at_d6={"ebauche": 0.020, "equilibre": 0.015, "finition": 0.010},
        max_depth_ratio=0.25, max_width_ratio=0.25,
        source="pratique courante fraisage acier doux sur machine legere",
        notes="exige une rigidite que peu de machines en kit atteignent : "
              "commencer nettement sous ces valeurs",
    ),
    "inox-304": MaterialData(
        name="inox-304",
        vc_m_min={"ebauche": 25.0, "equilibre": 35.0, "finition": 45.0},
        fz_mm_at_d6={"ebauche": 0.018, "equilibre": 0.012, "finition": 0.008},
        max_depth_ratio=0.2, max_width_ratio=0.2,
        source="pratique courante fraisage inox austenitique, machine legere",
        notes="ecrouissable : une avance trop FAIBLE durcit la matiere et use "
              "l'arete plus vite qu'une avance trop forte",
    ),
    "pom-acetal": MaterialData(
        name="pom-acetal",
        vc_m_min={"ebauche": 200.0, "equilibre": 250.0, "finition": 300.0},
        fz_mm_at_d6={"ebauche": 0.060, "equilibre": 0.045, "finition": 0.030},
        max_depth_ratio=1.0, max_width_ratio=0.5,
        source="pratique courante fraisage plastiques techniques",
    ),
    "bois-mdf": MaterialData(
        name="bois-mdf",
        vc_m_min={"ebauche": 250.0, "equilibre": 300.0, "finition": 350.0},
        fz_mm_at_d6={"ebauche": 0.080, "equilibre": 0.060, "finition": 0.040},
        max_depth_ratio=1.0, max_width_ratio=0.5,
        source="pratique courante defonceuse bois",
        notes="poussiere abrasive : aspiration necessaire, pas optionnelle",
    ),
}


class UnknownMaterialError(KeyError):
    """Matiere absente de la table. Volontairement une erreur, pas un defaut.

    Deviner les parametres d'une matiere inconnue depuis sa voisine de table
    est la facon la plus sure de casser un outil au premier engagement.
    """


@dataclass
class CuttingRecipe:
    """Recette de coupe complete, et tout ce qui la relativise."""

    material: str
    quality: str
    tool_id: str
    spindle_rpm: float
    feed_mm_min: float
    depth_of_cut_mm: float
    width_of_cut_mm: float
    #: Vitesse de coupe REELLEMENT obtenue, apres bridage par la broche.
    vc_effective_m_min: float
    #: Diametre effectif employe pour le calcul (bec rond a faible profondeur).
    effective_diameter_mm: float
    #: Facteur d'amincissement radial applique a l'avance par dent.
    chip_thinning_factor: float
    source: str
    uncertainty: str
    #: Bridages appliques, en clair. Vide = aucun.
    clamped: list[str] = field(default_factory=list)
    #: Avertissements a LIRE avant de lancer. Un bridage qui eloigne la vitesse
    #: de coupe de sa cible n'est pas un detail : c'est une recette hors
    #: domaine, et la suivre casse ou brule l'outil.
    warnings: list[str] = field(default_factory=list)
    #: Coefficient de charge applique, et pourquoi.
    derating: float = 1.0
    derating_reason: str = ""
    notes: str = ""
    #: Toujours False : le logiciel ne peut pas qualifier une chaine mecanique
    #: assemblee par l'acheteur.
    qualified: bool = False

    def lines(self) -> list[tuple[str, str]]:
        rows = [
            ("Matiere", self.material),
            ("Qualite", self.quality),
            ("Outil", self.tool_id),
            ("Vitesse de broche", f"{self.spindle_rpm:.0f} tr/min"),
            ("Avance", f"{self.feed_mm_min:.0f} mm/min"),
            ("Profondeur de passe", f"{self.depth_of_cut_mm:.2f} mm"),
            ("Engagement radial", f"{self.width_of_cut_mm:.2f} mm"),
            ("Diametre effectif", f"{self.effective_diameter_mm:.2f} mm"),
            ("Vitesse de coupe obtenue", f"{self.vc_effective_m_min:.0f} m/min"),
            ("Amincissement radial", f"x{self.chip_thinning_factor:.2f}"),
            ("Source", self.source),
            ("Incertitude", self.uncertainty),
            ("Qualifiee sur machine", "NON — point de depart a valider"),
        ]
        if self.derating != 1.0:
            rows.append(("Charge reduite a", f"{self.derating * 100:.0f} % — "
                                             f"{self.derating_reason}"))
        for c in self.clamped:
            rows.append(("Bride par", c))
        for w in self.warnings:
            rows.append(("AVERTISSEMENT", w))
        if self.notes:
            rows.append(("A savoir", self.notes))
        return rows

    def describe(self) -> str:
        base = (f"{self.material} / {self.quality} / {self.tool_id} : "
                f"S{self.spindle_rpm:.0f} F{self.feed_mm_min:.0f}, "
                f"ap {self.depth_of_cut_mm:.2f} mm, ae {self.width_of_cut_mm:.2f} mm "
                f"(Vc reelle {self.vc_effective_m_min:.0f} m/min)")
        if self.clamped:
            base += " ; bride par " + ", ".join(self.clamped)
        for w in self.warnings:
            base += f"\n  AVERTISSEMENT : {w}"
        return base + "\n  recette NON QUALIFIEE"


def effective_diameter(tool: ToolAssembly, depth_of_cut_mm: float) -> float:
    """Diametre reellement engage, pour un outil a bec rond.

    Une fraise hemispherique engagee sur ``ap`` inferieur a son rayon ne coupe
    pas a son diametre nominal : le contact se fait sur une calotte de diametre

        D_eff = 2.sqrt(D.ap - ap^2)

    Mesure de ce que cela change : a 0,2 mm de profondeur, une fraise de 6 mm
    coupe a 2,15 mm. Employer la vitesse de broche du diametre nominal donne
    donc une vitesse de coupe reelle trois fois trop faible — l'outil frotte au
    lieu de couper, et s'use bien plus vite qu'a la bonne vitesse.

    Sans rayon de bec, ou au-dela du rayon, le diametre nominal s'applique.
    """
    d = float(tool.diameter)
    r = float(tool.corner_radius)
    ap = max(float(depth_of_cut_mm), 0.0)
    if r <= 1e-9 or ap >= r:
        return d
    if ap <= 1e-9:
        # Profondeur nulle : le contact est ponctuel, le diametre effectif tend
        # vers zero et la vitesse de broche vers l'infini. On borne au dixieme
        # du nominal plutot que de rendre une valeur non physique.
        return max(d * 0.1, 1e-3)
    return 2.0 * math.sqrt(max(d * ap - ap * ap, 1e-12))


def radial_chip_thinning(diameter_mm: float, width_of_cut_mm: float) -> float:
    """Facteur d'amincissement radial du copeau.

    Sous un engagement radial ``ae`` inferieur au rayon, l'epaisseur de copeau
    reelle est plus faible que l'avance par dent programmee, dans le rapport

        D / (2.sqrt(ae.(D - ae)))

    qui vaut 1 a ``ae = D/2`` et croit quand l'engagement diminue. Ne pas le
    poser fait travailler l'outil en frottement, ce qui l'use sans enlever de
    matiere — le mode de destruction le plus courant en finition.

    Borne a 4 : au-dela l'engagement est si faible que le modele quitte son
    domaine, et multiplier l'avance par dix serait pire que de ne rien corriger.
    """
    d = float(diameter_mm)
    ae = min(max(float(width_of_cut_mm), 1e-6), d - 1e-6)
    if ae >= d / 2.0:
        return 1.0
    return float(min(d / (2.0 * math.sqrt(ae * (d - ae))), 4.0))


def build_recipe(
    material: str | MaterialData,
    tool: ToolAssembly,
    machine: MachineKinematics,
    *,
    quality: Quality | str = Quality.BALANCED,
    depth_of_cut_mm: float | None = None,
    width_of_cut_mm: float | None = None,
    derating: float | None = None,
    vc_tolerance: float = 0.25,
) -> CuttingRecipe:
    """Recette de coupe pour un couple matiere / outil, bridee par la machine.

    Chaine de calcul, dans l'ordre :

    1. profondeur et engagement par defaut, depuis les ratios de la matiere ;
    2. **diametre effectif**, car un bec rond a faible profondeur ne coupe pas
       a son diametre nominal ;
    3. vitesse de broche ``N = 1000.Vc / (pi.D_eff)`` ;
    4. **bridage par la broche**, et la vitesse de coupe reellement obtenue est
       recalculee depuis la vitesse bridee — pas depuis celle qu'on visait ;
    5. avance ``F = fz . z . N``, avec correction d'amincissement radial ;
    6. **bridage par les courses d'avance** des axes lineaires.

    Chaque bridage est enregistre dans ``clamped``. Une recette qui plafonne
    sans le dire ferait croire a une vitesse de coupe qu'on n'atteint pas.

    **``derating`` : la charge est reduite par defaut, et c'est assume.** Une
    premiere version livrait les valeurs de table en se contentant d'une note
    disant « commencer nettement en dessous » — une note qui contredit la
    valeur qu'elle accompagne ne protege personne. La machine etant un kit dont
    la rigidite depend de l'assemblage de l'acheteur, et n'etant pas qualifiee
    (ADR-007), la charge est ramenee a 50 % par defaut : profondeur, engagement
    et avance par dent. Le coefficient est rapporte, et le relever est une
    decision a prendre APRES une qualification, pas avant.

    **``vc_tolerance`` : un bridage qui eloigne trop la vitesse de coupe de sa
    cible produit un AVERTISSEMENT.** Le cas se produit sur cette machine :
    avec une broche plancher a 6 000 tr/min et une fraise de 6 mm, l'acier
    doux se coupe a 113 m/min au lieu des 40 vises — presque le triple, ce qui
    brule l'arete. Ce n'est pas un plafonnement benin, c'est une recette hors
    domaine, et le taire serait le pire service a rendre.
    """
    data = material if isinstance(material, MaterialData) else MATERIALS.get(str(material))
    if data is None:
        raise UnknownMaterialError(
            f"matiere '{material}' absente de la table. Les parametres de coupe "
            "ne se devinent pas depuis une matiere voisine : ajouter la matiere "
            f"a recipe_profiles.MATERIALS. Connues : {sorted(MATERIALS)}")

    q = quality.value if isinstance(quality, Quality) else str(quality)
    if q not in data.vc_m_min:
        raise ValueError(f"qualite '{q}' inconnue pour {data.name} "
                         f"(connues : {sorted(data.vc_m_min)})")

    d_nom = float(tool.diameter)
    z = max(int(getattr(tool, "flute_count", 0) or 2), 1)

    k = 0.5 if derating is None else float(derating)
    if not 0.0 < k <= 1.0:
        raise ValueError(f"derating={k} hors ]0, 1] : ce coefficient reduit la "
                         "charge, il ne l'augmente pas")
    reason = ("machine en kit non qualifiee : rigidite inconnue (ADR-007)"
              if derating is None else "coefficient impose par l'appelant")

    ap = (float(depth_of_cut_mm) if depth_of_cut_mm is not None
          else data.max_depth_ratio * d_nom * k)
    ae = (float(width_of_cut_mm) if width_of_cut_mm is not None
          else data.max_width_ratio * d_nom * k)
    ap = max(min(ap, data.max_depth_ratio * d_nom), 1e-4)
    ae = max(min(ae, min(data.max_width_ratio * d_nom, d_nom)), 1e-4)

    clamped: list[str] = []
    warnings: list[str] = []

    d_eff = effective_diameter(tool, ap)
    vc_target = float(data.vc_m_min[q])
    rpm = 1000.0 * vc_target / (math.pi * d_eff)

    if rpm > machine.spindle_max_rpm:
        rpm = float(machine.spindle_max_rpm)
        clamped.append(f"broche max {machine.spindle_max_rpm:.0f} tr/min")
    if rpm < machine.spindle_min_rpm:
        rpm = float(machine.spindle_min_rpm)
        clamped.append(f"broche min {machine.spindle_min_rpm:.0f} tr/min")

    # Vitesse de coupe REELLE, depuis la vitesse bridee. La viser est une
    # intention ; l'obtenir est un fait, et c'est le fait qui doit sortir.
    vc_eff = math.pi * d_eff * rpm / 1000.0

    fz6 = float(data.fz_mm_at_d6[q])
    # Mise a l'echelle du diametre : une fraise de 2 mm ne prend pas l'avance
    # par dent d'une fraise de 6 mm. La racine est le compromis usuel entre
    # proportionnalite (trop agressive en petit diametre) et constante (trop
    # timide en gros).
    fz = fz6 * math.sqrt(d_nom / 6.0) * k
    thinning = radial_chip_thinning(d_nom, ae)
    feed = fz * thinning * z * rpm

    feed_max = min(machine.x.max_feed_mm_min, machine.y.max_feed_mm_min,
                   machine.z.max_feed_mm_min)
    if feed > feed_max:
        feed = float(feed_max)
        clamped.append(f"avance max des axes {feed_max:.0f} mm/min")

    ecart = abs(vc_eff - vc_target) / max(vc_target, 1e-9)
    if ecart > vc_tolerance:
        # Diametre effectif qui donnerait la vitesse visee A CETTE vitesse de
        # broche : Vc = pi.D.N/1000, donc D = 1000.Vc/(pi.N). Un chiffre
        # actionnable vaut mieux qu'une direction.
        #
        # ATTENTION AU SENS, et une premiere version l'avait inverse : la
        # broche etant bridee, Vc croit avec D. Pour BAISSER une vitesse de
        # coupe trop elevee il faut donc un diametre plus PETIT, pas plus
        # grand. La mesure l'avait montre sans ambiguite — passer de 6 a 12 mm
        # faisait monter Vc de 113 a 226 m/min — et le conseil disait le
        # contraire.
        d_needed = 1000.0 * vc_target / (math.pi * max(rpm, 1e-9))
        if vc_eff > vc_target:
            conseil = (f"une vitesse trop elevee brule l'arete. La broche ne "
                       f"descendant pas sous {machine.spindle_min_rpm:.0f} tr/min, "
                       f"il faudrait un diametre effectif de {d_needed:.2f} mm "
                       f"au lieu de {d_eff:.2f} — donc un outil plus PETIT. "
                       "Sinon, cette matiere n'est pas au domaine de cette broche.")
        else:
            conseil = (f"une vitesse trop faible fait frotter au lieu de couper. "
                       f"La broche ne montant pas au-dela de "
                       f"{machine.spindle_max_rpm:.0f} tr/min, il faudrait un "
                       f"diametre effectif de {d_needed:.2f} mm au lieu de "
                       f"{d_eff:.2f} — donc un outil plus GRAND.")
        warnings.append(
            f"vitesse de coupe {'TROP ELEVEE' if vc_eff > vc_target else 'trop faible'} : "
            f"{vc_eff:.0f} m/min obtenus contre {vc_target:.0f} vises "
            f"({ecart * 100:.0f} % d'ecart). " + conseil)

    return CuttingRecipe(
        material=data.name, quality=q, tool_id=tool.tool_id,
        spindle_rpm=float(rpm), feed_mm_min=float(feed),
        depth_of_cut_mm=float(ap), width_of_cut_mm=float(ae),
        vc_effective_m_min=float(vc_eff),
        effective_diameter_mm=float(d_eff),
        chip_thinning_factor=float(thinning),
        source=data.source, uncertainty=data.uncertainty,
        clamped=clamped, warnings=warnings, notes=data.notes,
        derating=k, derating_reason=reason,
    )


def material_profile(name: str) -> MaterialProfile:
    """Adaptation vers le ``MaterialProfile`` declare au jalon M1.

    Conserve pour ne rien casser de ce qui l'importe deja.
    """
    d = MATERIALS.get(name)
    if d is None:
        raise UnknownMaterialError(f"matiere '{name}' inconnue")
    return MaterialProfile(
        name=d.name, surface_speed_m_min=d.vc_m_min["equilibre"],
        feed_per_tooth_mm=d.fz_mm_at_d6["equilibre"],
        max_depth_ratio=d.max_depth_ratio, max_width_ratio=d.max_width_ratio,
        source=f"{d.source} — {d.uncertainty}",
    )
