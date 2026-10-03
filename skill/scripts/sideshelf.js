// Relative build times, the share button, the offline service worker, what's on the iPhone
// ("Open" / "Update"), and a QR code of the page on desktop.
(() => {
  const T = {
    en: {
      now: "just now", minAgo: (n) => `${n} min ago`, today: (t) => `Today, ${t}`, yesterday: (t) => `Yesterday, ${t}`,
      install: "Install", open: "Open", update: "Update", opening: "Opening…", failed: "Didn’t work", onPhone: "On iPhone",
    },
    ru: {
      now: "только что", minAgo: (n) => `${n} мин назад`, today: (t) => `Сегодня, ${t}`, yesterday: (t) => `Вчера, ${t}`,
      install: "Установить", open: "Открыть", update: "Обновить", opening: "Открываю…", failed: "Не вышло", onPhone: "На телефоне",
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
  else watchPhone();

  // The Mac asks the iPhone (over CoreDevice) which builds are installed; buttons follow.
  function watchPhone() {
    const buttons = [...document.querySelectorAll("a[data-latest]")];
    const rows = [...document.querySelectorAll("details[data-build]")];
    if (!buttons.length) return;
    const originals = new Map(buttons.map((b) => [b, b.getAttribute("href")]));
    const rowActions = new Map(rows.map((r) => [r, {
      own: r.querySelector("summary > :last-child"),
      onPhone: Object.assign(document.createElement("span"), { className: "tag", textContent: T.onPhone }),
    }]));

    const apply = (state) => {
      const apps = state?.apps ?? {};
      document.getElementById("phone")?.toggleAttribute("hidden", !state?.device);
      for (const b of buttons) {
        const installed = apps[b.dataset.bundle];
        b.dataset.state = !state?.device || !installed ? "install" : installed.build === b.dataset.latest ? "open" : "update";
        b.textContent = T[b.dataset.state];
        b.setAttribute("href", originals.get(b));
      }
      for (const r of rows) {
        const { own, onPhone } = rowActions.get(r);
        const wanted = state?.device && apps[r.dataset.bundle]?.build === r.dataset.build ? onPhone : own;
        const current = r.querySelector("summary > :last-child");
        if (current !== wanted) current.replaceWith(wanted);
      }
    };

    const refresh = (fresh) =>
      fetch(`/api/device${fresh ? "?fresh=1" : ""}`, { cache: "no-store" })
        .then((r) => (r.ok ? r.json() : null))
        .then(apply)
        .catch(() => {});

    for (const b of buttons) {
      b.addEventListener("click", (e) => {
        if (b.dataset.state !== "open") return; // install/update: follow the itms-services link
        e.preventDefault();
        b.textContent = T.opening;
        fetch("/api/open", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ bundle_id: b.dataset.bundle }) })
          .then((r) => { if (!r.ok) throw new Error(r.status); b.textContent = T.open; })
          .catch(() => { b.textContent = T.failed; setTimeout(() => refresh(true), 1500); });
      });
    }

    refresh(false);
    // Coming back from an install (or from the app) re-checks without the server's cache.
    document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(true); });
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
