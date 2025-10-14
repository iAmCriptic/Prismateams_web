Anforderungskatalog: Team-Portal
Dieses Dokument beschreibt die Anforderungen an die Entwicklung eines webbasierten Team-Portals. Es dient als technische und funktionale Grundlage für die Konzeption, Umsetzung und spätere Wartung der Anwendung.

1. Allgemeine Anforderungen (System- & Architekturanforderungen)
Diese Anforderungen definieren die technologische Basis und die grundlegenden Prinzipien der Anwendung.

ID

Anforderung

Beschreibung

Priorität

1.1

Technologie-Stack

Das Backend muss auf dem Python-Framework Flask basieren. Das Frontend muss mit Bootstrap 5 gestaltet werden, um ein modernes und responsives Design zu gewährleisten.

Muss

1.2

Datenbank

Als Datenbankmanagementsystem ist eine relationale Datenbank wie MariaDB oder MySQL zu verwenden.

Muss

1.3

Server-Umgebung

Die Anwendung muss für den Betrieb auf einem Ubuntu Server optimiert sein. Alle Abhängigkeiten und Konfigurationen sind darauf auszulegen.

Muss

1.4

Architektur

Die Anwendung soll modular aufgebaut sein. Einzelne Funktionalitäten (z.B. Chat, Kalender, Dateiverwaltung) sind in separaten Modulen (Blueprints in Flask) zu kapseln.

Muss

1.5

API-Schnittstelle

Das Backend muss eine RESTful-API bereitstellen. Alle Kernfunktionen sollen über definierte API-Endpunkte zugänglich sein, um eine zukünftige Anbindung einer mobilen App zu ermöglichen.

Muss

1.6

Design-Ansatz

Das Design muss dem "Mobile-First"-Prinzip folgen. Die Darstellung und Bedienbarkeit auf mobilen Endgeräten hat höchste Priorität.

Muss

1.7

Zugriff und Startpunkt

Die Webseite ist ein internes Werkzeug und nicht öffentlich zugänglich. Es wird keine Landing-Page benötigt. Benutzer werden beim Aufruf direkt zur Anmeldeseite geleitet.

Muss

2. Funktionale Anforderungen (Features & Module)
2.1 Benutzerverwaltung (Registrierung & Anmeldung)
ID

Anforderung

Beschreibung

Priorität

2.1.1

Registrierung

- Abfrage von: Vorname, Nachname, E-Mail-Adresse, Telefonnummer, Passwort. - Nach der Registrierung wird das Benutzerkonto als "inaktiv" markiert.

Muss

2.1.2

Admin-Bestätigung

Ein Administrator muss neue Registrierungen manuell in der Administrationsoberfläche freischalten. Der Benutzer erhält nach Freischaltung eine Benachrichtigung.

Muss

2.1.3

Anmeldung

- Anmeldung erfolgt über E-Mail und Passwort. - Eine "Angemeldet bleiben"-Funktion (via persistentem Cookie) muss implementiert werden, um den Benutzer direkt zum Dashboard zu leiten.

Muss

2.1.4

Benutzerrollen

Es gibt mindestens zwei Rollen: Benutzer und Administrator mit unterschiedlichen Berechtigungen.

Muss

2.2 Dashboard
ID

Anforderung

Beschreibung

Priorität

2.2.1

Responsives Layout

- Mobil: App-ähnliches Layout mit einer festen Navigationsleiste am unteren Bildschirmrand. - Desktop: Klassisches Webseiten-Layout mit seitlicher oder oberer Navigation.

Muss

2.2.2

Navigationselemente

Die Hauptnavigation enthält die Punkte: Dashboard, Chats, Dateien, Termine, Mehr. Der "Mehr"-Bereich fasst alle weiteren Module zusammen.

Muss

2.2.3

Widget-Übersicht

Das Dashboard zeigt eine Zusammenfassung der wichtigsten Informationen in Form von interaktiven Widgets: - Anstehende Termine (die nächsten 3) - Letzte ungelesene Chat-Nachrichten - Neueste E-Mails Ein Klick auf ein Widget führt zur jeweiligen Detailseite.

Muss

2.3 Chats
ID

Anforderung

Beschreibung

Priorität

2.3.1

Kommunikationsmedien

Der Versand von Textnachrichten, Bildern, kurzen Videos und Sprachnachrichten muss möglich sein.

Muss

2.3.2

Haupt-Chat

Es muss einen vordefinierten Chat geben, in dem alle Teammitglieder automatisch Mitglied sind.

Muss

2.3.3

Unter-Chats

Benutzer müssen eigene Gruppen-Chats ("Unter-Chats") zu bestimmten Themen erstellen und andere Mitglieder einladen können.

Muss

2.3.4

Direktnachrichten

Die Möglichkeit, 1-zu-1-Gespräche mit einzelnen Teammitgliedern zu führen, muss gegeben sein.

Muss

2.3.5

Benachrichtigungen

Bei neuen Nachrichten sollte eine (optische) Benachrichtigung in der Navigation erscheinen.

Soll

2.4 Dateiverwaltung (Gemeinsamer Cloud-Speicher)
ID

Anforderung

Beschreibung

Priorität

2.4.1

Globaler Zugriff

Alle Dateien und Ordner sind für alle angemeldeten Benutzer sichtbar und zugänglich. Es gibt keine privaten Bereiche.

Muss

2.4.2

Ordnerstruktur

Benutzer müssen Ordner erstellen, umbenennen und löschen können.

Muss

2.4.3

Datei-Upload

Benutzer können beliebige Dateien hochladen.

Muss

2.4.4

Konfliktbehandlung

Beim Upload einer Datei mit einem bereits existierenden Namen wird der Benutzer gefragt, ob die bestehende Datei überschrieben werden soll.

Muss

2.4.5

Versionierung

- Zu jeder Datei werden die letzten 3 Versionen gespeichert. - Der Versionsverlauf muss einsehbar sein, und frühere Versionen müssen heruntergeladen werden können.

Muss

2.4.6

Metadaten

Zu jeder Datei werden folgende Informationen gespeichert und angezeigt: Ersteller/Uploader, Upload-Datum, Datum der letzten Änderung.

Muss

2.4.7

Online-Editor

Einfache Textdateien (z.B. .txt, .md) sollen direkt im Browser bearbeitet und gespeichert werden können.

Soll

2.5 Kalender (Geteilte Termine)
ID

Anforderung

Beschreibung

Priorität

2.5.1

Terminerstellung

Jeder Benutzer kann neue Termine für das gesamte Team erstellen. Ein Termin besteht aus Titel, Beschreibung, Datum und Uhrzeit (Start/Ende).

Muss

2.5.2

Teilnahmestatus

Jeder Benutzer kann bei einem Termin seine Teilnahme bestätigen ("Nehme teil") oder absagen ("Nehme nicht teil").

Muss

2.5.3

Bearbeitung

Jeder Benutzer kann bestehende Termine bearbeiten (Titel, Beschreibung, Zeit ändern).

Muss

2.5.4

Löschen (Admin)

Nur Administratoren können Termine endgültig löschen.

Muss

2.5.5

Admin-Verwaltung

Ein Admin kann Benutzer aus der Teilnehmerliste eines Termins entfernen. Ein so entfernter Benutzer kann diesem spezifischen Termin nicht erneut beitreten.

Muss

2.6 Zentraler E-Mail-Client
ID

Anforderung

Beschreibung

Priorität

2.6.1

Kontointegration

Die Zugangsdaten (IMAP/SMTP) für eine zentrale E-Mail-Adresse werden im Backend sicher hinterlegt.

Muss

2.6.2

Posteingang

Alle Benutzer mit entsprechender Berechtigung sehen den gemeinsamen Posteingang dieser zentralen Adresse.

Muss

2.6.3

E-Mails senden

Ein integrierter Editor ermöglicht das Verfassen und Senden von E-Mails über das zentrale Konto.

Muss

2.6.4

Dynamischer Footer

Der Admin kann einen globalen E-Mail-Footer (Text und optional ein Bild) definieren. Beim Senden wird automatisch der Name des sendenden Benutzers hinzugefügt (z.B. "Gesendet von Max Mustermann").

Muss

2.7 Zugangsdaten-Verwaltung
ID

Anforderung

Beschreibung

Priorität

2.7.1

Zentrale Speicherung

Ein Bereich zur Speicherung von Zugangsdaten. Alle Einträge sind für alle Benutzer sichtbar und bearbeitbar.

Muss

2.7.2

Datenfelder

Ein Eintrag besteht aus: Webseite (URL), Benutzername, Passwort, Vermerk.

Muss

2.7.3

Favicon-Anzeige

Neben jedem Eintrag soll automatisch das Favicon der angegebenen Webseite angezeigt werden, um die Übersichtlichkeit zu erhöhen.

Soll

2.8 Bedienungsanleitungen
ID

Anforderung

Beschreibung

Priorität

2.8.1

Admin-Upload

Nur Administratoren können PDF-Dateien in diesem Bereich hochladen.

Muss

2.8.2

Benutzerzugriff

Alle Benutzer können die hochgeladenen PDFs in einer Liste sehen, direkt im Browser ansehen und herunterladen. Ein Bearbeiten oder Löschen ist für Benutzer nicht möglich.

Muss

2.9 Canvas (Kreativbereich)
ID

Anforderung

Beschreibung

Priorität

2.9.1

Canvas-Verwaltung

Benutzer können eine Liste von "Canvases" einsehen, neue erstellen oder bestehende auswählen.

Muss

2.9.2

Dynamische Textfelder

Innerhalb eines Canvas kann ein Benutzer an eine beliebige Stelle klicken. An dieser Position wird ein neues Textfeld erstellt, in das geschrieben werden kann.

Muss

2.9.3

Bearbeitung

Bestehende Textfelder können verschoben, in der Größe geändert und gelöscht werden.

Muss

2.10 Einstellungen
ID

Anforderung

Beschreibung

Priorität

2.10.1

Benutzereinstellungen

Jeder Benutzer kann seine eigenen Daten ändern: - Vorname, Nachname, E-Mail, Passwort - Profilbild hochladen - Persönliche Akzentfarbe für das UI festlegen - Zwischen Light- und Dark-Mode wechseln

Muss

2.10.2

Admin-Einstellungen

Ein separater Admin-Bereich mit folgenden Funktionen: - Benutzerverwaltung: Registrierungen bestätigen/ablehnen, Benutzer bearbeiten/löschen. - Kalenderverwaltung: Wie in 2.5.5 beschrieben. - E-Mail-Verwaltung: Globalen Footer festlegen, einzelnen Benutzern die Berechtigung zum Lesen/Senden von E-Mails entziehen oder erteilen. - System-Einstellungen: Z.B. den Namen des Portals oder das Logo ändern.

Muss

3. Nicht-funktionale Anforderungen
ID

Anforderung

Beschreibung

Priorität

3.1

Performance

Die Ladezeiten der Seiten sollten auch bei mobiler Verbindung kurz sein. API-Antworten sollten im Normalfall unter 500ms liegen.

Muss

3.2

Sicherheit

- Passwörter müssen sicher gehasht (z.B. mit Argon2, Scrypt) gespeichert werden. - Alle Eingaben sind gegen XSS- und SQL-Injection-Angriffe zu schützen. - Der Zugriff auf Module muss serverseitig anhand der Benutzerrolle validiert werden.

Muss

3.3

Benutzerfreundlichkeit

Die Oberfläche muss intuitiv und selbsterklärend sein. Wichtige Funktionen müssen mit maximal 3 Klicks erreichbar sein.

Muss

3.4

Wartbarkeit

Der Code muss gut dokumentiert und sauber strukturiert sein, um zukünftige Erweiterungen zu erleichtern.

Muss
