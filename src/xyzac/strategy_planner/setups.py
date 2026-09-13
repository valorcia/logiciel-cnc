"""Ordonnancer plusieurs MONTAGES, quand une seule pose ne suffit pas.

Le trou que ce module comble
----------------------------
Depuis le jalon M10 le moteur sait dire, sur la passe entiere, qu'une face est
inatteignable — et il nomme le remede. Sur le dome C10, quatre passes sur huit
rendent ``AXIS_LIMITS`` avec pour remede « cette face demande un second
montage ». Le verdict etait juste et personne ne l'ordonnançait : le plan
s'arretait sur un constat.

Ce que « remonter la piece » veut dire dans ce moteur
----------------------------------------------------
Le champ d'obstacles ne contient que la piece, le brut et les bridages — tout
ce qui tourne AVEC la piece ; les organes machine sont traites a part par
``MachineGuard``. Un remontage est donc exactement une **rotation du repere
piece**, et il suffit de faire tourner le champ, les points de passe et leurs
normales. Aucune modification du solveur n'est necessaire, et l'equivalence
avec un remontage physique est exacte plutot qu'approchee.

**Six candidats, et non vingt-quatre.** Le cube a 24 rotations, mais l'axe C de
cette machine est continu : deux montages qui ne different que par une rotation
autour du Z du montage sont **le meme montage**, la machine faisant la
difference toute seule. Ne restent donc que les six choix de la face posee sur
le plateau. C'est la cinematique de la machine qui reduit l'espace de
recherche, pas une heuristique.

Ce que ce module ne fait pas
----------------------------
Il ne transfere aucune origine. Chaque montage **rereference la piece**, donc
il exige son propre palpage, et les budgets d'incertitude **se composent** :
une tolerance etablie dans un montage ne vaut pas d'un montage a l'autre. Voir
``SetupPlan.tolerance_warning``, et ``CalibrationRecord.tolerance_statement``
qui reste le seul endroit autorise a enoncer une precision.

Il n'ordonne pas non plus les bridages : le banc ne connait pas de bridage, et
un bridage reel retire des orientations. Une couverture obtenue sans bridage
est donc **optimiste**, et le plan le dit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..collision_engine.field import ObstacleField

#: Rehausseur par defaut sous la piece, en mm. Voir ``derive_mount``.
RISER_MM = 25.0

#: Facteur applique au diametre pour l'outil de SONDAGE, quand l'appelant en
#: fournit un. Ce n'est pas un outil « ponctuel ».
#:
#: **Pourquoi pas un outil ponctuel.** La premiere version de ce module testait
#: les points durs avec un bec de 0,1 mm, pour conclure « aucun rayon de bec ne
#: leve ce point, donc c'est la geometrie ». La mesure a demoli ce
#: raisonnement : le champ d'obstacles est gonfle d'au moins 1,26 mm au pas
#: d'echantillonnage courant (1,5 mm), soit DOUZE FOIS le rayon du bec sonde.
#: Un tel outil est bloque par le gonflement seul, et son echec ne prouve
#: rien. Au pas de 0,5 mm, le meme point devient atteignable.
#:
#: C'est la troisieme apparition de la meme faute dans ce projet : une grandeur
#: dominee par une autre, et lue comme si elle mesurait ce qu'on voulait (la
#: marge du certificat de gouge en M6, la marge tous tronçons en M10).
#:
#: Le test decidable est donc : un outil REELLEMENT plus petit — moitie de
#: diametre — leve-t-il ces points ? La reponse est actionnable, et la question
#: « existe-t-il un rayon nul qui passerait » est laissee ouverte, parce que le
#: test discret ne sait pas decider au-dessous de son propre gonflement
#: (ADR-001 / D2).
PROBE_TOOL_SCALE = 0.5


def derive_mount(bbox_lo, bbox_hi, *, riser_mm: float = RISER_MM,
                 ) -> tuple[float, float, float]:
    """Montage PROPOSE : piece centree sur l'axe C, posee sur un rehausseur.

    Ce n'est pas un detail d'affichage, et c'est pourquoi ce calcul vit ici et
    non dans l'interface. Sur une machine table/table, une piece decentree de
    ``d`` tourne a ``d`` du centre du plateau : ses faces eloignees sortent des
    courses ou balaient le berceau, et le solveur les declare inaccessibles a
    bon droit — pour une raison qui n'est pas celle de la piece.

    Mesure sur le dome C10 (60 x 60 mm, repere au coin) : a un montage fixe
    ``(0, 0, 25)``, deux des quatre parois verticales sont declarees
    inatteignables et deux accessibles — une asymetrie sans aucune cause
    geometrique. Centree et rehaussee, les quatre offrent 35 a 38 orientations.

    **Pourquoi 25 mm de rehausseur**, et le critere n'est pas « le plus de
    degagement possible » mais « n'introduire aucune limite nouvelle » :

        rehausseur 10 mm : 2 parois inatteignables, 2 a 99,6 %
        rehausseur 25 mm : 4 parois en 3+2, degagement 12,7 a 14,1 mm
        rehausseur 40 mm : 4 parois en 3+2, degagement 14,4 a 16,8 mm
        rehausseur 60 mm : 4 parois en 3+2, mais le dome bute en COURSE

    A 60 mm la course lineaire se met a buter et **masque la vraie cause** du
    rejet sur le dome, qui est que l'arete de coupe ne rentre pas dans le rayon
    local. Monter plus haut achete du degagement au prix d'un diagnostic faux.

    La valeur rendue est une HYPOTHESE de montage, a afficher comme telle : le
    moteur ne connait pas le montage reel. Ce qu'il ne doit pas faire, c'est en
    choisir un mauvais en silence.
    """
    lo = np.asarray(bbox_lo, dtype=np.float64)
    hi = np.asarray(bbox_hi, dtype=np.float64)
    return (-0.5 * float(lo[0] + hi[0]),
            -0.5 * float(lo[1] + hi[1]),
            float(riser_mm) - float(lo[2]))


@dataclass(frozen=True)
class PartOrientation:
    """Une pose de la piece sur le plateau, decrite par sa rotation.

    ``rotation`` transporte du repere PIECE vers le repere du MONTAGE. Le
    moteur travaille ensuite dans ce repere-la, ce qui rend le remontage
    transparent pour le solveur.
    """

    name: str
    rotation: np.ndarray
    #: Quelle direction de la piece regarde le plateau. Sert au libelle, et
    #: c'est l'information que l'operateur doit lire pour poser la piece.
    face_down: str = ""

    def points(self, p: np.ndarray) -> np.ndarray:
        return np.asarray(p, dtype=np.float64).reshape(-1, 3) @ self.rotation.T

    def directions(self, d: np.ndarray) -> np.ndarray:
        """Les normales tournent comme les points : la rotation est orthogonale,
        donc pas de transposee inverse a sortir. Le noter evite la correction
        de trop, qui est l'erreur classique sur les normales."""
        v = np.asarray(d, dtype=np.float64).reshape(-1, 3) @ self.rotation.T
        n = np.linalg.norm(v, axis=1, keepdims=True)
        return v / np.maximum(n, 1e-12)

    def field(self, f: ObstacleField) -> ObstacleField:
        return ObstacleField(self.points(f.points), f.classes.copy(),
                             f.inflation.copy())


def _rot(axis: str, deg: float) -> np.ndarray:
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    if axis == "x":
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float64)
    if axis == "y":
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float64)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float64)


#: Les SIX montages distincts. Aucune rotation autour de Z n'y figure : l'axe C
#: la realise sans remonter la piece, et l'y mettre ferait croire a un cout de
#: remontage qui n'existe pas.
CANONICAL_MOUNTS: tuple[PartOrientation, ...] = (
    PartOrientation("tel quel", np.eye(3), "-Z de la piece"),
    PartOrientation("retourne", _rot("x", 180.0), "+Z de la piece"),
    PartOrientation("couche sur +X", _rot("y", 90.0), "+X de la piece"),
    PartOrientation("couche sur -X", _rot("y", -90.0), "-X de la piece"),
    PartOrientation("couche sur +Y", _rot("x", -90.0), "+Y de la piece"),
    PartOrientation("couche sur -Y", _rot("x", 90.0), "-Y de la piece"),
)


def ideal_machine(machine):
    """La meme machine, sans butees ni organes : une MACHINE IDEALE.

    A quoi cela sert, et c'est le coeur de ce module. Un booleen
    « atteignable » confond deux questions distinctes :

      1. **ce montage** presente-t-il cette surface a l'outil ?
      2. l'**outil** rentre-t-il dans cette surface ?

    La premiere depend du montage, la seconde n'en depend pas du tout : le
    champ d'obstacles tourne avec la piece, donc une collision entre l'outil et
    la piece a une direction donnee du repere piece est la meme dans tous les
    montages. Ce qui change d'un montage a l'autre, c'est l'ensemble des
    directions ATTEIGNABLES.

    Tester le point sur une machine ideale — toutes les directions permises —
    separe donc les deux : s'il echoue encore, aucun montage n'y changera rien.

    Sans cette separation, le plan disait « aucun des six montages ne rend ces
    passes atteignables, revoir l'outil ou le bridage » — un fourre-tout. Alors
    que la mesure dit, elle : retournee, la passe 1 n'a qu'UN point de sondage
    en echec sur huit, et pour cause d'arete de coupe. Le retournement ouvre la
    face ; c'est l'outil qui bloque, et c'est une autre decision.
    """
    m = machine.model_copy(deep=True)
    for ax in (m.x, m.y, m.z):
        ax.min_mm, ax.max_mm = -1e6, 1e6
    for ax in (m.a, m.c):
        ax.min_deg, ax.max_deg = -360.0, 360.0
    m.collision_volumes = []
    return m


@dataclass
class PassScreen:
    """Ce qu'un depistage dit d'une passe dans un montage donne."""

    pass_index: int
    reachable: bool
    n_probe: int
    n_unreachable: int
    reasons: dict[str, int] = field(default_factory=dict)
    #: Points inatteignables MEME sur une machine ideale : aucun montage n'y
    #: changera rien. Se subdivise en deux causes tres differentes, voir
    #: ``n_radius_limited``.
    n_tool_limited: int = 0
    tool_reasons: dict[str, int] = field(default_factory=dict)
    #: Points inatteignables meme sur machine ideale AVEC UN OUTIL DE SONDAGE
    #: reellement plus petit (moitie de diametre). Un outil deux fois plus fin
    #: ne les leve donc pas.
    #:
    #: Ce n'est PAS « aucun rayon ne les leve » : le test discret ne sait pas
    #: decider au-dessous de son propre gonflement (ADR-001 / D2), et un bec
    #: plus fin que ce gonflement serait bloque par lui seul. La question du
    #: rayon nul reste donc ouverte, et le rapport le dit.
    n_probe_tool_fails: int = 0
    #: Gonflement minimal du champ employe, et rayon de bec de l'outil de
    #: sondage. Les deux sont rendus pour que la portee du diagnostic soit
    #: verifiable plutot que crue.
    field_inflation_mm: float = 0.0
    probe_nose_mm: float = 0.0
    #: Indices, DANS LE TABLEAU DE POINTS DE LA PASSE, des points refuses.
    #:
    #: Le depistage comptait les echecs et retenait leurs motifs, mais pas
    #: OU ils se produisent. Un verdict « cette surface demande un changement »
    #: qui ne montre pas l'endroit renvoie l'operateur chercher lui-meme dans
    #: sa CAO — c'est-a-dire tout le travail qu'on pretend lui enlever.
    #:
    #: Des INDICES et non des coordonnees : le depistage travaille sur les
    #: points tournes dans le montage, et ce qu'on veut afficher est le point
    #: dans la piece. L'indice est la seule chose qui traverse les deux reperes
    #: sans conversion — donc sans occasion de se tromper de repere.
    blocking_indices: tuple[int, ...] = ()
    #: Indices refuses MEME sur machine ideale : ceux qu'aucun montage ne leve.
    tool_blocking_indices: tuple[int, ...] = ()

    @property
    def reachable_fraction(self) -> float:
        if not self.n_probe:
            return 0.0
        return (self.n_probe - self.n_unreachable) / self.n_probe

    @property
    def mount_limited(self) -> int:
        """Echecs que ce montage explique, donc qu'un autre peut lever."""
        return self.n_unreachable - self.n_tool_limited

    @property
    def radius_fixable(self) -> int:
        """Echecs qu'un outil deux fois plus fin leverait."""
        return self.n_tool_limited - self.n_probe_tool_fails

    @property
    def probe_conclusive(self) -> bool:
        """L'outil de sondage est-il assez gros pour que son echec signifie
        quelque chose ?

        Son bec doit depasser le gonflement du champ, sans quoi c'est le
        gonflement qui le bloque et son echec ne dit rien de la geometrie.
        """
        return self.probe_nose_mm > self.field_inflation_mm

    @property
    def detail(self) -> str:
        if self.reachable:
            return f"atteignable sur {self.n_probe} points sondes"
        bouts = [f"{self.n_unreachable}/{self.n_probe} points sondes "
                 f"inatteignables"]
        if self.mount_limited:
            bouts.append(f"{self.mount_limited} propres a ce MONTAGE "
                         f"({self.reasons})")
        if self.radius_fixable:
            bouts.append(f"{self.radius_fixable} qu'un outil deux fois plus "
                         "fin leverait")
        if self.n_probe_tool_fails:
            if self.probe_conclusive:
                bouts.append(f"{self.n_probe_tool_fails} qu'un outil deux fois "
                             "plus fin ne leve pas non plus")
            else:
                bouts.append(f"{self.n_probe_tool_fails} non discrimines : le "
                             f"bec de sondage ({self.probe_nose_mm:.2f} mm) ne "
                             f"depasse pas le gonflement du champ "
                             f"({self.field_inflation_mm:.2f} mm), donc son "
                             "echec ne prouve rien")
        return ", ".join(bouts)


@dataclass
class SetupCoverage:
    orientation: PartOrientation
    mount_offset_mm: tuple[float, float, float]
    screens: list[PassScreen] = field(default_factory=list)

    @property
    def reachable(self) -> set[int]:
        return {s.pass_index for s in self.screens if s.reachable}

    def describe(self) -> str:
        r = sorted(self.reachable)
        return (f"« {self.orientation.name} » (poser {self.orientation.face_down} "
                f"sur le plateau) : passes {r if r else 'aucune'}")


@dataclass
class SetupPlan:
    """Sequence de montages couvrant les passes, et ce qu'elle coute."""

    setups: list[SetupCoverage] = field(default_factory=list)
    uncovered: list[int] = field(default_factory=list)
    #: Pour chaque passe non couverte : le meilleur montage trouve, la part
    #: atteignable, et le partage entre ce qui tient au MONTAGE et ce qui tient
    #: a l'OUTIL. Sans ce partage le plan renvoyait a « revoir l'outil ou le
    #: bridage », ce qui ne designe rien.
    residual: dict = field(default_factory=dict)
    #: Les six depistages, gardes : ils disent ce qu'on a essaye, et un plan
    #: qui ne le dit pas ne peut pas etre discute.
    all_screens: list[SetupCoverage] = field(default_factory=list)
    n_passes: int = 0
    candidates_screened: int = 0
    probes_per_pass: int = 0
    seconds: float = 0.0

    @property
    def n_setups(self) -> int:
        return len(self.setups)

    def tolerance_warning(self) -> str:
        """Ce que coute un montage de plus, et il ne se paie pas en temps.

        Chaque remontage **rereference** la piece : nouvelle origine palpee,
        nouvelle incertitude, et les budgets **se composent**. Une cote entre
        deux surfaces usinees dans DEUX montages differents porte l'erreur des
        deux reperages, plus celle du transfert. Une tolerance etablie dans un
        montage ne vaut donc pas d'un montage a l'autre.

        Le moteur ne sait pas encore chiffrer cette composition — il faudrait
        modeliser le transfert d'origine, ce qui n'est pas fait. Il refuse donc
        d'annoncer un chiffre, et dit pourquoi.
        """
        if self.n_setups <= 1:
            return ("Un seul montage : aucun transfert d'origine, le budget "
                    "geometrique est celui de ce montage.")
        return (
            f"{self.n_setups} montages. CHACUN rereference la piece : palpage "
            "propre, incertitude propre, et les budgets SE COMPOSENT. Une cote "
            "entre deux surfaces usinees dans des montages differents porte "
            "l'erreur des deux reperages plus celle du transfert. Le moteur ne "
            "chiffre pas encore cette composition : aucune tolerance ne peut "
            "etre annoncee d'un montage a l'autre.")

    def describe(self) -> str:
        lignes = [f"{self.n_setups} montage(s) pour {self.n_passes} passes, "
                  f"{self.candidates_screened} candidats depistes "
                  f"({self.seconds:.0f} s) :"]
        for i, s in enumerate(self.setups, 1):
            lignes.append(f"  {i}. {s.describe()}")
        for i in self.uncovered:
            r = self.residual.get(i, {})
            lignes.append(
                f"  passe {i} NON COUVERTE — au mieux "
                f"{r.get('fraction_atteignable', 0.0) * 100:.0f} % en "
                f"« {r.get('meilleur_montage', '?')} »")
            # Partage EXCLUSIF : les echecs hors montage se repartissent entre
            # « un outil plus fin leverait » et « il n'y suffirait pas ». Les
            # trois branches etaient additives, et la troisieme testait encore
            # une cle renommee : elle s'affichait donc en annonçant qu'aucun
            # outil de sondage n'avait ete fourni alors qu'il y en avait un.
            if r.get("outil_seul") and not r.get("sonde_fournie"):
                lignes.append(
                    f"      {r['outil_seul']} point(s) inatteignable(s) meme "
                    f"sur machine idEale {r.get('motifs_outil')} ; aucun outil "
                    "de sondage fourni, donc la cause n'est pas separee entre "
                    "rayon de bec et geometrie")
            else:
                if r.get("rayon"):
                    lignes.append(
                        f"      {r['rayon']} point(s) qu'un outil deux fois "
                        f"plus fin leverait {r.get('motifs_outil')} — pas une "
                        "question de montage")
                if r.get("sonde_echoue") and r.get("sonde_concluante"):
                    lignes.append(
                        f"      {r['sonde_echoue']} point(s) qu'un outil DEUX "
                        "FOIS PLUS FIN ne leve pas non plus : raccordement "
                        "concave trop serre. Un conge au dessin, ou accepter "
                        "le rayon de l'outil dans ce coin")
                elif r.get("sonde_echoue"):
                    lignes.append(
                        f"      {r['sonde_echoue']} point(s) NON DISCRIMINES : "
                        "le bec de sondage ne depasse pas le gonflement du "
                        "champ, donc son echec ne prouve rien. Affiner "
                        "l'echantillonnage pour decider (ADR-001 / D2)")
            if r.get("montage"):
                lignes.append(
                    f"      {r['montage']} point(s) propres au montage "
                    f"{r.get('motifs_montage')} : un autre montage, un "
                    "rehausseur ou un decalage peut les lever")
        lignes.append("  " + self.tolerance_warning())
        lignes.append("  DEPISTAGE OPTIMISTE : etabli sur "
                      f"{self.probes_per_pass} points sondes par passe, sans "
                      "bridage. Un bridage reel retire des orientations, et une "
                      "passe depistee atteignable reste a verifier en entier "
                      "(decide_indexed_pass)")
        return "\n".join(lignes)


def screen_orientation(
    orientation: PartOrientation,
    passes: list[tuple[np.ndarray, np.ndarray]],
    field_part: ObstacleField,
    make_solver,
    machine,
    tool,
    *,
    probe_tool=None,
    bbox_lo, bbox_hi,
    n_probe: int = 8,
    riser_mm: float = RISER_MM,
    on_pass=None,
) -> SetupCoverage:
    """Depiste quelles passes deviennent atteignables dans ce montage.

    ``on_pass(i, screen, coverage)``, s'il est fourni, est appele des qu'une
    passe est depistee — avant que les suivantes le soient. Le depistage dure
    des dizaines de secondes et decide les passes UNE PAR UNE : garder le
    resultat de la premiere pendant qu'on calcule la sixieme fait attendre pour
    rien.

    La couverture EN COURS DE REMPLISSAGE est passee au rappel, et non
    seulement l'ecran : sans elle, l'appelant ne pourrait rattacher l'ecran ni
    a son montage ni aux precedents, et ne saurait donc rien conclure avant le
    retour de la fonction. Le rappel ne rend rien et ne modifie rien : il
    OBSERVE.

    ``make_solver(field, mount_offset, machine, tool)`` est fourni par
    l'appelant : ce module ne construit ni solveur ni outil. La machine ET
    l'outil sont passes EXPLICITEMENT parce que le depistage emploie deux
    machines — la vraie et l'ideale — et jusqu'a deux outils — le vrai et un
    outil ponctuel. Cachees dans une cloture, elles ne pourraient pas etre
    remplacees, et le diagnostic se reduirait a un booleen.

    ``n_probe`` est petit a dessein : un depistage n'a pas a conclure, il a a
    ECARTER. Moins de points rend le depistage OPTIMISTE — il voit moins
    d'occasions de trouver un point inatteignable — et c'est acceptable
    puisque la verification complete suit. Le plan le dit explicitement, faute
    de quoi le depistage se lirait comme un verdict.
    """
    R = orientation.rotation
    lo_r, hi_r = _rotated_bbox(bbox_lo, bbox_hi, R)
    mount = derive_mount(lo_r, hi_r, riser_mm=riser_mm)
    champ = orientation.field(field_part)
    solver = make_solver(champ, np.asarray(mount), machine, tool)

    # Solveur sur MACHINE IDEALE, sur le meme champ : il sert a distinguer
    # « ce montage ne presente pas la surface » de « l'outil ne rentre pas ».
    # Construit une fois par montage, et seulement interroge sur les points
    # qui echouent — donc quelques-uns.
    ideale = ideal_machine(machine)
    ideal = make_solver(champ, np.asarray(mount), ideale, tool)
    # Outil PONCTUEL sur machine ideale : le dernier discriminant. S'il echoue
    # encore, ni le montage ni le rayon de bec ne sont en cause.
    sonde = (make_solver(champ, np.asarray(mount), ideale, probe_tool)
             if probe_tool is not None else None)
    inflation = float(champ.inflation.min()) if len(champ) else 0.0
    bec_sonde = float(getattr(probe_tool, "corner_radius", 0.0)) if probe_tool else 0.0

    cov = SetupCoverage(orientation=orientation, mount_offset_mm=mount)
    for i, (pts, nrm) in enumerate(passes):
        p = orientation.points(pts)
        n = orientation.directions(nrm)
        idx = np.unique(np.linspace(0, len(p) - 1, min(n_probe, len(p))).astype(int))
        bad = 0
        why: dict[str, int] = {}
        outil = 0
        rayon = 0
        why_outil: dict[str, int] = {}
        bloquants: list[int] = []
        bloquants_outil: list[int] = []
        for k in idx:
            m = solver.solve_point(p[k], n[k])
            if m.accessible:
                continue
            bad += 1
            bloquants.append(int(k))
            r = m.dominant_reason()
            nom = r.name if r is not None else "INCONNU"
            why[nom] = why.get(nom, 0) + 1
            mi = ideal.solve_point(p[k], n[k])
            if not mi.accessible:
                outil += 1
                bloquants_outil.append(int(k))
                ri = mi.dominant_reason()
                nomi = ri.name if ri is not None else "INCONNU"
                why_outil[nomi] = why_outil.get(nomi, 0) + 1
                if sonde is not None:
                    mp = sonde.solve_point(p[k], n[k])
                    if not mp.accessible:
                        rayon += 1
        ecran = PassScreen(
            pass_index=i, reachable=(bad == 0), n_probe=len(idx),
            n_unreachable=bad, reasons=why,
            n_tool_limited=outil, tool_reasons=why_outil,
            n_probe_tool_fails=rayon, field_inflation_mm=inflation,
            probe_nose_mm=bec_sonde,
            blocking_indices=tuple(bloquants),
            tool_blocking_indices=tuple(bloquants_outil))
        cov.screens.append(ecran)
        if on_pass is not None:
            on_pass(i, ecran, cov)
    return cov


@dataclass
class OutilPassant:
    """Le plus gros outil qui passe en des points donnes, et ce que ca vaut.

    Pas un simple nombre, et l'asymetrie compte.

    Le test de collision est DISCRET : les obstacles sont echantillonnes puis
    gonfles de delta, et il est une BORNE SUPERIEURE sur la collision
    (ADR-001 / D2). Les deux sens ne valent donc pas la meme chose :

      - « ce diametre PASSE » est fiable, et meme prudent. Le test voit un
        outil de rayon r comme un outil de rayon r + delta ; s'il passe quand
        meme, il passe reellement. Le vrai diametre admissible peut etre plus
        GROS que celui rendu, jamais plus petit ;
      - « aucun diametre ne passe » est indecidable des que le rayon essaye est
        comparable a delta : c'est peut-etre le gonflement seul qui bloque, pas
        la piece.

    ``concluant`` porte exactement cette distinction. La premiere version de ce
    champ l'avait a l'envers — elle declarait non concluant un diametre de
    2,4 mm sous un gonflement de 1,26 mm, alors qu'un passage mesure est
    precisement ce dont on peut etre sûr. C'est la meme famille de faute que
    partout ailleurs dans ce projet : lire une grandeur voisine de celle qu'on
    veut, ici le sens d'une inegalite.
    """

    diametre: float | None
    diametre_min_essaye: float
    diametre_max_essaye: float
    inflation_mm: float
    n_points: int
    n_essais: int

    @property
    def concluant(self) -> bool:
        """Peut-on agir sur ce resultat ?

        Un diametre trouve : oui, toujours — un passage mesure par un test
        conservatif est un passage reel. Une absence de diametre : seulement si
        le plus petit rayon essaye depassait le gonflement, faute de quoi c'est
        le gonflement qu'on a mesure.
        """
        if self.diametre is None:
            return (self.diametre_min_essaye / 2.0) > self.inflation_mm
        return True

    @property
    def prudent(self) -> bool:
        """Le diametre rendu est-il sous-estime par le test ?

        Vrai des que le rayon est comparable au gonflement : le diametre reel
        admissible est alors plus gros, et le dire evite de faire acheter un
        outil plus fin que necessaire.
        """
        return (self.diametre is not None
                and (self.diametre / 2.0) < 2.0 * self.inflation_mm)

    def describe(self) -> str:
        if self.diametre is None:
            fin = (f"aucun diametre entre {self.diametre_min_essaye:.1f} et "
                   f"{self.diametre_max_essaye:.1f} mm ne passe")
            reserve = ("" if self.concluant else
                       f" — NON CONCLUANT : au rayon essaye "
                       f"({self.diametre_min_essaye / 2:.2f} mm) le gonflement "
                       f"du champ ({self.inflation_mm:.2f} mm) bloque a lui "
                       f"seul, donc le test ne decide pas")
        else:
            fin = f"le plus gros qui passe est {self.diametre:.1f} mm"
            reserve = ("" if not self.prudent else
                       f" — valeur PRUDENTE : a ce rayon le gonflement du champ "
                       f"({self.inflation_mm:.2f} mm) pese, le diametre reel "
                       f"admissible est plus gros")
        return (f"{self.n_points} point(s) bloquants, {self.n_essais} essais : "
                f"{fin}{reserve}")


def plus_gros_outil_passant(
    make_solver,
    field_mount,
    mount_offset,
    machine,
    points: np.ndarray,
    normals: np.ndarray,
    *,
    fabrique_outil,
    diametre_max: float,
    diametre_min: float = 0.4,
    tolerance: float = 0.2,
) -> OutilPassant:
    """Cherche par dichotomie le plus gros outil qui passe en TOUS ces points.

    Repond a la question que l'operateur pose vraiment devant un refus : « et
    avec quel outil, alors ? ». Jusqu'ici l'atelier savait dire « un outil deux
    fois plus fin ne suffirait pas non plus » — vrai, et pas une cote a
    commander.

    ``fabrique_outil(diametre)`` est fourni par l'appelant : ce module ne
    construit ni solveur ni outil, et c'est ce qui permet de lui passer la
    vraie geometrie de porte-outil de l'atelier plutot qu'un outil suppose.

    La dichotomie porte sur le DIAMETRE et non sur le rayon de bec : c'est le
    diametre qu'on lit sur un outil et qu'on commande.
    """
    P = np.asarray(points, dtype=float).reshape(-1, 3)
    N = np.asarray(normals, dtype=float).reshape(-1, 3)
    if len(P) == 0:
        raise ValueError("aucun point a tester")
    inflation = float(field_mount.inflation.min()) if len(field_mount) else 0.0
    essais = 0

    def passe(d: float) -> bool:
        nonlocal essais
        essais += 1
        solveur = make_solver(field_mount, np.asarray(mount_offset), machine,
                              fabrique_outil(d))
        return all(solveur.solve_point(P[k], N[k]).accessible
                   for k in range(len(P)))

    lo, hi = float(diametre_min), float(diametre_max)
    if passe(hi):
        # L'appelant a donne des points que l'outil courant franchit : ce n'est
        # pas une erreur, mais la reponse est « celui que vous avez ».
        return OutilPassant(hi, lo, hi, inflation, len(P), essais)
    if not passe(lo):
        return OutilPassant(None, lo, hi, inflation, len(P), essais)

    # ``lo`` passe, ``hi`` ne passe pas : on resserre.
    while hi - lo > tolerance:
        mid = 0.5 * (lo + hi)
        if passe(mid):
            lo = mid
        else:
            hi = mid
    return OutilPassant(lo, float(diametre_min), float(diametre_max),
                        inflation, len(P), essais)


def _rotated_bbox(lo, hi, R: np.ndarray):
    """Boite englobante de la boite tournee.

    On tourne les HUIT sommets et on reprend le min/max : tourner seulement
    ``lo`` et ``hi`` donnerait une boite fausse des que la rotation n'est pas
    alignee sur les axes, et le montage derive s'en trouverait decale.
    """
    lo = np.asarray(lo, dtype=np.float64)
    hi = np.asarray(hi, dtype=np.float64)
    coins = np.array([[x, y, z] for x in (lo[0], hi[0])
                      for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    t = coins @ R.T
    return t.min(axis=0), t.max(axis=0)


def plan_setups(
    passes: list[tuple[np.ndarray, np.ndarray]],
    field_part: ObstacleField,
    make_solver,
    machine,
    tool,
    *,
    probe_tool=None,
    bbox_lo, bbox_hi,
    orientations: tuple[PartOrientation, ...] = CANONICAL_MOUNTS,
    n_probe: int = 8,
    riser_mm: float = RISER_MM,
) -> SetupPlan:
    """Couverture GLOUTONNE des passes par des montages.

    Le glouton est assume, comme pour l'ebauche (voir ``planner``) : le
    probleme est une couverture d'ensembles, donc NP-difficile, et l'optimum
    n'a pas d'interet pratique ici — le nombre de candidats est six et le
    nombre de passes une dizaine. Ce qui compte est de ne jamais annoncer une
    couverture qu'on n'a pas.

    A egalite de passes couvertes, on prefere le montage qui vient plus tot
    dans la liste, donc « tel quel » d'abord : un remontage evite vaut mieux
    qu'un remontage arbitrairement equivalent.
    """
    import time

    t0 = time.time()
    couvertures = [
        screen_orientation(o, passes, field_part, make_solver, machine, tool,
                           probe_tool=probe_tool,
                           bbox_lo=bbox_lo, bbox_hi=bbox_hi,
                           n_probe=n_probe, riser_mm=riser_mm)
        for o in orientations
    ]
    restantes = set(range(len(passes)))
    retenus: list[SetupCoverage] = []
    libres = list(couvertures)
    while restantes:
        meilleur = max(libres, key=lambda c: len(c.reachable & restantes))
        if len(meilleur.reachable & restantes) == 0:
            break
        retenus.append(meilleur)
        restantes -= meilleur.reachable
        libres = [c for c in libres if c is not meilleur]

    # Pour chaque passe non couverte, dire QUI bloque et OU cela se joue le
    # mieux. « Aucun des six montages » etait un fourre-tout : il melangeait
    # une face que le retournement ouvre a un point prés et une face que
    # l'outil ne peut pas atteindre.
    residu: dict[int, dict] = {}
    for i in sorted(restantes):
        best = min(couvertures,
                   key=lambda c: (c.screens[i].n_unreachable,
                                  c.screens[i].n_tool_limited))
        sc = best.screens[i]
        residu[i] = {
            "meilleur_montage": best.orientation.name,
            "fraction_atteignable": sc.reachable_fraction,
            "outil_seul": sc.n_tool_limited,
            "rayon": sc.radius_fixable,
            "sonde_echoue": sc.n_probe_tool_fails,
            "sonde_concluante": sc.probe_conclusive,
            "sonde_fournie": sc.probe_nose_mm > 0.0,
            "montage": sc.mount_limited,
            "motifs_outil": dict(sc.tool_reasons),
            "motifs_montage": dict(sc.reasons),
        }
    return SetupPlan(setups=retenus, uncovered=sorted(restantes),
                     residual=residu, all_screens=couvertures,
                     n_passes=len(passes),
                     candidates_screened=len(orientations),
                     probes_per_pass=n_probe,
                     seconds=time.time() - t0)
