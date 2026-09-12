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
from ...tool_model import build_ballnose, build_endmill
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
    tool_kind: str = "ballnose"
    #: Gamme calculee, si elle l'a ete. ``None`` = pas calculee, ce qui n'est
    #: pas la meme chose qu'une gamme vide.
    plan: object | None = None
    plan_report: object | None = None
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
    #: Valeur par defaut REMPLACEE au chargement de la piece, par
    #: ``suggested_mount``. Un montage fixe est un piege : (0, 0, 25) place la
    #: piece a cheval sur le bord du plateau des qu'elle n'est pas centree sur
    #: son propre repere, et la moitie de ses faces deviennent « inaccessibles »
    #: pour une raison qui n'a rien de geometrique. Mesure sur le dome C10 :
    #: deux des quatre parois verticales etaient declarees inatteignables a
    #: (0, 0, 25) et le sont toutes accessibles, avec 35 a 38 orientations
    #: admissibles, une fois la piece centree et rehaussee.
    mount_offset_mm: list[float] = field(default_factory=lambda: [0.0, 0.0, 25.0])
    messages: list[str] = field(default_factory=list)
    #: Champ d'obstacles mis en cache : son echantillonnage coute plusieurs
    #: dizaines de milliers de points et ne depend que du montage.
    _obstacles: object | None = field(default=None, repr=False)

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
        self._obstacles = None      # la scene change : le cache est perime
        self.plan = None            # et la gamme precedente ne s'y applique plus
        self.plan_report = None
        if heal.describe():
            self.messages.append(f"Import : {heal.describe()}")

        if auto_stock:
            self.stock = stock_from_part(bb, margin_xy=2.0, margin_z_top=2.0,
                                         margin_z_bottom=2.0)
        # Montage DERIVE de la piece, et non laisse a une valeur fixe. Voir
        # ``suggested_mount`` : un montage fixe fait declarer inaccessibles des
        # faces qui ne le sont pas.
        self.mount_offset_mm = list(self.suggested_mount(bb))
        self.messages.append(
            f"Montage propose : piece centree sur l'axe C, rehaussee de "
            f"{self.mount_offset_mm[2]:.0f} mm. Valeur DECLAREE, a verifier "
            f"contre le montage reel.")
        # Pose d'inspection par defaut : au-dessus du centre de la piece, ce qui
        # montre l'outil entier sans le faire traverser la matiere.
        self.inspect_tcp = np.array([bb.center[0], bb.center[1], bb.hi[2]])
        return info

    @staticmethod
    def suggested_mount(bb, *, riser_mm: float = 25.0) -> tuple[float, float, float]:
        """Montage PROPOSE : piece centree sur l'axe C, posee sur un rehausseur.

        Ce n'est pas un detail d'affichage. Sur une machine table/table, une
        piece decentree de d tourne a d du centre du plateau : ses faces
        eloignees sortent des courses ou balaient le berceau, et le solveur les
        declare inaccessibles a bon droit — pour une raison qui n'est pas celle
        de la piece.

        Mesure sur le dome C10 (60 x 60 mm, repere au coin) : a (0, 0, 25),
        deux des quatre parois verticales sont declarees inatteignables et deux
        accessibles — une asymetrie qui n'a aucune cause geometrique, seulement
        celle du decentrage. Centree et rehaussee de 60 mm, les quatre parois
        offrent 35 a 38 orientations admissibles.

        Le rehausseur est une HYPOTHESE de montage, affichee comme telle : le
        banc ne connait pas le montage reel de l'utilisateur. Ce qu'il ne doit
        pas faire, c'est en choisir un mauvais en silence.

        **Pourquoi 25 mm.** Valeur choisie par mesure, et le critere n'est pas
        « le plus de degagement possible » mais « n'introduire aucune limite
        nouvelle ». Sur le dome C10, verdict des quatre parois verticales et
        cause du blocage sur le dome lui-meme :

            rehausseur 10 mm : 2 parois inatteignables (plateau), 2 a 99,6 %
            rehausseur 25 mm : 4 parois 3+2, degagement 12,7 a 14,1 mm
            rehausseur 40 mm : 4 parois 3+2, degagement 14,4 a 16,8 mm
            rehausseur 60 mm : 4 parois 3+2, mais le dome bute en COURSE

        A 60 mm la course lineaire se met a buter et MASQUE la vraie cause du
        rejet sur le dome, qui est COLLISION_CUTTING — l'arete de coupe ne
        rentre pas dans le rayon local, et aucun montage n'y changera rien.
        Monter plus haut achete du degagement au prix d'un diagnostic faux.
        """
        cx = -0.5 * float(bb.lo[0] + bb.hi[0])
        cy = -0.5 * float(bb.lo[1] + bb.hi[1])
        # Le rehausseur porte le DESSOUS de la piece, pas son origine.
        cz = riser_mm - float(bb.lo[2])
        return (cx, cy, cz)

    def set_default_tool(self, kind: str = "ballnose", *, diameter: float = 6.0,
                         stickout: float = 45.0,
                         holder: str = "ER16") -> ToolAssembly:
        """Outil du banc, complet avec porte-outil et nez de broche.

        « Complet » est le mot qui compte : le differenciateur du projet est de
        modeliser bec, goujure, col, tige, porte-outil et nez de broche, donc le
        banc doit les montrer tous.

        **Hemispherique par defaut, et ce n'est pas un detail d'agrement.**
        Mesure sur la face superieure du bloc C01 : une fraise a bout DROIT y a
        2 orientations admissibles, une hemispherique en a 106 — un facteur 53.
        Ce n'est pas un defaut du moteur mais une physique connue depuis M1 :
        sur une face plane, une fraise a bout droit ne peut ni travailler
        verticale (singularite) ni inclinee (son talon enfonce la matiere). Un
        banc qui ouvrirait sur cet outil ferait conclure a l'operateur que tout
        est inaccessible, alors que le calcul est juste.

        ``kind`` vaut ``"ballnose"`` ou ``"endmill"`` : les deux sont utiles, et
        comparer l'un a l'autre est justement une des choses que ce banc sert a
        faire.
        """
        if kind == "endmill":
            self.tool = build_endmill("EM6", diameter=diameter, flute_length=20.0,
                                      stickout=stickout, holder_type=holder)
        elif kind == "ballnose":
            self.tool = build_ballnose("BN6", diameter=diameter, flute_length=20.0,
                                       stickout=stickout, holder_type=holder)
        else:
            raise ValueError(f"type d'outil inconnu : {kind!r} "
                             "(attendu 'ballnose' ou 'endmill')")
        self.tool_kind = kind
        self._obstacles = None          # la scene change avec l'outil
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

    # ------------------------------------------------------- accessibilite

    def build_setup(self):
        """Montage minimal, pour que le solveur dispose d'une scene.

        Le banc ne connait pas de bridage en V1 : le montage ne porte que la
        machine, la piece, le brut et l'outil. C'est une hypothese ASSUMEE, et
        elle est optimiste — un bridage reel retire des orientations. Le panneau
        d'accessibilite le dit, pour qu'un resultat favorable ne soit pas lu
        comme un feu vert.
        """
        from ...machine_model import Setup

        if self.part is None:
            raise RuntimeError("aucune piece chargee")
        if self.tool is None:
            self.set_default_tool()
        return Setup(
            setup_id=f"banc-{self.part.path.stem}", machine=self.machine,
            part_step_path=str(self.part.path), stock=self.stock,
            tools=[self.tool],
            part_to_table_mm=list(self.mount_offset_mm),
        )

    def obstacle_field(self, *, material: str = "finished"):
        """Champ d'obstacles de la scene, mis en cache.

        Son calcul echantillonne piece, brut et organes machine : quelques
        dizaines de milliers de points. Le refaire a chaque analyse doublerait
        le temps percu pour un resultat identique.
        """
        if self._obstacles is None:
            from ...simulation_engine.scene import build_scene as build_sim_scene

            self._obstacles = build_sim_scene(
                self.build_setup(), material_state=material).obstacles
        return self._obstacles

    def analyse_face(self, face_index: int, *, max_points: int = 12,
                     spacing: float = 2.0, subdivisions: int = 3,
                     max_lead_deg: float = 45.0, reject_singular: bool = False,
                     point_choice: str = "median"):
        """Analyse l'accessibilite d'une face. Appelle le SOLVEUR, ne calcule rien.

        ``max_points`` borne le coût : une resolution complete coûte de l'ordre
        de 70 ms par point de contact (mesure du jalon M6), donc une face de
        mille points prendrait plus d'une minute. Le resultat annonce toujours
        combien de points il a reellement traites sur combien la face en
        contient — un echantillon qui se presenterait comme la face entiere
        serait un mensonge par omission.

        ``reject_singular=False`` par defaut, contrairement au solveur. Le banc
        repond a « cette face est-elle ATTEIGNABLE », pas a « peut-on s'y
        deplacer en continu ». Or la singularite A -> 0 est un probleme de
        MOUVEMENT et non de position (ADR-003) : en indexation 3+2 l'axe C est
        bloque et A = 0 est parfaitement utilisable. La rejeter ferait declarer
        inatteignable une face que trois axes suffisent a usiner. Effet mesure
        sur la face superieure de C01 avec un bec hemispherique : 106
        orientations admissibles en la rejetant, 118 en la permettant.

        ``point_choice`` designe le point dont les orientations sont detaillees :
        ``"median"`` prend celui de rang median en nombre d'admissibles, donc
        representatif ; ``"worst"`` le plus contraint, ce qui est souvent le plus
        instructif ; ``"first"`` le premier, utile pour comparer deux executions.
        """
        import time

        from ...accessibility_solver.solver import (
            REMEDY,
            AccessibilityConfig,
            AccessibilitySolver,
        )
        from . import palette

        if self.part_shape is None:
            raise RuntimeError("aucune piece chargee")

        samp = brep.sample_face(self.part_shape, face_index, spacing=spacing)
        n_face = len(samp.points)
        if n_face == 0:
            raise RuntimeError(f"face {face_index} sans point echantillonne")

        take = min(int(max_points), n_face)
        # Prefixe contigu et non echantillonnage reparti : un ``linspace``
        # detruirait le voisinage des points, defaut mesure au jalon M4.
        pts, nrm = samp.points[:take], samp.normals[:take]

        cfg = AccessibilityConfig(subdivisions=subdivisions,
                                  max_lead_deg=max_lead_deg, cutting_depth=0.0,
                                  reject_singular=reject_singular)
        solver = AccessibilitySolver(self.tool or self.set_default_tool(),
                                     self.machine, self.obstacle_field(), cfg,
                                     mount_offset_mm=self.mount_offset)

        t0 = time.perf_counter()
        maps = solver.solve_points(pts, nrm)
        elapsed = time.perf_counter() - t0

        n_ok_points = sum(1 for m in maps if m.accessible)
        if point_choice == "worst":
            k = int(np.argmin([m.n_feasible for m in maps]))
        elif point_choice == "first":
            k = 0
        else:
            order = np.argsort([m.n_feasible for m in maps])
            k = int(order[len(order) // 2])
        chosen = maps[k]

        infos = {f.index: f for f in brep.face_info(self.part_shape)}
        stype = infos[face_index].surface_type if face_index in infos else "?"

        cands: list[OrientationCandidate] = []
        counts: dict[str, int] = {}
        for i in range(len(chosen.directions)):
            name = self._reason_name(int(chosen.reason[i]))
            fam = palette.reason_family(name)
            counts[fam] = counts.get(fam, 0) + 1
            cands.append(OrientationCandidate(
                index=i, direction=np.asarray(chosen.directions[i], dtype=float),
                a_deg=float(chosen.a_deg[i]), c_deg=float(chosen.c_deg[i]),
                feasible=bool(chosen.feasible[i]),
                margin_mm=float(chosen.margin[i]),
                reason_name=name,
                remedy=REMEDY.get(int(chosen.reason[i]), ""),
            ))

        # TCP machine, seulement pour les orientations admissibles : les autres
        # n'ont pas de pose realisable, et en afficher une serait inventer.
        from ...accessibility_solver.solver import tcp_from_contact
        from ...kinematics_solver.solver import KinematicsSolver

        ks = KinematicsSolver(self.machine)
        for cnd in cands:
            if not cnd.feasible:
                continue
            tcp = tcp_from_contact(chosen.point, chosen.normal, cnd.direction,
                                   self.tool)
            cnd.tcp_machine = ks.part_to_machine_point(
                np.asarray(tcp) + self.mount_offset, cnd.a_deg, cnd.c_deg)

        return AccessibilityResult(
            face_index=int(face_index), surface_type=stype,
            n_points_face=n_face, n_points_solved=take,
            point=np.asarray(chosen.point, dtype=float),
            normal=np.asarray(chosen.normal, dtype=float),
            candidates=cands, counts=counts,
            per_point_accessible=n_ok_points,
            stage_counts=dict(chosen.stage_counts), elapsed_s=elapsed,
            hypotheses={
                "outil": f"{self.tool.tool_id} ({self.tool_kind})",
                "jauge": f"{self.tool.gauge_length:.1f} mm",
                "lead maximal": f"{max_lead_deg:.0f} deg",
                "grille de directions": f"{subdivisions} subdivisions",
                "singularite A=0": "rejetee" if reject_singular else "permise",
                "bridage": "AUCUN pris en compte — resultat OPTIMISTE",
                "cales sous piece": f"{self.mount_offset_mm[2]:.1f} mm",
            },
        )

    def collision_matrix(self, direction: np.ndarray | None = None,
                         tcp_part: np.ndarray | None = None
                         ) -> list[tuple[str, str, str]]:
        """Detail des collisions, par ROLE de troncon et classe d'obstacle.

        Rend des lignes ``(troncon, obstacle, verdict)``. C'est le panneau du
        point 8 du cahier des charges : savoir non pas « ca touche » mais
        **quoi touche quoi**, parce que le remede en depend entierement — une
        tige qui touche demande une jauge plus longue, un nez de broche qui
        touche demande souvent de renoncer.

        Trois choses que ce tableau ne fait PAS, et chacune corrige un defaut
        de sa premiere version :

        1. il n'affiche **pas de marge par ligne**. ``CollisionReport.min_margin``
           est un minimum GLOBAL sur tous les troncons : le reporter ligne par
           ligne attribuait a la tige un nombre appartenant a l'arete, et
           affichait « degage, -2,335 mm » — un verdict et une valeur qui se
           contredisent. La marge globale figure sur une ligne de synthese, une
           seule fois, avec le troncon auquel elle appartient.
        2. il **agrege par role** et non par troncon. Un bec hemispherique
           compte huit troncons de role ``cutting`` ; les lister huit fois
           repetait la meme information.
        3. il interroge le **garde machine** pour les organes machine, qui ne
           sont pas dans le champ d'obstacles. Sans cela la ligne MACHINE
           annoncait « aucun obstacle », alors que c'est la cause de rejet la
           plus fréquente sur ce corpus.

        Et il emploie la **meme tolerance d'arete** que le solveur
        (``cutting_allowance``, deduite de l'inflation du champ sur la classe
        PART). Sans elle le panneau signalait « arete / PART : 804 points en
        violation » sur des orientations que le solveur declare admissibles :
        un panneau de debug qui contredit le moteur est pire que pas de panneau.
        """
        from ...collision_engine.field import PENETRATION_ALLOWED, ObstacleClass, ObstacleField
        from ...collision_engine.machine_guard import MachineGuard
        from ...collision_engine.tool_collision import ToolCollisionChecker
        from ...kinematics_solver.solver import KinematicsSolver

        if self.tool is None:
            self.set_default_tool()
        field_ = self.obstacle_field()
        d = (np.asarray(direction, dtype=float) if direction is not None
             else self.machine.tool_axis_in_part(self.inspect_a_deg,
                                                 self.inspect_c_deg))
        tcp = (np.asarray(tcp_part, dtype=float) if tcp_part is not None
               else np.asarray(self.inspect_tcp, dtype=float))

        roles = []
        for seg in self.tool.segments:
            if seg.role not in roles:
                roles.append(seg.role)

        checker = ToolCollisionChecker(self.tool)
        # Meme tolerance d'arete que ``AccessibilitySolver`` : le maximum de
        # l'inflation sur les points de classe PART.
        is_part = field_.classes == int(ObstacleClass.PART)
        cut_allow = (float(field_.inflation[is_part].max()) if is_part.any() else 0.0)

        rows: list[tuple[str, str, str]] = []
        for cls in (ObstacleClass.PART, ObstacleClass.STOCK, ObstacleClass.FIXTURE):
            m = field_.classes == int(cls)
            if not np.any(m):
                rows.append(("—", cls.name, "aucun obstacle de cette classe"))
                continue
            sub = ObstacleField(field_.points[m], field_.classes[m],
                                field_.inflation[m])
            rep = checker.check(tcp, d, sub, cutting_depth=0.0,
                                cutting_allowance=cut_allow)
            for role in roles:
                if PENETRATION_ALLOWED.get((role, cls), False):
                    rows.append((role.value, cls.name,
                                 "penetration toleree (contact voulu)"))
                    continue
                n = int(rep.violations_by_role.get(role, 0))
                rows.append((role.value, cls.name,
                             f"COLLISION — {n} points en violation" if n else "degage"))
            worst = rep.worst_role.value if rep.worst_role else "—"
            rows.append(("(synthese)", cls.name,
                         f"marge minimale {rep.min_margin:+.3f} mm, "
                         f"troncon le plus proche : {worst}"))

        # --- organes machine : ils ne sont pas dans le champ d'obstacles
        guard = MachineGuard(self.machine, self.tool)
        ks = KinematicsSolver(self.machine)
        tcp_m = ks.part_to_machine_point(tcp + self.mount_offset,
                                         self.inspect_a_deg, self.inspect_c_deg)
        chk = guard.check_pose(tcp_m, self.inspect_a_deg, self.inspect_c_deg)
        rows.append(("outil complet", "MACHINE", chk.reason()))
        if not chk.axis_limits_ok:
            rows.append(("(synthese)", "MACHINE", f"hors course : {chk.detail}"))
        return rows

    def plan_roughing_preview(self, *, layer_thickness: float = 3.0,
                              max_setups: int = 1, pitch: float = 2.0,
                              point_spacing: float = 2.0):
        """Calcule une gamme d'ebauche et rend ``(plan, rapport)``.

        Appelle ``strategy_planner.plan_roughing`` : aucun calcul ici. Le
        resultat sert a AFFICHER la trajectoire — c'est la seule facon de voir
        ce que le post-processeur va ecrire, et sans cela un G-code emis n'est
        inspectable qu'en le lisant ligne par ligne.

        **Coûteux** : tranchage, simulation d'enlevement de matiere et
        validation par couche. Quelques secondes a quelques dizaines de
        secondes selon la piece et le pas de voxel. ``pitch`` est le levier
        principal : le doubler divise le temps par huit et rend la matiere plus
        grossiere.
        """
        from ...stock_engine.material import MaterialState
        from ...strategy_planner.planner import plan_roughing

        if self.part_shape is None:
            raise RuntimeError("aucune piece chargee")
        if self.tool is None:
            self.set_default_tool()

        verts, tris, _ = brep.tessellate(self.part_shape, deflection=pitch * 0.25)
        material = MaterialState.from_setup(self.stock, verts, tris, pitch=pitch)
        plan, report = plan_roughing(
            self.part_shape, self.build_setup(), material, self.tool,
            max_setups=max_setups, layer_thickness=layer_thickness,
            point_spacing=point_spacing)
        self.plan = plan
        self.plan_report = report
        return plan, report

    def operation_path(self, index: int = 0):
        """``(points, is_rapid)`` d'une operation de la gamme calculee.

        Rend ``None`` si aucune gamme n'a ete calculee — et non un tableau vide,
        qui se confondrait avec une gamme sans mouvement.
        """
        if self.plan is None or not self.plan.operations:
            return None
        op = self.plan.operations[min(index, len(self.plan.operations) - 1)]
        return np.asarray(op.toolpath.points, dtype=float), op.toolpath.is_rapid

    def plan_lines(self) -> list[tuple[str, str]]:
        if self.plan is None:
            return [("Gamme", "non calculee")]
        rows = [("Gamme", self.plan.plan_id),
                ("Operations", str(len(self.plan.operations)))]
        for op in self.plan.operations:
            P = np.asarray(op.toolpath.points, dtype=float)
            R = op.toolpath.is_rapid
            n_rap = "non disponible" if R is None else str(int(np.sum(R)))
            rows.append((op.op_id, f"{len(P)} points, dont {n_rap} rapides"))
            if op.notes:
                rows.append(("", op.notes))
        if self.plan_report is not None:
            rows.append(("Volume enleve",
                         f"{sum(self.plan_report.removed_per_step):.0f} mm3"))
            rows.append(("Voxels gouges", str(self.plan_report.gouged_voxels)))
        return rows

    def set_inspect_from_candidate(self, result, candidate) -> None:
        """Place l'outil A l'orientation interrogee.

        C'est le geste le plus informatif du banc : on ne regarde plus une
        fleche, on voit la pose reelle — et donc pourquoi le porte-outil passe
        ou pourquoi il touche. Le TCP vient de ``tcp_from_contact``, la meme
        fonction que le solveur emploie, de sorte que la pose affichee est
        exactement celle qu'il a evaluee.
        """
        from ...accessibility_solver.solver import tcp_from_contact

        if self.tool is None:
            self.set_default_tool()
        self.inspect_tcp = np.asarray(
            tcp_from_contact(result.point, result.normal,
                             np.asarray(candidate.direction, dtype=float), self.tool),
            dtype=np.float64)
        self.inspect_a_deg = float(candidate.a_deg)
        self.inspect_c_deg = float(candidate.c_deg)

    @staticmethod
    def _reason_name(value: int) -> str:
        from ...accessibility_solver.solver import RejectReason

        try:
            return RejectReason(value).name
        except ValueError:
            return f"INCONNU_{value}"

    def face_list(self) -> list[tuple[int, str, float]]:
        """(index, type de surface, aire) de chaque face, aire decroissante.

        L'aire sert a trier : sur une piece du corpus, les faces qui comptent
        sont les grandes, et une liste dans l'ordre topologique les noie.
        """
        if self.part_shape is None:
            return []
        infos = brep.face_info(self.part_shape)
        rows = [(f.index, f.surface_type, float(f.area)) for f in infos]
        return sorted(rows, key=lambda r: -r[2])

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


# ---------------------------------------------------------------------------
# Accessibilite : le differenciateur du projet, rendu lisible
# ---------------------------------------------------------------------------


@dataclass
class OrientationCandidate:
    """Une direction candidate, avec tout ce qui decide de son sort.

    Reprend tel quel ce que ``AccessibilityMap`` contient — rien n'est recalcule
    ici. La seule valeur ajoutee est la mise en forme : nom du motif, remede, et
    position machine, pour que l'operateur n'ait pas a les deduire.
    """

    index: int
    direction: np.ndarray
    a_deg: float
    c_deg: float
    feasible: bool
    margin_mm: float
    reason_name: str
    remedy: str
    tcp_machine: np.ndarray | None = None

    @property
    def family(self) -> str:
        from . import palette

        return palette.reason_family(self.reason_name)

    def lines(self) -> list[tuple[str, str]]:
        """Detail d'une orientation, tel que le panneau l'affiche."""
        m = ("non disponible" if not np.isfinite(self.margin_mm)
             else f"{self.margin_mm:+.3f} mm")
        t = self.tcp_machine
        rows = [
            ("Statut", "ADMISSIBLE" if self.feasible else f"REJETEE — {self.reason_name}"),
            ("A", f"{self.a_deg:+.3f} deg"),
            ("C", f"{self.c_deg:+.3f} deg"),
            ("X", "non disponible" if t is None else f"{t[0]:+.3f} mm"),
            ("Y", "non disponible" if t is None else f"{t[1]:+.3f} mm"),
            ("Z", "non disponible" if t is None else f"{t[2]:+.3f} mm"),
            ("Direction d'outil", f"{self.direction[0]:+.4f}, "
                                  f"{self.direction[1]:+.4f}, {self.direction[2]:+.4f}"),
            ("Marge minimale", m),
        ]
        if self.feasible:
            # La « marge » est une distance signee au plus proche obstacle
            # interdit. Un rejet non geometrique (butee, singularite) n'en a pas,
            # d'ou le -inf, affiche « non disponible » plutot que -1e308.
            rows.append(("Remede", "sans objet"))
        else:
            rows.append(("Remede", self.remedy or "aucun remede enregistre"))
        return rows


@dataclass
class AccessibilityResult:
    """Resultat d'une analyse d'accessibilite sur une face.

    Deux granularites, parce que les deux questions sont differentes :

      - ``candidates`` decrit UN point de contact en detail. C'est ce que les
        fleches 3D montrent, et ce qu'on interroge orientation par orientation.
      - ``counts`` agrege sur tous les points echantillonnes de la face. C'est
        ce qui repond a « cette surface est-elle usinable ».

    Confondre les deux ferait conclure d'un point sur toute une face — l'erreur
    exacte que le rapport de finition du moteur signale depuis M4 en distinguant
    l'etalement du segment de celui de la passe.
    """

    face_index: int
    surface_type: str
    n_points_face: int
    n_points_solved: int
    point: np.ndarray
    normal: np.ndarray
    candidates: list[OrientationCandidate] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    per_point_accessible: int = 0
    stage_counts: dict[str, int] = field(default_factory=dict)
    elapsed_s: float = 0.0
    #: Reglages qui ont produit ces chiffres.
    #:
    #: Un nombre d'orientations admissibles ne veut rien dire sans eux : le
    #: meme point passe de 2 a 118 orientations selon l'outil et le traitement
    #: de la singularite. Les taire rendrait le panneau trompeur.
    hypotheses: dict[str, str] = field(default_factory=dict)

    @property
    def n_feasible(self) -> int:
        return sum(1 for c in self.candidates if c.feasible)

    def summary_lines(self) -> list[tuple[str, str]]:
        cov = (f"{self.n_points_solved} sur {self.n_points_face} points de la face"
               if self.n_points_solved < self.n_points_face
               else f"{self.n_points_solved} points (face entiere)")
        rows = [
            ("Face", f"{self.face_index} ({self.surface_type})"),
            ("Points analyses", cov),
            ("Points accessibles", f"{self.per_point_accessible} / {self.n_points_solved}"),
            ("Duree", f"{self.elapsed_s:.2f} s"),
            ("", ""),
            ("— au point affiche —", f"{len(self.candidates)} orientations evaluees"),
            ("Admissibles", str(self.counts.get("admissible", 0))),
        ]
        for fam in ("collision outil", "collision machine", "cinematique",
                    "singularite", "geometrie"):
            rows.append((f"Rejetees — {fam}", str(self.counts.get(fam, 0))))
        if self.hypotheses:
            rows.append(("", ""))
            rows.append(("— hypotheses —", ""))
            rows.extend(self.hypotheses.items())
        return rows

    def verdict(self) -> str:
        """Phrase que l'operateur lit en premier."""
        if self.n_feasible == 0:
            worst = max((f for f in self.counts if f != "admissible"),
                        key=lambda f: self.counts[f], default="inconnu")
            return (f"Face {self.face_index} INACCESSIBLE au point analyse — "
                    f"cause dominante : {worst}")
        if self.per_point_accessible < self.n_points_solved:
            return (f"Face {self.face_index} partiellement accessible : "
                    f"{self.per_point_accessible}/{self.n_points_solved} points")
        return (f"Face {self.face_index} accessible — {self.n_feasible} "
                f"orientations admissibles au point analyse")
