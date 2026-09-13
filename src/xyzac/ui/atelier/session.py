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

import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

CORPUS = Path(__file__).resolve().parents[4] / "tests" / "corpus" / "step"

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

#: Resserrage du cadrage des vues de l'atelier.
#:
#: Le cadrage porte sur « piece + brut + organes machine », ce qui le rend
#: stable a toute indexation A/C — mais le plateau et le berceau sont bien plus
#: grands qu'une piece de kit, qui n'occupait alors qu'un tiers de l'image.
#: 1,6 a ete choisi en regardant les deux poses extremes d'une gamme (A = 0 et
#: A = -90) : au-dela, la piece commence a sortir du cadre aux poses basculees.
#: Verifie sur le corpus, pas prouve pour toute taille de piece.
ZOOM_3D = 1.6


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
        self.film, self.simulation_note, self.simulation_resume = [], "", ""
        self.n_images = 0
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
        machine = self.reglages.machine()
        banc.machine = machine
        banc._obstacles = None

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

        # La liste s'affiche ENTIERE des maintenant, verdicts vides : les noms
        # ne dependent que des normales, donc ils sont deja connus. L'attente
        # devant une barre de progression pendant que le moteur decide les
        # surfaces une par une etait du temps perdu pour rien.
        couvertures: list = []
        self.publier(passes, couvertures, complet=False)

        n_total = len(CANONICAL_MOUNTS) * max(len(passes), 1)
        faits = 0

        for o in CANONICAL_MOUNTS:
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
                consigne = ("Un outil deux fois plus fin ne suffirait pas non "
                            "plus : le raccordement est trop serré. Ajoutez un "
                            "congé au dessin, ou acceptez le rayon de l'outil "
                            "dans ce coin.")
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
        self.film, self.simulation_note, self.simulation_resume = [], "", ""
        self.n_images = 0

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
                              part_color=palette.NEUTRAL)

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
        banc.machine = self.reglages.machine()
        banc._obstacles = None
        banc.set_default_tool("ballnose",
                              diameter=self.reglages.diametre_outil,
                              stickout=self.reglages.jauge_outil)

        dossier.mkdir(parents=True, exist_ok=True)
        self.etape = "calcul de la trajectoire d'ébauche"
        self.progres = 0.03
        plan, rapport = banc.plan_roughing_preview(
            layer_thickness=3.0, max_setups=MAX_INDEXATIONS,
            pitch=2.0, point_spacing=2.0)

        if not plan.operations:
            # Rien plutot qu'une animation qui ne correspondrait a rien. Une
            # image fausse est pire qu'une absence d'image : l'absence, on la
            # remarque.
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
        total = float(sum(len(P) for P, _, _ in chemins)) or 1.0
        plans = []
        for P, R, cand in chemins:
            q = max(2, int(round(n * len(P) / total)))
            idx = np.unique(np.linspace(1, max(len(P) - 1, 1), q).astype(int))
            plans.append((P, R, cand, idx))
        n_total = sum(len(idx) for *_, idx in plans)

        # Camera FIXE pour toute la serie, posee avant la premiere image. Le
        # cadrage automatique suit l'outil ; sur une suite d'images, la piece
        # sauterait alors d'une vue a l'autre et ce saut se lirait comme un
        # mouvement de la machine.
        banc.inspect_a_deg = float(plans[0][2].a_deg)
        banc.inspect_c_deg = float(plans[0][2].c_deg)
        camera = sc.camera_serie(banc, azimuth_deg=35.0, elevation_deg=18.0,
                                 window_size=(960, 640), zoom=ZOOM_3D)

        k = 0
        for numero, (P, R, cand, idx) in enumerate(plans, start=1):
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
                    "titre": self._titre_operation(numero, len(plans), cand),
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

    @staticmethod
    def _titre_operation(numero: int, sur: int, cand) -> str:
        return (f"Ébauche {numero}/{sur} — la pièce est basculée à "
                f"A = {cand.a_deg:.0f}°, C = {cand.c_deg:.0f}°")

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
        bouts = [
            f"{len(plans)} opération(s) d'ébauche, {n_points} points de "
            f"trajectoire, {self.n_images} images.",
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
        if hors:
            bouts.append(f"{hors} image(s) sur {self.n_images} placent l'outil "
                         f"HORS des courses réglées plus haut : la machine "
                         f"ne pourrait pas y aller.")
        bouts.append(
            "Ce qui n'est PAS montré ici : les passes de finition (seule "
            "l'ébauche est calculée), la matière qui disparaît au fur et à "
            "mesure (la pièce finie est dessinée dès la première image), et "
            "les brides, qui ne sont pas modélisées du tout.")
        self.simulation_note = " ".join(bouts)

        # La ligne courte : seulement ce qui change une decision.
        courts = [f"{len(plans)} opération(s) d'ébauche",
                  f"{rapport.removed_fraction * 100:.0f} % de matière enlevée"]
        if rapport.gouged_voxels:
            courts.append(f"{rapport.gouged_voxels} points de la pièce touchés")
        if hors:
            courts.append(f"{hors} image(s) sur {self.n_images} HORS courses")
        self.simulation_resume = " · ".join(courts)

    # ------------------------------------------------------------ le lancement

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
            "reglages": {k: getattr(self.reglages, k)
                         for k in vars(Reglages()) if not k.startswith("_")},
            "surfaces": [dict(vars(s), etiquette=s.etiquette,
                              couleur=couleur_verdict(s.verdict))
                         for s in self.surfaces],
        }
