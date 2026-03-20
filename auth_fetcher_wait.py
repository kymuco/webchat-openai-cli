import argparse
import asyncio

from auth_fetcher import DEFAULT_AUTH_TIMEOUT, run_auth_and_save


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch ChatGPT web auth data via NoDriver in wait mode."
    )
    parser.add_argument(
        "--output",
        default="auth_data.json",
        help="Path to auth_data.json output file.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_AUTH_TIMEOUT,
        help="Seconds to wait for auth capture after you trigger it from the browser.",
    )
    parser.add_argument(
        "--ready-timeout",
        type=float,
        default=0.0,
        help="Seconds to wait for login/chat readiness. 0 means wait indefinitely.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    try:
        asyncio.run(
            run_auth_and_save(
                mode="wait",
                output_file=args.output,
                auth_timeout=args.timeout,
                ready_timeout=args.ready_timeout,
            )
        )
    except KeyboardInterrupt:
        print("Operation interrupted by user.")
