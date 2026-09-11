"""Digital twin : assemblage de la scene complete, sans aucune machine reelle.

C'est le premier jalon impose par la methode : tout doit etre eprouvable hors
machine. La scene reunit piece, brut, bridages, outil et machine dans un seul
objet, et produit le ``ObstacleField`` que consomment les solveurs.

Ce module ne genere AUCUNE commande. Il n'a pas de dependance vers
``linuxcnc_gateway`` et n'en aura jamais : la frontiere de securite (ADR-001 /
D9) est aussi une frontiere de dependances, verifiable par un test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..collision_engine.field import ObstacleField
from ..geometry_core import brep
from ..machine_model.setup import Setup
from ..tool_model.assembly import ToolAssembly


@dataclass
class Scene:
    """Scene complete prete pour les solveurs."""

    setup: Setup
    part_shape: object                 # TopoDS_Shape
    part_samples: brep.SampledSurface
    obstacles: ObstacleField
    sample_spacing: float
    stats: dict = field(default_factory=dict)

    @property
    def tool(self) -> ToolAssembly:
        return self.setup.tools[0]

    def face_points(self, face_index: int, spacing: float | None = None):
        """Points de contact + normales sur une face donnee."""
        s = brep.sample_face(self.part_shape, face_index,
                             spacing=spacing or self.sample_spacing)
        return s.points, s.normals

    def describe(self) -> str:
        bb = brep.bounding_box(self.part_shape)
        return "\n".join([
            f"Scene « {self.setup.setup_id} »",
            f"  piece      : {Path(self.setup.part_step_path).name}  "
            f"V={brep.volume(self.part_shape):.1f} mm3  "
            f"bbox {np.round(bb.lo,1)} -> {np.round(bb.hi,1)}",
            f"  brut       : {self.setup.stock.kind.value} "
            f"{np.round(self.setup.stock.bbox.size,1)} mm  "
            f"({self.setup.stock.material})",
            f"  bridages   : {len(self.setup.fixtures)}",
            f"  outil      : {self.tool.tool_id} D{self.tool.diameter} "
            f"jauge {self.tool.gauge_length} mm",
            f"  machine    : {self.setup.machine.describe_limits()}",
            f"  obstacles  : {len(self.obstacles)} points "
            f"(pas {self.sample_spacing} mm, inflation "
            f"{self.obstacles.inflation.min():.2f}..{self.obstacles.inflation.max():.2f} mm)",
            f"  hash setup : {self.setup.setup_hash()[:16]}",
        ])


def build_scene(
    setup: Setup,
    *,
    sample_spacing: float = 1.5,
    stock_spacing: float = 3.0,
    fixture_spacing: float = 3.0,
    safety_clearance: float = 0.5,
    include_stock: bool = True,
) -> Scene:
    """Assemble la scene et le champ d'obstacles a partir d'un ``Setup``.

    ``include_stock=False`` modelise l'etat « brut deja enleve autour de la
    zone » — une hypothese OPTIMISTE, a n'utiliser que pour des passes de
    finition dont on a deja verifie qu'elles suivent une ebauche. Par defaut le
    brut est INTACT, ce qui est l'hypothese la plus conservative.
    """
    shape = brep.load_step(setup.part_step_path)
    part = brep.sample_surface(shape, spacing=sample_spacing)

    stock_pts = None
    if include_stock:
        stock_pts, _ = setup.stock.surface_samples(stock_spacing)

    fix_pts = None
    if setup.fixtures:
        fp = [f.surface_samples(fixture_spacing)[0] for f in setup.fixtures]
        fix_pts = np.vstack(fp)

    field_ = ObstacleField.build(
        part.points,
        part_spacing=part.max_spacing,
        finish_allowance=setup.stock.finish_allowance_mm,
        stock_points=stock_pts,
        stock_spacing=stock_spacing,
        fixture_points=fix_pts,
        fixture_spacing=fixture_spacing,
        fixture_keepout=max((f.keepout_mm for f in setup.fixtures), default=0.0),
        safety_clearance=safety_clearance,
    )

    return Scene(
        setup=setup, part_shape=shape, part_samples=part, obstacles=field_,
        sample_spacing=sample_spacing,
        stats={
            "n_part_samples": len(part),
            "n_stock_samples": 0 if stock_pts is None else len(stock_pts),
            "n_fixture_samples": 0 if fix_pts is None else len(fix_pts),
            "stock_intact": include_stock,
        },
    )
