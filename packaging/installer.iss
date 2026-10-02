#define MyAppName "OpenPOS"
#define MyAppVersion "1.0.9"
#define MyAppPublisher "OpenPOS Platform"
#define MyAppURL "https://github.com/Cave404/Open-POS"
#define MyAppExeName "OpenPOS.exe"
#define MyAppId "{{7E1C3829-1B8F-4D2A-94B6-6BCB6B34A999}"

[Setup]
AppId={#MyAppId}
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
Source: "..\dist\OpenPOS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

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

// 1. Detect if WebView2 Runtime is installed
function IsWebView2Installed(): Boolean;
var
  InstalledVersion: String;
begin
  Result := RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-991A-47C2-9A4E-A795240217C1}', 'pv', InstalledVersion) or
            RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-991A-47C2-9A4E-A795240217C1}', 'pv', InstalledVersion);
end;

// 2. Detect if OpenPOS is already installed
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
      'OpenPOS Maintenance & Setup', 
      'An existing OpenPOS installation was detected on this computer. Choose an operation.');

    LblPrompt := TLabel.Create(MaintenancePage);
    LblPrompt.Parent := MaintenancePage.Surface;
    LblPrompt.Caption := 'Select the action you wish to perform:';
    LblPrompt.Top := ScaleY(10);
    LblPrompt.Left := ScaleX(0);

    RadioRepair := TNewRadioButton.Create(MaintenancePage);
    RadioRepair.Parent := MaintenancePage.Surface;
    RadioRepair.Top := LblPrompt.Top + ScaleY(25);
    RadioRepair.Left := ScaleX(10);
    RadioRepair.Caption := 'Repair OpenPOS (Reinstall and repair missing or corrupted files)';
    RadioRepair.Checked := True;

    RadioUpdate := TNewRadioButton.Create(MaintenancePage);
    RadioUpdate.Parent := MaintenancePage.Surface;
    RadioUpdate.Top := RadioRepair.Top + ScaleY(28);
    RadioUpdate.Left := ScaleX(10);
    RadioUpdate.Caption := 'Update / Reinstall (Apply current software package)';

    RadioUninstall := TNewRadioButton.Create(MaintenancePage);
    RadioUninstall.Parent := MaintenancePage.Surface;
    RadioUninstall.Top := RadioUpdate.Top + ScaleY(28);
    RadioUninstall.Left := ScaleX(10);
    RadioUninstall.Caption := 'Uninstall OpenPOS (Safely remove binaries; retains store database)';
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  // In Maintenance Mode, skip directory and task selection if user just wants to repair or update in-place
  if IsMaintenanceMode and (PageID = wpSelectDir) then
    Result := True
  else
    Result := False;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  UninstallerPath: String;
  ResultCode: Integer;
begin
  Result := True;
  if IsMaintenanceMode and (MaintenancePage <> nil) and (CurPageID = MaintenancePage.ID) then
  begin
    if RadioUninstall.Checked then
    begin
      // User selected uninstall from the maintenance screen
      if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppId}_is1', 'UninstallString', UninstallerPath) or
         RegQueryStringValue(HKLM, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppId}_is1', 'UninstallString', UninstallerPath) then
      begin
        UninstallerPath := RemoveQuotes(UninstallerPath);
        Exec(UninstallerPath, '', '', SW_SHOWNORMAL, ewNoWait, ResultCode);
        WizardForm.Close;
        Result := False;
      end;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  DownloadUrl, TempInstaller: String;
begin
  if CurStep = ssPreInstall then
  begin
    // Check WebView2 prerequisite
    if not IsWebView2Installed() then
    begin
      WizardForm.StatusLabel.Caption := 'Installing Microsoft Edge WebView2 Runtime...';
      // Download or trigger silent Evergreen Bootstrapper
      DownloadUrl := 'https://go.microsoft.com/fwlink/p/?LinkId=2124703';
      TempInstaller := ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe');
      
      if FileExists(ExpandConstant('{src}\MicrosoftEdgeWebview2Setup.exe')) then
        CopyFile(ExpandConstant('{src}\MicrosoftEdgeWebview2Setup.exe'), TempInstaller, False)
      else
      begin
        Exec('curl.exe', Format('-L -s -o "%s" "%s"', [TempInstaller, DownloadUrl]), '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
        if not FileExists(TempInstaller) then
          Exec('powershell.exe', Format('-WindowStyle Hidden -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile(''%s'', ''%s'')"', [DownloadUrl, TempInstaller]), '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
      end;

      if FileExists(TempInstaller) then
        Exec(TempInstaller, '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    MsgBox('OpenPOS core application files have been uninstalled.' + #13#10 + #13#10 +
           'All store databases, transaction logs, receipts, and custom addons remain safely preserved in the application data folder.', 
           mbInformation, MB_OK);
  end;
end;
