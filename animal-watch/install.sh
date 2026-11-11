#!/bin/bash
# Instalare Animal Watch pe macOS (Apple Silicon). Se poate rula de mai multe ori fără probleme.
set -euo pipefail
cd "$(dirname "$0")"
DIR="$(pwd)"
bold() { printf "\n\033[1m%s\033[0m\n" "$*"; }
ok()   { printf "  \033[32m✓\033[0m %s\n" "$*"; }
warn() { printf "  \033[33m!\033[0m %s\n" "$*"; }
ask()  { local a; read -r -p "  $1 [d/N] " a; [[ "$a" =~ ^[dDyY] ]]; }

bold "1. Verific mediul"
[[ "$(uname -s)" == "Darwin" ]] || { echo "Scriptul e pentru macOS."; exit 1; }
ARCH="$(uname -m)"; CHIP="$(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo '?')"
[[ "$ARCH" == "arm64" ]] && ok "Chip: $CHIP ($ARCH)" || warn "Chip $ARCH: nu e Apple Silicon, MPS nu va fi disponibil (merge pe CPU)"
ok "macOS $(sw_vers -productVersion)"

if ! command -v brew >/dev/null 2>&1; then
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [[ -x $b ]] && eval "$($b shellenv)"; done
fi
if ! command -v brew >/dev/null 2>&1; then
  warn "Homebrew nu e instalat."
  if ask "Instalez Homebrew acum (cere parola de admin)?"; then
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    eval "$(/opt/homebrew/bin/brew shellenv)"
  else
    echo "Fără Homebrew trebuie să instalezi manual Python 3.11+ și ffmpeg."; exit 1
  fi
fi
ok "Homebrew $(brew --version | head -1 | awk '{print $2}')"

PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v $c >/dev/null 2>&1 && $c -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null; then
    PY="$(command -v $c)"; break
  fi
done
if [[ -z "$PY" ]]; then
  warn "Python 3.11+ lipsește, instalez python@3.12 cu Homebrew"
  brew install python@3.12
  PY="$(brew --prefix)/bin/python3.12"
fi
ok "Python: $($PY --version) ($PY)"

if ! command -v ffmpeg >/dev/null 2>&1; then
  warn "ffmpeg lipsește, îl instalez cu Homebrew"
  brew install ffmpeg
fi
ok "ffmpeg $(ffmpeg -version | head -1 | awk '{print $3}')"

bold "2. Mediul virtual Python (.venv) și dependențele"
[[ -d .venv ]] || "$PY" -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt
ok "dependențe instalate"
.venv/bin/python - <<'EOF'
import torch
print(f"  ✓ PyTorch {torch.__version__}, MPS (GPU Apple) disponibil: {torch.backends.mps.is_available()}")
EOF

bold "3. Setări private (.env)"
if [[ -f .env ]]; then
  ok ".env există deja (șterge-l dacă vrei să-l refaci)"
else
  read -r -p "  IP-ul DVR-ului (ex. 192.168.1.64): " DVR_IP
  read -r -p "  Port RTSP [554]: " DVR_PORT; DVR_PORT=${DVR_PORT:-554}
  read -r -p "  User DVR (doar live view): " DVR_USER
  read -r -s -p "  Parola DVR (nu se afișează): " DVR_PASS; echo
  read -r -p "  Topic ntfy (ales de tine, greu de ghicit): " NTFY_TOPIC
  umask 077
  DVR_IP="$DVR_IP" DVR_PORT="$DVR_PORT" DVR_USER="$DVR_USER" DVR_PASS="$DVR_PASS" NTFY_TOPIC="$NTFY_TOPIC" \
  .venv/bin/python - <<'EOF2'
import os
q = lambda v: "'" + v.replace("\\", "\\\\").replace("'", "\\'") + "'"
keys = ["DVR_IP", "DVR_PORT", "DVR_USER", "DVR_PASS", "NTFY_TOPIC"]
lines = [f"{k}={q(os.environ[k])}" for k in keys] + ["NTFY_SERVER=https://ntfy.sh", "NTFY_TOKEN="]
open(".env", "w").write("\n".join(lines) + "\n")
EOF2
  chmod 600 .env
  ok ".env creat (permisiuni 600, ignorat de git)"
fi

FRESH_CONFIG=0
if [[ ! -f config.yaml ]]; then cp config.example.yaml config.yaml; FRESH_CONFIG=1; ok "config.yaml creat din config.example.yaml"; fi

bold "4. Modelul YOLO"
MODEL=$(.venv/bin/python -c "from animalwatch import config; print(config.load().section('detection')['model'])")
.venv/bin/python -c "from ultralytics import YOLO; YOLO('$MODEL')" >/dev/null && ok "$MODEL descărcat"

bold "5. Test DVR (ping, port 554, fiecare canal)"
if [[ $FRESH_CONFIG == 1 ]]; then .venv/bin/python -m animalwatch probe --update-config; else .venv/bin/python -m animalwatch probe; fi
echo "  Deschide snapshots_setup/toate_camerele.jpg ca să vezi camerele."

bold "6. Test detecție (YOLO pe imagini cu pisică/câine/vulpe)"
.venv/bin/python -m animalwatch selftest || warn "selftest a eșuat (vezi mesajul de mai sus)"

bold "7. Notificare de test"
if ask "Trimit o notificare de probă pe telefon?"; then .venv/bin/python -m animalwatch test-notify || true; fi

bold "8. Ollama (opțional, identificare specie)"
if command -v ollama >/dev/null 2>&1; then
  ok "Ollama instalat"
  SPECIES_MODEL=$(.venv/bin/python -c "from animalwatch import config; print(config.load().section('species')['model'])")
  if ollama list 2>/dev/null | grep -q "^${SPECIES_MODEL%%:*}"; then ok "model $SPECIES_MODEL prezent"
  elif ask "Descarc modelul $SPECIES_MODEL (~6 GB)?"; then ollama pull "$SPECIES_MODEL"; fi
else
  warn "Ollama nu e instalat. Sistemul merge și fără. Ca să-l adaugi: brew install ollama && brew services start ollama && ollama pull qwen2.5vl:7b"
fi

bold "9. Pornire automată (LaunchAgent)"
if ask "Instalez LaunchAgent-ul (pornește la login și repornește dacă pică)?"; then
  ./scripts/service.sh install
fi

bold "Gata."
echo "  Pagina locală: http://127.0.0.1:8765  (evenimente, zone, test notificare)"
echo "  Ca Mac-ul să nu adoarmă: ./scripts/power.sh (îți explică și îți cere acordul)"
