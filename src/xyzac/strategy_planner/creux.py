"""Un creux, son outil, son orientation — et laquelle des trois etapes bloque.

Ce que ce module ajoute
-----------------------
``feature_engine.volumes`` repond a « quel outil rentre dans ce creux ». Le
solveur d'accessibilite repond a « depuis quelle orientation cette surface est
usinable ». Les deux questions etaient posees separement, et l'operateur
recevait donc deux refus sans savoir lequel comptait.

Or l'ordre est fixe, et chaque etape peut refuser pour sa propre raison :

  1. **quel volume** — la decomposition trouve un creux, ou n'en trouve pas ;
  2. **quel outil** — aucun outil de la gamme n'y entre, et alors il n'y a
     rien a orienter : la question suivante ne se pose meme pas ;
  3. **quelle orientation** — l'outil retenu rentre geometriquement, mais le
     porte-outil, le nez de broche ou les courses lineaires s'y opposent.

Nommer l'etape qui bloque, c'est nommer ce qu'il faut CHANGER : un outil plus
fin, un autre bridage, ou une seconde prise de piece. « Non usinable » tout
court n'indique aucune de ces trois actions.

Quels points bordent un creux
-----------------------------
Le creux est un tas de voxels ; ce qu'on usine, ce sont les FACES de la piece
qui le bordent. Le lien se fait par la normale : un point de contact ``p`` de
normale ``n`` borde le creux si le voxel situe juste devant lui, ``p + n.d``,
en fait partie.

Les points viennent des passes de finition, donc de la tessellation exacte, et
non des voxels. La grille sert a DESIGNER le creux, pas a decrire la surface —
les normales voxelisees d'une paroi inclinee ne prennent que six valeurs, ce
qui ferait refuser par le solveur des orientations parfaitement saines.

La question qu'on pose au solveur n'est pas celle d'une surface
---------------------------------------------------------------
Premiere version de ce module, et premiere mesure : la poche de C02 se faisait
refuser avec « 8 des 8 points sondes ne sont atteignables par AUCUNE
orientation », en accusant le plateau de la machine. C'etait faux, et le
mecanisme merite d'etre nomme.

``decide_indexed_pass`` cherche UNE orientation qui mette le bec de l'outil
face a CHAQUE point — le bec, donc a moins de ``max_lead_deg`` de la normale
locale. C'est la bonne question pour une passe de finition sur une surface,
dont tous les points regardent a peu pres dans le meme sens. Ce n'en est pas
une pour un creux : une poche est bordee d'un fond qui regarde en haut et de
quatre flancs qui regardent dans quatre directions a 90 degres du fond. Aucune
orientation ne les met tous face au bec, et il n'en manque aucune — les flancs
se coupent par le FLANC de l'outil, pas par son bec.

Un creux a donc une direction a lui : celle de sa BOUCHE, c'est-a-dire celle
d'ou on le voit le mieux. Ce module la mesure — la part du creux que
``reachable_from`` voit depuis chaque candidate — puis verifie cette direction
la avec ``verify_direction``, qui rend un motif PAR POINT. Le motif fait alors
toute la difference :

  - un point refuse pour ``LEAD_LIMIT`` regarde ailleurs : il demande une
    AUTRE orientation, ou le flanc de l'outil. Ce n'est pas un blocage ;
  - un point refuse pour ``COLLISION_CUTTING`` est bien face au bec : seul le
    cylindre de coupe touche la matiere voisine, ce qui est son travail ;
  - un point refuse pour toute autre collision, ou une butee d'axe, bloque.

Confondre ces trois tas, c'est ce que faisait la premiere version, et cela
transformait chaque poche du corpus en refus. Le detail de chaque decompte est
dans ``_compter``, avec la mesure qui l'a impose.

Le sens de l'erreur
-------------------
La distance de sondage vaut un pas de grille. Trop courte, elle laisserait des
points de bord non attribues ; trop longue, elle attribuerait a un creux des
points qui regardent ailleurs. Deux distances sont donc essayees, et un point
est retenu des que l'une des deux tombe dans le creux : un point OUBLIE serait
une surface qu'on croit usinee et qui ne l'est pas, alors qu'un point en trop
ne fait que durcir le verdict.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: L'etape qui bloque, dans l'ordre ou elles se posent.
ETAPE_VOLUME = "volume"
ETAPE_OUTIL = "outil"
ETAPE_ORIENTATION = "orientation"
ETAPE_COURSE = "course"
#: Pas un refus de la piece : un aveu du moteur.
#:
#: Le creux s'ouvre, l'outil y entre, la machine y va — mais aucun de ses points
#: de bord ne se finit au BEC depuis la bouche : ils se prennent tous au FLANC
#: de l'outil. C'est le cas d'une poche conique, dont la paroi est a plus de
#: ``max_lead_deg`` de la direction d'ouverture. Le fraisage en roulant est un
#: mode que ce moteur ne decide pas encore, et le dire est plus honnete que de
#: rendre « aucune orientation ne degage », qui accuserait la machine.
ETAPE_FLANC = "flanc"
ETAPE_AUCUNE = "aucune"

#: Ce que chaque motif de rejet veut dire, EN FRANÇAIS.
#:
#: ``COLLISION_SHANK`` est le nom que porte le motif dans le moteur. Ecrit tel
#: quel sur l'ecran d'un operateur — ce qui etait le cas — il ne veut rien dire,
#: et il a l'air d'un bout de code qui aurait fui jusqu'a la page. Le remede,
#: lui, etait deja en clair : il manquait la cause.
NOM_MOTIF = {
    "BACK_FACING": "l'outil viendrait par l'intérieur de la matière",
    "LEAD_LIMIT": "la face regarde trop loin de l'axe de l'outil",
    "AXIS_LIMITS": "l'axe A ou C est en butée",
    "SINGULARITY": "la pose est trop près de la singularité A = 0",
    "COLLISION_CUTTING": "l'arête de coupe touche",
    "COLLISION_NECK": "le col touche",
    "COLLISION_SHANK": "la tige touche",
    "COLLISION_HOLDER": "le porte-outil touche",
    "COLLISION_SPINDLE": "le nez de broche touche",
    "MACHINE_COLLISION": "l'outil touche un organe de la machine",
    "MACHINE_TRAVEL": "la pose sort des courses linéaires",
}

#: Distances de sondage devant un point de contact, en pas de grille.
SONDES_MM = (0.75, 1.5)

#: Nombre de points de contact verifies par creux.
#:
#: Meme grandeur que pour une surface (``ECHANTILLON_FINITION``), et pour la
#: meme raison : la verification coûte environ 31 ms par point, donc 150 points
#: font 5 s. Au-dela, l'operateur attend sans rien apprendre de neuf.
ECHANTILLON = 150

#: Points sondes avant de proposer un candidat d'orientation.
SONDES_ORIENTATION = 8

#: Ecart, en degres, sous lequel deux directions candidates sont la meme.
#:
#: Les normales moyennes des faces qui bordent un creux se repetent — quatre
#: flancs paralleles deux a deux en donnent deux, pas quatre — et chaque
#: direction coûte un lancer de rayons sur toute la grille, soit ~1 s.
TOLERANCE_DIRECTION_DEG = 10.0

#: Motifs de rejet qui ne BLOQUENT pas un creux, et pourquoi.
#:
#: ``LEAD_LIMIT`` : le point regarde ailleurs. Un flanc de poche a 90 degres du
#: fond n'est pas inatteignable — il se prend par le FLANC de l'outil, ou dans
#: une seconde orientation. Le compter comme un blocage faisait refuser toutes
#: les poches du corpus.
#:
#: ``COLLISION_CUTTING`` : le tronçon COUPANT de l'outil touche la piece. C'est
#: son travail. Sur le fond d'une poche, tout point situe a moins d'un rayon du
#: flanc met le cylindre de coupe en contact avec ce flanc — 8 points sur 60
#: mesures sur C02 — et cela ne dit rien d'autre que « la fraise coupe la ou
#: elle doit couper ». Le meme piege avait deja ete tendu au portillon de
#: collision, qui ecartait la meilleure indexation de C02 POUR AVOIR COUPE.
#:
#: Ce qui bloque, c'est tout le reste : le col, la tige, le porte-outil, le nez
#: de broche, les organes de la machine et les butees d'axes. Ces motifs sont
#: comptes et nommes separement, jamais additionnes aux deux ci-dessus.
MOTIFS_NON_BLOQUANTS = ("LEAD_LIMIT", "COLLISION_CUTTING")

#: Ecart de visibilite sous lequel deux directions sont a departager autrement.
#:
#: Une rainure debouchante se voit a 100 % de deux directions au moins — par le
#: dessus et par le bout. Les deux « voient tout », et pourtant l'une finit son
#: fond au bec de l'outil et l'autre ne finit rien du tout. Mesure sur C04,
#: rainure de 8 x 40 x 35 mm : departagees par l'ordre de la liste, le moteur
#: retenait le bout (A = -90, C = -180) et concluait « ce creux ne se prend
#: qu'au flanc ». Par le dessus, son fond se finit normalement.
#:
#: Les directions a moins de ce seuil de la meilleure sont donc toutes
#: verifiees, et c'est la VERIFICATION qui tranche — pas l'ordre d'une liste.
MARGE_VISIBILITE = 0.05

#: Part du creux qu'une direction doit voir pour meriter d'etre verifiee.
#:
#: En dessous, ce n'est pas la bouche du creux : c'est un flanc vu de biais.
#: Le seuil est bas exprés — il ecarte l'absurde, il ne choisit pas.
VISIBILITE_MINIMALE = 0.10


def _diam(rayon_mm: float) -> str:
    """Un diametre d'outil, sans decimale inutile.

    « Ø 10.0 mm » donne l'air d'une precision au dixieme sur une fraise qui
    s'achete au millimetre entier. Les demi-millimetres existent (Ø 2,5), donc
    la decimale reste quand elle dit quelque chose.
    """
    d = 2.0 * float(rayon_mm)
    return f"{d:.0f}" if abs(d - round(d)) < 1e-9 else f"{d:.1f}".replace(".", ",")


@dataclass(frozen=True)
class VerdictCreux:
    """Ce qu'on sait d'un creux : son outil, son orientation, ou son blocage."""

    index: int
    #: ``ETAPE_*`` : laquelle des trois etapes bloque, ``ETAPE_AUCUNE`` si rien.
    etape: str
    volume_mm3: float
    cotes_mm: str
    #: Rayon de l'outil retenu, ou ``None`` si aucun n'entre.
    rayon_mm: float | None = None
    #: Part du creux que cet outil atteint, entre 0 et 1.
    fraction: float = 0.0
    #: Faces de la piece qui bordent ce creux.
    surfaces: tuple[int, ...] = ()
    n_points: int = 0
    n_verifies: int = 0
    a_deg: float | None = None
    c_deg: float | None = None
    degagement_mm: float | None = None
    #: Part du creux que la direction retenue VOIT, entre 0 et 1.
    visibilite: float = 0.0
    #: Part des points de bord que cette orientation finit au bec de l'outil.
    part_au_bec: float = 0.0
    #: Points qui regardent ailleurs : une autre orientation, ou le flanc.
    n_ailleurs: int = 0
    #: Points ou seul le tronçon COUPANT touche : la fraise fait son travail.
    n_en_coupe: int = 0
    #: Rayon de l'outil de reprise, ou ``None`` si l'ebauche suffit.
    reprise_mm: float | None = None
    motif: str = ""

    @property
    def usinable(self) -> bool:
        return self.etape == ETAPE_AUCUNE

    @property
    def outil(self) -> str:
        return ("aucun outil" if self.rayon_mm is None
                else f"Ø {_diam(self.rayon_mm)} mm")

    def consigne(self) -> str:
        """Le creux, dit a l'operateur, en nommant ce qui bloque.

        Une phrase par etape, et chacune dit quoi CHANGER. Un « non usinable »
        unique pour les trois cas laisserait l'operateur essayer au hasard.
        """
        tete = f"{self.volume_mm3:.0f} mm³ à sortir, {self.cotes_mm}"
        if self.etape == ETAPE_OUTIL:
            return (f"{tete}. Aucun des outils de la gamme n'y entre : "
                    f"{self.motif} Il faut un outil plus fin — "
                    f"l'orientation ne se pose pas encore.")
        if self.etape == ETAPE_ORIENTATION:
            return (f"{tete}. Une fraise de {self.outil} y entre et en prend "
                    f"{self.fraction * 100:.0f} %, mais aucune orientation ne "
                    f"dégage : {self.motif}")
        if self.etape == ETAPE_COURSE:
            return (f"{tete}. Une fraise de {self.outil} y entre et une "
                    f"orientation dégage, mais {self.motif}")
        if self.etape == ETAPE_FLANC:
            return (f"{tete}. Une fraise de {self.outil} y entre, en prend "
                    f"{self.fraction * 100:.0f} %, et la machine atteint sa "
                    f"bouche à A = {self.a_deg:.0f}°, C = {self.c_deg:.0f}° — "
                    f"mais {self.motif}")
        if self.etape == ETAPE_VOLUME:
            return f"{tete}. {self.motif}"
        phrase = (f"{tete}. On ébauche à la fraise de {self.outil}, qui en "
                  f"prend {self.fraction * 100:.0f} %, par sa bouche à "
                  f"A = {self.a_deg:.0f}°, C = {self.c_deg:.0f}°"
                  + (f", dégagement {self.degagement_mm:.1f} mm."
                     if self.degagement_mm is not None else "."))
        if self.reprise_mm is not None:
            phrase += (f" Reprise à Ø {_diam(self.reprise_mm)} mm pour les "
                       f"{(1 - self.fraction) * 100:.0f} % qu'elle laisse.")
        if self.n_ailleurs:
            phrase += (f" {self.n_ailleurs} point"
                       f"{'s' if self.n_ailleurs > 1 else ''} de bord "
                       f"regarde{'nt' if self.n_ailleurs > 1 else ''} "
                       f"ailleurs : les flancs se prennent au flanc de "
                       f"l'outil, ou dans une seconde orientation.")
        return phrase

    def describe(self) -> str:
        return (f"creux {self.index} ({self.etape}) : {self.volume_mm3:.0f} mm3, "
                f"{self.outil}, {len(self.surfaces)} face(s), "
                f"{self.n_verifies}/{self.n_points} points, "
                f"vu a {self.visibilite * 100:.0f} %, "
                f"bec {self.part_au_bec * 100:.0f} %"
                + (f", A={self.a_deg:.0f} C={self.c_deg:.0f}"
                   if self.a_deg is not None else ""))


def points_du_creux(masque, grille, points, normales) -> np.ndarray:
    """Indices des points de contact qui bordent ce creux.

    ``points`` et ``normales`` decrivent la surface de la piece ; le creux est
    un masque de voxels. Un point borde le creux si le voxel devant lui en
    fait partie — voir l'en-tete pour le choix des distances de sondage.
    """
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    nrm = np.asarray(normales, dtype=np.float64).reshape(-1, 3)
    if len(pts) == 0:
        return np.zeros(0, dtype=np.int64)
    norme = np.linalg.norm(nrm, axis=1, keepdims=True)
    nrm = nrm / np.where(norme > 0.0, norme, 1.0)

    pas = float(grille.pitch)
    origine = np.asarray(grille.origin, dtype=np.float64)
    nx, ny, nz = masque.shape
    dedans = np.zeros(len(pts), dtype=bool)
    for k in SONDES_MM:
        ijk = np.floor((pts + nrm * (k * pas) - origine) / pas).astype(np.int64)
        ok = ((ijk[:, 0] >= 0) & (ijk[:, 0] < nx)
              & (ijk[:, 1] >= 0) & (ijk[:, 1] < ny)
              & (ijk[:, 2] >= 0) & (ijk[:, 2] < nz))
        idx = ijk[ok]
        if len(idx):
            touche = masque[idx[:, 0], idx[:, 1], idx[:, 2]]
            dedans[np.flatnonzero(ok)[touche]] = True
    return np.flatnonzero(dedans)


def directions_candidates(passes, indices=None) -> list[np.ndarray]:
    """Les directions a essayer sur un creux : celles de ses faces, et les axes.

    Les normales moyennes des faces qui le bordent, parce que la bouche d'un
    creux est presque toujours parallele a l'une d'elles — le fond d'une poche
    regarde par sa bouche. Les six axes en plus, parce qu'une poche debouchante
    n'a pas de fond, donc pas de face qui donne sa direction.

    Deduplique a ``TOLERANCE_DIRECTION_DEG`` : chaque direction coûte un lancer
    de rayons sur toute la grille.
    """
    brutes = []
    for i, fp in enumerate(passes):
        if indices is not None and i not in indices:
            continue
        n = np.asarray(fp.normals, dtype=np.float64).reshape(-1, 3).mean(axis=0)
        if np.linalg.norm(n) > 1e-9:
            brutes.append(n / np.linalg.norm(n))
    brutes += [np.array(v, dtype=np.float64) for v in
               ((0, 0, 1), (0, 0, -1), (1, 0, 0), (-1, 0, 0),
                (0, 1, 0), (0, -1, 0))]
    cos_tol = float(np.cos(np.radians(TOLERANCE_DIRECTION_DEG)))
    gardees: list[np.ndarray] = []
    for d in brutes:
        if not any(float(d @ g) >= cos_tol for g in gardees):
            gardees.append(d)
    return gardees


def vues_par_direction(material, directions) -> list[tuple[np.ndarray, np.ndarray]]:
    """Ce que chaque direction voit de la matiere enlevable, une fois pour toutes.

    Un lancer de rayons coûte ~1 s sur une grille au pas de 1 mm. Il ne depend
    PAS du creux : le calculer une fois par direction, et non une fois par
    couple (creux, direction), est ce qui rend l'enchainement praticable.
    """
    return [(np.asarray(d, dtype=np.float64), material.reachable_from(d))
            for d in directions]


def _compter(v) -> dict:
    """Trie les points d'une verification, et distingue trois choses.

    ``presentes`` : les points que cette orientation met FACE AU BEC, c'est-a-
    dire tous ceux que ``verify_direction`` ne rejette pas pour
    ``LEAD_LIMIT``. C'est la mesure de ce que la direction ADRESSE, avant toute
    question de collision — et c'est elle qui doit departager deux directions.

    Le defaut mesure sans elle, sur la rainure de C04 (8 x 40 x 35 mm) : vue de
    bout, la rainure « ne bloque rien », parce qu'elle ne presente rien — fond
    et flancs sont tous a 90 degres de l'axe. Vue de dessus, son fond est bien
    face au bec mais la tige de la fraise de Ø 6 touche les parois, ce qui
    donne 29 points bloques. Un classement par le nombre de BLOCAGES retenait
    donc la vue de bout, qui ne peut rien usiner, contre la vue de dessus, qui
    dit exactement quoi changer : allonger la jauge ou prendre une fraise a col
    reduit. Une direction qui n'adresse rien ne bloque rien, et ce n'est pas
    une qualite.

    ``finis`` : les points reellement finis. Il inclut ceux rejetes pour
    ``COLLISION_CUTTING``, car un tel point a passe le filtre d'inclinaison —
    le bec le regarde — et seul le cylindre de coupe touche la matiere voisine,
    ce qui est son travail. Dans une rainure de 8 mm fraisee a Ø 6, tout point
    de fond est a moins d'un rayon d'un flanc : les compter comme des echecs
    reviendrait a declarer la rainure inusinable parce que la fraise coupe.

    ``bloques`` : tout le reste — col, tige, porte-outil, nez de broche,
    organes machine, butees d'axes. Ceux-la seuls sont des refus.
    """
    from ..accessibility_solver.solver import RejectReason

    motifs: dict[str, int] = {}
    for r in v.reason[~v.ok]:
        nom = RejectReason(int(r)).name
        motifs[nom] = motifs.get(nom, 0) + 1
    ailleurs = motifs.pop("LEAD_LIMIT", 0)
    en_coupe = motifs.pop("COLLISION_CUTTING", 0)
    return {"motifs": motifs, "ailleurs": ailleurs, "en_coupe": en_coupe,
            "bloques": sum(motifs.values()),
            "presentes": int(len(v.ok)) - ailleurs,
            "finis": int(v.ok.sum()) + en_coupe}


def _fini(v):
    """La valeur, ou ``None`` si elle n'en est pas une."""
    return None if v is None or not np.isfinite(v) else float(v)


def _ac_verifie(solveur, pts, nrm, direction):
    """``verify_direction`` sur une direction donnee, avec le degagement."""
    return solveur.verify_direction(pts, nrm, direction, with_clearance=True)


def decider_creux(volume, passes, material, *, fabrique_solveur, machine,
                  mount_offset, vues=None,
                  echantillon: int = ECHANTILLON) -> VerdictCreux:
    """Enchaine les trois etapes sur UN creux, et nomme celle qui bloque.

    ``passes`` est la liste des passes de finition (chacune avec ``points`` et
    ``normals``), dans l'ordre des surfaces. ``fabrique_solveur(rayon_mm)``
    rend le couple ``(solveur, outil)`` arme de l'outil de ce rayon — c'est
    l'appelant qui sait construire un outil, pas ce module.

    ``vues`` est la liste ``(direction, masque vu)`` de ``vues_par_direction``,
    partagee entre tous les creux. Sans elle, chaque creux relance les lancers
    de rayons pour son propre compte.

    L'outil est retenu AVANT l'orientation : demander au solveur de chercher
    une orientation pour un outil qui n'entre pas geometriquement serait lui
    faire perdre son temps pour un refus deja connu.
    """
    from .travel import course_lineaire

    base = dict(index=volume.index, volume_mm3=volume.volume_mm3,
                cotes_mm=volume.cotes_mm)

    # --- etape 2 : quel outil ------------------------------------------
    #
    # L'outil d'EBAUCHE, et non celui qui vide le creux entierement : c'est lui
    # qui fait le gros du travail, donc c'est son accessibilite qui decide. Sur
    # la poche de C02, « celui qui vide » est une Ø 3 mm — une heure de
    # travail pour ce qu'une Ø 10 fait en quelques minutes.
    gros = volume.outil_d_ebauche()
    if gros is None:
        entrants = [o for o in volume.par_outil if o.entre]
        if entrants:
            meilleur = max(entrants, key=lambda o: o.fraction)
            motif = (f"le meilleur qui entre, Ø "
                     f"{_diam(meilleur.rayon_mm)} mm, n'en prend que "
                     f"{meilleur.fraction * 100:.0f} %, et n'atteint pas "
                     f"son fond.")
        else:
            motif = "aucun n'y entre, même partiellement."
        return VerdictCreux(**base, etape=ETAPE_OUTIL, motif=motif)

    # --- quels points bordent ce creux ---------------------------------
    if volume.masque is None:
        return VerdictCreux(**base, etape=ETAPE_VOLUME,
                            rayon_mm=gros.rayon_mm, fraction=gros.fraction,
                            motif="ce volume ne porte pas ses voxels : "
                                  "impossible de savoir quelles faces le "
                                  "bordent.")
    pts_l, nrm_l, surf = [], [], []
    for i, fp in enumerate(passes):
        pf = np.asarray(fp.points, dtype=np.float64)
        nf = np.asarray(fp.normals, dtype=np.float64)
        k = points_du_creux(volume.masque, material.grid, pf, nf)
        if len(k):
            pts_l.append(pf[k])
            nrm_l.append(nf[k])
            surf.append(i)
    if not pts_l:
        return VerdictCreux(**base, etape=ETAPE_VOLUME,
                            rayon_mm=gros.rayon_mm, fraction=gros.fraction,
                            motif="aucune face de la pièce ne le borde : "
                                  "ce volume est de la matière libre, pas "
                                  "un creux à usiner.")
    pts = np.concatenate(pts_l)
    nrm = np.concatenate(nrm_l)
    fins = [o for o in volume.par_outil
            if o.entre and o.rayon_mm < gros.rayon_mm
            and o.fraction > gros.fraction]
    base = dict(base, rayon_mm=gros.rayon_mm, fraction=gros.fraction,
                reprise_mm=(max(fins, key=lambda o: o.rayon_mm).rayon_mm
                            if fins else None),
                surfaces=tuple(surf), n_points=int(len(pts)))

    # --- etape 3a : par ou ce creux s'ouvre ----------------------------
    if vues is None:
        vues = vues_par_direction(material,
                                  directions_candidates(passes, set(surf)))
    n_vox = int(volume.masque.sum())
    scores = [(float((vu & volume.masque).sum()) / max(n_vox, 1), d)
              for d, vu in vues]
    scores.sort(key=lambda t: -t[0])
    vis = scores[0][0]
    if vis < VISIBILITE_MINIMALE:
        return VerdictCreux(**base, etape=ETAPE_ORIENTATION, visibilite=vis,
                            motif=(f"aucune direction n'en voit plus de "
                                   f"{vis * 100:.0f} % : ce creux est fermé "
                                   f"sur lui-même, il faut une seconde prise "
                                   f"de pièce ou un autre brut."))

    # Echantillon REGULIER : un tirage aleatoire donnerait un verdict
    # different a chaque lancement, sans que rien n'ait bouge.
    k = np.unique(np.linspace(0, len(pts) - 1,
                              min(echantillon, len(pts))).astype(int))
    base = dict(base, n_verifies=int(len(k)), visibilite=vis)

    # --- etape 3b : cette direction tient-elle sur la machine ? --------
    #
    # Toutes les directions a egalite de visibilite sont verifiees, et c'est la
    # VERIFICATION qui tranche, pas l'ordre d'une liste : voir
    # ``MARGE_VISIBILITE``. On garde celle qui PRESENTE le plus de points au
    # bec, et a egalite celle qui en bloque le moins — jamais l'inverse, car
    # une direction qui n'adresse rien ne bloque rien, et ce n'est pas une
    # qualite (voir ``_compter``).
    from ..accessibility_solver.solver import RejectReason

    solveur, outil = fabrique_solveur(gros.rayon_mm)
    meilleur = None
    for score, d in scores:
        if score < vis - MARGE_VISIBILITE:
            break
        v = _ac_verifie(solveur, pts[k], nrm[k], d)
        if v.a_deg is None:
            note = (-1, 0, score)
        else:
            c = _compter(v)
            # Ce que la direction ADRESSE d'abord, ce qu'elle bloque ensuite.
            note = (c["presentes"], -c["bloques"], score)
        if meilleur is None or note > meilleur[0]:
            meilleur = (note, v, d, score)
    _, verdict, _, vis = meilleur
    base = dict(base, visibilite=vis)
    if verdict.a_deg is None:
        return VerdictCreux(**base, etape=ETAPE_ORIENTATION,
                            motif=("la direction de la bouche sort des butées "
                                   "des axes A ou C : il faut reposer la "
                                   "pièce autrement."))
    compte = _compter(verdict)
    motifs = compte["motifs"]
    base = dict(base, part_au_bec=compte["finis"] / max(len(k), 1),
                n_ailleurs=compte["ailleurs"], n_en_coupe=compte["en_coupe"],
                a_deg=float(verdict.a_deg), c_deg=float(verdict.c_deg))
    if compte["presentes"] == 0:
        return VerdictCreux(**base, etape=ETAPE_FLANC,
                            motif=("aucun de ses points de bord ne se présente "
                                   "au bec depuis la bouche : ils se prennent "
                                   "tous au flanc de l'outil, et le fraisage "
                                   "en roulant n'est pas encore décidé par "
                                   "ce moteur."))
    if compte["bloques"] > 0:
        detail = ", ".join(
            f"{v} parce que {NOM_MOTIF.get(nom, nom)}"
            for nom, v in sorted(motifs.items(), key=lambda t: -t[1]))
        # Le remede, et non le seul motif : un rejet muet n'aide personne, et
        # le solveur sait deja quoi changer pour chaque motif. Celui du motif
        # DOMINANT, parce qu'en lever un seul suffit souvent a lever les
        # autres — une jauge plus longue degage la tige ET le porte-outil.
        from ..accessibility_solver.solver import REMEDY

        pire = max(motifs.items(), key=lambda t: t[1])[0]
        remede = REMEDY.get(RejectReason[pire])
        if remede:
            detail += f" ; à changer : {remede}"
        return VerdictCreux(**base, etape=ETAPE_ORIENTATION,
                            motif=(f"{compte['bloques']} des "
                                   f"{compte['presentes']} points présentés "
                                   f"au bec "
                                   f"{'est bloqué' if compte['bloques'] == 1 else 'sont bloqués'}"
                                   f" ({detail})."))
    # Le degagement est celui des tronçons NON COUPANTS — ``clearance`` et non
    # ``margin`` : cette derniere est dominee par le tronçon coupant, tangent a
    # la surface par construction, donc vaut ~0 partout. C'est le meme piege
    # que le certificat de gouge du jalon M6, et il se tend a chaque fois.
    #
    # Et il se lit sur tous les points NON BLOQUES, pas sur les seuls points
    # `ok` : ``min_clearance()`` ecarte les points en coupe, qui sont
    # justement ceux ou le porte-outil passe le plus pres du flanc. Sur C02
    # avec une Ø 10 mm, `ok` ne retenait qu'un point sur soixante, et le
    # degagement annonce etait celui de ce point-la.
    degagement = None
    if verdict.clearance is not None:
        interdits = np.zeros(len(k), dtype=bool)
        for nom in motifs:
            interdits |= (verdict.reason == int(RejectReason[nom]))
        cl = np.asarray(verdict.clearance)[~interdits]
        cl = cl[np.isfinite(cl)]
        degagement = float(cl.min()) if cl.size else None

    # --- etape 3c : les courses lineaires ------------------------------
    from ..accessibility_solver.solver import tcp_from_contact

    axe = machine.tool_axis_in_part(verdict.a_deg, verdict.c_deg)
    vus = k[np.asarray(verdict.ok, dtype=bool)
            | (np.asarray(verdict.reason) == int(RejectReason.COLLISION_CUTTING))]
    if not len(vus):
        vus = k[np.asarray(verdict.ok, dtype=bool)]
    tcp = np.array([tcp_from_contact(pts[j], nrm[j], axe, outil) for j in vus])
    course = course_lineaire(machine, tcp, mount_offset,
                             verdict.a_deg, verdict.c_deg, exact=True)
    if not course.tient:
        return VerdictCreux(**base, etape=ETAPE_COURSE,
                            motif=course.consigne())
    return VerdictCreux(**base, etape=ETAPE_AUCUNE,
                        degagement_mm=degagement,
                        motif="")
