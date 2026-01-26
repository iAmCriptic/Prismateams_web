# Neue Abhängigkeiten für API-Erweiterungen

Die folgenden Python-Pakete müssen zur `requirements.txt` hinzugefügt werden:

```
flask-restx==1.3.0
```

## Installation

```bash
pip install flask-restx==1.3.0
```

Oder alternativ:

```bash
pip install -r requirements.txt
```

## Hinweise

- **Flask-RESTX** wird für die Swagger/OpenAPI-Dokumentation verwendet
- OAuth2 wird mit den bereits vorhandenen Bibliotheken (PyJWT, cryptography) implementiert
- Webhooks nutzen die vorhandene `requests` Bibliothek
