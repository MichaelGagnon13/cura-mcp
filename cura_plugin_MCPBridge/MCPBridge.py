# MCP Bridge — plugin Cura qui pilote le GUI en direct depuis un serveur MCP.
# Construit par Claude (Opus 4.8) pour Michael Gagnon, sur l'API réelle de Cura/Uranium.
#
# Principe (comme l'addon Blender MCP) : un socket TCP écoute dans un thread ; chaque commande
# est exécutée sur le THREAD GUI via Application.callLater() (obligatoire pour toucher la scène Qt),
# le thread socket attend le résultat via un Event, puis renvoie du JSON.
import base64
import json
import os
import socket
import tempfile
import threading

from UM.Extension import Extension
from UM.Application import Application
from UM.Logger import Logger

HOST = "127.0.0.1"
PORT = 9770


class MCPBridge(Extension):
    def __init__(self):
        super().__init__()
        self.setMenuName("MCP Bridge")
        self.addMenuItem("Statut du pont", self._status_popup)
        self._server_thread = threading.Thread(target=self._serve, daemon=True)
        self._server_thread.start()
        Logger.log("i", "MCPBridge: socket démarré sur %s:%d" % (HOST, PORT))

    # ---- statut menu ----
    def _status_popup(self):
        Logger.log("i", "MCPBridge actif sur %s:%d" % (HOST, PORT))

    # ---- serveur socket (thread) ----
    def _serve(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind((HOST, PORT))
        except OSError as e:
            Logger.log("e", "MCPBridge: bind échoué: %s" % e)
            return
        srv.listen(5)
        while True:
            try:
                conn, _ = srv.accept()
                threading.Thread(target=self._handle, args=(conn,), daemon=True).start()
            except Exception as e:
                Logger.log("e", "MCPBridge accept: %s" % e)

    def _handle(self, conn):
        buf = b""
        with conn:
            while True:
                try:
                    chunk = conn.recv(65536)
                except OSError:
                    return
                if not chunk:
                    return
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    resp = self._dispatch(line.decode("utf-8", "ignore"))
                    try:
                        conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
                    except OSError:
                        return

    # ---- exécuter une fonction sur le thread GUI et récupérer le résultat ----
    def _on_main(self, fn, timeout=120):
        box = {}
        done = threading.Event()

        def wrapper():
            try:
                box["value"] = fn()
            except Exception as e:  # noqa
                import traceback
                box["error"] = "%s\n%s" % (e, traceback.format_exc())
            finally:
                done.set()

        Application.getInstance().callLater(wrapper)
        if not done.wait(timeout):
            raise RuntimeError("timeout thread GUI")
        if "error" in box:
            raise RuntimeError(box["error"])
        return box.get("value")

    def _dispatch(self, raw):
        try:
            msg = json.loads(raw)
            cmd = msg.get("cmd")
            args = msg.get("args", {}) or {}
        except Exception as e:
            return {"ok": False, "error": "json invalide: %s" % e}
        try:
            handler = getattr(self, "_cmd_" + cmd, None)
            if handler is None:
                return {"ok": False, "error": "commande inconnue: %s" % cmd}
            return {"ok": True, "result": self._on_main(lambda: handler(args))}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ================= COMMANDES (exécutées sur le thread GUI) =================
    def _cmd_ping(self, args):
        app = Application.getInstance()
        gs = app.getGlobalContainerStack()
        return {"pong": True, "cura": app.getVersion(),
                "printer": gs.getName() if gs else None}

    def _cmd_load(self, args):
        from PyQt6.QtCore import QUrl
        app = Application.getInstance()
        loaded = []
        for path in args.get("paths", []):
            if not os.path.exists(path):
                raise RuntimeError("introuvable: %s" % path)
            app.readLocalFile(QUrl.fromLocalFile(path))
            loaded.append(path)
        return {"loaded": loaded}

    def _cmd_clear(self, args):
        Application.getInstance().deleteAll()
        return {"cleared": True}

    def _cmd_set(self, args):
        # args: {"settings": {"layer_height":0.16, ...}}  -> écrit dans la pile globale (visible dans le GUI)
        app = Application.getInstance()
        gs = app.getGlobalContainerStack()
        if gs is None:
            raise RuntimeError("aucune imprimante active")
        applied = {}
        for k, v in (args.get("settings", {}) or {}).items():
            gs.setProperty(k, "value", v)
            applied[k] = gs.getProperty(k, "value")
        return {"applied": applied}

    def _cmd_get(self, args):
        app = Application.getInstance()
        gs = app.getGlobalContainerStack()
        if gs is None:
            raise RuntimeError("aucune imprimante active")
        return {k: gs.getProperty(k, "value") for k in args.get("keys", [])}

    def _cmd_screenshot(self, args):
        from cura.Snapshot import Snapshot
        w = int(args.get("width", 700))
        h = int(args.get("height", 700))
        img = Snapshot.isometricSnapshot(w, h)
        if img is None:
            raise RuntimeError("snapshot vide (rien sur le plateau ?)")
        out = args.get("path") or os.path.join(tempfile.gettempdir(), "cura_view.png")
        img.save(out)
        data = None
        if args.get("base64"):
            with open(out, "rb") as f:
                data = base64.b64encode(f.read()).decode("ascii")
        return {"path": out, "base64": data}

    def _cmd_arrange(self, args):
        app = Application.getInstance()
        try:
            app.arrangeAll()
        except Exception:
            from cura.Arranging.ArrangeObjectsJob import ArrangeObjectsJob
            from UM.Scene.Iterator.DepthFirstIterator import DepthFirstIterator
            root = app.getController().getScene().getRoot()
            nodes = [n for n in DepthFirstIterator(root) if n.callDecoration("isSliceable")]
            ArrangeObjectsJob(nodes, []).start()
        return {"arranged": True}

    def _cmd_slice(self, args):
        app = Application.getInstance()
        backend = app.getBackend()
        backend.forceSlice()
        return {"slicing": True}

    def _cmd_time(self, args):
        from UM.Qt.Duration import DurationFormat
        app = Application.getInstance()
        pi = app.getPrintInformation()
        dur = pi.currentPrintTime
        try:
            txt = dur.getDisplayString(DurationFormat.Format.ISO8601)
        except Exception:
            txt = str(dur)
        return {"print_time": txt,
                "material_grams": [round(w, 1) for w in (getattr(pi, "materialWeights", []) or [])],
                "material_meters": [round(l, 2) for l in (getattr(pi, "materialLengths", []) or [])]}

    def _cmd_objects(self, args):
        from UM.Scene.Iterator.DepthFirstIterator import DepthFirstIterator
        app = Application.getInstance()
        root = app.getController().getScene().getRoot()
        names = [n.getName() for n in DepthFirstIterator(root) if n.callDecoration("isSliceable")]
        return {"objects": names, "count": len(names)}
