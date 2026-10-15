"""
Mock LLM server (stdlib only, port 9000).
Behaves like an OpenAI-compatible /v1/chat/completions endpoint.
Used for practice, testing, and as a last-resort backup when no real AI is available.
"""

import json
import time
import sys
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler


class MockLLMHandler(BaseHTTPRequestHandler):
    """Handles POST /v1/chat/completions with a fixed reply."""

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self._send(404, {"error": {"message": "Not found", "type": "mock"}})
            return

        # Read and parse the request body
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            self._send(400, {"error": {"message": "Invalid JSON", "type": "mock"}})
            return

        model = body.get("model", "mock-large")
        messages = body.get("messages", [])

        # Build a fixed reply (PRD §12)
        reply = "Step done. " + "Here is a detailed answer with many words. " * 18

        # Token counts: simple char-based heuristic matching the PRD
        all_content = " ".join(m.get("content", "") for m in messages)
        prompt_tokens = len(all_content) // 4
        completion_tokens = len(reply) // 4

        # Simulate latency (PRD §12: sleep 0.4s)
        time.sleep(0.4)

        response = {
            "id": f"mock-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": reply},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }
        self._send(200, response)

    def _send(self, status: int, body: dict):
        """Send a JSON response."""
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        """Quieter logging — just method and path."""
        print(f"[mock-llm] {args[0]}")


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
    server = ThreadingHTTPServer(("0.0.0.0", port), MockLLMHandler)
    print(f"[mock-llm] Mock LLM server running on port {port}")
    print(f"[mock-llm] POST http://localhost:{port}/v1/chat/completions")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[mock-llm] Shutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
