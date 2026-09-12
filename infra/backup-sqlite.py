#!/usr/bin/env python3
"""Create a consistent recovery database before a Proxmox container snapshot."""
import os
from pathlib import Path
import sqlite3

os.umask(0o077)
root = Path("/var/lib/metcom-agent")
source = root / "metcom.db"
target = root / "recovery-snapshot.db"
pending = root / "recovery-snapshot.pending"
with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as src:
    with sqlite3.connect(pending) as dest:
        src.backup(dest)
        if dest.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise SystemExit("Database integrity check failed.")
pending.replace(target)
print("Consistent METCOM recovery snapshot prepared.")
