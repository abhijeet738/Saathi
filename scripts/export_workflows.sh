
#!/usr/bin/env bash
# Saves every n8n workflow as its own JSON file in n8n/workflows/, named after the workflow
# (WF00 Error Handler -> WF00_error_handler.json). Commit these files to Git.
#
# n8n does not export credentials, only their names. As a safety net this script also refuses
# to write anything if a secret from your .env appears inside an exported workflow.
set -euo pipefail
cd "$(dirname "$0")/.."

# Export lands here first (inside the n8n container's /workflows mount), then is checked and renamed.
TMP=/workflows/.export_tmp
cleanup() { docker compose exec -T n8n rm -rf "$TMP" >/dev/null 2>&1 || true; }
trap cleanup EXIT

cleanup
if ! docker compose exec -T n8n mkdir -p "$TMP" \
   || ! docker compose exec -T n8n n8n export:workflow --all --separate --pretty --output="$TMP/"; then
  echo "Export failed. Is n8n running? Check with: make ps" >&2
  echo "On Linux, a 'permission denied' error is fixed by: chmod -R a+rwX n8n/workflows" >&2
  exit 1
fi

python3 - n8n/workflows/.export_tmp n8n/workflows .env <<'PY'
import json
import re
import sys
from pathlib import Path

tmp, out, env_file = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])

# Secrets from .env that must never appear inside a workflow file.
SECRET_KEYS = {
    "TELEGRAM_BOT_TOKEN", "SAATHI_API_KEY", "GEMINI_API_KEY", "N8N_ENCRYPTION_KEY", "WHATSAPP_TOKEN",
    "CLOUDFLARE_TUNNEL_TOKEN", "DASHBOARD_PASSWORD", "GOLDEN_TOKEN",
}
secrets = {}
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key in SECRET_KEYS and len(value) >= 8:
            secrets[key] = value
        if key == "DATABASE_URL":
            match = re.search(r"://[^:/@]+:([^@]+)@", value)
            if match and len(match.group(1)) >= 8:
                secrets["DATABASE_URL (password)"] = match.group(1)


def slug(name: str) -> str:
    """'WF00 Error Handler' -> 'WF00_error_handler'; 'ZZ Error test' -> 'zz_error_test'."""
    s = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
    m = re.match(r"(WF\d+)(.*)", s)
    return (m.group(1) + m.group(2).lower()) if m else s.lower()


found = []   # (slug, name, id, raw bytes)
problems = []
for path in sorted(tmp.glob("*.json")):
    raw = path.read_bytes()
    data = json.loads(raw)
    if isinstance(data, list):          # some n8n versions wrap a single workflow in a list
        data = data[0]
    name = data.get("name") or path.stem
    text = raw.decode("utf-8")
    for key, value in secrets.items():
        if value in text:
            problems.append(f'  "{name}" contains the value of {key}')
    found.append((slug(name), name, str(data.get("id", path.stem)), raw))

if not found:
    sys.exit("No workflows were exported. Does n8n have any workflows yet?")
if problems:
    print("A secret from your .env is inside an exported workflow. NOTHING was written.", file=sys.stderr)
    print("\n".join(problems), file=sys.stderr)
    print("Fix: select the credential in the node instead of typing the secret, save, and export again.",
          file=sys.stderr)
    sys.exit(1)

# Two workflows with the same name would overwrite each other, so add the id to the file name.
# Compared in lowercase because macOS and Windows file systems ignore letter case.
counts = {}
for s, *_ in found:
    counts[s.lower()] = counts.get(s.lower(), 0) + 1

out.mkdir(parents=True, exist_ok=True)
for s, name, wid, raw in found:
    filename = f"{s}_{wid}.json" if counts[s.lower()] > 1 else f"{s}.json"
    (out / filename).write_bytes(raw)
    print(f"  {filename}   <- {name}")
print(f"Exported {len(found)} workflow(s) to {out}/")
PY
