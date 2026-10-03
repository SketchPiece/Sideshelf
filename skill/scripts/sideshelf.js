// Relative build times, the share button, the offline service worker, what's on the iPhone
// ("Open" / "Update"), and a QR code of the page on desktop.
(() => {
  const T = {
    en: {
      now: "just now", minAgo: (n) => `${n} min ago`, today: (t) => `Today, ${t}`, yesterday: (t) => `Yesterday, ${t}`,
      install: "Install", open: "Open", update: "Update", opening: "Opening…", failed: "Didn’t work", onPhone: "On iPhone",
      installing: "Installing", installed: "Installed",
    },
    ru: {
      now: "только что", minAgo: (n) => `${n} мин назад`, today: (t) => `Сегодня, ${t}`, yesterday: (t) => `Вчера, ${t}`,
      install: "Установить", open: "Открыть", update: "Обновить", opening: "Открываю…", failed: "Не вышло", onPhone: "На телефоне",
      installing: "Устанавливается", installed: "Установлено",
    },
  }[document.documentElement.lang === "ru" ? "ru" : "en"];
  const pad = (n) => String(n).padStart(2, "0");
  const now = new Date();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  for (const t of document.querySelectorAll("time[data-rel]")) {
    const d = new Date(t.dateTime);
    if (isNaN(d)) continue;
    const min = Math.round((now - d) / 60000);
    const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
    if (min < 1) t.textContent = T.now;
    else if (min < 60) t.textContent = T.minAgo(min);
    else if (d.toDateString() === now.toDateString()) t.textContent = T.today(hm);
    else if (d.toDateString() === yesterday.toDateString()) t.textContent = T.yesterday(hm);
  }

  for (const b of document.querySelectorAll("[data-share]")) {
    b.addEventListener("click", () => {
      if (navigator.share) navigator.share({ title: document.title, url: location.href }).catch(() => {});
      else navigator.clipboard?.writeText(location.href);
    });
  }

  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});

  if (document.documentElement.classList.contains("desktop")) showQr();
  else { watchPhone(); pullToRefresh(); }

  // A home-screen app keeps pages in memory for hours; reload when something new was published.
  const checkRev = () =>
    fetch("/rev.json", { cache: "no-store" })
      .then((r) => r.json())
      .then(({ rev }) => { if (rev && rev !== document.documentElement.dataset.rev) location.reload(); })
      .catch(() => {});
  document.addEventListener("visibilitychange", () => { if (!document.hidden) checkRev(); });
  addEventListener("pageshow", (e) => { if (e.persisted) checkRev(); });

  // The Mac asks the iPhone (over CoreDevice) which builds are installed; buttons follow.
  // Tapping Install/Update follows the real install: the server counts the .ipa bytes iOS
  // downloads, then the Mac watches for the build to show up on the phone.
  function watchPhone() {
    const buttons = [...document.querySelectorAll("a[data-latest]")];
    const installers = [...document.querySelectorAll("a[data-slug]")];
    const rows = [...document.querySelectorAll("details[data-build]")];
    if (!installers.length) return;
    const originals = new Map(buttons.map((b) => [b, b.getAttribute("href")]));
    const rowActions = new Map(rows.map((r) => [r, {
      own: r.querySelector("summary > :last-child"),
      onPhone: Object.assign(document.createElement("span"), { className: "tag", textContent: T.onPhone }),
    }]));
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const json = (url, opts) => fetch(url, { cache: "no-store", ...opts }).then((r) => (r.ok ? r.json() : null)).catch(() => null);

    const apply = (state) => {
      const apps = state?.apps ?? {};
      document.getElementById("phone")?.toggleAttribute("hidden", !state?.device);
      for (const b of buttons) {
        if (b.dataset.busy) continue;
        const installed = apps[b.dataset.bundle];
        b.dataset.state = !state?.device || !installed ? "install" : installed.build === b.dataset.latest ? "open" : "update";
        b.textContent = T[b.dataset.state];
        b.setAttribute("href", originals.get(b));
      }
      for (const r of rows) {
        const { own, onPhone } = rowActions.get(r);
        if (own.dataset?.busy) continue;
        const wanted = state?.device && apps[r.dataset.bundle]?.build === r.dataset.build ? onPhone : own;
        const current = r.querySelector("summary > :last-child");
        if (current !== wanted) current.replaceWith(wanted);
      }
    };
    const refresh = (fresh) => json(`/api/device${fresh ? "?fresh=1" : ""}`).then((s) => { if (s) apply(s); return s; });

    // Progress ring in place of the label: spinning while we wait, filling while the .ipa downloads.
    const ring = (b, progress) => {
      b.classList.add("busy");
      if (!b.querySelector(".ring")) {
        b.innerHTML = '<svg class="ring" viewBox="0 0 32 32" aria-hidden="true"><circle class="track" cx="16" cy="16" r="13"/>' +
          '<circle class="arc" cx="16" cy="16" r="13" pathLength="100"/></svg>';
      }
      const svg = b.querySelector(".ring");
      svg.classList.toggle("spin", progress == null);
      svg.querySelector(".arc").style.strokeDasharray = progress == null ? "25 100" : `${Math.max(3, progress * 100)} 100`;
      b.setAttribute("aria-label", progress == null ? T.installing : `${T.installing} ${Math.round(progress * 100)}%`);
    };
    const settle = (b, label) => {
      b.classList.remove("busy");
      b.removeAttribute("aria-label");
      b.textContent = label;
    };

    const follow = async (b) => {
      const { slug, build, bundle } = b.dataset;
      b.dataset.busy = "1";
      ring(b, null);
      await json("/api/install", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ slug, build }), keepalive: true });
      const tapped = Date.now();
      let downloaded = null;
      for (;;) {
        await sleep(downloaded ? 0 : 700);
        const s = await json(`/api/install?slug=${encodeURIComponent(slug)}&build=${encodeURIComponent(build)}`);
        if (s?.done && !downloaded) downloaded = Date.now();
        if (!downloaded) {
          if (s?.started && s.total) ring(b, s.sent / s.total);
          else if (Date.now() - tapped > 60000) { delete b.dataset.busy; settle(b, T.install); return refresh(true); } // cancelled in the iOS alert
          continue;
        }
        ring(b, null); // downloaded; iOS is installing
        const d = await refresh(true);
        const elapsed = Date.now() - downloaded;
        if (d?.device && d.apps[bundle]?.build === build) {
          delete b.dataset.busy;
          settle(b, T.install);
          return apply(d); // main buttons become "Open", an older build's row gets "On iPhone"
        }
        if ((!d?.device && elapsed > 4000) || elapsed > 120000) {
          settle(b, T.installed); // phone out of the Mac's reach: trust the finished download
          b.classList.add("done");
          return;
        }
        await sleep(1500);
      }
    };

    for (const b of installers) {
      b.addEventListener("click", (e) => {
        if (b.dataset.busy) return e.preventDefault();
        if (b.dataset.state === "open") {
          e.preventDefault();
          b.textContent = T.opening;
          fetch("/api/open", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ bundle_id: b.dataset.bundle }) })
            .then((r) => { if (!r.ok) throw new Error(r.status); b.textContent = T.open; })
            .catch(() => { b.textContent = T.failed; setTimeout(() => refresh(true), 1500); });
          return;
        }
        follow(b); // install/update: the itms-services link goes on to iOS
      });
    }

    let fresh = false;
    try { fresh = sessionStorage.getItem("ss-fresh") === "1"; sessionStorage.removeItem("ss-fresh"); } catch {}
    refresh(fresh);
    // Coming back from the app (or after deleting it) re-checks without the server's cache.
    document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(true); });
  }

  // Pull down at the top to reload. Only in the home-screen app: Safari has its own gesture.
  function pullToRefresh() {
    if (!(navigator.standalone || matchMedia("(display-mode: standalone)").matches)) return;
    const THRESHOLD = 64;
    const el = document.createElement("div");
    el.className = "ptr";
    el.innerHTML = '<svg class="ring" viewBox="0 0 32 32" aria-hidden="true"><circle class="track" cx="16" cy="16" r="13"/><circle class="arc" cx="16" cy="16" r="13" pathLength="100"/></svg>';
    document.body.prepend(el);
    const arc = el.querySelector(".arc");
    let startY = null, pull = 0;
    const show = (d) => {
      el.style.transform = `translate(-50%, ${d}px)`;
      el.style.opacity = Math.min(1, d / THRESHOLD);
      arc.style.strokeDasharray = `${Math.min(100, (d / THRESHOLD) * 100)} 100`;
    };
    addEventListener("touchstart", (e) => {
      startY = scrollY <= 0 && e.touches.length === 1 ? e.touches[0].clientY : null;
    }, { passive: true });
    addEventListener("touchmove", (e) => {
      if (startY == null) return;
      pull = Math.min(Math.max(0, e.touches[0].clientY - startY) * 0.5, THRESHOLD * 1.4);
      el.classList.toggle("armed", pull >= THRESHOLD);
      show(pull);
    }, { passive: true });
    addEventListener("touchend", () => {
      if (startY == null) return;
      startY = null;
      if (pull >= THRESHOLD) {
        el.classList.add("loading");
        el.querySelector(".ring").classList.add("spin");
        arc.style.strokeDasharray = "25 100";
        try { sessionStorage.setItem("ss-fresh", "1"); } catch {}
        location.reload();
      } else {
        el.style.transition = "transform .3s, opacity .3s";
        show(0);
        setTimeout(() => (el.style.transition = ""), 300);
      }
      pull = 0;
    });
  }

  function showQr() {
    const s = document.createElement("script");
    s.src = "https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js";
    s.onload = () =>
      new QRCode(document.getElementById("qr"), {
        text: location.href, width: 400, height: 400,
        colorDark: "#1c1c1e", colorLight: "#ffffff", correctLevel: QRCode.CorrectLevel.M,
      });
    document.head.append(s);
  }
})();
