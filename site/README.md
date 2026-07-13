# plugins.mere.run

The public catalog and product site for official `mere.run` companion plugins.
It deliberately follows the same static Cloudflare Worker shape and visual
system as `mere-run-site`.

```bash
pnpm install
pnpm dev
pnpm check
pnpm deploy
```

`pnpm prepare:catalog` copies the repository catalog into the public site and
its agent-readable well-known path. Keep plugin copy and commands grounded in
the root catalog and plugin documentation.
