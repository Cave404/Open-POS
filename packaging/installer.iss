#define MyAppName "OpenPOS"
#define MyAppVersion "1.0.9"
#define MyAppPublisher "OpenPOS Platform"
#define MyAppURL "https://github.com/Cave404/Open-POS"
#define MyAppExeName "OpenPOS.exe"
#define MyAppId "{{7E1C3829-1B8F-4D2A-94B6-6BCB6B34A999}"

[Setup]
; Fixed AppId uniquely identifies OpenPOS across all releases and pre-releases
AppId={#MyAppId}
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

; Upgrade and Self-Repair Directives
UsePreviousAppDir=yes
UsePreviousGroup=yes
UsePreviousTasks=yes
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Core Application Binaries (overwritten during upgrades and repairs)
Source: "..\dist\OpenPOS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
; Store Data Directories: strictly preserved on updates and never deleted on uninstall
Name: "{app}\data"; Flags: uninsneveruninstall
Name: "{app}\data\db"; Flags: uninsneveruninstall
Name: "{app}\data\config"; Flags: uninsneveruninstall
Name: "{app}\data\logs"; Flags: uninsneveruninstall
Name: "{app}\data\custom_addons"; Flags: uninsneveruninstall
Name: "{app}\data\backups"; Flags: uninsneveruninstall
Name: "{app}\data\uploads"; Flags: uninsneveruninstall

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
// Notify user upon uninstallation that business records remain intact
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    MsgBox('OpenPOS core binaries have been uninstalled.' + #13#10 + #13#10 +
           'Your store database, transaction history, custom addons, and configuration files remain safely preserved in the application data directory.', 
           mbInformation, MB_OK);
  end;
end;
