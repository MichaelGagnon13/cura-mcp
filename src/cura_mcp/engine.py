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

    txt = Path(out_gcode).read_text(errors="ignore")[:4000]
    time_s = 0.0
    m = re.search(r";TIME:(\d+)", txt)
    if m:
        time_s = float(m.group(1))
    fil_mm = 0.0
    m = re.search(r";Filament used:\s*([\d.]+)m", txt)
    if m:
        fil_mm = float(m.group(1)) * 1000
    return {
        "gcode": str(out_gcode),
        "time_s": time_s,
        "time_h": round(time_s / 3600, 2),
        "filament_mm": round(fil_mm, 1),
        "size_bytes": Path(out_gcode).stat().st_size,
    }
