#!/usr/bin/env python3
"""Sideshelf web server: static files from <www> plus a small API about the user's iPhone and iPad.

  GET  /api/device[?type=iPad][&fresh=1]  which published apps are on the reachable iPhone (or iPad),
                                          and which builds; the page asks about its own kind of device
  POST /api/open {"bundle_id", "type"}    launch a published app on that device
  POST /api/install {"slug","build"}  arm progress tracking right before the page opens itms-services
  GET  /api/install?slug=&build=      did iOS fetch the manifest, how much of the .ipa it downloaded

Pages come in English (index.html) and Russian (index.ru.html); the language is picked from
the browser's Accept-Language, which on iOS follows the system language.

Devices are reached through CoreDevice (`xcrun devicectl`), which works when they are on the same
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
from urllib.parse import parse_qs

WWW = Path(sys.argv[1])
PORT = int(sys.argv[2])
CACHE_SECONDS = 20
KINDS = ("iPhone", "iPad")  # CoreDevice deviceType values Sideshelf installs to

lock = threading.Lock()
cache = {"at": 0.0, "data": None}
installs = {}  # "/<slug>/builds/<build>/" -> {"armed", "manifest", "started", "sent", "total", "done"}


def devicectl(*args, timeout=25):
    """Run `xcrun devicectl … -j <tmp>` and return the parsed "result"."""
    with tempfile.NamedTemporaryFile(suffix=".json") as out:
        subprocess.run(["xcrun", "devicectl", *args, "-q", "-j", out.name],
                       capture_output=True, timeout=timeout, check=True)
        return json.load(open(out.name))["result"]


def find_devices():
    """The first reachable physical device of each kind (CoreDevice also lists simulators)."""
    found = {}
    for d in devicectl("list", "devices")["devices"]:
        hw = d["hardwareProperties"]
        kind = hw.get("deviceType")
        if kind in KINDS and kind not in found and hw.get("reality", "physical") == "physical" and \
                d["connectionProperties"].get("tunnelState") != "unavailable":
            found[kind] = {"id": d["identifier"], "name": d["deviceProperties"].get("name", kind)}
    return found


def published_bundles():
    ids = set()
    for m in WWW.glob("*/builds/*/meta.json"):
        try:
            ids.add(json.loads(m.read_text())["bundle_id"])
        except (OSError, ValueError, KeyError):
            pass
    return ids


def probe():
    """{kind: {"device", "apps"}} for every kind; a device asleep or out of reach answers "no device"."""
    data = {kind: {"device": None, "apps": {}} for kind in KINDS}
    try:
        devices = find_devices()
    except (subprocess.SubprocessError, OSError, ValueError, KeyError):
        return data
    wanted = published_bundles()
    for kind, device in devices.items():
        try:
            apps = devicectl("device", "info", "apps", "--device", device["id"])["apps"]
        except (subprocess.SubprocessError, OSError, ValueError, KeyError):
            continue
        data[kind] = {"device": device, "apps": {
            a["bundleIdentifier"]: {"build": a.get("bundleVersion"), "version": a.get("version")}
            for a in apps if a.get("bundleIdentifier") in wanted}}
    return data


def refresh():
    asked = time.time()
    with lock:
        if cache["at"] >= asked:  # a probe finished while we waited for the lock: reuse it
            return cache["data"]
        data = probe()
        cache.update(at=time.time(), data=data)
        return data


def device_state(kind="iPhone", fresh=False):
    """Asking the devices takes seconds, so answer from cache and refresh stale data in the background;
    fresh=True waits for a new answer."""
    kind = kind if kind in KINDS else "iPhone"
    if cache["data"] is not None and time.time() - cache["at"] < 3:
        return cache["data"][kind]  # just asked; don't make the devices answer twice in a row
    if fresh or cache["data"] is None:
        return refresh()[kind]
    if time.time() - cache["at"] > CACHE_SECONDS and not lock.locked():
        threading.Thread(target=refresh, daemon=True).start()
    return cache["data"][kind]


def preferred_lang(header):
    """First of ru/en in the Accept-Language list, by q-value; English otherwise."""
    langs = []
    for part in (header or "").split(","):
        tag, _, q = part.strip().partition(";q=")
        try:
            weight = float(q) if q else 1.0
        except ValueError:
            weight = 0.0
        langs.append((weight, tag.strip().lower()[:2]))
    for _, lang in sorted(langs, key=lambda x: -x[0]):  # stable: equal weights keep their order
        if lang in ("ru", "en"):
            return lang
    return "en"


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        path = self.path.split("?")[0]
        if path.endswith((".html", "/")):
            self.send_header("Vary", "Accept-Language")
        if path.endswith((".html", "/", ".css", ".js", ".json", ".webmanifest")):
            # Always revalidate, so the home-screen app picks up new pages, styles and scripts at once.
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def copyfile(self, source, outputfile):
        """Stream an armed .ipa in chunks, counting bytes for /api/install."""
        path = self.path.split("?")[0]
        rec = installs.get(path.rsplit("/", 1)[0] + "/") if path.endswith("/app.ipa") else None
        if rec is None:
            return super().copyfile(source, outputfile)
        rec.update(started=time.time(), sent=0, total=os.fstat(source.fileno()).st_size, done=None)
        while chunk := source.read(64 * 1024):
            outputfile.write(chunk)
            rec["sent"] += len(chunk)
        rec["done"] = time.time()

    def localize(self):
        """Point a page request at index.ru.html when the visitor prefers Russian."""
        path, sep, query = self.path.partition("?")
        if path.endswith("/") and preferred_lang(self.headers.get("Accept-Language")) == "ru" \
                and (WWW / path.lstrip("/") / "index.ru.html").is_file():
            self.path = path + "index.ru.html" + sep + query

    def send_json(self, code, body):
        raw = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path, _, query = self.path.partition("?")
        q = parse_qs(query)
        if path == "/api/device":
            return self.send_json(200, device_state(q.get("type", ["iPhone"])[0], fresh="fresh=1" in query))
        if path == "/api/install":
            rec = installs.get(f"/{q.get('slug', [''])[0]}/builds/{q.get('build', [''])[0]}/")
            return self.send_json(200, {"armed": rec is not None, **(rec or {}), "now": time.time()})
        if path.endswith("/manifest.plist") and path.rsplit("/", 1)[0] + "/" in installs:
            installs[path.rsplit("/", 1)[0] + "/"]["manifest"] = time.time()
        self.localize()
        super().do_GET()

    def do_HEAD(self):
        self.localize()
        super().do_HEAD()

    def read_json(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")

    def do_POST(self):
        if self.path == "/api/install":
            try:
                body = self.read_json()
                slug, build = str(body["slug"]), str(body["build"])
            except (ValueError, KeyError, TypeError):
                return self.send_json(400, {"error": "slug and build are required"})
            if "/" in slug + build or ".." in slug + build or not (WWW / slug / "builds" / build / "app.ipa").is_file():
                return self.send_json(404, {"error": "no such build"})
            installs[f"/{slug}/builds/{build}/"] = {"armed": time.time(), "manifest": None, "started": None,
                                                     "sent": 0, "total": 0, "done": None}
            return self.send_json(200, {"ok": True})
        if self.path != "/api/open":
            return self.send_json(404, {"error": "not found"})
        try:
            body = self.read_json()
            bundle, kind = body["bundle_id"], str(body.get("type") or "iPhone")
        except (ValueError, KeyError, TypeError, AttributeError):
            return self.send_json(400, {"error": "bundle_id is required"})
        if bundle not in published_bundles():
            return self.send_json(404, {"error": "not a Sideshelf app"})
        device = (device_state(kind).get("device") or {}).get("id")
        if not device:
            return self.send_json(409, {"error": f"{kind} is out of reach"})
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
