---
name: sideshelf
description: Ship the current iOS app (Xcode project) to the user's iPhone. Builds a development .ipa, publishes an over-the-air install page via Tailscale HTTPS, and optionally installs and launches it directly on a connected iPhone or iPad. Use when the user says "залей на телефон", "поставь на айфон", "обнови приложение на телефоне", "собери и установи", "deploy to my phone", "install on my iPhone", "поставь на айпад", "install on my iPad", "push a build", or invokes /sideshelf. Also use to set this up in a new iOS project.
---

# Sideshelf

Gets a fresh build of the current iOS app onto the user's iPhone or iPad, from anywhere on their tailnet.
Everything is in one script: `~/.claude/skills/sideshelf/scripts/ota-deploy.sh`.

## How it works

1. `xcodebuild archive` + `-exportArchive` with `method: debugging` (development signing,
   automatic provisioning). The app is named by its `CFBundleDisplayName` (the name under the icon),
   falling back to `PRODUCT_NAME`; the page slug comes from that name. The build number is set to a timestamp (`YYYYMMDD.HHMMSS`) so every
   build is newer than the last. The phone is already in the dev profile, so no ad-hoc needed.
2. Each build gets its own folder `~/.sideshelf/www/<app-slug>/builds/<build>/` with the `.ipa`,
   a `manifest.plist` and `meta.json` (version, size, min iOS, git sha, and "what's new": subjects of
   commits touching the project directory since the previous published build, the last 5 on the first
   one, plus a flag for uncommitted changes). The newest 10 builds are kept (`SIDESHELF_KEEP`).
   The app icon is pulled from the archive into `<app-slug>/icon.png`.
   `scripts/render.py` then draws the storefront (`/`) and an App Store-style page per app with the
   build history, each build installable via `itms-services://`. Light/dark follows the phone; on a
   desktop the pages show a QR code of the page instead of install buttons. Pages are rendered in
   English (`index.html`) and Russian (`index.ru.html`); the server picks one from `Accept-Language`,
   which on iOS follows the system language.
   The site is a PWA (manifest + `sw.js`): added to the Home Screen it opens like an app, pages
   push in with cross-document view transitions, and when the Mac can't be reached (Tailscale off,
   Mac asleep) the service worker shows `offline.html`, which reloads by itself once the Mac answers.
3. `scripts/server.py` on 127.0.0.1:8473 serves that folder. It runs as the LaunchAgent
   `com.sideshelf.server` (`~/Library/LaunchAgents/com.sideshelf.server.plist`, `RunAtLoad` +
   `KeepAlive`), so it comes back after a reboot or crash. Every deploy copies `server.py` to
   `~/.sideshelf/` (launchd agents can't read `~/Documents`) and reloads the agent. Then
   `tailscale serve --bg 8473` exposes it at `https://<mac>.<tailnet>.ts.net/` with a real
   certificate (iOS refuses OTA installs without valid HTTPS). The App Store build of Tailscale
   on macOS cannot serve folders directly (sandbox), hence the proxy.
4. `--push`: on every iPhone and iPad Xcode can reach (cable or same Wi-Fi), `xcrun devicectl`
   installs the `.ipa` and launches the app with no taps. The iPad must be in the team's
   provisioning profile too (run something on it from Xcode once). Over Tailscale alone this usually doesn't work
   (CoreDevice discovery relies on local-network mDNS), so the page is the fallback.

## Steps

1. Run from the directory containing the `.xcodeproj` / `.xcworkspace`:
   ```
   ~/.claude/skills/sideshelf/scripts/ota-deploy.sh --push
   ```
   Options: `--scheme NAME` (default: first scheme), `--project X.xcodeproj` /
   `--workspace X.xcworkspace` (default: auto-detect, workspace first), `--push`.
   Archiving takes a minute or more; use a 10-minute timeout.
   Projects that aren't built by Xcode (e.g. Bazel) pass an already signed development `.ipa`
   instead: `ota-deploy.sh --ipa path/to/App.ipa [--push]`, run from the repo root (for the
   "what's new" notes). Name, bundle id and versions come from the app's Info.plist; the
   project's own script builds the `.ipa` (Semafor: `scripts/semafor-deploy-iphone.sh`).
2. Report the result. Always give the install page as a clickable markdown link, e.g.
   `[Установить <App>](https://host.ts.net/<slug>/)`, never in backticks. Say whether `--push`
   installed and launched it, or that the user needs to tap "Установить" on the page.
3. Add `build/` to the project's `.gitignore` if the project uses git and it isn't ignored.

## Requirements and troubleshooting

- Target must have a signing team (`DEVELOPMENT_TEAM`). If missing, ask the user which team or
  set it in the project. The user's dev team so far: `YOURTEAMID`.
- Tailscale must be running on the Mac and on the iPhone. Serve/HTTPS must be enabled on the
  tailnet; if `tailscale serve` prints an enable link, give it to the user as a markdown link.
- Tap does nothing on the page → check `~/.sideshelf/http.log`. No `manifest.plist` request means
  iOS rejected the link (open it in Safari itself, not an in-app browser). Manifest fetched but
  no `.ipa` request → bundle id or URL mismatch in the manifest.
- "Unable to install" after download → the device isn't in the provisioning profile; run once
  from Xcode with the phone connected, or let `-allowProvisioningUpdates` register it.
- Garbled text on the page → missing `<meta charset="utf-8">` (the script includes it).
- Server not answering → `launchctl print gui/$UID/com.sideshelf.server` and `~/.sideshelf/http.log`.
- The server also asks the iPhone and the iPad over CoreDevice which builds are installed
  (`GET /api/device?type=iPhone|iPad`, cached ~20 s) and can launch a published app (`POST /api/open`),
  so pages show "Открыть" / "Обновить" / "Установить" and mark the build that is on the device.
  A page asks about its own kind of device (iPadOS Safari is told apart by touch points). This needs
  the device on the same Wi-Fi as the Mac or on a cable; otherwise pages fall back to plain "Установить".
- Tapping Install arms `POST /api/install`; the server counts the `.ipa` bytes iOS downloads and the
  button becomes a progress ring, then spins until the Mac sees the build on the phone ("Открыть"),
  or shows "Установлено" a few seconds after the download if the phone is out of reach. No download
  within a minute means the iOS alert was cancelled, and the button comes back.
- To stop serving: `tailscale serve --https=443 off` and
  `launchctl bootout gui/$UID/com.sideshelf.server && rm ~/Library/LaunchAgents/com.sideshelf.server.plist`.
