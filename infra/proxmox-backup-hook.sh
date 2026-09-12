#!/usr/bin/env bash
set -euo pipefail
phase=${1:?missing phase}
case "${phase}" in
  backup-start)
    [[ ${3:-} == 113 ]] || { echo 'This hook is restricted to METCOM CT 113.' >&2; exit 1; }
    /usr/sbin/pct exec 113 -- /opt/metcom-agent/venv/bin/python \
      /opt/metcom-agent/source/infra/backup-sqlite.py
    ;;
  backup-end)
    [[ ${3:-} == 113 ]] || exit 1
    case "${TARGET:-}" in
      /hddpool/backups/dump/vzdump-lxc-113-*.tar.zst) chmod 0600 -- "${TARGET}" ;;
      *) echo 'Unexpected METCOM backup destination.' >&2; exit 1 ;;
    esac
    ;;
esac
