#define MyAppName "OpenPOS"
#define MyAppVersion "1.0.99"
#define MyAppPublisher "OpenPOS Platform"
#define MyAppURL "https://github.com/Cave404/Open-POS"
#define MyAppExeName "OpenPOS.exe"
#define MyAppId "{7E1C3829-1B8F-4D2A-94B6-6BCB6B34A999}"

[Setup]
AppId={{#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=..\dist_installer
OutputBaseFilename=OpenPOS-Setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest

UsePreviousAppDir=yes
UsePreviousGroup=yes
UsePreviousTasks=yes
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Core application binaries
Source: "..\dist\OpenPOS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Bundled WebView2 bootstrapper (temporarily extracted to run if needed)
Source: "MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: ignoreversion deleteafterinstall

[Dirs]
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
var
  MaintenancePage: TWizardPage;
  RadioRepair, RadioUpdate, RadioUninstall: TNewRadioButton;
  IsMaintenanceMode: Boolean;
  PortPage: TInputQueryWizardPage;

function IsWebView2Installed(): Boolean;
var
  VersionStr: String;
begin
  Result := RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-991A-47C2-9A4E-A795240217C1}', 'pv', VersionStr) or
            RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-991A-47C2-9A4E-A795240217C1}', 'pv', VersionStr) or
            RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-991A-47C2-9A4E-A795240217C1}', 'pv', VersionStr);
end;

function IsAppInstalled(): Boolean;
var
  UninstPath: String;
begin
  Result := RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppId}_is1', 'UninstallString', UninstPath) or
            RegQueryStringValue(HKLM, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppId}_is1', 'UninstallString', UninstPath);
end;

procedure InitializeWizard();
var
  LblPrompt: TLabel;
begin
  IsMaintenanceMode := IsAppInstalled();

  if IsMaintenanceMode then
  begin
    MaintenancePage := CreateCustomPage(wpWelcome, 
      'OpenPOS Maintenance', 
      'An existing installation of OpenPOS was detected. Select an option to proceed:');

    LblPrompt := TLabel.Create(MaintenancePage);
    LblPrompt.Parent := MaintenancePage.Surface;
    LblPrompt.Caption := 'Choose an operation:';
    LblPrompt.Top := ScaleY(10);
    LblPrompt.Left := ScaleX(0);

    RadioRepair := TNewRadioButton.Create(MaintenancePage);
    RadioRepair.Parent := MaintenancePage.Surface;
    RadioRepair.Top := LblPrompt.Top + ScaleY(25);
    RadioRepair.Left := ScaleX(15);
    RadioRepair.Caption := 'Repair OpenPOS (Verify and restore all application files; keeps store data)';
    RadioRepair.Checked := True;

    RadioUpdate := TNewRadioButton.Create(MaintenancePage);
    RadioUpdate.Parent := MaintenancePage.Surface;
    RadioUpdate.Top := RadioRepair.Top + ScaleY(30);
    RadioUpdate.Left := ScaleX(15);
    RadioUpdate.Caption := 'Update / Reinstall (Upgrade core files to version {#MyAppVersion})';

    RadioUninstall := TNewRadioButton.Create(MaintenancePage);
    RadioUninstall.Parent := MaintenancePage.Surface;
    RadioUninstall.Top := RadioUpdate.Top + ScaleY(30);
    RadioUninstall.Left := ScaleX(15);
    RadioUninstall.Caption := 'Uninstall OpenPOS (Remove binaries; preserves all store data and settings)';
  end;

  PortPage := CreateInputQueryPage(wpSelectTasks,
    'Server Configuration',
    'Local Web Server Port Assignment',
    'Specify the local TCP port for OpenPOS presentation server to bind to (Default: 5050):');
  PortPage.Add('Server Port:', False);
  PortPage.Values[0] := '5050';
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  if IsMaintenanceMode and ((PageID = wpSelectDir) or (PageID = wpSelectTasks) or ((PortPage <> nil) and (PageID = PortPage.ID))) then
    Result := True
  else
    Result := False;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  UninstPath: String;
  ResultCode: Integer;
  PortVal: Integer;
begin
  Result := True;
  if IsMaintenanceMode and (MaintenancePage <> nil) and (CurPageID = MaintenancePage.ID) then
  begin
    if RadioUninstall.Checked then
    begin
      if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppId}_is1', 'UninstallString', UninstPath) or
         RegQueryStringValue(HKLM, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppId}_is1', 'UninstallString', UninstPath) then
      begin
        UninstPath := RemoveQuotes(UninstPath);
        Exec(UninstPath, '', '', SW_SHOWNORMAL, ewNoWait, ResultCode);
        WizardForm.Close;
        Result := False;
        Exit;
      end;
    end;
  end;

  if (PortPage <> nil) and (CurPageID = PortPage.ID) then
  begin
    PortVal := StrToIntDef(Trim(PortPage.Values[0]), 0);
    if (PortVal < 1024) or (PortVal > 65535) then
    begin
      MsgBox('Please enter a valid TCP port number between 1024 and 65535.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
  end;
end;

procedure SaveInstallerPortConfig();
var
  ConfigDir, SettingsFile, PortStr, FileContent: String;
begin
  ConfigDir := ExpandConstant('{app}\data\config');
  SettingsFile := ConfigDir + '\store_settings.json';
  if PortPage <> nil then
    PortStr := Trim(PortPage.Values[0])
  else
    PortStr := '5050';

  if PortStr = '' then
    PortStr := '5050';

  ForceDirectories(ConfigDir);
  if not FileExists(SettingsFile) then
  begin
    FileContent := '{' + #13#10 +
                   '  "server_port": ' + PortStr + #13#10 +
                   '}';
    SaveStringToFile(SettingsFile, FileContent, False);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  BootstrapperPath: String;
begin
  if CurStep = ssPreInstall then
  begin
    if not IsWebView2Installed() then
    begin
      BootstrapperPath := ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe');
      if FileExists(BootstrapperPath) then
      begin
        WizardForm.StatusLabel.Caption := 'Installing required Microsoft Edge WebView2 runtime...';
        Exec(BootstrapperPath, '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
      end;
    end;
  end
  else if CurStep = ssPostInstall then
  begin
    SaveInstallerPortConfig();
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    MsgBox('OpenPOS application files have been uninstalled.' + #13#10 + #13#10 +
           'All store databases, sales history, custom addons, and configuration files remain safely preserved in the application data folder.', 
           mbInformation, MB_OK);
  end;
end;
