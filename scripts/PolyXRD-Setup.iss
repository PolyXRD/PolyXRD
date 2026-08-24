; ============================================================
; PolyXRD V0.8.23 — Installer Script (Inno Setup 6.x)
; 独立安装包: 主程序 + 全部依赖 (不含 COD 无机物数据库)
; 数据库需单独下载外挂包: PolyXRD_COD_Inorganics_v0.8.21.zip
; 本版本更新: 新增 MCP Server (AI-friendly 接口)
; ============================================================
#define MyAppName      "PolyXRD"
#define MyAppVersion   "0.8.23"
#define MyAppPublisher "PolyXRD Team"
#define MyAppExeName   "PolyXRD.exe"
#define MyAppUrl       "https://github.com/PolyXRD/PolyXRD"
#define BuildDistDir   "D:\TraeSolo\PolyXRD\dist\PolyXRD"
#define WizardImg      "D:\TraeSolo\PolyXRD\brand_assets\polyxrd-brand-assets\exports\innosetup\wizard_image.bmp"
#define WizardSmallImg "D:\TraeSolo\PolyXRD\brand_assets\polyxrd-brand-assets\exports\innosetup\wizard_small_image.bmp"

[Setup]
AppId={{4F3A8B61-5321-4D83-B3B2-6F42F003422D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppUrl}
AppSupportURL={#MyAppUrl}
AppUpdatesURL={#MyAppUrl}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=D:\TraeSolo\PolyXRD\release
OutputBaseFilename=PolyXRD-Setup-v0.8.23
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64
ArchitecturesAllowed=x64
DisableProgramGroupPage=yes
SetupIconFile=D:\TraeSolo\PolyXRD\src\polyxrd\resources\app-icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallFilesDir={app}\Uninstall
VersionInfoVersion=0.8.23.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=PolyXRD X-ray Diffraction Analysis Suite
VersionInfoCopyright=Copyright (C) 2025-2026 PolyXRD Team
; ---- 品牌视觉: 安装向导背景 ----
WizardImageFile={#WizardImg}
WizardSmallImageFile={#WizardSmallImg}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
; 注: PolyXRD 应用内已包含中文/英文/日文界面. 安装界面语言仅用于安装向导, 不影响应用语言.

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked
Name: "startmenuicon"; Description: "Create a start menu shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "{#BuildDistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; NOTE: COD 无机物数据库(COD_inorganics.sqlite, ~259MB) 不包含在主安装包,用户通过外挂包导入

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{commonprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startmenuicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Registry]
Root: HKCU; Subkey: "Software\PolyXRD"; Flags: uninsdeletekeyifempty

[Code]
function InitializeSetup: Boolean;
begin
  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  DataDir: string;
begin
  if CurStep = ssPostInstall then begin
    DataDir := ExpandConstant('{userappdata}\PolyXRD');
    if not DirExists(DataDir) then CreateDir(DataDir);
  end;
end;
