; Inno Setup script - builds VidHarbor-<version>-setup.exe from dist\VidHarbor
; Run:  iscc /DMyAppVersion=1.0.0 installer.iss
; Installs per user (no admin prompt) into %LOCALAPPDATA%\Programs\VidHarbor.
; Installing a newer setup over an older one updates in place; settings,
; sign-ins and engine updates live in %LOCALAPPDATA%\VidHarbor and are kept.

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

[Setup]
AppId={{351CD2F0-0893-40B2-9E5B-A8981BA0011E}
AppName=VidHarbor
AppVersion={#MyAppVersion}
AppVerName=VidHarbor {#MyAppVersion}
AppPublisher=VidHarbor
DefaultDirName={autopf}\VidHarbor
DefaultGroupName=VidHarbor
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist
OutputBaseFilename=VidHarbor-{#MyAppVersion}-setup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\VidHarbor.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "dist\VidHarbor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; drop files from the previous version so stale libraries never linger
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\VidHarbor"; Filename: "{app}\VidHarbor.exe"
Name: "{group}\Uninstall VidHarbor"; Filename: "{uninstallexe}"
Name: "{autodesktop}\VidHarbor"; Filename: "{app}\VidHarbor.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\VidHarbor.exe"; Description: "Start VidHarbor"; Flags: nowait postinstall skipifsilent
