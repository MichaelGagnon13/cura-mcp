"""Cœur du MCP Cura : lance CuraEngine (extrait d'AppImage) en headless.

Défi résolu : CuraEngine standalone a besoin (1) de l'interpréteur ld-linux bundlé,
(2) de toutes les libs de l'AppImage, (3) d'un jeu COMPLET de réglages aplatis
(fdmprinter + fdmextruder + overrides), sinon il crashe sur un réglage manquant.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

# Racine de Cura extraite (voir README pour l'auto-détection communautaire)
CURA_ROOT = Path(os.environ.get("CURA_ROOT", str(Path.home() / "opt/cura/squashfs-root")))
ENGINE = CURA_ROOT / "CuraEngine"
LD = CURA_ROOT / "runtime/compat/lib64/ld-linux-x86-64.so.2"
DEFS = CURA_ROOT / "share/cura/resources/definitions"
FDMPRINTER = DEFS / "fdmprinter.def.json"
FDMEXTRUDER = DEFS / "fdmextruder.def.json"


def _lib_path() -> str:
    """Tous les dossiers contenant des .so sous la racine Cura (mis en cache)."""
    cache = CURA_ROOT / ".libpath"
    if cache.exists():
        return cache.read_text().strip()
    dirs = {str(p.parent) for p in CURA_ROOT.rglob("*.so*") if p.is_file()}
    dirs.add(str(CURA_ROOT))  # libArcus.so est à la racine
    val = os.pathsep.join(sorted(dirs))
    try:
        cache.write_text(val)
    except OSError:
        pass
    return val


def _flatten(node: dict, out: dict) -> None:
    """Parcourt l'arbre 'settings' de Cura, extrait default_value de chaque feuille."""
    for key, spec in node.items():
        if not isinstance(spec, dict):
            continue
        if "default_value" in spec:
            out[key] = spec["default_value"]
        if "children" in spec:
            _flatten(spec["children"], out)


def base_settings() -> dict:
    """Jeu complet de réglages par défaut (fdmprinter + fdmextruder)."""
    settings: dict = {}
    for deffile in (FDMPRINTER, FDMEXTRUDER):
        data = json.loads(deffile.read_text())
        _flatten(data.get("settings", {}), settings)
    return settings


def _fmt(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, dict)):
        return json.dumps(v)
    return str(v)


def slice_stl(stl_paths: list[str], overrides: dict, out_gcode: str) -> dict:
    """Tranche un ou plusieurs STL avec CuraEngine. Retourne {gcode, time_s, filament_mm, filament_cm3}."""
    if not ENGINE.exists():
        raise RuntimeError(f"CuraEngine introuvable : {ENGINE} (extraire l'AppImage Cura)")
    settings = base_settings()
    settings.update(overrides)

    cmd = [str(LD), "--library-path", _lib_path(), str(ENGINE), "slice", "-v"]
    cmd += ["-j", str(FDMPRINTER)]
    # réglages globaux
    for k, v in settings.items():
        cmd += ["-s", f"{k}={_fmt(v)}"]
    # extrudeur 0 (mêmes réglages)
    cmd += ["-e0"]
    for k, v in settings.items():
        cmd += ["-s", f"{k}={_fmt(v)}"]
    # modèles
    for p in stl_paths:
        cmd += ["-l", str(p)]
    cmd += ["-o", str(out_gcode)]

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if not Path(out_gcode).exists() or Path(out_gcode).stat().st_size == 0:
        tail = (proc.stderr or proc.stdout)[-800:]
        raise RuntimeError(f"Découpe échouée. Fin du log :\n{tail}")

    stats = analyze_gcode(out_gcode)
    stats["gcode"] = str(out_gcode)
    stats["size_bytes"] = Path(out_gcode).stat().st_size
    return stats


def analyze_gcode(path: str) -> dict:
    """Calcule le VRAI temps + filament en simulant les mouvements du gcode.

    CuraEngine standalone n'écrit pas de stats fiables (;TIME est constant) — on les
    calcule nous-mêmes : temps = somme(distance/vitesse), filament = somme(extrusion E).
    Gère E relatif (M83, défaut Cura) et absolu (M82).
    """
    x = y = z = e = 0.0
    feed = 1800.0  # mm/min
    e_abs = False   # M83 relatif par défaut chez Cura
    e_total = 0.0
    t_total = 0.0
    for line in Path(path).read_text(errors="ignore").splitlines():
        line = line.split(";", 1)[0].strip()
        if not line:
            continue
        code = line.split()[0]
        if code == "M82":
            e_abs = True
            continue
        if code == "M83":
            e_abs = False
            continue
        if code == "G92":
            for tok in line.split()[1:]:
                if tok[:1] == "E":
                    try:
                        e = float(tok[1:])
                    except ValueError:
                        pass
            continue
        if code not in ("G0", "G1"):
            continue
        nx, ny, nz, ne = x, y, z, None
        for tok in line.split()[1:]:
            axis, val = tok[:1], tok[1:]
            try:
                f = float(val)
            except ValueError:
                continue
            if axis == "X":
                nx = f
            elif axis == "Y":
                ny = f
            elif axis == "Z":
                nz = f
            elif axis == "E":
                ne = f
            elif axis == "F":
                feed = f
        dist = ((nx - x) ** 2 + (ny - y) ** 2 + (nz - z) ** 2) ** 0.5
        if feed > 0:
            t_total += dist / (feed / 60.0)
        if ne is not None:
            if e_abs:
                de = ne - e
                e = ne
            else:
                de = ne
            if de > 0:
                e_total += de
        x, y, z = nx, ny, nz
    return {
        "time_s": round(t_total, 1),
        "time_h": round(t_total / 3600, 2),
        "filament_mm": round(e_total, 1),
        "filament_cm3": round(e_total * 3.14159 * (1.75 / 2) ** 2 / 1000, 2),
    }
