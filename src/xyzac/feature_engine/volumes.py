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
``r`` ne peut atteindre que l'OUVERTURE morphologique du volume par une boule
de rayon ``r`` : l'ensemble des points que la boule balaie quand on la promene
partout ou elle tient.

    ouverture(V, r) = { x : il existe un centre c avec |x - c| <= r
                            et boule(c, r) entierement dans V }

Elle se calcule avec deux transformees de distance, sans construire d'element
structurant :

  1. ``d = EDT(V)`` donne, en chaque point, la distance au bord du volume :
     la boule de rayon r tient en c si et seulement si ``d(c) >= r`` ;
  2. ``EDT(non-coeur) <= r`` donne les points a portee d'un tel centre.

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
Il ne connait ni l'ORIENTATION ni la machine. Une ouverture morphologique dit
qu'un outil de rayon r tient dans le creux ; elle ne dit pas qu'il peut y
arriver avec sa tige, son porte-outil et son nez de broche, depuis un couple
(A, C) realisable. C'est le travail du solveur d'accessibilite, et il vient
APRES — sur un volume dont on sait deja qu'aucun outil ne rentre, il n'y a rien
a orienter.

L'enchainement est donc : quels volumes ? quel outil dans chacun ? depuis
quelle orientation ? Et chaque etape peut refuser pour sa propre raison.

Ce qu'une composante connexe N'EST PAS
--------------------------------------
Une limite a dire avant qu'elle trompe quelqu'un : les composantes connexes de
la matiere enlevable ne sont PAS des poches. Sur une piece prismatique, le brut
enveloppe la piece d'une peau continue — 2 mm de marge sur chaque face — et
cette peau relie toutes les cavites en UN seul bloc.

Mesure sur la poche C02, brut a 2 mm de marge : un seul volume de 47 669 mm3,
dont une fraise de Ø 10 mm prend 41 % et une de Ø 3 mm... 43 %. Deux points
d'ecart entre deux outils que tout separe, parce que la peau domine le compte
et qu'aucun des deux n'y entre.

Deux facons de s'en sortir, et la premiere est deja disponible :

  1. passer un ``masque`` — typiquement ``material.reachable_from(d)`` — pour
     ne decomposer que ce qu'une direction voit. Le resultat devient lisible :
     de +X, la poche C02 ne montre qu'une peau ou la plus grosse boule fait
     Ø 4 mm, et une fraise de Ø 10 mm y prend 0 % ;
  2. separer la PEAU des CAVITES, ce qui reste a faire. Ce module ne le fait
     pas et ne pretend pas le faire.
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

CONNEXITE = np.array([[[0, 0, 0], [0, 1, 0], [0, 0, 0]],
                      [[0, 1, 0], [1, 1, 1], [0, 1, 0]],
                      [[0, 0, 0], [0, 1, 0], [0, 0, 0]]], dtype=bool)


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
            return (f"Ø {2 * self.rayon_mm:.1f} mm : NON DISCRIMINE "
                    f"(plus fin que le pas de grille)")
        return (f"Ø {2 * self.rayon_mm:.1f} mm : {self.fraction * 100:.0f} % "
                f"({self.volume_mm3:.0f} mm3)"
                + ("" if self.atteint_le_fond else ", sans atteindre le fond"))


@dataclass(frozen=True)
class VolumeAEnlever:
    """Un creux, considere comme une piece a sortir.

    ``rayon_inscrit_max_mm`` est le rayon de la plus grosse boule qui tient
    QUELQUE PART dans le volume. C'est un majorant de ce qu'un outil peut
    faire, et il se lit comme tel : au-dela, aucun outil n'entre nulle part.
    """

    index: int
    volume_mm3: float
    n_voxels: int
    lo: tuple[float, float, float]
    hi: tuple[float, float, float]
    rayon_inscrit_max_mm: float
    #: Un resultat par rayon essaye, dans l'ordre ou ils ont ete demandes.
    par_outil: tuple[OutilSurVolume, ...] = ()

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

    def reprises(self, *, seuil: float = 0.98) -> tuple[OutilSurVolume, ...]:
        """Les outils plus fins qui prennent ce que le plus gros laisse.

        Rendus dans l'ordre decroissant : la gamme classique est d'ebaucher au
        plus gros puis de reprendre au plus fin, et non l'inverse.
        """
        gros = self.outil_le_plus_gros(seuil=seuil)
        base = gros.rayon_mm if gros is not None else np.inf
        return tuple(sorted((o for o in self.par_outil
                             if o.entre and o.rayon_mm < base),
                            key=lambda o: -o.rayon_mm))

    def consigne(self) -> str:
        """Ce volume, dit a l'operateur : ce qui le vide, et ce qui manque."""
        gros = self.outil_le_plus_gros()
        tete = f"{self.volume_mm3:.0f} mm³ à sortir, {self.cotes_mm}"
        if gros is None:
            if self.rayon_inscrit_max_mm <= 0.0:
                return (tete + ". Aucun des outils essayés n'y entre, même "
                        "partiellement.")
            reste = self.reprises()
            meilleur = max((o for o in self.par_outil if o.entre),
                           key=lambda o: o.fraction, default=None)
            fin = (f" Le meilleur essayé, Ø {2 * meilleur.rayon_mm:.1f} mm, "
                   f"en prend {meilleur.fraction * 100:.0f} %."
                   if meilleur is not None else
                   " Aucun outil discriminable n'y entre.")
            return (tete + f". Aucun des outils essayés ne le vide "
                    f"entièrement ; la plus grosse boule qui tiendrait "
                    f"quelque part fait Ø "
                    f"{2 * self.rayon_inscrit_max_mm:.1f} mm." + fin)
        bouts = [tete + f". Une fraise de Ø {2 * gros.rayon_mm:.1f} mm le vide"]
        rep = self.reprises()
        if rep:
            bouts.append(f"Reprise possible à Ø {2 * rep[0].rayon_mm:.1f} mm "
                         f"pour ce qu'elle laisse.")
        else:
            bouts[0] += " sans reprise"
        return " ".join(bouts).rstrip(".") + "."

    def describe(self) -> str:
        return (f"volume {self.index} : {self.volume_mm3:.0f} mm3, "
                f"etendue {np.round(self.etendue_mm, 1).tolist()} mm, "
                f"boule max Ø {2 * self.rayon_inscrit_max_mm:.1f} mm ; "
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


def decomposer(material, *, rayons_mm, volume_min_mm3: float = 20.0,
               masque=None) -> list[VolumeAEnlever]:
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
    """
    from scipy import ndimage

    enlevable = material.removable() if masque is None else np.asarray(masque)
    if not enlevable.any():
        return []

    grille = material.grid
    pas = float(grille.pitch)
    v_vox = float(grille.voxel_volume)
    origine = np.asarray(grille.origin, dtype=np.float64)

    etiquettes, n = ndimage.label(enlevable, structure=CONNEXITE)
    rayons = [float(r) for r in rayons_mm]
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
        r_max = float(d.max()) * pas
        fond = np.unravel_index(int(np.argmax(d)), d.shape)

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
            ouvert = ouverture(bloc, r_vox)
            pris = int(ouvert.sum())
            essais.append(OutilSurVolume(
                rayon_mm=r, volume_mm3=pris * v_vox,
                fraction=pris / n_vox if n_vox else 0.0,
                atteint_le_fond=bool(ouvert[fond])))

        out.append(VolumeAEnlever(
            index=len(out), volume_mm3=n_vox * v_vox, n_voxels=n_vox,
            lo=tuple(float(v) for v in lo), hi=tuple(float(v) for v in hi),
            rayon_inscrit_max_mm=r_max, par_outil=tuple(essais)))
    out.sort(key=lambda v: -v.volume_mm3)
    return [VolumeAEnlever(index=i, volume_mm3=v.volume_mm3,
                           n_voxels=v.n_voxels, lo=v.lo, hi=v.hi,
                           rayon_inscrit_max_mm=v.rayon_inscrit_max_mm,
                           par_outil=v.par_outil)
            for i, v in enumerate(out)]
