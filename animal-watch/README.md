# 🐾 Animal Watch

Sistem local și gratuit care urmărește camerele DVR-ului Hikvision, detectează animalele din curte cu YOLO (pe GPU-ul Apple Silicon) și îți trimite notificare pe telefon prin **ntfy**, cu poză. Opțional, un model vizual local (Ollama) spune ce specie e (vulpe, jder, arici, mistreț…).

Nu modifică nimic pe DVR, ci doar citește stream-urile RTSP. Singurul serviciu din cloud folosit e ntfy.sh.

## Instalare (o singură dată)

```bash
cd animal-watch
./install.sh
```

Scriptul:
1. verifică chip-ul, macOS, Homebrew, Python 3.11+ și ffmpeg (instalează ce lipsește);
2. creează mediul Python `.venv` și instalează dependențele;
3. îți cere **IP-ul DVR-ului, userul, parola** (un user doar cu live view) și **topicul ntfy**, apoi le scrie în `.env` (permisiuni 600, nu intră în git);
4. testează DVR-ul (ping, port 554, fiecare canal 1–8, substream + main stream) și salvează câte un snapshot în `snapshots_setup/` (`toate_camerele.jpg` = toate pe o pagină);
5. rulează YOLO pe imagini de test (pisică, câine, vulpe);
6. trimite o notificare de test;
7. verifică Ollama (opțional) și instalează LaunchAgent-ul.

Pe telefon: în aplicația ntfy apasă **+** și abonează-te la același topic, pe serverul `ntfy.sh`.
Topicul e ca o parolă: oricine îl știe poate citi notificările, așa că alege ceva greu de ghicit.

## Pornire / oprire

| Ce | Comandă |
|---|---|
| Pornește la login + repornire automată dacă pică | `./scripts/service.sh install` |
| Oprește | `./scripts/service.sh stop` |
| Pornește | `./scripts/service.sh start` |
| Repornește (după ce editezi config.yaml) | `./scripts/service.sh restart` |
| Stare, CPU, FPS, camere | `./scripts/service.sh status` |
| Loguri live | `./scripts/service.sh logs` |
| Rulare manuală în terminal (pentru teste) | `.venv/bin/python -m animalwatch run` |

Pagina locală (doar pe acest Mac): **http://127.0.0.1:8765**
- **Evenimente**: istoric cu poze, filtrabil pe cameră, animal și zi, plus starea camerelor și a CPU-ului;
- **Zone**: editorul de zone;
- butonul **Trimite notificare de test**.

## Zone (unde contează o detecție)

1. Deschide http://127.0.0.1:8765/zones și alege camera.
2. Click pe imagine = punct nou. Dublu-click sau Enter = închizi poligonul. Poți desena mai multe zone. Click dreapta pe o zonă = o ștergi.
3. **Punct verificat**: *baza box-ului* (recomandat, adică „picioarele” animalului sunt în zonă) sau *centrul*.
4. **Salvează**. Se scrie în `config.yaml` și se aplică imediat, fără repornire.

Fără nicio zonă, tot cadrul contează. Zonele sunt salvate în coordonate relative (0–1), deci merg și pe substream, și pe main stream.

## Praguri și setări (`config.yaml`)

După modificări: `./scripts/service.sh restart`.

| Setare | Ce face | Dacă primești… |
|---|---|---|
| `detection.min_confidence` / `class_confidence` | prag de încredere (global / per clasă) | alarme false → crește (0.5–0.6); animale ratate → scade (0.35) |
| `detection.min_box_area` | box minim, ca fracție din cadru | alarme pe lucruri mici/îndepărtate → crește (0.005) |
| `detection.confirm_frames` | câte cadre consecutive confirmă detecția | alarme false scurte → 4–5; animale rapide ratate → 2 |
| `detection.cooldown_seconds` | pauză per cameră + clasă după o alertă | prea multe notificări → 600–900 |
| `detection.classes` | ce clase se urmăresc | șterge `bird` dacă te deranjează păsările |
| `detection.fps_per_camera` | cadre analizate pe secundă | Mac încărcat → 1.0 |
| `detection.model` | `yolo11s.pt` (implicit) / `yolo11n.pt` (mai ușor) | |
| `cameras[].enabled` | activează / dezactivează o cameră | |
| `notifications.quiet_hours` | ore de liniște (evenimentele se salvează, nu se trimit) | |
| `notifications.priority`, `class_priority` | prioritatea în ntfy (1–5) | |
| `storage.retention_days` | după câte zile se șterge istoricul (implicit 30) | |
| `autotune` | reduce FPS-ul (și la nevoie trece pe yolo11n) dacă CPU-ul trece de `max_cpu_percent` | |

## Schimbarea topicului ntfy (sau a parolei DVR)

Editează `.env` (de ex. `open -e .env`), schimbă `NTFY_TOPIC=...`, apoi:

```bash
./scripts/service.sh restart
.venv/bin/python -m animalwatch test-notify
```

## Identificarea speciei (opțional, Ollama)

Clasele YOLO (COCO) nu includ vulpe, jder, arici sau mistreț. O vulpe poate apărea ca „câine” sau „cal”. Dacă Ollama rulează, poza e trimisă local la un model vizual, iar specia apare în titlu (ex. „Vulpe – Camera 3”).

```bash
brew install ollama
brew services start ollama
ollama pull qwen2.5vl:7b      # ~6 GB; alternativ: llava:7b (setează species.model)
```

Aplicația detectează singură Ollama (verifică la fiecare 5 minute). Fără Ollama totul merge normal, iar titlul folosește clasa YOLO. Ca să-l dezactivezi complet: `species.enabled: false`.

## Mac-ul să nu adoarmă

```bash
./scripts/power.sh        # explică variantele și cere acordul
./scripts/power.sh undo   # revine la setările implicite
```

## Comenzi utile

```bash
.venv/bin/python -m animalwatch probe                    # retestează DVR-ul + snapshot-uri
.venv/bin/python -m animalwatch selftest poza.jpg        # YOLO pe o imagine
.venv/bin/python -m animalwatch simulate poza.jpg --camera 3   # tot lanțul: filtre, zone, specie, istoric, ntfy
.venv/bin/python -m animalwatch test-notify
.venv/bin/python -m animalwatch cleanup --days 30
.venv/bin/python -m animalwatch perf                     # CPU, FPS, timp inferență, camere
```

## Fișiere

| Unde | Ce |
|---|---|
| `.env` | IP DVR, user, parolă, topic ntfy (privat) |
| `config.yaml` | toate setările + zonele |
| `events/AAAA-LL-ZZ/*.jpg`, `events/events.db` | istoricul (SQLite) |
| `logs/animalwatch.log` | log rotativ (5 × 5 MB) |
| `snapshots_setup/` | snapshot-uri de la instalare/test |
| `~/Library/LaunchAgents/ro.local.animalwatch.plist` | pornirea automată |

## Dezinstalare

```bash
./uninstall.sh      # oprește serviciul, scoate LaunchAgent-ul, opțional șterge datele
./scripts/power.sh undo   # dacă ai schimbat setările de sleep
```

## Probleme frecvente

- **Camerele nu se conectează când rulează ca serviciu, dar merg din terminal**: pe macOS 15+, verifică în *System Settings → Privacy & Security → Local Network* că Python are acces.
- **401 la probe**: user/parolă greșite sau userul nu are drept de live view pe canalele respective.
- **Mac-ul e încărcat**: `./scripts/service.sh status`. Scade `fps_per_camera` sau treci pe `yolo11n.pt` (autotune face asta automat).
