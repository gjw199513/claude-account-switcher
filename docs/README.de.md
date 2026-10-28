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

Im Menü oben rechts lässt sich eine Sprache wählen oder die Systemsprache verwenden. Die beiden Balken zeigen den von Claude gespeicherten Fünf-Stunden- und Wochenverbrauch des ausgewählten Kontos; es sind weder Livewerte noch Tokenzahlen. Zeitpunkt und veralteter Cache werden gekennzeichnet. Fehlen Daten oder ist ihre Zuordnung unklar, bleiben die Werte leer.

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

## Optional: offizielle geplante Aufgabe

Diese App automatisiert kein Aufwärmen. Für jedes bezahlte Claude-Konto kann eine [offizielle geplante Cowork-Aufgabe](https://support.claude.com/en/articles/13854387-schedule-recurring-tasks-in-claude-cowork) mit einem kurzen Auftrag und Zeitplan eingerichtet werden; Haiku kann gewählt werden, falls verfügbar. Cloud-Aufgaben laufen auch bei geschlossener App. Sie verbrauchen Kontingent und können zusätzliche Nutzungskosten verursachen. Es ist nicht garantiert, dass eine kurze Anfrage ein neues Fünf-Stunden-Fenster startet.

## Deinstallation

Führe `./uninstall.sh` aus. Claude-Profile, Unterhaltungen und lokale Sicherungen bleiben erhalten.

## Lizenz

[MIT](../LICENSE). Dieses unabhängige Projekt ist nicht mit Anthropic verbunden oder von Anthropic unterstützt.
