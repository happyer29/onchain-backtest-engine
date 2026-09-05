#!/usr/bin/env bash

set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "error: this helper must run inside WSL2/Ubuntu" >&2
  exit 2
fi

if [[ -z "${WSL_DISTRO_NAME:-}" ]] || ! uname -r | grep -Eqi 'microsoft-standard-WSL2|wsl2'; then
  echo "error: WSL2 was not detected; native Windows and WSL1 are unsupported" >&2
  exit 2
fi

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
case "$project_root/" in
  /mnt/*)
    echo "error: clone the repository inside the WSL Linux filesystem, not under /mnt" >&2
    exit 2
    ;;
esac

filesystem_type="$(stat -f -c '%T' "$project_root")"
case "${filesystem_type,,}" in
  9p|drvfs|cifs|smb*|fuseblk)
    echo "error: unsupported repository filesystem for durable publication: $filesystem_type" >&2
    exit 2
    ;;
esac

cd "$project_root"

if ! command -v uv >/dev/null 2>&1; then
  echo "error: uv is not installed inside Ubuntu; see docs/getting-started.md" >&2
  exit 2
fi

uv sync --all-groups --frozen
uv run python -c \
  'from pathlib import Path; from backtest.bootstrap.config import load_settings; load_settings(Path("configs/local-windows-wsl2-16gb.toml"))'
uv run backtest --help >/dev/null

echo "Windows 11 / WSL2 profile smoke passed."
