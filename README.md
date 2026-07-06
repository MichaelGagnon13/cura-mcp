# cura-mcp

An **MCP server** that lets an AI agent (Claude, etc.) slice 3D models with **UltiMaker Cura**
(the `CuraEngine` backend) **headlessly** — no GUI, no clicking. Load STL files, pick a printer
profile, override any Cura setting, and get back a ready-to-print `.gcode` plus the estimated
print time.

Built because Cura has no official MCP and its engine is awkward to run standalone — this wraps it cleanly.

## What it exposes

| Tool | What it does |
|---|---|
| `list_printers` | List available printer profiles (id, build volume, nozzle). |
| `get_profile` | Return the full settings of a profile, to inspect or tweak. |
| `slice` | Slice one or more STL files with a profile + optional setting overrides → gcode + print time. |

Example: *"Slice `part.stl` on the Creasee 340 with 0.16 mm layers, 5 walls, 30% infill, and a raft."*
→ the agent calls `slice(stl_paths=["/…/part.stl"], printer_id="creasee340",
settings={"layer_height":0.16,"wall_line_count":5,"infill_sparse_density":30,"adhesion_type":"raft"})`.

## Why this was hard (and how it's solved)

`CuraEngine` from the Cura AppImage doesn't run standalone: it needs (1) the AppImage's bundled
`ld-linux` interpreter, (2) all of the AppImage's shared libraries, and (3) a **complete, flattened**
set of settings (`fdmprinter` + `fdmextruder` defaults + your overrides) — miss one and it aborts.
`engine.py` handles all three: it runs CuraEngine via the bundled linker with a full library path,
and flattens Cura's nested settings tree into the ~400 `-s key=value` flags CuraEngine expects.

## Requirements

- Linux, Python ≥ 3.10.
- **UltiMaker Cura AppImage** extracted to `~/opt/cura/squashfs-root` (or set `CURA_ROOT`):
  ```bash
  cd ~/opt/cura && /path/to/UltiMaker-Cura-*.AppImage --appimage-extract
  ```

## Install

```bash
git clone <this repo> && cd cura-mcp
python3 -m venv .venv && ./.venv/bin/pip install -e .
```

## Use with Claude Code

```bash
claude mcp add cura-slicer -- /ABS/PATH/cura-mcp/.venv/bin/python -m cura_mcp
```

Then restart your session and ask Claude to slice a model.

## Printer profiles

Profiles live in `src/cura_mcp/profiles/*.json` as `{name, manufacturer, description, settings:{…Cura settings…}}`.
Ships with **Creasee 340** (large CR-10-class bowden printer, CR-Touch ABL, quality profile tuned for a
slightly warped bed) and a generic 220 mm printer. Add your own by dropping a JSON file in that folder.

## Notes

- `filament_mm` may report 0 — a CuraEngine-standalone quirk; the print-time estimate is reliable.
- License AGPL-3.0 (CuraEngine is AGPL; this wrapper follows).
