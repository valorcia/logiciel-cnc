"""La matiere a enlever, consideree comme des PIECES a part entiere.

Le renversement
---------------
Jusqu'ici ce logiciel raisonnait sur les SURFACES de la piece finie : une
liste de faces, un verdict par face, une orientation par face. C'est le point
de vue du dessin. Ce n'est pas celui de l'usinage.

Un usineur ne regarde pas une face : il regarde un CREUX, et il se demande
« qu'est-ce que je sors de la, et avec quoi ? ». La matiere a enlever est un
objet, avec une forme, un volume, une profondeur et un goulot — bref, une piece
en negatif. Ce module la traite comme telle.

Consequence directe : l'outil cesse d'etre un reglage global pour devenir une
REPONSE, et une reponse par volume. Une poche large se vide a la fraise de
10 mm ; le conge au fond de la meme poche demande 2 mm. Ce ne sont pas deux
reglages concurrents, ce sont deux operations sur le meme volume.

Ce qu'un outil peut enlever, exactement
---------------------------------------
La question « quel outil enleve ce volume » a une reponse geometrique exacte,
et ce n'est pas « le plus gros qui rentre quelque part ». Un outil de rayon
``r`` atteint l'ensemble des points que sa boule balaie quand on la promene
partout ou elle tient — une OUVERTURE morphologique. Elle se calcule avec deux
transformees de distance, sans construire d'element structurant :

  1. ``d = EDT(espace)`` donne, en chaque point, la distance au premier point
     interdit : la boule de rayon r tient en c si et seulement si ``d(c) >= r`` ;
  2. ``EDT(non-coeur) <= r`` donne les points a portee d'un tel centre.

Reste a dire dans QUEL espace la boule circule, et c'est la toute la question.

  - ``ouverture(V, r)`` confine la boule DANS le volume. C'est la definition
    de manuel, et c'est le mauvais modele pour une poche : un outil n'y entre
    pas en tenant tout entier dedans, il arrive de l'exterieur par la bouche,
    et la matiere au-dessus de lui aura deja ete enlevee quand il passera.
    Mesure sur la poche de C02, 30 x 30 x 20 mm : une fraise de Ø 10 mm y
    tombait a 84 %, et les 16 % manquants n'etaient nulle part ailleurs que
    dans une bouche traitee comme un plafond ;

  - ``portee_outil(libre, r, cible)`` fait circuler la boule dans l'espace
    LIBRE — tout sauf la piece a conserver, l'air autour compris — et
    n'intersecte qu'a la fin avec la cible. C'est le modele juste, et c'est
    celui que ``decomposer`` emploie des que l'etat de matiere sait ce qu'il
    faut conserver. A defaut, il retombe sur ``ouverture``, qui est plus
    severe : sans risque de flatter un outil.

Le sens de l'erreur, et il est FAVORABLE
----------------------------------------
Le calcul se fait sur une grille de voxels, donc a un pas pres. La transformee
de distance mesure vers le CENTRE du voxel de fond le plus proche et non vers
la frontiere : un demi-voxel est donc retire du budget (``d >= r + 0.5``), ce
qui RETRECIT le coeur, donc l'ouverture. Un outil se voit ainsi attribuer
MOINS de matiere qu'il n'en enleverait vraiment.

  - « cet outil enleve au moins ce volume » est fiable ;
  - « cet outil n'atteint pas ce coin » peut etre pessimiste d'un demi-voxel.

C'est le bon sens : on ne promet pas a un outil une matiere qu'il ne sortirait
pas. La reserve s'enonce, elle ne se cache pas.

Ce que ce module ne fait PAS
----------------------------
Il ne connait ni l'ORIENTATION ni la machine, et il repond pour un bout
SPHERIQUE de rayon r suppose porte par une tige infiniment fine. Il ne dit donc
pas si l'outil peut arriver la avec sa vraie tige, son porte-outil et son nez
de broche, depuis un couple (A, C) realisable. C'est le travail du solveur
d'accessibilite, et il vient APRES — sur un volume dont on sait deja qu'aucun
outil ne rentre, il n'y a rien a orienter.

``strategy_planner.creux`` enchaine les deux et nomme celle des etapes qui
bloque.

L'enchainement est donc : quels volumes ? quel outil dans chacun ? depuis
quelle orientation ? Et chaque etape peut refuser pour sa propre raison.

La peau du brut n'est pas une poche
-----------------------------------
Les composantes connexes de la matiere enlevable ne sont PAS des poches. Sur
une piece prismatique, le brut enveloppe la piece d'une peau continue — 2 mm
de marge sur chaque face — et cette peau relie toutes les cavites en UN seul
bloc. Mesure sur la poche C02 : un seul volume de 47 669 mm3, dont une fraise
de Ø 10 mm prenait 41 % et une de Ø 3 mm... 43 %. Deux points d'ecart entre
deux outils que tout separe, parce que la peau dominait le compte et
qu'aucun des deux n'y entrait.

``separer_peau_cavites`` coupe ce bloc en deux, sur un critere qui n'a aucun
reglage : un creux est une CONCAVITE de la piece, donc de la matiere enlevable
situee a l'interieur de l'enveloppe convexe de la piece.

    cavites = enlevable ∩ conv(piece)        peau = enlevable − conv(piece)

C'est exact et sans parametre : l'enveloppe convexe d'un solide est le plus
petit convexe qui le contient, et un solide n'a de creux que la ou il s'en
ecarte. Une piece deja convexe n'a donc aucune cavite, et le module le dit
plutot que d'en inventer.

Une fois la peau retiree, les cavites se separent d'elles-memes : deux poches
sur deux faces opposees ne communiquent plus, puisque le chemin qui les
reliait passait par la peau. Les ailettes de C05 deviennent un canal par
intervalle, et c'est la que le choix d'outil se joue.

Le sens de l'erreur, encore, et il reste favorable
--------------------------------------------------
L'enveloppe est construite sur les CENTRES des voxels de la piece, donc elle
est plus petite d'un demi-voxel que la piece reelle. La bordure d'une cavite,
a sa bouche, bascule donc du cote « peau ». Ce qu'on retire ainsi a la cavite
est sa partie la plus OUVERTE, celle ou le gros outil entrait le plus
facilement : la fraction attribuee a un gros outil ne peut donc qu'etre
sous-estimee, jamais gonflee.

Ce qui reste hors de portee du critere
--------------------------------------
Il est convexe, donc il ne distingue pas un creux ferme d'un decrochement
ouvert : le rentrant d'une piece en L est compte comme une cavite. Ce n'est pas
un defaut a corriger en douce — c'est le sens du mot : ce module nomme les
CONCAVITES, pas les poches fermees. Ce qui est ouvert et ce qui ne l'est pas
depend d'une direction d'attaque, que ce module ne connait toujours pas.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

#: Voisinage employe pour separer les volumes.
#:
#: 6-connexite (faces seulement) et non 26 : deux poches qui ne se touchent que
#: par une ARETE de voxel ne communiquent pas physiquement — aucun outil ne
#: passe par une arete. Les relier ferait croire a une seule poche, et donc a
#: un seul outil pour les deux.
#: Rayon minimal, en VOXELS, pour qu'une ouverture veuille dire quelque chose.
#:
#: Sous un voxel, tout point interieur est deja un centre valide : l'ouverture
#: vaut alors le volume entier, quel que soit le rayon. Mesure a un pas de
#: 1 mm : un rayon de 0,75 mm rendait 100 % sur les quatre pieces essayees.
#: Un seuil a 1,0 voxel ecarte exactement ce cas.
RAYON_MINIMAL_VOX = 1.0


def diametre(rayon_mm: float) -> str:
    """Un diametre d'outil, sans decimale inutile.

    « Ø 10.0 mm » donne l'air d'une precision au dixieme sur une fraise qui
    s'achete au millimetre entier. Les demi-millimetres existent (Ø 2,5), donc
    la decimale reste quand elle dit quelque chose — et la virgule aussi, parce
    que c'est le separateur decimal de la langue de cette interface.
    """
    d = 2.0 * float(rayon_mm)
    if abs(d - round(d)) < 1e-9:
        return f"{d:.0f}"
    return f"{d:.1f}".replace(".", ",")

CONNEXITE = np.array([[[0, 0, 0], [0, 1, 0], [0, 0, 0]],
                      [[0, 1, 0], [1, 1, 1], [0, 1, 0]],
                      [[0, 0, 0], [0, 1, 0], [0, 0, 0]]], dtype=bool)

#: Nature d'un volume, quand la peau a ete separee des cavites.
CAVITE = "cavite"
PEAU = "peau"
#: Nature d'un volume qu'on n'a PAS cherche a classer. Le defaut, et il se lit
#: comme un aveu : ce volume peut melanger une poche et la peau du brut.
INDIVIS = "indivis"

#: Taille des paquets de voxels testes d'un coup contre l'enveloppe convexe.
#:
#: Le test est un produit matriciel (n_voxels x n_facettes). Sur une piece
#: tessellee, l'enveloppe peut compter quelques milliers de facettes : le
#: produit entier depasserait alors plusieurs gigaoctets pour un resultat
#: booleen. On le decoupe.
PAQUET_ENVELOPPE = 20_000

#: Plafond, en MILLIMETRES de rayon, du « plus gros outil qui atteint le fond ».
#:
#: Sans plafond, ce nombre ne mesure plus rien des que le fond donne sur l'air
#: libre : la boule grandit jusqu'a buter sur le bord du tableau, et le
#: resultat annonce alors la taille du REMBOURRAGE. Mesure sur la peau du brut
#: de C02 : « au fond Ø 130,6 mm », soit exactement deux fois le rembourrage
#: choisi. Un nombre qui bouge quand on change une constante d'implementation
#: ne mesure pas la piece.
#:
#: 25 mm de rayon, soit une fraise de Ø 50 mm : au-dela, on ne parle plus
#: d'un outil que porterait une broche de machine en kit. Le module rend alors
#: ``inf``, qui se lit « rien ne borne cet outil ici », et qui ne se confond
#: avec aucune mesure.
PLAFOND_OUTIL_MM = 25.0


@dataclass(frozen=True)
class OutilSurVolume:
    """Ce qu'un outil donne atteint dans un volume donne."""

    rayon_mm: float
    volume_mm3: float
    #: Part du volume que cet outil atteint, entre 0 et 1.
    fraction: float
    #: Vrai quand l'outil atteint le point le plus profond du volume. Un outil
    #: qui prend 90 % d'une poche mais n'en atteint pas le fond ne la finit
    #: pas — et c'est le fond qui decide s'il faut un second outil.
    atteint_le_fond: bool
    #: Le pas de grille permet-il de DECIDER pour cet outil ?
    #:
    #: Defaut mesure, et il donnait la reponse la plus flatteuse possible : a
    #: un pas de 1 mm, un rayon de 0,75 mm rendait « 100 % » sur les quatre
    #: pieces essayees. Ce n'etait pas une propriete des pieces — c'etait la
    #: grille. Tout voxel interieur est a une distance >= 1 du bord, donc tout
    #: rayon inferieur a 1 voxel a son coeur partout, donc son ouverture vaut
    #: le volume entier.
    #:
    #: Un outil plus fin que le pas est donc indiscernable d'un outil
    #: infiniment fin, et ce module REFUSE de repondre pour lui plutot que de
    #: rendre 100 %.
    discriminant: bool = True

    @property
    def entre(self) -> bool:
        """L'outil rentre-t-il, ne serait-ce qu'un peu ?"""
        return self.discriminant and self.fraction > 0.0

    def describe(self) -> str:
        if not self.discriminant:
            return (f"Ø {diametre(self.rayon_mm)} mm : NON DISCRIMINE "
                    f"(plus fin que le pas de grille)")
        return (f"Ø {diametre(self.rayon_mm)} mm : {self.fraction * 100:.0f} % "
                f"({self.volume_mm3:.0f} mm³)"
                + ("" if self.atteint_le_fond else ", sans atteindre le fond"))


@dataclass(frozen=True)
class VolumeAEnlever:
    """Un creux, considere comme une piece a sortir.

    ``rayon_au_fond_mm`` est le rayon du plus gros outil qui atteint le point
    le PLUS PROFOND du volume — celui qui decide s'il faudra un second outil.
    Au-dela, la poche ne peut pas etre finie, quoi qu'on fasse par ailleurs.

    Ce champ s'appelait ``rayon_inscrit_max_mm`` et mesurait la plus grosse
    boule qui TIENT dans le volume. C'est autre chose, et c'est devenu faux le
    jour ou l'outil a eu le droit de circuler hors du volume : sur la peau du
    brut, epaisse de 2 mm, la boule inscrite faisait Ø 3,5 mm pendant qu'une
    fraise de Ø 10 mm en enlevait 100 % en roulant dessus. Deux nombres cote
    a cote, dont l'un contredisait l'autre. Le remplacer par « le plus gros
    outil qui touche ce volume quelque part » n'a rien arrange : sur un volume
    ouvert, cela rendait Ø 134 mm, c'est-a-dire la taille de la grille. Seul
    le FOND borne quelque chose.
    """

    index: int
    volume_mm3: float
    n_voxels: int
    lo: tuple[float, float, float]
    hi: tuple[float, float, float]
    rayon_au_fond_mm: float
    #: Un resultat par rayon essaye, dans l'ordre ou ils ont ete demandes.
    par_outil: tuple[OutilSurVolume, ...] = ()
    #: ``CAVITE``, ``PEAU``, ou ``INDIVIS`` quand on n'a pas cherche a classer.
    nature: str = INDIVIS
    #: Les voxels de ce volume, pour qui doit faire le lien avec la geometrie.
    #:
    #: Hors comparaison et hors representation : un tableau numpy n'a pas de
    #: ``==`` booleen, et l'afficher noierait la ligne. Il est la parce que
    #: l'etape suivante — trouver depuis quelle orientation ce creux s'usine —
    #: a besoin de savoir QUELS points de la piece le bordent, et qu'un
    #: rectangle englobant ne le dit pas.
    masque: np.ndarray | None = field(default=None, compare=False, repr=False)

    @property
    def etendue_mm(self) -> tuple[float, float, float]:
        return tuple(float(h - l) for l, h in zip(self.lo, self.hi))

    @property
    def cotes_mm(self) -> str:
        """Les trois etendues, dites telles quelles.

        Il y avait ici une propriete ``profondeur_mm`` qui rendait la plus
        GRANDE des trois etendues. Sur la poche C02 — 64 x 64 x 29 mm — elle
        annonçait « 64 mm de profondeur » pour une poche profonde de 29. La
        profondeur n'existe pas sans direction d'attaque, et ce module n'en
        connait aucune : il rend donc les trois cotes, et laisse la profondeur
        a qui connait l'orientation.
        """
        x, y, z = self.etendue_mm
        return f"{x:.0f} × {y:.0f} × {z:.0f} mm"

    @property
    def fond_a_ciel_ouvert(self) -> bool:
        """Le fond de ce volume n'est borne par rien a l'echelle d'un outil.

        C'est le cas de la peau du brut, et de tout creux plus large que
        ``PLAFOND_OUTIL_MM``. La phrase doit alors le DIRE, et non annoncer un
        diametre qui ne serait que la taille du rembourrage de calcul.
        """
        return not np.isfinite(self.rayon_au_fond_mm)

    @property
    def texte_fond(self) -> str:
        if self.fond_a_ciel_ouvert:
            return "fond à ciel ouvert"
        return f"au fond Ø {diametre(self.rayon_au_fond_mm)} mm"

    @property
    def quoi(self) -> str:
        """Ce qu'est ce volume, en un mot, pour ouvrir la phrase.

        La peau du brut et une poche ne se pilotent pas pareil — l'une se
        surface de l'exterieur, l'autre se vide par sa bouche — et l'operateur
        doit savoir laquelle il lit avant d'en lire le chiffre.
        """
        return {CAVITE: "Creux", PEAU: "Peau du brut"}.get(self.nature,
                                                           "Volume")

    def outil_le_plus_gros(self, *, seuil: float = 0.98) -> OutilSurVolume | None:
        """Le plus gros outil qui vide ce volume a ``seuil`` pres, ou ``None``.

        Le plus GROS et non le premier qui marche : a volume egal, un outil
        plus gros enleve la matiere plus vite et flechit moins. Le seuil n'est
        pas 100 % parce qu'un voxel isole dans un coin ne justifie pas de
        changer d'outil pour toute la poche — il justifie un second outil de
        reprise, ce que ``reprises`` nomme.
        """
        bons = [o for o in self.par_outil
                if o.discriminant and o.fraction >= seuil and o.atteint_le_fond]
        return max(bons, key=lambda o: o.rayon_mm) if bons else None

    def outil_d_ebauche(self) -> OutilSurVolume | None:
        """Le plus gros outil qui entre ET atteint le fond.

        Ce n'est pas ``outil_le_plus_gros``, et la difference se voit sur la
        poche de C02 — 30 x 30 x 20 mm. Celui-la exige de vider 98 % du creux,
        donc il retient Ø 3 mm, seul a y arriver. Une fraise de Ø 3 mm dans
        une poche de 30 mm de large, c'est une heure de travail pour ce qu'une
        Ø 10 fait en quelques minutes, et c'est le contraire de ce qu'un
        usineur ferait.

        L'usineur ebauche au plus gros qui descend au fond — ici Ø 10 mm, qui
        en prend 90 % — puis reprend les angles au plus fin. Les deux methodes
        repondent donc a deux questions differentes, et celle-ci repond a
        « avec quoi commence-t-on ».

        Aucun seuil arbitraire : entrer et atteindre le fond, c'est tout. Le
        majorant de ce choix est exactement ``rayon_au_fond_mm``.
        """
        bons = [o for o in self.par_outil if o.entre and o.atteint_le_fond]
        return max(bons, key=lambda o: o.rayon_mm) if bons else None

    def reprises(self, *, seuil: float = 0.98) -> tuple[OutilSurVolume, ...]:
        """Les outils plus fins qui prennent ce que le plus gros laisse.

        « Ce qu'il laisse » au sens strict : un outil plus fin n'est une
        reprise que s'il en prend PLUS. Sans cette condition, une poche videe
        a 100 % par une fraise de Ø 10 mm s'annonçait quand meme « reprise
        possible a Ø 6 mm » — une operation de plus, pour rien.

        Rendus dans l'ordre decroissant : la gamme classique est d'ebaucher au
        plus gros puis de reprendre au plus fin, et non l'inverse.
        """
        gros = self.outil_le_plus_gros(seuil=seuil)
        base = gros.rayon_mm if gros is not None else np.inf
        pris = gros.fraction if gros is not None else 0.0
        return tuple(sorted((o for o in self.par_outil
                             if o.entre and o.rayon_mm < base
                             and o.fraction > pris),
                            key=lambda o: -o.rayon_mm))

    def consigne(self) -> str:
        """Ce volume, dit a l'operateur : ce qui le vide, et ce qui manque."""
        gros = self.outil_le_plus_gros()
        tete = f"{self.quoi} : {self.volume_mm3:.0f} mm³ à sortir, {self.cotes_mm}"
        if gros is None:
            if self.rayon_au_fond_mm <= 0.0:
                return (tete + ". Aucun des outils essayés n'y entre, même "
                        "partiellement.")
            meilleur = max((o for o in self.par_outil if o.entre),
                           key=lambda o: o.fraction, default=None)
            fin = (f" Le meilleur essayé, Ø {diametre(meilleur.rayon_mm)} mm, "
                   f"en prend {meilleur.fraction * 100:.0f} %."
                   if meilleur is not None else
                   " Aucun outil discriminable n'y entre.")
            borne = ("son point le plus profond est à ciel ouvert, "
                     "donc aucun outil n'y est trop gros."
                     if self.fond_a_ciel_ouvert else
                     f"le plus gros qui atteindrait son point le plus "
                     f"profond fait Ø {diametre(self.rayon_au_fond_mm)} mm.")
            return (tete + f". Aucun des outils essayés ne le vide "
                    f"entièrement ; " + borne + fin)
        verbe = "l'enlève" if self.nature == PEAU else "le vide"
        bouts = [tete + f". Une fraise de Ø {diametre(gros.rayon_mm)} mm "
                 + verbe]
        rep = self.reprises()
        if rep:
            bouts[0] += "."
            bouts.append(f"Reprise à Ø {diametre(rep[0].rayon_mm)} mm pour "
                         f"les {(1 - gros.fraction) * 100:.0f} % qu'elle "
                         f"laisse.")
        else:
            bouts[0] += " sans reprise"
        return " ".join(bouts).rstrip(".") + "."

    def describe(self) -> str:
        return (f"volume {self.index} ({self.nature}) : "
                f"{self.volume_mm3:.0f} mm3, "
                f"etendue {np.round(self.etendue_mm, 1).tolist()} mm, "
                f"{self.texte_fond} ; "
                + " | ".join(o.describe() for o in self.par_outil))


def ouverture(masque: np.ndarray, rayon_vox: float) -> np.ndarray:
    """Ouverture morphologique par une boule, via deux transformees de distance.

    Ce qu'un outil de rayon ``rayon_vox`` (en VOXELS) peut balayer sans sortir
    de ``masque``. Voir l'en-tete du module pour la demonstration et pour le
    sens de l'erreur — qui est favorable.

    Deux EDT plutot qu'une erosion suivie d'une dilatation : l'element
    structurant d'une boule de 7 voxels de rayon compte 1 419 cellules, et la
    convolution correspondante coûte bien plus que deux transformees de
    distance exactes.
    """
    from scipy import ndimage

    if rayon_vox <= 0.0:
        return masque.copy()
    # ``distance_transform_edt`` mesure la distance au CENTRE du voxel de fond
    # le plus proche, et non a la frontiere du volume — un demi-voxel d'ecart.
    # Le demi-voxel est donc retire du budget : la boule tient en c si
    # ``d(c) - 0.5 >= r``. Sans cette marge, le coeur etait trop large, et mon
    # propre essai l'a montre en trouvant une ouverture qui SORTAIT du volume.
    #
    # Le sens de la marge est celui qu'on veut : elle retrecit le coeur, donc
    # l'ouverture, donc ce qu'on attribue a l'outil.
    d = ndimage.distance_transform_edt(masque)
    coeur = d >= rayon_vox + 0.5
    if not coeur.any():
        return np.zeros_like(masque)
    # Les points a portee d'un centre valide — intersectes avec le volume,
    # parce qu'une ouverture est par DEFINITION contenue dans ce qu'on ouvre.
    # L'intersection n'est pas une precaution cosmetique : sans elle, la
    # discretisation laissait deborder d'un voxel.
    return (ndimage.distance_transform_edt(~coeur) <= rayon_vox) & masque


def portee_outil(libre: np.ndarray, rayon_vox: float,
                 cible: np.ndarray) -> np.ndarray:
    """Ce qu'un outil de rayon ``rayon_vox`` atteint DANS ``cible``.

    Difference avec ``ouverture``, et elle est de fond : la boule circule dans
    ``libre`` — tout ce qui n'est pas la piece a conserver — et non dans la
    cible elle-meme. C'est le modele juste, parce qu'un outil n'entre pas dans
    une poche en tenant tout entier dedans : il arrive de l'exterieur, par la
    bouche, et la matiere qui est au-dessus de lui aura deja ete enlevee quand
    il passera.

    Le defaut que cela corrige a ete mesure : sur la poche de C02, ouverte a
    30 x 30 x 25 mm, ``ouverture(cavite, 5 mm)`` rendait 84 %. Il manquait
    16 % qui n'etaient nulle part ailleurs que dans une bouche traitee comme
    un plafond.

    L'air AUTOUR du brut est libre lui aussi : la grille est donc rembourree de
    ``rayon_vox + 1`` voxels vides avant le calcul, sans quoi un outil ne
    pourrait pas se tenir au-dessus de la piece faute de place pour son centre
    dans le tableau.

    Ce qui n'est toujours pas modelise, et il faut le dire : la TIGE, le
    porte-outil et le nez de broche. Cette fonction repond pour un bout
    spherique de rayon r suppose porte par une tige infiniment fine. Le
    solveur d'accessibilite, lui, connait le vrai outil.
    """
    from scipy import ndimage

    if rayon_vox <= 0.0:
        return cible.copy()
    p = int(np.ceil(rayon_vox)) + 1
    espace = np.pad(np.asarray(libre, dtype=bool), p, constant_values=True)
    # Meme demi-voxel qu'ailleurs : la distance est mesuree vers le CENTRE du
    # voxel bloquant, pas vers sa frontiere. La reserve retrecit le coeur, donc
    # la portee, donc ce qu'on attribue a l'outil.
    d = ndimage.distance_transform_edt(espace)
    coeur = d >= rayon_vox + 0.5
    if not coeur.any():
        return np.zeros_like(cible)
    atteint = ndimage.distance_transform_edt(~coeur) <= rayon_vox
    return atteint[p:-p, p:-p, p:-p] & cible


def rayon_atteignant(libre: np.ndarray | None, cible: np.ndarray, *,
                     plafond_vox: float) -> float:
    """Le plus grand rayon, en VOXELS, dont la boule atteint ``cible``.

    Se calcule d'un coup, sans essayer de rayons un par un. La boule de rayon
    r centree en c atteint la cible si et seulement si :

      - elle tient dans l'espace libre :   D(c) - 0.5 >= r ;
      - elle touche la cible :             E(c) <= r,

    ou ``D`` est la distance au premier point interdit et ``E`` la distance a
    la cible. Les rayons realisables en c forment donc l'intervalle
    ``[E(c), D(c) - 0.5]``, vide quand il l'est, et le maximum cherche vaut

        max { D(c) - 0.5 : E(c) <= D(c) - 0.5 }.

    Deux transformees de distance suffisent, et le resultat est exact au pas
    de grille pres. Quand ``libre`` est inconnu, la boule doit tenir dans la
    cible elle-meme : ``D`` se mesure alors sur la cible, ce qui redonne la
    plus grosse boule inscrite.

    Rend ``inf`` des que la reponse atteint ``plafond_vox`` : au-dela, ce
    serait le rembourrage du tableau qu'on mesurerait, et non la piece.
    """
    from scipy import ndimage

    if not cible.any():
        return 0.0
    espace = cible if libre is None else np.asarray(libre, dtype=bool)
    # Rembourrage genereux : la plus grosse boule imaginable ne depasse pas la
    # diagonale de la grille, et son centre doit pouvoir exister dans le
    # tableau. Sans espace libre declare, en revanche, la boule reste dans la
    # cible : rien a rembourrer, et le bord du tableau n'est pas un obstacle.
    p = 0 if libre is None else int(np.ceil(plafond_vox)) + 1
    if p:
        espace = np.pad(espace, p, constant_values=True)
    D = ndimage.distance_transform_edt(espace) - 0.5
    E = ndimage.distance_transform_edt(~np.pad(cible, p) if p else ~cible)
    bon = E <= D
    if not bon.any():
        return 0.0
    r = float(D[bon].max())
    return np.inf if r >= plafond_vox else r


def enveloppe_convexe(material, masque: np.ndarray) -> np.ndarray:
    """Voxels de ``masque`` dont le centre tombe dans conv(piece).

    L'enveloppe est celle de la matiere PROTEGEE, c'est-a-dire de la piece
    finie augmentee de sa surepaisseur. Un solide n'a de creux que la ou il
    s'ecarte de son enveloppe convexe : ce qui est enlevable et pourtant
    dedans est donc, par definition, dans une concavite.

    Rend un masque de la meme forme que ``masque``, vide si l'enveloppe est
    degeneree (piece plate ou reduite a quelques voxels alignes) — cas ou il
    n'y a aucune concavite a nommer, et ou l'inventer serait pire que de se
    taire.
    """
    from scipy import ndimage

    protegee = getattr(material, "protected", None)
    if protegee is None:
        raise TypeError(
            "separer la peau des cavites demande de connaitre la piece : "
            "l'etat de matiere n'a pas d'attribut ``protected``")
    protegee = np.asarray(protegee)
    vide = np.zeros(masque.shape, dtype=bool)
    if not protegee.any():
        return vide

    # Seule la PEAU de la piece porte des sommets de l'enveloppe : l'interieur
    # est, par construction, dans l'enveloppe de son propre bord. Qhull recoit
    # donc dix a cent fois moins de points, pour le meme resultat exact.
    bord = protegee & ~ndimage.binary_erosion(protegee, structure=CONNEXITE)
    idx = np.argwhere(bord if bord.any() else protegee)

    grille = material.grid
    pas = float(grille.pitch)
    origine = np.asarray(grille.origin, dtype=np.float64)
    pts = origine + (idx + 0.5) * pas

    from scipy.spatial import ConvexHull, QhullError
    try:
        coque = ConvexHull(pts)
    except (QhullError, ValueError):
        # Moins de quatre points non coplanaires : pas de volume, donc pas de
        # creux. On le dit en ne rendant rien.
        return vide

    A = np.asarray(coque.equations[:, :3])
    b = np.asarray(coque.equations[:, 3])

    cand = np.argwhere(masque)
    if not len(cand):
        return vide
    cpts = origine + (cand + 0.5) * pas
    dedans = np.zeros(len(cpts), dtype=bool)
    for i in range(0, len(cpts), PAQUET_ENVELOPPE):
        bloc = cpts[i:i + PAQUET_ENVELOPPE]
        # `<= 0` strictement, sans tolerance : l'enveloppe des centres est deja
        # plus petite d'un demi-voxel que la piece, et cette reserve joue dans
        # le bon sens (voir l'en-tete).
        dedans[i:i + PAQUET_ENVELOPPE] = np.all(bloc @ A.T + b <= 0.0, axis=1)

    garde = cand[dedans]
    if len(garde):
        vide[garde[:, 0], garde[:, 1], garde[:, 2]] = True
    return vide


def separer_peau_cavites(material, masque=None) -> tuple[np.ndarray, np.ndarray]:
    """Coupe la matiere enlevable en ``(peau, cavites)``.

    La peau est ce que le brut ajoute AUTOUR de la piece : elle s'enleve par
    surfacage et contournage, de l'exterieur, et un gros outil y passe partout.
    Les cavites sont les creux : elles se vident par leur bouche, et c'est la
    seulement que le choix d'outil se decide.

    Les melanger, c'est diluer le second dans le premier — la mesure qui a
    motive cette fonction est dans l'en-tete du module.
    """
    enlevable = (material.removable() if masque is None
                 else np.asarray(masque, dtype=bool))
    cavites = enveloppe_convexe(material, enlevable)
    return enlevable & ~cavites, cavites



def _volumes_du_masque(material, masque: np.ndarray, rayons: list[float],
                       volume_min_mm3: float, nature: str
                       ) -> list[VolumeAEnlever]:
    """Composantes connexes d'un masque, chacune essayee avec chaque outil."""
    from scipy import ndimage

    if not masque.any():
        return []

    # L'espace ou la boule a le droit de circuler : tout sauf la piece. Quand
    # l'etat de matiere ne dit pas ce qu'il faut conserver, on se rabat sur le
    # volume lui-meme — plus severe, donc sans risque de flatter un outil.
    protegee = getattr(material, "protected", None)
    libre = None if protegee is None else ~np.asarray(protegee, dtype=bool)

    grille = material.grid
    pas = float(grille.pitch)
    v_vox = float(grille.voxel_volume)
    origine = np.asarray(grille.origin, dtype=np.float64)

    etiquettes, n = ndimage.label(masque, structure=CONNEXITE)
    out: list[VolumeAEnlever] = []
    for k in range(1, n + 1):
        bloc = etiquettes == k
        n_vox = int(bloc.sum())
        if n_vox * v_vox < volume_min_mm3:
            continue
        idx = np.argwhere(bloc)
        lo = origine + idx.min(axis=0) * pas
        hi = origine + (idx.max(axis=0) + 1) * pas

        # Le plus profond du volume, au sens de la distance au bord : c'est ce
        # point qu'un outil doit atteindre pour que la poche soit finie.
        d = ndimage.distance_transform_edt(bloc)
        fond = np.unravel_index(int(np.argmax(d)), d.shape)
        cible_fond = np.zeros_like(bloc)
        cible_fond[fond] = True
        r_max = rayon_atteignant(libre, cible_fond,
                                 plafond_vox=PLAFOND_OUTIL_MM / pas) * pas

        essais = []
        for r in rayons:
            r_vox = r / pas
            if r_vox < RAYON_MINIMAL_VOX:
                # Indiscernable a ce pas : on le DIT plutot que de rendre le
                # 100 % que la grille produirait.
                essais.append(OutilSurVolume(
                    rayon_mm=r, volume_mm3=0.0, fraction=0.0,
                    atteint_le_fond=False, discriminant=False))
                continue
            ouvert = (ouverture(bloc, r_vox) if libre is None
                      else portee_outil(libre, r_vox, bloc))
            pris = int(ouvert.sum())
            essais.append(OutilSurVolume(
                rayon_mm=r, volume_mm3=pris * v_vox,
                fraction=pris / n_vox if n_vox else 0.0,
                atteint_le_fond=bool(ouvert[fond])))

        out.append(VolumeAEnlever(
            index=0, volume_mm3=n_vox * v_vox, n_voxels=n_vox,
            lo=tuple(float(v) for v in lo), hi=tuple(float(v) for v in hi),
            rayon_au_fond_mm=r_max, par_outil=tuple(essais),
            nature=nature, masque=bloc))
    return out


def decomposer(material, *, rayons_mm, volume_min_mm3: float = 20.0,
               masque=None, separer_peau: bool = False) -> list[VolumeAEnlever]:
    """Decoupe la matiere a enlever en volumes, et essaie chaque outil sur chacun.

    ``rayons_mm`` est la liste des RAYONS d'outil a essayer — le bec, pas le
    diametre. Chaque volume est ensuite decrit par ce que chacun y atteint,
    ce qui est exactement « refaire l'operation avec des outils differents ».

    ``volume_min_mm3`` ecarte les grumeaux d'un ou deux voxels que la
    discretisation laisse toujours. Le seuil est declare, et les volumes
    ecartes ne sont pas silencieux : ils sortent du compte rendu de l'appelant,
    qui connait le nombre total.

    ``masque`` permet de restreindre a une partie de la matiere — par exemple
    ce qu'une direction donnee voit (``material.reachable_from``). Sans lui,
    tout l'enlevable est decompose.

    ``separer_peau`` classe d'abord chaque voxel en peau ou en cavite, puis
    decompose les deux SEPAREMENT. Sans lui, la peau du brut relie toutes les
    cavites en un seul bloc et le chiffre par outil ne veut plus rien dire —
    c'est le defaut historique de cette fonction, garde par defaut pour ne pas
    changer un resultat dans le dos de qui l'appelle deja.
    """
    enlevable = (material.removable() if masque is None
                 else np.asarray(masque, dtype=bool))
    if not enlevable.any():
        return []

    rayons = [float(r) for r in rayons_mm]
    if separer_peau:
        peau, cavites = separer_peau_cavites(material, enlevable)
        out = (_volumes_du_masque(material, cavites, rayons, volume_min_mm3,
                                  CAVITE)
               + _volumes_du_masque(material, peau, rayons, volume_min_mm3,
                                    PEAU))
    else:
        out = _volumes_du_masque(material, enlevable, rayons, volume_min_mm3,
                                 INDIVIS)

    out.sort(key=lambda v: -v.volume_mm3)
    return [VolumeAEnlever(index=i, volume_mm3=v.volume_mm3,
                           n_voxels=v.n_voxels, lo=v.lo, hi=v.hi,
                           rayon_au_fond_mm=v.rayon_au_fond_mm,
                           par_outil=v.par_outil, nature=v.nature,
                           masque=v.masque)
            for i, v in enumerate(out)]
