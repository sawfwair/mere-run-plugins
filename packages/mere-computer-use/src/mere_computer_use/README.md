# `mere_computer_use`

`cli.py` owns the plugin manifest, local run record, Cua Driver subprocess boundary, and Pi launch. `api_lifecycle.py` checks model terms, preflights, starts, and stops a run-owned loopback vision API. `driver_setup.py` installs the pinned, checksum-verified, signed Cua Driver macOS app on request. `resources/pi/extensions/mere-run-provider.ts` registers the loopback mere.run vision provider. `resources/pi/extensions/desktop.ts` exposes four window-scoped tools to Pi through the Python CLI.
