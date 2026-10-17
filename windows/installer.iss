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
CloseApplications=yes

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
Filename: "{cmd}"; Parameters: "/C taskkill /IM NeuralLoop.exe /T /F"; Flags: runhidden; RunOnceId: "StopNeuralLoop"
