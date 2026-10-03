#!/usr/bin/env python3
"""Render the Sideshelf storefront and one page per app from <www>/<app>/builds/*/meta.json,
in English (index.html) and Russian (index.ru.html); server.py picks one from Accept-Language.

Usage: render.py <www dir> <root url, e.g. https://mac.tailnet.ts.net>
"""
import hashlib
import html
import json
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

WWW = Path(sys.argv[1])
ROOT = sys.argv[2].rstrip("/")
STRINGS = {
    "en": {
        "months": "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(),
        "units": ("B", "KB", "MB", "GB"), "decimal": ".",
        "install": "Install", "dirty": "plus uncommitted changes", "more": "and {n} more",
        "no_changes": "No code changes", "no_commits": "No commit info",
        "qr_lead": "Over-the-air installs only work on iPhone and iPad. Point your phone's camera at the code to open this page in Safari.",
        "qr_note": "Your phone has to be on the tailnet with Tailscale turned on.",
        "open_on": "Open {name} on your iPhone",
        "mac_online": "Mac online", "phone_near": " · iPhone nearby",
        "fresh": "Latest build", "version_dot": "Version {v} · ", "all_apps": "All apps",
        "empty": "Nothing published yet. Run ota-deploy.sh in an Xcode project folder.",
        "foot": "Visible only to devices on your tailnet",
        "latest": "Latest", "share": "Share link",
        "k_version": "Version", "s_build": "build {b}", "k_built": "Built", "k_size": "Size", "s_later": "or later",
        "whats_new": "What’s New", "builds": "Builds",
    },
    "ru": {
        "months": "янв фев мар апр мая июн июл авг сен окт ноя дек".split(),
        "units": ("Б", "КБ", "МБ", "ГБ"), "decimal": ",",
        "install": "Установить", "dirty": "и незакоммиченные изменения", "more": "и ещё {n}",
        "no_changes": "Без изменений в коде", "no_commits": "Нет данных о коммитах",
        "qr_lead": "Установка по воздуху работает только на iPhone и iPad. Наведи камеру телефона на код, страница откроется в Safari.",
        "qr_note": "Телефон тоже должен быть в tailnet с включённым Tailscale.",
        "open_on": "Открой {name} на iPhone",
        "mac_online": "Mac онлайн", "phone_near": " · iPhone рядом",
        "fresh": "Свежая сборка", "version_dot": "Версия {v} · ", "all_apps": "Все приложения",
        "empty": "Пока ничего не опубликовано. Запусти ota-deploy.sh в папке Xcode-проекта.",
        "foot": "Видно только устройствам в твоём tailnet",
        "latest": "Последняя", "share": "Поделиться ссылкой",
        "k_version": "Версия", "s_build": "сборка {b}", "k_built": "Собрано", "k_size": "Размер", "s_later": "и новее",
        "whats_new": "Что нового", "builds": "Сборки",
    },
}
LANG = "en"  # set by main() for each pass


def t(key, **kw):
    s = STRINGS[LANG][key]
    return s.format(**kw) if kw else s

GRADIENTS = [("#4fd1c5", "#2563eb"), ("#ffd25e", "#ff9f1c"), ("#34d399", "#0f766e"),
             ("#c084fc", "#6d28d9"), ("#fb7185", "#be123c"), ("#93c5fd", "#4338ca")]


def esc(s):
    return html.escape(str(s), quote=True)


def day(iso):
    d = datetime.fromisoformat(iso)
    month = t("months")[d.month - 1]
    return f"{month} {d.day}" if LANG == "en" else f"{d.day} {month}"


def stamp(iso):
    """<time> with an absolute date; sideshelf.js turns it into "12 min ago" / "Yesterday, 18:20"."""
    d = datetime.fromisoformat(iso)
    return f'<time datetime="{esc(iso)}" data-rel>{day(iso)}, {d:%H:%M}</time>'


def size_parts(n):
    units = t("units")
    for i, unit in enumerate(units):
        if n < 1024 or unit == units[-1]:
            num = f"{n:.0f}" if i < 2 or n >= 10 else f"{n:.1f}".replace(".", t("decimal"))
            return num, unit
        n /= 1024


def size(n):
    return " ".join(size_parts(n))


def install_url(app, build):
    manifest = f"{ROOT}/{app['slug']}/builds/{build['dir']}/manifest.plist"
    return "itms-services://?action=download-manifest&url=" + urllib.parse.quote(manifest, safe="")


def icon(app, px, morph=False):
    """morph: name it for the view transition, so the icon flies between the list and the app page."""
    style = f"width:{px}px;height:{px}px" + (f";view-transition-name:icon-{app['slug']}" if morph else "")
    if app["icon"]:
        return f'<img class="icon" style="{style}" src="/{esc(app["slug"])}/icon.png?v={esc(app["builds"][0]["build"])}" alt="">'
    a, b = GRADIENTS[int(hashlib.md5(app["slug"].encode()).hexdigest(), 16) % len(GRADIENTS)]
    return (f'<span class="icon" style="{style};font-size:{round(px * 0.46)}px;'
            f'background:linear-gradient(155deg,{a},{b})">{esc(app["name"][:1].upper())}</span>')


def app_button(app, cls):
    """Install button for the latest build; sideshelf.js turns it into "Open" / "Update"
    when the Mac can see which build is on the iPhone."""
    b = app["builds"][0]
    return (f'<a class="{cls}" data-latest="{esc(b["build"])}" {track_attrs(app, b)} '
            f'href="{esc(install_url(app, b))}">{t("install")}</a>')


def track_attrs(app, build):
    """Lets sideshelf.js follow the install of this build (download progress, then the phone)."""
    return (f'data-bundle="{esc(app["bundle_id"])}" data-slug="{esc(app["slug"])}" '
            f'data-build="{esc(build["dir"])}"')


def notes(build, limit=None):
    if build.get("notes") is None and not build.get("dirty"):
        return ""
    items = [esc(n) for n in (build.get("notes") or [])]
    more = len(items) - limit if limit and len(items) > limit else 0
    items = items[:limit] if limit else items
    if build.get("dirty"):
        items.append(f'<span class="muted">{t("dirty")}</span>')
    if more:
        items.append(f'<span class="muted">{t("more", n=more)}</span>')
    if not items:
        return f'<p class="muted">{t("no_changes")}</p>'
    return '<ul class="notes">' + "".join(f"<li>{i}</li>" for i in items) + "</ul>"


# Same artwork as the project's icon in T3 Code (sideshelf.svg).
MARK = ('<svg viewBox="0 0 120 120" aria-hidden="true"><rect width="120" height="120" fill="#2F5BEA"/>'
        '<rect x="22" y="40" width="34" height="34" rx="9" fill="#fff"/>'
        '<rect x="64" y="40" width="34" height="34" rx="9" fill="#FFB547" transform="rotate(-14 98 74)"/>'
        '<rect x="14" y="74" width="92" height="11" rx="5.5" fill="#fff"/>'
        '<path d="M24 85h12l-12 12zM96 85H84l12 12z" fill="#fff"/></svg>')


def page(title, body, qr_title):
    return f"""<!doctype html>
<html lang="{LANG}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<title>{esc(title)}</title>
<link rel="stylesheet" href="/sideshelf.css">
<link rel="icon" href="/sideshelf.svg" type="image/svg+xml">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Sideshelf">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="theme-color" content="#f2f2f7" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#000000" media="(prefers-color-scheme: dark)">
<script>addEventListener("pagereveal",e=>{{e.viewTransition?.types?.add(location.pathname==="/"?"back":"forward")}})</script>
<script>if(!(/iPhone|iPad|iPod/.test(navigator.userAgent)||(navigator.maxTouchPoints>1&&/Macintosh/.test(navigator.userAgent))))document.documentElement.classList.add("desktop")</script>
</head>
<body>
<div class="wrap">
<aside class="qr-card">
  <div class="brand"><span class="mark">{MARK}</span>Sideshelf</div>
  <h2>{esc(qr_title)}</h2>
  <p>{t("qr_lead")}</p>
  <div class="qr"><div id="qr"></div></div>
  <p class="muted small">{t("qr_note")}</p>
</aside>
<main class="col">
{body}
</main>
</div>
<script src="/sideshelf.js" defer></script>
</body>
</html>
"""


def load_apps():
    apps = []
    for d in sorted(p for p in WWW.iterdir() if p.is_dir()):
        builds = []
        for m in (d / "builds").glob("*/meta.json"):
            b = json.loads(m.read_text())
            b["dir"] = m.parent.name
            builds.append(b)
        if not builds:
            continue
        builds.sort(key=lambda b: b["date"], reverse=True)
        apps.append({"slug": d.name, "name": builds[0]["name"], "bundle_id": builds[0]["bundle_id"],
                     "icon": (d / "icon.png").exists(), "builds": builds})
    apps.sort(key=lambda a: a["builds"][0]["date"], reverse=True)
    return apps


def storefront(apps):
    parts = [f"""<header class="head">
  <div>
    <div class="eyebrow"><span class="dot ok"></span>{t("mac_online")}<span id="phone" hidden>{t("phone_near")}</span></div>
    <h1 class="large-title">Sideshelf</h1>
  </div>
  <span class="mark">{MARK}</span>
</header>"""]
    if apps:
        a = apps[0]
        b = a["builds"][0]
        parts.append(f"""<section>
  <h2 class="title2">{t("fresh")}</h2>
  <div class="group fresh">
    <div class="top">
      <a class="top-link" href="/{esc(a['slug'])}/">
        {icon(a, 64, morph=True)}
        <span class="meta">
          <span class="name big">{esc(a['name'])}</span>
          <span class="line">{t("version_dot", v=esc(b['version'])) if b['version'] else ''}{stamp(b['date'])}</span>
        </span>
      </a>
      {app_button(a, "get solid install")}
    </div>
    {f'<div class="fresh-notes">{notes(b, limit=3)}</div>' if notes(b) else ''}
  </div>
</section>""")
        rows = "".join(f"""
    <div class="row">
      <a class="row-link" href="/{esc(x['slug'])}/">
        {icon(x, 60, morph=x is not a)}
        <span class="meta"><span class="name">{esc(x['name'])}</span><span class="line">{stamp(x['builds'][0]['date'])} · {size(x['builds'][0]['size'])}</span></span>
      </a>
      {app_button(x, "get install")}
    </div>""" for x in apps)
        if len(apps) > 1:  # with one app the fresh card already is the list
            parts.append(f"""<section>
  <div class="section-head"><h2 class="title2">{t("all_apps")}</h2><span class="count">{len(apps)}</span></div>
  <div class="group">{rows}
  </div>
</section>""")
    else:
        parts.append(f'<p class="muted">{t("empty")}</p>')
    parts.append(f'<p class="foot">{t("foot")}</p>')
    return page("Sideshelf", "\n".join(parts), t("open_on", name="Sideshelf"))


def app_page(a):
    b = a["builds"][0]
    num, unit = size_parts(b["size"])
    built = datetime.fromisoformat(b["date"])
    min_os = b.get("min_os") or "—"
    rows = []
    for i, x in enumerate(a["builds"]):
        action = (f'<span class="tag">{t("latest")}</span>' if i == 0 else
                  f'<a class="get install small-get" {track_attrs(a, x)} href="{esc(install_url(a, x))}">{t("install")}</a>')
        rows.append(f"""
    <details class="build" data-bundle="{esc(a['bundle_id'])}" data-build="{esc(x['build'])}"{' open' if i == 0 else ''}>
      <summary class="row">
        <span class="meta"><span class="num">{esc(x['build'])}</span><span class="line">{esc(x['version'])} · {stamp(x['date'])} · {size(x['size'])}</span></span>
        {action}
      </summary>
      <div class="build-notes">{notes(x) or f'<p class="muted">{t("no_commits")}</p>'}</div>
    </details>""")
    whats_new = notes(b)
    body = f"""<nav class="nav"><a href="/"><svg width="12" height="20" viewBox="0 0 12 20" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 2 2 10l8 8"/></svg>Sideshelf</a></nav>
<header class="hero">
  {icon(a, 112, morph=True)}
  <div class="meta">
    <h1>{esc(a['name'])}</h1>
    <span class="bid">{esc(a['bundle_id'])}</span>
    <div class="actions">
      {app_button(a, "get solid install")}
      <button class="share" type="button" data-share aria-label="{t("share")}"><svg width="22" height="24" viewBox="0 0 22 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 15V2M6 6.5 11 1.5l5 5M7 10H4v12h14V10h-3"/></svg></button>
    </div>
  </div>
</header>
<div class="facts">
  <div class="fact"><span class="k">{t("k_version")}</span><span class="v">{esc(b['version'])}</span><span class="s">{t("s_build", b=esc(b['build'].split('.')[-1]))}</span></div>
  <div class="fact"><span class="k">{t("k_built")}</span><span class="v">{day(b['date'])}</span><span class="s">{built:%H:%M}</span></div>
  <div class="fact"><span class="k">{t("k_size")}</span><span class="v">{num}</span><span class="s">{unit}</span></div>
  <div class="fact"><span class="k">iOS</span><span class="v">{esc(min_os)}</span><span class="s">{t("s_later")}</span></div>
</div>
{f'''<section class="new">
  <div class="section-head"><h2 class="title2">{t("whats_new")}</h2>{stamp(b['date'])}</div>
  <div class="bn">{esc(b['version'])} ({esc(b['build'])})</div>
  {whats_new}
</section>''' if whats_new else ''}
<section>
  <div class="section-head"><h2 class="title2">{t("builds")}</h2><span class="count">{len(a['builds'])}</span></div>
  <div class="group builds">{''.join(rows)}
  </div>
</section>"""
    return page(a["name"], body, t("open_on", name=a["name"]))


def main():
    apps = load_apps()
    here = Path(__file__).resolve().parent
    for asset in ("sideshelf.css", "sideshelf.js", "sideshelf.svg", "sw.js", "offline.html", "manifest.webmanifest"):
        (WWW / asset).write_text((here / asset).read_text())
    for asset in ("icon-192.png", "icon-512.png", "apple-touch-icon.png"):
        (WWW / asset).write_bytes((here / asset).read_bytes())
    global LANG
    for LANG, name in (("en", "index.html"), ("ru", "index.ru.html")):
        (WWW / name).write_text(storefront(apps))
        for a in apps:
            (WWW / a["slug"] / name).write_text(app_page(a))


main()
