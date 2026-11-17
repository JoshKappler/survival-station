#!/bin/zsh
# Builds "Survival Station.app" on the Desktop; double-clicking it runs start.sh.
ROOT="${0:A:h:h}"
APP="$HOME/Desktop/Survival Station.app"
rm -rf "$APP"
osacompile -o "$APP" -e "do shell script \"'$ROOT/bin-mac/start.sh' >/dev/null 2>&1 &\""
ICONSET=$(mktemp -d)/icon.iconset; mkdir -p "$ICONSET"
sips -s format png "$ROOT/app/icons/survival.ico" --out "$ICONSET/src.png" >/dev/null
for s in 16 32 128 256 512; do
  sips -z $s $s "$ICONSET/src.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) "$ICONSET/src.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
rm "$ICONSET/src.png"
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/applet.icns"
rm -f "$APP/Contents/Resources/Assets.car"
/usr/libexec/PlistBuddy -c "Delete :CFBundleIconName" "$APP/Contents/Info.plist" 2>/dev/null
codesign --force -s - "$APP" 2>/dev/null
touch "$APP"
