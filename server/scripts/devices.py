"""Manage per-device API tokens (ADR-0017).

    uv run python scripts/devices.py create "Pixel phone"   # prints the token ONCE
    uv run python scripts/devices.py list
    uv run python scripts/devices.py revoke <device id>

Works while the server is running: the server checks the DB on every
request, so a revoked token stops working on its next request or
reconnect. A WebSocket session that is already open keeps running until
it disconnects.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth import generate_token, hash_token  # noqa: E402
from app.config import get_config  # noqa: E402
from app.db import Database  # noqa: E402


async def main(args: argparse.Namespace) -> int:
    db = Database(get_config())
    await db.start()
    try:
        if args.command == "create":
            token = generate_token()
            device = await db.create_device(args.name, hash_token(token))
            print(f"device id: {device['id']}  name: {device['name']}")
            print(f"token:     {token}")
            print("Shown once — copy it into the app now. Only its hash is stored.")
        elif args.command == "list":
            devices = await db.list_devices()
            if not devices:
                print("no devices")
            for d in devices:
                state = f"REVOKED {d['revoked_at']}" if d["revoked_at"] else "active"
                print(f"{d['id']}  {d['name']!r:24}  created {d['created_at'][:19]}  "
                      f"last used {(d['last_used_at'] or '-')[:19]}  {state}")
        elif args.command == "revoke":
            if not await db.revoke_device(args.device_id):
                print(f"no active device {args.device_id!r}", file=sys.stderr)
                return 1
            print(f"revoked {args.device_id}")
    finally:
        await db.stop()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="new device token")
    create.add_argument("name")
    sub.add_parser("list", help="all devices")
    revoke = sub.add_parser("revoke", help="disable a device token")
    revoke.add_argument("device_id")
    sys.exit(asyncio.run(main(parser.parse_args())))
