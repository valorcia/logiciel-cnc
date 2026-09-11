"""Generateur du corpus de 20 geometries STEP synthetiques.

Chaque geometrie cible UNE difficulte identifiee du moteur. Un corpus genere
plutot que collecte a trois proprietes qui comptent pour la non-regression :

  - **verite terrain connue** : volume, nombre de faces, axes de revolution sont
    calculables analytiquement, donc un test peut affirmer autre chose que
    "ca n'a pas plante" ;
  - **reproductible** : pas de fichier binaire opaque dans le depot, pas de
    licence tierce sur les modeles ;
  - **parametrable** : on peut resserrer une cote jusqu'a faire echouer le
    solveur, et donc mesurer sa limite au lieu de la supposer.

Usage :  python tools/make_corpus.py [dossier_sortie]
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepPrimAPI import (
    BRepPrimAPI_MakeBox,
    BRepPrimAPI_MakeCone,
    BRepPrimAPI_MakeCylinder,
    BRepPrimAPI_MakeSphere,
    BRepPrimAPI_MakeTorus,
)
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec

from xyzac.geometry_core import brep


def _box(dx, dy, dz, at=(0, 0, 0)):
    return BRepPrimAPI_MakeBox(gp_Pnt(*at), dx, dy, dz).Shape()


def _cyl(r, h, at=(0, 0, 0), axis=(0, 0, 1)):
    return BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*at), gp_Dir(*axis)), r, h).Shape()


def _cone(r1, r2, h, at=(0, 0, 0), axis=(0, 0, 1)):
    return BRepPrimAPI_MakeCone(gp_Ax2(gp_Pnt(*at), gp_Dir(*axis)), r1, r2, h).Shape()


def _sphere(r, at=(0, 0, 0)):
    return BRepPrimAPI_MakeSphere(gp_Pnt(*at), r).Shape()


def _torus(r1, r2, at=(0, 0, 0), axis=(0, 0, 1)):
    return BRepPrimAPI_MakeTorus(gp_Ax2(gp_Pnt(*at), gp_Dir(*axis)), r1, r2).Shape()


def _cut(a, b):
    return BRepAlgoAPI_Cut(a, b).Shape()


def _fuse(a, b):
    return BRepAlgoAPI_Fuse(a, b).Shape()


def _common(a, b):
    return BRepAlgoAPI_Common(a, b).Shape()


def _rot(shape, axis, deg, at=(0, 0, 0)):
    t = gp_Trsf()
    t.SetRotation(gp_Ax2(gp_Pnt(*at), gp_Dir(*axis)).Axis(), math.radians(deg))
    return BRepBuilderAPI_Transform(shape, t, True).Shape()


def _move(shape, v):
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(*v))
    return BRepBuilderAPI_Transform(shape, t, True).Shape()


@dataclass
class Case:
    """Une geometrie du corpus, avec ce qu'elle est censee eprouver."""

    cid: str
    name: str
    difficulty: str      # la difficulte VISEE : c'est le coeur du corpus
    expect: str          # comportement attendu du moteur
    builder: object


def _c01():
    return _box(60, 40, 20)


def _c02():
    """Poche debouchante : test de base du brut et de la profondeur."""
    return _cut(_box(60, 60, 25), _box(30, 30, 30, at=(15, 15, 5)))


def _c03():
    """Poche a parois inclinees : la normale varie continument sur une face."""
    return _cut(_box(60, 60, 25), _cone(20, 8, 20, at=(30, 30, 5)))


def _c04():
    """Rainure profonde et etroite : le porte-outil ne passe pas verticalement."""
    return _cut(_box(70, 40, 45), _box(8, 44, 35, at=(31, -2, 10)))


def _c05():
    """Deux ailettes hautes et rapprochees : acces lateral contraint des deux cotes."""
    b = _box(70, 50, 8)
    b = _fuse(b, _box(70, 6, 45, at=(0, 14, 8)))
    return _fuse(b, _box(70, 6, 45, at=(0, 30, 8)))


def _c06():
    """Contre-depouille franche : aucune direction verticale n'accede a la face."""
    b = _box(60, 50, 30)
    return _cut(b, _rot(_box(70, 30, 30, at=(-5, 0, 0)), (1, 0, 0), -25, at=(0, 25, 30)))


def _c07():
    """Gorge en T : contre-depouille des deux cotes, cas type de l'outil a col."""
    b = _box(60, 50, 35)
    b = _cut(b, _box(10, 54, 20, at=(25, -2, 15)))
    return _cut(b, _box(26, 54, 10, at=(17, -2, 5)))


def _c08():
    """Trou incline : axe non aligne sur Z, exige une indexation A/C."""
    b = _box(60, 60, 30)
    h = _rot(_cyl(6, 60, at=(30, 30, -5)), (1, 0, 0), 35, at=(30, 30, 15))
    return _cut(b, h)


def _c09():
    """Trous sur 4 faces : oblige a changer d'indexation, teste le sequencement."""
    b = _box(50, 50, 50)
    for at, ax in [((25, -5, 25), (0, 1, 0)), ((-5, 25, 25), (1, 0, 0)),
                   ((25, 55, 25), (0, -1, 0)), ((55, 25, 25), (-1, 0, 0))]:
        b = _cut(b, _cyl(5, 20, at=at, axis=ax))
    return b


def _c10():
    """Surface spherique convexe : normale variant sur 180 deg, cas 5 axes simultane."""
    return _fuse(_box(60, 60, 10), _sphere(22, at=(30, 30, 10)))


def _c11():
    """Cavite spherique : normales rentrantes, piege classique du drop-cutter."""
    return _cut(_box(60, 60, 30), _sphere(20, at=(30, 30, 30)))


def _c12():
    """Arbre etage coaxial a Z : la cible du turning_engine (revolution detectable)."""
    s = _cyl(20, 15)
    s = _fuse(s, _cyl(14, 20, at=(0, 0, 15)))
    s = _fuse(s, _cyl(9, 25, at=(0, 0, 35)))
    return _fuse(s, _cone(9, 4, 10, at=(0, 0, 60)))


def _c13():
    """Arbre a gorge torique : revolution + rayon concave, tournage de forme."""
    s = _cyl(18, 60)
    return _cut(s, _torus(18, 5, at=(0, 0, 30)))


def _c14():
    """Hybride : corps de revolution + meplats fraises. Cas du plan hybride."""
    s = _cyl(20, 50)
    s = _cut(s, _box(20, 44, 55, at=(14, -22, -2)))
    return _cut(s, _box(20, 44, 55, at=(-34, -22, -2)))


def _c15():
    """Revolution hors axe C : ne doit PAS etre proposee au tournage."""
    b = _box(70, 40, 40)
    return _fuse(b, _cyl(12, 30, at=(35, 20, 40), axis=(1, 0, 0)))


def _c16():
    """Paroi mince : rigidite critique, l'orientation doit privilegier la stabilite."""
    b = _box(60, 60, 40)
    return _cut(b, _box(50, 50, 38, at=(5, 5, 2)))


def _c17():
    """Face quasi horizontale : zone de singularite A -> 0, piege de l'axe C."""
    b = _box(60, 60, 20)
    return _fuse(b, _rot(_box(40, 40, 2, at=(10, 10, 20)), (0, 1, 0), 1.5, at=(30, 30, 20)))


def _c18():
    """Poche a fond bombe et congés : melange de types de surface."""
    b = _cut(_box(60, 60, 30), _cyl(18, 20, at=(30, 30, 12)))
    return _cut(b, _sphere(18, at=(30, 30, 12)))


def _c19():
    """Deux solides disjoints : robustesse a l'import (compound, pas un solide)."""
    return _fuse(_box(25, 25, 20), _box(25, 25, 20, at=(45, 0, 0)))


def _c20():
    """Detail tres petit devant la piece : eprouve les tolerances de tessellation."""
    b = _box(60, 60, 20)
    return _cut(b, _cyl(0.6, 10, at=(30, 30, 12)))


CASES: list[Case] = [
    Case("C01", "bloc_simple", "reference", "import et volume exacts ; 6 faces planes", _c01),
    Case("C02", "poche_droite", "poche fermee", "parois verticales accessibles a A=0", _c02),
    Case("C03", "poche_conique", "normale variable", "lead continu sur la face conique", _c03),
    Case("C04", "rainure_profonde", "collision porte-outil",
         "rejet COLLISION_HOLDER en vertical ; admissible en basculant", _c04),
    Case("C05", "ailettes_rapprochees", "acces bilateral contraint",
         "cones d'accessibilite etroits, 2 composantes attendues", _c05),
    Case("C06", "contre_depouille", "contre-depouille",
         "aucune direction a A=0 ; exige |A| > 0", _c06),
    Case("C07", "gorge_en_T", "contre-depouille double",
         "inaccessible sans outil a col ; doit proposer le remede", _c07),
    Case("C08", "trou_incline", "indexation 3+2",
         "un seul couple (A,C) couvre tout le trou", _c08),
    Case("C09", "trous_4_faces", "multi-indexation",
         "4 segments 3+2 distincts, aucun simultane", _c09),
    Case("C10", "dome_convexe", "5 axes simultane",
         "intersection des admissibles vide -> simultane justifie", _c10),
    Case("C11", "cavite_spherique", "normales rentrantes",
         "pas de gouge du corps d'outil sur la cavite", _c11),
    Case("C12", "arbre_etage", "revolution coaxiale C",
         "detection de revolution ; candidat tournage", _c12),
    Case("C13", "arbre_gorge_torique", "revolution + concave",
         "revolution detectee malgre le tore", _c13),
    Case("C14", "hybride_meplats", "hybride tournage/fraisage",
         "regions de revolution ET regions prismatiques separees", _c14),
    Case("C15", "revolution_hors_axe", "faux positif tournage",
         "revolution detectee mais REJETEE (axe non colineaire a C)", _c15),
    Case("C16", "paroi_mince", "rigidite",
         "l'orientation doit penaliser les grands porte-a-faux", _c16),
    Case("C17", "face_quasi_horizontale", "singularite A->0",
         "rejet SINGULARITY ou contournement ; pas de retournement C", _c17),
    Case("C18", "poche_fond_bombe", "types de surface melanges",
         "plan + cylindre + sphere sur la meme piece", _c18),
    Case("C19", "deux_solides", "topologie compound",
         "import sans erreur ; 2 solides comptes", _c19),
    Case("C20", "micro_detail", "tolerances",
         "le percage D1.2 survit a la tessellation", _c20),
]


def build_all(out_dir: Path) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for case in CASES:
        shape = case.builder()
        path = out_dir / f"{case.cid}_{case.name}.step"
        brep.save_step(shape, path)
        bb = brep.bounding_box(shape)
        faces = brep.face_info(shape)
        types: dict[str, int] = {}
        for f in faces:
            types[f.surface_type] = types.get(f.surface_type, 0) + 1
        manifest.append({
            "id": case.cid,
            "name": case.name,
            "difficulty": case.difficulty,
            "expect": case.expect,
            "file": path.name,
            "volume_mm3": round(brep.volume(shape), 4),
            "n_faces": len(faces),
            "n_solids": brep.count_solids(shape),
            "face_types": types,
            "bbox_lo": [round(v, 4) for v in bb.lo.tolist()],
            "bbox_hi": [round(v, 4) for v in bb.hi.tolist()],
        })
        print(f"  {case.cid}  {case.name:26s} V={manifest[-1]['volume_mm3']:12.2f} mm3  "
              f"faces={len(faces):3d}  {types}")
    return manifest


if __name__ == "__main__":
    import json
    import os

    out = Path(sys.argv[1] if len(sys.argv) > 1 else "tests/corpus/step")
    # OCCT est bavard sur stdout lors de l'ecriture STEP ; on garde la sortie lisible.
    print(f"Generation du corpus dans {out} ...")
    man = build_all(out)
    mpath = out.parent / "manifest.json"
    mpath.write_text(json.dumps(man, indent=2, ensure_ascii=False))
    print(f"\n{len(man)} geometries ecrites. Manifeste : {mpath}")
