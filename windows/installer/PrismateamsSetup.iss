; Prismateams Inno Setup Script
; Generiert einen professionellen Windows-Installer (Prismateams_Setup.exe)

#define MyAppName "Prismateams"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Prismateams"
#define MyAppURL "https://prismateams.de"
#define MyAppExeName "Prismateams.exe"

[Setup]
AppId={{D374B542-C8EA-4DE9-91B2-7489C40E28A3}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=..\bin\Installer
OutputBaseFilename=Prismateams_Setup_v{#MyAppVersion}
SetupIconFile=..\resources\app.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startupicon"; Description: "Prismateams mit Windows im Hintergrund starten"; GroupDescription: "Systemintegration:"
Name: "explorercontext"; Description: "Rechtsklick-Eintrag 'In Prismateams live bearbeiten' im Windows Explorer registrieren"; GroupDescription: "Dateiverknüpfungen:"

[Files]
Source: "..\bin\Release\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\packages\Microsoft.Web.WebView2\build\native\x64\WebView2Loader.dll"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\resources\app.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\app.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\app.ico"
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--minimized"; Tasks: startupicon; IconFilename: "{app}\app.ico"

[Registry]
; URI Scheme: prismateams://
Root: HKCU; Subkey: "Software\Classes\prismateams"; ValueType: string; ValueName: ""; ValueData: "URL:Prismateams Protocol"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\prismateams"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\prismateams\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\app.ico"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\prismateams\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Flags: uninsdeletekey

; Context Menu: "In Prismateams live bearbeiten" für Office-Formate & Excalidraw
; Word
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.docx\Shell\PrismateamsLive"; ValueType: string; ValueName: ""; ValueData: "In Prismateams live bearbeiten"; Flags: uninsdeletekey; Tasks: explorercontext
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.docx\Shell\PrismateamsLive"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\app.ico"; Flags: uninsdeletekey; Tasks: explorercontext
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.docx\Shell\PrismateamsLive\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Flags: uninsdeletekey; Tasks: explorercontext

Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.doc\Shell\PrismateamsLive"; ValueType: string; ValueName: ""; ValueData: "In Prismateams live bearbeiten"; Flags: uninsdeletekey; Tasks: explorercontext
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.doc\Shell\PrismateamsLive"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\app.ico"; Flags: uninsdeletekey; Tasks: explorercontext
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.doc\Shell\PrismateamsLive\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Flags: uninsdeletekey; Tasks: explorercontext

; Excel
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.xlsx\Shell\PrismateamsLive"; ValueType: string; ValueName: ""; ValueData: "In Prismateams live bearbeiten"; Flags: uninsdeletekey; Tasks: explorercontext
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.xlsx\Shell\PrismateamsLive"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\app.ico"; Flags: uninsdeletekey; Tasks: explorercontext
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.xlsx\Shell\PrismateamsLive\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Flags: uninsdeletekey; Tasks: explorercontext

Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.xls\Shell\PrismateamsLive"; ValueType: string; ValueName: ""; ValueData: "In Prismateams live bearbeiten"; Flags: uninsdeletekey; Tasks: explorercontext
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.xls\Shell\PrismateamsLive"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\app.ico"; Flags: uninsdeletekey; Tasks: explorercontext
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.xls\Shell\PrismateamsLive\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Flags: uninsdeletekey; Tasks: explorercontext

; PowerPoint
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pptx\Shell\PrismateamsLive"; ValueType: string; ValueName: ""; ValueData: "In Prismateams live bearbeiten"; Flags: uninsdeletekey; Tasks: explorercontext
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pptx\Shell\PrismateamsLive"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\app.ico"; Flags: uninsdeletekey; Tasks: explorercontext
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pptx\Shell\PrismateamsLive\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Flags: uninsdeletekey; Tasks: explorercontext

; OpenDocument
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.odt\Shell\PrismateamsLive"; ValueType: string; ValueName: ""; ValueData: "In Prismateams live bearbeiten"; Flags: uninsdeletekey; Tasks: explorercontext
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.odt\Shell\PrismateamsLive"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\app.ico"; Flags: uninsdeletekey; Tasks: explorercontext
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.odt\Shell\PrismateamsLive\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Flags: uninsdeletekey; Tasks: explorercontext

Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.ods\Shell\PrismateamsLive"; ValueType: string; ValueName: ""; ValueData: "In Prismateams live bearbeiten"; Flags: uninsdeletekey; Tasks: explorercontext
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.ods\Shell\PrismateamsLive"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\app.ico"; Flags: uninsdeletekey; Tasks: explorercontext
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.ods\Shell\PrismateamsLive\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Flags: uninsdeletekey; Tasks: explorercontext

; Excalidraw
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.excalidraw\Shell\PrismateamsLive"; ValueType: string; ValueName: ""; ValueData: "In Prismateams live bearbeiten"; Flags: uninsdeletekey; Tasks: explorercontext
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.excalidraw\Shell\PrismateamsLive"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\app.ico"; Flags: uninsdeletekey; Tasks: explorercontext
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.excalidraw\Shell\PrismateamsLive\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Flags: uninsdeletekey; Tasks: explorercontext

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
// Prüft, ob WebView2 Runtime vorhanden ist, und bietet automatische Installation an
function IsWebView2Installed(): Boolean;
var
  InstalledVersion: String;
begin
  Result := RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-992A-446A-A215-2B34B9C49A06}', 'pv', InstalledVersion);
  if not Result then
    Result := RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-992A-446A-A215-2B34B9C49A06}', 'pv', InstalledVersion);
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
end;
