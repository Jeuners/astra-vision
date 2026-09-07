# astra-vision

**Fork von [astra-local-voice](https://github.com/Jeuners/astra-local-voice).**
Gleicher lokaler Sprachagent, plus Bilderzeugung (ComfyUI) und Bild/PDF-Upload
mit Vision (siehe unten). Die schlanke Basisversion ohne diese Werkzeuge lebt
im Hauptrepo — dorthin zurück, falls du nur den reinen Sprachagenten willst.

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

## Nachrichten aus deutschen RSS-Feeds

- **`astra/feeds.py`** — kuratierte Feed-Liste, nach Thema gruppiert
  (`tech`, `nachrichten`, `wirtschaft`, `hilden` — lokal für Hilden via
  RP ONLINE). Reine Daten, editierbar.
- **`astra/rss.py`** — async Feed-Client (`feedparser`), holt konfigurierte
  Feeds eines Themas parallel ab, überspringt nicht erreichbare Feeds statt
  komplett zu scheitern.
- Tool `read_news` in `astra/tools.py`: Astra ruft es auf, wenn nach
  aktuellen Nachrichten gefragt wird, und fasst die Schlagzeilen mündlich
  zusammen statt sie roh vorzulesen.
- **`astra/articles.py`** — lädt eine Artikel-URL und extrahiert den reinen
  Fließtext (`trafilatura`), ohne Navigation/Werbung/Boilerplate.
- Tool `read_article` in `astra/tools.py`: Astra ruft es auf, wenn der
  Nutzer zu einer schon genannten Schlagzeile mehr wissen will, und liest
  den vollen Artikeltext statt nur der RSS-Kurzbeschreibung.

Tool-Verhalten steht bewusst ausschließlich in der jeweiligen
`FunctionSchema.description` (siehe `astra/tools.py`), nicht im
`SYSTEM_PROMPT` — eine Quelle der Wahrheit pro Werkzeug statt duplizierter
Regeln in einem wachsenden globalen Prompt. Gemessener Preis davon: mit
drei gleichzeitig verfügbaren Tools (Bild + Nachrichten + Artikel) ruft
das lokale 9,7B-Modell `read_news` nur noch in ca. 15–20 % der Fälle
tatsächlich auf (vorher mit zwei Tools ca. 20–50 %, mit Tool-Regeln
zusätzlich im System-Prompt ca. 60–75 %) und erfindet sonst Schlagzeilen.
`read_article` ist bei einer konkreten Nachfrage zu einer schon genannten
Schlagzeile brauchbarer (~65 %, vermutlich weil der Kontext dort weniger
mehrdeutig ist). Bildgenerierung bleibt bei ~100 % zuverlässig. Bekannte
Grenze eines kleinen lokalen Modells bei Tool-Konkurrenz, kein Bug — die
saubere Trennung war eine bewusste Architekturentscheidung.

**`astra/triggers.py`** umgeht diese Grenze gezielt für `read_news`: ein
einfacher Keyword-Check (`nachrichten`/`news` + optional ein Themen-Alias
wie `hilden`/`technik`/`wirtschaft`) im transkribierten Nutzertext ruft
den `read_news`-Handler direkt auf — derselbe Handler, dieselbe UI,
nur ohne die unzuverlässige LLM-Entscheidung dazwischen. Das Ergebnis
landet als Tool-Roundtrip im Kontext, damit die nächste LLM-Antwort es
kennt. Live getestet: 2/2 zuverlässig, wo die reine LLM-Entscheidung nur
~15–20 % erreichte.

Schlagzeilen werden nummeriert angezeigt (1., 2., 3. …), und derselbe
Mechanismus kennt einen zweiten Trigger: `detect_article_reference()`
erkennt Formulierungen wie "Artikel 2", "Artikel Nummer drei" oder
"zweiter Artikel" im Nutzertext, löst die Nummer gegen die zuletzt
gezeigte Liste auf und ruft `read_article` direkt mit dem passenden Link
auf — ganz ohne dass das Modell selbst den richtigen Link kennen oder
sich für das Werkzeug entscheiden muss. Live getestet über einen echten
Zwei-Turn-Dialog ("News Hilden" → "Hole mir Detail zu Artikel zwei"):
korrekt aufgelöst, echter Artikeltext abgerufen.

`generate_image` bleibt bewusst ein reines LLM-Tool, weil ein Bildwunsch
zu variabel für ein Keyword-Muster ist und ohnehin zuverlässig
funktioniert.

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
