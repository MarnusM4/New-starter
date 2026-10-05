"""One-time helper: turn a Zoho "Self Client" grant code into a refresh token + org id.

1. Go to the Zoho API console for your data centre (e.g. https://api-console.zoho.com, or
   .eu / .in / .com.au), add a client of type **Self Client**, and note its Client ID and
   Client Secret.
2. In the Self Client, "Generate Code" with scope:
       Desk.tickets.ALL,Desk.basic.READ
   and a duration of 10 minutes. Copy the code (it expires quickly).
3. Run:
       python tools/zoho_token.py --region com --code <the code>
   Client ID / secret are read from ZOHO_CLIENT_ID / ZOHO_CLIENT_SECRET in .env, or asked
   for (the secret isn't echoed), so they don't end up in your shell history.

It prints the lines to put in .env: ZOHO_REFRESH_TOKEN, ZOHO_ORG_ID and the regional URLs.
Nothing is written to disk. Treat the refresh token like a password.
"""

from __future__ import annotations

import argparse
import getpass
import os
import pathlib
import sys
from typing import Any

import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent

REGIONS = ("com", "eu", "in", "com.au", "jp", "ca", "sa")


def exchange_code(region: str, client_id: str, client_secret: str, code: str) -> dict[str, Any]:
    """Grant code -> tokens. Zoho reports errors as HTTP 200 with an "error" field."""
    resp = requests.post(
        f"https://accounts.zoho.{region}/oauth/v2/token",
        params={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise SystemExit(
            f"Zoho refused the code: {data['error']}. Codes expire within minutes and can "
            "only be used once — generate a new one and run this again straight away. Also "
            "check --region matches the data centre your Zoho account is in."
        )
    if "refresh_token" not in data:
        raise SystemExit(
            "Zoho returned no refresh token. Generate the code from a *Self Client* "
            "(not a server-based client) and try again."
        )
    return data


def list_orgs(region: str, access_token: str) -> list[dict[str, Any]]:
    resp = requests.get(
        f"https://desk.zoho.{region}/api/v1/organizations",
        headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("data", [])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Get a Zoho Desk refresh token and org id.")
    parser.add_argument("--region", choices=REGIONS, default="com",
                        help="Zoho data centre: com (US), eu, in, com.au, ... (default com)")
    parser.add_argument("--code", help="grant code from the Self Client (asked if omitted)")
    args = parser.parse_args(argv)

    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

    def from_env(name: str) -> str:
        value = os.environ.get(name, "")
        return "" if value.startswith("PLACEHOLDER") else value

    client_id = from_env("ZOHO_CLIENT_ID") or input("Zoho Client ID: ").strip()
    client_secret = from_env("ZOHO_CLIENT_SECRET") or getpass.getpass("Zoho Client Secret: ").strip()
    code = args.code or input("Grant code: ").strip()

    tokens = exchange_code(args.region, client_id, client_secret, code)
    orgs = list_orgs(args.region, tokens["access_token"])

    print("\nAdd these to .env (keep the refresh token secret):\n")
    print(f"ZOHO_DESK_BASE_URL=https://desk.zoho.{args.region}")
    print(f"ZOHO_ACCOUNTS_URL=https://accounts.zoho.{args.region}")
    print(f"ZOHO_REFRESH_TOKEN={tokens['refresh_token']}")
    if len(orgs) == 1:
        print(f"ZOHO_ORG_ID={orgs[0].get('id')}")
    elif orgs:
        print("# Several Desk organisations — pick one ZOHO_ORG_ID:")
        for org in orgs:
            name = org.get("companyName") or org.get("portalName") or ""
            print(f"#   ZOHO_ORG_ID={org.get('id')}   ({name})")
    else:
        print("# No Desk organisation found for this account — check the region.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
