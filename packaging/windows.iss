#define AppTag "7.41f+Trove_of_Terror"
[Setup]
AppId={{77D647D8-B42B-4BC2-B10B-52EB9DF83D41}
AppName=Wallpaper changer
AppVersion={#AppTag}
AppPublisher=sparr0wl
AppPublisherURL=https://github.com/sparr0wl/wallpaper-changer
AppSupportURL=https://github.com/sparr0wl/wallpaper-changer/issues
DefaultDirName={localappdata}\Programs\WallpaperChanger
DefaultGroupName=Wallpaper changer
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\dist
OutputBaseFilename=wallpaper-changer-{#AppTag}-windows-x86_64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\wallpaper-changer.exe
CloseApplications=yes
ChangesEnvironment=yes
VersionInfoVersion=7.41.0.0

[Files]
Source: "..\dist\windows\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[Icons]
Name: "{autoprograms}\Wallpaper changer"; Filename: "{app}\wallpaper-changer.exe"
Name: "{autodesktop}\Wallpaper changer"; Filename: "{app}\wallpaper-changer.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\wallpaper-changer.exe"; ValueType: string; ValueData: "{app}\wallpaper-changer.exe"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\wallpaper-changer.exe"; ValueType: string; ValueName: "Path"; ValueData: "{app}"

[Run]
Filename: "{app}\wallpaper-changer.exe"; Description: "Launch Wallpaper changer"; Flags: nowait postinstall skipifsilent

[Code]
function ContainsPath(Value, Directory: String): Boolean;
begin
  Result := Pos(';' + Lowercase(Directory) + ';', ';' + Lowercase(Value) + ';') > 0;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Value, Directory: String;
begin
  if CurStep = ssPostInstall then begin
    Directory := ExpandConstant('{app}');
    RegQueryStringValue(HKCU, 'Environment', 'Path', Value);
    if not ContainsPath(Value, Directory) then begin
      if Value <> '' then Value := Value + ';';
      RegWriteExpandStringValue(HKCU, 'Environment', 'Path', Value + Directory);
      RegWriteDWordValue(HKCU, 'Software\WallpaperChanger', 'AddedToPath', 1);
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Value, Directory: String;
  Added: Cardinal;
  Position: Integer;
begin
  if (CurUninstallStep = usPostUninstall) and
     RegQueryDWordValue(HKCU, 'Software\WallpaperChanger', 'AddedToPath', Added) and (Added = 1) then begin
    Directory := Lowercase(ExpandConstant('{app}'));
    RegQueryStringValue(HKCU, 'Environment', 'Path', Value);
    Position := Pos(';' + Directory + ';', ';' + Lowercase(Value) + ';');
    if Position > 1 then
      Delete(Value, Position - 1, Length(Directory) + 1)
    else if Position = 1 then
      Delete(Value, 1, Length(Directory) + 1);
    RegWriteExpandStringValue(HKCU, 'Environment', 'Path', Value);
    RegDeleteValue(HKCU, 'Software\WallpaperChanger', 'AddedToPath');
  end;
end;
