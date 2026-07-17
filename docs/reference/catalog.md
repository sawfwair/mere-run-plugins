# Plugin catalog

The catalog is the install and discovery index for official plugins.

## Live endpoint

```text
https://plugins.mere.run/catalog/plugins.v1.json
```

It matches the repository source at `catalog/plugins.v1.json` and validates
against `contracts/catalog.v1.schema.json`.

## Top-level fields

| Field | Meaning |
| --- | --- |
| `contractVersion` | Catalog schema identifier |
| `updatedAt` | UTC catalog publication timestamp |
| `defaultChannel` | Channel used when installation does not specify one |
| `plugins` | Official plugin entries |

## Plugin entry

Each entry defines:

- stable `id` and display `name`;
- product description;
- source repository;
- Python package and monorepo subdirectory;
- installed executable `entrypoint`;
- capability strings;
- install channels with manager, ref, and package spec.

## Installation

```bash
mere.run plugin list
mere.run plugin install mere-vfx-tools
```

The CLI resolves the catalog ID and channel to the declared package spec. The
catalog does not execute plugin code.

## Updating the catalog

When adding or changing an entry:

1. update `catalog/plugins.v1.json`;
2. update the matching plugin docs and tests;
3. run the repository gate;
4. let the site catalog sync copy the validated source into the public build.

The docs coverage check requires every catalog ID to have a first-class page.
