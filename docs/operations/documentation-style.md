# Documentation style

This guide is for contributors who write or review developer documentation in
this repository. It defines the project-specific writing standard for Markdown,
CLI examples, and reference pages.

Project terminology and verified command behavior take precedence. For general
editorial decisions, follow the [Google developer documentation style
guide](https://developers.google.com/style).

## Write for a specific reader

Name the intended reader and the page's purpose in the opening. Organize the
page around the task that the reader wants to complete.

Recommend one path for the common case. Move alternatives, implementation
details, and edge cases into later sections.

## Use direct language

- Address the reader as "you," or use an imperative verb.
- Use present tense and active voice.
- Put conditions and goals before instructions.
- Use "must" for requirements, "can" for capabilities, and "might" for possible
  outcomes.
- Remove filler, hype, jokes, and time-dependent words.
- Define repository-specific terms when they first appear.

Keep sentences short. Put the distinguishing information at the start of each
paragraph.

## Structure pages consistently

Use one level-one heading. Use sentence case for headings and don't add terminal
punctuation.

Use numbered lists only when order matters. Use bullets for unordered items.
Introduce every list and code sample with a complete sentence.

For a procedure, give one action per step. Put prerequisites before the
procedure, not in a note.

## Format technical text

Use code font for commands, options, paths, filenames, environment variables,
schema fields, literal values, and executable names.

Use descriptive link text. Don't use raw URLs as link text, "click here," or
directional references such as "preceding" and "following" when you can name
the target. Never use "above" or "below" for position.

Use uppercase underscore-separated placeholders in code samples. Explain each
placeholder after the sample.

## Document command behavior

Copy command names, options, and defaults from the implementation or installed
help output. Distinguish preview commands from commands that change state.

For plugin installation:

- Omit `--yes` only when the surrounding text says that the command previews
  the resolved installation.
- Add `--yes` when the instruction installs the plugin.

When a command promises JSON or newline-delimited JSON (NDJSON), describe stdout
as machine-readable and stderr as diagnostic output.

## Preserve safety boundaries

State when a workflow uses local files, a local Docker context, a private
backend, or a user-controlled provider. Don't imply that local execution alone
secures output.

Separate these claims:

- A command or build passed local validation.
- A package or bundle was published.
- A website was deployed.
- A remote workflow completed.
- A human accepted the result.

For paid resources, document the plan, creation point, cleanup default, and
recovery path.

## Review a documentation change

Before you open a pull request:

1. Verify commands and claims against code, schemas, catalog data, or help
   output.
2. Confirm that headings, lists, links, code formatting, and terminology follow
   this guide.
3. Run the documentation coverage check.
4. Build the VitePress site with dead-link enforcement.
5. Run the repository gate.

Use these commands:

```bash
corepack pnpm docs:coverage
corepack pnpm docs:build
./scripts/check.sh
```

The coverage check verifies dedicated plugin pages, contract-schema coverage,
catalog counts, and known obsolete command forms.
