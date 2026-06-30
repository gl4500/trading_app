"""Fail fast if the CMA surface is missing from the installed anthropic SDK."""
import sys
import anthropic

REQUIRED = ("agents", "environments", "sessions")


def main() -> int:
    client = anthropic.Anthropic(api_key="x")  # no network call; just attribute access
    missing = [name for name in REQUIRED if not hasattr(client.beta, name)]
    print(f"anthropic {anthropic.__version__}")
    if missing:
        print(f"MISSING CMA surface: {missing}")
        return 1
    print("OK: beta.agents / environments / sessions present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
