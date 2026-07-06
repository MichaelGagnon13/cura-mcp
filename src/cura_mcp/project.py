"""Génère un PROJET 3MF ouvrable dans Cura : plusieurs STL positionnés côte à côte sur le plateau.

But (workflow Michael) : Michael OUVRE le .3mf dans Cura → VOIT les pièces posées + peut vérifier
les réglages du profil actif → valide sans rien toucher. Pur-Python (aucune dépendance externe).
"""
from __future__ import annotations

import struct
import zipfile
from pathlib import Path


def _read_binary_stl(path: str):
    """Retourne (vertices [(x,y,z)...], triangles [(i,j,k)...]) depuis un STL binaire."""
    data = Path(path).read_bytes()
    n = struct.unpack_from("<I", data, 80)[0]
    verts: list[tuple] = []
    tris: list[tuple] = []
    idx: dict[tuple, int] = {}
    off = 84
    for _ in range(n):
        # 12 floats: normal(3) + 3 sommets(9), puis 2 octets attribut
        vals = struct.unpack_from("<12f", data, off)
        off += 50
        tri = []
        for v in ((vals[3], vals[4], vals[5]), (vals[6], vals[7], vals[8]), (vals[9], vals[10], vals[11])):
            key = (round(v[0], 4), round(v[1], 4), round(v[2], 4))
            i = idx.get(key)
            if i is None:
                i = len(verts)
                idx[key] = i
                verts.append(v)
            tri.append(i)
        tris.append(tuple(tri))
    return verts, tris


def make_3mf(stl_paths: list[str], out_3mf: str, bed=(340.0, 340.0), gap=20.0) -> dict:
    """Positionne les STL côte à côte (centrés Y, posés Z=0) et écrit UN .3mf multi-objets."""
    objects = []  # (verts, tris)
    widths = []
    for p in stl_paths:
        v, t = _read_binary_stl(p)
        objects.append((v, t))
        xs = [a[0] for a in v]
        widths.append(max(xs) - min(xs))

    total = sum(widths) + gap * (len(objects) - 1)
    cursor = (bed[0] - total) / 2.0  # départ X pour centrer l'ensemble

    obj_xml = []
    item_xml = []
    for oid, ((verts, tris), w) in enumerate(zip(objects, widths), start=1):
        xs = [a[0] for a in verts]; ys = [a[1] for a in verts]; zs = [a[2] for a in verts]
        # translation : bord gauche -> cursor ; centré en Y ; posé Z=0
        tx = cursor - min(xs)
        ty = bed[1] / 2.0 - (min(ys) + (max(ys) - min(ys)) / 2.0)
        tz = -min(zs)
        cursor += w + gap
        vtxt = "".join(f'<vertex x="{a[0]:.4f}" y="{a[1]:.4f}" z="{a[2]:.4f}"/>' for a in verts)
        ttxt = "".join(f'<triangle v1="{t[0]}" v2="{t[1]}" v3="{t[2]}"/>' for t in tris)
        obj_xml.append(f'<object id="{oid}" type="model"><mesh><vertices>{vtxt}</vertices><triangles>{ttxt}</triangles></mesh></object>')
        item_xml.append(f'<item objectid="{oid}" transform="1 0 0 0 1 0 0 0 1 {tx:.4f} {ty:.4f} {tz:.4f}"/>')

    model = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
        f'<resources>{"".join(obj_xml)}</resources>'
        f'<build>{"".join(item_xml)}</build></model>'
    )
    rels = ('<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rel0" Target="/3D/3dmodel.model" '
            'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    ctypes = ('<?xml version="1.0" encoding="UTF-8"?>'
              '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
              '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
              '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')

    Path(out_3mf).parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_3mf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ctypes)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)

    return {"project_3mf": out_3mf, "parts": len(objects), "bed_mm": list(bed),
            "size_bytes": Path(out_3mf).stat().st_size}
