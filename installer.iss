; Inno Setup script. The release workflow passes /DAppVersion=x.y.z.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId=ZunimiLabs.Tidy
AppName=Tidy
AppVersion={#AppVersion}
AppVerName=Tidy {#AppVersion}
AppPublisher=ZUNIMILABS
DefaultDirName={autopf}\Tidy
DefaultGroupName=Tidy
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=installer
OutputBaseFilename=Tidy-Setup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\Tidy.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=force

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"

[Files]
Source: "dist\Tidy\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[InstallDelete]
; Old program files must not mix with new ones. Settings and the deletion log live in %LOCALAPPDATA%\Tidy.
Type: filesandordirs; Name: "{app}\_internal"

[UninstallDelete]
; Tidy's own settings and logs go with it. It never stores anything of the person's there.
Type: filesandordirs; Name: "{localappdata}\Tidy"

[Icons]
Name: "{autoprograms}\Tidy"; Filename: "{app}\Tidy.exe"
Name: "{autodesktop}\Tidy"; Filename: "{app}\Tidy.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Tidy.exe"; Description: "Start Tidy"; Flags: nowait postinstall skipifsilent
; after an in-app update (a silent install) Tidy opens again by itself
Filename: "{app}\Tidy.exe"; Flags: nowait; Check: WizardSilent

[Code]
// Waits for the running app to close before any file is touched.
function AppIsRunning(Args: String): Boolean;
var
  Code: Integer;
begin
  Result := False;
  if Exec(ExpandConstant('{sys}\taskkill.exe'), Args, '', SW_HIDE, ewWaitUntilTerminated, Code) then
    Result := Code <> 128;      // 128 = no such program running
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  I: Integer;
begin
  Result := '';
  for I := 1 to 20 do begin
    if not AppIsRunning('/IM Tidy.exe') then begin
      Sleep(500);
      exit;
    end;
    Sleep(500);
  end;
  AppIsRunning('/F /T /IM Tidy.exe');
  Sleep(1500);
end;
