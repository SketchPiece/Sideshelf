---
name: sideshelf
description: Ship the current iOS app (Xcode project) to the user's iPhone. Builds a development .ipa, publishes an over-the-air install page via Tailscale HTTPS, and optionally installs and launches it directly on a connected iPhone. Use when the user says "залей на телефон", "поставь на айфон", "обнови приложение на телефоне", "собери и установи", "deploy to my phone", "install on my iPhone", "push a build", or invokes /sideshelf. Also use to set this up in a new iOS project.
---

# Sideshelf

Gets a fresh build of the current iOS app onto the user's iPhone, from anywhere on their tailnet.
Everything is in one script: `~/.claude/skills/sideshelf/scripts/ota-deploy.sh`.

## How it works

1. `xcodebuild archive` + `-exportArchive` with `method: debugging` (development signing,
   automatic provisioning). The build number is set to a timestamp (`YYYYMMDD.HHMMSS`) so every
   build is newer than the last. The phone is already in the dev profile, so no ad-hoc needed.
2. Each build gets its own folder `~/.sideshelf/www/<app-slug>/builds/<build>/` with the `.ipa`,
   a `manifest.plist` and `meta.json` (version, size, min iOS, git sha, and "what's new": subjects of
   commits touching the project directory since the previous published build, the last 5 on the first
   one, plus a flag for uncommitted changes). The newest 10 builds are kept (`SIDESHELF_KEEP`).
   The app icon is pulled from the archive into `<app-slug>/icon.png`.
   `scripts/render.py` then draws the storefront (`/`) and an App Store-style page per app with the
   build history, each build installable via `itms-services://`. Light/dark follows the phone; on a
   desktop the pages show a QR code of the page instead of install buttons.
3. A local `python3 -m http.server 8473` on 127.0.0.1 serves that folder, and
   `tailscale serve --bg 8473` exposes it at `https://<mac>.<tailnet>.ts.net/` with a real
   certificate (iOS refuses OTA installs without valid HTTPS). The App Store build of Tailscale
   on macOS cannot serve folders directly (sandbox), hence the proxy.
4. `--push`: if Xcode can reach an iPhone (cable or same Wi-Fi), `xcrun devicectl` installs the
   `.ipa` and launches the app with no taps. Over Tailscale alone this usually doesn't work
   (CoreDevice discovery relies on local-network mDNS), so the page is the fallback.

## Steps

1. Run from the directory containing the `.xcodeproj` / `.xcworkspace`:
   ```
   ~/.claude/skills/sideshelf/scripts/ota-deploy.sh --push
   ```
   Options: `--scheme NAME` (default: first scheme), `--project X.xcodeproj` /
   `--workspace X.xcworkspace` (default: auto-detect, workspace first), `--push`.
   Archiving takes a minute or more; use a 10-minute timeout.
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
- The local server doesn't survive a reboot; the next run of the script restarts it.
- To stop serving: `tailscale serve --https=443 off` and `pkill -f "http.server 8473"`.
