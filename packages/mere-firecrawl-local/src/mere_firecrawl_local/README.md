# Firecrawl Local adapter

`cli.py` handles the HTTP API, input validation, and command output.
`pi.py` manages the separate Pi extension link. The extension calls the CLI
and provides the same bounded JSON response to the agent.
