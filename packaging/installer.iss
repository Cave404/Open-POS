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
  ConfigPage: TWizardPage;
  StoreNameEdit: TNewEdit;
  PinEdit: TPasswordEdit;
  DbCombo: TNewComboBox;

function IsFreshInstallation(): Boolean;
begin
  // Only present store configuration if .setup_complete does not already exist
  Result := not FileExists(ExpandConstant('{app}\data\config\.setup_complete'));
end;

procedure InitializeWizard();
var
  LblStore, LblPin, LblDb: TLabel;
begin
  ConfigPage := CreateCustomPage(wpSelectTasks, 
    'Store Configuration & Security Setup', 
    'Configure initial business branding and administrative access credentials.');

  LblStore := TLabel.Create(ConfigPage);
  LblStore.Parent := ConfigPage.Surface;
  LblStore.Caption := 'Store / Business Name:';
  LblStore.Top := ScaleY(10);
  LblStore.Left := ScaleX(0);

  StoreNameEdit := TNewEdit.Create(ConfigPage);
  StoreNameEdit.Parent := ConfigPage.Surface;
  StoreNameEdit.Top := LblStore.Top + ScaleY(20);
  StoreNameEdit.Left := ScaleX(0);
  StoreNameEdit.Width := ScaleX(320);
  StoreNameEdit.Text := 'Dragon''s Lair TCG';

  LblPin := TLabel.Create(ConfigPage);
  LblPin.Parent := ConfigPage.Surface;
  LblPin.Caption := 'Administrative Master PIN (4 to 6 Digits):';
  LblPin.Top := StoreNameEdit.Top + ScaleY(35);
  LblPin.Left := ScaleX(0);

  PinEdit := TPasswordEdit.Create(ConfigPage);
  PinEdit.Parent := ConfigPage.Surface;
  PinEdit.Top := LblPin.Top + ScaleY(20);
  PinEdit.Left := ScaleX(0);
  PinEdit.Width := ScaleX(160);
  PinEdit.Text := '1234';

  LblDb := TLabel.Create(ConfigPage);
  LblDb.Parent := ConfigPage.Surface;
  LblDb.Caption := 'Database Backend Architecture:';
  LblDb.Top := PinEdit.Top + ScaleY(35);
  LblDb.Left := ScaleX(0);

  DbCombo := TNewComboBox.Create(ConfigPage);
  DbCombo.Parent := ConfigPage.Surface;
  DbCombo.Top := LblDb.Top + ScaleY(20);
  DbCombo.Left := ScaleX(0);
  DbCombo.Width := ScaleX(320);
  DbCombo.Style := csDropDownList;
  DbCombo.Items.Add('Local Embedded SQLite (Single Station)');
  DbCombo.Items.Add('Centralized PostgreSQL (Multi-Terminal Network)');
  DbCombo.ItemIndex := 0;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  // Skip custom page if OpenPOS is already provisioned on this computer
  if (PageID = ConfigPage.ID) and (not IsFreshInstallation()) then
    Result := True
  else
    Result := False;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  Params: String;
  DbChoice: String;
begin
  if CurStep = ssPostInstall then
  begin
    if IsFreshInstallation() then
    begin
      if DbCombo.ItemIndex = 1 then
        DbChoice := 'postgres'
      else
        DbChoice := 'sqlite';

      Params := Format('--provision --store-name "%s" --admin-pin "%s" --db-engine "%s"', [
        StoreNameEdit.Text,
        PinEdit.Text,
        DbChoice
      ]);

      // Silently invoke Python to generate security keys, settings, and migrations
      Exec(ExpandConstant('{app}\{#MyAppExeName}'), Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    MsgBox('OpenPOS core binaries have been removed.' + #13#10 + #13#10 +
           'Your store database, custom addons, receipts, and settings remain safely stored in the application data directory.', 
           mbInformation, MB_OK);
  end;
end;
