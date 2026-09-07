# astra

Ein lokaler deutscher Sprachagent für Apple Silicon. Kein Cloud-Anruf, kein
Tracking, kein gespeichertes Audio — Spracherkennung, Sprachmodell und
Sprachausgabe laufen alle auf deinem Mac.

## Wie es funktioniert

Drei lokale Modelle, verbunden über eine [Pipecat](https://github.com/pipecat-ai/pipecat)-Pipeline:

| Stufe | Modell | Wo |
|---|---|---|
| Spracherkennung | Nemotron ASR (streaming) | MLX, on-device |
| Sprachmodell | Qwen 3.5 | über natives Ollama `/api/chat` |
| Sprachausgabe | Pocket TTS, 26 deutsche Stimmen wählbar | MLX, on-device |

Der Browser spricht per WebRTC direkt mit einem FastAPI-Server auf
`localhost:7860`. Der Server ist bewusst nur lokal erreichbar: Host- und
Origin-Prüfung auf jedem Request, strikte Content-Security-Policy, keine
offenen Ports nach außen.

Die Stimme lässt sich im UI per Dropdown wählen (`/api/voices` listet alle
26, Auswahl wird im Browser gemerkt). Jede Stimme wird beim ersten Gebrauch
lazy geladen und danach für die Laufzeit des Prozesses gecacht.

## Bilder erzeugen und Dokumente lesen

Zwei zusätzliche, sauber getrennte Fähigkeiten, unabhängig von STT/LLM/TTS:

- **`astra/comfyui.py`** — reiner async HTTP-Client für einen lokalen
  [ComfyUI](https://github.com/comfyanonymous/ComfyUI)-Server
  (`z-image-turbo`-Workflow). Kennt nichts von Pipecat.
- **`astra/documents.py`** — PDF-Textextraktion (`pypdf`), keine
  Netzwerkzugriffe.
- **`astra/tools.py`** — verdrahtet `generate_image` als natives
  Ollama-Tool. Qwen 3.5 entscheidet selbst, wann es aufgerufen wird
  (`ollama show qwen3.5` listet `tools` als unterstützte Fähigkeit); das
  generierte Bild landet im laufenden Gespräch als `/api/media/<id>` und
  wird per WebRTC-Datenkanal ans UI gemeldet.

Bilder (PNG/JPEG/WebP) und PDFs lassen sich während eines laufenden
Gesprächs über den Button „Bild oder PDF hinzufügen“ hochladen
(`POST /api/upload`). Ein PDF wird als Text in den Gesprächskontext
eingefügt, ein Bild als Base64 mit Qwens nativer Vision-Fähigkeit — beides
nur für die Dauer der Session, nichts wird auf Disk geschrieben.

## Starten

```bash
uv sync
uv run python -m astra.prepare   # lädt & prüft alle drei Modelle einmalig
uv run python -m astra.server    # startet auf http://localhost:7860
```

Ollama muss separat laufen (`ollama serve`) und `qwen3.5:latest` muss
gezogen sein. Die Seite öffnen, Mikrofon erlauben, sprechen.

## Konfiguration

Über Umgebungsvariablen, siehe `astra/core.py::Settings`:

| Variable | Default |
|---|---|
| `ASTRA_MODEL` | `qwen3.5:latest` |
| `ASTRA_OLLAMA_URL` | `http://127.0.0.1:11434` |
| `ASTRA_STT_MODEL` | `mlx-community/nemotron-3.5-asr-streaming-0.6b-8bit` |
| `ASTRA_TTS_LANGUAGE` | `german` |
| `ASTRA_VOICE` | `alba` |
| `ASTRA_PORT` | `7860` |
| `ASTRA_TAILNET_HOST` | *(leer)* — z. B. `minim4-1.tail0f2cb2.ts.net` |
| `ASTRA_COMFYUI_URL` | `http://100.125.107.123:8000` |

## Tests

```bash
uv run pytest
uv run ruff check .
```

## Im Tailnet freigeben

Standardmäßig nur `localhost` erreichbar. Für Zugriff von einem anderen
Gerät im selben Tailscale-Netz:

```bash
tailscale serve --bg 7860
ASTRA_TAILNET_HOST="$(tailscale status --json | python3 -c 'import json,sys;print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')" \
  uv run python -m astra.server
```

Danach ist die Seite unter `https://<tailnet-host>/` erreichbar (Port 443,
implizit — Tailscale terminiert TLS und proxyt auf 7860). Host- und
Origin-Prüfung lassen dann zusätzlich diesen einen Hostnamen durch.

## Sicherheit

- Nur `localhost`/`127.0.0.1` (bzw. der optionale Tailnet-Host) erreichbar,
  alle anderen Hosts bekommen 403
- POST-Requests werden gegen den erwarteten Origin geprüft
- `think` ist im Ollama-Request hart auf `false` gesetzt — die Pipeline
  wirft, falls das Modell trotzdem Denkausgabe liefert
- Kein Audio, keine Transkripte werden auf Disk geschrieben; der
  Gesprächsverlauf lebt nur im Speicher der laufenden Session

---

Erstellt von Astra (Grunddeploy), gecheckt, dokumentiert und bewertet durch Claude.
