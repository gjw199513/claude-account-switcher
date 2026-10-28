[English](../README.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md) · [Français](README.fr.md) · Deutsch

# Claude-Konto wechseln

Eine kleine inoffizielle macOS-App zum Wechseln zwischen Claude-Desktop-Konten, während lokale Code-Sitzungen sichtbar bleiben. Jedes Konto wird getrennt angemeldet; gleichzeitig läuft nur ein Claude-Fenster.

**Prüfstand der Nutzungsanzeige:** Synthetische verschlüsselte Daten und simulierte Antworten wurden getestet. Schlüsselbundzugriff und Online-Abruf mit echten Konten sind noch nicht geprüft.

## Installation

Benötigt werden macOS, Claude Desktop in `/Applications`, Xcode Command Line Tools und `/usr/bin/python3` ab Version 3.9.

```sh
git clone https://github.com/gjw199513/claude-account-switcher.git
cd claude-account-switcher
./install.sh
```

Öffne **Claude Account Switcher** aus `~/Applications`. Die Oberfläche folgt der Systemsprache und unterstützt Englisch, vereinfachtes Chinesisch, Japanisch, Koreanisch, Spanisch, Französisch und Deutsch.

Im Menü oben rechts lässt sich eine Sprache wählen oder die Systemsprache verwenden. Für die Nutzung ein Konto auswählen und **Aktualisieren** klicken. Der erste Zugriff wird erklärt; macOS kann Zugriff auf Claude Safe Storage im Schlüsselbund verlangen. Die vorhandene Claude-Desktop-Anmeldung wird verwendet, ohne erneute Anmeldung oder Modellnachricht. Das Zugriffstoken wird kurz im Speicher entschlüsselt und nur per HTTPS an `api.anthropic.com` gesendet; es wird nicht gespeichert, protokolliert oder erneuert. Nach dem ersten erfolgreichen Abruf wird während der macOS-Sitzung etwa alle 15 Minuten aktualisiert; manuell frühestens alle fünf Minuten. Werte über 30 Minuten oder nach dem Rücksetzen werden ausgeblendet. Eine inaktive Anmeldung kann ablaufen, bis das Konto in Claude geöffnet wird. Das Speicherformat und die API sind nicht öffentlich und können sich ändern oder Abfragen begrenzen.

## Verwendung

1. Das aktuelle Claude-Profil ist **Konto A**. Klicke auf **Konto hinzufügen**, bestätige den Wechsel, melde dich im neuen Claude-Fenster an und öffne **Code**.
2. Beende Claude nach der ersten Anmeldung mit `⌘Q`, wähle das Konto und klicke erneut auf **Wechseln**, damit die gemeinsame Sitzungsliste geladen wird.
3. Danach genügt es, ein Konto auszuwählen und auf **Wechseln** zu klicken. Claude wird regulär beendet, der lokale Index automatisch abgeglichen und das gewählte Konto geöffnet. Schließe laufende Arbeiten vorher ab oder speichere sie.

Weitere Konten werden genauso hinzugefügt. Läuft eine Anmeldung ab, kann eine erneute Anmeldung nötig sein.

## Funktionsweise und Grenzen

- Jedes Konto verwendet einen eigenen Claude-Datenordner. Beim Wechsel werden Anmeldedaten weder verschoben noch ersetzt; der Nutzungsabruf verwendet das Desktop-Token wie oben beschrieben. Ein automatischer Wechsel nach Kontingent erfolgt nicht.
- Lokale Code-Verläufe teilen sich `~/.claude/projects`. Ein Hintergrunddienst und der Kontowechsel gleichen die kontoabhängigen Seitenleistenindizes ab. Zum erneuten Laden kann ein Claude-Neustart nötig sein.
- Cloud-Chats, Cowork, Kontingente, kontospezifische Konnektoren und Desktop-spezifische Einstellungen bleiben getrennt.
- SSH-, WSL-, benutzerdefinierte Worktree- und andere besondere oder unbekannte Sitzungen können übersprungen werden. Vorhandene temporäre Arbeitsbereiche behalten ihren ursprünglichen Pfad; das Löschen des zugehörigen Profilordners kann sie unbrauchbar machen. Bei mehreren Organisationsordnern wird die Synchronisierung vorsichtshalber angehalten.
- Konflikte und fehlerhafte Einträge bleiben erhalten; vor dem Überschreiben werden Indizes gesichert. Löschungen werden nicht übertragen. Das interne Speicherformat von Claude Desktop ist nicht dokumentiert und kann sich nach Updates ändern.

**Validierung:** Auf dem aktuellen Mac wurde bestätigt, dass Konto B die lokale Code-Seitenleiste von A anzeigt. Der Abgleich mehrerer Konten und Schutzmechanismen wurden mit Testdaten geprüft; das Fortsetzen realer Gespräche und andere Claude-Versionen sind noch nicht vollständig validiert.

## Optional: lokale geplante Vorbereitung

Installiere [Claude Code CLI](https://code.claude.com/docs/en/setup) ab Version 2.1.268. Wähle ein Konto, öffne die Vorbereitungseinstellungen, melde dich im offiziellen CLI an und bestätige nach dem Aktualisieren die angezeigte E-Mail-Adresse. Danach kannst du die tägliche Uhrzeit aktivieren. Jedes Konto hat eine isolierte CLI-Konfiguration; die App liest keine Zugangsdaten.

Bei angemeldeter macOS-Sitzung sendet ein Hintergrunddienst zur gewählten Zeit eine kurze Haiku-Anfrage, auch bei geschlossenem Fenster. War der Mac aus oder im Ruhezustand, fragt die App beim späteren Öffnen am selben Tag vor dem Nachholen. Fehlgeschlagene Anfragen werden am selben Tag nicht automatisch wiederholt. Die Anfrage verbraucht Kontingent und kann Zusatzkosten verursachen; ein neues Fünf-Stunden-Fenster ist nicht garantiert.

## Deinstallation

Führe `./uninstall.sh` aus. Claude-Profile, Unterhaltungen und lokale Sicherungen bleiben erhalten.

## Lizenz

[MIT](../LICENSE). Dieses unabhängige Projekt ist nicht mit Anthropic verbunden oder von Anthropic unterstützt.
