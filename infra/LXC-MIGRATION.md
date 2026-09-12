# METCOM LXC migration

The retained application is the existing Discord bot, not a new agent harness.
Use an unprivileged Debian 12 LXC with 1 CPU, 1 GiB RAM, 256 MiB swap, an 8 GiB
`vmstore` root disk, and DHCP on `vmbr0`. The initial container is CT 113,
hostname `metcom`, observed at `192.168.0.189`. Manage it through Proxmox; no
public ingress or nested container runtime is required.

Set `features: nesting=1` for the service's systemd mount namespaces. Without
this, CT 113's AppArmor profile denies its private `/proc` mount and the service
fails with `226/NAMESPACE`. The container remains unprivileged and the existing
service sandbox is preserved; no nested container runtime is installed.

On 2026-09-12 the protected final state was installed, SQLite integrity passed,
and the bot connected from CT 113, including after a reboot. The old VM 109 bot
is stopped/disabled. Container autostart and the daily backup job are enabled.
An isolated restore into temporary CT 114 passed integrity checks for both the
database and recovery snapshot, with configuration and all nine content files
present. The restore was never booted, its network was disabled, and CT 114 was
removed after verification. The owner confirmed the Discord response/history
check passed. VM 109 shut down on September 12 at 21:41:54 UTC with autostart off;
its disks are retained through at least September 26 at 21:41:54 UTC.

## Staging

`prepare-lxc.sh` installs the source, pinned Python dependencies and the existing
hardened service. It deliberately does not enable or start the bot. The initial
deployment source and all nine `info/` files were checked against VM 109's live
application. Differing source-checkout files and the original Windows checkout
remain preserved separately; do not accidentally deploy unrelated local edits.

## Final handoff

1. On VM 109, run the reviewed Work exporter with `metcom`. It stops the old
   bot, makes a consistent SQLite backup and exports configuration and current
   content to a mode-0600 archive outside Git. Export failure restarts the old bot.
2. Transfer the archive privately over SSH, check its SHA-256, and push it into
   CT 113. Do not print configuration values or database records.
3. Run `restore-handoff.py /root/metcom.tar.gz` in the container. It refuses a
   running destination bot or existing database and verifies SQLite integrity.
4. Confirm VM 109's bot is still stopped, then enable/start `metcom-agent` in
   CT 113. Check service health and Discord connection without dumping messages.
5. The owner sends a test command in Discord. Verify exactly one response and
   continuity of existing profiles/logs. Restart the container and repeat health
   checks before disabling the old bot's automatic startup.

Keep only one bot active throughout. If rolling back after the new bot has
processed messages, stop it and transfer its latest consistent database back
before starting the old bot; otherwise new food logs would be lost.

## Backups and recovery

`backup-sqlite.py` makes a consistent `recovery-snapshot.db` before a Proxmox
snapshot backup. Invoke it from the METCOM-specific vzdump backup-start hook.
The daily job must retain seven daily backups and must not change existing
Counter-Strike backup jobs. Enable the schedule only after final state is
installed; a missing database must fail, not create an empty backup.

Test a restore in an isolated, network-disabled environment, and verify SQLite
integrity before allowing a restored bot to connect. Recovery archives contain
credentials and personal records and must remain protected outside Git.
