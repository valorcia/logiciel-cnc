"""Decider l'indexation d'une passe de finition COMPLETE, et non d'un prefixe.

Le probleme que ce module resout
--------------------------------
Jusqu'ici la finition etait planifiee sur un **prefixe contigu** de chaque
passe, faute de pouvoir en payer la totalite : un point de contact coûte 65 ms
en resolution complete, et une gamme de finition du dome C10 compte 159 899
points, soit prés de trois heures. Le plan etait donc une maquette, et — bien
pire — le MODE qu'elle annoncait etait celui du prefixe. Le meme dome rapportait
``{3+2: 3, simultane: 2, inaccessible: 3}`` a 2 % de couverture et
``{3+2: 2, simultane: 4, inaccessible: 2}`` a 18 %.

Ce n'etait pas une imprecision mais une consequence necessaire de la regle du
moteur : le mode sort de l'INTERSECTION des ensembles admissibles, et une
intersection ne peut que retrecir quand on ajoute des points. Un prefixe donne
donc systematiquement un mode OPTIMISTE.

Le renversement
---------------
Explorer et verifier ne coûtent pas la meme chose. ``solve_point`` teste 642
directions filtrees pour DECOUVRIR ce qui est possible : 65 ms. Verifier UNE
orientation deja connue demande un seul test exact, vectorisable sur les
points : 1,6 ms. Soit un facteur 40.

La decision se fait donc en deux temps, et le second porte sur la passe
ENTIERE :

1. **sondage** — resolution complete en quelques points repartis. Leur
   intersection donne des CANDIDATS. C'est une hypothese, jamais une
   conclusion : l'intersection sur un echantillon majore l'intersection reelle.
2. **verification** — chaque candidat est teste en CHAQUE point de la passe.
   Un candidat qui degage partout est une preuve ; un candidat qui echoue
   nomme le point et le tronçon fautifs.

Ce que ce module ne fait pas
----------------------------
La trajectoire SIMULTANEE. Elle demande le champ admissible complet en chaque
point, et reste hors de portee — trois heures pour le dome. Ce module rend donc
decidable le 3+2, positivement comme negativement, et il le dit quand la
reponse est « pas en 3+2 » sans pouvoir proposer l'alternative.

Un point du sondage inaccessible pour TOUTE orientation est en revanche un
verdict definitif, et pas seulement contre le 3+2 : aucune trajectoire, meme
simultanee, ne passera par la.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class IndexedPassVerdict:
    """Ce qu'on sait de l'indexation d'une passe, et sur quelle portee.

    ``coverage`` vaut 1.0 des que la verification a eu lieu : c'est la raison
    d'etre de ce module. Le champ existe quand meme, parce qu'un verdict rendu
    sans verification (sondage concluant a l'impossible) ne porte que sur les
    points sondes — et il faut pouvoir le distinguer.
    """

    n_points: int
    #: "3+2" | "pas-3+2" | "inatteignable"
    verdict: str
    a_deg: float | None = None
    c_deg: float | None = None
    #: Degagement minimal des tronçons NON COUPANTS, sur toute la passe.
    #: La marge tous tronçons confondus ne veut rien dire : l'arete de coupe
    #: est tangente a la surface par construction (voir ``DirectionVerdict``).
    min_clearance_mm: float | None = None
    #: Part des points de la passe EXAMINES. A ne pas confondre avec la portee
    #: de la conclusion : voir ``basis`` et ``conclusive``.
    coverage: float = 0.0
    #: Sur quoi la conclusion repose :
    #:   "verification"  — une orientation testee en CHAQUE point ;
    #:   "contre-exemple" — un point sonde qu'aucune orientation n'atteint ;
    #:   "intersection-vide" — aucune orientation commune aux points sondes.
    #:
    #: Les trois sont des conclusions, pas des echantillons, et c'est le point
    #: a ne pas manquer : une intersection calculee sur un sous-ensemble
    #: CONTIENT celle de l'ensemble, donc vide sur 24 points implique vide sur
    #: 73 792. Le rapport annonçait « MAQUETTE : 0,2 % de la passe » pour un
    #: verdict definitif — une phrase qui sous-estimait son propre resultat.
    basis: str = ""
    n_probe: int = 0
    n_probe_unreachable: int = 0
    #: Indices (dans la passe) des points sondes qu'aucune orientation
    #: n'atteint, et ce qui les bloque. Sans cela le verdict est un constat
    #: sans prise : « inatteignable » ne dit pas quoi changer.
    unreachable_points: list[int] = field(default_factory=list)
    unreachable_reasons: dict[str, int] = field(default_factory=dict)
    n_candidates: int = 0
    n_verified: int = 0
    #: Meilleure fraction degagee atteinte par un candidat, quand aucun ne
    #: degage partout. Dit s'il a manque un point ou la moitie de la passe.
    best_clear_fraction: float = 0.0
    first_failure: int | None = None
    failure_reasons: dict[str, int] = field(default_factory=dict)
    seconds: float = 0.0
    detail: str = ""

    @property
    def indexable(self) -> bool:
        return self.verdict == "3+2"

    @property
    def conclusive(self) -> bool:
        """Le verdict porte-t-il sur la passe entiere ?

        Oui dans les trois cas, mais pas au meme titre, et la difference est
        reelle :

        * ``verification`` — conclusion PLEINE. Une orientation est exhibee et
          testee exactement en chaque point.
        * ``contre-exemple`` et ``intersection-vide`` — conclusions negatives
          valables **a la resolution de la grille de directions** (8,6 deg a
          ``subdivisions=3``). Le solveur teste 642 directions plus des germes ;
          qu'aucune ne degage n'interdit pas formellement qu'une direction
          INTERMEDIAIRE le fasse. Raffiner la grille est la seule facon de
          resserrer cette reserve, et elle est enoncee ici plutot que passee
          sous silence.

        Cette asymetrie est structurelle : le positif s'etablit par exemple, le
        negatif par epuisement, et un epuisement sur un ensemble discret n'est
        jamais qu'un epuisement sur cet ensemble.
        """
        return self.basis in ("verification", "contre-exemple",
                              "intersection-vide")

    def consigne(self) -> str:
        """Le meme verdict, mais dit a l'OPERATEUR : ce qu'on a trouve, ou
        ce qu'il faut changer.

        ``describe()`` s'adresse a qui lit un rapport de moteur : il nomme la
        base du verdict, la resolution de la grille, les compteurs. Une
        personne devant la machine n'a pas ces categories ; elle a une piece
        posee et une decision a prendre. La phrase est donc rendue ICI, et non
        dans l'interface : le remede vient de ``_remede``, donc du meme endroit
        que celui qui connait les motifs. Redigee dans l'IHM, elle aurait
        reconstruit une table de remedes a cote de celle-ci, et les deux
        auraient diverge.

        Aucune phrase n'est ecrite en dur pour un manque : tout sort des
        champs mesures. Une phrase ecrite survit a la disparition de ce
        qu'elle decrit.
        """
        if self.n_points == 0:
            return "Aucun point à usiner sur cette surface."
        if self.indexable:
            deg = ("" if self.min_clearance_mm is None
                   else f", dégagement {self.min_clearance_mm:.1f} mm")
            return (f"Orientation trouvée : A = {self.a_deg:.0f}°, "
                    f"C = {self.c_deg:.0f}°{deg}, vérifiée en chacun des "
                    f"{self.n_points} points examinés.")
        if self.verdict == "inatteignable":
            return (f"{self.n_probe_unreachable} des {self.n_probe} points "
                    f"sondés ne sont atteignables par AUCUNE orientation : "
                    f"ni 3+2 ni simultané ne passeront là. Ce qui bloque : "
                    f"{_remede(self.unreachable_reasons)}.")
        if self.basis == "intersection-vide":
            return ("Aucune orientation unique ne dégage sur toute la "
                    "surface : il faudrait du 5 axes simultané, que le "
                    "moteur ne calcule pas encore.")
        # « Les 1 orientations essayées » : l'accord se calcule, il ne
        # s'ecrit pas. Un pluriel invariable dans une phrase affichee a
        # l'operateur se lit comme une phrase generee, donc comme une phrase
        # qu'on n'a pas relue.
        if self.n_verified == 1:
            tete = "La seule orientation candidate dégage"
        else:
            tete = f"Les {self.n_verified} orientations essayées dégagent"
        return (f"{tete} au mieux "
                f"{self.best_clear_fraction * 100:.0f} % de la surface : il "
                "faudrait du 5 axes simultané, que le moteur ne calcule pas "
                "encore.")

    def describe(self) -> str:
        head = f"{self.n_points} points : {self.verdict}"
        if self.indexable:
            head += (f" A={self.a_deg:.2f} C={self.c_deg:.2f}, degagement hors "
                     f"coupe min {self.min_clearance_mm:.2f} mm")
        if self.basis == "verification":
            head += f" — VERIFIE en chacun des {self.n_points} points"
        elif self.basis == "contre-exemple":
            head += (f" — DEFINITIF : contre-exemple sur {self.n_probe} points "
                     "sondes (a la resolution de la grille)")
        elif self.basis == "intersection-vide":
            head += (f" — DEFINITIF : intersection vide sur {self.n_probe} "
                     "points sondes, donc vide sur la passe (a la resolution "
                     "de la grille)")
        if self.detail:
            head += f" ; {self.detail}"
        return head


def decide_indexed_pass(
    solver, points: np.ndarray, normals: np.ndarray, *,
    n_probe: int = 24,
    max_candidates: int = 6,
    block: int | None = None,
) -> IndexedPassVerdict:
    """Decide si une passe est indexable, en la verifiant en entier.

    ``n_probe`` points REPARTIS, et non un prefixe : ici on cherche a faire
    RETRECIR l'intersection le plus vite possible, donc il faut des points
    dissemblables. C'est l'inverse du choix fait pour une maquette, ou un
    prefixe contigu preservait la continuite du chemin. Les deux choix sont
    justes pour leur usage, et les confondre donnerait soit une intersection
    trop large, soit une trajectoire qui n'existe pas.

    ``max_candidates`` borne le coût : chaque candidat coûte une passe complete
    de verification. On les essaie dans l'ordre des marges du sondage, et on
    retient celui dont le DEGAGEMENT MINIMAL est le plus grand — pas le premier
    qui passe. Mesure sur les parois du dome C10 : le premier candidat donne
    12,0 mm, le meilleur des six 16,1 mm. Prendre le premier serait accepter
    25 % de degagement en moins sans raison.
    """
    import time

    t0 = time.time()
    points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    normals = np.asarray(normals, dtype=np.float64).reshape(-1, 3)
    n = len(points)
    if n == 0:
        return IndexedPassVerdict(n_points=0, verdict="inatteignable",
                                  basis="", detail="passe vide")

    probe = np.unique(np.linspace(0, n - 1, min(n_probe, n)).astype(int))
    inter = None
    unreachable = 0
    bad_pts: list[int] = []
    bad_why: dict[str, int] = {}
    best_margins = None
    for k in probe:
        m = solver.solve_point(points[k], normals[k])
        if not m.accessible:
            unreachable += 1
            bad_pts.append(int(k))
            r = m.dominant_reason()
            nom = r.name if r is not None else "INCONNU"
            bad_why[nom] = bad_why.get(nom, 0) + 1
            continue
        f = m.feasible_mask_full()
        inter = f if inter is None else (inter & f)
        mf = m.margin_full()
        best_margins = mf if best_margins is None else np.minimum(best_margins, mf)

    if unreachable:
        # Definitif, et pas seulement contre le 3+2 : un point qu'AUCUNE
        # orientation n'atteint ne sera pas atteint davantage par une
        # trajectoire simultanee.
        return IndexedPassVerdict(
            n_points=n, verdict="inatteignable", n_probe=len(probe),
            n_probe_unreachable=unreachable,
            unreachable_points=bad_pts, unreachable_reasons=bad_why,
            coverage=len(probe) / n, basis="contre-exemple",
            seconds=time.time() - t0,
            detail=(f"{unreachable}/{len(probe)} points sondes ne sont "
                    "atteignables par AUCUNE orientation : ni 3+2 ni simultane "
                    f"ne couvriront cette passe. Motifs {bad_why} ; premiers "
                    f"points {bad_pts[:5]}. "
                    + _remede(bad_why)))

    n_i = 0 if inter is None else int(inter.sum())
    if n_i == 0:
        return IndexedPassVerdict(
            n_points=n, verdict="pas-3+2", n_probe=len(probe),
            coverage=len(probe) / n, basis="intersection-vide",
            seconds=time.time() - t0,
            detail=("intersection vide des ensembles admissibles sur les points "
                    "sondes : aucune orientation unique ne peut degager partout, "
                    "il faut du simultane (trajectoire non calculee)"))

    idx = np.flatnonzero(inter)
    ordre = idx[np.argsort(-best_margins[idx])]
    retenu = None
    n_verified = 0
    best_frac = 0.0
    premier_echec = None
    motifs: dict[str, int] = {}
    for gi in ordre[:max_candidates]:
        d = solver.grid.directions[gi]
        v = solver.verify_direction(points, normals, d, block=block,
                                    with_clearance=True)
        n_verified += 1
        if v.clear_fraction > best_frac:
            best_frac = v.clear_fraction
            premier_echec = v.first_failure()
            motifs = v.reason_counts()
        if v.clears_all:
            if retenu is None or (v.min_clearance() or -np.inf) > (retenu.min_clearance() or -np.inf):
                retenu = v

    if retenu is not None:
        return IndexedPassVerdict(
            n_points=n, verdict="3+2", a_deg=retenu.a_deg, c_deg=retenu.c_deg,
            min_clearance_mm=retenu.min_clearance(), coverage=1.0,
            basis="verification",
            n_probe=len(probe), n_candidates=n_i, n_verified=n_verified,
            best_clear_fraction=1.0, seconds=time.time() - t0)

    return IndexedPassVerdict(
        n_points=n, verdict="pas-3+2", coverage=1.0, basis="verification",
        n_probe=len(probe),
        n_candidates=n_i, n_verified=n_verified,
        best_clear_fraction=best_frac, first_failure=premier_echec,
        failure_reasons=motifs, seconds=time.time() - t0,
        detail=(f"{n_verified} candidats verifies sur la passe ENTIERE, aucun ne "
                f"degage partout ; le meilleur couvre "
                f"{best_frac * 100:.1f} %. Il faut du simultane "
                "(trajectoire non calculee)"))


def _remede(motifs: dict[str, int]) -> str:
    """Que changer, d'apres ce qui bloque. Un rejet muet n'aide personne.

    Les remedes sont ceux que la geometrie autorise, et pas des generalites :
    un porte-outil qui touche se corrige par la jauge, un depassement de
    course par la position de la piece, une inaccessibilite de face inferieure
    par un RETOURNEMENT — c'est-a-dire un second montage, que le moteur ne
    sait pas encore ordonnancer.

    Ces phrases sont ACCENTUEES, contrairement au reste du module : elles sont
    les seules que l'operateur lit telles quelles, au travers de
    ``consigne()``. Une table interne doublee d'une table affichable finirait
    par diverger, et celle qui aurait diverge serait celle qu'on lit a
    l'ecran : il n'y en a donc qu'une.
    """
    if not motifs:
        return ""
    dominant = max(motifs, key=lambda k: motifs[k])
    return {
        "COLLISION_CUTTING": "l'arête de coupe elle-même ne rentre pas : le "
                             "rayon local de la surface est plus petit que le "
                             "bec de l'outil. Aucun montage n'y changera rien, "
                             "il faut un outil de bec plus petit",
        "LEAD_LIMIT": "aucune direction ne tient dans l'inclinaison admise : "
                      "relever l'inclinaison maximale si la surface le "
                      "supporte, sinon un outil plus court",
        "COLLISION_HOLDER": "le porte-outil touche : allonger la jauge",
        "COLLISION_SPINDLE": "le nez de broche touche : allonger la jauge",
        "COLLISION_SHANK": "la tige touche : outil plus long ou col plus fin",
        "COLLISION_NECK": "le col touche : il faut un outil à col réduit",
        "MACHINE_COLLISION": "l'outil touche un organe de la machine "
                             "(plateau, berceau) : rehausser ou décaler la "
                             "pièce, ou la retourner si cette face regarde le "
                             "plateau",
        "MACHINE_TRAVEL": "hors course linéaire : rapprocher la pièce du "
                          "centre du plateau",
        "AXIS_LIMITS": "aucun couple (A, C) ne réalise l'orientation requise : "
                       "cette face demande un second montage",
        "SINGULARITY": "orientation quasi verticale rejetée comme singulière : "
                       "en 3+2 le plateau est bloqué, donc A = 0 est "
                       "utilisable",
        "BACK_FACING": "la normale regarde à l'opposé de tout accès : il faut "
                       "un second montage",
    }.get(dominant, f"motif dominant {dominant}")
