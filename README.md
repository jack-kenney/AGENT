# AGENT

AGENT is the Advanced General Exogenic Nutrient Transformer: a Discord nutrition
assistant backed by the OpenAI Responses API. It maintains profiles and food
logs in SQLite and loads METCOM lore from `info/` at startup.

## Local development

Create a virtual environment, install `requirements.txt`, and provide a `.env`
containing at least `DISCORD_TOKEN` and `OPENAI_API_KEY`.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python agent_bot.py
```

The local database defaults to `metcom.db` beside the source. Override it with
`METCOM_DB_PATH` when application code and mutable data need separate locations.

## Linux service

The production deployment uses these paths:

- application: `/opt/metcom-agent/app`;
- virtual environment: `/opt/metcom-agent/venv`;
- protected environment: `/etc/metcom-agent/agent.env`;
- SQLite state: `/var/lib/metcom-agent/metcom.db`;
- service: `metcom-agent.service`.

Install the environment file with mode `0640`, owned by
`root:metcom-agent`, then run:

```bash
sudo bash infra/install-linux-service.sh
```

Useful operations:

```bash
systemctl status metcom-agent
journalctl -u metcom-agent -f
sudo systemctl restart metcom-agent
```

The service runs as an unprivileged account with a read-only application tree.
Only `/var/lib/metcom-agent` is writable. Secrets and SQLite files stay outside
Git.
