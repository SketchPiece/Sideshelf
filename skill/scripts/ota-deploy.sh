#!/bin/zsh
# Build an iOS app, export a development .ipa and publish an OTA install page over Tailscale HTTPS.
# Keeps the last $SIDESHELF_KEEP (10) builds with commit notes; render.py draws the pages.
# Optionally install and launch it on a connected iPhone via CoreDevice (--push).
#
# Usage: ota-deploy.sh [--scheme NAME] [--project X.xcodeproj | --workspace X.xcworkspace] [--push]
#        ota-deploy.sh --ipa path/to/App.ipa [--push]
# Run from the app's project directory. --ipa publishes an already signed development .ipa
# (e.g. from a Bazel build) instead of archiving with xcodebuild; name, bundle id and versions
# come from the app's Info.plist.
set -euo pipefail

SCHEME="" CONTAINER=() PUSH=0 PREBUILT=""
while (( $# )); do
  case $1 in
    --scheme) SCHEME=$2; shift 2 ;;
    --project|--workspace) CONTAINER=("-${1#--}" "$2"); shift 2 ;;
    --push) PUSH=1; shift ;;
    --ipa) PREBUILT=${2:A}; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

die() { echo "error: $*" >&2; exit 1; }

if [[ -n $PREBUILT ]]; then
  [[ -f $PREBUILT ]] || die "no such .ipa: $PREBUILT"
  plist=$(mktemp)
  unzip -p "$PREBUILT" 'Payload/*.app/Info.plist' > "$plist" || die "no Payload/*.app/Info.plist in $PREBUILT"
  pl() { plutil -extract "$1" raw "$plist" 2>/dev/null || true; }
  PRODUCT_BUNDLE_IDENTIFIER=$(pl CFBundleIdentifier) PRODUCT_NAME=$(pl CFBundleName)
  INFOPLIST_KEY_CFBundleDisplayName=$(pl CFBundleDisplayName) MARKETING_VERSION=$(pl CFBundleShortVersionString)
  BUNDLE_VERSION=$(pl CFBundleVersion)
  rm -f "$plist"
  [[ -n $PRODUCT_BUNDLE_IDENTIFIER ]] || die "no CFBundleIdentifier in $PREBUILT"
fi

# Find the project container: workspace first (CocoaPods/SPM setups), then project.
if [[ -z $PREBUILT ]] && (( ! ${#CONTAINER} )); then
  ws=(*.xcworkspace(N)) pj=(*.xcodeproj(N))
  if (( ${#ws} )); then CONTAINER=(-workspace "$ws[1]")
  elif (( ${#pj} )); then CONTAINER=(-project "$pj[1]")
  else die "no .xcodeproj or .xcworkspace in $PWD"; fi
fi

if [[ -z $PREBUILT && -z $SCHEME ]]; then
  SCHEME=$(xcodebuild "${CONTAINER[@]}" -list -json 2>/dev/null | python3 -c '
import json,sys
d=json.load(sys.stdin); d=d.get("workspace") or d.get("project")
print(d["schemes"][0] if d["schemes"] else "")')
  [[ -n $SCHEME ]] || die "no schemes found, pass --scheme"
fi

# Read signing and identity from the app target's build settings.
[[ -n $PREBUILT ]] || eval "$(xcodebuild "${CONTAINER[@]}" -scheme "$SCHEME" -configuration Release \
  -destination generic/platform=iOS -showBuildSettings -json 2>/dev/null | python3 -c '
import json,sys,shlex
for t in json.load(sys.stdin):
    s=t["buildSettings"]
    if s.get("WRAPPER_EXTENSION")=="app":
        for k in ("PRODUCT_BUNDLE_IDENTIFIER","DEVELOPMENT_TEAM","PRODUCT_NAME","MARKETING_VERSION","INFOPLIST_FILE","SRCROOT","INFOPLIST_KEY_CFBundleDisplayName"):
            print(k+"="+shlex.quote(s.get(k) or ""))
        break')"
[[ -n ${PRODUCT_BUNDLE_IDENTIFIER:-} ]] || die "could not find an iOS app target in scheme $SCHEME"
[[ -n $PREBUILT || -n ${DEVELOPMENT_TEAM:-} ]] || die "DEVELOPMENT_TEAM is not set for $SCHEME; set a signing team in Xcode"

command -v tailscale >/dev/null || die "tailscale CLI not found"
HOST=$(tailscale status --json | python3 -c 'import json,sys;print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')
[[ -n $HOST ]] || die "Tailscale is not connected"

# The name under the icon (CFBundleDisplayName) names the app; PRODUCT_NAME is the fallback,
# since generated projects (Expo) often keep an internal ASCII product name.
APP_NAME=${INFOPLIST_KEY_CFBundleDisplayName:-}
if [[ -z $APP_NAME && -n ${INFOPLIST_FILE:-} ]]; then
  plist=$INFOPLIST_FILE; [[ $plist == /* ]] || plist=$SRCROOT/$plist
  APP_NAME=$(plutil -extract CFBundleDisplayName raw "$plist" 2>/dev/null || true)
fi
[[ -z $APP_NAME || $APP_NAME == *'$('* ]] && APP_NAME=$PRODUCT_NAME

slugify() { print -r -- "$1" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | sed 's/^-//;s/-$//'; }
SLUG=$(slugify "$APP_NAME")
# Non-Latin display names (e.g. Cyrillic) leave nothing; use PRODUCT_NAME for the URL then.
[[ -n $SLUG ]] || SLUG=$(slugify "$PRODUCT_NAME")
[[ -n $SLUG ]] || die "could not derive a URL slug from '$APP_NAME' or PRODUCT_NAME"
BASE="https://$HOST/$SLUG"
BUILD=$(date +%Y%m%d.%H%M%S)
BUNDLE_VERSION=${BUNDLE_VERSION:-$BUILD}  # xcodebuild builds are stamped with $BUILD
WORK=build/ota-deploy
WWW=$HOME/.sideshelf/www
OUT=$WWW/$SLUG
PORT=8473
KEEP=${SIDESHELF_KEEP:-10}

rm -rf "$WORK" && mkdir -p "$WORK" "$OUT"
cat > "$WORK/ExportOptions.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>method</key><string>debugging</string>
  <key>teamID</key><string>$DEVELOPMENT_TEAM</string>
  <key>signingStyle</key><string>automatic</string>
  <key>thinning</key><string>&lt;none&gt;</string>
</dict></plist>
PLIST

if [[ -n $PREBUILT ]]; then
  echo "Publishing $PREBUILT ($PRODUCT_BUNDLE_IDENTIFIER $MARKETING_VERSION ($BUNDLE_VERSION))..."
  unzip -q "$PREBUILT" 'Payload/*' -d "$WORK/prebuilt"
  IPA=("$PREBUILT")
  APP=("$WORK"/prebuilt/Payload/*.app(N))
else
  echo "Building $SCHEME ($PRODUCT_BUNDLE_IDENTIFIER) build $BUILD..."
  xcodebuild "${CONTAINER[@]}" -scheme "$SCHEME" -configuration Release \
    -destination generic/platform=iOS -archivePath "$WORK/App.xcarchive" \
    -allowProvisioningUpdates CURRENT_PROJECT_VERSION="$BUILD" archive -quiet
  xcodebuild -exportArchive -archivePath "$WORK/App.xcarchive" \
    -exportOptionsPlist "$WORK/ExportOptions.plist" -exportPath "$WORK/export" \
    -allowProvisioningUpdates -quiet
  IPA=("$WORK"/export/*.ipa(N))
  (( ${#IPA} )) || die "export produced no .ipa"
  APP=("$WORK"/App.xcarchive/Products/Applications/*.app(N))
fi

# What's new: subjects of commits touching this directory since the previous published build
# (the last 5 on the first build). NOTES stays unset outside a git repo.
GIT=0 NOTES="" DIRTY=0 SHA=""
if SHA=$(git rev-parse -q --verify HEAD 2>/dev/null); then
  GIT=1
  PREV=$(python3 -c '
import json,sys,pathlib
ms=sorted(pathlib.Path(sys.argv[1]).glob("builds/*/meta.json"))
print((json.loads(ms[-1].read_text()).get("sha") or "") if ms else "")' "$OUT")
  if [[ -n $PREV ]] && git cat-file -e "$PREV^{commit}" 2>/dev/null; then
    NOTES=$(git log --no-merges -n 20 --format=%s "$PREV..HEAD" -- .)
  else
    NOTES=$(git log --no-merges -n 5 --format=%s HEAD -- .)
  fi
  [[ -z $(git status --porcelain -- . 2>/dev/null) ]] || DIRTY=1
fi

# Each build keeps its own folder: builds/<build>/{app.ipa,manifest.plist,meta.json}.
DEST=$OUT/builds/$BUILD
mkdir -p "$DEST"
cp "$IPA[1]" "$DEST/app.ipa"
rm -f "$OUT/app.ipa" "$OUT/manifest.plist"  # layout before build history

# App icon: the largest loose AppIcon*.png, re-encoded since Xcode stores them as CgBI PNGs browsers can't read.
icons=("$APP[1]"/AppIcon*.png(NOL))
# Icon Composer (.icon) app icons are named after the icon, e.g. Semafor60x60@2x.png.
(( ${#icons} )) || icons=("$APP[1]"/*60x60@*.png(NOL))
(( ${#icons} )) && sips -s format png "$icons[1]" --out "$OUT/icon.png" >/dev/null 2>&1 || true

TITLE=$(print -r -- "$APP_NAME" | sed 's/&/\&amp;/g;s/</\&lt;/g')
cat > "$DEST/manifest.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>items</key><array><dict>
  <key>assets</key><array><dict>
    <key>kind</key><string>software-package</string>
    <key>url</key><string>$BASE/builds/$BUILD/app.ipa</string>
  </dict></array>
  <key>metadata</key><dict>
    <key>bundle-identifier</key><string>$PRODUCT_BUNDLE_IDENTIFIER</string>
    <key>bundle-version</key><string>$BUNDLE_VERSION</string>
    <key>kind</key><string>software</string>
    <key>title</key><string>$TITLE</string>
  </dict>
</dict></array></dict></plist>
PLIST

SS_NAME=$APP_NAME SS_BUNDLE=$PRODUCT_BUNDLE_IDENTIFIER SS_VERSION=${MARKETING_VERSION:-} SS_BUILD=$BUILD \
SS_MIN_OS=$(plutil -extract MinimumOSVersion raw "$APP[1]/Info.plist" 2>/dev/null || true) \
SS_SIZE=$(stat -f%z "$DEST/app.ipa") SS_GIT=$GIT SS_NOTES=$NOTES SS_DIRTY=$DIRTY SS_SHA=$SHA \
python3 - "$DEST/meta.json" <<'PY'
import json, os, sys
from datetime import datetime
e = os.environ
json.dump({
    "name": e["SS_NAME"], "bundle_id": e["SS_BUNDLE"], "version": e["SS_VERSION"], "build": e["SS_BUILD"],
    "date": datetime.now().astimezone().isoformat(timespec="seconds"), "size": int(e["SS_SIZE"]),
    "min_os": e["SS_MIN_OS"] or None, "sha": e["SS_SHA"] or None,
    "notes": [l for l in e["SS_NOTES"].splitlines() if l.strip()] if e["SS_GIT"] == "1" else None,
    "dirty": e["SS_DIRTY"] == "1",
}, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
PY

# Keep the newest $KEEP builds.
old=("$OUT"/builds/*(N/On))
for d in $old[KEEP+1,-1]; do rm -rf "$d"; done

python3 "${0:A:h}/render.py" "$WWW" "https://$HOST"

# App Store Tailscale on macOS can't serve folders directly, so proxy to a local server.
# Restart it on every deploy so it always runs the current server.py.
PIDFILE=$HOME/.sideshelf/server.pid
[[ -f $PIDFILE ]] && kill "$(cat "$PIDFILE")" 2>/dev/null || true
pkill -f "http.server $PORT" 2>/dev/null || true  # static server from before server.py
for _ in {1..20}; do lsof -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1 || break; sleep 0.25; done
nohup python3 "${0:A:h}/server.py" "$WWW" $PORT >>"$HOME/.sideshelf/http.log" 2>&1 &
for _ in {1..20}; do curl -s -o /dev/null "http://127.0.0.1:$PORT/" && break; sleep 0.25; done
tailscale serve --bg $PORT >/dev/null || die "tailscale serve failed (is Serve/HTTPS enabled on the tailnet?)"

echo "Published: $BASE/"

if (( PUSH )); then
  xcrun devicectl list devices -q -j "$WORK/devices.json"
  DEVICE=$(python3 -c '
import json,sys
for d in json.load(open(sys.argv[1]))["result"]["devices"]:
    if d["hardwareProperties"].get("deviceType")=="iPhone" and d["connectionProperties"].get("tunnelState")!="unavailable":
        print(d["identifier"]); break' "$WORK/devices.json")
  if [[ -z $DEVICE ]]; then
    echo "No reachable iPhone for --push; install from the page instead."
  else
    xcrun devicectl device install app --device "$DEVICE" "$DEST/app.ipa" >/dev/null
    xcrun devicectl device process launch --terminate-existing --device "$DEVICE" "$PRODUCT_BUNDLE_IDENTIFIER" >/dev/null
    echo "Installed and launched on device $DEVICE"
  fi
fi
