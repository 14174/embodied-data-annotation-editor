#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'HELP'
Usage: ./deploy.sh DATASET OUTPUT [--service] [--port 18080] [platform options]

Create/reuse .venv, install requirements, then start the annotation editor.
DATASET must contain meta/info.json and indexed, independent episode videos.
OUTPUT must be outside the source dataset and scanned collection directories.

  --service           Install/restart a Linux systemd user service instead of foreground run
  --host HOST         Bind address (default: 127.0.0.1)
  --port PORT         Listen port (default: 18080)
  --collection-root   Automatically scan this collection's immediate dataset directories
  --review-root       Directory containing prepared playback datasets

Set ANNOTATION_PYTHON to choose a Python 3.10+ executable on first installation.
HELP
}

if [[ "${1:-}" == '--help' || "${1:-}" == '-h' ]]; then
  usage
  exit 0
fi
if [[ $# -lt 2 ]]; then
  usage >&2
  exit 2
fi
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
dataset="$1"
output="$2"
shift 2
if [[ ! -f "$dataset/meta/info.json" ]]; then
  echo "Dataset is missing meta/info.json: $dataset" >&2
  exit 2
fi
mode=run
options=()
for argument in "$@"; do
  if [[ "$argument" == '--service' ]]; then
    mode=install
  else
    options+=("$argument")
  fi
done
if [[ "$mode" == install ]]; then
  for tool in systemctl systemd-analyze; do
    if ! command -v "$tool" >/dev/null 2>&1; then
      echo "--service requires Linux systemd with a user session; use foreground mode here." >&2
      exit 2
    fi
  done
fi
if [[ ! -x "$repo_dir/.venv/bin/python" ]]; then
  python_bin="${ANNOTATION_PYTHON:-python3}"
  "$python_bin" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else "Python 3.10+ is required")'
  "$python_bin" -m venv "$repo_dir/.venv"
fi
"$repo_dir/.venv/bin/python" -m pip install -r "$repo_dir/requirements.txt"
echo "Starting annotation editor ($mode); default URL: http://127.0.0.1:18080/editor"
exec "$repo_dir/annotationctl" platform "$mode" --dataset "$dataset" --output "$output" ${options[@]+"${options[@]}"}
