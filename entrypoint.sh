#!/bin/sh
set -eu
umask 077
workspace="${TEAMWORKER_WORKSPACE:-/workspace}"
export PI_CODING_AGENT_DIR="${PI_CODING_AGENT_DIR:-$workspace/data/pi-agent}"
mkdir -p "$PI_CODING_AGENT_DIR" "$workspace/skills" "$workspace/memory"
# Bundled resources follow the deployed image; credentials/settings remain on
# the volume. Custom skills belong in /workspace/skills, not these symlinks.
ln -sfn /app/teamworker/extensions "$PI_CODING_AGENT_DIR/extensions"
ln -sfn /app/teamworker/skills "$PI_CODING_AGENT_DIR/skills"
if [ ! -f "$workspace/AGENTS.md" ]; then
    cp /app/teamworker/AGENTS.md "$workspace/AGENTS.md"
fi
python - <<'PY'
import json, os
from pathlib import Path
path = Path(os.environ['PI_CODING_AGENT_DIR']) / 'settings.json'
settings = json.loads(path.read_text()) if path.exists() else {}
settings.setdefault('compaction', {})['enabled'] = True
settings['compaction']['reserveTokens'] = int(os.getenv('CONTEXT_RESERVE_TOKENS', '16384'))
path.write_text(json.dumps(settings, indent=2) + '\n')
path.chmod(0o600)
PY
if [ -n "${GH_TOKEN:-}" ]; then
    gh auth setup-git --hostname github.com
fi
cd "$workspace"
exec "$@"
