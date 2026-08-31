# Signed plugin bundles

This reference is for plugin and CLI maintainers implementing signed macOS
Apple Silicon bundles. A catalog channel may retain source installation as a
portable fallback while advertising a verified bundle to compatible clients.

## Distribution contract

`plugin-bundle.v1.schema.json` describes an installable program. It is distinct
from `artifact-bundle.v1.schema.json`, which inventories workflow results.

The package contains one app bundle inside a read-only DMG. Each declared
plugin ID maps to an identically named executable in `Contents/MacOS`. Native
launchers use a bundled Python runtime; the user's Python environment is not
part of installation or execution. Bundle trees contain only directories and
regular files, and relative links that resolve inside the bundle. Absolute,
escaping, dangling, and special-file links are rejected.

`plugin-bundle-envelope.v1.schema.json` wraps the exact manifest JSON bytes as
base64. The signature is Ed25519 over those decoded bytes, not reserialized
JSON. `keyID` selects a public key shipped in the CLI. Catalogs and envelopes
cannot introduce a trusted key. `mere-release-1` identifies the existing Mere
release signing key. Private key custody stays in the release infrastructure.

The signed payload binds package, version, increasing release sequence,
source commit, platform, minimum macOS version, expiration, entrypoints,
app name, and the HTTPS artifact URL, byte length, and SHA-256. The first
contract supports macOS 15 or later on Apple Silicon only. The app identifier
is `run.mere.plugins.<package>` and the Developer ID team is pinned by the CLI.

The example in `examples/plugin-bundles/document-tools.manifest.json` is
synthetic contract data. Its zero hash and example URL are not a release.

## Catalog compatibility

A source channel can add an optional `bundles` map:

```json
{
  "manager": "pipx",
  "spec": "git+https://github.com/sawfwair/mere-run-plugins.git@main#subdirectory=packages/mere-workflow-tools",
  "bundles": {
    "macos-arm64": "https://example.com/releases/document-tools.release.json"
  }
}
```

Compatible CLIs prefer the advertised bundle. Older CLIs retain the source
install behavior. An explicit `--source` selects pipx. A failed bundle
verification never falls back to installing source. An unsupported bundle
platform requires an explicit source installation choice.

## Verification and activation

Before mounting the DMG, the CLI verifies the publisher signature, expiry,
requested package/plugin, artifact size, and hash. It mounts the image
read-only without opening it, validates link containment, rejects special files, and verifies
the app's Developer ID, identity, signature, and stapled notarization ticket.
The CLI uses `codesign`, `syspolicy_check`, and Gatekeeper tools included in
macOS; installation does not require Xcode or command-line developer tools.
It then checks every plugin manifest and graph provider before and after
relocation. Only a successful result replaces the active-version record.

Updates keep the previous version. A process lock serializes installation and
rollback; a failed check leaves the active version unchanged. A monotonic
sequence rejects downloaded downgrades or conflicting releases. Explicit
rollback revalidates a retained installation without lowering the recorded
highest sequence. Expiration prevents new installs, not offline use of an
installed version. Initial-install freshness depends on the signed expiration;
this pilot does not implement a transparency log or online revocation service.
An existing artifact digest must match its retained release metadata exactly.
Reissuing different metadata for the same retained digest is rejected.

Signing authenticates the publisher and bytes. It does not sandbox a plugin,
grant authority to operate paid resources, or establish that code is safe.
Plugins still run with the user's permissions. Do not bypass Gatekeeper,
strip quarantine attributes, or relax signature verification to install one.

## Release requirements

Build from an immutable source revision with reviewed runtime/dependency pins.
Preserve upstream licenses, native dependency notices, and a dependency
inventory. Sign every Mach-O component, seal the app, notarize and staple it,
then produce and sign the DMG. Sign the release metadata only after tests pass.
Publish immutable artifacts before advertising their metadata in the catalog.

Required checks include every declared manifest, a package-specific offline
workflow with the bundled runtime, a relocated path containing spaces, no
package-manager dependency, signature and artifact tamper rejection, and
failed-update/rollback behavior. Optional programs such as Blender stay
visible in `doctor`; they are not silently installed or treated as mandatory
for unrelated local workflows. A valid signature alone is not a workflow test.

Reviewed recipes cover Workflow, Image, Face, Animatic, VFX, Perform, Film
Studio, Geospatial, and Terminal-Bench tools. The Terminal-Bench recipe includes
the pinned Harbor runtime and invokes it through the plugin's restricted frozen
entrypoint. It doesn't include Docker, task images, task data, model weights,
credentials, or benchmark results. Film Studio bundles its first-party Pi
prompts, skills, agents, and extension sources, but not Pi, provider
credentials, or ffmpeg. Those runtime integrations remain visible in `doctor`
and under user control.
