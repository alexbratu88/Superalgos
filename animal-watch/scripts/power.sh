#!/bin/bash
# Setări de sleep, ca Mac-ul să nu adoarmă cât e în priză. Nu schimbă nimic fără acordul tău.
set -euo pipefail
cd "$(dirname "$0")/.."
cat <<'TXT'
Cât timp Mac-ul doarme, camerele nu sunt analizate. Ai două variante:

 A) caffeinate (recomandat, fără sudo, ușor de anulat)
    Aplicația pornește "caffeinate -s" cât timp rulează. -s împiedică doar sleep-ul
    sistemului și DOAR când Mac-ul e în priză; pe baterie Mac-ul adoarme normal.
    Ecranul se poate stinge în continuare. Se oprește singur când oprești aplicația.
    Setare: power.caffeinate: true în config.yaml.

 B) pmset (setare de sistem, cere parola de admin)
    sudo pmset -c sleep 0      -> în priză (-c), sistemul nu mai intră în sleep
    sudo pmset -c displaysleep 10  -> ecranul se stinge după 10 min (economie)
    Pe baterie (-b) nu se schimbă nimic. Se anulează cu: ./scripts/power.sh undo

 Atenție: cu capacul închis un MacBook adoarme oricum, dacă nu are monitor extern
 (clamshell). Lasă capacul deschis sau folosește un monitor/HDMI dummy.

Setările actuale (în priză):
TXT
pmset -g custom 2>/dev/null | awk '/AC Power/{f=1} f&&/ (sleep|displaysleep) /' || true
echo

case "${1:-}" in
  undo)
    echo "Revin la valorile implicite pentru priză: sleep 1, displaysleep 10 (cere parola)."
    sudo pmset -c sleep 1 displaysleep 10
    sed -i '' 's/^\(  caffeinate:\) true/\1 false/' config.yaml 2>/dev/null || true
    echo "Gata. Repornește aplicația: ./scripts/service.sh restart"; exit 0 ;;
esac

read -r -p "Ce aleg? [A = caffeinate / B = pmset / N = nimic] " c
case "$c" in
  A|a) sed -i '' 's/^\(  caffeinate:\) false/\1 true/' config.yaml
       if grep -q "caffeinate: true" config.yaml; then
         echo "Activat în config.yaml."
         ./scripts/service.sh restart 2>/dev/null || echo "Pornește/repornește aplicația ca să se aplice."
       else echo "Editează manual config.yaml: power.caffeinate: true"; fi ;;
  B|b) sudo pmset -c sleep 0 displaysleep 10 && echo "Setat. Verifică: pmset -g custom" ;;
  *) echo "Nu am schimbat nimic." ;;
esac
