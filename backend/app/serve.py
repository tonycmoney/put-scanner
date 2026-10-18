"""Production entry point: `python -m app.serve` (reads PORT, no shell needed)."""

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",  # noqa: S104 - all interfaces inside the container
        port=int(os.environ.get("PORT", "8000")),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
