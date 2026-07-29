<div align="center">

  <!-- Falls ein Logo im Repo vorhanden ist, kann der Pfad hier angepasst werden -->
  <img src="static/img/logo.png" alt="Prismateams Logo" width="120" height="120">

  # 🛡️ Prismateams Security Policy

  **Sicherheitsrichtlinien & Informationen zur Offenlegung von Schwachstellen**

  [![Supported Version](https://img.shields.io/badge/Supported%20Branch-main-brightgreen.svg?style=for-the-badge&logo=github)](https://github.com/iAmCriptic/Prismateams_web)
  [![Security Status](https://img.shields.io/badge/Security-Active-blue.svg?style=for-the-badge&logo=shield)](https://github.com/iAmCriptic/Prismateams_web)

---

</div>

## 📌 Unterstützte Versionen

Wir legen großen Wert auf die Sicherheit von **Prismateams**. Um den besten Schutz zu gewährleisten, wird ausschließlich der neueste Stand des `main`-Branches aktiv gepflegt und mit Sicherheitsupdates versorgt. 

> ⚠️ **Wichtig:** Ältere Commits, abgezweigte Branches, Tags oder vorherige Releases werden **nicht** mehr für Sicherheitsupdates unterstützt.

| Branch / Version | Unterstützt | Anmerkung |
| :--- | :---: | :--- |
| 🟢 **`main` Branch** (aktueller Stand) | ✅ | Erhält aktiv alle Sicherheitsupdates & Fixes |
| 🔴 Ältere Commits / Branches / Tags | ❌ | Nicht mehr unterstützt – Bitte auf `main` aktualisieren |

> 💡 **Empfehlung für Produktionsumgebungen:**  
> Bitte stellen Sie sicher, dass Ihre Instanz regelmäßig auf den neuesten Stand des `main`-Branches aktualisiert wird.

---

## 🚨 Meldung von Sicherheitslücken

Wenn Sie eine Sicherheitslücke oder eine Schwachstelle in Prismateams entdeckt haben, bitten wir Sie, diese **verantwortungsvoll** zu melden.

Da es sich bei Prismateams derzeit um ein **Freizeit- & Schulprojekt** handelt, stehen aktuell nur die folgenden offiziellen Kanäle zur Verfügung:

1. **🐛 GitHub Issues:** Erstellen Sie ein neues Issue und versehen Sie es mit den Labels `security` oder `vulnerability`.
2. **💬 GitHub Discussions:** Erwähnen Sie die Sicherheitslücke bzw. Bedenken in den Repository-Diskussionen.

---

### 📋 Was sollte Ihre Meldung enthalten?

Damit wir die Schwachstelle so schnell wie möglich analysieren und beheben können, fügen Sie Ihrer Meldung bitte folgende Details hinzu:

* 📝 **Beschreibung:** Eine klare und verständliche Erläuterung der Lücke.
* ⚠️ **Schweregrad:** Ihre eigene Einschätzung (`Niedrig` | `Mittel` | `Hoch` | `Kritisch`).
* 🔄 **Schritte zur Reproduktion:** Detaillierte Schritt-für-Schritt-Anleitung oder PoC (Proof of Concept).
* 🏷️ **Betroffener Stand:** Welches Commit / welches Skript im `main`-Branch ist betroffen?
* 💥 **Mögliche Auswirkungen:** Welche Risiken entstehen dadurch (z. B. Datenverlust, Unauthorized Access)?

---

## 🔒 Implemented Security Measures

Prismateams setzt verschiedene Best Practices und Sicherheitsmechanismen ein, um die Anwendung gegen Angriffe zu schützen:

### 🔑 Authentifizierung & Autorisierung
* **Passwort-Hashing:** Einsatz von **Argon2** für eine extrem sichere Passwort-Speicherung.
* **Rollenbasierte Zugriffskontrolle (RBAC):** Strikte Trennung zwischen User- und Admin-Rollen mit granularer Rechtevergabe.
* **Session-Sicherheit:** Sichere Cookie-Einstellungen (z. B. `HttpOnly`, `SameSite`) für den Produktionsbetrieb.

### 🔐 Datenverschlüsselung
* **Symmetrische Verschlüsselung:** Verwendung von **Fernet** zur sicheren Speicherung von sensitiven Zugangsdaten.
* **HTTPS / TLS:** Dringend empfohlen und unterstützt über SSL/TLS-Zertifikate.

### 🛡️ Schutz vor gängigen Web-Angriffen
* **CSRF-Schutz:** Integration von **Flask-WTF** zur Verhinderung von Cross-Site Request Forgery.
* **XSS-Schutz:** **Jinja2 Auto-Escaping** schützt vor Cross-Site-Scripting.
* **SQL-Injection-Schutz:** **SQLAlchemy ORM** verhindert direkte SQL-Injections durch parametrisierte Queries.
* **Rate Limiting:** Schutz kritischer API-Endpunkte via **Flask-Limiter**.

---

## 🛠️ Best Practices für Administratoren

Wenn Sie Prismateams in einer produktiven Umgebung betreiben, befolgen Sie bitte diese Empfehlungen:

- [ ] 🔄 **Aktualisierungen:** Halten Sie die Anwendung immer synchron mit dem `main`-Branch.
- [ ] 🔑 **Starker `SECRET_KEY`:** Generieren Sie einen sicheren Schlüssel (z. B. via `openssl rand -hex 32`).
- [ ] 🌐 **HTTPS aktivieren:** Verwenden Sie SSL/TLS-Zertifikate (z. B. kostenfrei über [Let's Encrypt](https://letsencrypt.org/)).
- [ ] 🔒 **Sichere Passwörter:** Nutzen Sie starke, einzigartige Passwörter für Datenbank- und Mail-Zugänge.
- [ ] 🧱 **Firewall:** Beschränken Sie den Zugriff auf notwendige Ports (z. B. Port 80/443).
- [ ] 💾 **Regelmäßige Backups:** Sichern Sie in festen Intervallen die Datenbank sowie hochgeladene Dateien.
- [ ] ⚙️ **System-Updates:** Halten Sie das zugrundeliegende Betriebssystem und Python-Dependencies aktuell.
- [ ] 📄 **OnlyOffice JWT:** Aktivieren Sie für die Produktion zwingend die JWT-Authentifizierung.
- [ ] 📁 **Dateiberechtigungen:** Achten Sie auf korrekte Berechtigungen in den Upload-Verzeichnissen.

---

## 🐛 Bekannte Sicherheitslücken

* **Aktueller Status:** 🟢 *Derzeit sind keine offenen Sicherheitslücken bekannt.*

---

## 🔄 Sicherheits-Updates

Sicherheitsrelevante Patches werden direkt in den `main`-Branch eingepflegt. Wir empfehlen Administratoren:
1. Den `main`-Branch regelmäßig auf neue Commits zu prüfen.
2. Die Release-Notes / Commit-Nachrichten zu lesen.
3. Sicherheitsrelevante Updates unverzüglich einzuspielen.

---

## 📖 Weitere Dokumentation

* 📘 [`README.md`](README.md) – Allgemeine Projektinformationen & Übersicht
* 📙 [`INSTALLATION.md`](INSTALLATION.md) – Detaillierte Installationsanleitung mit Sicherheitshinweisen

---

<div align="center">

  <sub>Erstellt für das Project **Prismateams** • Maintained by <a href="https://github.com/iAmCriptic">iAmCriptic</a></sub>

</div>
