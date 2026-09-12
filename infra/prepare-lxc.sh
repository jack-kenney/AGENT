#!/usr/bin/env bash
# Prepare runtime and source without connecting a second bot to Discord.
set -euo pipefail
[[ ${EUID} -eq 0 ]] || { echo 'Run as an administrator.' >&2; exit 1; }
[[ $(hostname) == metcom ]] || { echo 'Expected the metcom container.' >&2; exit 1; }
source_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if ! id metcom-agent >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/metcom-agent --shell /usr/sbin/nologin metcom-agent
fi
install -d -m 0755 /opt/metcom-agent/app/info
install -d -m 0750 -o metcom-agent -g metcom-agent /var/lib/metcom-agent
install -d -m 0750 -o root -g metcom-agent /etc/metcom-agent
for name in agent_bot.py db.py requirements.txt; do
  install -m 0644 "${source_root}/${name}" "/opt/metcom-agent/app/${name}"
done
for file in "${source_root}"/info/*.md; do
  install -m 0644 "${file}" "/opt/metcom-agent/app/info/$(basename "${file}")"
done
python3 -m venv /opt/metcom-agent/venv
/opt/metcom-agent/venv/bin/python -m pip install --disable-pip-version-check -r /opt/metcom-agent/app/requirements.txt
/opt/metcom-agent/venv/bin/python -m pip check
install -m 0644 "${source_root}/infra/metcom-agent.service" /etc/systemd/system/metcom-agent.service
systemctl daemon-reload
echo 'Prepared. Bot remains stopped until the final export is installed.'
