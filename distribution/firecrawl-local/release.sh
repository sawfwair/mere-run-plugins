#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$root/../.." && pwd)"
version=0.1.1
crate_sha256=5a0f837d8b3687aab45c6d4ad5c2dddf21849c883501e24145df4c32787be964
upstream=7c16513e6ada9df5d9a6cfa6a1a1cfda3c841f9d
prefix="firecrawl-local-$version"
image="$prefix-macos-arm64.dmg"
source_archive="$prefix-source.tar.gz"
object_prefix="releases/firecrawl-local/$version"

die() {
  echo "$*" >&2
  exit 1
}

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 build|sign|publish|plan-publish OUTPUT_DIRECTORY" >&2
  exit 2
fi
action="$1"

if [[ "$action" == plan-publish ]]; then
  for name in "$source_archive" SHA256SUMS "$image"; do
    printf 's3://%s/%s/%s\n' "${R2_BUCKET:-BUCKET}" "$object_prefix" "$name"
  done
  exit 0
fi

mkdir -p "$2"
out="$(cd "$2" && pwd)"
app="$out/Firecrawl Local.app"
public_origin() {
  [[ "${PUBLIC_BASE_URL:-}" == https://* ]] || die "Set PUBLIC_BASE_URL to the HTTPS public origin."
}

case "$action" in
  build)
    [[ "$(uname -sm)" == "Darwin arm64" ]] || die "Build on an Apple Silicon Mac."
    [[ ! -e "$app" && ! -e "$out/$source_archive" ]] || die "Choose a fresh output directory."
    work="$(mktemp -d "${TMPDIR:-/tmp}/firecrawl-local-release.XXXXXX")"
    trap 'rm -rf "$work"' EXIT
    packaged="$work/$prefix.crate"
    curl --fail --silent --show-error --location \
      "https://static.crates.io/crates/firecrawl-local/$prefix.crate" --output "$packaged"
    printf '%s  %s\n' "$crate_sha256" "$packaged" | shasum -a 256 -c -
    source_root="$work/$prefix-source"
    mkdir "$source_root"
    tar -xzf "$packaged" -C "$source_root"
    crate="$source_root/$prefix"
    curl --fail --silent --show-error --location \
      "https://raw.githubusercontent.com/firecrawl/firecrawl/$upstream/LICENSE" --output "$crate/LICENSE"
    cp "$root/Launcher.swift" "$root/Info.plist" "$root/build-app.sh" "$source_root/"
    cp "$repo/LICENSE" "$source_root/LICENSE-launcher"
    {
      printf 'Firecrawl Local %s\nUpstream revision: %s\nPublished crate SHA-256: %s\n' \
        "$version" "$upstream" "$crate_sha256"
      rustc --version --verbose
      cargo --version
    } > "$source_root/BUILD-INFO.txt"
    (
      cd "$crate"
      mkdir -p .cargo
      cargo vendor --locked vendor > .cargo/config.toml
      cargo metadata --offline --locked --format-version 1 | python3 -c '
import json, sys
packages = json.load(sys.stdin)["packages"]
fields = ("name", "version", "license", "license_file", "repository", "source")
json.dump([{key: item[key] for key in fields} for item in sorted(
    packages, key=lambda item: (item["name"], item["version"]))], sys.stdout, indent=2)
print()
' > "$source_root/DEPENDENCIES.json"
    )
    python3 - "$crate/vendor" "$source_root/THIRD-PARTY-NOTICES" <<'PYTHON'
from pathlib import Path
from shutil import copyfile
import sys

vendor, notices = map(Path, sys.argv[1:])
prefixes = ("license", "licence", "copyright", "notice", "copying")
for source in vendor.rglob("*"):
    parts = source.relative_to(vendor).parts
    if source.is_file() and any(part.lower().startswith(prefixes) for part in parts[1:]):
        destination = notices.joinpath(*parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        copyfile(source, destination)
PYTHON
    cat > "$source_root/README.txt" <<REBUILD
Build on an Apple Silicon Mac with Xcode and the Rust toolchain in BUILD-INFO.txt.
Run ./build-app.sh $prefix "./Firecrawl Local.app" from this directory.
The build uses the vendored Cargo source and Cargo.lock. For a local build, run
the firecrawl-local executable directly or sign the application for local use.
Firecrawl Local is covered by $prefix/LICENSE. The launcher is covered by
LICENSE-launcher. THIRD-PARTY-NOTICES contains dependency license and notice
files. DEPENDENCIES.json lists the vendored dependencies.
REBUILD
    COPYFILE_DISABLE=1 tar --exclude=.DS_Store -czf "$work/$source_archive" -C "$work" "$prefix-source"
    "$source_root/build-app.sh" "$crate" "$work/Firecrawl Local.app"
    cp "$source_root/DEPENDENCIES.json" "$out/"
    mv "$work/$source_archive" "$out/$source_archive"
    mv "$work/Firecrawl Local.app" "$app"
    ;;
  sign)
    [[ -f "$out/$source_archive" && -d "$app" ]] || die "Build the app and corresponding source first."
    : "${DEVELOPER_ID_APPLICATION:?Set the Developer ID Application signing identity}"
    public_origin
    notary_args=()
    if [[ -n "${KEY_PATH:-}" ]]; then
      notary_args=(--key "$KEY_PATH" --key-id "${KEY_ID:?}" --issuer "${ISSUER_ID:?}")
    else
      notary_args=(--keychain-profile "${NOTARY_PROFILE:?Set the notarization keychain profile}")
    fi
    [[ ! -e "$out/$image" ]] || die "The output DMG already exists."
    work="$(mktemp -d "${TMPDIR:-/tmp}/firecrawl-local-sign.XXXXXX")"
    trap 'rm -rf "$work"' EXIT
    mkdir "$work/image"
    ditto "$app" "$work/image/Firecrawl Local.app"
    printf 'Firecrawl Local is distributed under AGPL-3.0.\nMatching source archive (free download)\n%s/%s/%s\n' \
      "${PUBLIC_BASE_URL%/}" "$object_prefix" "$source_archive" > "$work/image/Source.txt"
    cp "$work/image/Source.txt" "$work/image/Firecrawl Local.app/Contents/Resources/"
    codesign --force --timestamp --options runtime --sign "$DEVELOPER_ID_APPLICATION" \
      "$work/image/Firecrawl Local.app/Contents/MacOS/firecrawl-local"
    codesign --force --timestamp --options runtime --sign "$DEVELOPER_ID_APPLICATION" \
      "$work/image/Firecrawl Local.app"
    codesign --verify --deep --strict "$work/image/Firecrawl Local.app"
    ln -s /Applications "$work/image/Applications"
    hdiutil create -quiet -fs HFS+ -format UDZO -volname "Firecrawl Local" \
      -srcfolder "$work/image" "$work/$image"
    codesign --timestamp --sign "$DEVELOPER_ID_APPLICATION" "$work/$image"
    xcrun notarytool submit "$work/$image" "${notary_args[@]}" --wait
    xcrun stapler staple "$work/$image"
    xcrun stapler validate "$work/$image"
    mv "$work/$image" "$out/$image"
    (cd "$out" && shasum -a 256 "$source_archive" "$image" > SHA256SUMS)
    ;;
  publish)
    : "${R2_BUCKET:?Set the R2 bucket}"
    public_origin
    if [[ "${PUBLIC_BASE_URL%/}" == https://mere.run && "$R2_BUCKET" != mere-run-releases ]]; then
      die "The mere.run release route serves the mere-run-releases bucket."
    fi
    if [[ -n "${R2_WRANGLER_CONFIG:-}" ]]; then
      [[ -f "$R2_WRANGLER_CONFIG" ]] || die "The Wrangler configuration file does not exist."
    else
      : "${CLOUDFLARE_ACCOUNT_ID:?Set the Cloudflare account ID}"
      : "${R2_ACCESS_KEY_ID:?Set the R2 access key ID}"
      : "${R2_SECRET_ACCESS_KEY:?Set the R2 secret access key}"
    fi
    xcrun stapler validate "$out/$image"
    expected="$(cd "$out" && shasum -a 256 "$source_archive" "$image")"
    [[ "$expected" == "$(cat "$out/SHA256SUMS")" ]] || die "Release checksums do not match."
    work="$(mktemp -d "${TMPDIR:-/tmp}/firecrawl-local-publish.XXXXXX")"
    trap 'rm -rf "$work"' EXIT
    publish_asset() {
      local name="$1" content_type="$2" key="$object_prefix/$1"
      local public_url="${PUBLIC_BASE_URL%/}/$key"
      local cache_control='public, max-age=31536000, immutable'
      local status
      status="$(curl --silent --show-error --location --output "$work/$name" --write-out '%{http_code}' "$public_url")"
      if [[ "$status" == 404 ]]; then
        if [[ -n "${R2_WRANGLER_CONFIG:-}" ]]; then
          CI=1 WRANGLER_SEND_METRICS=false npx --yes wrangler@4.165.0 r2 object put "$R2_BUCKET/$key" \
            --remote --config "$R2_WRANGLER_CONFIG" --file "$out/$name" \
            --content-type "$content_type" --cache-control "$cache_control" >&2
        else
          AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
            AWS_REQUEST_CHECKSUM_CALCULATION=when_required aws --no-cli-pager --region auto \
            --endpoint-url "https://$CLOUDFLARE_ACCOUNT_ID.r2.cloudflarestorage.com" \
            s3api put-object --bucket "$R2_BUCKET" --key "$key" --body "$out/$name" \
            --if-none-match '*' --content-type "$content_type" --cache-control "$cache_control" \
            >/dev/null
        fi
        curl --fail --silent --show-error --retry 3 --retry-all-errors --location "$public_url" --output "$work/$name"
      elif [[ "$status" != 200 ]]; then
        die "Public release route returned HTTP $status for $name."
      fi
      cmp -s "$out/$name" "$work/$name" || die "Public asset differs from this release: $name"
      printf '%s\n' "$public_url"
    }
    publish_asset "$source_archive" application/gzip
    publish_asset SHA256SUMS text/plain
    publish_asset "$image" application/x-apple-diskimage
    ;;
  *)
    die "Unknown release action: $action"
    ;;
esac
