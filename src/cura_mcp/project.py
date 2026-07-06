"""Génère un PROJET 3MF propre pour Cura : plusieurs STL RÉPARÉS + positionnés sur le plateau.

Répare le maillage avec trimesh (la même bibliothèque que le plugin Mesh Tools de Cura) —
sinon un mesh non-manifold fait CALER CuraEngine et la découpe ne finit jamais.
Michael 2026-07-06 : travailler AVEC l'outil, réparer le mesh.
"""
from __future__ import annotations

from pathlib import Path

import trimesh
from trimesh import repair


def _repair(m: "trimesh.Trimesh") -> "trimesh.Trimesh":
    """Répare un maillage pour qu'il soit sain (watertight si possible)."""
    m.process(validate=True)
    m.merge_vertices()
    m.update_faces(m.nondegenerate_faces())
    m.update_faces(m.unique_faces())
    m.remove_infinite_values()
    m.remove_unreferenced_vertices()
    repair.fix_winding(m)
    repair.fix_inversion(m)
    repair.fix_normals(m)
    repair.fill_holes(m)
    return m


def make_3mf(stl_paths: list[str], out_3mf: str, bed=(340.0, 340.0), gap=20.0) -> dict:
    """Charge, RÉPARE et positionne les STL côte à côte (centrés, posés Z=0) → un .3mf propre."""
    meshes = []
    report = []
    for p in stl_paths:
        m = trimesh.load(p, force="mesh")
        m = _repair(m)
        meshes.append(m)
        report.append({"file": Path(p).name, "watertight": bool(m.is_watertight),
                       "faces": int(len(m.faces))})

    widths = [float(m.bounds[1][0] - m.bounds[0][0]) for m in meshes]
    total = sum(widths) + gap * (len(meshes) - 1)
    cursor = (bed[0] - total) / 2.0

    scene = trimesh.Scene()
    for i, (m, w) in enumerate(zip(meshes, widths)):
        b = m.bounds
        tx = cursor - b[0][0]
        ty = bed[1] / 2.0 - (b[0][1] + (b[1][1] - b[0][1]) / 2.0)
        tz = -b[0][2]
        cursor += w + gap
        m.apply_translation([tx, ty, tz])
        scene.add_geometry(m, node_name="part_%d" % (i + 1))

    Path(out_3mf).parent.mkdir(parents=True, exist_ok=True)
    scene.export(out_3mf)
    return {"project_3mf": out_3mf, "parts": len(meshes),
            "all_watertight": all(r["watertight"] for r in report),
            "meshes": report, "size_bytes": Path(out_3mf).stat().st_size}
