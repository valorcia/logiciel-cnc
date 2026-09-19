"""La fiche de la machine : toutes ses cotes, et D'OU chacune vient.

Pourquoi une fiche, et pas dix champs de reglage
------------------------------------------------
La machine n'existe pas encore. Tout ce que le logiciel sait d'elle vient du
dessin, et le dessin n'est pas la machine : les bras ne feront pas 250,0 mm, le
pivot du berceau ne sera pas a Z = -40,000, et le plateau ne sera pas
parfaitement centre. Le jour ou la machine sera montee, quelqu'un devra
mesurer tout cela et le dire au logiciel.

Ce module est l'endroit ou on le lui dit. Il tient chaque cote avec quatre
choses, et la quatrieme est celle qui manque a tous les ecrans de reglages :

  1. sa VALEUR et son unite ;
  2. ce qu'elle CHANGE — la faisabilite, le temps, la precision ou la securite ;
  3. comment la MESURER, en une phrase, une fois la machine devant soi ;
  4. sa PROVENANCE : plan, essai, mesure ou calibration.

La provenance ne se choisit pas
-------------------------------
C'est la seule regle de ce module, et elle est stricte : **taper une valeur ne
la rend pas mesuree**. Une valeur tapee devient un ESSAI, quel que soit le soin
qu'on y a mis ; elle ne devient MESUREE que si l'on dit avec QUOI on l'a
mesuree, et CALIBREE que si c'est la procedure de calibration qui l'a ecrite.

Sans cette regle, la fiche ne servirait a rien : un operateur presse tape les
cotes du plan, l'ecran affiche « mesure », et plus personne — lui le premier —
ne sait ce que les verdicts valent. Le projet interdit ailleurs d'annoncer
±0,02 mm comme acquis ; la meme interdiction vaut pour 250,0 mm de bras.

Consequence pratique : ``a_mesurer()`` rend la liste de ce qui n'a pas encore
ete mesure, et elle reste honnete meme apres que tout a ete saisi. C'est cette
liste qui devient la feuille de route du jour de la mise en service.

Ce que la fiche ne fait pas
---------------------------
Elle ne pilote rien. Elle ne connait ni LinuxCNC, ni moteur, ni codeur. Elle
decrit une machine ; le reste du logiciel s'en sert pour SIMULER. Les organes
de securite — arret d'urgence, fins de course cablees — n'y sont presents que
comme des DECLARATIONS a cocher, parce qu'ils sont materiels et independants du
logiciel par construction : une case cochee ici n'arrete aucune broche.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

#: Cote du dessin. Nominale, jamais vue sur une machine.
PLAN = "plan"
#: Valeur tapee pour essayer. Honnete, et sans pretention.
ESSAI = "essai"
#: Mesuree sur la machine, avec un moyen NOMME.
MESURE = "mesure"
#: Ecrite par la procedure de calibration.
CALIBRE = "calibre"

#: Dans l'ordre de confiance croissante. Sert a trier et a decider.
PROVENANCES = (PLAN, ESSAI, MESURE, CALIBRE)

#: Ce qu'une provenance dit, en clair.
TEXTE_PROVENANCE = {
    PLAN: "cote du plan, jamais vérifiée",
    ESSAI: "valeur saisie pour essayer",
    MESURE: "mesurée sur la machine",
    CALIBRE: "issue de la calibration",
}

#: Une cote est SUFFISANTE quand elle vient d'une mesure ou d'une calibration.
SUFFISANTES = frozenset({MESURE, CALIBRE})

# -- ce que change une cote --------------------------------------------------
FAISABILITE = "faisabilité"
TEMPS = "temps"
PRECISION = "précision"
SECURITE = "sécurité"

#: Les groupes, dans l'ordre ou on les remplit le jour du montage.
GROUPES = (
    ("structure", "La structure delta"),
    ("rotatifs", "Les axes A et C"),
    ("organes", "Le plateau et le berceau"),
    ("broche", "La broche et le porte-outil"),
    ("courses", "Les courses utiles"),
    ("precision", "Les jeux et la précision"),
    ("securite", "Les organes de sécurité"),
)


@dataclass
class Parametre:
    """Une cote de la machine, avec tout ce qu'il faut pour en juger."""

    cle: str
    libelle: str
    valeur: float
    unite: str
    groupe: str
    #: Ce que cette cote change dans le logiciel. Pas un commentaire : un
    #: choix parmi quatre, pour que l'ecran puisse le dire et l'operateur
    #: savoir si sa saisie va invalider un verdict ou seulement une duree.
    effet: str
    #: Comment la mesurer, une fois la machine devant soi. C'est la phrase qui
    #: transforme un formulaire en fiche de mise en service.
    comment_mesurer: str
    #: Bornes de PLAUSIBILITE, pas de securite : elles attrapent la virgule
    #: oubliee (2500 mm de bras), pas une machine differente de la notre.
    mini: float
    maxi: float
    aide: str = ""
    provenance: str = PLAN
    #: Avec quoi la mesure a ete faite. Vide tant qu'elle ne l'a pas ete.
    moyen: str = ""
    #: Incertitude declaree de la mesure, dans l'unite de la cote.
    incertitude: float | None = None
    #: Date de la mesure, ISO. Une cote mesuree il y a un an sur une machine
    #: qu'on a demontee depuis n'est plus une mesure.
    date_mesure: str = ""
    decimales: int = 1

    @property
    def suffisante(self) -> bool:
        """La cote repose-t-elle sur autre chose qu'un dessin ou un essai ?"""
        return self.provenance in SUFFISANTES

    @property
    def texte_valeur(self) -> str:
        return f"{self.valeur:.{self.decimales}f} {self.unite}".strip()

    def dans_les_bornes(self, v: float) -> bool:
        return self.mini <= float(v) <= self.maxi

    def regler(self, valeur: float) -> "Parametre":
        """Une valeur TAPEE. Elle devient un essai, jamais une mesure.

        C'est la regle du module, et c'est la seule facon de garder la fiche
        honnete : sans elle, tout serait « mesuré » avant midi.
        """
        v = float(valeur)
        if not self.dans_les_bornes(v):
            raise ValueError(
                f"{self.libelle} : {v} {self.unite} est hors des bornes "
                f"plausibles ({self.mini} à {self.maxi} {self.unite})")
        return replace(self, valeur=v, provenance=ESSAI, moyen="",
                       incertitude=None, date_mesure="")

    def mesurer(self, valeur: float, *, moyen: str,
                incertitude: float | None = None,
                quand: str = "") -> "Parametre":
        """Une valeur RELEVEE sur la machine, avec le moyen qui l'a relevee.

        ``moyen`` est obligatoire et non vide : « mesuré » sans dire avec quoi
        ne vaut pas mieux qu'un essai, et le laisser passer reviendrait a
        rendre la provenance decorative.
        """
        moyen = str(moyen).strip()
        if not moyen:
            raise ValueError(
                f"{self.libelle} : dites avec QUOI vous l'avez mesurée "
                "(pied à coulisse, comparateur, palpeur, laser…) — sinon "
                "c'est un essai, et l'atelier le notera comme tel.")
        v = float(valeur)
        if not self.dans_les_bornes(v):
            raise ValueError(
                f"{self.libelle} : {v} {self.unite} est hors des bornes "
                f"plausibles ({self.mini} à {self.maxi} {self.unite})")
        return replace(self, valeur=v, provenance=MESURE, moyen=moyen,
                       incertitude=(None if incertitude is None
                                    else float(incertitude)),
                       date_mesure=quand or date.today().isoformat())

    def calibrer(self, valeur: float, *, procedure: str,
                 incertitude: float | None = None) -> "Parametre":
        """Ecrite par la calibration. Le seul cas ou le logiciel s'auto-atteste."""
        return replace(self, valeur=float(valeur), provenance=CALIBRE,
                       moyen=f"calibration : {procedure}",
                       incertitude=(None if incertitude is None
                                    else float(incertitude)),
                       date_mesure=date.today().isoformat())

    def describe(self) -> str:
        bout = TEXTE_PROVENANCE[self.provenance]
        if self.moyen:
            bout += f" ({self.moyen})"
        if self.incertitude is not None:
            bout += f", ± {self.incertitude:g} {self.unite}"
        return f"{self.libelle} = {self.texte_valeur} — {bout}"


def _p(cle, libelle, valeur, unite, groupe, effet, comment_mesurer,
       mini, maxi, aide="", decimales=1) -> Parametre:
    return Parametre(cle=cle, libelle=libelle, valeur=float(valeur),
                     unite=unite, groupe=groupe, effet=effet,
                     comment_mesurer=comment_mesurer, mini=float(mini),
                     maxi=float(maxi), aide=aide, decimales=decimales)


def parametres_du_kit() -> list[Parametre]:
    """Toutes les cotes de la machine, telles que le PLAN les donne.

    Aucune n'est mesuree, et c'est l'etat de depart honnete : la machine
    n'existe pas encore. Chacune porte la phrase qui dira comment la relever
    le jour du montage.
    """
    return [
        # ------------------------------------------------ structure delta
        _p("delta_rayon_base_mm", "Rayon du cercle des rotules de chariot (R)",
           150.0, "mm", "structure", FAISABILITE,
           "Sur la machine à l'arrêt, mesurer au pied à coulisse la distance "
           "entre deux centres de rotules de chariot, puis diviser par √3 : "
           "trois points à 120° sur un cercle sont distants de R√3.",
           40.0, 600.0,
           "Avec r et L, c'est l'un des trois nombres dont dépend TOUTE la "
           "cinématique delta. Une erreur de 1 mm ici déplace la broche.",
           decimales=2),
        _p("delta_rayon_plateforme_mm", "Rayon du cercle des rotules de plateforme (r)",
           40.0, "mm", "structure", FAISABILITE,
           "Même méthode que R, sur la plateforme mobile : distance entre deux "
           "rotules divisée par √3.",
           5.0, 300.0,
           "Seul l'écart R − r intervient dans la cinématique : les deux "
           "peuvent être faux de la même quantité sans conséquence.",
           decimales=2),
        _p("delta_longueur_bras_mm", "Longueur des bras, entraxe des rotules (L)",
           250.0, "mm", "structure", FAISABILITE,
           "Entraxe entre les deux centres de rotules d'un MÊME bras. À "
           "mesurer sur les six bras : s'ils diffèrent de plus de 0,1 mm, la "
           "plateforme ne restera pas parallèle et cette fiche ne suffira plus "
           "à décrire la machine.",
           60.0, 800.0,
           "C'est la cote la plus sensible de la delta. Les fabricants de "
           "delta la mesurent bras par bras et les apparient.",
           decimales=2),
        _p("delta_chariot_min_mm", "Position basse des chariots",
           0.0, "mm", "structure", FAISABILITE,
           "Amener un chariot contre sa butée basse EN MANUEL, moteur "
           "débrayé, et lire la règle ou le codeur.",
           -500.0, 500.0,
           "C'est une course de CHARIOT, pas une course en Z : sur une delta "
           "les butées portent sur les rails, pas sur les axes cartésiens."),
        _p("delta_chariot_max_mm", "Position haute des chariots",
           300.0, "mm", "structure", FAISABILITE,
           "Même méthode contre la butée haute. L'écart entre les deux est la "
           "course réelle du rail, qui est presque toujours plus courte que "
           "celle du plan une fois les fins de course posées.",
           -500.0, 1500.0),
        _p("delta_chariot_vitesse_max_mm_min", "Vitesse maximale d'un chariot",
           4000.0, "mm/min", "structure", TEMPS,
           "Augmenter la vitesse en manuel jusqu'à perdre des pas ou entendre "
           "le moteur décrocher, puis retirer 30 %. À refaire chargé : une "
           "delta perd de la vitesse quand la plateforme porte la broche.",
           100.0, 30000.0,
           "C'est ELLE qui est limitée, et non une vitesse cartésienne : le "
           "temps de cycle se calcule dessus.",
           decimales=0),
        _p("delta_chariot_accel_max_mm_s2", "Accélération maximale d'un chariot",
           500.0, "mm/s²", "structure", TEMPS,
           "Même méthode que la vitesse : monter jusqu'au décrochage, retirer "
           "30 %. Se mesure à vide ET chargé.",
           10.0, 20000.0,
           "Non utilisée dans le temps de cycle actuel, qui l'annonce comme "
           "un PLANCHER faute de la connaître.",
           decimales=0),

        # -------------------------------------------------- axes A et C
        _p("a_min_deg", "Butée basse du berceau A",
           -120.0, "°", "rotatifs", FAISABILITE,
           "Basculer le berceau en manuel jusqu'à la butée et lire l'angle sur "
           "un niveau numérique posé sur le plateau.",
           -180.0, 0.0,
           "C'est cette course qui décide si une contre-dépouille passe. "
           "Mesurée sur C06 : −65° suffit, −30° ne suffirait pas."),
        _p("a_max_deg", "Butée haute du berceau A",
           30.0, "°", "rotatifs", FAISABILITE,
           "Basculer le berceau vers le haut jusqu'à la butée et lire "
           "l'angle sur le même niveau numérique. La course totale A est la "
           "somme des deux : c'est elle qui décide combien de faces une "
           "seule prise de pièce peut atteindre.",
           0.0, 180.0),
        _p("a_vitesse_max_deg_min", "Vitesse maximale du berceau A",
           3600.0, "°/min", "rotatifs", TEMPS,
           "Chronométrer dix aller-retours de 90° en manuel à vitesse "
           "maximale et diviser : sur un seul, le temps d'accélération "
           "pèse plus que le mouvement lui-même.",
           60.0, 36000.0, decimales=0),
        _p("c_vitesse_max_deg_min", "Vitesse maximale du plateau C",
           7200.0, "°/min", "rotatifs", TEMPS,
           "Chronométrer dix tours complets en manuel à vitesse maximale et "
           "diviser, pour la même raison qu'en A : l'accélération fausse une "
           "mesure faite sur un seul mouvement.",
           60.0, 72000.0, decimales=0),
        _p("a_jeu_deg", "Jeu du berceau A",
           0.0, "°", "rotatifs", PRECISION,
           "Comparateur sur le plateau, loin de l'axe : approcher un angle par "
           "la gauche, noter, approcher le MÊME angle par la droite, noter. "
           "L'écart divisé par le rayon donne le jeu angulaire.",
           0.0, 5.0,
           "Laissé à 0 tant qu'il n'est pas mesuré : déclarer un jeu non "
           "mesuré serait pire que de n'en déclarer aucun.",
           decimales=3),
        _p("c_jeu_deg", "Jeu du plateau C",
           0.0, "°", "rotatifs", PRECISION,
           "Comparateur posé en périphérie du plateau, le plus loin possible "
           "de l'axe : approcher une position par la gauche, noter, "
           "approcher la MÊME position par la droite, noter. L'écart divisé "
           "par le rayon d'appui donne le jeu angulaire.",
           0.0, 5.0, decimales=3),
        _p("pivot_a_x_mm", "Pivot du berceau A — X",
           0.0, "mm", "rotatifs", PRECISION,
           "NE SE MESURE PAS AU PIED À COULISSE. Palper une bille étalon dans "
           "au moins huit positions de A, puis ajuster le cercle : son axe est "
           "le pivot. C'est l'étape ROTARY_AC de la calibration, et elle "
           "l'écrit elle-même.",
           -500.0, 500.0,
           "Un pivot faux de 1 mm décale toute pièce usinée en 3+2 de 1 mm, "
           "sans qu'aucune simulation ne le voie.",
           decimales=3),
        _p("pivot_a_y_mm", "Pivot du berceau A — Y",
           0.0, "mm", "rotatifs", PRECISION,
           "Sort du même ajustement de cercle que Pivot A — X : la "
           "procédure palpe une bille étalon dans au moins huit positions de "
           "A et en déduit les trois coordonnées d'un coup.",
           -500.0, 500.0, decimales=3),
        _p("pivot_a_z_mm", "Pivot du berceau A — Z",
           -40.0, "mm", "rotatifs", PRECISION,
           "Sort du même ajustement de cercle que Pivot A — X. C'est la "
           "coordonnée la plus sensible des trois : elle fixe la hauteur "
           "autour de laquelle la pièce bascule.",
           -500.0, 500.0, decimales=3),
        _p("pivot_c_x_mm", "Pivot du plateau C — X",
           0.0, "mm", "rotatifs", PRECISION,
           "Palper une bille étalon en au moins huit positions de C et ajuster "
           "le cercle. Étape ROTARY_AC de la calibration.",
           -500.0, 500.0, decimales=3),
        _p("pivot_c_y_mm", "Pivot du plateau C — Y",
           0.0, "mm", "rotatifs", PRECISION,
           "Sort du même ajustement de cercle que Pivot C — X : huit "
           "positions de C palpées sur une bille étalon donnent les trois "
           "coordonnées d'un coup.",
           -500.0, 500.0, decimales=3),
        _p("pivot_c_z_mm", "Pivot du plateau C — Z",
           0.0, "mm", "rotatifs", PRECISION,
           "Sort du même ajustement de cercle que Pivot C — X. Sur un plateau "
           "bien monté elle vaut à peu près l'épaisseur du plateau, mais "
           "« à peu près » n'est pas une mesure.",
           -500.0, 500.0, decimales=3),
        _p("a_singularite_deg", "Zone de singularité autour de A = 0",
           3.0, "°", "rotatifs", FAISABILITE,
           "Ne se mesure pas : se CHOISIT, puis se vérifie. Faire décrire à la "
           "broche un petit cercle à A = 0,5°, 1°, 2°… et retenir l'angle en "
           "dessous duquel le plateau C s'emballe.",
           0.0, 30.0,
           "En 3+2 le plateau est bloqué, donc A = 0 est une POSITION "
           "utilisable : la singularité est un problème de MOUVEMENT."),

        # ------------------------------------------ plateau et berceau
        _p("plateau_rayon_mm", "Rayon du plateau C",
           75.0, "mm", "organes", FAISABILITE,
           "Pied à coulisse sur le plateau NU, bridage démonté, en mesurant "
           "le diamètre puis en divisant par deux — un rayon pris du centre "
           "suppose de savoir où est le centre, ce qui n'est pas acquis.",
           20.0, 400.0,
           "Sert à la détection de collision : un plateau plus grand que "
           "déclaré fera passer des orientations qui touchent."),
        _p("plateau_epaisseur_mm", "Épaisseur du plateau C",
           12.0, "mm", "organes", FAISABILITE,
           "Pied à coulisse au bord du plateau, en trois endroits à 120° : "
           "s'ils diffèrent, le plateau n'est pas plan et c'est un défaut à "
           "corriger avant de continuer.",
           2.0, 100.0),
        _p("berceau_largeur_mm", "Largeur du berceau A",
           220.0, "mm", "organes", FAISABILITE,
           "Encombrement hors tout du berceau, joues comprises, mesuré au "
           "mètre ruban sur la machine montée.",
           50.0, 1000.0, decimales=0),
        _p("berceau_hauteur_mm", "Hauteur du berceau A",
           110.0, "mm", "organes", FAISABILITE,
           "Au mètre ruban, du dessous du berceau au dessus de ses joues, "
           "berceau à A = 0. C'est cette hauteur qui décide à partir de quel "
           "basculement l'outil vient toucher une joue.",
           20.0, 600.0, decimales=0),
        _p("berceau_profondeur_mm", "Profondeur du berceau A",
           15.0, "mm", "organes", FAISABILITE,
           "Épaisseur d'une joue au pied à coulisse — celle contre laquelle "
           "l'outil peut venir quand le berceau est basculé vers elle. "
           "Prendre la plus épaisse des deux si elles diffèrent.",
           5.0, 300.0, decimales=0),

        # ------------------------------------------ broche et porte-outil
        _p("broche_rpm_min", "Régime minimal de la broche",
           6000.0, "tr/min", "broche", TEMPS,
           "Descendre le régime jusqu'à ce que la broche cale ou perde son "
           "couple, et retenir la valeur au-dessus.",
           0.0, 60000.0,
           "Une broche qui ne descend pas sous 6 000 tr/min interdit les gros "
           "diamètres dans l'acier : c'est une limite de gamme, pas de confort.",
           decimales=0),
        _p("broche_rpm_max", "Régime maximal de la broche",
           24000.0, "tr/min", "broche", TEMPS,
           "Valeur du variateur, à vérifier au tachymètre optique : les "
           "broches chinoises annoncent souvent 10 % de plus que le réel.",
           1000.0, 120000.0, decimales=0),
        _p("broche_puissance_w", "Puissance de la broche",
           800.0, "W", "broche", TEMPS,
           "Plaque signalétique, puis à vérifier à la pince ampèremétrique en "
           "coupe : la puissance utile est souvent la moitié de l'annoncée.",
           50.0, 20000.0,
           "Non utilisée pour l'instant : le calcul de temps n'a pas de "
           "modèle d'effort de coupe.",
           decimales=0),
        _p("broche_nez_diametre_mm", "Diamètre du nez de broche",
           50.0, "mm", "broche", FAISABILITE,
           "Pied à coulisse sur la partie la plus LARGE du nez, écrou de "
           "pince compris et tout capteur ou buse d'arrosage en place : "
           "c'est le plus large qui touche en premier.",
           10.0, 200.0,
           "C'est l'organe qui refuse le plus d'orientations dans les creux "
           "profonds. Le déclarer trop petit fait accepter des passes qui "
           "toucheront."),
        _p("broche_nez_longueur_mm", "Longueur du nez de broche",
           60.0, "mm", "broche", FAISABILITE,
           "Du plan de serrage de la pince au premier épaulement du corps de "
           "broche, au pied à coulisse ou à la règle. C'est la longueur sur "
           "laquelle la broche garde son plus grand diamètre.",
           10.0, 400.0),
        _p("porte_outil_diametre_mm", "Diamètre du porte-outil",
           25.0, "mm", "broche", FAISABILITE,
           "Diamètre extérieur de l'écrou de pince au pied à coulisse, pince "
           "serrée : l'écrou se déforme légèrement au serrage, et c'est "
           "serré qu'il travaille.",
           8.0, 120.0,
           "Un ER16 fait environ 25 mm, un ER11 environ 19 mm."),
        _p("porte_outil_longueur_mm", "Longueur du porte-outil",
           35.0, "mm", "broche", FAISABILITE,
           "Du plan de serrage de la broche à la face avant de l'écrou, "
           "outil monté. C'est la longueur du tronçon qui ne coupe pas mais "
           "qui occupe la place.",
           5.0, 200.0),
        _p("jauge_outil_mm", "Jauge — longueur hors pince",
           45.0, "mm", "broche", FAISABILITE,
           "Se RÈGLE, ne se mesure pas : c'est vous qui décidez de combien "
           "l'outil sort de la pince. La mesurer une fois l'outil serré, au "
           "pied à coulisse ou au banc de préréglage.",
           5.0, 300.0,
           "C'est le premier levier quand un refus dit « la tige touche » : "
           "l'allonger dégage la tige ET le porte-outil."),

        # ------------------------------------------------ courses utiles
        _p("course_x_mm", "Demi-course utile en X",
           150.0, "mm", "courses", FAISABILITE,
           "Sur une delta, la course cartésienne SE DÉDUIT des chariots : "
           "elle n'a pas de butée propre. À vérifier en promenant la broche "
           "aux quatre coins et en notant où les chariots butent.",
           10.0, 2000.0,
           "Déclarée ici parce que les écrans d'accessibilité raisonnent "
           "encore en boîte cartésienne. Le test exact, lui, passe par la "
           "cinématique delta.",
           decimales=0),
        _p("course_y_mm", "Demi-course utile en Y",
           120.0, "mm", "courses", FAISABILITE,
           "Comme en X : promener la broche jusqu'aux extrêmes en Y et "
           "noter où les chariots butent. La course Y d'une delta n'est pas "
           "la même partout en X — retenir la plus PETITE.",
           10.0, 2000.0, decimales=0),
        _p("course_z_bas_mm", "Point le plus bas atteignable en Z",
           -120.0, "mm", "courses", FAISABILITE,
           "Descendre la broche jusqu'à la butée des chariots, pointe d'outil "
           "montée, et lire Z.",
           -2000.0, 0.0, decimales=0),
        _p("course_z_haut_mm", "Point le plus haut atteignable en Z",
           60.0, "mm", "courses", FAISABILITE,
           "Voir le point bas. C'est cette hauteur qui décide si une pièce "
           "haute passe sous la broche une fois le berceau basculé.",
           0.0, 2000.0, decimales=0),

        # --------------------------------------------- jeux et precision
        _p("jeu_x_mm", "Jeu en X", 0.0, "mm", "precision", PRECISION,
           "Comparateur sur la broche : aller à une cote par la gauche, noter, "
           "revenir à la MÊME cote par la droite, noter. L'écart est le jeu.",
           0.0, 2.0,
           "Laissé à 0 tant qu'il n'est pas mesuré.", decimales=3),
        _p("jeu_y_mm", "Jeu en Y", 0.0, "mm", "precision", PRECISION,
           "Comparateur sur la broche, palpeur orienté en Y : aller à une "
           "cote par un sens, noter, y revenir par l'autre, noter. L'écart "
           "est le jeu.", 0.0, 2.0, decimales=3),
        _p("jeu_z_mm", "Jeu en Z", 0.0, "mm", "precision", PRECISION,
           "Comparateur vertical sous la broche : descendre à une cote, "
           "noter, y remonter depuis le bas, noter. En Z le poids de la "
           "broche masque une partie du jeu — mesurer dans les deux sens.",
           0.0, 2.0, decimales=3),
        _p("repetabilite_origine_mm", "Répétabilité de la prise d'origine",
           0.0, "mm", "precision", PRECISION,
           "Faire dix prises d'origine d'affilée, comparateur en place, et "
           "relever l'étendue des dix lectures. C'est l'étendue, pas l'écart "
           "type : c'est l'étendue qu'on retrouve sur la pièce.",
           0.0, 5.0, decimales=3),
        _p("rayon_bille_palpeur_mm", "Rayon de la bille du palpeur",
           1.0, "mm", "precision", PRECISION,
           "Palper un alésage étalon de diamètre connu : la différence entre "
           "le diamètre lu et le diamètre vrai donne le rayon effectif, qui "
           "n'est pas le rayon géométrique de la bille.",
           0.1, 10.0, decimales=3),
        _p("tolerance_visee_mm", "Tolérance VISÉE sur pièce",
           0.02, "mm", "precision", PRECISION,
           "Ne se mesure pas ici : c'est un OBJECTIF. Il ne devient un fait "
           "qu'après avoir usiné la pièce d'épreuve et l'avoir mesurée sur un "
           "moyen indépendant de la machine.",
           0.001, 1.0,
           "Le projet interdit d'annoncer ±0,02 mm comme acquis. Cette cote "
           "reste donc un objectif tant que l'étape QUALIFICATION_PART n'a pas "
           "été franchie, et l'atelier l'écrit.",
           decimales=3),

        # -------------------------------------------------- securite
        _p("arret_urgence_materiel", "Arrêt d'urgence câblé en dur",
           0.0, "oui/non", "securite", SECURITE,
           "Appuyer sur le champignon moteurs en marche et VÉRIFIER que tout "
           "s'arrête même si l'ordinateur est débranché. Si l'arrêt passe par "
           "un logiciel, la réponse est non.",
           0.0, 1.0,
           "Déclaration, pas commande : cocher cette case n'arrête aucune "
           "broche. Le logiciel ne pilote pas la sécurité, il la constate.",
           decimales=0),
        _p("fins_de_course_materielles", "Fins de course câblées en dur",
           0.0, "oui/non", "securite", SECURITE,
           "Déclencher chaque fin de course à la main, moteurs en marche, et "
           "vérifier l'arrêt. Six sur une delta : deux par colonne.",
           0.0, 1.0, decimales=0),
        _p("capot_interverrouille", "Capot à interverrouillage",
           0.0, "oui/non", "securite", SECURITE,
           "Ouvrir le capot broche en rotation et vérifier l'arrêt. Absent sur "
           "la plupart des machines en kit — répondre non est la réponse "
           "honnête, et elle apparaîtra dans les conditions de lancement.",
           0.0, 1.0, decimales=0),
    ]


#: Les cotes sans lesquelles un programme destine a la machine REELLE ne veut
#: rien dire, meme si la simulation, elle, tourne tres bien sans.
#:
#: Ce ne sont pas « les plus importantes » : ce sont celles dont une erreur ne
#: se voit PAS a l'ecran. Une course fausse fait refuser une passe, et cela se
#: remarque ; un pivot faux de 1 mm laisse la simulation parfaitement verte et
#: decale la piece de 1 mm. La liste separe donc ce qui se trahit tout seul de
#: ce qui ne se trahit jamais.
CRITIQUES = (
    "delta_rayon_base_mm", "delta_rayon_plateforme_mm", "delta_longueur_bras_mm",
    "delta_chariot_min_mm", "delta_chariot_max_mm",
    "pivot_a_x_mm", "pivot_a_y_mm", "pivot_a_z_mm",
    "pivot_c_x_mm", "pivot_c_y_mm", "pivot_c_z_mm",
)

#: Les cotes que seule la calibration a le droit d'ecrire.
#:
#: Elles restent saisissables — on peut vouloir essayer « et si le pivot etait
#: la ? » — mais une saisie les marque ESSAI, jamais MESURE, meme si l'on
#: nomme un moyen. Un pivot ne se releve pas au pied a coulisse : il s'ajuste
#: sur un cercle palpe, et pretendre l'avoir mesure autrement serait annoncer
#: une precision qu'on n'a pas.
RESERVEES_A_LA_CALIBRATION = (
    "pivot_a_x_mm", "pivot_a_y_mm", "pivot_a_z_mm",
    "pivot_c_x_mm", "pivot_c_y_mm", "pivot_c_z_mm",
    "jeu_x_mm", "jeu_y_mm", "jeu_z_mm",
    "a_jeu_deg", "c_jeu_deg", "repetabilite_origine_mm",
    "rayon_bille_palpeur_mm",
)

#: Nom du fichier ou la fiche se garde, a cote du logiciel.
NOM_FICHIER = "machine.json"


@dataclass
class FicheMachine:
    """Toutes les cotes de la machine, et d'ou chacune vient."""

    parametres: dict[str, Parametre] = field(default_factory=dict)
    #: Nom que l'operateur donne a SA machine. Deux exemplaires d'un meme kit
    #: n'ont pas les memes cotes une fois montes.
    nom: str = "Ma machine XYZAC"

    @staticmethod
    def du_kit() -> "FicheMachine":
        return FicheMachine({p.cle: p for p in parametres_du_kit()})

    # -- lecture ----------------------------------------------------------

    def __getitem__(self, cle: str) -> Parametre:
        return self.parametres[cle]

    def valeur(self, cle: str) -> float:
        return self.parametres[cle].valeur

    def oui(self, cle: str) -> bool:
        """Une declaration oui/non, lue comme telle."""
        return self.parametres[cle].valeur >= 0.5

    def groupes(self) -> list[tuple[str, str, list[Parametre]]]:
        """Les cotes, rangees dans l'ordre ou on les remplit au montage."""
        return [(cle, titre, [p for p in self.parametres.values()
                              if p.groupe == cle])
                for cle, titre in GROUPES]

    def a_mesurer(self, *, critiques_seulement: bool = False) -> list[Parametre]:
        """Ce qui n'a pas encore ete mesure. La feuille de route du montage."""
        return [p for p in self.parametres.values()
                if not p.suffisante
                and (not critiques_seulement or p.cle in CRITIQUES)]

    @property
    def mesuree(self) -> bool:
        """Toutes les cotes critiques reposent-elles sur une mesure ?"""
        return not self.a_mesurer(critiques_seulement=True)

    def securite_declaree(self) -> list[str]:
        """Les organes de securite qui NE sont PAS declares presents."""
        return [p.libelle for p in self.parametres.values()
                if p.groupe == "securite" and p.valeur < 0.5]

    def resume(self) -> str:
        """Ce que la fiche vaut, dit sans detour.

        Le chiffre qui compte n'est pas « 46 cotes renseignees » — elles le
        sont toutes depuis le premier jour, par le plan. C'est combien
        reposent sur autre chose qu'un dessin.
        """
        n = len(self.parametres)
        mesurees = sum(1 for p in self.parametres.values() if p.suffisante)
        crit = self.a_mesurer(critiques_seulement=True)
        if mesurees == 0:
            tete = (f"Aucune des {n} cotes n'a été mesurée : elles viennent "
                    f"toutes du plan. Tout ce que l'atelier annonce porte donc "
                    f"sur la machine DESSINÉE, pas sur une machine réelle.")
        elif crit:
            tete = (f"{mesurees} cote(s) sur {n} reposent sur une mesure. "
                    f"Il en reste {len(crit)} de critiques : sans elles, une "
                    f"pièce usinée peut être fausse sans que rien ne le montre "
                    f"à l'écran.")
        else:
            tete = (f"{mesurees} cote(s) sur {n} reposent sur une mesure, et "
                    f"toutes les cotes critiques en font partie.")
        manque = self.securite_declaree()
        if manque:
            tete += (" Sécurité non déclarée : " + ", ".join(manque).lower()
                     + ".")
        return tete

    # -- ecriture ---------------------------------------------------------

    def regler(self, cle: str, valeur: float) -> Parametre:
        """Saisie a la main : la cote devient un ESSAI."""
        p = self.parametres[cle].regler(valeur)
        self.parametres[cle] = p
        return p

    def mesurer(self, cle: str, valeur: float, *, moyen: str,
                incertitude: float | None = None) -> Parametre:
        """Relevee sur la machine. Refusee pour les cotes de calibration."""
        if cle in RESERVEES_A_LA_CALIBRATION:
            raise ValueError(
                f"{self.parametres[cle].libelle} ne se relève pas à la main : "
                "elle s'obtient par la procédure de calibration, qui l'écrit "
                "elle-même. Vous pouvez la saisir pour essayer, elle restera "
                "notée comme un essai.")
        p = self.parametres[cle].mesurer(valeur, moyen=moyen,
                                         incertitude=incertitude)
        self.parametres[cle] = p
        return p

    def calibrer(self, cle: str, valeur: float, *, procedure: str,
                 incertitude: float | None = None) -> Parametre:
        p = self.parametres[cle].calibrer(valeur, procedure=procedure,
                                          incertitude=incertitude)
        self.parametres[cle] = p
        return p

    # -- persistance ------------------------------------------------------

    def enregistrer(self, chemin) -> Path:
        """Ecrit la fiche a cote du logiciel, en JSON lisible a l'oeil.

        Lisible exprès : le jour ou quelque chose cloche, on doit pouvoir
        ouvrir ce fichier dans un Bloc-notes et voir ce que la machine croit
        savoir d'elle-meme. Un format binaire aurait rendu ce diagnostic
        impossible a quelqu'un qui n'est pas developpeur.
        """
        chemin = Path(chemin)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        corps = {
            "nom": self.nom,
            "cotes": {cle: {"valeur": p.valeur, "provenance": p.provenance,
                            "moyen": p.moyen, "incertitude": p.incertitude,
                            "date_mesure": p.date_mesure}
                      for cle, p in self.parametres.items()},
        }
        chemin.write_text(json.dumps(corps, indent=2, ensure_ascii=False),
                          encoding="utf-8")
        return chemin

    @staticmethod
    def charger(chemin) -> "FicheMachine":
        """Relit la fiche, en repartant TOUJOURS des definitions du code.

        Seules la valeur et la provenance viennent du fichier ; les libelles,
        les bornes et les phrases de mesure viennent du code. Une fiche
        enregistree il y a six mois profite donc des corrections apportees
        depuis, au lieu de figer un texte faux.

        Une cote inconnue du code est ignoree — le fichier peut venir d'une
        version plus recente — et une cote absente du fichier garde sa valeur
        de plan. Ni l'un ni l'autre n'est une erreur.
        """
        fiche = FicheMachine.du_kit()
        chemin = Path(chemin)
        if not chemin.exists():
            return fiche
        corps = json.loads(chemin.read_text(encoding="utf-8"))
        fiche.nom = str(corps.get("nom", fiche.nom))
        for cle, v in (corps.get("cotes") or {}).items():
            p = fiche.parametres.get(cle)
            if p is None:
                continue
            prov = str(v.get("provenance", PLAN))
            fiche.parametres[cle] = replace(
                p, valeur=float(v.get("valeur", p.valeur)),
                provenance=prov if prov in PROVENANCES else PLAN,
                moyen=str(v.get("moyen", "")),
                incertitude=(None if v.get("incertitude") is None
                             else float(v["incertitude"])),
                date_mesure=str(v.get("date_mesure", "")))
        return fiche

    # -- ce que le reste du logiciel en fait ------------------------------

    def delta(self):
        """La cinematique delta decrite par cette fiche."""
        from .delta import DeltaLineaire

        crit = self.a_mesurer(critiques_seulement=True)
        return DeltaLineaire(
            rayon_base_mm=self.valeur("delta_rayon_base_mm"),
            rayon_plateforme_mm=self.valeur("delta_rayon_plateforme_mm"),
            longueur_bras_mm=self.valeur("delta_longueur_bras_mm"),
            chariot_min_mm=self.valeur("delta_chariot_min_mm"),
            chariot_max_mm=self.valeur("delta_chariot_max_mm"),
            chariot_max_feed_mm_min=self.valeur(
                "delta_chariot_vitesse_max_mm_min"),
            source=("cotes mesurées sur la machine" if not crit else
                    f"cotes PROVISOIRES : {len(crit)} cote(s) critiques pas "
                    f"encore mesurées"))

    def machine(self):
        """La machine complete decrite par cette fiche."""
        from .machine import default_xyzac_kit

        m = default_xyzac_kit().model_copy(deep=True)
        m.machine_id = self.nom
        m.description = self.resume()
        m.x.min_mm, m.x.max_mm = (-self.valeur("course_x_mm"),
                                  self.valeur("course_x_mm"))
        m.y.min_mm, m.y.max_mm = (-self.valeur("course_y_mm"),
                                  self.valeur("course_y_mm"))
        m.z.min_mm, m.z.max_mm = (self.valeur("course_z_bas_mm"),
                                  self.valeur("course_z_haut_mm"))
        m.x.backlash_mm = self.valeur("jeu_x_mm")
        m.y.backlash_mm = self.valeur("jeu_y_mm")
        m.z.backlash_mm = self.valeur("jeu_z_mm")
        m.a.min_deg, m.a.max_deg = (self.valeur("a_min_deg"),
                                    self.valeur("a_max_deg"))
        m.a.max_feed_deg_min = self.valeur("a_vitesse_max_deg_min")
        m.a.backlash_deg = self.valeur("a_jeu_deg")
        m.c.max_feed_deg_min = self.valeur("c_vitesse_max_deg_min")
        m.c.backlash_deg = self.valeur("c_jeu_deg")
        m.singularity_a_deg = self.valeur("a_singularite_deg")
        m.spindle_min_rpm = self.valeur("broche_rpm_min")
        m.spindle_max_rpm = self.valeur("broche_rpm_max")
        m.pivot_a = [self.valeur("pivot_a_x_mm"), self.valeur("pivot_a_y_mm"),
                     self.valeur("pivot_a_z_mm")]
        m.pivot_c = [self.valeur("pivot_c_x_mm"), self.valeur("pivot_c_y_mm"),
                     self.valeur("pivot_c_z_mm")]
        ep = self.valeur("plateau_epaisseur_mm")
        larg = self.valeur("berceau_largeur_mm") / 2.0
        haut = self.valeur("berceau_hauteur_mm")
        prof = self.valeur("berceau_profondeur_mm")
        for v in m.collision_volumes:
            if v.frame == "table_C" and v.kind == "cylinder":
                v.radius = self.valeur("plateau_rayon_mm")
                v.height = ep
                v.base = [0.0, 0.0, -ep]
            elif v.frame == "cradle_A" and v.kind == "box":
                v.lo = [-larg, -95.0, -haut + 40.0]
                v.hi = [larg, -95.0 + prof, 40.0]
        m.delta = self.delta()
        return m
