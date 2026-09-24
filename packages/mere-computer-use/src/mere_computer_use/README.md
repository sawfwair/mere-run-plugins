# `mere_computer_use`

`cli.py` owns the plugin manifest, local run record, Cua Driver subprocess boundary, and Pi launch. `resources/pi/extensions/mere-run-provider.ts` registers the loopback mere.run vision provider. `resources/pi/extensions/desktop.ts` exposes four window-scoped tools to Pi through the Python CLI. The package does not install or include Cua Driver.
