; Inno Setup script for the Windows installer. Built by: python scripts/build.py --installer
; (the build script passes /DAppVersion=... and /DSourceDir=...).
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\Airglide"
#endif

[Setup]
AppId={{66DD9D35-AFA8-4B27-A8D0-EB37B5E7DE1E}
AppName=Airglide
AppVersion={#AppVersion}
AppPublisher=Airglide
DefaultDirName={autopf}\Airglide
DefaultGroupName=Airglide
DisableProgramGroupPage=yes
; Per-user install: no administrator rights needed.
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Airglide-{#AppVersion}-windows-setup
SetupIconFile=..\Assets\icon.ico
UninstallDisplayIcon={app}\Airglide.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Airglide"; Filename: "{app}\Airglide.exe"
Name: "{group}\Uninstall Airglide"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Airglide"; Filename: "{app}\Airglide.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Airglide.exe"; Description: "Start Airglide"; Flags: nowait postinstall skipifsilent
