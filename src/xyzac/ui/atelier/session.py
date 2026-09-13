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

import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

CORPUS = Path(__file__).resolve().parents[4] / "tests" / "corpus" / "step"


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
                         "faut un outil plus fin, ou un conge plus large au "
                         "dessin",
    "COLLISION_NECK": "le col de l'outil frotte : prenez un outil a col reduit",

    "COLLISION_SHANK": "la tige de l'outil touche la piece : prenez un outil "
                       "plus long, ou a col plus fin",
    "COLLISION_HOLDER": "la pince touche la piece : sortez l'outil davantage "
                        "de la pince",
    "COLLISION_SPINDLE": "le nez de broche touche la piece : sortez l'outil "
                         "davantage de la pince",
    "MACHINE_COLLISION": "l'outil taperait dans le plateau ou le berceau : "
                         "surelevez la piece, ou posez-la autrement",
    "MACHINE_TRAVEL": "la machine n'a pas assez de course : rapprochez la "
                      "piece du centre du plateau, ou allongez la course",
    "AXIS_LIMITS": "la bascule A ne va pas assez loin pour presenter cette "
                   "surface : il faut retourner la piece",
    "SINGULARITY": "orientation verticale ecartee",
    "LEAD_LIMIT": "aucune inclinaison admise ne convient ici",
    "BACK_FACING": "cette surface regarde a l'oppose de tout acces",
}


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
                (0, 1): "arriere", (0, -1): "avant"}
        cle = (1 if x > 0.5 else -1 if x < -0.5 else 0,
               1 if y > 0.5 else -1 if y < -0.5 else 0)
        return f"le flanc {cote.get(cle, 'lateral')}"
    return "une surface inclinee"


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
            self._banc = None
            self.piece = chemin.name
            self.dimensions = ""
            self.import_detail = ""
            self.surfaces, self.resume, self.montages = [], "", []
            self.erreur = str(e)
            return
        banc.set_default_tool("ballnose",
                              diameter=self.reglages.diametre_outil,
                              stickout=self.reglages.jauge_outil)
        self._banc = banc
        self.piece = chemin.name
        t = info.size
        self.dimensions = f"{t[0]:.0f} x {t[1]:.0f} x {t[2]:.0f} mm"
        # Le diagnostic du moteur est ecrit pour le moteur. On n'en garde ici
        # que ce qui se decide : combien de solides, combien de surfaces, et
        # si l'import a du reparer quelque chose.
        bouts = [f"{info.n_solids} solide(s)", f"{info.n_faces} surfaces"]
        if info.volume_mm3:
            bouts.append(f"{info.volume_mm3 / 1000.0:.0f} cm3 de matiere")
        self.import_detail = "Fichier lu sans probleme : " + ", ".join(bouts) + "."
        # ``healing`` est renseigne MEME quand rien n'a ete repare — il dit
        # alors « Reparation non appliquee ». L'introduire par « Reparation
        # appliquee : » produisait la phrase « Reparation appliquee :
        # Reparation non appliquee », qui se contredit en six mots. On ne
        # mentionne donc la reparation que lorsqu'il y en a eu une.
        if info.healing and not info.healing.lower().startswith(
                ("reparation non", "réparation non")):
            self.import_detail += f" Reparation : {info.healing}"
        self.surfaces = []
        self.resume = ""
        self.montages = []
        self.avertissements = list(banc.messages)
        self.n_images = 0
        self.erreur = ""

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
        self.etape = "preparation"
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

        self.etape = "decoupe des surfaces"
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
            self.resume = "Aucune surface a finir n'a ete trouvee sur cette piece."
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

        couvertures = []
        for i, o in enumerate(CANONICAL_MOUNTS):
            self.etape = f"essai du montage « {o.name} »"
            self.progres = 0.1 + 0.8 * i / len(CANONICAL_MOUNTS)
            couvertures.append(screen_orientation(
                o, listes, champ, fabrique, machine, banc.tool,
                probe_tool=sonde, bbox_lo=bb.lo, bbox_hi=bb.hi, n_probe=6))

        self.etape = "redaction"
        self.progres = 0.95
        self._rediger(passes, couvertures)

    def _rediger(self, passes, couvertures) -> None:
        """Traduit les verdicts du moteur en consignes. N'en invente aucun."""
        from ...strategy_planner.setups import CANONICAL_MOUNTS

        tel_quel = couvertures[0]
        surfaces: list[Surface] = []
        montages_utiles: set[str] = set()

        vus: dict[str, int] = {}
        for i, fp in enumerate(passes):
            base = nommer(fp.normals.mean(axis=0))
            vus[base] = vus.get(base, 0) + 1
            nom = base if vus[base] == 1 else f"{base} ({vus[base]})"
            sc0 = tel_quel.screens[i]
            if sc0.reachable:
                surfaces.append(Surface(
                    numero=i + 1, n_points=fp.n_points, verdict="faisable",
                    titre=nom.capitalize(),
                    consigne="Rien a faire : la machine l'atteint dans la pose "
                             "de depart.",
                    montage="tel quel"))
                continue

            # Un autre montage la rend-il atteignable ?
            mieux = None
            for cov in couvertures[1:]:
                if cov.screens[i].reachable:
                    mieux = cov
                    break
            if mieux is not None:
                montages_utiles.add(mieux.orientation.name)
                surfaces.append(Surface(
                    numero=i + 1, n_points=fp.n_points, verdict="a-changer",
                    titre=nom.capitalize(),
                    consigne=f"Retournez la piece : posez "
                             f"{mieux.orientation.face_down} sur le plateau.",
                    montage=mieux.orientation.name,
                    detail="Cette surface regarde le plateau dans la pose de "
                           "depart : la machine ne peut pas l'atteindre sans "
                           "remonter la piece."))
                continue

            # Personne ne la couvre : dire ce qui bloque le moins mal.
            best = min(couvertures,
                       key=lambda c: (c.screens[i].n_unreachable,
                                      c.screens[i].n_probe_tool_fails))
            sc = best.screens[i]
            part = sc.reachable_fraction * 100.0
            if sc.radius_fixable:
                consigne = (f"Essayez un outil plus fin : un diametre "
                            f"{self.reglages.diametre_outil / 2:.0f} mm "
                            f"passerait la ou celui-ci ne passe pas.")
            elif sc.n_probe_tool_fails and sc.probe_conclusive:
                consigne = ("Un outil deux fois plus fin ne suffirait pas non "
                            "plus : le raccordement est trop serre. Ajoutez un "
                            "conge au dessin, ou acceptez le rayon de l'outil "
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
                    "aucune des six poses ne presente entierement cette "
                    "surface")
                consigne = consigne[0].upper() + consigne[1:] + "."
            detail = (f"Atteinte a {part:.0f} % au mieux, en posant "
                      f"{best.orientation.face_down} sur le plateau.")
            if sc.n_probe_tool_fails and not sc.probe_conclusive:
                detail += (" Le moteur n'a pas pu verifier si un outil plus "
                           "fin suffirait : a ce niveau de detail, il ne sait "
                           "pas distinguer un coin trop serre de sa propre "
                           "marge de securite.")
            surfaces.append(Surface(
                numero=i + 1, n_points=fp.n_points, verdict="impossible",
                titre=nom.capitalize(), consigne=consigne,
                montage=best.orientation.name, detail=detail))

        self.surfaces = surfaces
        self.montages = ["tel quel"] + sorted(montages_utiles)
        n_ok = sum(1 for s in surfaces if s.verdict == "faisable")
        n_chg = sum(1 for s in surfaces if s.verdict == "a-changer")
        n_non = sum(1 for s in surfaces if s.verdict == "impossible")
        bouts = [f"{n_ok} surface(s) usinables telles quelles"]
        if n_chg:
            bouts.append(f"{n_chg} apres avoir retourne la piece")
        if n_non:
            bouts.append(f"{n_non} qui demandent un changement")
        self.resume = ", ".join(bouts) + "."
        self.avertissements = [
            "Verdict etabli sur un echantillon de 6 points par surface : il "
            "ecarte, il ne garantit pas.",
            "Aucun bridage n'est modelise. Un bridage reel retire des "
            "orientations, donc ce resultat est OPTIMISTE.",
        ]
        if len(self.montages) > 1:
            self.avertissements.append(
                "Plusieurs montages : chaque remontage repositionne la piece, "
                "et les erreurs s'additionnent. Aucune tolerance ne peut etre "
                "annoncee d'un montage a l'autre.")

    # ------------------------------------------------------------- les vues

    def vue(self, chemin: Path, *, azimut: float = 35.0, elevation: float = 18.0,
            cadrage: str = "machine") -> Path:
        from ..debug import scene as sc

        return sc.capture(self._banc, chemin, azimuth_deg=azimut,
                          elevation_deg=elevation, fit=cadrage)

    def simuler(self, dossier: Path, *, n: int = 24) -> None:
        """Rend les images de la simulation, en tache de fond."""
        if self.occupe or not self.piece_chargee:
            return
        self.occupe = True
        self.progres = 0.0
        self.etape = "simulation"
        self.n_images = 0
        threading.Thread(target=self._simuler, args=(dossier, n),
                         daemon=True).start()

    def _simuler(self, dossier: Path, n: int) -> None:
        """Tour complet autour de la piece.

        V0 assumee : la simulation montre la SCENE, pas encore l'outil qui
        parcourt sa trajectoire. Le dire plutot que de laisser croire qu'une
        gamme a ete calculee — la trajectoire complete demande la verification
        de M10, et elle se compte en minutes.
        """
        from ..debug import scene as sc

        try:
            dossier.mkdir(parents=True, exist_ok=True)
            for i in range(n):
                sc.capture(self._banc, dossier / f"f{i:03d}.png",
                           azimuth_deg=360.0 * i / n, elevation_deg=18.0,
                           fit="machine", window_size=(900, 620))
                self.n_images = i + 1
                self.progres = (i + 1) / n
        except Exception as e:                     # noqa: BLE001
            self.erreur = f"{type(e).__name__} : {e}"
        finally:
            self.occupe = False
            self.etape = ""

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
            "reglages": {k: getattr(self.reglages, k)
                         for k in vars(Reglages()) if not k.startswith("_")},
            "surfaces": [vars(s) for s in self.surfaces],
        }
