"""Rendu hors-ligne (matplotlib/Agg) : machine virtuelle, outil complet, champs
d'orientation.

Choix assume a ce jalon : pas de visualiseur interactif. Un rendu PNG
deterministe est ce dont on a besoin maintenant, parce qu'il sert AUSSI de
test de non-regression visuel (une image qui change signale un changement de
comportement du solveur). L'UI interactive viendra quand les solveurs seront
stables, pas avant.

La palette encode le MOTIF de rejet, pas seulement le rejet : c'est ce qui
transforme une image en diagnostic.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # obligatoire : pas de serveur X sur la cible embarquee

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402

from ..accessibility_solver.solver import AccessibilityMap, RejectReason  # noqa: E402
from ..geometry_core.types import orthonormal_basis  # noqa: E402
from ..tool_model.assembly import SegmentRole, ToolAssembly  # noqa: E402

REASON_COLOR = {
    RejectReason.OK: "#1a9850",
    RejectReason.BACK_FACING: "#d9d9d9",
    RejectReason.LEAD_LIMIT: "#fee08b",
    RejectReason.AXIS_LIMITS: "#8c510a",
    RejectReason.SINGULARITY: "#c51b7d",
    RejectReason.COLLISION_CUTTING: "#d73027",
    RejectReason.COLLISION_NECK: "#f46d43",
    RejectReason.COLLISION_SHANK: "#fdae61",
    RejectReason.COLLISION_HOLDER: "#4575b4",
    RejectReason.COLLISION_SPINDLE: "#313695",
}

ROLE_COLOR = {
    SegmentRole.CUTTING: "#d73027",
    SegmentRole.FLUTE: "#f46d43",
    SegmentRole.NECK: "#fdae61",
    SegmentRole.SHANK: "#74add1",
    SegmentRole.HOLDER: "#4575b4",
    SegmentRole.SPINDLE_NOSE: "#313695",
}


def _frustum_mesh(z0, z1, r0, r1, n=24):
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    c, s = np.cos(t), np.sin(t)
    lo = np.stack([r0 * c, r0 * s, np.full(n, z0)], axis=1)
    hi = np.stack([r1 * c, r1 * s, np.full(n, z1)], axis=1)
    quads = [[lo[i], lo[(i + 1) % n], hi[(i + 1) % n], hi[i]] for i in range(n)]
    quads.append(list(lo))
    quads.append(list(hi[::-1]))
    return quads


def draw_tool(ax, tool: ToolAssembly, tcp: np.ndarray, axis: np.ndarray,
              alpha: float = 0.85, n: int = 20) -> None:
    """Dessine l'outil COMPLET place. Chaque troncon garde sa couleur de role.

    C'est le point qui distingue visuellement notre moteur d'un CAM 3 axes :
    on voit le porte-outil et le nez de broche, donc on voit *pourquoi* une
    orientation est refusee.
    """
    u, v, d = orthonormal_basis(axis)
    R = np.stack([u, v, d], axis=1)
    for seg in tool.segments:
        for quad in _frustum_mesh(seg.z_start, seg.z_end, seg.r_start, seg.r_end, n):
            poly = np.array(quad) @ R.T + tcp
            ax.add_collection3d(Poly3DCollection(
                [poly], facecolor=ROLE_COLOR[seg.role], edgecolor="none", alpha=alpha))


def draw_box(ax, lo, hi, color="#999999", alpha=0.18, edge="#555555") -> None:
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    c = np.array([[lo[0], lo[1], lo[2]], [hi[0], lo[1], lo[2]], [hi[0], hi[1], lo[2]],
                  [lo[0], hi[1], lo[2]], [lo[0], lo[1], hi[2]], [hi[0], lo[1], hi[2]],
                  [hi[0], hi[1], hi[2]], [lo[0], hi[1], hi[2]]])
    faces = [[0, 1, 2, 3], [4, 5, 6, 7], [0, 1, 5, 4],
             [2, 3, 7, 6], [1, 2, 6, 5], [0, 3, 7, 4]]
    ax.add_collection3d(Poly3DCollection(
        [c[f] for f in faces], facecolor=color, edgecolor=edge, alpha=alpha, linewidths=0.5))


def draw_cylinder(ax, base, axis, radius, height, color="#777777", alpha=0.25, n=28) -> None:
    u, v, d = orthonormal_basis(axis)
    R = np.stack([u, v, d], axis=1)
    for quad in _frustum_mesh(0.0, height, radius, radius, n):
        ax.add_collection3d(Poly3DCollection(
            [np.array(quad) @ R.T + np.asarray(base, float)],
            facecolor=color, edgecolor="none", alpha=alpha))


def _equal_aspect(ax, pts: np.ndarray) -> None:
    pts = np.asarray(pts).reshape(-1, 3)
    c = pts.mean(axis=0)
    r = max(float(np.abs(pts - c).max()), 1.0)
    ax.set_xlim(c[0] - r, c[0] + r)
    ax.set_ylim(c[1] - r, c[1] + r)
    ax.set_zlim(c[2] - r, c[2] + r)
    ax.set_box_aspect((1, 1, 1))


def render_scene(scene, tcp=None, axis=None, out_path="out/scene.png",
                 title="Digital twin — brut, piece, bridages, outil complet",
                 elev=22, azim=-58) -> Path:
    """Vue d'ensemble : machine virtuelle + brut + piece + bridages + outil."""
    fig = plt.figure(figsize=(11, 8.5))
    ax = fig.add_subplot(111, projection="3d")

    st = scene.setup.stock
    if st.lo is not None:
        draw_box(ax, st.lo, st.hi, color="#b8c6d6", alpha=0.12, edge="#7b8fa3")

    p = scene.part_samples.points
    step = max(1, len(p) // 4000)
    ax.scatter(p[::step, 0], p[::step, 1], p[::step, 2], s=1.2, c="#2b5d8a",
               alpha=0.5, label="piece (echantillonnee)")

    for f in scene.setup.fixtures:
        if f.lo is not None:
            draw_box(ax, f.lo, f.hi, color="#8c510a", alpha=0.32, edge="#5a3406")

    # Plateau C du modele machine, a l'origine piece (digital twin simplifie).
    for cv in scene.setup.machine.collision_volumes:
        if cv.kind == "cylinder" and cv.frame == "table_C":
            draw_cylinder(ax, cv.base, cv.axis, cv.radius, cv.height,
                          color="#555555", alpha=0.18)

    if tcp is not None and axis is not None:
        draw_tool(ax, scene.tool, np.asarray(tcp), np.asarray(axis))
        ax.scatter(*np.asarray(tcp), s=40, c="#000000", marker="x")

    allpts = [p]
    if st.lo is not None:
        allpts.append(np.array([st.lo, st.hi]))
    if tcp is not None and axis is not None:
        allpts.append(np.array([tcp, np.asarray(tcp) + np.asarray(axis) * scene.tool.total_length]))
    _equal_aspect(ax, np.vstack(allpts))

    ax.set_xlabel("X piece (mm)"); ax.set_ylabel("Y piece (mm)"); ax.set_zlabel("Z piece (mm)")
    ax.set_title(title, fontsize=11)
    ax.view_init(elev=elev, azim=azim)

    handles = [plt.Line2D([], [], marker="s", ls="", color=ROLE_COLOR[r], label=r.value)
               for r in SegmentRole if any(s.role is r for s in scene.tool.segments)]
    handles.append(plt.Line2D([], [], marker="s", ls="", color="#b8c6d6", label="brut"))
    if scene.setup.fixtures:
        handles.append(plt.Line2D([], [], marker="s", ls="", color="#8c510a", label="bridage"))
    ax.legend(handles=handles, loc="upper left", fontsize=8, framealpha=0.9)

    return _save(fig, out_path)


def render_orientation_sphere(amap: AccessibilityMap, out_path="out/orientations.png",
                              title=None) -> Path:
    """Carte des orientations candidates et rejetees, projetee et en 3D.

    Trois panneaux, parce que trois questions differentes :
      - QUOI : quelles directions passent, et lesquelles echouent, par motif ;
      - COMBIEN : la marge de degagement des directions admissibles ;
      - OU : la meme information dans l'espace (A, C) de la machine, seul
        espace ou la continuite de la sequence se lit.
    """
    fig = plt.figure(figsize=(16, 5.4))
    n = amap.normal

    # -- panneau 1 : sphere 3D par motif
    ax = fig.add_subplot(131, projection="3d")
    for r in RejectReason:
        m = amap.reason == r
        if not np.any(m):
            continue
        d = amap.directions[m]
        ax.scatter(d[:, 0], d[:, 1], d[:, 2], s=14 if r is RejectReason.OK else 7,
                   c=REASON_COLOR[r], label=f"{r.name} ({int(m.sum())})",
                   alpha=0.95 if r is RejectReason.OK else 0.55,
                   depthshade=False)
    ax.quiver(0, 0, 0, *n, color="k", lw=2.2, arrow_length_ratio=0.14)
    ax.text(*(n * 1.18), "normale", fontsize=8)
    b = amap.best()
    if b is not None:
        d = amap.directions[b]
        ax.quiver(0, 0, 0, *d, color="#1a9850", lw=3.0, arrow_length_ratio=0.14)
    ax.set_box_aspect((1, 1, 1))
    for lim in (ax.set_xlim, ax.set_ylim, ax.set_zlim):
        lim(-1.05, 1.05)
    ax.set_xlabel("X"); ax.set_ylabel("Y"); ax.set_zlabel("Z")
    ax.set_title("Directions candidates (repere piece)", fontsize=10)
    ax.legend(fontsize=6.2, loc="upper left", framealpha=0.9)
    ax.view_init(elev=24, azim=-62)

    # -- panneau 2 : marge de degagement
    ax2 = fig.add_subplot(132, projection="3d")
    ok = amap.feasible
    if np.any(ok):
        d = amap.directions[ok]
        mg = np.clip(amap.margin[ok], 0, np.percentile(amap.margin[ok], 97) + 1e-6)
        sc = ax2.scatter(d[:, 0], d[:, 1], d[:, 2], c=mg, s=22, cmap="viridis",
                         depthshade=False)
        fig.colorbar(sc, ax=ax2, shrink=0.62, label="marge (mm)")
    bad = ~ok
    if np.any(bad):
        d = amap.directions[bad]
        ax2.scatter(d[:, 0], d[:, 1], d[:, 2], c="#e0e0e0", s=4, alpha=0.35,
                    depthshade=False)
    ax2.set_box_aspect((1, 1, 1))
    for lim in (ax2.set_xlim, ax2.set_ylim, ax2.set_zlim):
        lim(-1.05, 1.05)
    ax2.set_title("Marge de degagement des directions admissibles", fontsize=10)
    ax2.view_init(elev=24, azim=-62)

    # -- panneau 3 : espace machine (A, C)
    ax3 = fig.add_subplot(133)
    for r in RejectReason:
        m = (amap.reason == r) & np.isfinite(amap.a_deg)
        if not np.any(m):
            continue
        ax3.scatter(amap.c_deg[m], amap.a_deg[m], s=20 if r is RejectReason.OK else 9,
                    c=REASON_COLOR[r], alpha=0.9 if r is RejectReason.OK else 0.45,
                    label=r.name if r is RejectReason.OK else None)
    mach = None
    try:
        mach = amap  # bornes tracees par l'appelant si besoin
    except Exception:
        pass
    if b is not None and np.isfinite(amap.a_deg[b]):
        ax3.scatter([amap.c_deg[b]], [amap.a_deg[b]], s=140, facecolor="none",
                    edgecolor="#1a9850", lw=2.2, label="retenue")
    ax3.axhline(0.0, color="#c51b7d", ls="--", lw=1.1)
    ax3.text(ax3.get_xlim()[0], 0.0, " A=0 : singularite de l'axe C",
             color="#c51b7d", fontsize=7.5, va="bottom")
    ax3.set_xlabel("C (deg)"); ax3.set_ylabel("A (deg)")
    ax3.set_title("Espace machine (A, C)", fontsize=10)
    ax3.grid(alpha=0.25)
    ax3.legend(fontsize=7.5, loc="best")

    fig.suptitle(title or f"Accessibilite en {np.round(amap.point, 2)} — "
                          f"{amap.n_feasible}/{len(amap.directions)} directions admissibles",
                 fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    return _save(fig, out_path)


def render_tool_profile(tool: ToolAssembly, out_path="out/tool.png") -> Path:
    """Profil de l'outil complet, en coupe. Ce que le solveur voit reellement."""
    fig, ax = plt.subplots(figsize=(4.6, 8.2))
    for s in tool.segments:
        ax.fill_betweenx([s.z_start, s.z_end], [-s.r_start, -s.r_end], [s.r_start, s.r_end],
                         color=ROLE_COLOR[s.role], alpha=0.85, lw=0)
        ax.text(max(s.r_start, s.r_end) + 1.6, 0.5 * (s.z_start + s.z_end),
                f"{s.role.value}\n{s.label}", fontsize=6.6, va="center")
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xlabel("rayon (mm)"); ax.set_ylabel("z depuis le bec (mm)")
    ax.set_title(f"{tool.tool_id} — outil complet modelise\n"
                 f"D{tool.diameter}, jauge {tool.gauge_length} mm", fontsize=10)
    ax.set_xlim(-tool.max_radius * 2.4, tool.max_radius * 2.4)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    return _save(fig, out_path)


def render_ac_sequence(plan, out_path="out/ac_sequence.png") -> Path:
    """Sequence A/C retenue, avec les segments 3+2 et simultanes en fond.

    Le lecteur doit pouvoir verifier d'un coup d'oeil les deux proprietes qui
    comptent : pas de saut de C, et A qui ne traverse pas la bande de
    singularite.
    """
    fig, axes = plt.subplots(3, 1, figsize=(12, 8.4), sharex=True)
    t = np.arange(plan.n_points)

    for seg in plan.segments:
        axes[0].axvspan(seg.start, seg.end,
                        color="#1a9850" if seg.mode == "3+2" else "#fdae61",
                        alpha=0.16, lw=0)

    axes[0].plot(t, plan.a_deg, "-", lw=1.6, color="#2b5d8a", label="A")
    axes[0].plot(t, plan.c_deg, "-", lw=1.6, color="#c51b7d", label="C (deroule)")
    axes[0].axhline(0, color="#c51b7d", ls="--", lw=0.9, alpha=0.6)
    axes[0].set_ylabel("angle (deg)")
    axes[0].legend(fontsize=8, loc="best")
    axes[0].grid(alpha=0.25)
    axes[0].set_title(
        f"Sequence A/C — couverture 3+2 : {plan.indexed_fraction * 100:.1f} %  "
        f"(vert = indexe, orange = simultane)", fontsize=11)

    da = np.abs(np.diff(plan.a_deg, prepend=plan.a_deg[0]))
    dc = np.abs(np.diff(plan.c_deg, prepend=plan.c_deg[0]))
    axes[1].plot(t, da, lw=1.2, color="#2b5d8a", label="|dA| par point")
    axes[1].plot(t, dc, lw=1.2, color="#c51b7d", label="|dC| par point")
    axes[1].set_ylabel("increment (deg)")
    axes[1].legend(fontsize=8); axes[1].grid(alpha=0.25)

    axes[2].plot(t, plan.margin, lw=1.4, color="#1a9850")
    axes[2].axhline(0, color="#d73027", ls="--", lw=1.0)
    axes[2].set_ylabel("marge (mm)"); axes[2].set_xlabel("index du point de contact")
    axes[2].grid(alpha=0.25)

    fig.tight_layout()
    return _save(fig, out_path)


def _save(fig, out_path) -> Path:
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(p, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return p
