"""Serveur MCP pour UltiMaker Cura — permet à un agent IA de trancher en 3D headless.

Outils :
  - list_printers      : profils imprimante disponibles
  - get_profile        : réglages complets d'un profil (pour inspection/ajustement)
  - slice              : tranche un/des STL avec un profil + overrides → gcode + stats

Backend : CuraEngine (extrait de l'AppImage Cura). Voir engine.py.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastmcp import FastMCP

from . import engine

PROFILES_DIR = Path(__file__).parent / "profiles"

mcp = FastMCP(
    name="cura-slicer",
    instructions=(
        "Contrôle le slicer UltiMaker Cura (moteur CuraEngine) en headless. "
        "Utilise list_printers pour voir les profils, get_profile pour lire/ajuster les réglages, "
        "et slice pour produire un gcode prêt à imprimer + le temps d'impression estimé. "
        "Les chemins STL et de sortie sont des chemins de fichiers locaux absolus."
    ),
)


def _load_profiles() -> dict[str, dict]:
    out = {}
    for f in PROFILES_DIR.glob("*.json"):
        data = json.loads(f.read_text())
        out[f.stem] = data
    return out


@mcp.tool
def list_printers() -> list[dict]:
    """Liste les profils d'imprimante disponibles avec leurs specs clés.

    Retourne pour chaque profil : id, nom, fabricant, description, et volume d'impression.
    """
    res = []
    for pid, data in _load_profiles().items():
        s = data.get("settings", {})
        res.append({
            "id": pid,
            "name": data.get("name", pid),
            "manufacturer": data.get("manufacturer", ""),
            "description": data.get("description", ""),
            "build_volume_mm": [s.get("machine_width"), s.get("machine_depth"), s.get("machine_height")],
            "nozzle_mm": s.get("machine_nozzle_size"),
        })
    return res


@mcp.tool
def get_profile(printer_id: str) -> dict:
    """Retourne les réglages complets d'un profil d'imprimante (pour inspection ou ajustement).

    Args:
        printer_id: identifiant du profil (voir list_printers), ex. "creasee340".
    """
    profiles = _load_profiles()
    if printer_id not in profiles:
        raise ValueError(f"Profil inconnu : {printer_id}. Dispo : {list(profiles)}")
    return profiles[printer_id]


@mcp.tool
def slice(
    stl_paths: list[str],
    printer_id: str = "creasee340",
    output_gcode: str | None = None,
    settings: dict | None = None,
) -> dict:
    """Tranche un ou plusieurs fichiers STL en gcode prêt à imprimer, avec CuraEngine.

    Args:
        stl_paths: chemins absolus des STL à trancher (plusieurs = arrangés sur le plateau).
        printer_id: profil d'imprimante (voir list_printers). Défaut "creasee340".
        output_gcode: chemin de sortie du .gcode. Défaut = à côté du 1er STL.
        settings: overrides de réglages Cura (ex. {"layer_height":0.16,"infill_sparse_density":30,
                  "wall_line_count":5,"material_print_temperature":210,"adhesion_type":"raft"}).
                  Fusionnés PAR-DESSUS le profil imprimante.

    Retourne : gcode (chemin), time_h (heures estimées), time_s, filament_mm, size_bytes.
    """
    profiles = _load_profiles()
    if printer_id not in profiles:
        raise ValueError(f"Profil inconnu : {printer_id}. Dispo : {list(profiles)}")
    for p in stl_paths:
        if not Path(p).exists():
            raise FileNotFoundError(f"STL introuvable : {p}")

    overrides = dict(profiles[printer_id].get("settings", {}))
    if settings:
        overrides.update(settings)

    if output_gcode is None:
        first = Path(stl_paths[0])
        output_gcode = str(first.with_suffix("").parent / (first.stem + "_cura.gcode"))
    os.makedirs(Path(output_gcode).parent, exist_ok=True)

    return engine.slice_stl(stl_paths, overrides, output_gcode)


def main() -> None:
    mcp.run()  # stdio par défaut


if __name__ == "__main__":
    main()
