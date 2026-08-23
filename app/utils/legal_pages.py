"""Rechtliche Texte (Datenschutz & Impressum) aus SystemSettings."""

from app import db
from app.models.settings import SystemSettings

SETTING_PRIVACY = 'legal_privacy'
SETTING_IMPRINT = 'legal_imprint'
SETTING_TERMS = 'legal_terms'

PAGE_KEYS = {
    'privacy': SETTING_PRIVACY,
    'imprint': SETTING_IMPRINT,
    'terms': SETTING_TERMS,
    'nutzungsbedingungen': SETTING_TERMS,
}

DEFAULT_PRIVACY = """Datenschutzerklärung

Stand: [Datum einfügen]

1. Verantwortlicher
Verantwortlich für die Datenverarbeitung auf diesem Portal ist:

[Name der Organisation / Betreiber]
[Straße und Hausnummer]
[PLZ Ort]
[Land]
E-Mail: [E-Mail-Adresse]
Telefon: [Telefonnummer]

2. Zweck der Verarbeitung
Dieses Portal dient der internen Zusammenarbeit, Kommunikation und Organisation.
Personenbezogene Daten werden verarbeitet, soweit dies für den Betrieb des Portals,
die Nutzerverwaltung, die Anmeldung sowie die von Ihnen genutzten Module erforderlich ist.

3. Verarbeitete Daten
Je nach Nutzung können insbesondere folgende Daten verarbeitet werden:
- Stammdaten (z. B. Name, E-Mail-Adresse)
- Zugangs- und Authentifizierungsdaten
- Nutzungs- und Protokolldaten (z. B. Login-Zeitpunkte, technische Logs)
- Inhalte, die Sie im Portal speichern oder versenden (z. B. Dateien, Nachrichten)

4. Rechtsgrundlagen
Die Verarbeitung erfolgt je nach Kontext auf Grundlage von Art. 6 Abs. 1 lit. b DSGVO
(Vertragserfüllung / vorvertragliche Maßnahmen), Art. 6 Abs. 1 lit. f DSGVO
(berechtigtes Interesse am sicheren Betrieb) und – soweit erforderlich –
Art. 6 Abs. 1 lit. a DSGVO (Einwilligung).

5. Speicherdauer
Personenbezogene Daten werden nur so lange gespeichert, wie es für die genannten Zwecke
erforderlich ist oder gesetzliche Aufbewahrungspflichten bestehen.

6. Empfänger / Auftragsverarbeitung
Eine Weitergabe an Dritte erfolgt nur, wenn dies für den Betrieb technisch notwendig ist,
eine gesetzliche Pflicht besteht oder Sie eingewilligt haben.
Soweit Dienstleister eingesetzt werden, erfolgt dies im Rahmen von Auftragsverarbeitung.

7. Cookies und lokale Speicherung
Für Anmeldung, Sicherheit und grundlegende Funktionen werden notwendige Cookies
bzw. vergleichbare Speichermechanismen eingesetzt. Optionale Funktionen können
zusätzliche lokale Einstellungen speichern.

8. Ihre Rechte
Sie haben nach Maßgabe der DSGVO insbesondere folgende Rechte:
Auskunft, Berichtigung, Löschung, Einschränkung der Verarbeitung, Datenübertragbarkeit
sowie Widerspruch gegen Verarbeitungen auf Basis berechtigter Interessen.
Sofern eine Verarbeitung auf Einwilligung beruht, können Sie diese jederzeit widerrufen.

9. Beschwerderecht
Sie können sich bei einer Datenschutzaufsichtsbehörde beschweren.

10. Hinweis
Dieser Text ist eine generische Vorlage und ersetzt keine individuelle Rechtsberatung.
Bitte passen Sie die Angaben an Ihre Organisation und Ihren tatsächlichen Betrieb an."""

DEFAULT_IMPRINT = """Impressum

Angaben gemäß § 5 TMG

[Name der Organisation / Betreiber]
[Rechtsform, falls zutreffend]
[Straße und Hausnummer]
[PLZ Ort]
[Land]

Vertreten durch:
[Name der vertretungsberechtigten Person(en)]

Kontakt
Telefon: [Telefonnummer]
E-Mail: [E-Mail-Adresse]
Website: [Website, falls vorhanden]

Registereintrag (falls zutreffend)
Registergericht: [Gericht]
Registernummer: [Nummer]

Umsatzsteuer-ID (falls zutreffend)
Umsatzsteuer-Identifikationsnummer gemäß § 27a UStG: [USt-IdNr.]

Verantwortlich für den Inhalt nach § 18 Abs. 2 MStV
[Name]
[Adresse]

Haftungsausschluss
Trotz sorgfältiger inhaltlicher Kontrolle übernehmen wir keine Haftung für die Inhalte
externer Links. Für den Inhalt der verlinkten Seiten sind ausschließlich deren Betreiber verantwortlich.

Urheberrecht
Die auf diesem Portal erstellten Inhalte und Werke unterliegen dem deutschen Urheberrecht.
Vervielfältigung, Bearbeitung und Verbreitung bedürfen der schriftlichen Zustimmung
des jeweiligen Rechteinhabers, soweit nicht gesetzliche Ausnahmen greifen.

Hinweis
Dieser Text ist eine generische Vorlage und ersetzt keine individuelle Rechtsberatung.
Bitte ersetzen Sie die Platzhalter durch die korrekten Angaben Ihrer Organisation."""

DEFAULT_TERMS = """Nutzungsbedingungen

Stand: [Datum einfügen]

1. Geltungsbereich und Vertragsgegenstand
Diese Nutzungsbedingungen gelten für die Nutzung des Portals [Name der Organisation / Betreiber] (nachfolgend „Portal“).
Das Portal stellt Funktionen für Organisation, Kommunikation, Datenverwaltung und Zusammenarbeit zur Verfügung.
Mit der Registrierung oder Nutzung des Portals erklären Sie sich mit diesen Nutzungsbedingungen einverstanden.

2. Registrierung und Benutzerkonto
2.1 Für die Nutzung des Portals ist ein Benutzerkonto erforderlich.
2.2 Der Nutzer ist verpflichtet, bei der Registrierung wahrheitsgemäße Angaben zu machen.
2.3 Die Zugangsdaten (insbesondere das Passwort) sind vertraulich zu behandeln und vor dem Zugriff Dritter zu schützen. Bei Verdacht auf Missbrauch ist der Betreiber unverzüglich zu informieren.
2.4 Ein Anspruch auf Registrierung oder Nutzung des Portals besteht nicht.

3. Nutzungsrechte und Pflichten der Nutzer
3.1 Dem Nutzer wird das einfache, nicht übertragbare Recht eingeräumt, das Portal im Rahmen der vorgesehenen Zwecke zu nutzen.
3.2 Der Nutzer verpflichtet sich, keine Inhalte zu übermitteln oder zu speichern, die gegen geltendes Recht, gute Sitten oder Rechte Dritter verstoßen.
3.3 Untersagt sind insbesondere:
- Die Verbreitung rechtswidriger, beleidigender oder schädlicher Inhalte.
- Versuche, die Sicherheit, Integrität oder Verfügbarkeit des Portals zu beeinträchtigen.
- Die unbefugte Weitergabe von Zugangsdaten an Dritte.

4. Verfügbarkeit und Änderungen
4.1 Der Betreiber bemüht sich um eine dauerhafte Bereitstellung des Portals, übernimmt jedoch keine Garantie für eine unterbrechungsfreie Verfügbarkeit.
4.2 Wartungsarbeiten, Sicherheitsupdates oder technische Störungen können zu vorübergehenden Einschränkungen führen.
4.3 Der Betreiber behält sich vor, Funktionen des Portals jederzeit anzupassen oder weiterzuentwickeln.

5. Haftung
5.1 Der Betreiber haftet für Vorsatz und grobe Fahrlässigkeit nach den gesetzlichen Bestimmungen.
5.2 Für leicht fahrlässige Pflichtverletzungen haftet der Betreiber nur bei Verletzung wesentlicher Vertragspflichten (Kardinalpflichten).
5.3 Für vom Nutzer eingestellte Inhalte übernimmt der Betreiber keine Haftung.

6. Beendigung der Nutzung
6.1 Der Nutzer kann die Nutzung des Portals jederzeit beenden.
6.2 Der Betreiber ist berechtigt, das Benutzerkonto bei Verstößen gegen diese Nutzungsbedingungen vorübergehend oder dauerhaft zu sperren.

7. Schlussbestimmungen
7.1 Es gilt das Recht der Bundesrepublik Deutschland.
7.2 Sollten einzelne Bestimmungen dieser Nutzungsbedingungen unwirksam sein, bleibt die Wirksamkeit der übrigen Bestimmungen unberührt.
7.3 Gerichtsstand ist [Ort / Gerichtsstand, falls zutreffend].

Hinweis:
Dieser Text ist eine generische Vorlage und ersetzt keine individuelle Rechtsberatung.
Bitte passen Sie die Angaben an Ihre Organisation und Ihren tatsächlichen Betrieb an."""


def _default_for_key(setting_key: str) -> str:
    if setting_key == SETTING_PRIVACY:
        return DEFAULT_PRIVACY
    if setting_key == SETTING_IMPRINT:
        return DEFAULT_IMPRINT
    if setting_key == SETTING_TERMS:
        return DEFAULT_TERMS
    return ''


def get_legal_content(page: str) -> str:
    """Lädt den Text für privacy/imprint/terms; Fallback auf generische Vorlage."""
    setting_key = PAGE_KEYS.get(page)
    if not setting_key:
        return ''
    row = SystemSettings.query.filter_by(key=setting_key).first()
    if row and row.value and row.value.strip():
        return row.value
    return _default_for_key(setting_key)


def set_legal_content(page: str, value: str) -> None:
    """Speichert den Text für privacy/imprint/terms in SystemSettings."""
    setting_key = PAGE_KEYS.get(page)
    if not setting_key:
        raise ValueError(f'Unknown legal page: {page}')

    text = (value or '').strip() or _default_for_key(setting_key)
    if setting_key == SETTING_PRIVACY:
        description = 'Datenschutzerklärung (öffentliche Seite)'
    elif setting_key == SETTING_IMPRINT:
        description = 'Impressum (öffentliche Seite)'
    else:
        description = 'Nutzungsbedingungen (öffentliche Seite)'

    row = SystemSettings.query.filter_by(key=setting_key).first()
    if row:
        row.value = text
        if not row.description:
            row.description = description
    else:
        db.session.add(SystemSettings(key=setting_key, value=text, description=description))
