#define MyAppName "OpenPOS"
#define MyAppVersion "1.0.9"
#define MyAppPublisher "OpenPOS Platform"
#define MyAppURL "https://github.com/Cave404/Open-POS"
#define MyAppExeName "OpenPOS.exe"

[Setup]
AppId={{7E1C3829-1B8F-4D2A-94B6-6BCB6B34A999}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=..\dist_installer
OutputBaseFilename=OpenPOS-Setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Core binaries and frozen distribution
Source: "..\dist\OpenPOS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
; Persistent data directory isolated from binary updates
Name: "{localappdata}\{#MyAppName}\data\db"; Flags: uninsneveruninstall
Name: "{localappdata}\{#MyAppName}\data\config"; Flags: uninsneveruninstall
Name: "{localappdata}\{#MyAppName}\data\logs"; Flags: uninsneveruninstall
Name: "{localappdata}\{#MyAppName}\data\custom_addons"; Flags: uninsneveruninstall
Name: "{localappdata}\{#MyAppName}\data\backups"; Flags: uninsneveruninstall

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
