#!/usr/bin/env python3
"""Sideshelf web server: static files from <www> plus a small API about the user's iPhone.

  GET  /api/device[?fresh=1]  which published apps are on the reachable iPhone, and which builds
  POST /api/open {"bundle_id"} launch a published app on that iPhone

The iPhone is reached through CoreDevice (`xcrun devicectl`), which works when it is on the same
Wi-Fi as the Mac or on a cable. Otherwise /api/device answers {"device": null} and pages keep
plain "Install" buttons.

Usage: server.py <www dir> <port>   (binds 127.0.0.1; tailscale serve proxies it)
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WWW = Path(sys.argv[1])
PORT = int(sys.argv[2])
CACHE_SECONDS = 20

lock = threading.Lock()
cache = {"at": 0.0, "data": None}


def devicectl(*args, timeout=25):
    """Run `xcrun devicectl … -j <tmp>` and return the parsed "result"."""
    with tempfile.NamedTemporaryFile(suffix=".json") as out:
        subprocess.run(["xcrun", "devicectl", *args, "-q", "-j", out.name],
                       capture_output=True, timeout=timeout, check=True)
        return json.load(open(out.name))["result"]


def find_iphone():
    for d in devicectl("list", "devices")["devices"]:
        if d["hardwareProperties"].get("deviceType") == "iPhone" and \
                d["connectionProperties"].get("tunnelState") != "unavailable":
            return {"id": d["identifier"], "name": d["deviceProperties"].get("name", "iPhone")}
    return None


def published_bundles():
    ids = set()
    for m in WWW.glob("*/builds/*/meta.json"):
        try:
            ids.add(json.loads(m.read_text())["bundle_id"])
        except (OSError, ValueError, KeyError):
            pass
    return ids


def probe():
    data = {"device": None, "apps": {}}
    try:
        device = find_iphone()
        if device:
            wanted = published_bundles()
            apps = devicectl("device", "info", "apps", "--device", device["id"])["apps"]
            data = {"device": device, "apps": {
                a["bundleIdentifier"]: {"build": a.get("bundleVersion"), "version": a.get("version")}
                for a in apps if a.get("bundleIdentifier") in wanted}}
    except (subprocess.SubprocessError, OSError, ValueError, KeyError):
        pass  # phone asleep or out of reach: answer "no device"
    return data


def refresh():
    with lock:
        data = probe()
        cache.update(at=time.time(), data=data)
        return data


def device_state(fresh=False):
    """Asking the phone takes seconds, so answer from cache and refresh stale data in the background;
    fresh=True waits for a new answer."""
    if fresh or cache["data"] is None:
        return refresh()
    if time.time() - cache["at"] > CACHE_SECONDS and not lock.locked():
        threading.Thread(target=refresh, daemon=True).start()
    return cache["data"]


class Handler(SimpleHTTPRequestHandler):
    def send_json(self, code, body):
        raw = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/device":
            return self.send_json(200, device_state(fresh="fresh=1" in self.path))
        super().do_GET()

    def do_POST(self):
        if self.path != "/api/open":
            return self.send_json(404, {"error": "not found"})
        try:
            bundle = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))["bundle_id"]
        except (ValueError, KeyError, TypeError):
            return self.send_json(400, {"error": "bundle_id is required"})
        if bundle not in published_bundles():
            return self.send_json(404, {"error": "not a Sideshelf app"})
        device = (device_state().get("device") or {}).get("id")
        if not device:
            return self.send_json(409, {"error": "iPhone is out of reach"})
        try:
            devicectl("device", "process", "launch", "--device", device, bundle)
        except (subprocess.SubprocessError, OSError) as e:
            return self.send_json(502, {"error": f"launch failed: {e}"})
        return self.send_json(200, {"ok": True})


if __name__ == "__main__":
    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer(("127.0.0.1", PORT), partial(Handler, directory=str(WWW)))
    (WWW.parent / "server.pid").write_text(str(os.getpid()))
    threading.Thread(target=refresh, daemon=True).start()  # warm the cache before the first visit
    server.serve_forever()
