import json
import os
import sys
import mimetypes
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Ensure src is in python path
src_dir = Path(__file__).resolve().parent.parent.parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from npc_memory_project.simulation.town_simulation import TownSimulation
from npc_memory_project.core.models import GameEvent

# Shared simulation instance
simulation = TownSimulation()

STATIC_DIR = Path(__file__).resolve().parent / "static"

class GameWebHandler(BaseHTTPRequestHandler):
    def _send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len == 0:
            return {}
        raw = self.rfile.read(content_len).decode("utf-8")
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self._serve_file(STATIC_DIR / "index.html", "text/html")
            return

        if path.startswith("/static/"):
            rel_path = path[len("/static/"):]
            file_path = STATIC_DIR / rel_path
            mime, _ = mimetypes.guess_type(str(file_path))
            self._serve_file(file_path, mime or "application/octet-stream")
            return

        if path == "/api/state":
            self._send_json({
                "game_day": simulation.world.game_day,
                "location": simulation.world.location,
                "player_pos": simulation.player_pos,
                "npcs": {
                    k: {
                        "npc_id": v.npc_id,
                        "role": v.role,
                        "trust": v.trust,
                        "personality": v.personality,
                        "inventory": v.inventory,
                    }
                    for k, v in simulation.npcs.items()
                },
                "event_log": simulation.event_log,
            })
            return

        if path == "/api/dialogue/config":
            hook = simulation.synthesizer.llm_hook
            self._send_json({
                "llm_configured": hook.is_configured,
                "model": hook.model,
                "endpoint": hook.endpoint or "https://api.openai.com/v1/chat/completions (default)",
                "mode": "LLM Paraphraser" if hook.is_configured else "Offline Deterministic Persona Generator",
            })
            return

        if path.startswith("/api/npc/") and path.endswith("/brain"):
            # /api/npc/{npc_id}/brain
            parts = path.split("/")
            if len(parts) >= 4:
                npc_id = parts[3]
                brain = simulation.get_npc_brain(npc_id)
                self._send_json(brain)
                return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._read_json()

        if path == "/api/player/move":
            x = body.get("x", simulation.player_pos["x"])
            y = body.get("y", simulation.player_pos["y"])
            simulation.player_pos = {"x": x, "y": y}
            self._send_json({"status": "ok", "pos": simulation.player_pos})
            return

        if path == "/api/interact":
            npc_id = body.get("npc_id", "mira")
            res = simulation.interact_with_npc(npc_id)
            self._send_json(res)
            return

        if path == "/api/day/advance":
            res = simulation.advance_day()
            self._send_json(res)
            return

        if path == "/api/counterfactual/simulate":
            npc_id = body.get("npc_id", "mira")
            disabled_ids = body.get("disabled_event_ids", [])
            res = simulation.simulate_counterfactual(npc_id, disabled_ids)
            self._send_json(res)
            return

        if path == "/api/action/evidence":
            # Player shows evidence to Guard or Mira
            target = body.get("target", "kael")
            if target == "kael" or target == "mira":
                e = GameEvent(
                    event_type="innocence_verified",
                    actor="player",
                    target_npc=target,
                    description="The player presented stamped pharmacy receipts proving Rohan stole the medicine.",
                    game_day=simulation.world.game_day,
                    location="pharmacy",
                    emotional_impact=0.9,
                    relationship_impact=0.8,
                    quest_relevance=0.8,
                    novelty=0.9,
                    source="direct_proof",
                    confidence=0.98,
                    metadata={"conflict_key": "medicine_theft", "claim": "rohan_stole"},
                )
                simulation.record_event(e)
                # If presenting to Kael, Kael updates Mira
                if target == "kael":
                    e_mira = GameEvent(
                        event_type="innocence_verified",
                        actor="kael",
                        target_npc="mira",
                        description="Officer Kael officially confirmed the player's receipt evidence proving Rohan stole.",
                        game_day=simulation.world.game_day,
                        location="pharmacy",
                        emotional_impact=0.9,
                        relationship_impact=0.8,
                        quest_relevance=0.7,
                        novelty=0.9,
                        source="guard",
                        confidence=0.95,
                        metadata={"conflict_key": "medicine_theft", "claim": "rohan_stole"},
                    )
                    simulation.record_event(e_mira)
                    simulation.npcs["mira"].trust = 10.0
                self._send_json({"status": "evidence_presented", "target": target})
                return

        if path == "/api/action/persuade_rohan":
            # Persuade Rohan to confess
            e_confess = GameEvent(
                event_type="confess_theft",
                actor="rohan",
                target_npc="kael",
                description="Rohan confessed in tears that he stole the medicine out of desperation.",
                game_day=simulation.world.game_day,
                location="alley",
                emotional_impact=0.95,
                relationship_impact=0.5,
                quest_relevance=0.9,
                novelty=0.9,
                source="confession",
                confidence=0.99,
                metadata={"conflict_key": "medicine_theft", "claim": "rohan_stole"},
            )
            simulation.record_event(e_confess)
            simulation._log("Rohan confessed to Officer Kael! Medicine theft resolved.")
            self._send_json({"status": "confessed"})
            return

        if path == "/api/rumour/share":
            speaker = body.get("speaker", "arun")
            listener = body.get("listener", "mira")
            res = simulation.share_rumour(speaker, listener)
            self._send_json(res or {"status": "no_memory_to_share"})
            return

        if path == "/api/scenario/reset":
            simulation.init_characters()
            simulation.load_preset_benchmark()
            self._send_json({"status": "reset_completed", "game_day": 1})
            return

        self.send_response(404)
        self.end_headers()

    def _serve_file(self, file_path: Path, content_type: str):
        if not file_path.exists() or not file_path.is_file():
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404 Not Found")
            return

        with open(file_path, "rb") as f:
            content = f.read()

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

def run_server(port=8080):
    server = HTTPServer(("127.0.0.1", port), GameWebHandler)
    print(f"Server started at http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping server...")
    finally:
        server.server_close()

if __name__ == "__main__":
    port = 8080
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])
    run_server(port)
