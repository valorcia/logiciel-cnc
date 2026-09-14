"""Ce qu'une trajectoire indexee demande aux axes LINEAIRES.

Le defaut que ce module corrige
-------------------------------
``evaluate_candidates`` filtrait les indexations sur les courses A et C, avec
ce commentaire : « une direction que le berceau n'atteint pas n'est pas une
option, quelle que soit la matiere qu'elle verrait ». L'argument est juste, et
il valait tout autant pour X, Y et Z — ou personne ne le tenait.

Consequence mesuree sur ``C05_ailettes_rapprochees``, machine du kit, 25 mm de
cales : le planner choisit A = -90°, C = -90° pour le volume qu'elle enleve, et
la trajectoire produite sort de la course Y sur **3 974 de ses 18 249 points**,
avec 6 mm de depassement. Rien ne le disait. Un programme qui contient des
positions hors course ne s'arrete pas a la simulation : il s'arrete a la
machine, en pleine matiere.

Pourquoi la hauteur de la piece devient une course en Y
-------------------------------------------------------
C'est la cinematique table/table qui le veut. Le berceau A tourne autour d'un
pivot situe 40 mm sous le plateau ; a A = -90° un point de la piece a la
hauteur ``z`` se retrouve en ``Y = z + 40`` dans le repere machine. Les 53 mm
de la piece, plus 25 mm de cales, plus 40 mm de pivot font 118 mm pour une
course de 120 — et le plan de degagement acheve de sortir. Sur une machine
XYZAC, la hauteur de la piece se paie donc en course Y des que le berceau
bascule, et c'est exactement le genre de fait qu'un utilisateur ne peut pas
deviner.

Les deux questions, et leurs deux portees
-----------------------------------------
1. **Une trajectoire donnee tient-elle ?** Reponse EXACTE, et sans reserve : le
   domaine des courses est une BOITE, donc convexe. Un segment dont les deux
   extremites tiennent tient donc entierement, et tester les sommets de la
   polyligne suffit. Rien n'est echantillonne ici.

   **CETTE EXACTITUDE REPOSE SUR UNE HYPOTHESE DE MACHINE**, et il faut la
   nommer : trois axes lineaires INDEPENDANTS et orthogonaux, chacun avec sa
   butee. C'est le cas d'un portique ou d'une table/table comme la XYZAC de
   reference — et ce n'est PAS le cas d'une cinematique PARALLELE (delta,
   tripode, hexapode), ou les grandeurs butees sont les positions des chariots
   et non les coordonnees cartesiennes.

   Sur une telle machine, le domaine atteignable en cartesien n'est ni une
   boite ni necessairement convexe, et une DROITE cartesienne devient une
   COURBE dans l'espace des chariots : tester ses deux extremites ne prouve
   plus rien sur ce qu'il y a entre les deux. Ce module serait alors a refaire
   — les positions de chariots seraient calculees par la cinematique inverse,
   et le segment devrait etre echantillonne, avec la reserve que cela
   introduit.

2. **Cette indexation peut-elle tenir ?** Reponse par une boite englobante,
   donc ASYMETRIQUE, et la distinction est celle de tout le projet (ADR-001 /
   D2) : les huit coins d'une boite donnent exactement l'enveloppe machine de
   cette boite, donc « la boite tient » prouve que tout ce qu'elle contient
   tient ; « la boite ne tient pas » ne prouve rien sur la trajectoire, qui
   n'occupe pas toute la boite. Un tel resultat sert a CLASSER les candidates,
   jamais a en ecarter une.

Le remede est calcule
---------------------
Un depassement est une translation : il se corrige en decalant la piece, et le
decalage se calcule. Comme les cales agissent dans le repere PIECE et le
depassement se lit dans le repere MACHINE, le vecteur rendu est
``R_machine<-piece^T . t_machine``. Deux cas se distinguent, et le second
n'admet aucun decalage : quand l'ETENDUE demandee depasse la course, la piece
sort par les deux bouts et seule une course plus longue — ou une piece plus
petite — y ferait quelque chose.
"""

from __future__ import annotations

from dataclasses import dataclass

import math

import numpy as np

#: Nom des trois axes lineaires, dans l'ordre des coordonnees.
AXES = ("X", "Y", "Z")


def _mm(v: float) -> str:
    """Une cote en mm, sans jamais afficher zero pour une valeur non nulle.

    Defaut mesure : la poche C02 sort de la course Z de 0,4 mm sur 532 de ses
    5 512 positions, et la phrase annonçait « il manque 0 mm de course Z.
    Décaler la pièce de (+0, +0, +0) mm y suffirait ». Un arrondi qui fait
    disparaitre la grandeur qu'il decrit produit une phrase fausse et
    rassurante — le pire des deux mondes. La resolution suit donc l'ordre de
    grandeur, et un depassement reste visible jusqu'au centieme.
    """
    a = abs(float(v))
    if a == 0.0:
        return "0 mm"
    if a < 0.095:
        return f"{v:.2f} mm"
    if a < 9.95:
        return f"{v:.1f} mm"
    return f"{v:.0f} mm"


@dataclass(frozen=True)
class CourseLineaire:
    """Ce que des positions demandent aux axes lineaires, et ce qui manque.

    ``exact`` porte la portee du resultat, et c'est le champ a ne pas perdre de
    vue : vrai quand les positions testees SONT celles du programme (verdict
    sans reserve, dans les deux sens), faux quand ce sont les coins d'une boite
    englobante (« tient » prouve, « ne tient pas » ne prouve rien).
    """

    a_deg: float
    c_deg: float
    #: Enveloppe machine des positions testees.
    lo: tuple[float, float, float]
    hi: tuple[float, float, float]
    #: Ce qui MANQUE sur chaque axe, en mm, 0 quand l'axe tient.
    exces_mm: tuple[float, float, float]
    #: Etendue demandee moins course disponible, par axe : positif = la piece
    #: sort par les deux bouts, et aucun decalage n'y suffira.
    etendue_excedentaire_mm: tuple[float, float, float]
    n_points: int
    n_hors: int
    exact: bool
    #: Decalage a appliquer aux cales, dans le repere PIECE, qui ramenerait
    #: tout dans les courses. ``None`` quand aucun decalage n'y suffit.
    correction_piece_mm: tuple[float, float, float] | None
    #: Pourquoi aucun decalage n'est propose, quand c'est le cas. Nomme plutot
    #: que deduit : sur une delta, « aucun remede » recouvre deux causes tres
    #: differentes — la piece est hors de PORTEE des bras, ou aucun decalage
    #: essaye ne suffit — et les deduire d'un champ cartesien produisait la
    #: phrase « il manque 0 mm de plus que toute la course X », qui ne veut
    #: rien dire sur une machine sans course X.
    motif_sans_remede: str = ""
    #: Vrai quand les butees portent sur des CHARIOTS et non sur X, Y, Z. Le
    #: depassement est alors en millimetres de RAIL, et l'axe nomme n'aurait
    #: aucun sens — les trois chariots melangent les trois coordonnees.
    parallele: bool = False

    @property
    def tient(self) -> bool:
        return max(self.exces_mm) <= 0.0

    @property
    def concluant(self) -> bool:
        """Le verdict porte-t-il sur le programme ?

        Oui toujours quand il tient — une boite qui tient contient une
        trajectoire qui tient. Non quand il ne tient pas et que le test portait
        sur une boite englobante : c'est peut-etre le coin vide de la boite qui
        depasse, pas une position du programme.
        """
        return self.tient or self.exact

    @property
    def axe_le_plus_court(self) -> str | None:
        """L'axe qui manque le plus. Un depassement sans axe nomme n'aide pas."""
        if self.tient:
            return None
        if self.parallele:
            return "chariot"
        i = int(np.argmax(self.exces_mm))
        return AXES[i]

    def consigne(self, *, remede: bool = True) -> str:
        """Ce qu'il faut changer, dit a l'operateur.

        Rendu ici et non dans l'interface : c'est ce module qui connait la
        difference entre un depassement rattrapable par les cales et une
        etendue qui excede la course, et deux tables de phrases finiraient par
        diverger.

        ``remede=False`` s'arrete au constat. A employer quand l'appelant sait
        deja que le decalage est impraticable — lui il connait la pose et le
        plateau, ce module non. Sans cela la note enchainait « décaler de
        -24 mm y suffirait » et « ce n'est pas praticable », et laissait au
        lecteur le soin de resoudre la contradiction.
        """
        if self.tient:
            return "La trajectoire tient dans les courses de la machine."
        if self.parallele and self.correction_piece_mm is None \
                and "PORTÉE" in self.motif_sans_remede:
            # Annoncer « il manque 24 mm de course » devant un point hors de
            # portee des bras ferait chercher du rail la ou il faut des bras.
            return (f"{self.n_hors} des {self.n_points} positions du programme "
                    f"sont hors du volume de travail. "
                    + self.motif_sans_remede)
        if self.parallele:
            manque = f"{_mm(self.exces_mm[0])} de course de chariot"
        else:
            manque = ", ".join(f"{_mm(self.exces_mm[i])} de course {nom}"
                               for i, nom in enumerate(AXES)
                               if self.exces_mm[i] > 0.0)
        if self.exact:
            tete = (f"{self.n_hors} des {self.n_points} positions du programme "
                    f"sortent des courses : il manque {manque}.")
        else:
            tete = (f"Cette indexation demande peut-être plus que les courses "
                    f"réglées : il manquerait {manque} à l'enveloppe de la "
                    f"pièce.")
        if not remede:
            return tete
        if self.correction_piece_mm is None and self.motif_sans_remede:
            return tete + " " + self.motif_sans_remede
        if self.correction_piece_mm is None:
            i = int(np.argmax(self.etendue_excedentaire_mm))
            return (tete + f" Aucun décalage de la pièce n'y suffirait : elle "
                    f"demande {_mm(self.etendue_excedentaire_mm[i])} de plus "
                    f"que toute la course {AXES[i]}. Il faut une course plus "
                    f"longue, ou usiner cette forme dans un autre montage.")
        # Le decalage est exprime dans le repere de la PIECE, donc dans les
        # termes ou l'operateur agit : des cales et un centrage. Seules les
        # composantes NON NULLES sont dites — « décaler de (0, 0, -6) » fait
        # chercher ce qu'il faut faire des deux zeros.
        d = np.asarray(self.correction_piece_mm, dtype=float)
        axes = [f"{_mm(d[i])} en {AXES[i]}" for i in range(3)
                if abs(d[i]) >= 0.005]
        return (tete + f" Décaler la pièce de {', '.join(axes)} dans son "
                f"propre repère y suffirait — à vérifier qu'elle ne touche "
                f"alors ni le plateau ni le berceau, ce que ce calcul ne "
                f"regarde pas.")

    def describe(self) -> str:
        etat = "TIENT" if self.tient else "DEHORS"
        portee = "trajectoire" if self.exact else "boite englobante"
        return (f"A={self.a_deg:.1f} C={self.c_deg:.1f} [{portee}] {etat} : "
                f"X[{self.lo[0]:.0f},{self.hi[0]:.0f}] "
                f"Y[{self.lo[1]:.0f},{self.hi[1]:.0f}] "
                f"Z[{self.lo[2]:.0f},{self.hi[2]:.0f}], "
                f"exces {np.round(self.exces_mm, 1).tolist()} mm, "
                f"{self.n_hors}/{self.n_points} positions dehors")


def _bornes(machine) -> tuple[np.ndarray, np.ndarray]:
    return (np.array([machine.x.min_mm, machine.y.min_mm, machine.z.min_mm],
                     dtype=np.float64),
            np.array([machine.x.max_mm, machine.y.max_mm, machine.z.max_mm],
                     dtype=np.float64))


def _course_delta(machine, M: np.ndarray, a_deg: float, c_deg: float,
                  exact: bool) -> "CourseLineaire":
    """Le meme verdict, pour une cinematique PARALLELE.

    Les butees portent sur les CHARIOTS, pas sur X, Y, Z : le depassement se
    mesure donc en millimetres de rail, et l'enveloppe cartesienne ne sert plus
    qu'a decrire ou la trajectoire est passee.

    L'exactitude survit — voir ``DeltaLineaire.segment_tient`` : le long d'un
    segment droit, la portee des bras est une parabole convexe (maximum aux
    bouts) et la position de chariot est concave (minimum aux bouts, maximum
    interieur resolu par une equation du second degre). Verifie sur 4 000
    segments contre un echantillonnage a 401 points : zero faux positif.

    Ce qui ne survit PAS, c'est le remede en forme close : le decalage qui
    ramenerait tout dans les courses ne se lit plus sur une difference de
    bornes, parce que la relation entre une translation et une position de
    chariot n'est pas lineaire. Il est donc CHERCHE puis VERIFIE — on ne
    propose que ce qu'on a re-teste.
    """
    d = machine.delta
    lo = M.min(axis=0) if len(M) else np.zeros(3)
    hi = M.max(axis=0) if len(M) else np.zeros(3)

    if len(M):
        dep = d.depassement(M)                     # (N, 3) mm de rail
        dehors = (dep > 0.0).any(axis=1)
        n_hors = int(dehors.sum())
        fini = dep[np.isfinite(dep)]
        pire = float(fini.max()) if len(fini) else 0.0
        # Un point que les bras n'atteignent pas n'est pas « un peu dehors » :
        # aucune longueur de rail ne le rattrape. Il est compte a part.
        n_hors_portee = int((~np.isfinite(dep)).any(axis=1).sum())
    else:
        n_hors = n_hors_portee = 0
        pire = 0.0

    # Les segments, exactement. Un point de passage peut sortir entre deux
    # sommets : c'est precisement ce que la non-convexite du volume autorise,
    # et ce qu'un portique interdisait.
    if exact and len(M) > 1:
        for k in range(len(M) - 1):
            if not d.segment_tient(M[k], M[k + 1]):
                n_hors = max(n_hors, 1)
                break

    correction = None
    motif = ""
    if n_hors_portee:
        motif = (f"{n_hors_portee} position(s) sont hors de PORTÉE des bras : "
                 f"aucune longueur de rail n'y changerait rien, seuls des bras "
                 f"plus longs ou une pièce plus proche de l'axe le feraient.")
    elif n_hors:
        correction = _chercher_decalage(machine, M, a_deg, c_deg)
        if correction is None:
            motif = ("Aucun décalage de la pièce jusqu'à 200 mm, dans les six "
                     "directions essayées, ne ramène la trajectoire dans le "
                     "volume de travail.")

    # L'exces est porte par le premier axe, faute de pouvoir l'attribuer a X, Y
    # ou Z : sur une delta les trois chariots melangent les trois coordonnees.
    exces = (float(pire), 0.0, 0.0)
    return CourseLineaire(
        a_deg=float(a_deg), c_deg=float(c_deg),
        lo=tuple(float(v) for v in lo), hi=tuple(float(v) for v in hi),
        exces_mm=exces,
        etendue_excedentaire_mm=(0.0, 0.0, 0.0),
        n_points=int(len(M)), n_hors=n_hors, exact=bool(exact),
        correction_piece_mm=correction, motif_sans_remede=motif,
        parallele=True)


def _chercher_decalage(machine, M: np.ndarray, a_deg: float, c_deg: float):
    """Un decalage de piece qui ramene TOUT dans les courses, ou ``None``.

    Cherche puis VERIFIE : chaque candidat est re-teste sur l'ensemble des
    positions, et rien n'est propose qui n'ait passe ce test. C'est la seule
    facon honnete de rendre un remede quand la forme close n'existe pas — et
    c'est plus sûr que la forme close, qui elle n'est jamais re-testee.

    La recherche est volontairement pauvre : les trois directions d'axe et
    leurs combinaisons a une dimension, par dichotomie sur l'amplitude. Une
    delta a un volume non convexe, donc une recherche riche trouverait parfois
    un decalage exotique qu'aucun operateur ne saurait realiser sur ses cales.
    """
    d = machine.delta
    R = machine.rotation_machine_from_part(a_deg, c_deg)
    directions = [np.array(v, dtype=float) for v in
                  ((0, 0, -1), (0, 0, 1), (1, 0, 0), (-1, 0, 0),
                   (0, 1, 0), (0, -1, 0))]
    meilleur = None
    for u in directions:
        bas, haut = 0.0, 200.0
        if not bool(d.atteignable(M + haut * u).all()):
            continue      # cette direction ne rattrape rien, meme au maximum
        for _ in range(24):                       # dichotomie au centieme
            mid = 0.5 * (bas + haut)
            if bool(d.atteignable(M + mid * u).all()):
                haut = mid
            else:
                bas = mid
        t = math.ceil(haut * 100.0) / 100.0       # par exces, comme ailleurs
        if not bool(d.atteignable(M + t * u).all()):
            continue
        if meilleur is None or t < meilleur[0]:
            meilleur = (t, u)
    if meilleur is None:
        return None
    t, u = meilleur
    return tuple(float(v) for v in (R.T @ (t * u)))


def course_lineaire(machine, points_piece: np.ndarray, mount_offset_mm,
                    a_deg: float, c_deg: float, *,
                    exact: bool) -> CourseLineaire:
    """Mesure ce que ces positions demandent aux axes X, Y et Z.

    ``points_piece`` sont dans le repere PIECE, avant les cales : c'est la
    forme sous laquelle une trajectoire sort du trancheur, et la convertir ici
    evite a l'appelant de refaire la composition cales + pivots — celle ou l'on
    oublie un pivot et ou l'on obtient une simulation juste avec une piece
    fausse.

    ``exact`` DOIT dire la verite sur ce qu'on passe : ``True`` pour les sommets
    du programme, ``False`` pour les coins d'une enveloppe. Tout le sens du
    resultat en depend, et ce module ne peut pas le deviner.
    """
    from ..kinematics_solver.solver import KinematicsSolver

    kin = KinematicsSolver(machine)
    P = np.asarray(points_piece, dtype=np.float64).reshape(-1, 3)
    off = np.asarray(mount_offset_mm, dtype=np.float64).reshape(3)
    M = np.array([kin.part_to_machine_point(p + off, a_deg, c_deg) for p in P]) \
        if len(P) else np.zeros((0, 3))

    # La question n'est pas la meme selon la machine, et elle se DEMANDE.
    if getattr(machine, "lineaire_parallele", False):
        return _course_delta(machine, M, a_deg, c_deg, exact)

    mn, mx = _bornes(machine)
    if len(M):
        lo = M.min(axis=0)
        hi = M.max(axis=0)
        dehors = ((M < mn) | (M > mx)).any(axis=1)
        n_hors = int(dehors.sum())
    else:
        lo = np.zeros(3)
        hi = np.zeros(3)
        n_hors = 0

    exces = np.maximum(np.maximum(mn - lo, hi - mx), 0.0)
    etendue = np.maximum((hi - lo) - (mx - mn), 0.0)

    # Le decalage qui ramene tout dedans, axe par axe. Impossible des qu'un axe
    # est demande sur une etendue plus longue que sa course : la piece sort
    # alors par les deux bouts, et translater ne fait que changer le bout.
    correction = None
    if not (exces <= 0.0).all() and (etendue <= 0.0).all():
        t = np.zeros(3)
        for i in range(3):
            if lo[i] < mn[i]:
                t[i] = mn[i] - lo[i]
            elif hi[i] > mx[i]:
                t[i] = mx[i] - hi[i]
        # Les cales agissent dans le repere PIECE, le depassement se lit dans
        # le repere MACHINE : la rotation est orthogonale, donc sa transposee
        # transporte en sens inverse.
        R = machine.rotation_machine_from_part(a_deg, c_deg)
        d = R.T @ t
        # Arrondi AU CENTIEME ET PAR EXCES, pour deux raisons distinctes.
        # Par exces d'abord : un decalage arrondi vers le bas laisserait la
        # trajectoire a un centieme de millimetre de la butee, donc dehors.
        # Au centieme ensuite parce que la transposee d'une rotation laisse un
        # residu de l'ordre de 1e-16, et « decaler la piece de 3,7e-16 mm en X »
        # est une consigne qu'on ne peut pas suivre.
        d = np.sign(d) * np.ceil(np.abs(d) * 100.0 - 1e-9) / 100.0
        correction = tuple(float(v) + 0.0 for v in d)

    return CourseLineaire(
        a_deg=float(a_deg), c_deg=float(c_deg),
        lo=tuple(float(v) for v in lo), hi=tuple(float(v) for v in hi),
        exces_mm=tuple(float(v) for v in exces),
        etendue_excedentaire_mm=tuple(float(v) for v in etendue),
        n_points=int(len(P)), n_hors=n_hors, exact=bool(exact),
        correction_piece_mm=correction)


def dessus_du_plateau(machine) -> float:
    """Cote du dessus du plateau C, dans le repere de la table.

    Lue sur les volumes de collision de la MACHINE, et non ecrite ici : c'est
    la meme geometrie que celle contre laquelle les collisions sont
    verifiees, et une deuxieme declaration finirait par en differer. Rend 0.0
    quand la machine ne declare pas de plateau — ne rien savoir ne doit pas
    inventer une hauteur.
    """
    haut = 0.0
    for v in getattr(machine, "collision_volumes", ()) or ():
        if v.kind == "cylinder" and v.base is not None:
            h = float(v.base[2]) + float(v.height or 0.0)
            haut = max(haut, h)
    return haut


def hauteur_sur_plateau(machine, z_bas_piece_mm: float,
                        mount_offset_mm) -> float:
    """De combien le point le plus bas de la piece surplombe le plateau.

    Sert a juger un decalage AVANT de le proposer : le calcul de course est
    purement geometrique et descendrait volontiers la piece de 30 mm, ce qui
    l'enfoncerait de 5 mm dans le plateau. Un remede impraticable est pire
    qu'un constat : il fait demonter un montage pour rien.

    Negatif = la piece traverse le plateau.
    """
    z = float(np.asarray(mount_offset_mm, dtype=np.float64).reshape(3)[2])
    return float(z_bas_piece_mm) + z - dessus_du_plateau(machine)


def coins(boite_lo, boite_hi, *, marge_mm: float = 0.0) -> np.ndarray:
    """Les huit coins d'une boite, eventuellement gonflee.

    Huit coins et non un echantillonnage : l'enveloppe machine de l'image d'une
    boite par une rotation est exactement l'enveloppe de l'image de ses coins,
    parce qu'une boite est l'enveloppe convexe de ses coins et qu'une rotation
    preserve la convexite. Ajouter des points au milieu ne changerait donc
    rien — et en retirer un changerait tout.
    """
    lo = np.asarray(boite_lo, dtype=np.float64).reshape(3) - float(marge_mm)
    hi = np.asarray(boite_hi, dtype=np.float64).reshape(3) + float(marge_mm)
    return np.array([[x, y, z] for x in (lo[0], hi[0])
                     for y in (lo[1], hi[1]) for z in (lo[2], hi[2])],
                    dtype=np.float64)


def enveloppe_indexation(machine, boite_lo, boite_hi, mount_offset_mm,
                         a_deg: float, c_deg: float, *,
                         marge_mm: float = 0.0) -> CourseLineaire:
    """Cette indexation peut-elle tenir, au vu de l'enveloppe de la piece ?

    Resultat ASYMETRIQUE, a n'employer que pour classer des candidates : voir
    l'en-tete du module. ``marge_mm`` doit couvrir ce que la trajectoire ajoute
    a la piece — rayon de l'outil, garde d'approche, plan de degagement —,
    faute de quoi un « tient » ne porterait pas sur le programme.
    """
    return course_lineaire(machine, coins(boite_lo, boite_hi, marge_mm=marge_mm),
                           mount_offset_mm, a_deg, c_deg, exact=False)
