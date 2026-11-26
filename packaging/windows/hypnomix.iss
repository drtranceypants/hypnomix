; Inno Setup script for the Windows installer. Built by packaging\windows\build.ps1, which passes
; AppVersion, SourceDir (the staged app: python\, bin\ffmpeg.exe, launcher.pyw, hypnomix.ico) and OutDir.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{7E3B5C1A-5A0B-4F7E-9C59-8A1F2B6D4E21}
AppName=hypnomix
AppVersion={#AppVersion}
AppPublisher=Dr. Trance
AppPublisherURL=https://hypnomix.bradfieldenterprises.org
AppSupportURL=https://github.com/drtranceypants/hypnomix/issues
DefaultDirName={localappdata}\Programs\Hypnomix
DefaultGroupName=hypnomix
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutDir}
OutputBaseFilename=Hypnomix-{#AppVersion}-windows-x64-setup
SetupIconFile={#SourceDir}\hypnomix.ico
UninstallDisplayIcon={app}\hypnomix.ico
LicenseFile={#SourceDir}\LICENSE.txt
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
#ifdef SIGN
SignTool=signtool
SignedUninstaller=yes
#endif

[Tasks]
Name: "desktopicon"; Description: "Make a desktop shortcut"; Flags: unchecked
Name: "live"; Description: "Set up Ableton Live (copy the AbletonOSC remote script into Live's User Library)"

[InstallDelete]
; an upgrade replaces the whole Python tree, so packages a new version dropped do not linger
Type: filesandordirs; Name: "{app}\python"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\hypnomix"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\launcher.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\hypnomix.ico"
Name: "{group}\Quit hypnomix"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\launcher.pyw"" --stop"; WorkingDir: "{app}"; IconFilename: "{app}\hypnomix.ico"
Name: "{userdesktop}\hypnomix"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\launcher.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\hypnomix.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\python\python.exe"; Parameters: "-m hypnomix.cli install"; StatusMsg: "Setting up Ableton Live…"; Flags: runhidden; Tasks: live
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\launcher.pyw"""; Description: "Open hypnomix now"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\launcher.pyw"" --stop"; Flags: runhidden; RunOnceId: "StopServer"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\python"

[Code]
// stop a running copy before files are replaced on an upgrade
function PrepareToInstall(var NeedsRestart: Boolean): String;
var Code: Integer;
begin
  if FileExists(ExpandConstant('{app}\launcher.pyw')) then
    Exec(ExpandConstant('{app}\python\pythonw.exe'), '"' + ExpandConstant('{app}\launcher.pyw') + '" --stop', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := '';
end;
