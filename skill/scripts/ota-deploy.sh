#!/bin/zsh
# Build an iOS app, export a development .ipa and publish an OTA install page over Tailscale HTTPS.
# Optionally install and launch it on a connected iPhone via CoreDevice (--push).
#
# Usage: ota-deploy.sh [--scheme NAME] [--project X.xcodeproj | --workspace X.xcworkspace] [--push]
# Run from the app's project directory.
set -euo pipefail

SCHEME="" CONTAINER=() PUSH=0
while (( $# )); do
  case $1 in
    --scheme) SCHEME=$2; shift 2 ;;
    --project|--workspace) CONTAINER=("-${1#--}" "$2"); shift 2 ;;
    --push) PUSH=1; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

die() { echo "error: $*" >&2; exit 1; }

# Find the project container: workspace first (CocoaPods/SPM setups), then project.
if (( ! ${#CONTAINER} )); then
  ws=(*.xcworkspace(N)) pj=(*.xcodeproj(N))
  if (( ${#ws} )); then CONTAINER=(-workspace "$ws[1]")
  elif (( ${#pj} )); then CONTAINER=(-project "$pj[1]")
  else die "no .xcodeproj or .xcworkspace in $PWD"; fi
fi

if [[ -z $SCHEME ]]; then
  SCHEME=$(xcodebuild "${CONTAINER[@]}" -list -json 2>/dev/null | python3 -c '
import json,sys
d=json.load(sys.stdin); d=d.get("workspace") or d.get("project")
print(d["schemes"][0] if d["schemes"] else "")')
  [[ -n $SCHEME ]] || die "no schemes found, pass --scheme"
fi

# Read signing and identity from the app target's build settings.
eval "$(xcodebuild "${CONTAINER[@]}" -scheme "$SCHEME" -configuration Release \
  -destination generic/platform=iOS -showBuildSettings -json 2>/dev/null | python3 -c '
import json,sys,shlex
for t in json.load(sys.stdin):
    s=t["buildSettings"]
    if s.get("WRAPPER_EXTENSION")=="app":
        for k in ("PRODUCT_BUNDLE_IDENTIFIER","DEVELOPMENT_TEAM","PRODUCT_NAME","MARKETING_VERSION"):
            print(k+"="+shlex.quote(s.get(k) or ""))
        break')"
[[ -n ${PRODUCT_BUNDLE_IDENTIFIER:-} ]] || die "could not find an iOS app target in scheme $SCHEME"
[[ -n ${DEVELOPMENT_TEAM:-} ]] || die "DEVELOPMENT_TEAM is not set for $SCHEME; set a signing team in Xcode"

command -v tailscale >/dev/null || die "tailscale CLI not found"
HOST=$(tailscale status --json | python3 -c 'import json,sys;print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')
[[ -n $HOST ]] || die "Tailscale is not connected"

SLUG=$(print -r -- "$PRODUCT_NAME" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | sed 's/^-//;s/-$//')
BASE="https://$HOST/$SLUG"
BUILD=$(date +%Y%m%d.%H%M%S)
WORK=build/ota-deploy
WWW=$HOME/.sideshelf/www
OUT=$WWW/$SLUG
PORT=8473

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

echo "Building $SCHEME ($PRODUCT_BUNDLE_IDENTIFIER) build $BUILD..."
xcodebuild "${CONTAINER[@]}" -scheme "$SCHEME" -configuration Release \
  -destination generic/platform=iOS -archivePath "$WORK/App.xcarchive" \
  -allowProvisioningUpdates CURRENT_PROJECT_VERSION="$BUILD" archive -quiet
xcodebuild -exportArchive -archivePath "$WORK/App.xcarchive" \
  -exportOptionsPlist "$WORK/ExportOptions.plist" -exportPath "$WORK/export" \
  -allowProvisioningUpdates -quiet
IPA=("$WORK"/export/*.ipa(N))
(( ${#IPA} )) || die "export produced no .ipa"
cp "$IPA[1]" "$OUT/app.ipa"

MANIFEST_URL=$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1],safe=""))' "$BASE/manifest.plist")
TITLE=$(print -r -- "$PRODUCT_NAME" | sed 's/&/\&amp;/g;s/</\&lt;/g')

cat > "$OUT/manifest.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>items</key><array><dict>
  <key>assets</key><array><dict>
    <key>kind</key><string>software-package</string>
    <key>url</key><string>$BASE/app.ipa</string>
  </dict></array>
  <key>metadata</key><dict>
    <key>bundle-identifier</key><string>$PRODUCT_BUNDLE_IDENTIFIER</string>
    <key>bundle-version</key><string>$BUILD</string>
    <key>kind</key><string>software</string>
    <key>title</key><string>$TITLE</string>
  </dict>
</dict></array></dict></plist>
PLIST

cat > "$OUT/index.html" <<HTML
<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>$TITLE</title>
<body style="font:18px -apple-system;text-align:center;padding:60px 20px">
<h1>$TITLE</h1><p>${MARKETING_VERSION:-} (build $BUILD)</p>
<a style="display:inline-block;padding:16px 32px;background:#007aff;color:#fff;border-radius:14px;text-decoration:none"
   href="itms-services://?action=download-manifest&amp;url=$MANIFEST_URL">Установить</a>
<p><a href="/">Все приложения</a></p>
</body>
HTML

# Root page listing every published app.
{
  print '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
  print '<title>Sideshelf</title><body style="font:18px -apple-system;padding:40px 20px"><h1>Sideshelf</h1><ul>'
  for d in "$WWW"/*/index.html(N); do
    s=${d:h:t}; t=$(sed -n 's:.*<title>\(.*\)</title>.*:\1:p' "$d")
    print "<li style=\"margin:12px 0\"><a href=\"/$s/\">$t</a></li>"
  done
  print '</ul></body>'
} > "$WWW/index.html"

# App Store Tailscale on macOS can't serve folders directly, so proxy to a local static server.
if ! lsof -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
  nohup python3 -m http.server $PORT --bind 127.0.0.1 --directory "$WWW" >"$HOME/.sideshelf/http.log" 2>&1 &
  for _ in {1..20}; do curl -s -o /dev/null "http://127.0.0.1:$PORT/" && break; sleep 0.25; done
fi
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
    xcrun devicectl device install app --device "$DEVICE" "$OUT/app.ipa" >/dev/null
    xcrun devicectl device process launch --terminate-existing --device "$DEVICE" "$PRODUCT_BUNDLE_IDENTIFIER" >/dev/null
    echo "Installed and launched on device $DEVICE"
  fi
fi
