"""Read Earthdata Login credentials without ever printing or logging them.

Order of lookup:
  1. ~/.netrc entry for machine urs.earthdata.nasa.gov
  2. EARTHDATA_USERNAME and EARTHDATA_PASSWORD environment variables

If neither exists we stop (fail closed) with a message saying where to put them.
"""
from __future__ import annotations

import netrc
import os

URS_HOST = "urs.earthdata.nasa.gov"


class MissingCredentials(RuntimeError):
    pass


def credentials() -> tuple[str, str]:
    try:
        entry = netrc.netrc().authenticators(URS_HOST)
    except (FileNotFoundError, netrc.NetrcParseError):
        entry = None
    if entry and entry[0] and entry[2]:
        return entry[0], entry[2]
    user, pwd = os.environ.get("EARTHDATA_USERNAME"), os.environ.get("EARTHDATA_PASSWORD")
    if user and pwd:
        return user, pwd
    raise MissingCredentials(
        "No Earthdata Login credentials found. Add a ~/.netrc line "
        f"'machine {URS_HOST} login <user> password <password>' (chmod 600), or set "
        "EARTHDATA_USERNAME and EARTHDATA_PASSWORD. Nothing was sent."
    )


def status() -> str:
    """'present' or 'absent' — safe to print."""
    try:
        credentials()
        return "present"
    except MissingCredentials:
        return "absent"
