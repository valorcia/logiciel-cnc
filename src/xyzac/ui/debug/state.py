"""Etat du banc de debug. AUCUNE dependance Qt, AUCUN calcul geometrique.

Role exact de ce module : tenir ce que l'operateur a charge, appeler les modules
metier pour l'obtenir, et rendre des donnees pretes a afficher. Il ne calcule
rien lui-meme — c'est la regle d'architecture du banc (ADR-008 / D67), et elle
est verifiee par un test qui interdit a ce paquet d'importer un solveur de
calcul autrement que par ses entrees publiques.

Consequence de conception qui vient du conteneur sans ecran : l'etat et la
construction de scene sont **separes de la fenetre**. On peut donc charger un
STEP, construire la scene et produire une capture sans aucun affichage — ce qui
rend le banc testable, et fait marcher le bouton CAPTURE meme sur une machine
sans interface graphique.

Regle de non-invention : tout champ dont la valeur n'est pas reellement calculee
vaut ``None`` et s'affiche « non disponible ». Aucune valeur de remplacement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ...geometry_core import brep
from ...geometry_core.healing import load_step_checked, require_usable
from ...geometry_core.types import AABB
from ...kinematics_solver.solver import KinematicsSolver
from ...machine_model import MachineKinematics, default_xyzac_kit
from ...stock_engine import stock_from_part
from ...stock_engine.stock import Stock
from ...tool_model import build_endmill
from ...tool_model.assembly import ToolAssembly


@dataclass
class PartInfo:
    """Ce que le banc sait de la piece chargee. Rien d'invente."""

    path: Path
    n_solids: int
    n_faces: int
    volume_mm3: float | None
    bbox: AABB
    diagnosis: str = ""
    healing: str = ""

    @property
    def size(self) -> np.ndarray:
        return self.bbox.hi - self.bbox.lo

    def lines(self) -> list[tuple[str, str]]:
        sx, sy, sz = self.size
        vol = ("non disponible" if self.volume_mm3 is None
               else f"{self.volume_mm3:.1f} mm3")
        return [
            ("Fichier", self.path.name),
            ("Solides", str(self.n_solids)),
            ("Faces", str(self.n_faces)),
            ("Dimensions X/Y/Z", f"{sx:.2f} x {sy:.2f} x {sz:.2f} mm"),
            ("Volume", vol),
            ("Boite min", f"{self.bbox.lo[0]:.2f}, {self.bbox.lo[1]:.2f}, "
                          f"{self.bbox.lo[2]:.2f}"),
            ("Boite max", f"{self.bbox.hi[0]:.2f}, {self.bbox.hi[1]:.2f}, "
                          f"{self.bbox.hi[2]:.2f}"),
        ]


@dataclass
class AxisReadout:
    """Pose d'inspection : X, Y, Z, A, C, et d'ou ils viennent.

    ``source`` dit toujours si les valeurs sortent d'une trajectoire calculee ou
    d'une pose d'inspection choisie a la main. Confondre les deux ferait lire un
    resultat la ou il n'y a qu'un reglage de vue.
    """

    x_mm: float | None = None
    y_mm: float | None = None
    z_mm: float | None = None
    a_deg: float | None = None
    c_deg: float | None = None
    source: str = "aucune trajectoire chargee"
    within_limits: bool | None = None
    singular: bool | None = None

    @staticmethod
    def _fmt(v: float | None, unit: str) -> str:
        return "non disponible" if v is None else f"{v:+.3f} {unit}"

    def lines(self) -> list[tuple[str, str]]:
        def state(v: bool | None, ok: str, bad: str) -> str:
            return "non disponible" if v is None else (ok if v else bad)

        return [
            ("X", self._fmt(self.x_mm, "mm")),
            ("Y", self._fmt(self.y_mm, "mm")),
            ("Z", self._fmt(self.z_mm, "mm")),
            ("A", self._fmt(self.a_deg, "deg")),
            ("C", self._fmt(self.c_deg, "deg")),
            ("Courses", state(self.within_limits, "OK", "HORS COURSE")),
            ("Singularite", state(self.singular, "OUI", "non")),
            ("Origine des valeurs", self.source),
        ]


@dataclass
class BenchState:
    """Ce que l'operateur a charge, et ce que le banc peut en dire.

    Volontairement pauvre en V0 : piece, brut, outil, machine. Les champs des
    versions suivantes (trajectoires, matiere, orientations) ne sont pas
    pre-declares ici — un champ vide qui attend est indistinguable d'un champ
    casse.
    """

    machine: MachineKinematics = field(default_factory=default_xyzac_kit)
    part_shape: object | None = None
    part: PartInfo | None = None
    stock: Stock | None = None
    tool: ToolAssembly | None = None
    #: Pose a laquelle l'outil est DESSINE. Choisie, pas calculee.
    inspect_tcp: np.ndarray = field(default_factory=lambda: np.zeros(3))
    inspect_a_deg: float = 0.0
    inspect_c_deg: float = 0.0

    #: Position de l'origine PIECE dans le repere du plateau C, en mm.
    #:
    #: Valeur DECLAREE, affichee dans le panneau, et non mesuree. Elle est
    #: indispensable a la justesse de l'image : la piece vit dans le repere
    #: piece, les organes machine dans le repere machine, et les dessiner dans
    #: la meme vue sans transport produit une image fausse — plateau traversant
    #: le brut, axes passant a cote des pivots reels. Laisser (0, 0, 0)
    #: encastrerait la piece dans le plateau (voir ``Setup.part_to_table_mm``).
    mount_offset_mm: list[float] = field(default_factory=lambda: [0.0, 0.0, 25.0])
    messages: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ chargement

    def load_step(self, path: str | Path, *, auto_stock: bool = True) -> PartInfo:
        """Charge un STEP par l'importeur CONTROLE du moteur.

        On passe par ``healing.load_step_checked`` et non par ``brep.load_step`` :
        c'est lui qui separe un defaut geometrique d'une invraisemblance de cote,
        qui refuse une reparation deplacant la matiere, et qui leve sur une forme
        inutilisable. Un banc de debug qui contournerait ce chemin ne montrerait
        pas ce que le moteur voit.
        """
        p = Path(path)
        shape, diag, heal = load_step_checked(p)
        require_usable(shape, heal.after or diag)

        bb = brep.bounding_box(shape)
        try:
            vol = float(brep.volume(shape))
        except Exception:                       # noqa: BLE001
            vol = None                          # non disponible, pas zero

        info = PartInfo(
            path=p, n_solids=int(diag.n_solids), n_faces=int(diag.n_faces),
            volume_mm3=vol, bbox=bb,
            diagnosis=diag.describe(), healing=heal.describe(),
        )
        self.part_shape = shape
        self.part = info
        self.messages = []
        if heal.describe():
            self.messages.append(f"Import : {heal.describe()}")

        if auto_stock:
            self.stock = stock_from_part(bb, margin_xy=2.0, margin_z_top=2.0,
                                         margin_z_bottom=2.0)
        # Pose d'inspection par defaut : au-dessus du centre de la piece, ce qui
        # montre l'outil entier sans le faire traverser la matiere.
        self.inspect_tcp = np.array([bb.center[0], bb.center[1], bb.hi[2]])
        return info

    def set_default_tool(self) -> ToolAssembly:
        """Outil de demonstration : fraise 2 tailles complete avec porte-outil.

        « Complete » est le mot qui compte : le differenciateur du projet est de
        modeliser bec, goujure, col, tige, porte-outil et nez de broche, donc le
        banc doit les montrer tous — c'est precisement ce qu'on vient verifier.
        """
        self.tool = build_endmill("EM6", diameter=6.0, flute_length=20.0,
                                  stickout=45.0, holder_type="ER16")
        return self.tool

    # ------------------------------------------------------------------ lectures

    @property
    def mount_offset(self) -> np.ndarray:
        return np.asarray(self.mount_offset_mm, dtype=np.float64)

    def machine_tcp(self) -> np.ndarray:
        """TCP de la pose d'inspection, exprime en repere MACHINE.

        C'est la position ou l'outil se dessine : la broche vit dans le repere
        machine et son axe y vaut invariablement +Z. Le transport passe par le
        ``KinematicsSolver``, donc par la meme chaine que les collisions.
        """
        ks = KinematicsSolver(self.machine)
        return ks.part_to_machine_point(
            np.asarray(self.inspect_tcp, dtype=np.float64) + self.mount_offset,
            float(self.inspect_a_deg), float(self.inspect_c_deg))

    def axis_readout(self) -> AxisReadout:
        """X/Y/Z/A/C de la pose d'inspection, par la cinematique du moteur.

        Ce sont de vraies valeurs — le transport piece -> machine est celui du
        ``KinematicsSolver`` — mais d'une pose CHOISIE. ``source`` le dit, parce
        qu'aucune trajectoire n'est calculee en V0.
        """
        if self.part is None:
            return AxisReadout(source="aucune piece chargee")

        a, c = float(self.inspect_a_deg), float(self.inspect_c_deg)
        p = self.machine_tcp()
        return AxisReadout(
            x_mm=float(p[0]), y_mm=float(p[1]), z_mm=float(p[2]),
            a_deg=a, c_deg=c,
            source="pose d'inspection (aucune trajectoire calculee en V0)",
            within_limits=bool(self.machine.within_limits(a, c)
                               and self.machine.x.contains(p[0])
                               and self.machine.y.contains(p[1])
                               and self.machine.z.contains(p[2])),
            singular=bool(self.machine.is_singular(a)),
        )

    def machine_lines(self) -> list[tuple[str, str]]:
        """Panneau machine. ``SIMULATION`` est une constante, pas un etat.

        Aucun bouton du banc ne peut deplacer une machine : ``linuxcnc_gateway``
        est verrouille et ce module ne l'importe meme pas.
        """
        m = self.machine
        return [
            ("Machine", "SIMULATION — aucune liaison materielle"),
            ("Modele", m.machine_id),
            ("Course X", f"[{m.x.min_mm:.0f}, {m.x.max_mm:.0f}] mm"),
            ("Course Y", f"[{m.y.min_mm:.0f}, {m.y.max_mm:.0f}] mm"),
            ("Course Z", f"[{m.z.min_mm:.0f}, {m.z.max_mm:.0f}] mm"),
            ("Course A", f"[{m.a.min_deg:.0f}, {m.a.max_deg:.0f}] deg"),
            ("Course C", "continu" if m.c.continuous
                         else f"[{m.c.min_deg:.0f}, {m.c.max_deg:.0f}] deg"),
            ("Mode C", m.c_mode.value),
            ("Geometrie", "NON MESUREE (voir assembly_calibration)"),
            ("Cales sous piece", f"{self.mount_offset_mm[2]:.1f} mm (valeur declaree)"),
            ("Simulation", "NON LANCEE"),
        ]

    def tool_lines(self) -> list[tuple[str, str]]:
        if self.tool is None:
            return [("Outil", "aucun")]
        t = self.tool
        return [
            ("Outil", t.tool_id),
            ("Description", t.description or "non renseignee"),
            ("Diametre", f"{t.diameter:.2f} mm"),
            ("Rayon de bec", f"{t.corner_radius:.2f} mm"),
            ("Jauge", f"{t.gauge_length:.2f} mm"),
            ("Troncons", str(len(t.segments))),
            ("Avance", "non disponible (recipe_profiles non implemente)"),
            ("Vitesse broche", "non disponible (recipe_profiles non implemente)"),
        ]

    def stock_lines(self) -> list[tuple[str, str]]:
        if self.stock is None:
            return [("Brut", "aucun")]
        s = self.stock
        if s.lo is None or s.hi is None:
            return [("Brut", f"{s.kind.value} (cotes non disponibles)")]
        lo, hi = np.asarray(s.lo, float), np.asarray(s.hi, float)
        d = hi - lo
        return [
            ("Brut", s.kind.value),
            ("Matiere", s.material),
            ("Dimensions", f"{d[0]:.2f} x {d[1]:.2f} x {d[2]:.2f} mm"),
            ("Volume brut", f"{float(np.prod(d)):.1f} mm3"),
        ]
