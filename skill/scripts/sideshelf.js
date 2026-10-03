// Relative build times, the share button, and a QR code of the page on desktop.
(() => {
  const pad = (n) => String(n).padStart(2, "0");
  const now = new Date();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  for (const t of document.querySelectorAll("time[data-rel]")) {
    const d = new Date(t.dateTime);
    if (isNaN(d)) continue;
    const min = Math.round((now - d) / 60000);
    const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
    if (min < 1) t.textContent = "только что";
    else if (min < 60) t.textContent = `${min} мин назад`;
    else if (d.toDateString() === now.toDateString()) t.textContent = `Сегодня, ${hm}`;
    else if (d.toDateString() === yesterday.toDateString()) t.textContent = `Вчера, ${hm}`;
  }

  for (const b of document.querySelectorAll("[data-share]")) {
    b.addEventListener("click", () => {
      if (navigator.share) navigator.share({ title: document.title, url: location.href }).catch(() => {});
      else navigator.clipboard?.writeText(location.href);
    });
  }

  if (!document.documentElement.classList.contains("desktop")) return;
  const s = document.createElement("script");
  s.src = "https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js";
  s.onload = () =>
    new QRCode(document.getElementById("qr"), {
      text: location.href, width: 400, height: 400,
      colorDark: "#1c1c1e", colorLight: "#ffffff", correctLevel: QRCode.CorrectLevel.M,
    });
  document.head.append(s);
})();
