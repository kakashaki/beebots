"""Isolated research budget for one OpenEvolve batch.

This process does not bind :4182, :4183, or :4184 and does not change those bridges.
It also does not read secrets. A dollar figure is claimed only when a price is supplied.
Without a price, the cap is a completion count and a token count, and the run fails closed
if someone offers a dollar cap anyway.

First batch: 1 iteration per bee, at most 2 completions per bee, at most 15000 tokens
requested on each completion. Bee1, bee2, and bee3 each have their own counter.
The parent points the research process at this proxy, for example
http://127.0.0.1:4195/bee2/v1 , and leaves the shared bridges alone.
"""
from __future__ import annotations

import argparse, json, os, sys

BEES = ("bee1", "bee2", "bee3")
MAX_ITERATIONS_PER_BEE = 1
MAX_COMPLETIONS_PER_BEE = 2
MAX_TOKENS_PER_COMPLETION = 15000
PRODUCTION_PORTS = {4182, 4183, 4184}
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 4195
COMPLETION_TAILS = ("/v1/chat/completions", "/chat/completions")

def new_state():
    return {
        "completions": {bee: 0 for bee in BEES},
        "tokens_reserved": {bee: 0 for bee in BEES},
        "dollar_cap_claimed": False,
        "price_usd_per_million_tokens": None,
        "paid_call": False,
    }

def dollar_budget(dollar_cap, price_per_million):
    """A dollar cap without a price is a refusal, not a guess."""
    if dollar_cap is None:
        return {"ok": True, "dollar_cap_claimed": False, "reason": "no_dollar_cap_offered"}
    try:
        price = float(price_per_million)
    except (TypeError, ValueError):
        price = None
    if price is None or not (price > 0):
        return {"ok": False, "dollar_cap_claimed": False, "reason": "price_unavailable_no_dollar_cap"}
    return {"ok": True, "dollar_cap_claimed": True, "reason": "priced", "dollar_cap": float(dollar_cap), "price_usd_per_million_tokens": price}

def parse_target(path):
    """/bee2/v1/chat/completions -> (bee2, /v1/chat/completions). Other routes stay unscoped."""
    parts = [p for p in path.split("?")[0].split("/") if p]
    if parts and parts[0] in BEES:
        bee = parts[0]
        rest = "/" + "/".join(parts[1:])
        return bee, rest
    return None, path.split("?")[0]

def admit(state, bee, max_tokens):
    if bee not in BEES:
        return False, "bee_not_in_batch"
    if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens <= 0 or max_tokens > MAX_TOKENS_PER_COMPLETION:
        return False, "token_limit"
    if state["completions"][bee] >= MAX_COMPLETIONS_PER_BEE:
        return False, "completion_cap"
    room = MAX_COMPLETIONS_PER_BEE * MAX_TOKENS_PER_COMPLETION
    if state["tokens_reserved"][bee] + max_tokens > room:
        return False, "token_budget"
    state["completions"][bee] += 1
    state["tokens_reserved"][bee] += max_tokens
    state["dollar_cap_claimed"] = False
    return True, "admitted"

def decide(method, path, body, state):
    """Whether this proxy will forward. GET /health is local. Completions require a bee and a token cap.

    Authorization headers are not read here. A 404 from this proxy is an unsupported route,
    not evidence that the upstream bridge cannot complete.
    """
    bee, rest = parse_target(path)
    if method == "GET" and rest == "/health":
        return {"status": 200, "forward": False, "bee": bee, "body": public_state(state)}
    if method != "POST" or rest not in COMPLETION_TAILS:
        return {
            "status": 404, "forward": False, "bee": bee,
            "body": {"error": "unsupported_route", "completions_broken": False, "completions_status": "not_tested"},
        }
    if bee is None:
        return {"status": 403, "forward": False, "bee": None, "body": {"error": "bee_path_required", "admitted": False}}
    ok, reason = admit(state, bee, body.get("max_tokens") if isinstance(body, dict) else None)
    if not ok:
        return {"status": 429, "forward": False, "bee": bee, "body": {"error": reason, "admitted": False, "dollar_cap_claimed": False}}
    return {"status": 200, "forward": True, "bee": bee, "upstream_path": rest, "body": {"admitted": True, "reason": reason}}

def public_state(state):
    return {
        "ok": True,
        "dollar_cap_claimed": False,
        "price_usd_per_million_tokens": state.get("price_usd_per_million_tokens"),
        "completions": state["completions"],
        "tokens_reserved": state["tokens_reserved"],
        "max_completions_per_bee": MAX_COMPLETIONS_PER_BEE,
        "max_tokens_per_completion": MAX_TOKENS_PER_COMPLETION,
        "max_iterations_per_bee": MAX_ITERATIONS_PER_BEE,
        "paid_call": False,
    }

def load_state(path):
    if not os.path.exists(path):
        return new_state()
    try:
        raw = json.load(open(path))
    except (OSError, json.JSONDecodeError):
        raise SystemExit("budget state is unreadable; refusing rather than starting from zero")
    state = new_state()
    for bee in BEES:
        try:
            state["completions"][bee] = int(raw["completions"][bee])
            state["tokens_reserved"][bee] = int(raw["tokens_reserved"][bee])
        except (KeyError, TypeError, ValueError):
            raise SystemExit("budget state is missing a bee counter; refusing rather than starting from zero")
        if state["completions"][bee] < 0 or state["tokens_reserved"][bee] < 0:
            raise SystemExit("budget state has a negative counter")
    return state

def save_state(path, state):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    json.dump(public_state(state) | {"completions": state["completions"], "tokens_reserved": state["tokens_reserved"]}, open(tmp, "w"), indent=2)
    os.replace(tmp, path)

def _port(url):
    host_port = url.split("://", 1)[-1].split("/", 1)[0]
    if host_port.startswith("["):
        return None
    if ":" not in host_port:
        return None
    host, port = host_port.rsplit(":", 1)
    if host != LISTEN_HOST:
        return None
    try:
        return int(port)
    except ValueError:
        return None

def serve(upstream, listen_port, state_path, dollar_cap, price_per_million):
    offer = dollar_budget(dollar_cap, price_per_million)
    if not offer["ok"]:
        print(json.dumps({"started": False, **offer}))
        raise SystemExit(2)
    up_port = _port(upstream)
    if up_port not in PRODUCTION_PORTS:
        print(json.dumps({"started": False, "reason": "upstream_must_be_existing_local_bridge"}))
        raise SystemExit(2)
    if listen_port in PRODUCTION_PORTS or listen_port == up_port:
        print(json.dumps({"started": False, "reason": "refusing_to_bind_a_shared_bridge_port"}))
        raise SystemExit(2)
    state = load_state(state_path)
    state["dollar_cap_claimed"] = False
    state["price_usd_per_million_tokens"] = offer.get("price_usd_per_million_tokens")
    save_state(state_path, state)
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import urllib.request

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def _send(self, status, payload):
            raw = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            decision = decide("GET", self.path, None, state)
            self._send(decision["status"], decision["body"])

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw.decode() or "{}")
            except json.JSONDecodeError:
                self._send(400, {"error": "bad_json", "admitted": False})
                return
            decision = decide("POST", self.path, body, state)
            if not decision["forward"]:
                save_state(state_path, state)
                self._send(decision["status"], decision["body"])
                return
            # The count is already reserved. A failed upstream is not retried and is not moved to another port.
            req = urllib.request.Request(upstream.rstrip("/") + decision["upstream_path"], data=raw, method="POST")
            req.add_header("Content-Type", self.headers.get("Content-Type", "application/json"))
            auth = self.headers.get("Authorization")
            if auth:
                req.add_header("Authorization", auth)
            try:
                with urllib.request.urlopen(req, timeout=240) as resp:
                    payload = resp.read()
                    status = resp.status
            except Exception as e:
                save_state(state_path, state)
                self._send(502, {"error": "upstream_failed", "admitted": True, "detail": type(e).__name__})
                return
            save_state(state_path, state)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    httpd = ThreadingHTTPServer((LISTEN_HOST, listen_port), Handler)
    print(json.dumps({"started": True, "listen": f"http://{LISTEN_HOST}:{listen_port}", "upstream": upstream, "dollar_cap_claimed": False, "paid_call": False}))
    httpd.serve_forever()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["status", "serve"])
    ap.add_argument("--upstream", default="http://127.0.0.1:4183")
    ap.add_argument("--listen-port", type=int, default=LISTEN_PORT)
    ap.add_argument("--state", default="evolve/research_out/budget_state.json")
    ap.add_argument("--dollar-cap", type=float)
    ap.add_argument("--price-per-million", type=float)
    args = ap.parse_args()
    if os.path.abspath(args.state).endswith(os.path.join("state", "oe_db")):
        raise SystemExit("refusing to use the live population as budget state")
    if args.cmd == "status":
        offer = dollar_budget(args.dollar_cap, args.price_per_million)
        print(json.dumps({
            "serve": False,
            "paid_call": False,
            "dollar_cap_claimed": False,
            "max_iterations_per_bee": MAX_ITERATIONS_PER_BEE,
            "max_completions_per_bee": MAX_COMPLETIONS_PER_BEE,
            "max_tokens_per_completion": MAX_TOKENS_PER_COMPLETION,
            "bees": list(BEES),
            "dollar_offer": offer,
            "shared_bridges_unchanged": True,
        }, indent=2))
        raise SystemExit(0 if offer["ok"] else 2)
    serve(args.upstream, args.listen_port, args.state, args.dollar_cap, args.price_per_million)

if __name__ == "__main__":
    main()
