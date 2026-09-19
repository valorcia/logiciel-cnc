"""Etat d'une session d'atelier. ORCHESTRE le moteur, ne decide rien.

Regle d'architecture, la meme que pour le banc de debug : l'interface ne
contient aucun algorithme metier. Tout verdict vient d'``accessibility_solver``,
``strategy_planner`` ou ``subtractive_slicer`` ; ce module se contente de les
appeler dans l'ordre, de garder le resultat, et de le traduire en phrases que
l'on peut lire sans etre du metier.

La traduction EST le travail de ce module, et elle n'est pas cosmetique : un
rapport qui dit « AXIS_LIMITS 24/24 » n'aide personne a decider. Mais elle ne
doit rien ajouter : chaque phrase rendue ici correspond a un champ calcule par
le moteur, jamais a une appreciation.

**Securite.** Aucune fonction de ce module n'ouvre de transport machine, et
aucune n'importe ``linuxcnc_gateway``. Un test le verifie sur l'AST. L'atelier
est un simulateur : il montre ce qui se passerait.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ...machine_model.fiche import NOM_FICHIER, FicheMachine

CORPUS = Path(__file__).resolve().parents[4] / "tests" / "corpus" / "step"

#: Ou la fiche de la machine se garde : a cote du logiciel, pas dans le dossier
#: de travail.
#:
#: Le dossier de travail se vide a chaque lancement — c'est la ou vont les
#: images. Les cotes de la machine, elles, sont le fruit d'une journee de
#: mesures : les y mettre aurait voulu dire les retaper a chaque demarrage,
#: c'est-a-dire ne jamais les mesurer.
#: Surchargeable par ``XYZAC_FICHE_MACHINE``, et pour deux raisons reelles :
#: quelqu'un qui monte deux machines veut deux fiches, et une epreuve
#: automatique ne doit pas ecrire dans le dossier du logiciel — la fiche
#: laissee par une epreuve devenait le point de depart de la suivante, qui
#: n'essayait alors plus ce qu'elle croyait essayer.
FICHIER_MACHINE = Path(os.environ.get("XYZAC_FICHE_MACHINE")
                       or Path(__file__).resolve().parents[4] / NOM_FICHIER)

#: Les cotes que l'ancien ecran de reglages et la fiche designent toutes deux.
#:
#: Ecrite UNE fois et lue des deux cotes. Sans cette table, l'ecran de reglages
#: continuait d'ecrire dans ``Reglages`` pendant que la machine se construisait
#: depuis la fiche : l'utilisateur deplacait une course et rien ne bougeait.
#: Un reglage sans effet est pire qu'un reglage absent — on cherche pourquoi.
REGLAGES_VERS_FICHE = {
    "course_x": "course_x_mm",
    "course_y": "course_y_mm",
    "course_z_bas": "course_z_bas_mm",
    "course_z_haut": "course_z_haut_mm",
    "a_min": "a_min_deg",
    "a_max": "a_max_deg",
    "rayon_plateau": "plateau_rayon_mm",
    "jauge_outil": "jauge_outil_mm",
}

#: Extensions acceptees pour un fichier televerse. On ne devine pas le format
#: par le contenu : l'importeur du moteur lit du STEP, et lui presenter autre
#: chose produirait une erreur technique la ou une phrase claire suffit.
EXTENSIONS = (".step", ".stp")

#: Plafond de taille. 80 Mo laisse passer tres largement une piece de kit ; la
#: borne existe pour qu'un fichier envoye par erreur ne remplisse pas le disque
#: du Raspberry Pi, pas pour ecarter des pieces legitimes.
TAILLE_MAX = 80 * 1024 * 1024

#: Nombre d'indexations que la PREVISION d'ebauche s'autorise.
#:
#: Deux, et non « autant qu'il en faut » : chaque indexation supplementaire
#: coute un tranchage complet et une simulation d'enlevement de matiere, donc
#: des dizaines de secondes, pour une page ou l'on attend devant l'ecran. Le
#: prix de ce plafond est qu'il reste de la matiere a la fin — ce qui est dit
#: dans la note de simulation, chiffre a l'appui, plutot que laisse a deviner.
MAX_INDEXATIONS = 2

#: Points examines par passe de finition avant de l'animer.
#:
#: Mesure sur C05, champ d'obstacles de 50 881 points : ``verify_direction``
#: coûte 31 ms par point avec degagement. Les 7 909 points d'une passe
#: demanderaient donc quatre minutes PAR orientation essayee, pour une
#: animation de quelques secondes.
#:
#: 150 points REPARTIS sont donc examines, et ce chiffre est affiche a cote du
#: verdict : une orientation validee sur un echantillon est une mesure
#: OPTIMISTE — les points non examines peuvent bloquer. Dire « vérifiée » sans
#: dire « en 150 points sur 7 909 » serait promettre une preuve la ou il y a
#: un sondage.
ECHANTILLON_FINITION = 150

#: Points sondes en resolution COMPLETE pour proposer des orientations.
#:
#: Le sondage coûte 0,1 a 0,5 s par point (642 directions testees), et son
#: role n'est pas de conclure mais de faire RETRECIR l'intersection des
#: orientations admissibles. Huit points repartis suffisent a la reduire a
#: quelques candidats, ou a exhiber un point qu'aucune orientation n'atteint —
#: et ce second cas est un refus definitif, obtenu pour quelques dixiemes de
#: seconde.
SONDES_FINITION = 8

#: Orientations candidates verifiees par passe.
#:
#: Chacune coûte un examen complet de l'echantillon (5 s). Deux, parce que
#: ``decide_indexed_pass`` les essaie par marge decroissante du sondage : la
#: premiere est deja la plus degagee des candidates, la seconde sert de
#: recours quand la premiere echoue loin du sondage.
CANDIDATS_FINITION = 2

#: Temps que la recherche d'orientations de finition s'autorise, en secondes.
#:
#: Mesure : 4 s sur C17, 23 s sur C10 (huit surfaces). Le plafond ne sert donc
#: pas au cas courant mais au cas imprevu — une piece a trente surfaces, ou un
#: champ d'obstacles bien plus dense. Les surfaces non examinees sont COMPTEES
#: et nommees dans la note : un plafond silencieux se lirait comme une absence
#: de finition possible.
BUDGET_FINITION = 90.0

#: Fond des vues 3D de l'atelier.
#:
#: Le banc de debug a un fond sombre, et c'est justifie la-bas : le degrade de
#: l'outil va du clair (l'arete de coupe, ce qui DOIT toucher) au sombre (le
#: nez de broche, ce qui ne doit JAMAIS toucher), de sorte que la gravite d'un
#: contact se lise sur la teinte. Mais pour quelqu'un qui regarde simplement
#: son usinage, le porte-outil et le nez de broche devenaient une tache noire
#: sur un fond noir. Le code couleur reste l'unique source ; seul le fond
#: change, et il change ici.
FOND_3D = "#eef1f6"

#: Rayons d'outil essayes sur chaque creux, en mm.
#:
#: Trois, et le plus fin vaut le pas de grille : sous 1 mm de rayon a 1 mm de
#: pas, ``feature_engine`` refuse de repondre plutot que de rendre 100 %, et
#: l'ecran afficherait « non discrimine » sur toute la colonne. Les trois
#: correspondent aux fraises Ø 10, Ø 6 et Ø 3 mm, qui sont les trois que
#: tout le monde a dans son tiroir.
RAYONS_CREUX = (5.0, 3.0, 1.5)

#: Pas de la grille de matiere, en mm, pour la recherche de creux.
#:
#: 1 mm : une poche de 30 mm se compte alors a 3 % pres, et le calcul complet
#: tient en deux secondes. A 0,5 mm il durerait huit fois plus longtemps pour
#: un chiffre dont la troisieme decimale ne changera aucune decision.
#:
#: La consequence a dire : un detail plus fin que le pas est INVISIBLE. Mesure
#: sur C20, dont la gravure disparait entierement a 1 mm — la piece s'y
#: voxelise en bloc plein, et le module rend donc « aucun creux », ce qui est
#: la bonne reponse a cette resolution et non une reponse a la piece.
PAS_CREUX = 1.0

#: Points de bord verifies par creux.
ECHANTILLON_CREUX = 80

#: Resserrage du cadrage des vues de l'atelier.
#:
#: Le cadrage porte sur « piece + brut + organes machine », ce qui le rend
#: stable a toute indexation A/C — mais le plateau et le berceau sont bien plus
#: grands qu'une piece de kit, qui n'occupait alors qu'un tiers de l'image.
#: 1,6 a ete choisi en regardant les deux poses extremes d'une gamme (A = 0 et
#: A = -90) : au-dela, la piece commence a sortir du cadre aux poses basculees.
#: Verifie sur le corpus, pas prouve pour toute taille de piece.
ZOOM_3D = 1.6


@dataclass(frozen=True)
class _Indexation:
    """Un couple (A, C), pour presenter une finition comme une ebauche.

    Les operations d'ebauche portent un ``DirectionCandidate`` du planner ; une
    finition n'en a pas. Plutot que deux chemins dans la boucle d'images, on
    donne a la finition le meme visage : un objet qui a ``a_deg`` et ``c_deg``.
    """

    a_deg: float
    c_deg: float


def couleur_verdict(verdict: str) -> str:
    """Teinte d'un verdict de surface, tiree du code couleur du moteur.

    Les memes trois teintes que partout ailleurs dans le projet : vert
    admissible, orange a corriger, rouge refuse. Les recopier ici aurait donne
    une quatrieme liste de couleurs a maintenir.
    """
    from ..debug import palette

    return {"faisable": palette.VALID,
            "a-changer": palette.WARNING,
            "impossible": palette.COLLISION,
            # « En analyse » n'est pas un verdict, donc ni vert ni rouge — mais
            # le gris neutre se confondait avec la piece, elle-meme grise sur
            # la vue de designation : les marques etaient invisibles. Le bleu
            # designe sans juger.
            "en-cours": palette.PATH}.get(verdict, palette.NEUTRAL)


def legende() -> list[dict]:
    """Ce que chaque couleur de la vue 3D veut dire.

    Les teintes viennent de ``ui.debug.palette``, l'unique source du code
    couleur : les recopier dans la feuille de style aurait cree une deuxieme
    verite, et c'est la copie affichee qui aurait fini par mentir.

    Manque signale a la relecture des captures : rien a l'ecran ne disait
    « bleu = le brut ». Une image qu'il faut se faire expliquer n'informe pas.
    """
    from ..debug import palette

    return [
        {"couleur": palette.PART, "nom": "la pièce finie"},
        {"couleur": palette.STOCK, "nom": "le brut"},
        {"couleur": palette.PATH, "nom": "la coupe"},
        {"couleur": palette.WARNING, "nom": "les déplacements rapides"},
        {"couleur": palette.TOOL_ROLE["cutting"], "nom": "l'arête de l'outil"},
        {"couleur": palette.TOOL_ROLE["holder"], "nom": "le porte-outil"},
        {"couleur": palette.MACHINE, "nom": "le plateau et le berceau"},
    ]

#: Caracteres gardes dans un nom de fichier televerse. Tout le reste est
#: remplace. Le nom vient de la machine de quelqu'un d'autre — cle USB, piece
#: jointe — et il n'a aucune raison d'etre sain.
_NOM_SUR = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
               "0123456789-_. ()")


@dataclass
class Reglages:
    """Les quelques cotes de la machine que l'on peut essayer.

    Pourquoi ces cinq-la et pas trente : ce sont celles qui changent le verdict
    d'accessibilite. Les autres (avances, accelerations) changent le TEMPS
    d'usinage, pas la faisabilite, et les melanger ferait croire qu'elles se
    valent.
    """

    course_x: float = 150.0
    course_y: float = 120.0
    course_z_bas: float = -120.0
    course_z_haut: float = 60.0
    a_min: float = -120.0
    a_max: float = 30.0
    rayon_plateau: float = 75.0
    diametre_outil: float = 6.0
    jauge_outil: float = 45.0

    #: Decalage DECLARE de la piece, ajoute a la pose suggeree, en mm dans le
    #: repere de la piece.
    #:
    #: Ce n'est pas une cote de machine, et c'est pourtant ici sa place : la
    #: pose change le verdict d'accessibilite exactement comme une course, et
    #: c'est le levier que le moteur propose quand une indexation est ecartee
    #: faute de 6 mm. Trois scalaires et non un vecteur : l'API des reglages
    #: lit des nombres, et un tuple s'y serait casse en silence.
    decalage_piece_x: float = 0.0
    decalage_piece_y: float = 0.0
    decalage_piece_z: float = 0.0

    @property
    def decalage_piece(self) -> tuple[float, float, float]:
        return (self.decalage_piece_x, self.decalage_piece_y,
                self.decalage_piece_z)

    def machine(self):
        """Construit la machine correspondante. La cinematique vient du moteur."""
        from ...machine_model import default_xyzac_kit

        m = default_xyzac_kit().model_copy(deep=True)
        m.x.min_mm, m.x.max_mm = -self.course_x, self.course_x
        m.y.min_mm, m.y.max_mm = -self.course_y, self.course_y
        m.z.min_mm, m.z.max_mm = self.course_z_bas, self.course_z_haut
        m.a.min_deg, m.a.max_deg = self.a_min, self.a_max
        for v in m.collision_volumes:
            if v.kind == "cylinder" and v.radius is not None:
                v.radius = self.rayon_plateau
                break
        return m


@dataclass
class Bridage:
    """Comment la piece est TENUE, en deux ou trois cotes.

    Troisieme groupe de reglages, et il a sa raison d'etre propre : le bridage
    change la FAISABILITE comme les courses, mais il se declare avec des cotes
    de montage — une prise d'etau, un recouvrement de bride — et non avec des
    cotes de machine. Les mettre ensemble ferait chercher « prise en mm » dans
    une liste de courses.

    Le defaut par defaut est ``aucun``, et c'est assume : supposer un bridage
    serait pire que de n'en supposer aucun, parce que cela ferait rejeter des
    orientations au nom d'un obstacle que personne n'a pose. Ce qui compte est
    de DIRE dans lequel des deux cas on se trouve — un verdict sans bridage
    declare est optimiste, et l'atelier l'ecrit.
    """

    forme: str = "aucun"
    #: Etau : sur quelle hauteur la piece est prise, et selon quel axe.
    prise_mm: float = 12.0
    axe_serrage: str = "x"
    #: Brides : combien, et ce qu'elles couvrent de la piece.
    n_brides: float = 4.0
    recouvrement_mm: float = 6.0
    hauteur_brides_mm: float = 12.0

    @staticmethod
    def formes() -> list[str]:
        from ...machine_model.bridage import FORMES

        return list(FORMES)

    def fixtures(self, bbox_lo, bbox_hi) -> list:
        """La geometrie, construite par le MOTEUR depuis ces quelques cotes."""
        from ...machine_model import bridage

        if self.forme == bridage.ETAU:
            return bridage.etau(bbox_lo, bbox_hi, axe=self.axe_serrage,
                                prise_mm=float(self.prise_mm))
        if self.forme == bridage.BRIDES:
            return bridage.brides_sur_plateau(
                bbox_lo, bbox_hi, n=int(self.n_brides),
                recouvrement_mm=float(self.recouvrement_mm),
                hauteur_mm=float(self.hauteur_brides_mm))
        return []

    def fixtures_declares(self) -> bool:
        from ...machine_model.bridage import AUCUN

        return self.forme != AUCUN

    def resume(self) -> str:
        """Une phrase, celle qui doit accompagner tout verdict."""
        from ...machine_model import bridage

        if self.forme == bridage.ETAU:
            return (f"Étau, pièce prise sur {self.prise_mm:.0f} mm selon "
                    f"{self.axe_serrage.upper()}.")
        if self.forme == bridage.BRIDES:
            return (f"{int(self.n_brides)} bride(s) de "
                    f"{self.hauteur_brides_mm:.0f} mm de haut, couvrant "
                    f"{self.recouvrement_mm:.0f} mm du bord.")
        return ("Aucun bridage déclaré : tous les verdicts sont donc "
                "OPTIMISTES, parce qu'un bridage réel retire des "
                "orientations.")


@dataclass
class Coupe:
    """Ce dont depend le TEMPS d'usinage, et rien d'autre.

    Groupe distinct des ``Reglages`` a dessein, et ce n'est pas du rangement :
    les reglages changent la FAISABILITE — une course plus courte rend une
    surface inaccessible —, la matiere change le TEMPS. Les melanger ferait
    croire qu'ils se valent, et ferait relancer une verification de 40 s parce
    que l'operateur a change d'alliage.

    La liste des matieres vient de ``recipe_profiles`` : ce module refuse de
    deviner les parametres d'une matiere voisine, et l'atelier ne peut donc
    proposer que celles qu'il connait.
    """

    matiere: str = "aluminium-6061"

    @staticmethod
    def matieres() -> list[str]:
        from ...recipe_profiles.recipes import MATERIALS

        return sorted(MATERIALS)

    def recette(self, tool, machine):
        """La recette de coupe, ou ``None`` si la matiere n'est pas connue.

        ``None`` plutot qu'une exception : une matiere inconnue ne doit pas
        faire echouer une simulation dont le reste est valable — elle doit
        faire disparaitre le TEMPS, qui est la seule chose qui en depend.
        """
        from ...recipe_profiles.recipes import UnknownMaterialError, build_recipe

        try:
            return build_recipe(self.matiere, tool, machine)
        except (UnknownMaterialError, KeyError):
            return None


#: Motif rendu par le moteur -> ce que l'utilisateur peut y faire.
#:
#: Ce n'est pas un doublon du remede de ``strategy_planner.setups`` : celui-la
#: s'adresse a quelqu'un qui lit le moteur, celui-ci a quelqu'un qui tient une
#: cle. « COLLISION_HOLDER » et « sortez l'outil davantage de la pince » sont
#: la meme information, pas le meme lecteur.
REMEDES = {
    "COLLISION_CUTTING": "le bout de l'outil ne rentre pas dans ce creux : il "
                         "faut un outil plus fin, ou un congé plus large au "
                         "dessin",
    "COLLISION_NECK": "le col de l'outil frotte : prenez un outil à col réduit",

    "COLLISION_SHANK": "la tige de l'outil touche la pièce : prenez un outil "
                       "plus long, ou à col plus fin",
    "COLLISION_HOLDER": "la pince touche la pièce : sortez l'outil davantage "
                        "de la pince",
    "COLLISION_SPINDLE": "le nez de broche touche la pièce : sortez l'outil "
                         "davantage de la pince",
    "MACHINE_COLLISION": "l'outil taperait dans le plateau ou le berceau : "
                         "surélevez la pièce, ou posez-la autrement",
    "MACHINE_TRAVEL": "la machine n'a pas assez de course : rapprochez la "
                      "pièce du centre du plateau, ou allongez la course",
    "AXIS_LIMITS": "la bascule A ne va pas assez loin pour présenter cette "
                   "surface : il faut retourner la pièce",
    "SINGULARITY": "orientation verticale écartée",
    "LEAD_LIMIT": "aucune inclinaison admise ne convient ici",
    "BACK_FACING": "cette surface regarde à l'opposé de tout accès",
}


#: Resultat memorise du controle de rendu. ``None`` = pas encore controle.
_RENDU: list = [None]


def rendu_3d() -> str:
    """Chaine VIDE si les vues 3D marchent ; sinon, quoi faire pour qu'elles
    marchent.

    Pourquoi un vrai rendu et pas un ``import pyvista`` : un import qui reussit
    ne dit pas qu'une image sortira. Le pilote graphique manque aussi souvent
    que la bibliotheque, et sur un Raspberry Pi sans ecran c'est meme le cas le
    plus frequent. Mesurer la chose qu'on veut savoir coute ici une image de
    32 x 32 pixels, une fois.

    Defaut qui a motive cette fonction : le README envoyait installer
    ``.[viz]``, qui ne contient pas pyvista. L'atelier demarrait, la piece se
    chargeait, puis la premiere vue mourait sur un ``ModuleNotFoundError`` —
    cote page, l'image restait vide sans un mot, et la trace n'apparaissait que
    dans le terminal. Une panne d'installation doit se dire a l'endroit ou on
    la subit.
    """
    if _RENDU[0] is None:
        _RENDU[0] = _controler_rendu()
    return _RENDU[0]


#: Le controle, execute dans un processus SEPARE.
_SONDE = (
    "import pyvista as pv;"
    "pv.OFF_SCREEN=True;"
    "p=pv.Plotter(off_screen=True, window_size=(32,32));"
    "p.add_mesh(pv.Sphere());"
    "p.screenshot(return_img=True);"
    "p.close();"
    "print('RENDU-OK')"
)


def _controler_rendu() -> str:
    """Fabrique une image dans un AUTRE processus, et rend ce qu'il faut faire.

    **Pourquoi un autre processus.** Le pilote graphique est du code natif : il
    ne leve pas d'exception, il fait tomber le processus. Mesure faite sur une
    machine Windows ou le rendu logiciel avait ete demande a tort : le controle
    a tue l'atelier entier, code de sortie 3221225477 (violation d'acces), sans
    une ligne de Python — donc sans rien a lire pour comprendre. Un controle
    qui tue le programme qu'il controle ne controle plus rien.

    Isole, le meme plantage devient un code de retour, donc une phrase.
    """
    try:
        r = subprocess.run([sys.executable, "-c", _SONDE], capture_output=True,
                           text=True, errors="replace", timeout=300)
    except OSError as e:
        return f"Impossible de controler l'affichage 3D ({e})."
    except subprocess.TimeoutExpired:
        return ("Le controle de l'affichage 3D ne repond pas au bout de "
                "5 minutes. Le pilote graphique de cette machine est "
                "probablement en cause.")

    if r.returncode == 0 and "RENDU-OK" in r.stdout:
        return ""

    sortie = f"{r.stdout}\n{r.stderr}"
    bas = sortie.lower()
    if "modulenotfounderror" in bas and "pyvista" in bas:
        return ("L'affichage 3D n'est pas installe. Dans le dossier du "
                "logiciel, tapez :  pip install -e \".[atelier]\"  puis "
                "relancez l'atelier.")
    if "osmesa" in bas:
        # Le cas exact qui a casse l'atelier sous Windows. On nomme la variable
        # plutot que de conseiller d'installer OSMesa : sur un poste qui a un
        # ecran, le rendu logiciel n'a rien a faire la, et c'est la DEMANDE
        # qu'il faut retirer, pas la bibliotheque qu'il faut ajouter.
        return ("L'affichage 3D a reclame le rendu logiciel OSMesa, qui n'est "
                "pas installe. Si cette machine a un ecran, c'est la demande "
                "qui est en trop : videz la variable d'environnement "
                "VTK_DEFAULT_OPENGL_WINDOW et relancez. Sur une machine SANS "
                "ecran, installez le rendu logiciel (Debian et Raspberry Pi "
                "OS : sudo apt install libosmesa6).")
    if r.returncode < 0 or r.returncode > 255:
        # Code anormal = le processus est TOMBE, il ne s'est pas termine.
        return (f"L'affichage 3D fait tomber le programme (code "
                f"{r.returncode}). C'est un probleme de pilote graphique, pas "
                f"de l'atelier : mettez a jour le pilote de votre carte "
                f"graphique, puis relancez.")
    derniere = [l for l in sortie.splitlines() if l.strip()]
    detail = derniere[-1][:200] if derniere else f"code {r.returncode}"
    return (f"L'affichage 3D est installe mais ne produit pas d'image. "
            f"Message : {detail}")


def nommer(normale) -> str:
    """Un nom qu'on peut prononcer, tire de la direction de la surface.

    « Surface 3 — 11 980 points » ne dit rien a personne. « Le dessous » se
    montre du doigt. Le nom vient de la normale moyenne calculee par le
    moteur : il decrit, il n'interprete pas.
    """
    n = np.asarray(normale, dtype=float)
    x, y, z = n / max(float(np.linalg.norm(n)), 1e-9)
    if z > 0.8:
        return "le dessus"
    if z < -0.8:
        return "le dessous"
    if abs(z) <= 0.35:
        cote = {(1, 0): "droit", (-1, 0): "gauche",
                (0, 1): "arrière", (0, -1): "avant"}
        cle = (1 if x > 0.5 else -1 if x < -0.5 else 0,
               1 if y > 0.5 else -1 if y < -0.5 else 0)
        return f"le flanc {cote.get(cle, 'lateral')}"
    return "une surface inclinée"


@dataclass
class Surface:
    """Ce qu'on sait d'une surface de la piece, en clair."""

    numero: int
    n_points: int
    verdict: str                 # "faisable" | "a-changer" | "impossible"
    titre: str
    consigne: str
    montage: str = ""
    detail: str = ""

    @property
    def etiquette(self) -> str:
        """Le verdict en un mot, pour la pastille de couleur.

        Redige ici et non dans la page : « a-changer » est un nom de champ,
        « a retourner » est une phrase, et les phrases se redigent du cote qui
        connait le verdict. La page colore, elle ne traduit pas.
        """
        return {"faisable": "usinable",
                "a-changer": "à retourner",
                "impossible": "à changer",
                "en-cours": "analyse…"}.get(self.verdict, self.verdict)


@dataclass
class Session:
    reglages: Reglages = field(default_factory=Reglages)
    #: La fiche de la machine : toutes ses cotes, et d'ou chacune vient.
    #:
    #: Chargee depuis le disque au demarrage, donc ce qui a ete MESURE un jour
    #: ne se retape pas le lendemain. C'est elle qui fait autorite ; les
    #: ``reglages`` ci-dessus en sont une vue, entretenue par
    #: ``_fiche_vers_reglages``.
    fiche: FicheMachine = field(
        default_factory=lambda: FicheMachine.charger(FICHIER_MACHINE))
    #: Ce dont depend le temps d'usinage. Separe des reglages : voir ``Coupe``.
    coupe: Coupe = field(default_factory=Coupe)
    #: Comment la piece est tenue. Separe aussi : voir ``Bridage``.
    bridage: Bridage = field(default_factory=Bridage)
    piece: str = ""
    dimensions: str = ""
    import_detail: str = ""
    surfaces: list[Surface] = field(default_factory=list)
    resume: str = ""
    montages: list[str] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)
    #: Progression d'un calcul en cours, entre 0 et 1, et ce qu'il fait.
    progres: float = 0.0
    etape: str = ""
    occupe: bool = False
    erreur: str = ""
    n_images: int = 0
    #: D'ou vient la piece : un exemple du corpus, ou le fichier de l'operateur.
    origine: str = ""
    #: Une entree par image de simulation : pose des axes et etat de la coupe.
    film: list[dict] = field(default_factory=list)
    #: Ce que la simulation a montre, et ce qu'elle n'a PAS montre.
    simulation_note: str = ""
    #: Le decalage de piece que le moteur PROPOSE, quand une indexation a ete
    #: ecartee faute de course : ``{"dx", "dy", "dz", "texte", "gain_mm3"}``.
    #:
    #: Propose et non applique : la pose est une declaration de l'operateur, et
    #: la baisser rapproche la piece du plateau — ce que ce calcul ne regarde
    #: pas. Mais lui faire calculer lui-meme un decalage que le moteur connait
    #: au dixieme de millimetre serait lui rendre le travail qu'on pretend lui
    #: enlever.
    #: Le temps PLANCHER du cycle, tel que ``strategy_planner.duree`` le
    #: calcule, avec sa reserve. ``None`` quand rien n'a ete simule ou quand
    #: la matiere n'est pas connue — pas de temps invente dans ce cas.
    duree: dict | None = None
    correction: dict | None = None
    #: Pourquoi il n'y a PAS de correction a proposer, quand la seule qui
    #: rattraperait la course enfoncerait la piece dans le plateau.
    _correction_impraticable: str = field(default="", repr=False)
    #: Les operations d'ebauche de la derniere simulation. Gardees pour le
    #: calcul du temps : le rapport du planner porte les courses mais pas les
    #: trajectoires, et les recalculer coûterait une simulation entiere.
    _operations_simulees: list = field(default_factory=list, repr=False)
    #: « Comment cette surface sera usinee », par surface, pour la revision
    #: courante. Un calcul de 0,1 a 6,5 s qu'on ne refait pas a chaque clic.
    _usinages: dict = field(default_factory=dict, repr=False)
    #: Le meme, en une ligne — pour un ecran de 10 pouces.
    #:
    #: Deux champs et non un seul tronque : ce qui doit rester VISIBLE, ce sont
    #: les faits qui changent une decision (combien de matiere, combien
    #: d'images hors courses). Le reste — ce que la simulation ne montre pas —
    #: reste accessible mais replie. Tronquer la phrase longue aurait coupe au
    #: hasard, et une reserve coupee en deux ne se lit plus.
    simulation_resume: str = ""
    #: Numero d'etat de la scene. Il change des que la piece ou les reglages
    #: changent, et il entre dans le NOM des images rendues.
    #:
    #: Defaut trouve au navigateur : les vues etaient nommees d'apres l'angle
    #: seul et effacees a chaque chargement. Deux chargements rapproches
    #: laissaient donc une requete en train d'ecrire un fichier que la suivante
    #: venait d'effacer, ou pire, trouvait « deja la » et servait — c'est-a-dire
    #: rendait l'image de la piece PRECEDENTE sous le nom de la nouvelle. Une
    #: image d'une autre piece est exactement le genre d'erreur qu'on ne voit
    #: pas : elle ressemble a une image.
    revision: int = 0

    #: Points echantillonnes de chaque surface, dans l'ordre des ``surfaces``.
    #:
    #: Gardes et non recalcules : ce qui s'allume a l'ecran doit etre
    #: EXACTEMENT ce que le solveur a interroge. Un contour redessine pour
    #: l'affichage pourrait differer de ce qui a ete juge, et l'operateur
    #: verrait alors une surface verte a l'endroit d'un refus.
    _points_surfaces: list = field(default_factory=list, repr=False)
    #: Normale MOYENNE de chaque surface : la direction depuis laquelle la
    #: regarder. Calculee par le moteur, pas par l'interface.
    _normales_surfaces: list = field(default_factory=list, repr=False)
    #: Indices des points que la machine refuse dans la POSE DE DEPART, par
    #: surface : c'est la pose que la vue montre, donc la seule ou marquer un
    #: point veut dire quelque chose.
    #: Les passes de finition elles-memes, gardees apres la verification :
    #: la simulation en a besoin, et les recalculer coûterait deux secondes
    #: pour reproduire a l'identique ce qu'on vient de jeter.
    _passes_finition: list = field(default_factory=list, repr=False)
    #: Les surfaces dont la finition N'EST PAS animee, et pourquoi — une
    #: phrase par surface, rendue par le moteur.
    #:
    #: Garde plutot que recalcule au moment de rediger la note : la raison
    #: d'un refus se connait a l'instant du refus, et la reconstituer apres
    #: coup demanderait de refaire le calcul qui vient de refuser.
    _refus_finition: list = field(default_factory=list, repr=False)
    #: Les creux trouves dans la matiere a enlever, et leur verdict complet
    #: (volume, outil, orientation). Calcules a la demande, invalides par la
    #: revision comme tout le reste.
    _creux: dict = field(default_factory=dict, repr=False)
    _blocages: list = field(default_factory=list, repr=False)
    #: Ceux que MEME une machine ideale refuse : aucun montage ne les leve, et
    #: ce sont donc eux que la recherche d'outil doit franchir.
    _blocages_outil: list = field(default_factory=list, repr=False)
    #: De quoi relancer un solveur apres la verification, pour repondre a
    #: « et avec quel outil, alors ? » sans tout recalculer.
    _contexte_diag: dict = field(default_factory=dict, repr=False)
    #: Reponse a cette question, par surface. Calculee a la demande.
    diagnostics: dict = field(default_factory=dict)

    _banc: object = field(default=None, repr=False)
    _verrou: object = field(default_factory=threading.Lock, repr=False)

    # ------------------------------------------------------------ la piece

    @staticmethod
    def exemples() -> list[dict]:
        """Les geometries du corpus, avec un nom lisible.

        Le corpus existe pour les tests du moteur ; le reutiliser ici evite a
        l'utilisateur d'avoir a fournir un STEP pour essayer l'outil.
        """
        noms = {
            "C01": "Bloc simple", "C02": "Poche rectangulaire",
            "C03": "Percages", "C04": "Marche", "C05": "Nervure",
            "C06": "Bossage", "C07": "Rainure en T", "C08": "Plan incline",
            "C09": "Chanfrein", "C10": "Dome convexe", "C11": "Cavite spherique",
            "C12": "Arbre etage", "C13": "Gorge", "C14": "Cone",
            "C15": "Helice", "C16": "Contre-depouille", "C17": "Paroi mince",
            "C18": "Angle vif", "C19": "Conge", "C20": "Piece composite",
        }
        out = []
        degrade = CORPUS.parent / "step_degraded"
        for p in sorted(CORPUS.glob("*.step")):
            cle = p.stem.split("_")[0]
            out.append({"fichier": p.name,
                        "nom": noms.get(cle, p.stem.replace("_", " "))})
        # Les geometries VOLONTAIREMENT abimees sont proposees elles aussi :
        # voir ce que le logiciel fait d'un mauvais fichier vaut mieux que
        # le decouvrir avec le sien.
        for p in sorted(degrade.glob("*.step")):
            out.append({"fichier": p.name,
                        "nom": "(abime) " + p.stem.split("_", 1)[-1].replace("_", " ")})
        return out

    def charger(self, chemin: str | Path) -> None:
        """Charge une piece par l'importeur CONTROLE du moteur.

        L'importeur REFUSE certaines geometries — une coque non fermee, par
        exemple — et il a raison : le suivi de matiere et le tranchage
        produiraient des resultats faux sans le signaler. Son message dit quoi
        faire ; il faut donc le rendre visible, et non le laisser remonter en
        erreur de serveur. Un refus motive est un service, une page blanche
        n'en est pas un.
        """
        from ...geometry_core.healing import UnusableShapeError
        from ..debug.state import BenchState

        chemin = Path(chemin)
        banc = BenchState()
        try:
            info = banc.load_step(chemin)
        except UnusableShapeError as e:
            self._refuser(chemin.name, str(e))
            return
        banc.set_default_tool("ballnose",
                              diameter=self.reglages.diametre_outil,
                              stickout=self.reglages.jauge_outil)
        self._banc = banc
        self.revision += 1
        self.origine = "exemple"
        self.piece = chemin.name
        t = info.size
        self.dimensions = f"{t[0]:.0f} x {t[1]:.0f} x {t[2]:.0f} mm"
        # Le diagnostic du moteur est ecrit pour le moteur. On n'en garde ici
        # que ce qui se decide : combien de solides, combien de surfaces, et
        # si l'import a du reparer quelque chose.
        bouts = [f"{info.n_solids} solide(s)", f"{info.n_faces} surfaces"]
        if info.volume_mm3:
            bouts.append(f"{info.volume_mm3 / 1000.0:.0f} cm³ de matière")
        self.import_detail = "Fichier lu sans problème : " + ", ".join(bouts) + "."
        # ``healing`` est renseigne MEME quand rien n'a ete repare — il dit
        # alors « Reparation non appliquee ». L'introduire par « Reparation
        # appliquee : » produisait la phrase « Reparation appliquee :
        # Reparation non appliquee », qui se contredit en six mots. On ne
        # mentionne donc la reparation que lorsqu'il y en a eu une.
        if info.healing and not info.healing.lower().startswith(
                ("reparation non", "réparation non")):
            self.import_detail += f" Réparation : {info.healing}"
        self.surfaces = []
        self.resume = ""
        self.montages = []
        self.avertissements = list(banc.messages)
        self.n_images = 0
        self.film = []
        self.simulation_note = ""
        self.simulation_resume = ""
        self.erreur = ""

    def _poser_piece(self) -> None:
        """Repose la piece selon le decalage DECLARE, sur la pose suggeree.

        Appelee avant chaque calcul et non une fois au chargement : un
        decalage se change sans recharger la piece, et une pose appliquee au
        seul chargement aurait laisse le verdict porter sur l'ancienne.

        La pose suggeree reste la reference : le decalage s'AJOUTE, de sorte
        qu'un operateur qui remet le decalage a zero retrouve exactement la
        pose de depart — et non une pose derivee de ses essais successifs.
        """
        banc = self._banc
        if banc is None or getattr(banc, "part", None) is None:
            return
        base = np.asarray(banc.suggested_mount(banc.part.bbox), dtype=float)
        banc.mount_offset_mm = list(
            base + np.asarray(self.reglages.decalage_piece, dtype=float))
        # Le BRIDAGE est pose en meme temps que la piece, et pour la meme
        # raison : les deux decrivent le montage, et un champ d'obstacles
        # calcule avant l'un des deux ne decrit rien.
        bb = banc.part.bbox
        banc.fixtures = self.bridage.fixtures(bb.lo, bb.hi)
        banc._obstacles = None

    def _refuser(self, nom: str, pourquoi: str) -> None:
        """Ecarte une piece en gardant le motif a l'ecran.

        Un refus remonte ici plutot qu'en erreur de serveur : le message dit
        quoi faire, et une page blanche ne le dirait pas.
        """
        self._banc = None
        self.revision += 1
        self.origine = ""
        self.piece = nom
        self.dimensions = ""
        self.import_detail = ""
        self.surfaces, self.resume, self.montages = [], "", []
        self._points_surfaces = []
        self._normales_surfaces = []
        self._passes_finition = []
        self._refus_finition = []
        self._operations_simulees = []
        self._usinages = {}
        self.duree = None
        self._blocages = []
        self._blocages_outil = []
        self.diagnostics = {}
        self.film, self.simulation_note, self.simulation_resume = [], "", ""
        self.n_images = 0
        # La correction proposee portait sur l'ancienne pose : la garder
        # afficherait un decalage a ajouter a un decalage deja applique.
        self.correction = None
        self.erreur = pourquoi

    def televerser(self, nom: str, donnees: bytes, dossier: Path) -> None:
        """Range le fichier de l'operateur, puis le charge comme les autres.

        Le fichier vient d'ailleurs — cle USB, piece jointe, telechargement —
        et son nom vient avec lui. Il est donc reconstruit ici a partir de
        caracteres connus, et non repris tel quel : un nom recu de l'exterieur
        et ecrit sur le disque est exactement la faute que l'on commet quand on
        se dit que « c'est local, donc c'est sans risque ». Le serveur n'ecoute
        que la boucle locale, mais « local » n'est pas une politique de
        securite.

        Le fichier est ECRIT, jamais execute ni interprete ailleurs que par
        l'importeur STEP du moteur — le meme que pour les exemples, avec les
        memes refus motives.
        """
        brut = Path(str(nom).replace("\\", "/")).name
        propre = "".join(c if c in _NOM_SUR else "_" for c in brut).strip(" .")
        if not propre:
            propre = "piece.step"
        if not propre.lower().endswith(EXTENSIONS):
            self._refuser(brut or "(sans nom)",
                          "Ce fichier n'est pas un STEP. L'atelier lit les "
                          "fichiers .step et .stp — c'est le format d'échange "
                          "que tous les logiciels de CAO savent exporter : "
                          "cherchez « Exporter » puis « STEP » dans le vôtre.")
            return
        if not donnees:
            self._refuser(propre, "Le fichier reçu est vide : le transfert "
                                  "s'est interrompu. Réessayez.")
            return
        if len(donnees) > TAILLE_MAX:
            self._refuser(propre,
                          f"Fichier trop gros : {len(donnees) / 1e6:.0f} Mo, "
                          f"pour une limite de {TAILLE_MAX // 10**6} Mo. Une "
                          f"pièce de cette machine tient très largement "
                          f"dessous ; vérifiez que vous n'exportez pas un "
                          f"assemblage entier.")
            return
        dossier = Path(dossier)
        dossier.mkdir(parents=True, exist_ok=True)
        cible = dossier / propre
        cible.write_bytes(donnees)
        self.charger(cible)
        self.origine = "votre fichier"

    @property
    def piece_chargee(self) -> bool:
        return self._banc is not None and self._banc.part is not None

    # ------------------------------------------------------- la verification

    def verifier(self) -> None:
        """Lance la verification en tache de fond. Ne bloque pas la page."""
        if self.occupe or not self.piece_chargee:
            return
        self.occupe = True
        self.progres = 0.0
        self.etape = "préparation"
        self.erreur = ""
        threading.Thread(target=self._verifier, daemon=True).start()

    def _verifier(self) -> None:
        try:
            self._faire_verifier()
        except Exception as e:                     # noqa: BLE001
            self.erreur = f"{type(e).__name__} : {e}"
        finally:
            self.occupe = False
            self.progres = 1.0
            self.etape = ""

    def _faire_verifier(self) -> None:
        from ...accessibility_solver.solver import (AccessibilityConfig,
                                                    AccessibilitySolver)
        from ...geometry_core import brep
        from ...strategy_planner.setups import (CANONICAL_MOUNTS, PROBE_TOOL_SCALE,
                                                screen_orientation)
        from ...subtractive_slicer.finishing import (generate_finishing_passes,
                                                      group_faces_by_normal)
        from ...tool_model import build_ballnose

        banc = self._banc
        banc.set_default_tool("ballnose",
                              diameter=self.reglages.diametre_outil,
                              stickout=self.reglages.jauge_outil)
        # La FICHE fait autorite, pas les reglages : elle porte les pivots,
        # la geometrie delta et les jeux, que ``Reglages`` n'a jamais eus.
        machine = self.fiche.machine()
        banc.machine = machine
        banc._obstacles = None
        self._poser_piece()

        self.etape = "découpe des surfaces"
        self.progres = 0.05
        ech = brep.sample_surface(banc.part_shape, spacing=0.4)
        passes = []
        for g in group_faces_by_normal(banc.part_shape, tol_deg=20.0):
            fp = generate_finishing_passes(banc.part_shape, g, banc.tool,
                                           scallop_mm=0.02, samples=ech)
            if fp is not None and fp.n_points:
                passes.append(fp)
        passes.sort(key=lambda f: -f.n_points)
        if not passes:
            self.resume = "Aucune surface à finir n'a été trouvée sur cette pièce."
            return

        setup = banc.build_setup()
        champ = banc.obstacle_field()
        cfg = AccessibilityConfig(subdivisions=3, max_lead_deg=45.0,
                                  cutting_depth=0.0)

        def fabrique(field_, mount, mach, outil):
            return AccessibilitySolver(outil, mach, field_, cfg,
                                       mount_offset_mm=mount)

        sonde = build_ballnose("sonde",
                               self.reglages.diametre_outil * PROBE_TOOL_SCALE,
                               20.0, stickout=self.reglages.jauge_outil,
                               holder_type="ER16")
        bb = banc.part.bbox
        listes = [(f.points, f.normals) for f in passes]

        # Les points et les normales sont gardes AVANT le depistage : la vue
        # qui designe une surface doit marcher pendant l'analyse, pas
        # seulement apres.
        self._points_surfaces = [np.asarray(f.points, dtype=float)
                                 for f in passes]
        self._normales_surfaces = [np.asarray(f.normals, dtype=float).mean(axis=0)
                                   for f in passes]
        self._passes_finition = list(passes)

        # La liste s'affiche ENTIERE des maintenant, verdicts vides : les noms
        # ne dependent que des normales, donc ils sont deja connus. L'attente
        # devant une barre de progression pendant que le moteur decide les
        # surfaces une par une etait du temps perdu pour rien.
        couvertures: list = []
        self.publier(passes, couvertures, complet=False)

        n_total = len(CANONICAL_MOUNTS) * max(len(passes), 1)
        faits = 0

        for o in CANONICAL_MOUNTS:
            if o is CANONICAL_MOUNTS[0]:
                # La pose de DEPART : celle que la vue montre. On garde de quoi
                # relancer un solveur dessus, pour repondre plus tard a « et
                # avec quel outil, alors ? » sans refaire les six montages.
                from ...strategy_planner.setups import derive_mount
                bb_r = (bb.lo, bb.hi)
                self._contexte_diag = {
                    "champ": o.field(champ),
                    "mount": derive_mount(*bb_r),
                    "machine": machine,
                    "fabrique": fabrique,
                }

            def au_fil(k, _ecran, cov, _o=o):
                nonlocal faits
                # La couverture en cours est accrochee des le premier rappel :
                # ``screen_orientation`` remplit l'objet qu'il rendra, donc
                # l'attendre ferait perdre tout le montage courant.
                if cov not in couvertures:
                    couvertures.append(cov)
                faits += 1
                self.progres = 0.1 + 0.85 * faits / n_total
                self.etape = (f"montage « {_o.name} » — "
                              f"surface {k + 1}/{len(passes)}")
                if _o is CANONICAL_MOUNTS[0]:
                    while len(self._blocages) <= k:
                        self._blocages.append(())
                        self._blocages_outil.append(())
                    self._blocages[k] = _ecran.blocking_indices
                    self._blocages_outil[k] = _ecran.tool_blocking_indices
                self.publier(passes, couvertures, complet=False)

            screen_orientation(
                o, listes, champ, fabrique, machine, banc.tool,
                probe_tool=sonde, bbox_lo=bb.lo, bbox_hi=bb.hi, n_probe=6,
                on_pass=au_fil)

        self.etape = "rédaction"
        self.progres = 0.95
        # Les points echantillonnes sont GARDES : ce qui s'allume a l'ecran
        # doit etre exactement ce que le solveur a interroge.
        self._points_surfaces = [np.asarray(f.points, dtype=float)
                                 for f in passes]
        self._normales_surfaces = [np.asarray(f.normals, dtype=float).mean(axis=0)
                                   for f in passes]
        self._rediger(passes, couvertures)

    @staticmethod
    def _noms(passes) -> list[str]:
        """Les noms des surfaces, connus AVANT tout depistage.

        Ils ne dependent que de la normale moyenne, donc la liste peut
        s'afficher entierement des la premiere seconde et se remplir ensuite.
        Une liste dont les lignes apparaissent une par une bouge sous le
        curseur ; une liste complete dont les verdicts arrivent ne bouge pas.
        """
        noms, vus = [], {}
        for fp in passes:
            base = nommer(fp.normals.mean(axis=0))
            vus[base] = vus.get(base, 0) + 1
            noms.append((base if vus[base] == 1
                         else f"{base} ({vus[base]})").capitalize())
        return noms

    def _verdict_surface(self, i: int, nom: str, fp, couvertures,
                         *, complet: bool) -> Surface | None:
        """Le verdict d'UNE surface, ou ``None`` s'il n'est pas encore acquis.

        Une seule fonction pour les deux chemins — l'affichage en direct et la
        redaction finale. Ecrites separement, la version affichee et la version
        finale auraient divergé, et c'est la version affichee que l'operateur
        aurait lue.

        ``complet`` dit si TOUS les montages ont ete depistes pour cette
        surface. Tant qu'il est faux, « aucun montage ne la couvre » n'est pas
        une conclusion : c'est une absence de conclusion, et les deux ne se
        ressemblent que si l'on ne compte pas.
        """
        def ecran(cov):
            return cov.screens[i] if i < len(cov.screens) else None

        e0 = ecran(couvertures[0]) if couvertures else None
        if e0 is None:
            return None
        if e0.reachable:
            return Surface(
                numero=i + 1, n_points=fp.n_points, verdict="faisable",
                titre=nom,
                consigne="Rien à faire : la machine l'atteint dans la pose "
                         "de départ.",
                montage="tel quel")

        for cov in couvertures[1:]:
            e = ecran(cov)
            if e is not None and e.reachable:
                return Surface(
                    numero=i + 1, n_points=fp.n_points, verdict="a-changer",
                    titre=nom,
                    consigne=f"Retournez la pièce : posez "
                             f"{cov.orientation.face_down} sur le plateau.",
                    montage=cov.orientation.name,
                    detail="Cette surface regarde le plateau dans la pose de "
                           "départ : la machine ne peut pas l'atteindre sans "
                           "remonter la pièce.")
        if not complet:
            return None

        # Personne ne la couvre : dire ce qui bloque le moins mal.
        candidats = [c for c in couvertures if ecran(c) is not None]
        best = min(candidats,
                   key=lambda c: (ecran(c).n_unreachable,
                                  ecran(c).n_probe_tool_fails))
        sc = ecran(best)
        if True:
            part = sc.reachable_fraction * 100.0
            if sc.radius_fixable:
                consigne = (f"Essayez un outil plus fin : un diamètre "
                            f"{self.reglages.diametre_outil / 2:.0f} mm "
                            f"passerait là où celui-ci ne passe pas.")
            elif sc.n_probe_tool_fails and sc.probe_conclusive:
                # Le sondage dit seulement qu'un outil de MOITIE de diametre
                # ne suffit pas. Il ne dit pas qu'aucun outil ne passe — et
                # conclure « ajoutez un conge » depuis ce seul essai
                # contredisait le diagnostic, qui trouve parfois un diametre
                # qui passe (0,9 mm mesure sur la piece d'essai). Deux phrases
                # vraies qui se contredisent valent moins qu'une seule qui
                # renvoie a la mesure.
                consigne = ("Un outil de moitié de diamètre ne suffirait pas "
                            "non plus : il faut descendre plus bas, ou ajouter "
                            "un congé au dessin. Sélectionnez cette ligne pour "
                            "savoir quel diamètre passe.")
            else:
                # Toujours une action, meme quand le discriminant fin n'a pas
                # conclu : le motif rendu par le solveur, lui, est toujours la.
                # « Le moteur ne sait pas trancher » etait exact et inutile —
                # cela laissait l'utilisateur sans rien a faire, ce qui est la
                # seule chose qu'une consigne ne doit jamais faire.
                dominant = max(sc.reasons, key=sc.reasons.get) if sc.reasons else ""
                consigne = REMEDES.get(
                    dominant,
                    "aucune des six poses ne présente entièrement cette "
                    "surface")
                consigne = consigne[0].upper() + consigne[1:] + "."
            detail = (f"Atteinte à {part:.0f} % au mieux, en posant "
                      f"{best.orientation.face_down} sur le plateau.")
            if sc.n_probe_tool_fails and not sc.probe_conclusive:
                detail += (" Le moteur n'a pas pu vérifier si un outil plus "
                           "fin suffirait : à ce niveau de détail, il ne sait "
                           "pas distinguer un coin trop serré de sa propre "
                           "marge de sécurité.")
            return Surface(
                numero=i + 1, n_points=fp.n_points, verdict="impossible",
                titre=nom, consigne=consigne,
                montage=best.orientation.name, detail=detail)

    def publier(self, passes, couvertures, *, complet: bool) -> None:
        """Met a l'ecran ce qui est DEJA decide, en gardant la liste stable.

        Les surfaces non encore decidees restent presentes avec leur nom et le
        verdict « en-cours ». Faire apparaitre les lignes une par une ferait
        bouger la liste sous le curseur au moment ou l'operateur la lit.
        """
        noms = self._noms(passes)
        surfaces: list[Surface] = []
        montages_utiles: set[str] = set()
        for i, fp in enumerate(passes):
            v = self._verdict_surface(i, noms[i], fp, couvertures,
                                      complet=complet)
            if v is None:
                v = Surface(numero=i + 1, n_points=fp.n_points,
                            verdict="en-cours", titre=noms[i], consigne="")
            elif v.verdict == "a-changer":
                montages_utiles.add(v.montage)
            surfaces.append(v)
        self.surfaces = surfaces
        self.montages = ["tel quel"] + sorted(montages_utiles)

        n = {c: sum(1 for s in surfaces if s.verdict == c)
             for c in ("faisable", "a-changer", "impossible", "en-cours")}
        if n["en-cours"]:
            # Un resume PARTIEL le dit : « 3 surfaces usinables » pendant que
            # trois sont encore en analyse se lirait comme un total.
            self.resume = (f"{len(surfaces) - n['en-cours']} surface(s) "
                           f"décidées sur {len(surfaces)} — analyse en cours.")
            self.avertissements = []
            return

        bouts = [f"{n['faisable']} surface(s) usinables telles quelles"]
        if n["a-changer"]:
            bouts.append(f"{n['a-changer']} après avoir retourné la pièce")
        if n["impossible"]:
            bouts.append(f"{n['impossible']} qui demandent un changement")
        self.resume = ", ".join(bouts) + "."
        self.avertissements = [
            "Verdict établi sur un échantillon de 6 points par surface : il "
            "écarte, il ne garantit pas.",
            "Aucun bridage n'est modélisé. Un bridage réel retire des "
            "orientations, donc ce résultat est OPTIMISTE.",
        ]
        if len(self.montages) > 1:
            self.avertissements.append(
                "Plusieurs montages : chaque remontage repositionne la pièce, "
                "et les erreurs s'additionnent. Aucune tolérance ne peut être "
                "annoncée d'un montage à l'autre.")

    def _rediger(self, passes, couvertures) -> None:
        """Redaction FINALE : tous les montages ont ete depistes."""
        self.publier(passes, couvertures, complet=True)

    # ------------------------------------------------------------- les vues

    def invalider(self) -> None:
        """La scene a change : les images rendues et le verdict ne valent plus.

        Appele quand un reglage bouge. Le verdict precedent portait sur une
        autre machine et l'image sur une autre scene ; les garder affiches
        serait un mensonge que rien a l'ecran ne signalerait.
        """
        self.revision += 1
        self.surfaces, self.resume, self.montages = [], "", []
        self._points_surfaces = []
        self._normales_surfaces = []
        self._passes_finition = []
        self._refus_finition = []
        self._operations_simulees = []
        self._usinages = {}
        self.duree = None
        self._blocages = []
        self._blocages_outil = []
        self.diagnostics = {}
        self.film, self.simulation_note, self.simulation_resume = [], "", ""
        self.n_images = 0
        # La correction proposee portait sur l'ancienne pose : la garder
        # afficherait un decalage a ajouter a un decalage deja applique.
        self.correction = None

    def vue(self, chemin: Path, *, azimut: float = 35.0,
            elevation: float = 18.0) -> Path:
        """Une vue fixe de la scene. Rendue une a la fois.

        Le verrou n'est pas du zele : deux rendus PyVista simultanes ecrivant
        le meme fichier produisent une image tronquee, et un navigateur qui
        recoit une image tronquee n'affiche rien sans rien dire.
        """
        from ..debug import scene as sc

        with self._verrou:
            # MEME cadrage qu'a la simulation : « piece + brut + organes ».
            #
            # Le cadrage « machine » encadrait tout le volume de courses —
            # 300 x 240 x 180 mm — ce qui rendait une piece de 60 mm minuscule
            # au centre d'une cage en fil de fer. Et la vue de l'etape 2 ne
            # ressemblait alors pas a celle de l'etape 4, alors que c'est la
            # meme scene : l'operateur avait deux images a reconcilier au lieu
            # d'une a comprendre.
            camera = sc.camera_serie(self._banc, azimuth_deg=azimut,
                                     elevation_deg=elevation,
                                     window_size=(1100, 740), zoom=ZOOM_3D)
            return sc.capture(self._banc, chemin, camera=camera,
                              window_size=(1100, 740), background=FOND_3D,
                              hidden=("limits", "machine_axes"))

    def vue_surface(self, i: int, chemin: Path, *, azimut: float = 0.0,
                    elevation: float = 0.0) -> Path:
        """La piece, dans la pose de depart, avec UNE surface allumee.

        Pose de DEPART et non la pose ou la surface serait atteignable : la
        question que se pose l'operateur devant la liste est « laquelle
        est-ce ? », pas « a quoi ressemblerait un autre montage ». Montrer la
        piece autrement l'obligerait a reconcilier deux images de la meme
        piece, ce qui est le travail qu'on lui enleve. La consigne, elle, dit
        deja qu'il faut la retourner.

        **La camera se tourne VERS la surface.** Defaut vu sur une capture : la
        selection par defaut nommait « le dessous » et la vue montrait le
        dessus — les marques etaient cachees derriere la piece. Une vue qui
        nomme une surface sans la montrer ne designe rien, et oblige
        l'operateur a chercher l'angle a la main avant meme de savoir ce qu'il
        cherche. La direction de vue vient de la normale MOYENNE de la
        surface, celle que le moteur a calculee ; ``azimut`` et ``elevation``
        s'y ajoutent, de sorte que les boutons de rotation partent d'une vue
        qui montre deja quelque chose.
        """
        from ..debug import scene as sc

        if not (0 <= i < len(self._points_surfaces)):
            raise IndexError(f"surface {i} inconnue")
        pts = self._points_surfaces[i]
        teinte = couleur_verdict(self.surfaces[i].verdict
                                 if i < len(self.surfaces) else "")
        normale = (self._normales_surfaces[i]
                   if i < len(self._normales_surfaces) else None)
        # Les points refuses, marques plus gros et en rouge PAR-DESSUS la
        # surface : c'est la reponse a « ou, exactement ? ».
        from ..debug import palette as pal
        k = self._blocages[i] if i < len(self._blocages) else ()
        bloquants = ((pts[np.asarray(k, dtype=int)], pal.COLLISION)
                     if len(k) else None)
        with self._verrou:
            camera = sc.camera_serie(self._banc, azimuth_deg=azimut,
                                     elevation_deg=elevation,
                                     window_size=(900, 620), zoom=ZOOM_3D,
                                     direction=normale)
            from ..debug import palette
            return sc.capture(self._banc, chemin, camera=camera,
                              window_size=(900, 620), background=FOND_3D,
                              hidden=("limits", "machine_axes", "stock",
                                      "tool_cutting", "tool_shank",
                                      "tool_holder", "tool_spindle"),
                              surface=(pts, teinte),
                              blocking=bloquants,
                              part_color=palette.NEUTRAL)

    def vue_usinage(self, i: int, chemin: Path, *, fraction: float = 0.5,
                    azimut: float = 25.0, elevation: float = 15.0) -> Path:
        """La surface EN TRAIN d'etre usinee : machine basculee, outil en place.

        C'est une autre image que ``vue_surface``, et la difference est le
        sujet meme de cette page. ``vue_surface`` repond a « laquelle est-ce ? »
        et montre donc la piece dans la pose de DEPART, celle que l'operateur a
        sous les yeux. Celle-ci repond a « comment sera-t-elle usinee ? » et
        montre donc la machine BASCULEE a l'orientation trouvee, avec l'outil
        pose dessus et la trajectoire derriere lui.

        Les deux images de la meme piece ne se contredisent pas : elles
        repondent a deux questions, et chacune porte son titre.

        ``fraction`` place l'outil le long de la passe. La moitie par defaut :
        au debut l'outil est encore au bord et ne montre rien de l'usinage.
        """
        from ..debug import scene as sc

        u = self.usinage_surface(i)
        if u["etat"] != "usinable":
            raise ValueError(u["phrase"])
        tcp = np.asarray(u["tcp"], dtype=float)
        j = int(min(max(fraction, 0.0), 1.0) * (len(tcp) - 1))

        banc = self._banc
        with self._verrou:
            a0, c0, t0 = banc.inspect_a_deg, banc.inspect_c_deg, banc.inspect_tcp
            try:
                banc.inspect_a_deg = float(u["a_deg"])
                banc.inspect_c_deg = float(u["c_deg"])
                banc.inspect_tcp = tcp[j]
                # PAS de camera de serie ici : celle-la englobe le berceau
                # pour qu'une suite d'images ne saute pas, au prix d'un tiers
                # de vide et d'un outil coupe en haut. Pour une image UNIQUE,
                # le cadrage propre de ``capture`` porte sur « piece + brut +
                # OUTIL » — donc l'outil entier tient dans l'image, ce qui est
                # precisement ce qu'on vient regarder.
                #
                # Les organes machine sont caches : la question est « comment
                # cette face sera usinee », pas « ou est le plateau ». Le
                # basculement se lit sur la piece elle-meme, et les angles sont
                # ecrits a cote.
                return sc.capture(banc, chemin,
                                  azimuth_deg=azimut, elevation_deg=elevation,
                                  zoom=1.2,
                                  window_size=(900, 620), background=FOND_3D,
                                  hidden=("limits", "machine_axes", "machine",
                                          "stock"),
                                  toolpath=(tcp[:j + 1], None))
            finally:
                # La pose d'inspection est celle de la scene, pas de cette
                # image : la rendre sans la restaurer ferait basculer toutes
                # les vues suivantes sans que rien ne l'ait demande.
                banc.inspect_a_deg, banc.inspect_c_deg = a0, c0
                banc.inspect_tcp = t0

    def diagnostiquer(self, i: int) -> dict:
        """« Et avec quel outil, alors ? » — la question que le refus posait.

        Jusqu'ici l'atelier savait dire « un outil deux fois plus fin ne
        suffirait pas non plus ». C'est vrai, et ce n'est pas une cote a
        commander. Ici on cherche par dichotomie le plus gros diametre qui
        franchit les points bloquants, avec la geometrie de porte-outil reelle.

        Sur les points que MEME une machine ideale refuse, quand il y en a :
        ce sont les seuls qu'un autre montage ne leverait pas, donc les seuls
        dont l'outil soit responsable. Les autres relevent du montage, et
        proposer un outil plus fin pour eux serait faire changer d'outil pour
        un probleme de pose.

        Calcule A LA DEMANDE. Une dichotomie coûte cinq a sept resolutions par
        point ; l'ajouter a la verification allongerait une attente qu'on vient
        de raccourcir, pour une question qui ne se pose que sur les surfaces
        qui bloquent.
        """
        from ...strategy_planner.setups import plus_gros_outil_passant
        from ...tool_model import build_ballnose

        if i in self.diagnostics:
            return self.diagnostics[i]
        ctx = self._contexte_diag
        if not ctx or i >= len(self._points_surfaces):
            raise RuntimeError("aucune verification a diagnostiquer")

        # UNIQUEMENT les points qu'une machine ideale refuse aussi.
        #
        # Defaut trouve au premier essai : en me rabattant sur tous les points
        # bloquants quand il n'y en avait aucun de ce type, je diagnostiquais
        # « ce n'est plus une question d'outil mais de dessin » pour une
        # surface dont les six points sont bloques par LE MONTAGE — elle
        # regarde le plateau. Le moteur distingue les deux causes
        # (``mount_limited`` contre ``n_tool_limited``) et je venais d'ecraser
        # la distinction. Faire changer d'outil pour un probleme de pose est
        # exactement le mauvais conseil.
        blocages = self._blocages[i] if i < len(self._blocages) else ()
        indices = (self._blocages_outil[i]
                   if i < len(self._blocages_outil) else ())
        if not blocages:
            res = {"etat": "rien", "phrase":
                   "Aucun point bloquant dans la pose de départ."}
            self.diagnostics[i] = res
            return res
        if not indices:
            res = {"etat": "montage", "phrase":
                   f"Les {len(blocages)} point(s) bloquants le sont à cause du "
                   f"MONTAGE, pas de l'outil : même une machine sans "
                   f"limite de course les atteindrait. Changer d'outil n'y "
                   f"ferait rien — c'est la pose de la pièce qu'il faut "
                   f"changer."}
            self.diagnostics[i] = res
            return res

        pts = np.asarray(self._points_surfaces[i], dtype=float)
        nrm = np.tile(np.asarray(self._normales_surfaces[i], dtype=float),
                      (len(indices), 1))
        k = np.asarray(indices, dtype=int)
        d0 = float(self.reglages.diametre_outil)

        def fabrique_outil(d: float):
            return build_ballnose(f"D{d:.2f}", d, 20.0,
                                  stickout=self.reglages.jauge_outil,
                                  holder_type="ER16")

        r = plus_gros_outil_passant(
            ctx["fabrique"], ctx["champ"], ctx["mount"], ctx["machine"],
            pts[k], nrm, fabrique_outil=fabrique_outil,
            diametre_max=d0, diametre_min=0.4, tolerance=0.2)

        if r.diametre is None:
            phrase = (f"Aucun outil, même de 0,4 mm, ne franchit ces "
                      f"{r.n_points} point(s) : ce n'est plus une question "
                      f"d'outil mais de dessin. Il faut ouvrir le raccordement "
                      f"à cet endroit.")
            if not r.concluant:
                phrase += (" À ce niveau de détail, le moteur ne distingue "
                           "pas un coin trop serré de sa propre marge de "
                           "sécurité : à confirmer sur une pièce d'essai.")
        elif abs(r.diametre - d0) < 1e-9:
            phrase = (f"L'outil de {d0:.0f} mm franchit ces points : le blocage "
                      f"vient du montage, pas de l'outil.")
        else:
            phrase = (f"Un outil de Ø {r.diametre:.1f} mm franchit ces "
                      f"{r.n_points} point(s), là où le vôtre de "
                      f"{d0:.0f} mm ne passe pas.")
            if r.prudent:
                phrase += (" C'est une valeur prudente : le diamètre réellement "
                           "admissible est un peu plus gros.")
        res = {"etat": "fait", "diametre": r.diametre, "n_points": r.n_points,
               "n_essais": r.n_essais, "concluant": r.concluant,
               "prudent": r.prudent, "phrase": phrase,
               "detail": r.describe()}
        self.diagnostics[i] = res
        return res

    def simuler(self, dossier: Path, *, n: int = 40) -> None:
        """Rend les images de la simulation d'usinage, en tache de fond."""
        if self.occupe or not self.piece_chargee:
            return
        self.occupe = True
        self.progres = 0.0
        self.etape = "préparation"
        self.n_images = 0
        self.film = []
        self.simulation_note = ""
        self.simulation_resume = ""
        self.erreur = ""
        threading.Thread(target=self._simuler, args=(dossier, max(4, int(n))),
                         daemon=True).start()

    def _simuler(self, dossier: Path, n: int) -> None:
        # La simulation DEPLACE la pose d'inspection du banc : c'est ce qui
        # fait avancer l'outil. Elle la remet ensuite ou elle l'a prise, sans
        # quoi la vue de l'etape « Regardez » montrerait la machine basculee a
        # la derniere pose de l'ebauche, en contradiction avec la phrase qui
        # l'accompagne.
        banc = self._banc
        pose = (np.array(banc.inspect_tcp, dtype=float),
                float(banc.inspect_a_deg), float(banc.inspect_c_deg))
        try:
            self._faire_simuler(dossier, n)
        except Exception as e:                     # noqa: BLE001
            self.erreur = f"{type(e).__name__} : {e}"
        finally:
            banc.inspect_tcp, banc.inspect_a_deg, banc.inspect_c_deg = pose
            self.occupe = False
            self.progres = 1.0
            self.etape = ""

    def _faire_simuler(self, dossier: Path, n: int) -> None:
        """L'outil parcourt sa trajectoire d'ebauche, image par image.

        Ce n'est pas un tour de manege autour de la piece : la camera ne bouge
        pas, c'est l'OUTIL qui se deplace, sur la trajectoire que le planner
        d'ebauche a reellement calculee, et avec les A/C que ce plan a choisis.
        Ce qui s'affiche est donc ce qui serait poste — a la reserve pres,
        ecrite plus bas, de ce que cette gamme ne contient pas encore.

        Aucun calcul n'est fait ici. La gamme vient de ``plan_roughing``, les
        trajectoires des operations de cette gamme, les poses de la cinematique
        du moteur : l'interface place la camera et compte les images.
        """
        from ..debug import scene as sc

        banc = self._banc
        banc.machine = self.fiche.machine()
        banc._obstacles = None
        self._poser_piece()
        banc.set_default_tool("ballnose",
                              diameter=self.reglages.diametre_outil,
                              stickout=self.reglages.jauge_outil)

        dossier.mkdir(parents=True, exist_ok=True)
        self.etape = "calcul de la trajectoire d'ébauche"
        self.progres = 0.03
        plan, rapport = banc.plan_roughing_preview(
            layer_thickness=3.0, max_setups=MAX_INDEXATIONS,
            pitch=2.0, point_spacing=2.0)
        self._operations_simulees = list(plan.operations)

        if not plan.operations:
            # Rien plutot qu'une animation qui ne correspondrait a rien. Une
            # image fausse est pire qu'une absence d'image : l'absence, on la
            # remarque.
            #
            # Mais l'absence doit dire sa cause, et il y en a deux : « pas
            # assez de matiere vue » et « aucune indexation ne tient dans les
            # courses ». La premiere version ne connaissait que la premiere, et
            # une piece recalee de 6 mm se lisait donc comme une piece
            # inusinable.
            refus_entree = list(getattr(rapport, "refuses_entree", ()) or ())
            refus_course = list(getattr(rapport, "refuses_course", ()) or ())
            if refus_entree and not refus_course:
                pire_e = max(refus_entree,
                             key=lambda r: r.candidate.reachable_mm3)
                self.simulation_resume = ("aucune ébauche : l'outil ne peut "
                                          "entrer nulle part")
                self.simulation_note = (
                    f"Aucune trajectoire d'ébauche n'est montrée : sur les "
                    f"{len(refus_entree)} indexation(s) essayée(s), l'outil "
                    f"traverse la matière ou la machine avant même de couper. "
                    + pire_e.consigne()
                    + " Aucun programme n'est produit dans ce cas : un contact "
                      "hors coupe n'est pas une passe, c'est un choc.")
                return
            if refus_course:
                pire = min(refus_course, key=lambda r: max(r.course.exces_mm))
                self._proposer_correction(refus_course)
                self.simulation_resume = (
                    f"aucune ébauche : il manque "
                    f"{max(pire.course.exces_mm):.1f} mm de course "
                    f"{pire.course.axe_le_plus_court}")
                self.simulation_note = (
                    f"Aucune trajectoire d'ébauche n'est montrée, et ce n'est "
                    f"pas la pièce qui est en cause : les "
                    f"{len(refus_course)} indexation(s) essayée(s) produisent toutes "
                    f"des positions hors des courses de la machine. La moins "
                    f"éloignée : " + pire.course.consigne(
                        remede=not self._correction_impraticable)
                    + " Aucun programme n'est produit tant qu'il sortirait des "
                      "courses : une position hors course ne s'arrête pas à la "
                      "simulation, elle s'arrête à la machine, en pleine "
                      "matière."
                    + (" " + self._correction_impraticable
                       if self._correction_impraticable else ""))
                return
            self.simulation_note = (
                "Aucune trajectoire d'ébauche n'a pu être construite sur cette "
                "pièce : aucune des indexations essayées ne voit assez de "
                "matière à enlever. Il n'y a donc rien à montrer, et cette "
                "page n'affichera pas une animation de remplacement.")
            return

        # Une image coute un rendu complet ; le budget ``n`` se repartit donc
        # entre les operations, proportionnellement a la longueur de chaque
        # trajectoire, avec deux images au minimum par operation : une
        # reindexation qu'on ne voit pas est une reindexation qu'on croira
        # gratuite, alors qu'elle coûte une reprise.
        chemins = []
        for j in range(len(plan.operations)):
            P, R = banc.operation_path(j)
            chemins.append((P, R, rapport.chosen[j]))
        # La FINITION rejoint le film, apres l'ebauche : c'est elle qui fait la
        # piece, et la simulation ne la montrait pas.
        self.etape = "orientations de finition"
        finitions = self._operations_finition(banc)
        for f in finitions:
            chemins.append((f["tcp"], None,
                            _Indexation(f["a_deg"], f["c_deg"]), f))

        total = float(sum(len(P) for P, *_ in chemins)) or 1.0
        plans = []
        for entree in chemins:
            P, R, cand = entree[0], entree[1], entree[2]
            info = entree[3] if len(entree) > 3 else None
            q = max(2, int(round(n * len(P) / total)))
            idx = np.unique(np.linspace(1, max(len(P) - 1, 1), q).astype(int))
            plans.append((P, R, cand, idx, info))
        n_total = sum(len(p[3]) for p in plans)

        # Camera FIXE pour toute la serie, posee avant la premiere image. Le
        # cadrage automatique suit l'outil ; sur une suite d'images, la piece
        # sauterait alors d'une vue a l'autre et ce saut se lirait comme un
        # mouvement de la machine.
        banc.inspect_a_deg = float(plans[0][2].a_deg)
        banc.inspect_c_deg = float(plans[0][2].c_deg)
        camera = sc.camera_serie(banc, azimuth_deg=35.0, elevation_deg=18.0,
                                 window_size=(960, 640), zoom=ZOOM_3D)

        k = 0
        for numero, (P, R, cand, idx, info) in enumerate(plans, start=1):
            banc.inspect_a_deg = float(cand.a_deg)
            banc.inspect_c_deg = float(cand.c_deg)
            for i in idx:
                i = int(i)
                banc.inspect_tcp = P[i]
                self.etape = (f"usinage {numero}/{len(plans)} — "
                              f"image {k + 1} sur {n_total}")
                sc.capture(banc, dossier / f"f{k:03d}.png", camera=camera,
                           window_size=(960, 640), background=FOND_3D,
                           hidden=("limits", "machine_axes"),
                           toolpath=(P[:i + 1],
                                     None if R is None else R[:i + 1]))
                lect = banc.axis_readout()
                self.film.append({
                    "operation": numero,
                    "titre": (self._titre_finition(info, cand) if info
                              else self._titre_operation(numero, len(plans),
                                                         cand)),
                    "finition": info is not None,
                    "x": round(float(lect.x_mm or 0.0), 1),
                    "y": round(float(lect.y_mm or 0.0), 1),
                    "z": round(float(lect.z_mm or 0.0), 1),
                    "a": round(float(lect.a_deg or 0.0), 1),
                    "c": round(float(lect.c_deg or 0.0), 1),
                    "coupe": bool(R is None or not R[i]),
                    "dans_courses": bool(lect.within_limits),
                })
                k += 1
                self.n_images = k
                self.progres = 0.1 + 0.9 * k / max(n_total, 1)
        self._noter_simulation(plans, rapport)

    def _operations_finition(self, banc):
        """Les passes de FINITION a simuler, avec une orientation VERIFIEE.

        La simulation ne montrait que l'ebauche, et le disait. Or c'est la
        finition qui fait la piece : c'est elle qui donne l'etat de surface,
        c'est elle qui passe au plus pres, et c'est donc elle qu'on veut voir
        avant de lancer.

        Comment l'orientation est choisie, et pourquoi pas autrement
        ------------------------------------------------------------
        La premiere version prenait la NORMALE MOYENNE de la surface et en
        tirait le couple (A, C) par cinematique inverse. C'etait faux, et la
        mesure l'a dit tout de suite : sur le flanc avant de C05, A = -90°,
        C = 0° ne degage qu'en **1,2 % des points**. La normale moyenne dit ou
        REGARDE la surface ; elle ne dit rien de ce que l'outil rencontre en
        chemin — ni le berceau, ni le porte-outil, ni le rayon local. C'est la
        meme faute que partout ailleurs dans ce projet : lire une grandeur
        voisine de celle qu'on veut.

        L'orientation vient donc de ``decide_indexed_pass`` (M10), qui sonde
        quelques points en resolution complete, intersecte leurs ensembles
        admissibles pour obtenir des CANDIDATS, puis verifie chaque candidat en
        chaque point examine. Une passe n'est animee que si un candidat degage
        PARTOUT sur l'echantillon.

        Ce que cette fonction refuse de faire
        -------------------------------------
        Animer une passe sans orientation verifiee. Le cas est frequent — sur
        C05 aucune des six surfaces n'a d'orientation qui degage dans le
        montage de depart — et le refus est alors NOMME, avec le motif et le
        remede rendus par le moteur. Une animation de 1 % de couverture
        ressemble a un usinage ; c'est ce qui la rend dangereuse.

        Le montage, et la reserve qui reste
        -----------------------------------
        Tout se passe dans le montage de DEPART, le seul que la scene sait
        dessiner. Une surface que la verification a jugee « usinable » peut
        l'etre dans un RETOURNEMENT — c'est meme le cas de trois surfaces de
        C05 — et n'avoir aucune orientation ici. Les deux verdicts ne portent
        donc pas sur la meme question, et la note de simulation le dit au lieu
        de laisser lire une contradiction.
        """
        import time

        from ...accessibility_solver.solver import (AccessibilityConfig,
                                                    AccessibilitySolver,
                                                    tcp_from_contact)
        from ...strategy_planner.indexed_pass import decide_indexed_pass
        from ...strategy_planner.travel import course_lineaire

        self._refus_finition = []
        if not self._passes_finition:
            return []

        cfg = AccessibilityConfig(subdivisions=3, max_lead_deg=45.0,
                                  cutting_depth=0.0)
        solveur = AccessibilitySolver(banc.tool, banc.machine,
                                      banc.obstacle_field(), cfg,
                                      mount_offset_mm=banc.mount_offset)
        out = []
        t0 = time.time()
        n_s = len(self._passes_finition)
        for i, fp in enumerate(self._passes_finition):
            titre = (self.surfaces[i].titre if i < len(self.surfaces)
                     else f"surface {i + 1}")
            if time.time() - t0 > BUDGET_FINITION:
                self._refus_finition.append({
                    "surface": i, "titre": titre,
                    "phrase": (f"non examinée : les {BUDGET_FINITION:.0f} s "
                               "que la recherche d'orientations s'autorise "
                               "étaient épuisées."),
                })
                continue
            pts = np.asarray(fp.points, dtype=float)
            nrm = np.asarray(fp.normals, dtype=float)
            # Echantillon REGULIER : un echantillon aleatoire donnerait un
            # chiffre different a chaque lancement, et un chiffre qui bouge
            # sans que rien ne bouge n'est pas une mesure.
            k = np.unique(np.linspace(0, len(pts) - 1,
                                      min(ECHANTILLON_FINITION, len(pts))
                                      ).astype(int))
            self.etape = (f"orientation de finition — {titre} "
                          f"({i + 1}/{n_s})")
            # La barre avance pendant cette recherche : elle dure jusqu'a une
            # vingtaine de secondes, et une barre immobile pendant vingt
            # secondes se lit comme un calcul bloque. Les images occupent
            # ensuite 0,1 a 1,0 ; cette phase tient donc dans 0,02 a 0,10.
            self.progres = 0.02 + 0.08 * i / max(n_s, 1)
            u = self._decider_surface(i, solveur=solveur, banc=banc)
            if u["etat"] != "usinable":
                self._refus_finition.append({
                    "surface": i, "titre": titre, "phrase": u["phrase"],
                })
                continue
            out.append(u)
        return out

    def creux(self) -> list[dict]:
        """Les creux de la piece : volume, outil, orientation — ou ce qui bloque.

        C'est le renversement du point de vue demande : on ne liste plus les
        FACES du dessin mais les CREUX a vider, et pour chacun on repond aux
        trois questions dans l'ordre ou elles se posent. Le refus, quand il y
        en a un, nomme laquelle des trois bloque — donc ce qu'il faut changer.

        Calcule a la demande et mis en cache sur la revision, comme
        ``usinage_surface`` : l'operateur vient de cliquer, il attend, et la
        reponse ne doit pas changer tant que rien n'a bouge.
        """
        import time

        from ...accessibility_solver.solver import (AccessibilityConfig,
                                                    AccessibilitySolver)
        from ...feature_engine.volumes import CAVITE, decomposer
        from ...geometry_core import brep
        from ...stock_engine.material import MaterialState
        from ...stock_engine.stock import stock_from_part
        from ...strategy_planner.creux import (decider_creux,
                                               directions_candidates,
                                               vues_par_direction)
        from ...tool_model import build_endmill

        if self._creux.get("cle") == self.revision:
            return self._creux["liste"]
        banc = self._banc
        if banc is None or not self._passes_finition:
            return []

        t0 = time.time()
        verts, tris, _ = brep.tessellate(banc.part_shape, deflection=0.3)
        bb = brep.bounding_box(banc.part_shape)
        # Le brut du BANC, pas un brut refait ici : deux bruts differents pour
        # la meme piece donneraient deux comptes de matiere, et celui qu'on
        # croirait serait celui qu'on voit.
        stock = getattr(banc, "stock", None)
        if stock is None:
            stock = stock_from_part(bb, margin_xy=2.0, margin_z_top=2.0,
                                    margin_z_bottom=2.0)
        matiere = MaterialState.from_setup(stock, verts, tris, pitch=PAS_CREUX)
        volumes = decomposer(matiere, rayons_mm=list(RAYONS_CREUX),
                             separer_peau=True)
        cavites = [v for v in volumes if v.nature == CAVITE]

        cfg = AccessibilityConfig(subdivisions=3, max_lead_deg=45.0,
                                  cutting_depth=0.0)
        champ = banc.obstacle_field()

        def fabrique(rayon_mm):
            outil = build_endmill("creux", 2.0 * rayon_mm, 30.0,
                                  stickout=self.reglages.jauge_outil,
                                  holder_type="ER16")
            return (AccessibilitySolver(outil, banc.machine, champ, cfg,
                                        mount_offset_mm=banc.mount_offset),
                    outil)

        # Les lancers de rayons NE dependent pas du creux : les calculer une
        # fois par direction, et non une fois par couple (creux, direction),
        # est ce qui fait tenir l'ensemble en quelques secondes.
        vues = vues_par_direction(
            matiere, directions_candidates(self._passes_finition))

        liste = []
        for v in cavites:
            vc = decider_creux(v, self._passes_finition, matiere,
                               fabrique_solveur=fabrique,
                               machine=banc.machine,
                               mount_offset=banc.mount_offset, vues=vues,
                               echantillon=ECHANTILLON_CREUX)
            liste.append({
                "creux": len(liste),
                "titre": f"Creux {len(liste) + 1} — {v.cotes_mm}",
                "volume_mm3": round(v.volume_mm3),
                "cotes": v.cotes_mm,
                "etape": vc.etape,
                "usinable": vc.usinable,
                "outil": vc.outil,
                "rayon_mm": vc.rayon_mm,
                "fraction": round(vc.fraction, 3),
                "reprise_mm": vc.reprise_mm,
                "visibilite": round(vc.visibilite, 3),
                "surfaces": list(vc.surfaces),
                # Arrondis a l'affichage : la cinematique inverse rend
                # -34,99999999998599 pour un angle de -35, et un tel nombre
                # dans une phrase donne l'air d'une precision qui n'existe pas.
                "a_deg": None if vc.a_deg is None else round(vc.a_deg, 2),
                "c_deg": None if vc.c_deg is None else round(vc.c_deg, 2),
                "degagement": (None if vc.degagement_mm is None
                               else round(vc.degagement_mm, 2)),
                "phrase": vc.consigne(),
                "par_outil": [o.describe() for o in v.par_outil],
            })
        self._creux = {"cle": self.revision, "liste": liste,
                       "duree_s": round(time.time() - t0, 1),
                       "_volumes": cavites, "_matiere": matiere}
        return liste

    def vue_creux(self, i: int, chemin: Path, *, azimut: float = 25.0,
                  elevation: float = 15.0) -> Path:
        """Le creux selectionne, vu depuis sa bouche, la piece basculee.

        La meme image que « son usinage » pour une surface, mais pour un creux :
        la piece a l'orientation trouvee, l'outil retenu pose a l'entree, et
        les points de bord du creux dessines derriere lui.

        Un creux dont l'orientation n'a pas ete trouvee n'a pas d'image : la
        methode leve, elle ne rend pas une vue de la pose de depart qui
        laisserait croire que ça passe.
        """
        from ...tool_model import build_endmill
        from ..debug import scene as sc

        liste = self.creux()
        if not (0 <= i < len(liste)):
            raise ValueError("Ce creux n'existe pas.")
        c = liste[i]
        if not c["usinable"]:
            raise ValueError(c["phrase"])
        vol = self._creux["_volumes"][i]

        # L'outil descend par la bouche jusqu'au milieu du creux : au ras de
        # l'entree il ne montre rien de l'usinage, et tout en haut il eloigne
        # le nez de broche au point qu'il remplit l'image a lui seul.
        grille = self._creux["_matiere"].grid
        idx = np.argwhere(vol.masque)
        pts = (np.asarray(grille.origin, dtype=float)
               + (idx + 0.5) * float(grille.pitch))
        centre = pts.mean(axis=0)
        axe = self._banc.machine.tool_axis_in_part(c["a_deg"], c["c_deg"])
        # La bouche : le point du creux le plus AVANCE le long de l'axe outil.
        bouche = centre + axe * float((pts @ axe).max() - (centre @ axe))
        chemin_outil = np.array([bouche, centre])

        banc = self._banc
        # L'outil MONTRE doit etre celui que la phrase nomme. Le banc porte
        # l'outil par defaut — ici une Ø 6 mm hemispherique — et le laisser
        # ferait lire « on ebauche a la fraise de Ø 10 mm » sous l'image d'une
        # Ø 6. Une image qui contredit sa legende est pire que pas d'image.
        outil_creux = build_endmill(f"creux{2 * c['rayon_mm']:.0f}",
                                    diameter=2.0 * float(c["rayon_mm"]),
                                    flute_length=30.0,
                                    stickout=self.reglages.jauge_outil,
                                    holder_type="ER16")
        with self._verrou:
            a0, c0, t0 = banc.inspect_a_deg, banc.inspect_c_deg, banc.inspect_tcp
            outil0 = banc.tool
            try:
                banc.tool = outil_creux
                banc.inspect_a_deg = float(c["a_deg"])
                banc.inspect_c_deg = float(c["c_deg"])
                banc.inspect_tcp = chemin_outil[-1]
                return sc.capture(banc, chemin, fit="piece",
                                  azimuth_deg=azimut, elevation_deg=elevation,
                                  zoom=1.0,
                                  window_size=(900, 620), background=FOND_3D,
                                  hidden=("limits", "machine_axes", "machine",
                                          "stock"),
                                  toolpath=(chemin_outil, None))
            finally:
                banc.inspect_a_deg, banc.inspect_c_deg = a0, c0
                banc.inspect_tcp = t0
                banc.tool = outil0

    def usinage_surface(self, i: int) -> dict:
        """Comment CETTE surface sera usinee. Calcule a la demande, mis en cache.

        C'est la question que l'operateur pose en cliquant une ligne, et
        jusqu'ici l'atelier n'y repondait qu'a l'etape suivante, pour la piece
        entiere. Or l'orientation est une propriete de la SURFACE : la calculer
        surface par surface, quand on la demande, c'est rendre la reponse au
        moment ou la question se pose.

        Le meme calcul que la simulation, exactement — pas une approximation
        rapide pour l'affichage. Deux calculs differents pour la meme question
        donneraient deux reponses, et celle qu'on croirait serait celle qu'on
        voit.

        Coût mesure : de 0,1 s (refus au sondage) a 6,5 s (orientation trouvee
        et verifiee). C'est l'ordre de grandeur du diagnostic d'outil, qui est
        deja synchrone — l'operateur vient de cliquer, il attend.
        """
        from ...accessibility_solver.solver import (AccessibilityConfig,
                                                    AccessibilitySolver)

        if not (0 <= i < len(self._passes_finition)):
            return {"etat": "rien", "surface": i,
                    "phrase": "Cette surface n'a pas de passe de finition : "
                              "lancez d'abord la vérification."}
        cle = (self.revision, i)
        if self._usinages.get("cle") != self.revision:
            self._usinages = {"cle": self.revision}
        if cle in self._usinages:
            return self._usinages[cle]

        banc = self._banc
        cfg = AccessibilityConfig(subdivisions=3, max_lead_deg=45.0,
                                  cutting_depth=0.0)
        solveur = AccessibilitySolver(banc.tool, banc.machine,
                                      banc.obstacle_field(), cfg,
                                      mount_offset_mm=banc.mount_offset)
        u = self._decider_surface(i, solveur=solveur, banc=banc)
        self._usinages[cle] = u
        return u

    def _decider_surface(self, i: int, *, solveur, banc) -> dict:
        """L'orientation VERIFIEE d'une surface, ou le motif du refus.

        Une seule source pour la simulation et pour l'apercu d'une surface :
        voir ``usinage_surface``. La trajectoire rendue est celle des points de
        contact transportes au centre de l'outil — donc ce que la machine
        parcourra, et non un contour redessine pour l'affichage.
        """
        from ...accessibility_solver.solver import tcp_from_contact
        from ...strategy_planner.indexed_pass import decide_indexed_pass
        from ...strategy_planner.travel import course_lineaire

        # ``banc`` est PASSE, pas lu sur la session : ``_operations_finition``
        # le reçoit en parametre, et lire ``self._banc`` ici aurait fait mentir
        # sa signature — les deux sont le meme objet en production, et pas dans
        # un essai qui fournit un banc reduit.
        fp = self._passes_finition[i]
        titre = (self.surfaces[i].titre if i < len(self.surfaces)
                 else f"surface {i + 1}")
        pts = np.asarray(fp.points, dtype=float)
        nrm = np.asarray(fp.normals, dtype=float)
        # Echantillon REGULIER : un echantillon aleatoire donnerait un chiffre
        # different a chaque lancement, et un chiffre qui bouge sans que rien
        # ne bouge n'est pas une mesure.
        k = np.unique(np.linspace(0, len(pts) - 1,
                                  min(ECHANTILLON_FINITION, len(pts))
                                  ).astype(int))
        verdict = decide_indexed_pass(
            solveur, pts[k], nrm[k],
            n_probe=SONDES_FINITION, max_candidates=CANDIDATS_FINITION)
        base = {"surface": i, "titre": titre, "n_points": int(len(pts)),
                "n_verifies": int(len(k))}
        if not verdict.indexable:
            return dict(base, etat="refus", phrase=verdict.consigne())

        axe = banc.machine.tool_axis_in_part(verdict.a_deg, verdict.c_deg)
        tcp = np.array([tcp_from_contact(pts[j], nrm[j], axe, banc.tool)
                        for j in range(len(pts))])

        # LES COURSES LINEAIRES, sur la passe de finition aussi. Le solveur
        # d'accessibilite connait MACHINE_TRAVEL et le verifie aux points
        # examines ; la trajectoire, elle, passe aussi par des points non
        # examines, et c'est sur ses sommets que le verdict est exact. Sans ce
        # test, la finition etait tenue a une exigence plus faible que
        # l'ebauche — sur le meme ecran.
        course = course_lineaire(banc.machine, tcp, banc.mount_offset,
                                 verdict.a_deg, verdict.c_deg, exact=True)
        if not course.tient:
            return dict(base, etat="refus",
                        phrase=("l'orientation trouvée dégage, mais "
                                + course.consigne()))
        return dict(base, etat="usinable",
                    a_deg=float(verdict.a_deg), c_deg=float(verdict.c_deg),
                    tcp=tcp, degagement=verdict.min_clearance_mm,
                    consigne=verdict.consigne(), phrase=verdict.consigne())

    @staticmethod
    def _titre_operation(numero: int, sur: int, cand) -> str:
        return (f"Ébauche {numero}/{sur} — la pièce est basculée à "
                f"A = {cand.a_deg:.0f}°, C = {cand.c_deg:.0f}°")

    @staticmethod
    def _titre_finition(info: dict, cand) -> str:
        """Le titre porte la MESURE et sa PORTEE, pas seulement un nom.

        « Finition du dessus » ne dit pas si l'orientation dégage.
        « orientation vérifiée » ne dit pas sur combien de points. Le titre
        porte donc les deux nombres : ceux qu'on a examinés et ceux de la
        passe. Un opérateur qui lit « 150 sur 7 909 » sait que le reste n'a
        pas été regardé ; « vérifiée » seul le lui aurait caché.
        """
        deg = ("" if info["degagement"] is None
               else f", dégagement {info['degagement']:.1f} mm")
        return (f"Finition — {info['titre'].lower()} à A = {cand.a_deg:.0f}°, "
                f"C = {cand.c_deg:.0f}° · orientation vérifiée en "
                f"{info['n_verifies']} points répartis sur les "
                f"{info['n_points']} de la passe{deg}")

    def _noter_simulation(self, plans, rapport) -> None:
        """Ce que la simulation a montre, et ce qu'elle n'a PAS montre.

        Toutes les valeurs sont relues de l'etat reel — nombre d'images
        produites, fraction enlevee calculee par le planner, images hors
        courses comptees sur la lecture d'axes. Une phrase qui decrit un manque
        doit etre calculee, pas ecrite : ecrite, elle survit a la disparition
        du manque.
        """
        n_points = sum(len(P) for P, *_ in plans)
        hors = sum(1 for f in self.film if not f["dans_courses"])
        self._calculer_duree(rapport)
        # Compte les deux familles depuis les PLANS, et non depuis une phrase
        # ecrite : « seule l'ebauche est calculee » etait vrai hier et faux
        # aujourd'hui, et une phrase qui decrit un manque survit a la
        # disparition du manque si on ne la calcule pas.
        n_fin = sum(1 for p in plans if len(p) > 4 and p[4] is not None)
        n_eb = len(plans) - n_fin
        bouts = [
            f"{n_eb} opération(s) d'ébauche et {n_fin} de finition, "
            f"{n_points} points de trajectoire, {self.n_images} images.",
            f"L'ébauche enlève {rapport.removed_fraction * 100:.0f} % de la "
            f"matière du brut.",
        ]
        if rapport.unreachable_mm3 > 1.0:
            bouts.append(f"{rapport.unreachable_mm3:.0f} mm³ restent qu'aucune "
                         f"indexation essayée ne voit : il faudrait reposer "
                         f"la pièce autrement.")
        # Le reste de la matiere n'est pas inaccessible : il est simplement
        # au-dela du plafond que cette prevision se donne. Ne pas le dire
        # laisserait lire « l'ebauche enleve 30 % » comme une limite de la
        # machine, alors que c'est une limite de l'apercu.
        plafonne = (rapport.final_removable_mm3 - rapport.unreachable_mm3)
        if plafonne > 1.0 and len(plans) >= MAX_INDEXATIONS:
            bouts.append(f"{plafonne:.0f} mm³ restent que d'autres indexations "
                         f"verraient : cet aperçu s'arrête à "
                         f"{MAX_INDEXATIONS} indexations pour tenir en "
                         f"quelques secondes, ce n'est pas la gamme complète.")
        if rapport.gouged_voxels:
            bouts.append(f"ATTENTION : {rapport.gouged_voxels} points de la "
                         f"pièce finie sont touchés par l'ébauche.")
        # Les COURSES, mesurees sur la trajectoire et non comptees sur les
        # images. « 15 images sur 36 hors courses » comptait les 36 poses
        # echantillonnees pour l'animation : un chiffre qui depend du nombre
        # d'images demandees, pas de la gamme. Le planner mesure maintenant
        # chaque sommet du programme, et le domaine des courses etant une
        # boite, ce verdict est exact et sans reserve.
        # Les COURSES. Plus aucune operation retenue n'en sort — le planner
        # ecarte celles qui le feraient —, donc ce qui reste a dire est ce
        # qu'on a PERDU en les ecartant, et a quel prix on le recupererait.
        # C'est la partie utile : sur la poche C02, l'indexation la plus riche
        # est ecartee pour 0,2 mm.
        refus_course = list(getattr(rapport, "refuses_course", ()) or ())
        if refus_course:
            pire = min(refus_course, key=lambda r: max(r.course.exces_mm))
            self._proposer_correction(refus_course)
            perdu = max(r.candidate.reachable_mm3 for r in refus_course)
            bouts.append(f"{len(refus_course)} indexation(s) ont été ÉCARTÉES "
                         f"parce que leur trajectoire sortait des courses — la "
                         f"plus riche voyait {perdu:.0f} mm³. La moins "
                         f"éloignée : "
                         + pire.course.consigne(
                             remede=not self._correction_impraticable))
            if self._correction_impraticable:
                bouts.append(self._correction_impraticable)

        # Les indexations ecartees parce qu'on ne peut pas y ENTRER : un
        # organe qui ne doit jamais toucher traverse le brut ou la piece. Sans
        # cette phrase, une gamme a 2 % de matiere enlevee restait
        # inexpliquee — et j'avais ajoute le champ sans l'afficher, ce qui est
        # exactement l'echec silencieux que ce projet traque.
        refus_entree = list(getattr(rapport, "refuses_entree", ()) or ())
        if refus_entree:
            pire_e = max(refus_entree, key=lambda r: r.candidate.reachable_mm3)
            bouts.append(
                f"{len(refus_entree)} indexation(s) ont été écartées parce "
                f"qu'on ne peut pas y entrer en matière — la plus riche voyait "
                f"{pire_e.candidate.reachable_mm3:.0f} mm³ : "
                + pire_e.consigne())
        if hors:
            # Il reste un comptage sur les images, et il ne porte que sur les
            # poses affichees : la finition mesure ses courses passe par passe,
            # mais une pose intermediaire de l'animation peut sortir sans que
            # la trajectoire le fasse.
            bouts.append(f"{hors} image(s) sur {self.n_images} placent l'outil "
                         f"hors des courses réglées — comptage sur les poses "
                         f"affichées, pas sur la trajectoire entière.")
        # Les surfaces sans finition animee sont NOMMEES, avec le motif rendu
        # par le moteur. « Certaines surfaces ne sont pas montrées » ne dit ni
        # lesquelles ni pourquoi, et laisse croire a une limite de l'apercu la
        # ou il y a une limite de la MACHINE, de l'OUTIL ou du MONTAGE.
        refus_fin = list(self._refus_finition)
        if refus_fin:
            bouts.append(f"{len(refus_fin)} surface(s) n'ont pas de finition "
                         f"simulée, faute d'orientation qui dégage dans le "
                         f"montage de départ :")
            for r in refus_fin[:4]:
                bouts.append(f"« {r['titre']} » — {r['phrase']}")
            if len(refus_fin) > 4:
                # Les surfaces en trop sont NOMMEES sans leur motif, et non
                # regroupees sous « même raison » : rien ne dit qu'elles
                # partagent la leur, et l'ecrire serait affirmer une mesure
                # qu'on n'a pas faite.
                autres = ", ".join(f"« {r['titre']} »" for r in refus_fin[4:])
                bouts.append(f"Également sans finition : {autres} — motifs "
                             f"non détaillés ici.")
        if n_fin:
            bouts.append("Les orientations de finition montrées sont "
                         "vérifiées sur un ÉCHANTILLON réparti de chaque "
                         "passe, pas sur tous ses points : la mesure est donc "
                         "optimiste, et le titre de chaque image dit sur "
                         "combien de points elle porte.")
        manques = []
        # La finition est montree dans le montage de DEPART, celui que la vue
        # dessine. La verification, elle, essaie six montages. Une surface
        # « usinable » sans finition animee n'est donc pas une contradiction,
        # mais deux questions differentes — et c'est a dire, sans quoi les deux
        # pages se contrediraient a l'ecran.
        usinables = sum(1 for x in self.surfaces if x.verdict == "faisable")
        if usinables > n_fin:
            manques.append(
                f"la finition des surfaces usinables dans un AUTRE montage "
                f"({usinables} surfaces jugées usinables, {n_fin} avec une "
                f"orientation dans le montage de départ) : retourner la pièce "
                f"n'est pas encore simulé")
        manques.append("la matière qui disparaît au fur et à mesure (la pièce "
                       "finie est dessinée dès la première image)")
        # La reserve sur le bridage se CALCULE, et c'est tout l'objet du
        # troisieme groupe de reglages : « les brides ne sont pas modélisées du
        # tout » etait vrai hier et faux aujourd'hui, et une phrase qui decrit
        # un manque survit a la disparition du manque si on ne la calcule pas.
        if not self.bridage.fixtures_declares():
            manques.append("les brides, qui ne sont pas déclarées — tous les "
                           "verdicts sont donc optimistes")
        if self.bridage.fixtures_declares():
            # Un verdict rendu AVEC bridage doit dire lequel : le meme refus
            # n'a pas le meme remede selon qu'un mors ou la piece bloque, et
            # l'operateur doit pouvoir reconnaitre son montage.
            bouts.append("Bridage pris en compte — " + self.bridage.resume()
                         + " Une boîte surestime un bridage réel : un refus "
                           "peut donc être prudent, un passage est fiable.")
        if manques:
            bouts.append("Ce qui n'est PAS montré ici : "
                         + ", ".join(manques) + ".")
        self.simulation_note = " ".join(bouts)

        # La ligne COURTE, et elle doit le rester. Defaut trouve au
        # navigateur sur l'ecran de 10 pouces : en y ajoutant le temps puis
        # les refus, je l'avais portee a 172 px de haut — quatre lignes de
        # texte, qui poussaient tout le reste de la colonne hors de l'ecran.
        # Une ligne courte qui fait quatre lignes n'est plus une ligne courte,
        # et le detail a deja sa place dans la note repliee.
        #
        # Trois faits au plus, sans « (s) » : l'accord se calcule, et les
        # parentheses coûtent de la place sans rien dire.
        def _p(n, singulier, pluriel=None):
            """L'accord se CALCULE, et pas en collant un « s » au dernier mot.

            Premiere version : ``f"{n} {mot}{'s' if n > 1 else ''}"``, qui
            affichait « 4 indexation écartées » — le s sur l'adjectif, pas sur
            le nom. En français l'accord porte sur le groupe, donc le pluriel
            se donne en entier.
            """
            return f"{n} {singulier if n <= 1 else (pluriel or singulier + 's')}"

        courts = [f"{_p(n_eb, 'ébauche')} + {_p(n_fin, 'finition')}",
                  f"{rapport.removed_fraction * 100:.0f} % de matière"]
        n_ecartees = len(refus_course) + len(refus_entree)
        if n_ecartees:
            courts.append(_p(n_ecartees, "indexation écartée",
                             "indexations écartées"))
        if refus_fin:
            # La finition manquante a sa place ici MEME quand des indexations
            # ont ete ecartees : ce sont deux manques distincts, et n'en dire
            # qu'un laisserait croire que l'autre n'existe pas.
            courts.append(_p(len(refus_fin), "surface sans finition",
                             "surfaces sans finition"))
        if rapport.gouged_voxels:
            courts.append(_p(rapport.gouged_voxels, "point touché",
                             "points touchés"))
        if hors:
            courts.append(f"{hors} images hors courses")
        self.simulation_resume = " · ".join(courts)

    # ------------------------------------------------------------ le lancement

    def _calculer_duree(self, rapport) -> None:
        """Le temps PLANCHER du cycle d'ebauche, ou rien.

        Rien, et non un zero ni un « — », quand la matiere n'est pas connue :
        ``recipe_profiles`` refuse de deviner les parametres d'une matiere
        voisine, et un temps calcule sur une avance inventee serait la fausse
        valeur type. L'interface affiche alors ce qui manque : la matiere.

        Le temps ne couvre que l'EBAUCHE, parce que c'est d'elle que le plan
        porte les trajectoires. La finition a ses propres passes, et son temps
        viendra quand elles entreront dans le plan plutot que dans le film.
        """
        from ...strategy_planner.duree import duree_plan

        banc = self._banc
        self.duree = None
        ops = list(self._operations_simulees)
        if banc is None or not ops or not getattr(rapport, "courses", None):
            return
        rec = self.coupe.recette(banc.tool, banc.machine)
        if rec is None:
            return
        d = duree_plan(banc.machine, ops, rapport.courses, banc.mount_offset,
                       avance_coupe_mm_min=rec.feed_mm_min,
                       bridages=tuple(rec.clamped))
        self.duree = {
            "texte": d.texte(),
            "consigne": d.consigne(),
            "part_en_coupe": d.part_en_coupe,
            "coupe_s": d.coupe_s, "rapide_s": d.rapide_s,
            "rotation_s": d.rotation_s, "total_s": d.total_s,
            "longueur_coupe_mm": d.longueur_coupe_mm,
            "longueur_rapide_mm": d.longueur_rapide_mm,
            "avance_coupe_mm_min": d.avance_coupe_mm_min,
            "matiere": self.coupe.matiere,
        }

    def _proposer_correction(self, refus: list) -> None:
        """Le decalage de piece qui recupererait le plus de matiere.

        Pas « la moins eloignee » mais la PLUS RICHE parmi celles qu'un
        decalage rattrape : sur la poche C02, l'indexation ecartee vaut
        36 028 mm3 pour 0,2 mm de course — c'est celle-la qu'on veut
        recuperer, et le critere doit donc etre le gain, pas la distance.

        Les indexations qu'aucun decalage ne rattrape sont exclues d'office :
        proposer un decalage qui ne resoudrait rien enverrait refaire un
        montage pour rien.
        """
        from ...strategy_planner.travel import hauteur_sur_plateau

        self._correction_impraticable = ""
        banc = self._banc
        rattrapables = [r for r in refus
                        if r.course.correction_piece_mm is not None]

        # Un decalage PRATICABLE, et non seulement geometrique. Mesure sur
        # C05 : la boucle proposait -6 puis -24 mm, soit des cales a -30 mm
        # pour une piece posee sur 25 mm de cales — donc la piece enfoncee de
        # 5 mm DANS le plateau. Le calcul de course ne regarde pas le plateau,
        # et il le dit ; c'est donc ici, ou la pose est connue, que le remede
        # impraticable doit etre ecarte. Un remede impraticable est pire qu'un
        # constat : il fait demonter un montage pour rien.
        impraticables = []
        if banc is not None and getattr(banc, "part", None) is not None:
            z_bas = float(banc.part.bbox.lo[2])
            pose = np.asarray(banc.mount_offset_mm, dtype=float)
            gardes = []
            for r in rattrapables:
                d = np.asarray(r.course.correction_piece_mm, dtype=float)
                h = hauteur_sur_plateau(banc.machine, z_bas, pose + d)
                (gardes if h >= 0.0 else impraticables).append((r, h))
            rattrapables = [r for r, _ in gardes]

        if not rattrapables:
            self.correction = None
            if impraticables:
                _r, h = max(impraticables, key=lambda x: x[1])
                # Phrase CALCULEE a chaque fois, et non rangee dans la liste
                # des avertissements : celle-la est remplie au chargement et
                # aurait garde ce message apres que le decalage a change,
                # c'est-a-dire apres qu'il a cesse d'etre vrai.
                self._correction_impraticable = (
                    f"Le décalage qui rendrait utilisable l'indexation la plus "
                    f"riche ferait descendre la pièce {abs(h):.1f} mm SOUS le "
                    f"plateau : il n'est pas praticable. Il faut une course "
                    f"plus longue, des cales plus hautes au départ, ou une "
                    f"pièce moins haute.")
            return
        meilleur = max(rattrapables, key=lambda r: r.candidate.reachable_mm3)
        d = meilleur.course.correction_piece_mm
        axes = [f"{v:+.1f} mm en {nom}"
                for v, nom in zip(d, ("X", "Y", "Z")) if abs(v) >= 0.005]
        self.correction = {
            "dx": float(d[0]), "dy": float(d[1]), "dz": float(d[2]),
            "gain_mm3": float(meilleur.candidate.reachable_mm3),
            # Deux longueurs pour la meme proposition : la longue explique,
            # la courte tient dans la colonne du lecteur. Ce n'est pas un
            # doublon de donnee — les deux sortent du meme calcul, au meme
            # instant.
            "court": ("Reposer la pièce de " + ", ".join(axes)
                      + f" → {meilleur.candidate.reachable_mm3:.0f} mm³ "
                        f"de plus"),
            "texte": ("Reposer la pièce de " + ", ".join(axes)
                      + f" rendrait utilisable une indexation qui voit "
                        f"{meilleur.candidate.reachable_mm3:.0f} mm³ — "
                        f"vérifiez qu'elle ne touche alors ni le plateau ni le "
                        f"berceau."),
        }

    def appliquer_correction(self) -> bool:
        """Applique le decalage propose, puis invalide tout ce qui en depend.

        Rend ``False`` quand il n'y a rien a appliquer, plutot que de lever :
        deux clics rapides sur le meme bouton ne sont pas une erreur.
        """
        c = self.correction
        if not c:
            return False
        self.reglages.decalage_piece_x += float(c["dx"])
        self.reglages.decalage_piece_y += float(c["dy"])
        self.reglages.decalage_piece_z += float(c["dz"])
        self.invalider()
        return True

    def lancement(self) -> dict:
        """Ce qui manque pour qu'un programme puisse partir a la machine.

        Les conditions ne sont PAS ecrites ici : elles viennent de
        ``production_gate``, c'est-a-dire du meme endroit que celui ou le depot
        les fait respecter. Les recopier dans l'interface aurait produit deux
        listes qui divergent, et celle qui aurait divergé serait celle qu'on lit
        a l'ecran.

        L'atelier n'a ni approbation de gamme ni dossier de calibration : une
        machine en kit qu'on vient d'assembler n'en a pas. Les quatre
        conditions ressortent donc non remplies, et c'est exact — il n'y a
        aucune raison de l'habiller.
        """
        from ... import production_gate

        liste = production_gate.exigences(
            approbation=False, calibration=None,
            destination=production_gate.MATERIEL)
        return {
            "jamais": production_gate.JAMAIS,
            "possible": not any(e.bloque for e in liste),
            "conditions": [{"titre": e.titre, "action": e.action,
                            "satisfaite": e.satisfaite, "bloque": e.bloque}
                           for e in liste],
        }

    # --------------------------------------------------------------- etat

    # ------------------------------------------------- la fiche machine

    def fiche_etat(self) -> dict:
        """La fiche, telle que l'ecran la montre : groupee et commentee."""
        from ...machine_model.fiche import (CRITIQUES, PROVENANCES,
                                            RESERVEES_A_LA_CALIBRATION,
                                            TEXTE_PROVENANCE)

        groupes = []
        for cle, titre, params in self.fiche.groupes():
            groupes.append({
                "cle": cle, "titre": titre,
                "cotes": [{
                    "cle": p.cle, "libelle": p.libelle, "valeur": p.valeur,
                    "unite": p.unite, "effet": p.effet,
                    "comment_mesurer": p.comment_mesurer, "aide": p.aide,
                    "provenance": p.provenance,
                    "provenance_texte": TEXTE_PROVENANCE[p.provenance],
                    "moyen": p.moyen, "incertitude": p.incertitude,
                    "date_mesure": p.date_mesure,
                    "suffisante": p.suffisante,
                    "critique": p.cle in CRITIQUES,
                    "calibration_seule": p.cle in RESERVEES_A_LA_CALIBRATION,
                    "mini": p.mini, "maxi": p.maxi,
                    "decimales": p.decimales,
                    "booleen": p.unite == "oui/non",
                } for p in params],
            })
        return {
            "nom": self.fiche.nom,
            "resume": self.fiche.resume(),
            "mesuree": self.fiche.mesuree,
            "n_a_mesurer": len(self.fiche.a_mesurer()),
            "n_critiques": len(self.fiche.a_mesurer(critiques_seulement=True)),
            "fichier": str(FICHIER_MACHINE),
            "provenances": list(PROVENANCES),
            "groupes": groupes,
        }

    def regler_cote(self, cle: str, valeur: float, *, moyen: str = "",
                    incertitude: float | None = None) -> None:
        """Ecrit une cote, puis invalide tout ce qui en dependait.

        ``moyen`` vide = saisie a la main, donc un ESSAI. ``moyen`` renseigne =
        une mesure, avec ce qui l'a mesuree. La fiche refuse d'elle-meme de
        marquer « mesuree » une cote qui ne peut venir que de la calibration.

        L'enregistrement est IMMEDIAT et non differe par un bouton
        « enregistrer » : une cote relevee sur la machine puis perdue parce
        qu'on a fermé la fenêtre est exactement le genre de perte qui fait
        qu'on ne remesure jamais.
        """
        if moyen.strip():
            self.fiche.mesurer(cle, valeur, moyen=moyen,
                               incertitude=incertitude)
        else:
            self.fiche.regler(cle, valeur)
        self.fiche.enregistrer(FICHIER_MACHINE)
        self._fiche_vers_reglages()
        # Une cote de machine change la FAISABILITE : tout verdict rendu sous
        # l'ancienne machine porte sur une machine qui n'existe plus.
        self.invalider()

    def _fiche_vers_reglages(self) -> None:
        """Recopie dans ``reglages`` les cotes que les anciens ecrans lisent.

        Un seul sens, et c'est voulu : la fiche fait autorite. Recopier dans
        les deux sens aurait cree deux sources pour la meme cote, et celle
        qu'on croirait serait celle qu'on voit.
        """
        for attr, cle in REGLAGES_VERS_FICHE.items():
            setattr(self.reglages, attr, self.fiche.valeur(cle))

    def regler_depuis_l_ancien_ecran(self, corps: dict) -> list[str]:
        """Les curseurs de l'etape 3, rediriges vers la fiche.

        Les cotes que la fiche porte y sont ecrites — donc notees ESSAI, ce
        qu'elles sont : personne n'a mesure quoi que ce soit en bougeant un
        curseur. Les autres (le diametre de l'outil, le decalage de la piece)
        ne sont pas des cotes de machine et restent sur ``Reglages``.

        Rend la liste des cles refusees, avec leur motif.
        """
        refus = []
        touche = False
        for k, v in corps.items():
            cle = REGLAGES_VERS_FICHE.get(k)
            if cle is not None:
                try:
                    self.fiche.regler(cle, float(v))
                    touche = True
                except (ValueError, TypeError) as e:
                    refus.append(str(e))
            elif hasattr(self.reglages, k):
                try:
                    setattr(self.reglages, k, float(v))
                except (TypeError, ValueError):
                    refus.append(f"{k} : valeur illisible")
        if touche:
            self.fiche.enregistrer(FICHIER_MACHINE)
        self._fiche_vers_reglages()
        self.invalider()
        return refus

    def etat(self) -> dict:
        return {
            "piece": self.piece,
            "dimensions": self.dimensions,
            "import_detail": self.import_detail,
            "chargee": self.piece_chargee,
            "occupe": self.occupe,
            "progres": self.progres,
            "etape": self.etape,
            "erreur": self.erreur,
            "resume": self.resume,
            "montages": self.montages,
            "avertissements": self.avertissements,
            "n_images": self.n_images,
            "revision": self.revision,
            "rendu": rendu_3d(),
            "legende": legende(),
            "origine": self.origine,
            "film": self.film,
            "simulation_note": self.simulation_note,
            "simulation_resume": self.simulation_resume,
            "duree": self.duree,
            "matiere": self.coupe.matiere,
            "matieres": self.coupe.matieres(),
            "bridage": {"forme": self.bridage.forme,
                        "formes": self.bridage.formes(),
                        "resume": self.bridage.resume(),
                        "prise_mm": self.bridage.prise_mm,
                        "axe_serrage": self.bridage.axe_serrage,
                        "n_brides": self.bridage.n_brides,
                        "recouvrement_mm": self.bridage.recouvrement_mm,
                        "hauteur_brides_mm": self.bridage.hauteur_brides_mm,
                        "declare": self.bridage.forme != "aucun"},
            "correction": self.correction,
            "decalage_piece": list(self.reglages.decalage_piece),
            "reglages": {k: getattr(self.reglages, k)
                         for k in vars(Reglages()) if not k.startswith("_")},
            "surfaces": [dict(vars(s), etiquette=s.etiquette,
                              couleur=couleur_verdict(s.verdict))
                         for s in self.surfaces],
            "diagnostics": {str(k): v for k, v in self.diagnostics.items()},
        }
