#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 UPSTREAM_CRATE_DIRECTORY OUTPUT_APP" >&2
  exit 2
fi
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
crate="$(cd "$1" && pwd)"
app="$2"
target="aarch64-apple-darwin"
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$crate/target}"
export MACOSX_DEPLOYMENT_TARGET=15.0

version="$(sed -n 's/^version = "\([^"]*\)"$/\1/p' "$crate/Cargo.toml" | head -n 1)"
(
  cd "$crate"
  cargo build --offline --locked --release --target "$target"
)
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
cp "$CARGO_TARGET_DIR/$target/release/firecrawl-local" "$app/Contents/MacOS/"
cp "$root/Info.plist" "$app/Contents/Info.plist"
for key in CFBundleVersion CFBundleShortVersionString; do
  /usr/libexec/PlistBuddy -c "Set :$key $version" "$app/Contents/Info.plist"
done
cp "$crate/LICENSE" "$root/LICENSE-launcher" "$root/DEPENDENCIES.json" "$app/Contents/Resources/"
cp -R "$root/THIRD-PARTY-NOTICES" "$app/Contents/Resources/"
xcrun swiftc -O -parse-as-library -target arm64-apple-macos15.0 "$root/Launcher.swift" \
  -o "$app/Contents/MacOS/FirecrawlLocalLauncher"
"$app/Contents/MacOS/firecrawl-local" --version
