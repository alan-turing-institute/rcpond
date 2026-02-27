#!/usr/bin/env python3
"""Pre-commit hook to detect accidentally committed API keys and tokens.

Scans staged files for RCPOND_LLM_API_KEY and RCPOND_SERVICENOW_TOKEN
assignments and rejects any that look like real secrets (i.e. not a
well-known placeholder value from the example .env file).
"""

import re
import sys

# Keys to check and their known-safe placeholder values
CHECKED_KEYS: dict[str, set[str]] = {
    "RCPOND_LLM_API_KEY": {"your-api-key-here", ""},
    "RCPOND_SERVICENOW_TOKEN": {"your-servicenow-token", ""},
}

# Matches lines like: RCPOND_LLM_API_KEY=some-value
_PATTERN = re.compile(
    r"^("
    + "|".join(re.escape(k) for k in CHECKED_KEYS)
    + r")\s*=\s*(.*)$"
)


def check_file(path: str) -> list[str]:
    """Return a list of violation messages for the given file."""
    violations = []
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line_no, line in enumerate(f, start=1):
                m = _PATTERN.match(line.rstrip())
                if m:
                    key, value = m.group(1), m.group(2).strip()
                    safe_values = CHECKED_KEYS[key]
                    if value not in safe_values:
                        violations.append(
                            f"  {path}:{line_no}: {key} appears to contain a real secret"
                        )
    except (OSError, UnicodeDecodeError):
        pass
    return violations


def main(files: list[str]) -> int:
    all_violations = []
    for path in files:
        all_violations.extend(check_file(path))

    if all_violations:
        print("Possible secrets detected — commit blocked:")  # noqa: T201
        for v in all_violations:
            print(v)  # noqa: T201
        print(  # noqa: T201
            "\nIf this is a false positive, move the value to a "
            "local .env file (which should be git-ignored) and "
            "use a placeholder in any committed file."
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
