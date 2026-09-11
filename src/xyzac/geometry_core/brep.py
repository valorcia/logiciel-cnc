"""Facade OCCT (via OCP) : import/export STEP, tessellation, echantillonnage.

Aucun autre module du projet n'importe ``OCP`` directement. Ce fichier est la
seule frontiere avec le noyau B-Rep (ADR-001 / D1) : un changement de bindings
(OCP -> pythonocc-core) se traite ici et nulle part ailleurs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepGProp import BRepGProp
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.Bnd import Bnd_Box
from OCP.GeomAbs import GeomAbs_SurfaceType
from OCP.GProp import GProp_GProps
from OCP.IFSelect import IFSelect_ReturnStatus
from OCP.Interface import Interface_Static
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Reader, STEPControl_Writer
from OCP.TopAbs import TopAbs_FACE, TopAbs_Orientation, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS, TopoDS_Face, TopoDS_Shape

from .types import AABB

# Noms lisibles des types de surface OCCT : sert au feature_engine et aux messages UI.
SURFACE_TYPE_NAMES = {
    GeomAbs_SurfaceType.GeomAbs_Plane: "plane",
    GeomAbs_SurfaceType.GeomAbs_Cylinder: "cylinder",
    GeomAbs_SurfaceType.GeomAbs_Cone: "cone",
    GeomAbs_SurfaceType.GeomAbs_Sphere: "sphere",
    GeomAbs_SurfaceType.GeomAbs_Torus: "torus",
    GeomAbs_SurfaceType.GeomAbs_BezierSurface: "bezier",
    GeomAbs_SurfaceType.GeomAbs_BSplineSurface: "bspline",
    GeomAbs_SurfaceType.GeomAbs_SurfaceOfRevolution: "revolution",
    GeomAbs_SurfaceType.GeomAbs_SurfaceOfExtrusion: "extrusion",
    GeomAbs_SurfaceType.GeomAbs_OffsetSurface: "offset",
    GeomAbs_SurfaceType.GeomAbs_OtherSurface: "other",
}


class StepLoadError(RuntimeError):
    """Echec d'import STEP, avec le statut OCCT conserve pour diagnostic."""


@dataclass
class SampledSurface:
    """Nuage de points oriente, avec une garantie d'espacement.

    ``max_spacing`` est le majorant de la distance entre un point quelconque de
    la surface et le point echantillonne le plus proche. C'est la quantite qui
    rend le test de collision conservatif (ADR-001 / D2) : on inflate les
    obstacles de ``max_spacing`` avant tout test.
    """

    points: np.ndarray   # (N,3)
    normals: np.ndarray  # (N,3) sortantes de la matiere
    face_ids: np.ndarray  # (N,) index de la face d'origine
    max_spacing: float

    def __len__(self) -> int:
        return int(self.points.shape[0])


@dataclass
class FaceInfo:
    """Metadonnees d'une face, sans exposer le type OCCT aux modules amont."""

    index: int
    surface_type: str
    area: float
    reversed_: bool
    axis_location: np.ndarray | None = None   # cylindre/cone/revolution : point de l'axe
    axis_direction: np.ndarray | None = None  # cylindre/cone/revolution : direction d'axe
    radius: float | None = None


def load_step(path: str | Path) -> TopoDS_Shape:
    """Charge un STEP en une forme unique.

    Force les unites en millimetres : un STEP en pouces silencieusement
    interprete en mm produirait des trajectoires fausses d'un facteur 25,4.
    """
    path = Path(path)
    if not path.exists():
        raise StepLoadError(f"fichier introuvable : {path}")

    reader = STEPControl_Reader()
    Interface_Static.SetCVal_s("xstep.cascade.unit", "MM")
    status = reader.ReadFile(str(path))
    if status != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise StepLoadError(f"lecture STEP echouee ({status}) : {path}")

    reader.TransferRoots()
    n = reader.NbShapes()
    if n < 1:
        raise StepLoadError(f"STEP sans forme exploitable : {path}")
    shape = reader.OneShape()
    if shape.IsNull():
        raise StepLoadError(f"forme nulle apres transfert : {path}")
    return shape


def save_step(shape: TopoDS_Shape, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = STEPControl_Writer()
    Interface_Static.SetCVal_s("write.step.unit", "MM")
    writer.Transfer(shape, STEPControl_AsIs)
    if writer.Write(str(path)) != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise StepLoadError(f"ecriture STEP echouee : {path}")
    return path


def bounding_box(shape: TopoDS_Shape, tolerance: float = 1e-6) -> AABB:
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box, True)
    box.SetGap(tolerance)
    # OCP 8.x : Bnd_Box.Get() renvoie une struct non depaquetable cote Python ;
    # CornerMin/CornerMax est l'acces portable.
    return AABB(_pnt(box.CornerMin()), _pnt(box.CornerMax()))


def volume(shape: TopoDS_Shape) -> float:
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return float(props.Mass())


# OCP n'expose pas les statiques sous un nom stable d'une version a l'autre :
# TopoDS.Face_s en 7.7, TopoDS.Face en 8.0. La facade absorbe la derive.
_to_face = getattr(TopoDS, "Face_s", None) or TopoDS.Face


def iter_faces(shape: TopoDS_Shape):
    """Itere les faces dans un ordre deterministe (necessaire pour les tests)."""
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    i = 0
    while exp.More():
        yield i, _to_face(exp.Current())
        exp.Next()
        i += 1


def count_solids(shape: TopoDS_Shape) -> int:
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    n = 0
    while exp.More():
        n += 1
        exp.Next()
    return n


def face_info(shape: TopoDS_Shape) -> list[FaceInfo]:
    """Decrit chaque face : type, aire, et axe pour les surfaces de revolution.

    L'axe est ce dont ``turning_engine`` a besoin pour detecter les regions
    tournables (des faces coaxiales autour de l'axe C).
    """
    out: list[FaceInfo] = []
    for idx, face in iter_faces(shape):
        ad = BRepAdaptor_Surface(face)
        st = ad.GetType()
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, props)

        loc = direction = None
        radius = None
        try:
            if st == GeomAbs_SurfaceType.GeomAbs_Cylinder:
                cyl = ad.Cylinder()
                ax = cyl.Axis()
                loc = _pnt(ax.Location())
                direction = _dir(ax.Direction())
                radius = float(cyl.Radius())
            elif st == GeomAbs_SurfaceType.GeomAbs_Cone:
                cone = ad.Cone()
                ax = cone.Axis()
                loc = _pnt(ax.Location())
                direction = _dir(ax.Direction())
                radius = float(cone.RefRadius())
            elif st == GeomAbs_SurfaceType.GeomAbs_Sphere:
                loc = _pnt(ad.Sphere().Location())
                radius = float(ad.Sphere().Radius())
            elif st == GeomAbs_SurfaceType.GeomAbs_Torus:
                tor = ad.Torus()
                ax = tor.Axis()
                loc = _pnt(ax.Location())
                direction = _dir(ax.Direction())
                radius = float(tor.MajorRadius())
            elif st == GeomAbs_SurfaceType.GeomAbs_SurfaceOfRevolution:
                ax = ad.AxeOfRevolution()
                loc = _pnt(ax.Location())
                direction = _dir(ax.Direction())
        except Exception:
            # Une face peut declarer un type sans exposer la primitive attendue.
            # On degrade proprement : l'absence d'axe est une information valide.
            pass

        out.append(
            FaceInfo(
                index=idx,
                surface_type=SURFACE_TYPE_NAMES.get(st, "other"),
                area=float(props.Mass()),
                reversed_=(face.Orientation() == TopAbs_Orientation.TopAbs_REVERSED),
                axis_location=loc,
                axis_direction=direction,
                radius=radius,
            )
        )
    return out


def _pnt(p) -> np.ndarray:
    return np.array([p.X(), p.Y(), p.Z()], dtype=np.float64)


def _dir(d) -> np.ndarray:
    return np.array([d.X(), d.Y(), d.Z()], dtype=np.float64)


def tessellate(
    shape: TopoDS_Shape, deflection: float = 0.05, angular_deflection: float = 0.3
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Maille la forme. Retourne (vertices (V,3), triangles (T,3), face_id (T,)).

    Les triangles sont reorientes selon l'orientation topologique de la face,
    de sorte que la normale calculee pointe vers l'exterieur de la matiere.
    """
    BRepMesh_IncrementalMesh(shape, deflection, False, angular_deflection, True)

    verts: list[np.ndarray] = []
    tris: list[tuple[int, int, int]] = []
    tri_face: list[int] = []

    for idx, face in iter_faces(shape):
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is None:
            continue  # face non maillee (degeneree) : signalee par check_mesh_coverage
        trsf = loc.Transformation()
        base = len(verts)

        for i in range(1, tri.NbNodes() + 1):
            p = tri.Node(i).Transformed(trsf)
            verts.append(np.array([p.X(), p.Y(), p.Z()]))

        flip = face.Orientation() == TopAbs_Orientation.TopAbs_REVERSED
        for i in range(1, tri.NbTriangles() + 1):
            a, b, c = tri.Triangle(i).Get()
            if flip:
                a, c = c, a
            tris.append((base + a - 1, base + b - 1, base + c - 1))
            tri_face.append(idx)

    if not tris:
        raise StepLoadError("tessellation vide : forme sans face maillable")

    return (
        np.array(verts, dtype=np.float64),
        np.array(tris, dtype=np.int64),
        np.array(tri_face, dtype=np.int64),
    )


#: En deca de cette aire doublee (|produit vectoriel|), un triangle est
#: considere degenere : sa normale n'a aucun sens geometrique.
DEGENERATE_TRIANGLE_EPS = 1e-12


def _triangle_normals(v: np.ndarray, t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Normales unitaires + masque des triangles exploitables.

    OCCT produit occasionnellement des triangles d'aire nulle (observe sur les
    surfaces spheriques du corpus). Leur normale est indefinie. La normaliser
    par 1.0 donnerait un vecteur quasi nul qui PASSE pour une normale — et le
    filtre geometrique du solveur d'accessibilite, qui projette les directions
    candidates sur la normale, rendrait alors un resultat arbitraire.

    On les ecarte donc explicitement. Leur aire etant nulle, leurs sommets sont
    confondus avec ceux des triangles voisins : la garantie d'espacement de
    l'echantillonnage n'en souffre pas.
    """
    n = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
    ln = np.linalg.norm(n, axis=1)
    valid = ln > DEGENERATE_TRIANGLE_EPS
    out = np.zeros_like(n)
    out[valid] = n[valid] / ln[valid, None]
    return out, valid


def sample_surface(
    shape: TopoDS_Shape, spacing: float = 1.0, deflection: float | None = None
) -> SampledSurface:
    """Echantillonne la surface avec un espacement **borne** par ``spacing``.

    La tessellation OCCT borne la *fleche*, pas la *taille* des triangles : une
    grande face plane ne donne que deux triangles. On subdivise donc chaque
    triangle en grille barycentrique jusqu'a ce que son arete la plus longue
    passe sous ``spacing``. C'est ce qui permet d'affirmer un ``max_spacing``,
    dont depend la garantie conservative du collision engine.
    """
    if deflection is None:
        deflection = max(spacing * 0.25, 1e-3)
    v, t, tf = tessellate(shape, deflection=deflection)
    normals, valid = _triangle_normals(v, t)
    if not np.any(valid):
        raise StepLoadError("tessellation entierement degeneree : forme inexploitable")

    pts_all, nrm_all, fid_all = [], [], []
    for k in np.flatnonzero(valid):
        p0, p1, p2 = v[t[k, 0]], v[t[k, 1]], v[t[k, 2]]
        emax = max(
            np.linalg.norm(p1 - p0), np.linalg.norm(p2 - p1), np.linalg.norm(p0 - p2)
        )
        n_div = max(1, int(np.ceil(emax / spacing)))
        # Grille barycentrique : (n+1)(n+2)/2 points, aretes <= emax/n <= spacing.
        pts = _barycentric_grid(p0, p1, p2, n_div)
        pts_all.append(pts)
        nrm_all.append(np.tile(normals[k], (pts.shape[0], 1)))
        fid_all.append(np.full(pts.shape[0], tf[k], dtype=np.int64))

    points = np.vstack(pts_all)
    nrm = np.vstack(nrm_all)
    fids = np.concatenate(fid_all)

    # Deduplication sur grille : les sommets partages entre triangles voisins
    # apparaissent plusieurs fois et n'apportent rien au test de collision.
    key = np.round(points / (spacing * 0.25)).astype(np.int64)
    _, keep = np.unique(key, axis=0, return_index=True)
    keep.sort()

    # La deduplication deplace un point d'au plus un demi-pas de grille ;
    # on l'integre au majorant d'espacement plutot que de l'ignorer.
    return SampledSurface(
        points=points[keep],
        normals=nrm[keep],
        face_ids=fids[keep],
        max_spacing=float(spacing + 0.125 * spacing),
    )


def _barycentric_grid(p0: np.ndarray, p1: np.ndarray, p2: np.ndarray, n: int) -> np.ndarray:
    """Points d'une grille barycentrique reguliere d'ordre ``n`` sur un triangle."""
    i, j = np.meshgrid(np.arange(n + 1), np.arange(n + 1), indexing="ij")
    m = (i + j) <= n
    a = i[m] / n
    b = j[m] / n
    c = 1.0 - a - b
    return a[:, None] * p0 + b[:, None] * p1 + c[:, None] * p2


def sample_face(
    shape: TopoDS_Shape, face_index: int, spacing: float = 1.0
) -> SampledSurface:
    """Echantillonne UNE face, avec la meme garantie d'espacement.

    Le solveur d'accessibilite travaille face par face : c'est l'unite naturelle
    de la strategie (une face = une famille de normales, donc une famille
    d'orientations candidates).
    """
    full = sample_surface(shape, spacing=spacing)
    m = full.face_ids == face_index
    if not np.any(m):
        raise StepLoadError(f"face {face_index} absente ou non maillee")
    return SampledSurface(
        points=full.points[m], normals=full.normals[m],
        face_ids=full.face_ids[m], max_spacing=full.max_spacing,
    )


def order_points_as_path(points: np.ndarray, start: np.ndarray | None = None) -> np.ndarray:
    """Ordonne un nuage en une passe continue (plus proche voisin glouton).

    Substitut volontairement simple, suffisant pour eprouver l'orientation
    solver a ce jalon. La vraie generation de passes (zigzag, spirale, pas
    transversal constant) releve de ``subtractive_slicer`` et n'est PAS
    implementee ici : melanger les deux masquerait quel module est en cause
    quand une trajectoire est mauvaise.
    """
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    n = len(pts)
    if n <= 1:
        return np.arange(n)
    cur = int(np.argmin(np.linalg.norm(pts - (start if start is not None else pts.min(axis=0)),
                                       axis=1)))
    order = [cur]
    remaining = np.ones(n, dtype=bool)
    remaining[cur] = False
    for _ in range(n - 1):
        d = np.linalg.norm(pts - pts[cur], axis=1)
        d[~remaining] = np.inf
        cur = int(np.argmin(d))
        remaining[cur] = False
        order.append(cur)
    return np.array(order, dtype=np.int64)
