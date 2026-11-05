# Prismateams Native Windows Client

Eine native, ressourcenschonende und schnelle Windows Desktop-Anwendung für **Prismateams**, geschrieben in modernem **C++20** mit **Microsoft Edge WebView2**.

---

## Highlights & Features

1. **Nativer App-Login mit WebAuthn / Passkeys**
   - Eigene Anmeldemaske mit Server-URL, E-Mail und Passwort.
   - Vollständige **2FA (TOTP)** Unterstützung.
   - **Passkey / WebAuthn Support** über native Windows Hello Integration (PIN, Fingerabdruck, Gesichtserkennung) sowie WebView2 FIDO2.
   - Sichere Speicherung der Zugangsdaten im **Windows Credential Manager** (`wincred.h`).
   - Automatische Synchronisation der Session-Cookies in das Webinterface ohne doppelten Login.

2. **Windows Explorer Integration (WebDAV / SMB)**
   - **1-Klick-Netzlaufwerk-Einbindung**: Bindet das Prismateams-Dateisystem direkt als virtuelles Laufwerk ein (Standard **`P:`** mit automatischem Fallback auf den nächsten freien Buchstaben).
   - Vollständiger nativer Datei-Workflow: Dateien erstellen, bearbeiten, speichern, umbenennen und löschen direkt im Windows Explorer.
   - Automatische Verwaltung des Windows `WebClient`-Dienstes.

3. **Live-Editing (Euro-Office & Excalidraw)**
   - Rechtsklick im Windows Explorer: **"In Prismateams live bearbeiten"** für:
     - Microsoft Office / OpenOffice: `.docx`, `.doc`, `.xlsx`, `.xls`, `.pptx`, `.ppt`, `.odt`, `.ods`, `.odp`, `.rtf`, `.txt`, `.csv`
     - Excalidraw: `.excalidraw`
   - Die App fängt das Dokument ab, löst den WebDAV-Pfad über die Server-API auf und öffnet direkt den kollaborativen **Euro-Office** (ONLYOFFICE) bzw. **Excalidraw** Editor in der App.
   - **Single-Instance IPC**: Wenn die App bereits läuft, wird die Datei über Windows IPC (`WM_COPYDATA`) an das bestehende Fenster übergeben und dieses in den Vordergrund geholt.

4. **Nativer Setup-Installer (`.exe`)**
   - Standalone-Installer erstellt mit Inno Setup (`Prismateams_Setup_v1.0.0.exe`).
   - Automatische Überprüfung und ggf. Hintergrund-Installation der Microsoft Edge WebView2 Evergreen Runtime.
   - Registrierung des URL-Protokolls `prismateams://` und der Explorer-Kontextmenüs.
   - Startmenü- und Desktop-Verknüpfungen, optionaler Windows-Autostart.
   - Saubere Deinstallation über Windows *"Programme und Features"*.

---

## Projektstruktur

```
windows/
├── Prismateams.sln               # Visual Studio Solution
├── Prismateams.vcxproj           # Visual Studio C++ Projekt (C++20)
├── Prismateams.vcxproj.filters   # Filter für den Solution Explorer
├── CMakeLists.txt                # Optionales CMake Build-Skript
├── packages.config               # NuGet Konfiguration für WebView2
├── packages/                     # Entpackte WebView2 C++ Header & Libraries
│   └── Microsoft.Web.WebView2/
├── resources/
│   ├── app.ico                   # Multi-Size Icon (16x16 bis 256x256)
│   ├── resource.h                # Menü- und Dialog-IDs
│   ├── Prismateams.rc            # Windows Ressourcen (Menüs, Dialoge, Manifest)
│   └── Prismateams.manifest      # PerMonitorV2 DPI-Awareness & Common Controls
├── src/
│   ├── main.cpp                  # WinMain: Single-Instance Mutex & IPC
│   ├── app.h / app.cpp           # Hauptfenster, Toolbar, Navigation, Login-Dialog
│   ├── auth_manager.h / .cpp     # WinHTTP Client, Login-API, 2FA, Token-Verwaltung
│   ├── webdav_manager.h / .cpp   # WNetAddConnection2W, Laufwerk P:, WebClient Service
│   ├── file_router.h / .cpp      # Pfad-Auflösung, Euro-Office & Excalidraw Routing
│   ├── webview_controller.h/.cpp # WebView2 Lifecycle, Cookie-Sync & JavaScript Bridge
│   ├── credential_vault.h / .cpp # Windows Credential Manager Kapselung
│   ├── settings.h / settings.cpp # Konfiguration (config.ini in %LOCALAPPDATA%)
│   └── tray_icon.h / .cpp        # System-Tray Icon & Kontextmenü
└── installer/
    ├── PrismateamsSetup.iss      # Inno Setup Skript für den .exe Installer
    └── build_installer.ps1       # Automatisches Build- & Packaging-Skript
```

---

## Bauen & Ausführen

### Mit Visual Studio
1. Öffnen Sie `windows/Prismateams.sln` in **Visual Studio**.
2. Wählen Sie als Konfiguration **Release** und als Plattform **x64**.
3. Drücken Sie `Strg + Umschalt + B` (Projektmappe erstellen).
4. Die kompilierte `Prismateams.exe` liegt in `windows/bin/Release/`.

### Automatisiertes Build & Installer-Erstellung (PowerShell)
```powershell
cd windows\installer
.\build_installer.ps1
```
Das Skript kompiliert das C++-Projekt über MSBuild und erstellt anschließend mit Inno Setup den Installer `Prismateams_Setup_v1.0.0.exe` in `windows\bin\Installer\`.
