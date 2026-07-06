"""Client du pont MCPBridge : parle au plugin qui tourne DANS Cura (GUI ouverte).

Permet de piloter Cura EN DIRECT (charger, arranger, régler, matériau, slice, screenshot)
pour que l'utilisateur VOIE tout se passer — comme le MCP Blender. Voir le plugin
~/.local/share/cura/5.13/plugins/MCPBridge/.
"""
from __future__ import annotations

import json
import socket

HOST = "127.0.0.1"
PORT = 9770


class CuraNotOpen(RuntimeError):
    pass


def send(cmd: str, timeout: float = 120.0, **args) -> dict:
    """Envoie une commande au plugin dans Cura et retourne le résultat (lève si Cura fermé)."""
    try:
        s = socket.create_connection((HOST, PORT), timeout=timeout)
    except OSError as e:
        raise CuraNotOpen(
            "Cura n'est pas ouvert (ou le plugin MCPBridge n'est pas chargé). "
            "Lance Cura, puis réessaie."
        ) from e
    try:
        s.sendall((json.dumps({"cmd": cmd, "args": args}) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    finally:
        s.close()
    resp = json.loads(buf.decode("utf-8", "ignore").strip())
    if not resp.get("ok"):
        raise RuntimeError("Cura: " + str(resp.get("error")))
    return resp.get("result", {})
