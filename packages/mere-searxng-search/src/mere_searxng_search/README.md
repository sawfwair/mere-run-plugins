# SearXNG Search package

`cli.py` owns the command interface, JSON response handling, and local search receipts. `instance.py` owns the Docker lifecycle for a loopback-only SearXNG container. The package calls SearXNG through its HTTP API and does not import its code.
