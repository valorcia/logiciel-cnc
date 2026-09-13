"""Construction de la scene 3D. PyVista uniquement, AUCUNE dependance Qt.

Separation voulue, et imposee par le materiel : la scene se construit et se rend
sans fenetre. Trois consequences utiles :

  - le banc est **testable** sans ecran — on charge un STEP, on construit les
    calques, on produit une capture, et on verifie le resultat ;
  - le bouton CAPTURE fonctionne sur une machine sans interface graphique, par
    exemple le Raspberry Pi de la machine, en SSH ;
  - la fenetre Qt n'est plus qu'une coquille, donc un probleme d'affichage ne
    peut pas casser la visualisation.

Ce module ne calcule aucune geometrie metier. Il traduit : maillage OCCT ->
maillage PyVista, troncons d'outil -> cones tronques, courses machine -> boite.
Tout ce qui est calcul vient de ``geometry_core``, ``tool_model``,
``machine_model``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ...geometry_core import brep
from ...geometry_core.types import normalize, orthonormal_basis
from ...machine_model import MachineKinematics
from ...tool_model.assembly import ToolAssembly
from . import palette

#: Calques du banc, dans l'ordre d'affichage de l'arborescence.
#:
#: ``available`` dit si le calque a une source de donnees a ce jalon. Les autres
#: apparaissent desactives et annonces « non disponible » : prevoir l'interface
#: sans fabriquer le contenu.
LAYERS: list[tuple[str, str, bool]] = [
    ("part", "Piece finale", True),
    ("stock", "Brut", True),
    ("material", "Matiere restante", False),
    ("tool_cutting", "Fraise (arete + goujure)", True),
    ("tool_shank", "Tige et col", True),
    ("tool_holder", "Porte-outil", True),
    ("tool_spindle", "Nez de broche", True),
    ("machine", "Machine (organes)", True),
    ("machine_axes", "Axes A et C", True),
    ("limits", "Limites machine", True),
    ("fixtures", "Bridage", False),
    ("path_cut", "Trajectoire — coupe", True),
    ("path_rapid", "Trajectoire — rapides et liaisons", True),
    ("orient_ok", "Orientations admissibles", True),
    ("orient_tool", "Rejets — collision outil", True),
    ("orient_machine", "Rejets — collision machine", True),
    ("orient_kin", "Rejets — courses A/C", True),
    ("orient_sing", "Rejets — singularite", True),
    ("orient_geom", "Rejets — geometrie", True),
    ("contact", "Point de contact analyse", True),
    ("collisions", "Volumes de collision", False),
]

#: Famille de motif de rejet -> calque. Un calque par famille permet d'isoler
#: une cause : « montre-moi seulement ce que le porte-outil interdit » est la
#: question qu'on se pose devant une face refusee.
FAMILY_LAYER = {
    "admissible": "orient_ok",
    "collision outil": "orient_tool",
    "collision machine": "orient_machine",
    "cinematique": "orient_kin",
    "singularite": "orient_sing",
    "geometrie": "orient_geom",
}

#: Roles de troncons regroupes par calque, pour que l'operateur puisse isoler
#: le porte-outil ou le nez de broche — les deux pieces dont le degagement est
#: le sujet du projet.
ROLE_LAYER = {
    "cutting": "tool_cutting",
    "flute": "tool_cutting",
    "neck": "tool_shank",
    "shank": "tool_shank",
    "holder": "tool_holder",
    "spindle_nose": "tool_spindle",
}


def _pv():
    """Import paresseux : ``state`` et les tests n'ont pas besoin de PyVista."""
    import pyvista as pv

    return pv


def occt_to_mesh(shape, deflection: float = 0.05):
    """Maillage OCCT -> ``pyvista.PolyData``, via ``brep.tessellate``.

    On reutilise le tesselateur du moteur, qui reoriente deja les triangles
    selon l'orientation topologique des faces. Mailler autrement ici donnerait
    une image qui ne correspond pas a ce que le moteur calcule.

    ``face_id`` est conserve comme donnee de cellule : c'est ce qui permettra de
    selectionner une face dans la vue.
    """
    pv = _pv()
    verts, tris, face_id = brep.tessellate(shape, deflection=deflection)
    if len(tris) == 0:
        return pv.PolyData()
    faces = np.hstack([np.full((len(tris), 1), 3, dtype=np.int64),
                       np.asarray(tris, dtype=np.int64)]).ravel()
    mesh = pv.PolyData(np.asarray(verts, dtype=float), faces)
    mesh.cell_data["face_id"] = np.asarray(face_id, dtype=np.int32)
    return mesh


def frustum_mesh(z0: float, z1: float, r0: float, r1: float,
                 tcp: np.ndarray, axis: np.ndarray, n: int = 32):
    """Un troncon d'outil : cone tronque place sur (tcp, axe).

    ``z`` court depuis le BEC vers la broche, convention de ``tool_model``. Un
    troncon de rayon nul a une extremite devient un cone, ce qui arrive pour le
    bec d'une hemispherique.
    """
    pv = _pv()
    u, v, d = orthonormal_basis(normalize(axis))
    tcp = np.asarray(tcp, dtype=float)
    ang = np.linspace(0.0, 2.0 * math.pi, n, endpoint=False)
    ring = np.cos(ang)[:, None] * u + np.sin(ang)[:, None] * v

    p0 = tcp + d * z0 + ring * r0
    p1 = tcp + d * z1 + ring * r1
    pts = np.vstack([p0, p1])

    faces = []
    for k in range(n):
        k2 = (k + 1) % n
        faces.append([4, k, k2, n + k2, n + k])
    # Fermetures : un troncon ouvert laisse voir l'interieur et brouille la vue.
    faces.append([n] + list(range(n)))
    faces.append([n] + list(range(2 * n - 1, n - 1, -1)))
    return pv.PolyData(pts, np.hstack([np.asarray(f, dtype=np.int64) for f in faces]))


def transport_to_machine(mesh, machine: MachineKinematics, mount_offset,
                         a_deg: float, c_deg: float):
    """Transporte un maillage du repere PIECE vers le repere MACHINE.

    **Indispensable a la justesse de l'image, pas cosmetique.** La piece, le
    brut et les bridages vivent dans le repere piece ; les organes machine, les
    courses et la broche dans le repere machine. Les dessiner dans la meme vue
    sans transport donne une image fausse — on voyait le plateau traverser le
    brut et les droites d'axes passer a cote des pivots.

    Le transport emprunte la meme chaine que les collisions
    (``KinematicsSolver.part_to_machine_point``, qui applique Rz(C) autour de
    ``pivot_c`` puis Rx(A) autour de ``pivot_a``), de sorte que l'image ne peut
    pas differer du calcul.
    """
    from ...kinematics_solver.solver import KinematicsSolver

    if mesh is None or mesh.n_points == 0:
        return mesh
    ks = KinematicsSolver(machine)
    mo = np.asarray(mount_offset, dtype=float)
    out = mesh.copy()
    pts = np.asarray(out.points, dtype=float) + mo
    out.points = np.array([ks.part_to_machine_point(q, a_deg, c_deg) for q in pts])
    return out


def transport_by_frame(mesh, machine: MachineKinematics, frame: str,
                       a_deg: float, c_deg: float):
    """Amene un maillage du repere de son MAILLON vers le repere machine.

    Les organes de collision sont decrits dans le repere du maillon qui les
    porte (``machine``, ``cradle_A``, ``table_C``). Les dessiner sans les
    animer les laisse a leur place de A = C = 0 : a A = -75 deg la piece part a
    116 mm en Y et -61 mm en Z tandis que le plateau reste plat, donc l'image
    montre une piece detachee du plateau sur lequel elle est bridee.

    Sur une vue dont le sujet EST le degagement machine, c'est plus qu'un
    defaut d'esthetique — c'est l'inverse de ce qu'on vient verifier. La chaine
    employee ici est la meme que celle du transport de la piece, ce qui garantit
    que les deux restent solidaires.
    """
    from ...kinematics_solver.solver import KinematicsSolver

    if mesh is None or mesh.n_points == 0 or frame == "machine":
        return mesh
    ks = KinematicsSolver(machine)
    out = mesh.copy()
    pts = np.asarray(out.points, dtype=float)
    if frame == "table_C":
        # Porte par le plateau : subit C puis A, comme la piece elle-meme.
        out.points = np.array([ks.part_to_machine_point(q, a_deg, c_deg) for q in pts])
    elif frame == "cradle_A":
        # Porte par le berceau : subit A seulement.
        out.points = np.array([ks.part_to_machine_point(q, a_deg, 0.0) for q in pts])
    else:
        raise ValueError(f"repere de volume machine inconnu : {frame}")
    return out


def box_mesh(lo, hi):
    pv = _pv()
    lo = np.asarray(lo, dtype=float)
    hi = np.asarray(hi, dtype=float)
    return pv.Box(bounds=(lo[0], hi[0], lo[1], hi[1], lo[2], hi[2]))


def cylinder_mesh(base, axis, radius: float, height: float):
    pv = _pv()
    b = np.asarray(base, dtype=float)
    a = normalize(axis)
    return pv.Cylinder(center=b + a * (height / 2.0), direction=a,
                       radius=float(radius), height=float(height))


@dataclass
class DebugScene:
    """Scene du banc : des calques nommes, affichables independamment.

    Ne detient aucune logique metier. Elle recoit des objets deja construits par
    les modules du moteur et les traduit en acteurs.
    """

    plotter: object
    actors: dict[str, list] = field(default_factory=dict)
    #: Maillages conserves par calque, pour pouvoir cadrer sur un sous-ensemble
    #: sans redemander leur geometrie aux modules metier.
    meshes: dict[str, list] = field(default_factory=dict)
    visible: dict[str, bool] = field(default_factory=dict)
    unavailable: set[str] = field(default_factory=set)
    #: famille -> (fleches dessinees, fleches totales). Non egaux = affichage
    #: borne, et le panneau doit le dire.
    drawn_counts: dict[str, tuple[int, int]] = field(default_factory=dict)

    # ------------------------------------------------------------------ calques

    def _add(self, layer: str, mesh, **kw) -> None:
        if mesh is None or (hasattr(mesh, "n_points") and mesh.n_points == 0):
            return
        actor = self.plotter.add_mesh(mesh, **kw)
        self.actors.setdefault(layer, []).append(actor)
        self.meshes.setdefault(layer, []).append(mesh)
        self.visible.setdefault(layer, True)

    def add_part(self, mesh) -> None:
        self._add("part", mesh, color=palette.PART,
                  opacity=palette.OPACITY["part"], smooth_shading=True,
                  name="part")

    def add_stock(self, mesh) -> None:
        if mesh is None:
            self.unavailable.add("stock")
            return
        self._add("stock", mesh, color=palette.STOCK,
                  opacity=palette.OPACITY["stock"], show_edges=True,
                  edge_color=palette.GRID, name="stock")

    def add_tool(self, tool: ToolAssembly, tcp: np.ndarray, axis: np.ndarray) -> None:
        """L'outil COMPLET, un acteur par troncon, colore par role.

        C'est la vue qui donne son sens au projet : on doit voir que le
        porte-outil et le nez de broche existent dans le modele de collision, et
        pas seulement le point TCP.
        """
        for i, seg in enumerate(tool.segments):
            layer = ROLE_LAYER.get(seg.role.value, "tool_shank")
            self._add(layer,
                      frustum_mesh(seg.z_start, seg.z_end, seg.r_start, seg.r_end,
                                   tcp, axis),
                      color=palette.role_color(seg.role.value),
                      opacity=palette.OPACITY["tool"], smooth_shading=True,
                      name=f"tool_{i}_{seg.role.value}")

    def add_machine_volumes(self, machine: MachineKinematics,
                            a_deg: float = 0.0, c_deg: float = 0.0) -> None:
        """Organes machine, dans leur propre repere.

        Dessines dans le repere MACHINE, comme toute la scene, et **animes par
        (A, C)** : le plateau suit C puis A, le berceau suit A seulement, la
        piece suit les deux. Les trois restent donc solidaires a toute pose, ce
        qui est la condition pour que la vue des orientations veuille dire
        quelque chose — c'est le degagement contre ces organes qu'elle montre.
        """
        for cv in machine.collision_volumes:
            mesh = (box_mesh(cv.lo, cv.hi) if cv.kind == "box"
                    else cylinder_mesh(cv.base, cv.axis, cv.radius, cv.height))
            mesh = transport_by_frame(mesh, machine, cv.frame, a_deg, c_deg)
            self._add("machine", mesh, color=palette.MACHINE,
                      opacity=palette.OPACITY["machine"], show_edges=False,
                      name=f"mv_{cv.name}")

    def add_machine_axes(self, machine: MachineKinematics, length: float = 90.0,
                         a_deg: float = 0.0) -> None:
        """Les droites des axes A et C, a leur position declaree.

        Ce sont les grandeurs que ``assembly_calibration`` mesure ; les voir est
        le seul moyen de reperer un pivot place n'importe ou avant de lancer un
        calcul. La legende dit qu'elles sont NOMINALES tant qu'aucune
        calibration n'est chargee.
        """
        pv = _pv()
        # L'axe A est fixe dans le repere machine ; l'axe C est porte par le
        # berceau, donc il basculE avec A. Les dessiner tous deux fixes ferait
        # croire a une cinematique ou le plateau ne s'incline pas.
        rot_a = machine.rotation_machine_from_part(a_deg, 0.0)
        for point, direction, label, moving in (
            (machine.pivot_a, (1.0, 0.0, 0.0), "A", False),
            (machine.pivot_c, (0.0, 0.0, 1.0), "C", True),
        ):
            p = np.asarray(point, dtype=float)
            d = normalize(np.asarray(direction, dtype=float))
            if moving:
                pa = np.asarray(machine.pivot_a, dtype=float)
                p = rot_a @ (p - pa) + pa
                d = normalize(rot_a @ d)
            line = pv.Line(p - d * length, p + d * length)
            self._add("machine_axes", line, color=palette.WARNING, line_width=3,
                      name=f"axis_{label}")
            self._add("machine_axes", pv.Sphere(radius=2.0, center=p),
                      color=palette.WARNING, name=f"pivot_{label}")

    def add_travel_limits(self, machine: MachineKinematics) -> None:
        """Boite des courses lineaires. Un cadre, pas un volume plein."""
        lo = (machine.x.min_mm, machine.y.min_mm, machine.z.min_mm)
        hi = (machine.x.max_mm, machine.y.max_mm, machine.z.max_mm)
        self._add("limits", box_mesh(lo, hi), color=palette.WARNING,
                  style="wireframe", line_width=1, opacity=0.6, name="limits")

    def add_toolpath(self, points, is_rapid, machine: MachineKinematics,
                     mount_offset, a_deg: float, c_deg: float, *,
                     tube_radius: float = 0.0) -> None:
        """Trajectoire d'une operation, coupe et liaisons separees.

        Deux calques et non un seul : la question qu'on se pose devant une
        trajectoire est « ou est-ce que ca coupe » et « par ou est-ce que ca
        passe ». Les melanger dans une seule polyligne bleue rend la seconde
        illisible, alors que c'est elle qui porte les liaisons au plan de
        degagement — donc les mouvements qui traversent la piece quand ils sont
        mal generes.

        Le transport passe par la meme chaine que la piece, sinon la
        trajectoire flotterait a cote de la matiere qu'elle enleve.
        """
        pv = _pv()
        from ...kinematics_solver.solver import KinematicsSolver

        P = np.asarray(points, dtype=float).reshape(-1, 3)
        if len(P) < 2:
            return
        R = (np.zeros(len(P), dtype=bool) if is_rapid is None
             else np.asarray(is_rapid, dtype=bool).reshape(-1))

        ks = KinematicsSolver(machine)
        mo = np.asarray(mount_offset, dtype=float)
        M = np.array([ks.part_to_machine_point(q + mo, a_deg, c_deg) for q in P])

        # Un segment est « rapide » si l'une de ses extremites l'est : c'est le
        # choix conservatif pour l'affichage, celui qui ne cache pas un
        # mouvement hors matiere derriere une couleur de coupe.
        seg_rapid = R[1:] | R[:-1]
        for mask, layer, color, width in (
            (~seg_rapid, "path_cut", palette.PATH, 3),
            (seg_rapid, "path_rapid", palette.WARNING, 1),
        ):
            idx = np.flatnonzero(mask)
            if idx.size == 0:
                continue
            # Un acteur unique : des milliers de petites lignes separees
            # etoufferaient le rendu.
            pts = np.empty((idx.size * 2, 3))
            pts[0::2] = M[idx]
            pts[1::2] = M[idx + 1]
            cells = np.hstack([np.column_stack([
                np.full(idx.size, 2), np.arange(0, idx.size * 2, 2),
                np.arange(1, idx.size * 2, 2)])]).ravel()
            poly = pv.PolyData()
            poly.points = pts
            poly.lines = cells
            self._add(layer, poly, color=color, line_width=width,
                      name=f"{layer}_lines")

    def add_orientations(self, result, machine: MachineKinematics, mount_offset,
                         a_deg: float, c_deg: float, *,
                         length: float = 20.0, only_family: str | None = None,
                         max_arrows_per_family: int = 400) -> None:
        """Fleches 3D des orientations candidates, un calque par famille de motif.

        Les fleches partent toutes du MEME point de contact et s'ouvrent en
        eventail : c'est la forme naturelle de la question posee — en ce point,
        quelles directions d'outil sont utilisables.

        Elles sont dessinees dans le repere de la scene (machine), donc les
        directions sont tournees par la pose d'inspection. Sans cela, un
        eventail calcule en repere piece serait affiche penche des que A ou C
        n'est pas nul.

        ``max_arrows_per_family`` borne l'affichage : une grille a 4
        subdivisions produit 2562 directions, et autant de fleches noient la
        piece au lieu de la montrer. Quand la borne mord, le nombre reellement
        dessine est conserve dans ``self.drawn_counts`` pour que le panneau
        puisse le dire.
        """
        pv = _pv()
        from ...kinematics_solver.solver import KinematicsSolver

        ks = KinematicsSolver(machine)
        origin = ks.part_to_machine_point(
            np.asarray(result.point, dtype=float) + np.asarray(mount_offset, float),
            a_deg, c_deg)
        rot = machine.rotation_machine_from_part(a_deg, c_deg)

        groups: dict[str, list] = {}
        for cnd in result.candidates:
            fam = cnd.family
            if only_family is not None and fam != only_family:
                continue
            groups.setdefault(fam, []).append(cnd)

        from . import palette as pal

        for fam, lst in groups.items():
            layer = FAMILY_LAYER.get(fam, "orient_geom")
            shown = lst[:max_arrows_per_family]
            self.drawn_counts[fam] = (len(shown), len(lst))
            dirs = np.array([rot @ normalize(c.direction) for c in shown])
            pts = np.tile(origin, (len(shown), 1))
            cloud = pv.PolyData(pts)
            cloud["vectors"] = dirs
            cloud.set_active_vectors("vectors")
            glyph = cloud.glyph(orient="vectors", scale=False,
                                factor=float(length), geom=pv.Arrow())
            # Couleur du motif DOMINANT de la famille : dans une meme famille
            # les nuances sont proches, et une couleur par fleche empecherait de
            # lire la famille d'un coup d'oeil.
            noms = {}
            for c in shown:
                noms[c.reason_name] = noms.get(c.reason_name, 0) + 1
            dominant = max(noms, key=noms.get) if noms else "OK"
            self._add(layer, glyph, color=pal.reason_color(dominant),
                      name=f"orient_{fam.replace(' ', '_')}")

        self._add("contact", pv.Sphere(radius=max(length * 0.06, 0.3),
                                       center=origin),
                  color=palette.PATH, name="contact_point")

    def highlight_orientation(self, result, machine: MachineKinematics, mount_offset,
                              a_deg: float, c_deg: float, candidate, *,
                              length: float = 20.0) -> None:
        """Met en evidence UNE orientation, celle que l'operateur interroge.

        Remplace la precedente : deux fleches mises en evidence en meme temps
        ne designeraient rien.
        """
        pv = _pv()
        from ...kinematics_solver.solver import KinematicsSolver

        for a in self.actors.pop("highlight", []):
            self.plotter.remove_actor(a)
        self.meshes.pop("highlight", None)

        ks = KinematicsSolver(machine)
        origin = ks.part_to_machine_point(
            np.asarray(result.point, dtype=float) + np.asarray(mount_offset, float),
            a_deg, c_deg)
        d = machine.rotation_machine_from_part(a_deg, c_deg) @ normalize(candidate.direction)
        arrow = pv.Arrow(start=origin, direction=d, scale=float(length) * 1.35,
                         tip_radius=0.14, shaft_radius=0.05)
        self._add("highlight", arrow, color="#ffffff", name="highlight")

    # ------------------------------------------------------------------ controle

    def set_visible(self, layer: str, on: bool) -> bool:
        """Affiche ou cache un calque. Rend l'etat REEL apres l'operation.

        Rendre l'etat reel plutot que rien permet a l'interface de se corriger
        si un calque n'a pas d'acteur : une case cochee sur un calque vide
        ferait croire a un affichage.
        """
        acts = self.actors.get(layer)
        if not acts:
            self.visible[layer] = False
            return False
        for a in acts:
            a.SetVisibility(bool(on))
        self.visible[layer] = bool(on)
        return bool(on)

    def layer_status(self) -> list[tuple[str, str, bool, bool]]:
        """(cle, libelle, disponible, visible) pour l'arborescence."""
        out = []
        for key, label, declared in LAYERS:
            has = bool(self.actors.get(key))
            out.append((key, label, declared and has, self.visible.get(key, False)))
        return out

    # ------------------------------------------------------------------ camera

    def reset_view(self) -> None:
        """Cadre sur TOUTE la scene, courses machine comprises."""
        self.plotter.reset_camera()
        self.plotter.view_isometric()

    def fit_layers(self, *prefixes: str) -> None:
        """Cadre sur les calques dont la cle commence par un des prefixes.

        ``fit_layers("part", "stock", "tool")`` est le cadrage par defaut du
        banc : il montre la piece, son brut ET l'outil entier. Cadrer sur la
        seule piece coupait le porte-outil hors de l'image, alors que le voir
        est precisement ce qu'on vient verifier.
        """
        picked = [m for key, lst in self.meshes.items()
                  if any(key.startswith(pre) for pre in prefixes)
                  for m in lst]
        self.fit_to(*picked)

    def fit_to(self, *meshes) -> None:
        """Cadre sur les maillages donnes, ou sur tout si aucun n'est fourni.

        Les courses machine font 300 x 240 x 180 mm : cadrer dessus rend une
        piece de 60 mm illisible. Le cadrage par defaut porte donc sur la piece
        et son brut, et « voir tout » reste un geste explicite.

        **La camera est posee a la main**, et non par ``reset_camera(bounds=...)``.
        Mesure : cet argument est ignore par la version de PyVista employee ici,
        et les deux cadrages rendaient une camera identique a 819,6 mm du point
        vise — celle de la scene entiere. Un cadrage qui ne cadre pas est le
        genre de defaut qu'on ne voit pas sans comparer deux images.
        """
        pts = [np.asarray(m.points, dtype=float) for m in meshes
               if m is not None and getattr(m, "n_points", 0) > 0]
        if not pts:
            self.reset_view()
            return
        allp = np.vstack(pts)
        lo, hi = allp.min(axis=0), allp.max(axis=0)
        centre = 0.5 * (lo + hi)
        radius = max(0.5 * float(np.linalg.norm(hi - lo)), 1e-6)

        cam = self.plotter.camera
        fov = math.radians(float(cam.view_angle) or 30.0)
        distance = radius / max(math.tan(fov / 2.0), 1e-6) * 1.15
        direction = normalize(np.array([1.0, 1.0, 0.75]))
        cam.focal_point = tuple(centre)
        cam.position = tuple(centre + direction * distance)
        cam.up = (0.0, 0.0, 1.0)
        self.plotter.reset_camera_clipping_range()

    def orbit(self, azimuth_deg: float = 0.0, elevation_deg: float = 0.0) -> None:
        """Rotation programmatique — le pendant testable du glisser-deposer."""
        if azimuth_deg:
            self.plotter.camera.azimuth += float(azimuth_deg)
        if elevation_deg:
            self.plotter.camera.elevation += float(elevation_deg)
        self.plotter.render()

    def zoom(self, factor: float) -> None:
        self.plotter.camera.zoom(float(factor))
        self.plotter.render()

    def screenshot(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.plotter.screenshot(str(p))
        return p


def build_scene(state, *, plotter=None, off_screen: bool = True,
                window_size=(1280, 860), deflection: float = 0.05,
                fit: str = "part") -> DebugScene:
    """Construit la scene complete depuis un ``BenchState``.

    Meme fonction pour la fenetre Qt et pour la capture sans ecran : un seul
    chemin de construction, donc pas de divergence possible entre ce que
    l'operateur voit et ce qu'une capture montre.

    **Toute la scene est exprimee en repere MACHINE.** La piece, le brut et
    l'outil y sont amenes par la chaine cinematique du moteur. Melanger les
    reperes donnait une image fausse, et une image fausse sur un banc de debug
    est pire que pas d'image.

    ``fit`` decide du cadrage initial : ``"part"`` cadre sur la piece et son
    brut — les courses machine font 300 x 240 x 180 mm et cadrer dessus rend la
    piece minuscule ; ``"all"`` cadre sur tout.
    """
    pv = _pv()
    if plotter is None:
        pv.OFF_SCREEN = bool(off_screen)
        plotter = pv.Plotter(off_screen=off_screen, window_size=window_size)

    scene = DebugScene(plotter=plotter)
    plotter.set_background(palette.BACKGROUND)

    mo = state.mount_offset
    a, c = float(state.inspect_a_deg), float(state.inspect_c_deg)

    part_mesh = None
    if state.part_shape is not None:
        part_mesh = transport_to_machine(
            occt_to_mesh(state.part_shape, deflection), state.machine, mo, a, c)
        scene.add_part(part_mesh)

    stock_mesh = None
    if state.stock is not None and state.stock.lo is not None:
        stock_mesh = transport_to_machine(
            box_mesh(state.stock.lo, state.stock.hi), state.machine, mo, a, c)
        scene.add_stock(stock_mesh)

    if state.tool is not None:
        # L'outil n'est PAS dans le repere piece : la broche vit dans le repere
        # machine et son axe y vaut invariablement +Z. On le place donc au TCP
        # machine, sans transport.
        scene.add_tool(state.tool, state.machine_tcp(), np.array([0.0, 0.0, 1.0]))

    scene.add_machine_volumes(state.machine, a, c)
    scene.add_machine_axes(state.machine, a_deg=a)
    scene.add_travel_limits(state.machine)

    plotter.add_axes(interactive=False)
    if fit == "part":
        scene.fit_layers("part", "stock", "tool")
    else:
        scene.reset_view()
    return scene


def _arrow_length(state) -> float:
    """Longueur de fleche proportionnee a la piece.

    Une longueur fixe donne des fleches minuscules sur une piece de 200 mm et
    des fleches qui la traversent sur une piece de 10 mm.
    """
    if state.part is None:
        return 20.0
    diag = float(np.linalg.norm(state.part.bbox.hi - state.part.bbox.lo))
    return max(diag * 0.45, 5.0)


def camera_serie(state, *, azimuth_deg: float = 0.0, elevation_deg: float = 0.0,
                 window_size=(1280, 860), deflection: float = 0.05):
    """Camera FIXE a passer a ``capture`` pour une suite d'images.

    Le cadrage automatique de ``capture`` porte sur « piece + brut + outil ».
    C'est le bon cadrage pour UNE image, et le mauvais pour une suite : l'outil
    se deplace, donc le cadrage suit l'outil, donc la piece saute d'une image a
    l'autre. Sur une animation, ce saut se lit comme un mouvement de la
    machine — l'image raconte alors quelque chose que la machine ne fait pas.

    Le cadrage rendu ici porte sur « piece + brut + ORGANES machine ». Les
    organes ne bougent pas avec l'outil, et ils englobent le plateau, donc la
    piece quelle que soit son indexation A/C. Le meme cadrage convient ainsi a
    toutes les images d'une serie, y compris de part et d'autre d'une
    reindexation.
    """
    pv = _pv()
    pv.OFF_SCREEN = True
    plotter = pv.Plotter(off_screen=True, window_size=window_size)
    scene = DebugScene(plotter=plotter)
    mo = state.mount_offset
    a, c = float(state.inspect_a_deg), float(state.inspect_c_deg)
    if state.part_shape is not None:
        scene.add_part(transport_to_machine(
            occt_to_mesh(state.part_shape, deflection), state.machine, mo, a, c))
    if state.stock is not None and state.stock.lo is not None:
        scene.add_stock(transport_to_machine(
            box_mesh(state.stock.lo, state.stock.hi), state.machine, mo, a, c))
    scene.add_machine_volumes(state.machine, a, c)
    scene.fit_layers("part", "stock", "machine")
    if azimuth_deg:
        plotter.camera.azimuth += float(azimuth_deg)
    if elevation_deg:
        plotter.camera.elevation += float(elevation_deg)
    cam = tuple(tuple(float(x) for x in v) for v in plotter.camera_position)
    plotter.close()
    return cam


def capture(state, path: str | Path, *, hidden=(), azimuth_deg: float = 0.0,
            elevation_deg: float = 0.0, zoom: float = 1.0, fit: str = "part",
            window_size=(1280, 860), deflection: float = 0.05,
            accessibility=None, arrow_length: float | None = None,
            toolpath=None, camera=None, background=None) -> Path:
    """Capture PNG d'un etat, par un plotter NEUF a chaque appel.

    **Pourquoi un plotter neuf et non une capture du plotter vivant.** Mesure
    faite sur le rendu logiciel sans ecran (OSMesa, le cas d'un Raspberry Pi en
    SSH ou d'une integration continue) : une fenetre de rendu y produit une
    seule image, et **tout changement ulterieur est ignore**. Fond, camera,
    visibilite d'un acteur — la capture suivante est identique au bit pres. Ce
    n'est pas un defaut du banc mais un comportement du rendu logiciel, et il
    rendrait le bouton CAPTURE silencieusement faux : on croirait photographier
    l'etat courant et on re-photographierait le premier.

    Construire une fenetre par capture coute un rendu complet — de l'ordre de la
    seconde sur une piece du corpus — et rend l'image exacte partout, avec ou
    sans ecran. C'est le bon echange pour un bouton qu'on presse a la main.

    ``hidden`` liste les cles de calques a ne pas dessiner. Elles sont ecartees
    A LA CONSTRUCTION, ce qui est plus sur qu'un acteur rendu invisible : un
    calque absent ne peut pas reapparaitre par un rendu qui ignore la
    visibilite.
    """
    pv = _pv()
    hide = set(hidden)
    pv.OFF_SCREEN = True
    plotter = pv.Plotter(off_screen=True, window_size=window_size)
    scene = DebugScene(plotter=plotter)
    # Le fond du BANC est sombre, et c'est justifie la-bas : le degrade de
    # l'outil va du clair (l'arete, qui doit toucher) au sombre (le nez de
    # broche, qui ne doit jamais toucher), de sorte que la gravite d'un contact
    # se lise sur la teinte. Mais pour quelqu'un qui regarde simplement son
    # usinage, le porte-outil et le nez deviennent une tache noire sur un fond
    # noir. Le fond est donc REGLABLE par l'appelant, sans toucher au code
    # couleur, qui reste l'unique source.
    plotter.set_background(background or palette.BACKGROUND)

    mo = state.mount_offset
    a, c = float(state.inspect_a_deg), float(state.inspect_c_deg)

    part_mesh = stock_mesh = None
    if state.part_shape is not None and "part" not in hide:
        part_mesh = transport_to_machine(
            occt_to_mesh(state.part_shape, deflection), state.machine, mo, a, c)
        scene.add_part(part_mesh)
    if state.stock is not None and state.stock.lo is not None and "stock" not in hide:
        stock_mesh = transport_to_machine(
            box_mesh(state.stock.lo, state.stock.hi), state.machine, mo, a, c)
        scene.add_stock(stock_mesh)
    if state.tool is not None:
        tcp = state.machine_tcp()
        for i, seg in enumerate(state.tool.segments):
            layer = ROLE_LAYER.get(seg.role.value, "tool_shank")
            if layer in hide:
                continue
            scene._add(layer,
                       frustum_mesh(seg.z_start, seg.z_end, seg.r_start, seg.r_end,
                                    tcp, np.array([0.0, 0.0, 1.0])),
                       color=palette.role_color(seg.role.value),
                       opacity=palette.OPACITY["tool"], smooth_shading=True,
                       name=f"tool_{i}_{seg.role.value}")
    if "machine" not in hide:
        scene.add_machine_volumes(state.machine, a, c)
    if "machine_axes" not in hide:
        scene.add_machine_axes(state.machine, a_deg=a)
    if "limits" not in hide:
        scene.add_travel_limits(state.machine)

    if toolpath is not None:
        pts_tp, rap_tp = toolpath
        scene.add_toolpath(pts_tp, rap_tp, state.machine, mo, a, c)

    if accessibility is not None:
        L = arrow_length if arrow_length is not None else _arrow_length(state)
        scene.add_orientations(accessibility, state.machine, mo, a, c, length=L)

    for key in list(scene.actors):
        if key in hide:
            scene.set_visible(key, False)

    plotter.add_axes(interactive=False)
    if camera is not None:
        # Cadrage IMPOSE. Une suite d'images ne peut pas se recadrer a chaque
        # vue : le cadrage automatique suit l'outil, et l'outil bouge, donc
        # la piece sauterait d'une image a l'autre. Le spectateur lirait ce
        # saut comme un mouvement de la machine — il faut donc pouvoir fixer
        # la camera une fois pour toute la serie.
        plotter.camera_position = camera
        plotter.reset_camera_clipping_range()
    else:
        if fit == "part":
            scene.fit_layers("part", "stock", "tool")
        else:
            scene.reset_view()
        if azimuth_deg:
            plotter.camera.azimuth += float(azimuth_deg)
        if elevation_deg:
            plotter.camera.elevation += float(elevation_deg)
        if zoom and zoom != 1.0:
            plotter.camera.zoom(float(zoom))

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    plotter.screenshot(str(out))
    plotter.close()
    return out
