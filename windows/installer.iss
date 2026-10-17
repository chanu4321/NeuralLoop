; Inno Setup script for NeuralLoop for Windows. `python windows/build.py` runs it when Inno Setup is installed:
;   iscc /DVersion=0.2.2 /DSource=dist\windows\NeuralLoop /DOut=dist windows\installer.iss
; Installs for this person only (no administrator needed) into %LOCALAPPDATA%\Programs\NeuralLoop, with a Start
; menu entry and an optional "start with Windows" (so Pip's nudges come without opening the app). Books, progress
; and settings live in %APPDATA%\NeuralLoop and stay when the app is removed.

#ifndef Version
  #define Version "0.0.0"
#endif
#ifndef Source
  #define Source "..\dist\windows\NeuralLoop"
#endif
#ifndef Out
  #define Out "..\dist"
#endif

[Setup]
AppId={{6F1C2D9A-4E7B-4B8E-9C3A-2B5D7E1F0A42}
AppName=NeuralLoop
AppVersion={#Version}
AppVerName=NeuralLoop {#Version}
AppPublisher=NeuralLoop
AppPublisherURL=https://github.com/NebulaTris/NeuralLoop
DefaultDirName={localappdata}\Programs\NeuralLoop
DefaultGroupName=NeuralLoop
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#Out}
OutputBaseFilename=NeuralLoop-{#Version}-setup
SetupIconFile={#Source}\_internal\NeuralLoop.ico
UninstallDisplayIcon={app}\NeuralLoop.exe
LicenseFile={#Source}\_internal\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Setup closes NeuralLoop itself (PrepareToInstall below) instead of asking through the Restart Manager: both
; programs and anything they started (a book being prepared, espeak-ng, a browser for sign-in) must be gone
; before their files can be replaced, and a half-closed app is never a choice worth offering.
CloseApplications=no
RestartApplications=no

[Tasks]
Name: "startup"; Description: "Start NeuralLoop when I sign in to Windows (Pip's nudges need it running)"; Flags: checkedonce
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked

[Files]
Source: "{#Source}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\NeuralLoop"; Filename: "{app}\NeuralLoop.exe"
Name: "{userdesktop}\NeuralLoop"; Filename: "{app}\NeuralLoop.exe"; Tasks: desktopicon
Name: "{userstartup}\NeuralLoop"; Filename: "{app}\NeuralLoop.exe"; Parameters: "--background"; Tasks: startup

[Run]
Filename: "{app}\NeuralLoop.exe"; Description: "Open NeuralLoop"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM NeuralLoop.exe /T /F"; Flags: runhidden; RunOnceId: "StopNeuralLoop"
Filename: "{sys}\taskkill.exe"; Parameters: "/IM nl-book.exe /T /F"; Flags: runhidden; RunOnceId: "StopBookPreparation"

[Messages]
ReadyLabel2a=Click Install to continue. If NeuralLoop is open, Setup closes it first; your books and progress stay.
ReadyLabel2b=Click Install to continue. If NeuralLoop is open, Setup closes it first; your books and progress stay.

[Code]
procedure StopProgram(const Name: String);
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM ' + Name + ' /T /F', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  { The app, then any book being prepared (with what it started). A book that was mid-way carries on from
    where it stopped the next time NeuralLoop opens. }
  StopProgram('NeuralLoop.exe');
  StopProgram('nl-book.exe');
  Sleep(800);
  Result := '';
end;
