"""Maintenance commands that do not require starting the web service."""

import argparse
import asyncio
import base64
import getpass
import hashlib
import json
import os
from pathlib import Path

from switchgear.storage.sqlite import SQLiteStorage


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return "scrypt:16384:8:1:" + base64.urlsafe_b64encode(salt).decode() + ":" + \
        base64.urlsafe_b64encode(digest).decode()


async def import_json(source: Path, database: Path) -> int:
    raw = json.loads(source.read_text(encoding="utf-8"))
    storage = SQLiteStorage(database)
    count = 0
    for collection, documents in raw.items():
        if not isinstance(documents, dict):
            raise ValueError(f"collection {collection!r} is not an object")
        for key, document in documents.items():
            if not isinstance(document, dict):
                raise ValueError(f"document {collection}/{key} is not an object")
            await storage.put(collection, key, document)
            count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(prog="switchgear")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("hash-password", help="generate SWITCHGEAR_LOCAL_PASSWORD_HASH")
    imp = sub.add_parser("import-storage-json", help="import legacy storage.json")
    imp.add_argument("source", type=Path)
    imp.add_argument("--database", type=Path, default=Path("/data/switchgear.sqlite3"))
    args = parser.parse_args()
    if args.command == "hash-password":
        first = getpass.getpass("Password: ")
        if first != getpass.getpass("Confirm: "):
            raise SystemExit("passwords do not match")
        print(hash_password(first))
    else:
        print(f"imported {asyncio.run(import_json(args.source, args.database))} documents")


if __name__ == "__main__":
    main()
