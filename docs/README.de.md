[English](../README.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md) · [Français](README.fr.md) · Deutsch

# Claude-Konto wechseln

Eine kleine inoffizielle macOS-App zum Wechseln zwischen Claude-Desktop-Konten, während lokale Code-Sitzungen sichtbar bleiben. Jedes Konto wird getrennt angemeldet; gleichzeitig läuft nur ein Claude-Fenster.

## Installation

Benötigt werden macOS, Claude Desktop in `/Applications`, Xcode Command Line Tools und `/usr/bin/python3` ab Version 3.9.

```sh
git clone https://github.com/gjw199513/claude-account-switcher.git
cd claude-account-switcher
./install.sh
```

Öffne **Claude Account Switcher** aus `~/Applications`. Die Oberfläche folgt der Systemsprache und unterstützt Englisch, vereinfachtes Chinesisch, Japanisch, Koreanisch, Spanisch, Französisch und Deutsch.

Im Menü oben rechts lässt sich eine Sprache wählen oder die Systemsprache verwenden. Die beiden Balken zeigen den von Claude Desktop oder dem CLI-Ereignis bei der Vorbereitung gespeicherten Fünf-Stunden- und Wochenverbrauch; es sind weder Livewerte noch Tokenzahlen. Der Zeitpunkt wird angezeigt; Cachewerte, die älter als 30 Minuten sind, werden ausgeblendet. Fehlen Daten oder ist ihre Zuordnung unklar, bleiben die Werte leer.

## Verwendung

1. Das aktuelle Claude-Profil ist **Konto A**. Klicke auf **Konto hinzufügen**, bestätige den Wechsel, melde dich im neuen Claude-Fenster an und öffne **Code**.
2. Beende Claude nach der ersten Anmeldung mit `⌘Q`, wähle das Konto und klicke erneut auf **Wechseln**, damit die gemeinsame Sitzungsliste geladen wird.
3. Danach genügt es, ein Konto auszuwählen und auf **Wechseln** zu klicken. Claude wird regulär beendet, der lokale Index automatisch abgeglichen und das gewählte Konto geöffnet. Schließe laufende Arbeiten vorher ab oder speichere sie.

Weitere Konten werden genauso hinzugefügt. Läuft eine Anmeldung ab, kann eine erneute Anmeldung nötig sein.

## Funktionsweise und Grenzen

- Jedes Konto verwendet einen eigenen Claude-Datenordner. Claude übernimmt die Anmeldung; das Tool exportiert oder kopiert keine Anmeldedaten. Es nutzt keinen Proxy und wechselt nicht automatisch nach Kontingent.
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
