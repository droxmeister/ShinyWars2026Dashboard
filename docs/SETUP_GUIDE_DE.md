# Vollständige Einrichtung: Shiny Wars 2026 Strategy Dashboard

## 1. Zielbild

Nach der Einrichtung funktioniert der Workflow ohne lokalen Rechner:

1. Ein berechtigter Editor trägt im privaten Google Sheet ein, **welcher Spieler welches Shiny gefangen hat**.
2. GitHub Actions liest das Sheet alle 15 Minuten.
3. Der Python-Parser ordnet jedes Pokémon seiner Wertungs-Evolutionslinie zu.
4. Der Parser berechnet:
   - ein Team-Ranking,
   - ein individuelles Ranking für jeden aktiven Spieler,
   - jeweils die Top 25 Spots für Saison und Tageszeit.
5. GitHub Pages veröffentlicht das aktualisierte englische Dashboard.
6. Im Dashboard wird über ein Dropdown zwischen **Team overall** und den Spielern gewechselt.

Es gibt nur einen Workflow und eine Website. Die 29 derzeit gelieferten Spielernamen werden innerhalb eines Laufs verarbeitet; es entstehen keine separaten Deployments.

---

## 2. Wichtige fachliche Festlegung

### 2.1 Benötigte Fangdaten

Die manuelle Eingabe besteht nur aus:

- `Player`
- `Pokemon`
- `Active`
- optional `Notes`

Zeitpunkt, Anzahl und tatsächlicher Fangort werden nicht für das Scoring benötigt.

### 2.2 Persönliche Spot-Sperre ohne Fangort

Standardmäßig gilt folgende ableitbare Regel:

> Hat ein Spieler bereits irgendeine Wertungs-Evolutionslinie gefangen, die an einem Spot verfügbar ist, wird der gesamte Spot aus seinem Ranking entfernt.

Beispiel: Ein Spieler besitzt bereits Volbeat. Alle Route-Kontexte, in denen die Volbeat-Wertungsfamilie vorkommt, werden für diesen Spieler ausgeschlossen.

Dadurch reichen Spieler und Pokémon als Input. Diese Regel ist strenger als „nur die Route sperren, an der der Fang tatsächlich erfolgte“. Für eine Sperre des tatsächlichen Fangortes müsste künftig zusätzlich die `location_id` des Fangs gespeichert werden.

Die Regel kann in `config/dashboard_config.json` deaktiviert werden:

```json
"exclude_player_context_if_any_target_family_caught": false
```

Dann bleiben alle Spots sichtbar und persönliche Duplikatfamilien werden lediglich mit dem konfigurierten Duplikatwert bewertet.

### 2.3 Location IDs

Alle Berechnungen und Verknüpfungen verwenden die `location_id`.

In der Anzeige stehen zusätzlich:

- Region
- Routen- beziehungsweise Ortsname
- Encounter-Methode
- Saison
- Tageszeit

Bei mehrfach verwendeten Ortsnamen wird die ID sichtbar ergänzt, zum Beispiel:

```text
Relic Castle (Depths) [Location ID 168]
```

---

## 3. Neues Google-Konto anlegen

### 3.1 Kontotyp

Erstellt ein eigenständiges Administrationskonto, zum Beispiel:

```text
teamuxie.shinywars@gmail.com
```

Das Konto sollte nicht das private Konto einer einzelnen Person sein. Das Passwort sollte trotzdem **nicht** unter allen Editoren geteilt werden. Das Administrationskonto besitzt das Sheet; die ausgewählten Bearbeiter erhalten Zugriff über ihre eigenen Google-Konten.

Google-Konto erstellen:

- https://support.google.com/accounts/answer/27441?hl=de

### 3.2 Sicherheit direkt einrichten

Nach der Erstellung:

1. Wiederherstellungs-E-Mail hinterlegen.
2. Wiederherstellungstelefonnummer hinterlegen.
3. 2‑Faktor-Authentifizierung aktivieren.
4. Backup-Codes sicher im Passwortmanager des Admin-Kreises speichern.
5. Keine Zugangsdaten in Discord, GitHub oder dem Google Sheet ablegen.

Google beschreibt die 2‑Faktor-Authentifizierung hier:

- https://support.google.com/accounts/answer/185839

---

## 4. Google Sheet aus der Vorlage erstellen

Vorlage:

```text
templates/shiny_wars_google_sheet_template.xlsx
```

### 4.1 Import

1. Mit dem neuen Administrationskonto Google Drive öffnen.
2. **Neu → Datei hochladen** auswählen.
3. Die XLSX-Vorlage hochladen.
4. Datei mit Google Tabellen öffnen.
5. **Datei → Als Google Tabellen speichern** verwenden, damit ein natives Google Sheet entsteht.
6. Das Dokument beispielsweise nennen:

```text
Team Uxie — Shiny Wars 2026 Catch Tracker
```

Der native Google-Sheets-Typ ist wichtig, weil Schutzbereiche und Bearbeitungsfunktionen zuverlässiger funktionieren.

### 4.2 Enthaltene Tabellenblätter

#### `Players`

Manuell gepflegt:

| Player | Active | Notes |
|---|---|---|
| cazartic | TRUE | |
| ThisIsMyWay | TRUE | |

Die Vorlage enthält die 29 gelieferten Namen. Eine freie Zeile ist für das noch fehlende 30. Mitglied vorgesehen.

Regeln:

- Schreibweise der In-Game-Namen möglichst nicht nachträglich verändern.
- Ausgeschiedene Spieler auf `FALSE` setzen, nicht löschen.
- Neue Spieler am Ende ergänzen.

#### `Catches`

Manuell gepflegt:

| Player | Pokemon | Active | Notes |
|---|---|---|---|
| Droxi | Volbeat | TRUE | |

Regeln:

- Pro Spieler/Pokémon-Kombination genügt eine Zeile.
- Mehrfache identische Zeilen erhöhen den Score nicht und werden vom Parser ignoriert.
- Fehlerhafte Einträge auf `FALSE` setzen.
- Pokémon über das Dropdown auswählen.
- Die Anzahl gefangener Exemplare ist irrelevant.

#### `Pokemon Lookup`

Nicht manuell bearbeiten. Enthält:

- alle 720 Pokémon-Namen aus der JSON,
- zugeordnete Wertungsfamilie,
- Tier,
- Basispunkte,
- Horde-Verfügbarkeit.

#### Automatisch erzeugte Tabs

- `Sync Status`
- `Team Checklist`
- `Player Summary`

Diese Blätter werden nach jedem erfolgreichen GitHub-Lauf überschrieben.

### 4.3 Checkboxen und Dropdowns prüfen

Die Vorlage enthält Datenvalidierungen. Nach dem Import kontrollieren:

- `Catches!A:A`: Dropdown aus `Players`
- `Catches!B:B`: Dropdown aus `Pokemon Lookup`
- `Active`: `TRUE`/`FALSE`

Optional können die Active-Spalten markiert und über **Einfügen → Kästchen** in echte Google-Sheets-Checkboxen umgewandelt werden.

Offizielle Google-Hilfen:

- Dropdowns: https://support.google.com/docs/answer/186103
- Checkboxen: https://support.google.com/docs/answer/7684717

### 4.4 Bearbeitungsrechte

Das Sheet auf **Eingeschränkt** lassen und nur bestimmte Google-Konten hinzufügen.

Empfohlene Gruppen:

- 2 Administratoren: vollständige Bearbeitung
- ausgewählte Catch-Editoren: Bearbeitung
- übrige Teammitglieder: optional nur Betrachter

Google-Drive-Freigabe:

- https://support.google.com/drive/answer/2494822?hl=de

### 4.5 Blätter schützen

Über **Daten → Blätter und Bereiche schützen**:

Komplett schützen:

- `Pokemon Lookup`
- `Sync Status`
- `Team Checklist`
- `Player Summary`
- `Start Here`

Bearbeitbar lassen:

- `Players` nur für Admins
- `Catches` für die ausgewählten Bearbeiter

Google-Hilfe:

- https://support.google.com/docs/answer/1218656?hl=de

---

## 5. Google Cloud und Service Account

GitHub Actions benötigt einen technischen Benutzer, um das private Sheet zu lesen und die erzeugten Tabs zu aktualisieren.

### 5.1 Cloud-Projekt erstellen

1. Mit dem neuen Google-Konto die Google Cloud Console öffnen.
2. Neues Projekt erstellen:

```text
shiny-wars-2026-dashboard
```

3. Das Projekt auswählen.
4. Unter **APIs & Services → Library** die **Google Sheets API** aktivieren.

Google Sheets API Quickstart:

- https://developers.google.com/workspace/sheets/api/quickstart/python

### 5.2 Service Account erstellen

1. **IAM & Admin → Service Accounts** öffnen.
2. **Create service account** auswählen.
3. Name:

```text
shiny-wars-dashboard
```

4. Beschreibung:

```text
Reads the private catch tracker and writes generated Shiny Wars status tabs.
```

5. Für das Cloud-Projekt selbst ist keine weitreichende Rolle erforderlich. Der Zugriff auf das Sheet erfolgt später durch direkte Freigabe an die Service-Account-E-Mail.
6. Erstellung abschließen.

Die E-Mail sieht ungefähr so aus:

```text
shiny-wars-dashboard@shiny-wars-2026-dashboard.iam.gserviceaccount.com
```

Google-Dokumentation:

- https://cloud.google.com/iam/docs/service-accounts-create

### 5.3 JSON-Schlüssel erstellen

1. Den erstellten Service Account öffnen.
2. Tab **Keys** auswählen.
3. **Add key → Create new key**.
4. Typ **JSON**.
5. Datei herunterladen.

Wichtig:

- Die Datei ist ein geheimer privater Schlüssel.
- Niemals ins GitHub-Repository hochladen.
- Nach dem Eintragen als GitHub Secret lokal sicher löschen oder verschlüsselt archivieren.
- Bei Verdacht auf Veröffentlichung den Schlüssel sofort in Google Cloud löschen und neu erstellen.

Google-Dokumentation:

- https://cloud.google.com/iam/docs/keys-create-delete

### 5.4 Sheet mit Service Account teilen

1. Google Sheet öffnen.
2. **Freigeben**.
3. Service-Account-E-Mail einfügen.
4. Rolle **Bearbeiter** auswählen.
5. Benachrichtigung muss nicht gesendet werden.

Editor ist erforderlich, weil der Workflow `Sync Status`, `Team Checklist` und `Player Summary` aktualisiert.

### 5.5 Spreadsheet ID kopieren

Aus der URL:

```text
https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/edit
```

ist die ID:

```text
1AbCdEfGhIjKlMnOpQrStUvWxYz
```

---

## 6. GitHub-Repository erstellen

### 6.1 Sichtbarkeit

Für GitHub Pages auf einem kostenlosen GitHub-Konto ist ein öffentliches Repository die einfachste Variante.

Empfohlener Name:

```text
shiny-wars-2026-dashboard
```

Wichtig: Das Repository enthält **keinen** Google-Schlüssel und keine private Sheet-URL. Die veröffentlichte Website selbst ist öffentlich erreichbar und zeigt Spielernamen und strategische Rankings. Falls diese Informationen geheim bleiben müssen, ist öffentliches GitHub Pages nicht die richtige Plattform. Private Pages-Zugriffskontrolle ist laut GitHub eine Enterprise-Cloud-Funktion.

GitHub-Dokumentation:

- Repository erstellen: https://docs.github.com/repositories/creating-and-managing-repositories/creating-a-new-repository
- Pages mit benutzerdefiniertem Workflow: https://docs.github.com/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages
- Private Pages: https://docs.github.com/enterprise-cloud@latest/pages/getting-started-with-github-pages/changing-the-visibility-of-your-github-pages-site

### 6.2 Projektdateien hochladen

Den Inhalt dieses Pakets in die Wurzel des Repositories laden. In GitHub müssen direkt sichtbar sein:

```text
.github/
config/
data/
docs/
src/
templates/
tests/
web/
requirements.txt
README.md
```

Nicht nur den äußeren ZIP-Ordner als Unterordner hochladen.

Mit Git lokal:

```bash
git init
git add .
git commit -m "Initial Shiny Wars dashboard"
git branch -M main
git remote add origin https://github.com/USERNAME/shiny-wars-2026-dashboard.git
git push -u origin main
```

Alternativ können die Dateien über **Add file → Upload files** hochgeladen werden. Bei der großen `monsters.json` ist Git lokal meist zuverlässiger.

---

## 7. GitHub Secrets anlegen

Repository öffnen:

```text
Settings → Secrets and variables → Actions → New repository secret
```

### Secret 1

Name:

```text
GOOGLE_SERVICE_ACCOUNT_JSON
```

Wert:

Der **vollständige Inhalt** der heruntergeladenen JSON-Datei, beginnend mit `{` und endend mit `}`.

### Secret 2

Name:

```text
GOOGLE_SHEET_ID
```

Wert:

Die kopierte Spreadsheet ID.

GitHub stellt Secrets einem Workflow nur bereit, wenn sie ausdrücklich referenziert werden. Sie werden nicht in die Pages-Dateien geschrieben.

GitHub-Dokumentation:

- https://docs.github.com/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets

---

## 8. GitHub Pages aktivieren

1. Repository → **Settings**.
2. Links **Pages** öffnen.
3. Unter **Build and deployment** als Source **GitHub Actions** auswählen.
4. Speichern.

Der mitgelieferte Workflow verwendet die offiziellen Pages-Actions:

- `actions/configure-pages@v5`
- `actions/upload-pages-artifact@v4`
- `actions/deploy-pages@v4`

Er besitzt die erforderlichen Berechtigungen:

```yaml
permissions:
  contents: read
  pages: write
  id-token: write
```

---

## 9. Ersten Lauf starten

1. Repository → **Actions**.
2. Workflow **Update Shiny Wars dashboard** auswählen.
3. **Run workflow**.
4. Branch `main` wählen.
5. Lauf starten.

Der Workflow erledigt:

1. Repository auschecken.
2. Python installieren.
3. Abhängigkeiten installieren.
4. Tests ausführen.
5. Google Sheet lesen.
6. Team- und Spieler-Rankings berechnen.
7. Google-Sheets-Ausgabetabs aktualisieren.
8. `web/data/strategy.json` erzeugen.
9. Website als Pages-Artefakt hochladen.
10. GitHub Pages deployen.

Bei Erfolg zeigt der Deploy-Job die Pages-URL an, normalerweise:

```text
https://USERNAME.github.io/shiny-wars-2026-dashboard/
```

---

## 10. Automatischer Rhythmus

Der Workflow läuft in:

```text
.github/workflows/update-dashboard.yml
```

alle 15 Minuten zu Minute 7, 22, 37 und 52:

```yaml
schedule:
  - cron: "7,22,37,52 * * * *"
```

Die Zeiten liegen bewusst nicht am Stundenanfang. GitHub weist darauf hin, dass geplante Workflows bei hoher Last verzögert werden können, besonders zu Beginn einer Stunde. Geplante Läufe funktionieren nur, wenn sich der Workflow auf dem Default Branch befindet.

GitHub-Dokumentation:

- https://docs.github.com/actions/using-workflows/events-that-trigger-workflows#schedule

Zusätzlich kann der Workflow jederzeit manuell gestartet werden, da `workflow_dispatch` konfiguriert ist.

---

## 11. Dashboard-Bedienung

Die Website enthält:

### View

- `Team overall`
- alle aktiven Spielernamen

### Season

- All seasons
- Summer
- Autumn
- Winter
- Spring

Während des offiziellen Eventzeitraums wird die aktuelle Saison standardmäßig ausgewählt.

### Time

- All times
- Morning
- Day
- Night

### Top-25-Tabelle

Je Spot werden angezeigt:

- Rang
- Region und Ortsname
- `location_id`
- Encounter-Methode
- Saison und Tageszeit
- Exklusivitäts-adjustierter Score
- Legacy-Score als Vergleich
- Top Target
- Horde-Wahrscheinlichkeit
- Fallback
- alle Ziele und ihre Detailwerte

---

## 12. Scoring im automatischen Workflow

### Teamzustand

Alle aktiven Zeilen aus `Catches` werden auf Wertungs-Evolutionsfamilien abgebildet.

Für die Teamansicht:

- noch nicht gefangene Familie: Basispunkte + 8 Unique Bonus
- bereits vom Team gefangene Familie: Basispunkte

### Spielerzustand

Für jeden Spieler wird eine eigene Familie-Menge erzeugt.

Standardmäßig werden Spots entfernt, wenn sie irgendeine bereits persönlich gefangene Familie enthalten.

Ist diese Sperre deaktiviert:

- persönlich bereits gefangene Familie: 1 Punkt
- vom Team, aber nicht vom Spieler gefangen: Basispunkte
- komplett neu: Basispunkte + 8

### Exklusivität

```text
Temporal Exclusivity = 12 / verfügbare Saison-Tageszeit-Kombinationen
```

```text
Adjusted Contribution =
Horde-Wahrscheinlichkeit
× Hordengröße
× aktueller Punktewert
× Temporal Exclusivity
```

### Horde-Wahrscheinlichkeiten

Die Horden-Splits werden innerhalb des aktiven Hordenpools normalisiert:

```text
2,5 % / 5 % = 50 % Sweet-Scent-Chance
1,0 % / 5 % = 20 % Sweet-Scent-Chance
```

---

## 13. Täglicher Teamprozess

1. Shiny wird bestätigt.
2. Berechtigter Editor ergänzt im `Catches`-Tab eine Zeile.
3. `Active` bleibt `TRUE`.
4. Innerhalb des nächsten Workflow-Laufs aktualisieren sich:
   - Team Checklist,
   - Player Summary,
   - GitHub-Pages-Dashboard.
5. Der betroffene Spieler öffnet seinen Namen im Dropdown und wechselt zum nächsten erlaubten Top Spot.

Fehleingabe:

1. Zeile nicht zwingend löschen.
2. `Active` auf `FALSE` setzen.
3. Nächsten Lauf abwarten oder Workflow manuell starten.

---

## 14. Wartung

### Spieler hinzufügen

1. Im `Players`-Tab neue Zeile ergänzen.
2. `Active = TRUE`.
3. Nach dem nächsten Lauf erscheint der Spieler im Website-Dropdown.

### Spieler deaktivieren

`Active = FALSE`. Der Spieler verschwindet aus dem Dashboard-Dropdown. Seine bereits eingetragenen Catches bleiben für den Team-Unique-Status erhalten.

### Neue monsters.json

Neue Datei unter folgendem Namen ersetzen:

```text
data/monsters.json
```

Danach committen und pushen. Der Push löst einen Workflow-Lauf aus.

### Neue Tierchart

Datei ersetzen:

```text
data/shiny_wars_2026_tier_chart.csv
```

### Gewichtung ändern

In `config/dashboard_config.json`:

```json
"temporal_exclusivity_weight_power": 1.0
```

- `1.0`: volle aktuelle Gewichtung
- `0.5`: abgeschwächte Gewichtung
- `0.0`: Exklusivitätsfaktor neutralisiert

### Anzahl angezeigter Spots

```json
"top_n": 25
```

---

## 15. Fehlerbehebung

### `GOOGLE_SERVICE_ACCOUNT_JSON is not set`

Secret fehlt oder Name ist falsch geschrieben.

### `GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON`

Nicht nur Dateiname oder Auszug einfügen, sondern den vollständigen Dateiinhalt.

### `The caller does not have permission`

Das Google Sheet wurde nicht als Bearbeiter mit der Service-Account-E-Mail geteilt.

### `Unable to parse range: Players`

Das Tabellenblatt muss exakt `Players` heißen.

### `Unknown or inactive player`

Der Name im `Catches`-Tab stimmt nicht mit einem aktiven Namen im `Players`-Tab überein. Dropdown verwenden.

### `Could not map caught Pokémon/family names`

Pokémonname entspricht keinem Wert aus `Pokemon Lookup`. Schreibweise korrigieren oder Dropdown verwenden.

### Website bleibt alt

1. Letzten Actions-Lauf prüfen.
2. Fehlermeldung öffnen.
3. Falls GitHub-Schedule verzögert war: **Run workflow** manuell starten.
4. Browser hart neu laden.

### Pages zeigt 404

Unter **Settings → Pages** prüfen, ob Source auf **GitHub Actions** steht und der Deploy-Job erfolgreich war.

---

## 16. Datenschutz und Zugriff

- Das Google Sheet bleibt privat.
- Der Service-Account-Schlüssel liegt nur als GitHub Secret vor.
- Der private Schlüssel wird nicht in die Website kopiert.
- GitHub Pages ist in dieser Standardkonfiguration öffentlich.
- Die Website veröffentlicht Spielernamen, Teamstatus und Empfehlungen.
- Catch-Rohzeilen werden nicht direkt auf der Website ausgegeben; aus Rankings und Checklisten können Teamfortschritte jedoch teilweise abgeleitet werden.

Falls die Strategie vollständig privat bleiben muss, sollte statt öffentlichem GitHub Pages ein Hosting mit echter Authentifizierung verwendet werden.
