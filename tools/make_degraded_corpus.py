"""Corpus de STEP volontairement DEGRADES.

Le corpus principal est genere par OCCT : cousu, oriente, aux tolerances par
defaut. Il ne prouve donc rien sur la robustesse a un fichier venu d'ailleurs.
Or c'est exactement ce que recevra le produit : un STEP exporte d'un autre
noyau, traduit, parfois dans la mauvaise unite.

Ces cas-la ne se collectent pas facilement (licences, confidentialite) : on les
FABRIQUE, ce qui a l'avantage de connaitre exactement le defaut injecte.

Usage :  python tools/make_degraded_corpus.py [dossier]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing, BRepBuilderAPI_Transform
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Trsf

from xyzac.geometry_core import brep

_to_face = getattr(TopoDS, "Face_s", None) or TopoDS.Face


def _open_shell():
    """Pave prive d'une face : shell ouvert, volume non calculable.

    Defaut le plus courant a l'import : une face perdue a la traduction. Le
    piege est qu'il reste parfaitement affichable — c'est le solveur qui
    decouvre que la matiere n'a pas d'interieur.
    """
    box = BRepPrimAPI_MakeBox(50.0, 40.0, 30.0).Shape()
    sew = BRepBuilderAPI_Sewing(1e-6)
    exp = TopExp_Explorer(box, TopAbs_FACE)
    i = 0
    while exp.More():
        if i != 0:  # on saute la premiere face
            sew.Add(_to_face(exp.Current()))
        exp.Next()
        i += 1
    sew.Perform()
    return sew.SewedShape()


def _scaled(factor: float):
    """Pave a l'echelle : simule une confusion d'unites."""
    box = BRepPrimAPI_MakeBox(50.0, 40.0, 30.0).Shape()
    t = gp_Trsf()
    t.SetScaleFactor(factor)
    return BRepBuilderAPI_Transform(box, t, True).Shape()


CASES = [
    ("D01", "shell_ouvert", "face manquante : volume non calculable",
     "diagnostic doit signaler volume nul et topologie suspecte", _open_shell),
    ("D02", "unites_pouces", "piece modelisee en pouces, lue en mm (x1/25,4)",
     "diagnostic doit signaler un encombrement suspect (< 2 mm)",
     lambda: _scaled(1.0 / 25.4)),
    ("D03", "trop_grande", "piece de 2,5 m : hors volume d'une machine maker",
     "diagnostic doit signaler un encombrement hors machine",
     lambda: _scaled(50.0)),
]


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "tests/corpus/step_degraded")
    out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for cid, name, defect, expect, builder in CASES:
        shape = builder()
        path = out / f"{cid}_{name}.step"
        brep.save_step(shape, path)
        manifest.append({"id": cid, "name": name, "defect": defect,
                         "expect": expect, "file": path.name})
        print(f"  {cid}  {name:18s} {defect}")
    (out.parent / "manifest_degraded.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"\n{len(manifest)} fichiers degrades ecrits dans {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
