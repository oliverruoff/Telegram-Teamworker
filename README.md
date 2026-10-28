# Telegram Teamworker

Ein kleiner Teamkollege für **eine Telegram-Gruppe**, basierend auf
[pi.lot](https://github.com/oliverruoff/pi.lot) und dem
[pi Coding Agent](https://github.com/earendil-works/pi).

**Kleiner Kern. Fähigkeiten über Skills, MCP und `AGENTS.md` statt Spezialcode.**

## Verhalten

- Liest neue Gruppennachrichten mit, antwortet aber **nur bei `@botusername`**.
- Keine Modellaufrufe für normales Gruppengespräch: Verlauf erst bei der nächsten
  Erwähnung übergeben. Eine Antwort auf den Bot allein genügt nicht.
- Erkennt Absender anhand ihrer Telegram-ID, ihres Namens und Usernames.
- Eine dauerhafte gemeinsame Session, auch über Container-Neustarts hinweg.
- Native pi-Compaction ab standardmäßig 200k Kontext-Tokens; kleinere Modelle
  compacten früher. Nach Erfolg erscheint ausschließlich `compacted.` als Status.
  Diese Meldung ist die einzige ungefragte Gruppenausgabe.
- Bilder und Dokumente nur bei Erwähnung herunterladen, einschließlich zitierter
  Anhänge. Maximale Downloadgröße: 20 MB. Keine Sprachnachrichten oder Videos.
- Alle Gruppenmitglieder dürfen Teamaufgaben stellen. Private Chats dienen nur
  der Administration durch den konfigurierten Betreiber.
- Keine Topics-Trennung: Auch Topics in dieser Gruppe teilen dieselbe Session.

## Einrichtung

Voraussetzungen: Docker, Telegram-Bot-Token und die numerischen Telegram-IDs
deiner Gruppe und deines eigenen Benutzerkontos.

1. Bot bei **@BotFather** erstellen. Gruppenbeitritt erlauben (`/setjoingroups`).
2. **Privacy Mode deaktivieren** (`/setprivacy` → Disable), damit der Bot auch
   Nachrichten ohne Erwähnung erhält. Falls bereits hinzugefügt, den Bot danach
   aus der Gruppe entfernen und erneut hinzufügen. Adminrechte sind nicht nötig.
3. Gruppen-ID und deine Benutzer-ID ermitteln, etwa aus Telegrams Bot-API
   `getUpdates`, **bevor** Teamworker Polling startet. Gruppen-IDs sind negativ.
   Bot-Token und API-Ausgaben nicht öffentlich teilen.
4. Konfiguration anlegen:

   ```sh
   cp .env.example .env
   # TELEGRAM_BOT_TOKEN, TELEGRAM_GROUP_ID und TELEGRAM_OWNER_ID eintragen
   ./deploy.sh
   ```

5. Privat den Bot öffnen, **Start** drücken und `/connect` ausführen. Verbindet
   OpenRouter per API-Key oder ein OpenAI-Abonnement über `openai-codex` OAuth;
   danach Modell und Thinking-Stufe auswählen. Weitere pi-Provider können ihre
   üblichen Umgebungsvariablen und `PI_ARGS` nutzen.
6. In der Gruppe: `@dein_bot_username Kannst du uns helfen?`

Die Gruppe sollte wissen, dass ihre Nachrichten persistent gespeichert und bei
Anfragen an den gewählten Modellanbieter übermittelt werden. Telegram-Bots können
nicht rückwirkend den gesamten Verlauf vor ihrem Beitritt abrufen.

### Einstellungen

| Variable | Bedeutung | Standard |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot-Token | erforderlich |
| `TELEGRAM_GROUP_ID` | Einzige freigegebene Gruppe | erforderlich |
| `TELEGRAM_OWNER_ID` | Einziger Betreiber, persönliche Telegram-ID | erforderlich |
| `PI_ARGS` | Initial `--provider`, `--model`, `--thinking` | optional |
| `COMPACT_TOKENS` | Gewünschte Kontextgrenze für Compaction | `200000` |
| `CONTEXT_RESERVE_TOKENS` | Mindestabstand zur Modell-Kontextgrenze | `16384` |
| `GROUP_CONTEXT_BYTES` | Maximaler zusätzlich übergebener Hintergrund, UTF-8-Bytes | `60000` |
| `GH_TOKEN` | GitHub-Token für ausgewählte Team-Repositories | optional |
| `BRAVE_SEARCH_API_KEY` | Brave-Web-/Nachrichtensuche | optional |

Gespeicherte Modell-/Thinking-Auswahl hat wie bei pi.lot Vorrang vor Startwerten.
Die Compaction-Grenze wird als pi-eigene Einstellung pro ausgewähltem Modell
gesetzt; native Prüfungen zwischen Werkzeugschritten und Overflow-Recovery bleiben
aktiv. Zusätzlich prüft die Bridge vor und nach Gruppenaufträgen.

Nach langem Gruppengespräch wird nur der jüngste passende Hintergrund zusätzlich
in den Prompt aufgenommen. Der vollständige gespeicherte Verlauf bleibt für
gezielte Recherche verfügbar. Große neue Nachrichtenblöcke werden nicht blind in
ein schon volles Kontextfenster geladen.

### Private Betreiberbefehle

| Befehl | Funktion |
|---|---|
| `/connect [openrouter\|openai-codex]` | Provider verbinden, Modell und Thinking auswählen |
| `/model [provider/model]` | Modell auswählen |
| `/thinking [level]` | Thinking-Stufe auswählen |
| `/reload` | Skills, MCP-Konfiguration und Anweisungen neu laden |
| `/status` | Aktivität und Queue anzeigen |
| `/new` | Neue gemeinsame Gruppensession, geordnet hinter bisherigen Aufgaben |
| `/stop` | Lauf abbrechen und wartende Queue leeren |
| `/cancel` | Offenen Eingabedialog abbrechen |
| `/help` | Hilfe |

Normale Aufgaben im privaten Chat werden nicht an den Agenten weitergereicht.
API-Keys, die du für `/connect` eingibst, gehen durch den Telegram-Chatverlauf;
alternativ Umgebungsvariablen verwenden. OAuth erfordert kein Passwort im Bot-Chat.

## Fähigkeiten und Erweiterungen

Mitgeliefert sind vier Skills:

- **github**: `gh` für Code, Issues, PRs, Merges und Workflows.
- **brave-search**: Web-/Nachrichtensuche über Brave.
- **browser-control**: Playwright mit vorinstalliertem Chromium.
- **team-memory**: Selbstständig gepflegte, kurze Markdown-Notizen für Teamwissen.

Bevor du Anwendungscode ergänzt:

1. **Arbeitsweise/Teamwissen:** `workspace/AGENTS.md` bearbeiten, dann `/reload`.
2. **Ablauf:** `workspace/skills/mein-skill/SKILL.md` hinzufügen, dann `/reload`.
3. **Externer Dienst:** Vorhandene CLI oder pi-nativen MCP nutzen.

Pi liest globale MCP-Konfiguration aus
`workspace/data/pi-agent/mcp.json` auf dem Host. Das übliche Format:

```json
{
  "mcpServers": {
    "team-service": {
      "command": "npx",
      "args": ["-y", "dein-mcp-paket@feste-version"]
    }
  }
}
```

Dies ist nur ein Strukturbeispiel, kein installierter Dienst. Die Version und
Zugangsdaten passend zum tatsächlichen Server konfigurieren. Danach `/reload`.
Keine zusätzliche MCP-Bridge erforderlich; pi 1.4.0 bringt MCP-Unterstützung mit.

## Zugriffe und Sicherheitsgrenzen

Nur die konfigurierte Gruppe und dein privater Admin-Chat werden angenommen.
Gruppenmitglieder erhalten dieselben Dienstzugriffe. Anonyme Admin-/Kanalbeiträge
werden als Hintergrund gespeichert, können aber keine Aufgabe auslösen. Editierte
Nachrichten lösen keine erneute Ausführung aus.

Für Merge, Löschen, Force-Push, Workflow-Ausführung und Deployments muss der Agent
vorher die konkrete Aktion erklären und den ursprünglichen Auftraggeber fragen.
Bestätigung wieder **mit @Erwähnung** senden. Diese Regel steckt bewusst in den
Anweisungen und Skills, nicht in einer komplexen eigenen Berechtigungsengine.

**Das ist keine Sandbox und keine technisch erzwungene Bestätigungsbarriere.**
Pi kann Shell-Kommandos ausführen und auf die Container-Umgebung zugreifen.
Anweisungen können nicht garantieren, dass ein Modell niemals Konfiguration oder
Geheimnisse liest oder eine Rückfrage überspringt. Nur für ein vertrauenswürdiges
Team betreiben; echte Grenzen über eng beschränkte Service-Credentials, Repository-
Auswahl und GitHub-Branch-Protection setzen. Kein Docker-Socket oder Host-Home mounten.
Der Container läuft als root; Chromium verwendet den übernommenen Docker-Modus ohne
Sandbox. Unbekannte Dateien und Websites bleiben ein Risiko.

## Daten und Betrieb

`./deploy.sh` baut zuerst das Image und ersetzt dann nur den Container
`telegram-teamworker`. Es mountet `./workspace:/workspace` persistent.

```text
workspace/
  AGENTS.md                 # beim ersten Start initialisiert, nie überschrieben
  skills/                   # eigene Skills
  memory/                   # Teamwissen in Markdown
  data/
    group.sqlite3           # Gruppenverlauf, Queue und Session-Checkpoint
    sessions/               # native pi-Sessions
    pi-agent/               # pi-Zugangsdaten, Einstellungen und MCP-Konfiguration
    files/                  # heruntergeladene Anhänge
    browser-sessions/       # Browser-Loginzustand
```

Keine automatische Löschung: Verlauf, Sessions, Anhänge und Browserzustand bleiben
erhalten. `/new` leert nur den aktiven Modellkontext, nicht das Archiv oder Memory.
Workspace sicher sichern, nicht committen und Speicherverbrauch beobachten.
Für eine konsistente vollständige Sicherung den Container zuvor stoppen.
Ein Workspace ist an seine Gruppen-ID gebunden. Für eine andere Gruppe einen
separaten Workspace verwenden; so kann alter Teamkontext nicht versehentlich
in einer anderen Gruppe landen.

Wartende Anfragen werden nach Neustart fortgesetzt. Bereits laufende Anfragen
werden **nicht automatisch wiederholt**, da externe Schreibaktionen möglicherweise
schon erfolgt sind; du bekommst dazu privat einen Hinweis.

```sh
docker logs --tail 100 telegram-teamworker
docker stop telegram-teamworker
docker start telegram-teamworker
```

Die Bridge protokolliert keine Chattexte oder rohen pi-Providerdiagnosen.
Detailmeldungen von pi werden zum Schutz möglicher Zugangsdaten zurückgehalten.
Für gezielte Diagnose pi bei Bedarf interaktiv im Container starten, niemals
ungeprüfte Diagnosen in die Gruppe oder öffentliche Logs kopieren.

## Entwicklung und Tests

Python 3.12+, Node 22.19+; Runtime fest auf pi **1.4.0** gepinnt.

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
# Optional: echte pi-RPC-/Extensions-Prüfung, ohne Modellaufrufe:
PI_TEST_COMMAND="$(command -v pi)" python -m unittest discover -s tests -v
```

Der Kern besteht aus Telegram-Koordination (`app.py`), Konfiguration (`config.py`),
Nachrichten/Identität (`messages.py`), SQLite-Journal (`store.py`), RPC und Formatierung.
Keine eigene Agentenlaufzeit, Zusammenfassungslogik oder Plugin-Plattform.

Übernommene pi.lot-Bausteine basieren auf Commit
`872b7f3d8d9250ca7d7cea0b9867a251cab27c5d`; siehe [ATTRIBUTION.md](ATTRIBUTION.md).
