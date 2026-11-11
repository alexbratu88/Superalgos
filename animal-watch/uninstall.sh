#!/bin/bash
# Dezinstalează Animal Watch: oprește serviciul și șterge LaunchAgent-ul.
# Opțional șterge și istoricul, logurile, mediul Python și .env.
set -euo pipefail
cd "$(dirname "$0")"
./scripts/service.sh uninstall || true
read -r -p "Șterg și istoricul (events/), logurile, snapshot-urile, .venv și .env? [d/N] " a
if [[ "$a" =~ ^[dDyY] ]]; then
  rm -rf events logs snapshots_setup .venv .env tests/images *.pt
  echo "Șterse. Poți șterge acum tot folderul: rm -rf \"$(pwd)\""
fi
if pmset -g custom 2>/dev/null | awk '/AC Power/{f=1} f&&/ sleep /{print $2}' | grep -qx 0; then
  echo "Notă: sleep-ul în priză e dezactivat (pmset). Pentru revenire: sudo pmset -c sleep 1"
fi
echo "Ollama și Homebrew (dacă le-ai instalat) rămân; le scoți cu: brew uninstall ollama ffmpeg"
