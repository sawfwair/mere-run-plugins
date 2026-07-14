# Exit codes

Official plugins use a shared top-level exit-code convention.

| Code | Meaning |
| ---: | --- |
| `0` | Command succeeded |
| `1` | Expected operator-facing failure |
| `2` | Invalid CLI usage or invalid input shape |
| `3` | Readiness check failed |
| `4` | Provider resource failure |
| `5` | Cleanup failed |

## Automation guidance

Parse the promised stdout payload first, then use the exit code to choose the
operator path. Keep stderr attached to logs for diagnosis.

- code `2`: fix the command or document before retrying;
- code `3`: satisfy `doctor` requirements before execution;
- code `4`: inspect provider state and the durable manifest before retrying;
- code `5`: treat the referenced resource as potentially live until verified.

Do not blindly retry resource creation after codes `4` or `5`. Resume or clean up
the existing run by manifest whenever possible.
