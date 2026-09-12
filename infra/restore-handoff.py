#!/usr/bin/env python3
"""Install a final stopped-source handoff; deliberately does not start the bot."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import sqlite3
import subprocess
import tarfile
import tempfile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path)
    args = p.parse_args()
    if os.geteuid() != 0 or subprocess.check_output(["hostname"], text=True).strip() != "metcom":
        raise SystemExit("Run as administrator inside the metcom container.")
    if subprocess.run(["systemctl", "is-active", "--quiet", "metcom-agent"]).returncode == 0:
        raise SystemExit("Refusing to overwrite a running bot's data.")
    database = Path("/var/lib/metcom-agent/metcom.db")
    if database.exists():
        raise SystemExit("Destination database exists; preserve it and resolve rollback state first.")
    owner = pwd.getpwnam("metcom-agent")
    os.umask(0o077)
    with tempfile.TemporaryDirectory(dir="/root", prefix="metcom-handoff-") as temp:
        work = Path(temp)
        with tarfile.open(args.archive) as archive:
            for m in archive.getmembers():
                path = PurePosixPath(m.name)
                if path.is_absolute() or ".." in path.parts or m.issym() or m.islnk():
                    raise SystemExit("Unsafe archive entry.")
                if m.isdir():
                    continue
                if not m.isfile() or not (m.name in ("state/metcom.db", "config/agent.env") or m.name.startswith("info/")):
                    raise SystemExit("Unexpected handoff contents.")
                target = work / m.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.extractfile(m).read())
        snapshot = work / "state/metcom.db"
        with sqlite3.connect(snapshot.as_uri() + "?mode=ro", uri=True) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise SystemExit("Invalid SQLite handoff.")
        config = work / "config/agent.env"
        if not config.is_file():
            raise SystemExit("Missing protected configuration.")
        database.write_bytes(snapshot.read_bytes())
        os.chown(database, owner.pw_uid, owner.pw_gid)
        database.chmod(0o600)
        dest = Path("/etc/metcom-agent/agent.env")
        dest.write_bytes(config.read_bytes())
        os.chown(dest, 0, owner.pw_gid)
        dest.chmod(0o640)
        for source in (work / "info").rglob("*"):
            if source.is_file():
                dest = Path("/opt/metcom-agent/app/info") / source.relative_to(work / "info")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(source.read_bytes())
                dest.chmod(0o644)
        print(json.dumps({"integrity": "ok", "database_sha256": hashlib.sha256(database.read_bytes()).hexdigest(), "bot": "still stopped"}))


if __name__ == "__main__":
    main()
