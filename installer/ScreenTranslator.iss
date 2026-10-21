; Inno Setup script. Build with: ISCC installer\ScreenTranslator.iss  (after build.bat has produced the PyInstaller folder)
#define AppName "Screen Translator"
#define AppVersion "0.3.0"
#ifndef SourceDir
  #define SourceDir "..\dist\ScreenTranslator"
#endif

[Setup]
AppId={{6D1C5E0A-4B7B-4F0B-9C55-3A5E7B2D9A11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=MilkteaTW1
DefaultDirName={autopf}\ScreenTranslator
DefaultGroupName={#AppName}
OutputBaseFilename=ScreenTranslator-Setup-{#AppVersion}
OutputDir=..\dist
Compression=lzma2/fast
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\ScreenTranslator.exe
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked
Name: "autostart"; Description: "Start Screen Translator with Windows"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\ScreenTranslator.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\ScreenTranslator.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ScreenTranslator.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "ScreenTranslator"; ValueData: """{app}\ScreenTranslator.exe"" --minimized"; Tasks: autostart; Flags: uninsdeletevalue
