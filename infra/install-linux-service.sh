#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run this installer as root." >&2
  exit 1
fi

source_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
app_root=/opt/metcom-agent/app
venv_root=/opt/metcom-agent/venv
config_root=/etc/metcom-agent
state_root=/var/lib/metcom-agent
service_name=metcom-agent

if [[ ! -s ${config_root}/agent.env ]]; then
  echo "Missing ${config_root}/agent.env; install the protected environment file first." >&2
  exit 1
fi

if ! id "${service_name}" >/dev/null 2>&1; then
  useradd --system --home-dir "${state_root}" --shell /usr/sbin/nologin "${service_name}"
fi

install -d -m 0755 -o root -g root /opt/metcom-agent "${app_root}" "${app_root}/info"
install -d -m 0755 -o root -g root "${config_root}"
install -d -m 0750 -o "${service_name}" -g "${service_name}" "${state_root}"

install -m 0644 -o root -g root "${source_root}/agent_bot.py" "${app_root}/agent_bot.py"
install -m 0644 -o root -g root "${source_root}/db.py" "${app_root}/db.py"
install -m 0644 -o root -g root "${source_root}/requirements.txt" "${app_root}/requirements.txt"
for info_file in "${source_root}"/info/*.md; do
  install -m 0644 -o root -g root "${info_file}" "${app_root}/info/$(basename "${info_file}")"
done

chown root:"${service_name}" "${config_root}/agent.env"
chmod 0640 "${config_root}/agent.env"

if [[ ! -x ${venv_root}/bin/python ]]; then
  python3 -m venv "${venv_root}"
fi
"${venv_root}/bin/python" -m pip install \
  --disable-pip-version-check \
  --requirement "${app_root}/requirements.txt"

install -m 0644 -o root -g root \
  "${source_root}/infra/metcom-agent.service" \
  "/etc/systemd/system/${service_name}.service"

systemctl daemon-reload
systemctl enable "${service_name}"
systemctl restart "${service_name}"

for _ in {1..30}; do
  if systemctl is-active --quiet "${service_name}" && \
      journalctl -u "${service_name}" --since "-1 minute" --no-pager | \
        grep -q "AGENT online as"; then
    exit 0
  fi
  sleep 1
done

echo "${service_name} did not confirm its Discord connection within 30 seconds." >&2
systemctl status "${service_name}" --no-pager -l >&2 || true
journalctl -u "${service_name}" -n 100 --no-pager >&2 || true
exit 1
