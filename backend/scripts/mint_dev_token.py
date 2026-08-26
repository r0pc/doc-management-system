"""Mint a dev JWT for e2e harnesses and manual testing.

Prints one HS256 token on stdout built from the given claims. The signing
secret defaults to ``Settings.dev_jwt_secret`` (the dev shim the API verifies
against when ``ENV=dev`` and no OIDC issuer is configured); ``--secret``
overrides it for tests that pin their own key.

Dev-only: tokens minted here are accepted solely by the DevJWTVerifier, which
is structurally forbidden outside ``env="dev"`` (see app/security/auth.py).
"""

import argparse
import sys
from pathlib import Path

# Script bootstrap: make the backend package importable no matter the caller's
# cwd (python puts the script's own dir on sys.path, never the project root).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.security.auth import issue_dev_token


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Mint a dev JWT bearer token (HS256 dev shim).",
    )
    parser.add_argument("--sub", required=True, help="OIDC subject claim")
    parser.add_argument("--tenant", required=True, help="tenant uuid claim")
    parser.add_argument("--dept", default=None, help="department uuid claim (optional)")
    parser.add_argument("--role", required=True, help="role claim (permissions table key)")
    parser.add_argument(
        "--clearance", required=True, type=int, help="clearance rank 1..4 (Public..Restricted)"
    )
    parser.add_argument("--secret", default=None, help="HMAC secret (default: settings value)")
    parser.add_argument("--expires", default=3600, type=int, help="token lifetime seconds")
    parser.add_argument("--audience", default="docmgmt-api", help="expected aud claim")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    secret = args.secret if args.secret is not None else Settings().dev_jwt_secret
    print(
        issue_dev_token(
            args.sub,
            args.tenant,
            args.dept,
            args.role,
            args.clearance,
            expires_in=args.expires,
            audience=args.audience,
            secret=secret,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
