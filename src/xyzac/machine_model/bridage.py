"""Le BRIDAGE, construit depuis deux ou trois cotes que l'operateur connait.

Pourquoi ce module existe
-------------------------
``Fixture`` existe depuis le jalon M1, et ``build_scene`` echantillonne les
bridages depuis toujours. Personne n'en declarait : l'atelier construisait un
montage sans bridage, et le disait — *« les brides ne sont pas modelisees du
tout »*. Tous les verdicts d'accessibilite etaient donc OPTIMISTES, et cette
reserve revenait sous chaque resultat sans que rien ne permette de la lever.

Ce qu'il manquait n'etait pas le modele mais le CHEMIN : personne ne peut
saisir huit coordonnees de boite sur un ecran de 10 pouces. Ce module part
donc de ce qu'un operateur sait de son montage — « la piece est dans l'etau,
prise sur 12 mm » — et en deduit la geometrie.

Le sens de l'erreur, et il est FAVORABLE
----------------------------------------
Une boite surestime un bridage reel : un etau a des mors chanfreines, une
bride est une piece mince sur une entretoise. Surestimer ajoute de l'obstacle,
donc RETIRE des orientations. L'asymetrie qui en decoule est celle qu'on veut :

- « cette orientation degage AVEC le bridage declare » est fiable, et meme
  prudent — un bridage reel plus petit degagerait encore mieux ;
- « elle ne degage pas » peut etre pessimiste : c'est peut-etre le coin carre
  d'une boite qui bloque, la ou un mors chanfreine passerait.

C'est l'inverse du decalage de piece (``strategy_planner.travel``), dont
l'erreur va dans le sens defavorable. Les deux reserves existent, elles ne se
lisent pas pareil, et les confondre ferait prendre un refus prudent pour un
refus definitif.

Tout est exprime dans le repere PIECE, comme ``Fixture`` l'exige : sur une
machine table/table le bridage TOURNE avec la piece, et c'est justement ce qui
le rend dangereux.
"""

from __future__ import annotations

import numpy as np

from .setup import Fixture, FixtureKind

#: Les formes de bridage que l'atelier sait construire.
ETAU = "etau"
BRIDES = "brides"
AUCUN = "aucun"
FORMES = (AUCUN, ETAU, BRIDES)


def etau(bbox_lo, bbox_hi, *, axe: str = "x", prise_mm: float = 10.0,
         epaisseur_mors_mm: float = 20.0, debord_mm: float = 10.0,
         keepout_mm: float = 3.0) -> list[Fixture]:
    """Deux mors qui serrent la piece sur ``prise_mm`` de sa hauteur.

    ``axe`` dit selon quelle direction les mors serrent : la piece est prise
    entre deux faces opposees, et l'autre direction reste libre. Se tromper
    d'axe est le genre d'erreur qui se voit a l'ecran — les mors apparaissent
    en travers — et c'est une raison de plus pour les DESSINER.

    ``prise_mm`` est mesuree depuis le DESSOUS de la piece : c'est ainsi qu'on
    serre, et c'est la cote que l'operateur lit sur son etau. Les mors montent
    donc de ``bbox_lo[2]`` a ``bbox_lo[2] + prise_mm``.

    ``debord_mm`` etend les mors au-dela de la piece dans l'autre direction :
    un etau est plus large que ce qu'il tient, et l'oublier sous-estimerait
    l'obstacle — la seule erreur a ne pas commettre ici.
    """
    lo = np.asarray(bbox_lo, dtype=np.float64).reshape(3)
    hi = np.asarray(bbox_hi, dtype=np.float64).reshape(3)
    if axe not in ("x", "y"):
        raise ValueError(f"axe de serrage inconnu : {axe!r} (x ou y)")
    if prise_mm <= 0.0:
        raise ValueError("prise_mm doit etre > 0 : sans prise, rien ne tient")

    i = 0 if axe == "x" else 1
    j = 1 - i
    z0 = float(lo[2])
    z1 = float(lo[2] + prise_mm)
    a = float(lo[j] - debord_mm)
    b = float(hi[j] + debord_mm)

    out = []
    for nom, cote in (("mors fixe", -1), ("mors mobile", +1)):
        if cote < 0:
            u0, u1 = float(lo[i] - epaisseur_mors_mm), float(lo[i])
        else:
            u0, u1 = float(hi[i]), float(hi[i] + epaisseur_mors_mm)
        p_lo = [0.0, 0.0, z0]
        p_hi = [0.0, 0.0, z1]
        p_lo[i], p_hi[i] = u0, u1
        p_lo[j], p_hi[j] = a, b
        out.append(Fixture(name=nom, kind=FixtureKind.VISE,
                           lo=p_lo, hi=p_hi, keepout_mm=float(keepout_mm)))
    return out


def brides_sur_plateau(bbox_lo, bbox_hi, *, n: int = 4,
                       largeur_mm: float = 25.0, longueur_mm: float = 40.0,
                       hauteur_mm: float = 12.0, recouvrement_mm: float = 6.0,
                       keepout_mm: float = 3.0) -> list[Fixture]:
    """``n`` brides posees sur le pourtour, qui MORDENT le bord de la piece.

    ``recouvrement_mm`` est ce que la bride couvre de la piece : c'est la cote
    qui compte, parce qu'elle interdit d'usiner cette bande — et c'est
    exactement ce qu'un operateur oublie en posant ses brides.

    ``hauteur_mm`` est mesuree depuis le dessous de la piece. Une bride sur
    entretoise depasse le dessus d'une piece basse, et c'est alors elle, et
    non la piece, qui limite l'accessibilite.

    Deux, trois ou quatre brides : 4 par defaut (une par cote), 2 sur les
    grands cotes, 3 reparties. Au-dela de 4 ce module rend 4 : il ne sait pas
    repartir un nombre quelconque sans inventer une disposition.
    """
    lo = np.asarray(bbox_lo, dtype=np.float64).reshape(3)
    hi = np.asarray(bbox_hi, dtype=np.float64).reshape(3)
    if n < 1:
        raise ValueError("il faut au moins une bride pour tenir la piece")
    cx = 0.5 * float(lo[0] + hi[0])
    cy = 0.5 * float(lo[1] + hi[1])
    z0 = float(lo[2])
    z1 = float(lo[2] + hauteur_mm)
    demi = 0.5 * float(largeur_mm)

    #: Les quatre cotes, dans l'ordre ou on les emploie quand il y en a moins
    #: de quatre : les deux grands d'abord, parce que c'est la qu'une piece
    #: bascule.
    grand_en_x = (hi[0] - lo[0]) >= (hi[1] - lo[1])
    cotes = ([("-Y", 0, -1), ("+Y", 0, +1), ("-X", 1, -1), ("+X", 1, +1)]
             if grand_en_x else
             [("-X", 1, -1), ("+X", 1, +1), ("-Y", 0, -1), ("+Y", 0, +1)])

    out = []
    for nom, axe_long, sens in cotes[:min(int(n), 4)]:
        p_lo = [0.0, 0.0, z0]
        p_hi = [0.0, 0.0, z1]
        # ``sens`` pointe VERS L'EXTERIEUR de la piece : le corps de la bride
        # s'etend donc en ``bord + sens * longueur``, et son nez mord la piece
        # en ``bord - sens * recouvrement``. La premiere version avait le signe
        # du corps inverse et posait des brides a l'INTERIEUR de la piece, ce
        # qui interdisait d'usiner son centre et laissait ses bords libres —
        # exactement l'inverse d'un bridage.
        if axe_long == 0:              # bride le long de X, sur un bord Y
            p_lo[0], p_hi[0] = cx - demi, cx + demi
            bord = float(lo[1]) if sens < 0 else float(hi[1])
            dedans = bord + recouvrement_mm * (1 if sens < 0 else -1)
            p_lo[1], p_hi[1] = sorted((dedans, bord + sens * longueur_mm))
        else:                          # bride le long de Y, sur un bord X
            p_lo[1], p_hi[1] = cy - demi, cy + demi
            bord = float(lo[0]) if sens < 0 else float(hi[0])
            dedans = bord + recouvrement_mm * (1 if sens < 0 else -1)
            p_lo[0], p_hi[0] = sorted((dedans, bord + sens * longueur_mm))
        out.append(Fixture(name=f"bride {nom}", kind=FixtureKind.CLAMP,
                           lo=p_lo, hi=p_hi, keepout_mm=float(keepout_mm)))
    return out


def construire(forme: str, bbox_lo, bbox_hi, **kw) -> list[Fixture]:
    """Le bridage decrit par ``forme``, ou une liste vide pour ``"aucun"``.

    Une liste vide et non ``None`` : l'appelant la passe directement au
    ``Setup``, et distinguer « aucun bridage » de « bridage non renseigne »
    est le travail de celui qui AFFICHE, pas de celui qui construit. La
    difference est reelle — un montage sans bridage n'existe pas — et l'atelier
    la dit.
    """
    if forme == AUCUN:
        return []
    if forme == ETAU:
        return etau(bbox_lo, bbox_hi, **kw)
    if forme == BRIDES:
        return brides_sur_plateau(bbox_lo, bbox_hi, **kw)
    raise ValueError(f"forme de bridage inconnue : {forme!r} (parmi {FORMES})")


def zone_interdite(fixtures: list[Fixture]) -> float:
    """La plus grande zone interdite autour des bridages declares.

    Rendue a part parce qu'elle ne se lit pas comme un obstacle : c'est une
    marge de SECURITE, decidee, et non une piece de metal mesuree.
    """
    return max((float(f.keepout_mm) for f in fixtures), default=0.0)
