"""HTTP server for the Selective Hierarchical Memory NPC simulator.

Hardening applied in v0.2.1 relative to v0.2
--------------------------------------------
* ``_serve_file`` is path-contained: ``/static/../../etc/passwd`` can no longer
  escape the static directory (previously returned HTTP 200 with file contents).
* The simulation is created by the caller / server factory instead of at import
  time, so importing this module has no side effects.
* CORS is opt-in (``--cors`` / ``NPC_CORS=1``) instead of always ``*``. The
  bundled UI is same-origin and needs no CORS headers; leaving them on means any
  web page the user visits could drive the simulation from their browser.
* Host/port are configurable (``--host`` / ``--port``, ``NPC_HOST`` / ``NPC_PORT``).
  Defaults to 127.0.0.1 so an unconfigured server is not exposed to the network.
* ``ThreadingHTTPServer`` + an unlocked shared SQLite handle is only safe because
  ``SQLiteMemoryStore`` now serialises access with an internal lock.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Type
from urllib.parse import unquote, urlparse

# Allow `python src/npc_memory_project/web/server.py` without an install step.
_src_dir = Path(__file__).resolve().parent.parent.parent
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from npc_memory_project.core.models import GameEvent  # noqa: E402
from npc_memory_project.simulation.town_simulation import TownSimulation  # noqa: E402

STATIC_DIR = (Path(__file__).resolve().parent / "static").resolve()


class GameWebHandler(BaseHTTPRequestHandler):
    """Request handler for the simulator UI and JSON API.

    ``simulation`` and ``static_dir`` are bound per-server by ``create_server``;
    subclassing keeps ``BaseHTTPRequestHandler``'s class-based dispatch intact.
    """

    simulation: TownSimulation
    static_dir: Path = STATIC_DIR
    allow_cors: bool = False
    server_version = "SHM-NPC/0.2.1"

    # ---------------------------------------------------------------- helpers
    def _cors_headers(self) -> None:
        if not self.allow_cors:
            return
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Dict[str, Any]:
        try:
            content_len = int(self.headers.get("Content-Length", 0) or 0)
        except (TypeError, ValueError):
            return {}
        if content_len <= 0:
            return {}
        raw = self.rfile.read(content_len).decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def log_message(self, fmt: str, *args: Any) -> None:  # keep the console tidy
        if os.environ.get("NPC_HTTP_LOG") == "1":
            super().log_message(fmt, *args)

    # ------------------------------------------------------------ HTTP verbs
    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self._cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path

        if path in ("/", "/index.html"):
            self._serve_static("index.html", "text/html; charset=utf-8")
            return

        if path.startswith("/static/"):
            self._serve_static(unquote(path[len("/static/"):]))
            return

        if path == "/api/state":
            sim = self.simulation
            self._send_json({
                "game_day": sim.world.game_day,
                "location": sim.world.location,
                "player_pos": sim.player_pos,
                "npcs": {
                    k: {
                        "npc_id": v.npc_id,
                        "role": v.role,
                        "trust": v.trust,
                        "personality": v.personality,
                        "inventory": v.inventory,
                    }
                    for k, v in sim.npcs.items()
                },
                "event_log": sim.event_log,
            })
            return

        if path == "/api/dialogue/config":
            hook = self.simulation.synthesizer.llm_hook
            self._send_json({
                "llm_configured": hook.is_configured,
                "model": hook.model,
                "endpoint": hook.endpoint or "https://api.openai.com/v1/chat/completions (default)",
                "mode": "LLM Paraphraser (grounding-verified)" if hook.is_configured
                        else "Offline Deterministic Persona Generator",
            })
            return

        if path.startswith("/api/npc/") and path.endswith("/brain"):
            parts = path.split("/")
            if len(parts) >= 4 and parts[3]:
                self._send_json(self.simulation.get_npc_brain(parts[3]))
                return

        self._send_json({"error": "not found", "path": path}, status=404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        body = self._read_json()
        sim = self.simulation

        if path == "/api/player/move":
            x = body.get("x", sim.player_pos["x"])
            y = body.get("y", sim.player_pos["y"])
            sim.player_pos = {"x": x, "y": y}
            self._send_json({"status": "ok", "pos": sim.player_pos})
            return

        if path == "/api/interact":
            self._send_json(sim.interact_with_npc(body.get("npc_id", "mira")))
            return

        if path == "/api/day/advance":
            self._send_json(sim.advance_day())
            return

        if path == "/api/counterfactual/simulate":
            self._send_json(sim.simulate_counterfactual(
                body.get("npc_id", "mira"),
                body.get("disabled_event_ids", []) or [],
            ))
            return

        if path == "/api/action/evidence":
            self._send_json(sim.present_evidence(body.get("target", "kael")))
            return

        if path == "/api/action/persuade_rohan":
            self._send_json(sim.persuade_rohan())
            return

        if path == "/api/rumour/share":
            res = sim.share_rumour(body.get("speaker", "arun"), body.get("listener", "mira"))
            self._send_json(res or {"status": "no_memory_to_share"}, status=200 if res else 409)
            return

        if path == "/api/scenario/reset":
            sim.reset()
            self._send_json({"status": "reset_completed", "game_day": sim.world.game_day})
            return

        self._send_json({"error": "not found", "path": path}, status=404)

    # ------------------------------------------------------------- static I/O
    def _serve_static(self, rel_path: str, content_type: Optional[str] = None) -> None:
        """Serve a file that is guaranteed to live under ``static_dir``."""
        try:
            candidate = (self.static_dir / rel_path).resolve()
            candidate.relative_to(self.static_dir)      # containment: blocks ../
        except (ValueError, OSError):
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._serve_file(candidate, content_type)

    def _serve_file(self, file_path: Path, content_type: Optional[str] = None) -> None:
        if not file_path.exists() or not file_path.is_file():
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        mime = content_type or mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        content = file_path.read_bytes()

        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def create_server(
    host: str = "127.0.0.1",
    port: int = 8080,
    simulation: Optional[TownSimulation] = None,
    *,
    cors: bool = False,
    threaded: bool = True,
) -> HTTPServer:
    """Build a server instance with the simulation bound to its handler class."""
    handler: Type[GameWebHandler] = type(
        "BoundGameWebHandler",
        (GameWebHandler,),
        {
            "simulation": simulation if simulation is not None else TownSimulation(),
            "allow_cors": cors,
            "static_dir": STATIC_DIR,
        },
    )
    server_cls = ThreadingHTTPServer if threaded else HTTPServer
    server_cls.daemon_threads = True
    return server_cls((host, port), handler)


def run_server(host: str = "127.0.0.1", port: int = 8080, *, cors: bool = False) -> None:
    server = create_server(host, port, cors=cors)
    print(f"NPC memory simulator running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping server...")
    finally:
        server.server_close()


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="SHM-NPC simulator web server")
    parser.add_argument("--host", default=os.environ.get("NPC_HOST", "127.0.0.1"),
                        help="bind address (use 0.0.0.0 to expose; default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("NPC_PORT", "8080")))
    parser.add_argument("--cors", action="store_true",
                        default=os.environ.get("NPC_CORS") == "1",
                        help="send permissive CORS headers (off by default)")
    parser.add_argument("--single-threaded", action="store_true",
                        help="use HTTPServer instead of ThreadingHTTPServer")
    args = parser.parse_args(argv)

    server = create_server(args.host, args.port, cors=args.cors,
                           threaded=not args.single_threaded)
    print(f"NPC memory simulator running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping server...")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
