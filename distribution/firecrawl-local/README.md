# Release Firecrawl Local for macOS

This directory builds the standalone Firecrawl Local download for Apple Silicon
Macs with macOS 15 or later. The download starts a loopback HTTP service for
the MIT-licensed Mere plugin and other HTTP clients. Both Firecrawl Cloud and
browser rendering are disabled in the app.

## Build and verify

On an Apple Silicon Mac with Xcode and Rust, choose a fresh output directory
and run `./distribution/firecrawl-local/release.sh build OUTPUT_DIRECTORY`.
The script verifies the published crate by SHA-256, vendors the locked
dependencies, and builds offline from the source it archives. The output
contains the app, the matching source archive, and a dependency inventory.
The two projects retain their upstream license notices.

Review the exact dependencies and their advisories. Check that opening the app
makes `mere-firecrawl-local doctor` succeed and that the plugin can scrape a
public page. Quit the app and verify the listener stops. Source and license
information also ships inside the app and disk image.

To sign and notarize the disk image, set `PUBLIC_BASE_URL`,
`DEVELOPER_ID_APPLICATION`, and either
`NOTARY_PROFILE` or Apple API key settings `KEY_PATH`, `KEY_ID`, and
`ISSUER_ID`. Run the following command.

```sh
./distribution/firecrawl-local/release.sh sign OUTPUT_DIRECTORY
```

## Publish to R2

Set `R2_BUCKET` and `PUBLIC_BASE_URL`. For `https://mere.run`, use the
`mere-run-releases` bucket. To use the R2 S3 API, set `CLOUDFLARE_ACCOUNT_ID`,
`R2_ACCESS_KEY_ID`, and `R2_SECRET_ACCESS_KEY` with access to that bucket. You
can also set `R2_WRANGLER_CONFIG` to the release worker's Wrangler configuration
and use an authenticated Wrangler session.

```sh
./distribution/firecrawl-local/release.sh plan-publish OUTPUT_DIRECTORY
./distribution/firecrawl-local/release.sh publish OUTPUT_DIRECTORY
```

The publisher verifies the notarization ticket and checksums. It publishes
the source and checksum file first, then the disk image. It verifies the
public copy of each object against the local file and stops if an existing
public asset differs. The S3 upload also enforces create-only writes. Keep the source available with each downloadable binary.
