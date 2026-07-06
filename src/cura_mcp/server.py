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

from . import engine, project, bridge

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


@mcp.tool
def make_project(
    stl_paths: list[str],
    printer_id: str = "creasee340",
    output_3mf: str | None = None,
) -> dict:
    """Crée un PROJET Cura (.3mf) avec les pièces positionnées côte à côte sur le plateau.

    À OUVRIR dans Cura : l'utilisateur VOIT les pièces posées et peut vérifier les réglages,
    sans rien toucher. C'est le livrable de validation visuelle (contrairement au gcode).

    Args:
        stl_paths: chemins absolus des STL à placer sur le plateau.
        printer_id: profil imprimante (pour la taille du plateau). Défaut "creasee340".
        output_3mf: chemin de sortie .3mf. Défaut = à côté du 1er STL.
    """
    profiles = _load_profiles()
    if printer_id not in profiles:
        raise ValueError(f"Profil inconnu : {printer_id}. Dispo : {list(profiles)}")
    for p in stl_paths:
        if not Path(p).exists():
            raise FileNotFoundError(f"STL introuvable : {p}")
    s = profiles[printer_id].get("settings", {})
    bed = (float(s.get("machine_width", 220)), float(s.get("machine_depth", 220)))
    if output_3mf is None:
        first = Path(stl_paths[0])
        output_3mf = str(first.parent / (first.stem + "_projet.3mf"))
    return project.make_3mf(stl_paths, output_3mf, bed=bed)


# ================= OUTILS FRONTEND (pilotent Cura EN DIRECT via le plugin MCPBridge) =================
# Nécessitent Cura OUVERT avec le plugin MCPBridge. L'utilisateur VOIT tout se passer.

@mcp.tool
def cura_status() -> dict:
    """Vérifie si Cura est ouvert et pilotable en direct (plugin MCPBridge). Retourne version + imprimante active."""
    return bridge.send("ping")


@mcp.tool
def cura_load(stl_paths: list[str], clear_first: bool = True) -> dict:
    """Charge des modèles (STL/3MF) DANS la fenêtre Cura ouverte — l'utilisateur les voit apparaître.

    Args:
        stl_paths: chemins absolus à charger sur le plateau.
        clear_first: vider le plateau avant (défaut True).
    """
    if clear_first:
        bridge.send("clear")
    r = bridge.send("load", paths=stl_paths)
    bridge.send("arrange")
    return r


@mcp.tool
def cura_set(settings: dict) -> dict:
    """Applique des réglages Cura EN DIRECT (visibles dans le panneau de l'utilisateur).

    Args:
        settings: ex. {"layer_height":0.16,"wall_line_count":4,"infill_sparse_density":22,
                  "material_print_temperature":205,"adhesion_type":"brim"}.
    """
    return bridge.send("set", settings=settings)


@mcp.tool
def cura_get(keys: list[str]) -> dict:
    """Lit les valeurs actuelles de réglages dans Cura (pour vérifier avec l'utilisateur)."""
    return bridge.send("get", keys=keys)


@mcp.tool
def cura_slice(wait: bool = True, timeout_s: int = 240) -> dict:
    """Lance la découpe DANS Cura et ATTEND la fin (temps + matière fiables).

    Args:
        wait: si True (défaut), attend que la découpe soit terminée et retourne le temps/matière.
        timeout_s: attente max en secondes.
    """
    import time
    bridge.send("slice")
    if not wait:
        return {"slicing": True}
    deadline = time.time() + timeout_s
    stable = None
    stable_count = 0
    while time.time() < deadline:
        time.sleep(3)
        t = bridge.send("time")
        pt = t.get("print_time")
        if pt and pt != "00:00:00":
            if pt == stable:
                stable_count += 1
                if stable_count >= 2:  # 2 lectures identiques = découpe stabilisée
                    return {"done": True, **t}
            else:
                stable = pt
                stable_count = 0
    return {"done": False, "note": "timeout — découpe pas terminée à temps", "last": stable}


@mcp.tool
def cura_print_time() -> dict:
    """Retourne le temps d'impression estimé + matière, après une découpe dans Cura."""
    return bridge.send("time")


@mcp.tool
def cura_screenshot(path: str = "/tmp/cura_view.png", width: int = 700, height: int = 700) -> dict:
    """Capture le viewport de Cura (image isométrique) — pour VOIR l'état et le montrer à l'utilisateur.

    Retourne le chemin de l'image PNG écrite (à lire ensuite).
    """
    return bridge.send("screenshot", path=path, width=width, height=height)


@mcp.tool
def cura_arrange() -> dict:
    """Ré-arrange automatiquement les pièces sur le plateau (sans chevauchement)."""
    return bridge.send("arrange")


def main() -> None:
    mcp.run()  # stdio par défaut


if __name__ == "__main__":
    main()
