; ============================================================
; PolyXRD Setup - Inno Setup Script
; 使用: iscc /DAppVersion=0.9.0 /O"installer_output" /F"PolyXRD-Setup-v0.9.0" scripts\PolyXRD-Setup.iss
; ============================================================

#ifndef AppVersion
  #define AppVersion "0.9.0"
#endif

#define AppName "PolyXRD"
#define AppPublisher "PolyXRD Team"
#define AppContact "sshztx@outlook.com"
#define AppExeName "PolyXRD.exe"
#define BuildOutputDir "..\dist\PolyXRD"

[Setup]
AppId={{A8F91C6B-2B3D-4F5E-8B3C-4E01A2C33D01}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=mailto:{#AppContact}
AppSupportURL=mailto:{#AppContact}
AppUpdatesURL=https://github.com/PolyXRD/PolyXRD/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=yes
OutputDir=..\installer_output
OutputBaseFilename=PolyXRD-Setup-v{#AppVersion}
SetupIconFile=..\src\polyxrd\resources\app-icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
DisableProgramGroupPage=yes
DisableDirPage=no
UninstallDisplayIcon={app}\{#AppExeName}
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} v{#AppVersion} Setup
VersionInfoCompany={#AppPublisher}
VersionInfoCopyright=(C) 2026 PolyXRD Team

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"; Flags: unchecked
Name: "quicklaunchicon"; Description: "创建任务栏快捷方式"; GroupDescription: "附加图标:"; Flags: unchecked; OnlyBelowVersion: 0,6.1

[Files]
Source: "{#BuildOutputDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: quicklaunchicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "现在启动 {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\PolyXRD"; Check: not DirExists('{userappdata}\PolyXRD')
Type: filesandordirs; Name: "{userappdata}\PolyXRD"
