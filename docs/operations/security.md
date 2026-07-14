# Security

## Secret handling

Never commit or print API keys, provider tokens, ShotGrid script keys, SSH
private keys, private pod IDs, or local artifact bundles. Secrets must not appear
on stdout or stderr.

Use environment variables or a supported secret store. Examples and fixtures
must use obvious non-secret values.

## Local data

Local execution reduces exposure but does not automatically secure files.
Restrict access to source, intermediate, manifest, and artifact directories.
Review OCR and redaction outputs before sharing them.

## Commands and streams

Plugins construct explicit argument arrays. Batch Runner accepts explicit
`mere.run` argv, not generic shell fragments. JSON or path results go to stdout;
diagnostics go to stderr.

## Provider credentials

Use least-privilege accounts and provider keys. Run `doctor` before execution,
review `plan`, and verify cleanup after every remote run.

## Dependencies and source

Catalog installation specs point to the public repository and explicit package
subdirectories. Release changes should be reviewed with the same attention as
runtime code because plugins can invoke local tools and provider APIs.

## Reporting

Report vulnerabilities through the repository's private security reporting
path when available; do not publish live credentials or exploitable account
details in an issue.
