"""Diagnostic et reparation d'un STEP importe.

Le corpus synthetique du projet est propre par construction : genere par OCCT,
cousu, oriente, aux tolerances par defaut. Un STEP reel ne l'est pas. Il vient
d'un autre noyau (Parasolid, ACIS), a traverse une traduction, et arrive avec
des faces mal cousues, des tolerances heterogenes de plusieurs ordres de
grandeur, parfois des shells ouverts — et, cas le plus sournois, des unites en
pouces.

Deux regles gouvernent ce module :

1. **On diagnostique AVANT de reparer, et on dit ce qu'on a change.** Une
   reparation silencieuse qui deplace une face de 0,3 mm produit une piece fausse
   sans que personne ne sache pourquoi.
2. **On ne repare pas ce qui n'est pas casse.** ``ShapeFix`` peut deteriorer une
   geometrie saine en recousant des aretes qui n'avaient rien demande.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.IFSelect import IFSelect_ReturnStatus
from OCP.Interface import Interface_Static
from OCP.ShapeAnalysis import ShapeAnalysis_ShapeTolerance
from OCP.ShapeFix import ShapeFix_Shape
from OCP.STEPControl import STEPControl_Reader
from OCP.TopoDS import TopoDS_Shape

from . import brep


@dataclass
class StepDiagnosis:
    """Ce qu'on sait du fichier AVANT de decider quoi que ce soit."""

    path: str
    valid: bool
    n_faces: int
    n_solids: int
    volume_mm3: float
    tol_min: float
    tol_max: float
    tol_avg: float
    declared_unit: str = "MM"
    bbox_size: tuple[float, float, float] = (0.0, 0.0, 0.0)

    #: Defauts GEOMETRIQUES : la forme est abimee, une reparation a un sens.
    geometry_issues: list[str] = field(default_factory=list)
    #: Alertes de PLAUSIBILITE : la forme est saine mais surprenante (taille,
    #: unites). Aucune reparation ne les corrigera — c'est a l'utilisateur de
    #: trancher. Les confondre ferait passer ShapeFix sur une piece intacte.
    plausibility_warnings: list[str] = field(default_factory=list)

    @property
    def warnings(self) -> list[str]:
        return self.geometry_issues + self.plausibility_warnings

    @property
    def needs_healing(self) -> bool:
        return bool(self.geometry_issues)

    @property
    def tolerance_spread(self) -> float:
        """Rapport entre la plus grande et la plus petite tolerance de la forme.

        Un rapport eleve signale une geometrie recousue a la main ou traduite
        d'un autre noyau. Ce n'est pas fatal, mais cela borne la precision
        atteignable : aucun solveur ne peut etre plus precis que la geometrie
        qu'on lui donne.
        """
        return self.tol_max / max(self.tol_min, 1e-12)

    def describe(self) -> str:
        lines = [
            f"STEP « {Path(self.path).name} » — "
            f"{'VALIDE' if self.valid else 'INVALIDE (topologie)'}",
            f"  {self.n_solids} solide(s), {self.n_faces} faces, "
            f"V = {self.volume_mm3:.1f} mm3",
            f"  encombrement : {np.round(self.bbox_size, 2)} mm",
            f"  tolerances   : {self.tol_min:.2e} .. {self.tol_max:.2e} mm "
            f"(moy. {self.tol_avg:.2e}, etendue x{self.tolerance_spread:.0f})",
        ]
        for w in self.geometry_issues:
            lines.append(f"  [DEFAUT]  {w}")
        for w in self.plausibility_warnings:
            lines.append(f"  [ALERTE]  {w}")
        return "\n".join(lines)


#: Encombrement (mm) au-dela duquel une piece est suspecte pour une machine maker.
#: Choisi large : une piece de 2 m n'est pas impossible, elle merite une question.
SUSPICIOUS_SIZE_MM = 2000.0

#: Sous cette taille, l'hypothese d'une confusion d'unites merite d'etre posee.
#: Une piece de 8 mm existe ; une piece de 8 mm dont les cotes valent des nombres
#: ronds divises par 25,4 est presque toujours un fichier en pouces lu en mm.
#: On pose la question, on ne tranche pas a la place de l'utilisateur.
SUSPICIOUS_SMALL_MM = 10.0


def diagnose_step(path: str | Path, *, shape: TopoDS_Shape | None = None) -> StepDiagnosis:
    """Analyse un STEP sans le modifier."""
    path = Path(path)
    unit = "MM"
    if shape is None:
        reader = STEPControl_Reader()
        Interface_Static.SetCVal_s("xstep.cascade.unit", "MM")
        if reader.ReadFile(str(path)) != IFSelect_ReturnStatus.IFSelect_RetDone:
            raise brep.StepLoadError(f"lecture STEP echouee : {path}")
        reader.TransferRoots()
        shape = reader.OneShape()
        unit = Interface_Static.CVal_s("xstep.cascade.unit") or "MM"

    analyzer = BRepCheck_Analyzer(shape)
    valid = bool(analyzer.IsValid())

    tol = ShapeAnalysis_ShapeTolerance()
    faces = brep.face_info(shape)
    bb = brep.bounding_box(shape)
    size = tuple(float(x) for x in bb.size)

    geom: list[str] = []
    plaus: list[str] = []
    n_solids = brep.count_solids(shape)

    if not valid:
        geom.append("topologie invalide : faces mal cousues ou aretes incoherentes")

    # Le test DECISIF pour notre usage, et il ne se lit pas dans BRepCheck.
    #
    # Un shell ouvert est topologiquement « valide » et OCCT lui calcule meme un
    # volume, par integration sur ses faces — on obtient donc un nombre juste
    # pour une forme qui n'a pas d'interieur. Ce qui trahit le defaut, c'est
    # l'absence de SOLIDE : sans solide, le lancer de rayons de la voxelisation
    # compte un nombre impair de traversees et le suivi de matiere devient faux.
    if n_solids == 0:
        geom.append(
            "aucun solide : la forme est un shell ouvert ou un ensemble de faces. "
            "Le volume affiche par OCCT n'a alors pas de sens, et le suivi de "
            "matiere ne peut pas fonctionner")

    tmin = float(tol.Tolerance(shape, -1))
    tmax = float(tol.Tolerance(shape, 1))
    tavg = float(tol.Tolerance(shape, 0))
    if tmax > 0.01:
        geom.append(
            f"tolerance maximale {tmax:.2e} mm : superieure au centieme, "
            "aucune conclusion de precision ne peut aller au-dela")
    if tmax / max(tmin, 1e-12) > 1e4:
        geom.append("tolerances tres heterogenes : geometrie probablement traduite")

    if max(size) > SUSPICIOUS_SIZE_MM:
        plaus.append(
            f"encombrement {max(size):.0f} mm : hors du volume d'une machine maker. "
            f"Verifier l'unite du fichier (x25,4 si lu en pouces par erreur)")
    if 0 < max(size) < SUSPICIOUS_SMALL_MM:
        plaus.append(
            f"encombrement {max(size):.2f} mm : le fichier etait peut-etre en "
            f"pouces et a ete lu en mm (x25,4 donnerait {max(size) * 25.4:.1f} mm)")

    volume = 0.0
    try:
        volume = brep.volume(shape)
    except Exception:
        geom.append("volume non calculable : la forme n'est pas un solide ferme")

    if volume < 0.0:
        geom.append("volume negatif : faces orientees a l'envers. "
                    "Les normales pointeraient dans la matiere")

    return StepDiagnosis(
        path=str(path), valid=valid, n_faces=len(faces),
        n_solids=n_solids, volume_mm3=volume,
        tol_min=tmin, tol_max=tmax, tol_avg=tavg, declared_unit=unit,
        bbox_size=size, geometry_issues=geom, plausibility_warnings=plaus,
    )


@dataclass
class HealingResult:
    """Ce que la reparation a change. Toujours compare a l'original."""

    shape: TopoDS_Shape
    applied: bool
    before: StepDiagnosis
    after: StepDiagnosis | None = None
    volume_change_mm3: float = 0.0
    reason: str = ""

    @property
    def volume_change_ratio(self) -> float:
        if self.before.volume_mm3 <= 0:
            return 0.0
        return abs(self.volume_change_mm3) / self.before.volume_mm3

    @property
    def resolved(self) -> bool:
        """La reparation a-t-elle REELLEMENT supprime les defauts ?

        Distinction indispensable : ``ShapeFix`` s'execute sans broncher sur une
        forme qu'il ne sait pas reparer. Un shell ouvert n'a pas de face
        manquante a inventer — l'outil rend la meme forme, et rapporter
        « reparation appliquee » laisserait croire le probleme regle. On compare
        donc l'etat AVANT et APRES, au lieu de faire confiance au fait que
        l'appel a abouti.
        """
        return self.after is not None and not self.after.needs_healing

    def describe(self) -> str:
        if not self.applied:
            return f"Reparation non appliquee : {self.reason}"
        head = (f"Reparation {'REUSSIE' if self.resolved else 'SANS EFFET'} : "
                f"volume {self.before.volume_mm3:.1f} -> {self.after.volume_mm3:.1f} mm3 "
                f"({self.volume_change_ratio * 100:+.4f} %)")
        if not self.resolved:
            head += (" — les defauts subsistent : "
                     + " ; ".join(self.after.geometry_issues))
        return head


def heal_shape(shape: TopoDS_Shape, diagnosis: StepDiagnosis,
               *, tolerance: float = 1e-3,
               max_volume_change_ratio: float = 0.001) -> HealingResult:
    """Repare une forme, mais seulement si elle en a besoin et sans la trahir.

    ``max_volume_change_ratio`` est un garde-fou : si ``ShapeFix`` modifie le
    volume de plus de cette fraction, la reparation est REFUSEE et la forme
    d'origine conservee. Un recousage qui deplace la matiere de plus d'un
    millieme n'est plus une reparation, c'est une modification de la piece — et
    ce n'est pas a un outil de la decider a la place du concepteur.
    """
    if not diagnosis.needs_healing:
        return HealingResult(
            shape=shape, applied=False, before=diagnosis,
            reason=("forme geometriquement saine — une alerte de plausibilite "
                    "(taille, unites) ne se repare pas, elle se tranche"
                    if diagnosis.plausibility_warnings else
                    "forme deja valide et sans defaut geometrique"))

    fixer = ShapeFix_Shape(shape)
    fixer.SetPrecision(tolerance)
    fixer.SetMaxTolerance(max(tolerance * 100.0, 1e-2))
    fixer.Perform()
    fixed = fixer.Shape()

    after = diagnose_step(diagnosis.path, shape=fixed)
    delta = after.volume_mm3 - diagnosis.volume_mm3

    if diagnosis.volume_mm3 > 0 and abs(delta) / diagnosis.volume_mm3 > max_volume_change_ratio:
        return HealingResult(
            shape=shape, applied=False, before=diagnosis, after=after,
            volume_change_mm3=delta,
            reason=(f"REFUSEE : la reparation change le volume de "
                    f"{abs(delta) / diagnosis.volume_mm3 * 100:.3f} % "
                    f"(seuil {max_volume_change_ratio * 100:.3f} %). "
                    "Ce n'est plus une reparation mais une modification de la piece."))

    return HealingResult(shape=fixed, applied=True, before=diagnosis, after=after,
                         volume_change_mm3=delta, reason="reparation appliquee")


def load_step_checked(path: str | Path, *, heal: bool = True
                      ) -> tuple[TopoDS_Shape, StepDiagnosis, HealingResult | None]:
    """Charge un STEP en diagnostiquant, et en reparant si c'est justifie.

    C'est le point d'entree a utiliser pour un fichier VENU DE L'EXTERIEUR.
    ``brep.load_step`` reste le chemin direct pour les fichiers dont on sait
    deja qu'ils sont sains — le corpus de tests, par exemple.
    """
    shape = brep.load_step(path)
    diag = diagnose_step(path, shape=shape)
    if not heal:
        return shape, diag, None
    result = heal_shape(shape, diag)
    return result.shape, diag, result


class UnusableShapeError(RuntimeError):
    """La forme ne permet pas de calculer une gamme, et aucune reparation n'y a suffi."""


def require_usable(shape: TopoDS_Shape, diagnosis: StepDiagnosis) -> None:
    """Refuse une forme sur laquelle le moteur produirait des resultats faux.

    Le cas qui impose ce garde-fou : un shell ouvert. Il est affichable, OCCT
    lui calcule meme un volume plausible par integration sur ses faces, et rien
    ne signale le probleme — jusqu'a la voxelisation, dont le lancer de rayons
    compte un nombre impair de traversees et remplit la matiere n'importe
    comment. Le moteur rendrait alors une gamme complete, coherente, et fausse.

    Mieux vaut refuser tot et nommer le defaut que produire un plan credible sur
    une geometrie qui n'a pas d'interieur.
    """
    if diagnosis.n_solids == 0:
        raise UnusableShapeError(
            f"« {Path(diagnosis.path).name} » ne contient aucun solide "
            f"({diagnosis.n_faces} faces libres). Le suivi de matiere et le "
            "tranchage produiraient des resultats faux sans le signaler. "
            "Refermer la geometrie dans le logiciel de CAO d'origine, puis "
            "re-exporter."
        )
    if diagnosis.volume_mm3 <= 0.0:
        raise UnusableShapeError(
            f"« {Path(diagnosis.path).name} » a un volume nul ou negatif "
            f"({diagnosis.volume_mm3:.3f} mm3) : faces probablement orientees "
            "a l'envers. Les normales pointeraient dans la matiere."
        )
