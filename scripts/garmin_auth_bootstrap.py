"""
garmin_auth_bootstrap.py

ONE-TIME bootstrap for Garmin Connect auth (garminconnect >= 0.3.x).

This is the *only* script in the project that performs a fresh SSO login.
After it runs successfully, OAuth tokens are saved to ~/.garminconnect
(the file ~/.garminconnect/garmin_tokens.json holds the DI access_token +
refresh_token). All other scripts load those tokens and refresh them via
diauth.garmin.com — they never hit the SSO endpoint again.

Usage (run ONCE, manually):
    python scripts/garmin_auth_bootstrap.py

If MFA is enabled on the Garmin account, the script will prompt for the
6-digit code interactively.

If you are currently 429-blocked on this account, DO NOT run this in a
loop. The block clears on its own in 1-24 hours; retrying faster only
delays recovery.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

from dotenv import load_dotenv

try:
    from garminconnect import (
        Garmin,
        GarminConnectAuthenticationError,
        GarminConnectConnectionError,
        GarminConnectTooManyRequestsError,
    )
except ImportError:
    sys.stderr.write(
        "garminconnect is not installed. Run: pip install -r requirements.txt\n"
    )
    sys.exit(1)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TOKENSTORE = Path.home() / ".garminconnect"


def harden_permissions(tokenstore: Path) -> None:
    """chmod 700 on the dir, chmod 600 on each file inside.

    garminconnect 0.3.x already writes garmin_tokens.json with mode 0600;
    this is belt-and-suspenders to make sure the directory and any legacy
    token files (oauth1_token.json / oauth2_token.json from older versions)
    are also locked down.
    """
    if not tokenstore.exists():
        return
    try:
        os.chmod(tokenstore, stat.S_IRWXU)  # 0o700
    except OSError as e:
        print(f"  ! could not chmod 700 {tokenstore}: {e}")
    if tokenstore.is_dir():
        for child in tokenstore.iterdir():
            if child.is_file():
                try:
                    os.chmod(child, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
                except OSError as e:
                    print(f"  ! could not chmod 600 {child}: {e}")


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")
    if not email or not password:
        sys.stderr.write(
            "Missing GARMIN_EMAIL / GARMIN_PASSWORD in .env. "
            "Copy .env.example to .env and fill in your credentials.\n"
        )
        return 2

    print(f"Bootstrapping Garmin token store at: {TOKENSTORE}")
    print("This will perform ONE fresh SSO login. Do not retry in a loop.")

    client = Garmin(
        email=email,
        password=password,
        prompt_mfa=lambda: input("Garmin MFA code: ").strip(),
    )

    try:
        # In garminconnect >= 0.3, login(tokenstore_path) is idempotent:
        # - if the token file exists and is valid, it loads it (no SSO)
        # - if the token file is missing/invalid, it performs SSO using the
        #   email+password we passed to the constructor and auto-persists
        #   the new tokens at the given path.
        client.login(str(TOKENSTORE))
    except GarminConnectTooManyRequestsError as e:
        print(
            "❌ Currently rate-limited (HTTP 429). Wait 1-24 hours before "
            "retrying THIS script. Do not retry in a loop."
        )
        print(f"   Detail: {e}")
        return 3
    except GarminConnectAuthenticationError as e:
        print(
            "❌ Authentication failed. Check the credentials in .env. If you "
            "recently changed your password, this is expected — fix .env and "
            "rerun this script once."
        )
        print(f"   Detail: {e}")
        return 4
    except GarminConnectConnectionError as e:
        print("❌ Network error reaching Garmin. Check connectivity and retry.")
        print(f"   Detail: {e}")
        return 5

    harden_permissions(TOKENSTORE)

    print("✅ Tokens saved to ~/.garminconnect/garmin_tokens.json. "
          "You can now run garmin_sync.py without rate limit risk.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
