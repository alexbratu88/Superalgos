#!/bin/bash
# Gestionează LaunchAgent-ul: install | uninstall | start | stop | restart | status | logs
set -euo pipefail
cd "$(dirname "$0")/.."
DIR="$(pwd)"
LABEL="ro.local.animalwatch"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

write_plist() {
  mkdir -p "$HOME/Library/LaunchAgents" "$DIR/logs"
  cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$DIR/.venv/bin/python</string><string>-m</string><string>animalwatch</string><string>run</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>PYTORCH_ENABLE_MPS_FALLBACK</key><string>1</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>15</integer>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$DIR/logs/launchd.out.log</string>
  <key>StandardErrorPath</key><string>$DIR/logs/launchd.err.log</string>
</dict>
</plist>
PL
  plutil -lint "$PLIST" >/dev/null
}

loaded() { launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; }

case "${1:-status}" in
  install)
    write_plist
    loaded && launchctl bootout "$DOMAIN/$LABEL" || true
    launchctl bootstrap "$DOMAIN" "$PLIST"
    echo "Instalat și pornit: $PLIST"
    echo "Pagina: http://127.0.0.1:8765 (pornirea durează ~20 s)"
    echo "La prima rulare macOS poate întreba dacă Python are voie să acceseze rețeaua locală: alege Permite."
    ;;
  uninstall)
    loaded && launchctl bootout "$DOMAIN/$LABEL" || true
    rm -f "$PLIST"; echo "LaunchAgent dezinstalat."
    ;;
  start)   loaded || launchctl bootstrap "$DOMAIN" "$PLIST"; launchctl kickstart "$DOMAIN/$LABEL"; echo pornit ;;
  stop)    loaded && launchctl bootout "$DOMAIN/$LABEL" && echo "oprit (pornește din nou la login sau cu: $0 start)" || echo "nu rulează" ;;
  restart) launchctl kickstart -k "$DOMAIN/$LABEL"; echo repornit ;;
  status)
    if loaded; then launchctl print "$DOMAIN/$LABEL" | grep -E "state =|pid =|last exit" | sed 's/^\s*/  /'
      .venv/bin/python -m animalwatch perf 2>/dev/null | head -40 || true
    else echo "nu rulează"; fi ;;
  logs)    tail -n 100 -f logs/animalwatch.log ;;
  *) echo "folosire: $0 install|uninstall|start|stop|restart|status|logs"; exit 1 ;;
esac
