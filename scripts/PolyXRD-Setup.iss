; ============================================================
; PolyXRD Setup - Inno Setup Script
; 使用: iscc /DAppVersion=2.0.1 /O"installer_output" /F"PolyXRD-Setup-v2.0.1" scripts\PolyXRD-Setup.iss
;
; 语言 (v2.0.1 新增中文):
;   简体中文 / 繁體中文 / English / 日本語
;   ⚠ Inno Setup 官方发行包【不自带】中文 .isl (仅 29 种语言)，
;     故中文语言文件随仓库提供于 scripts\languages\ 下，由本脚本引用。
; ============================================================

#ifndef AppVersion
  #define AppVersion "2.0.1"
#endif

#define AppName "PolyXRD"
#define AppPublisher "PolyXRD Team"
#define AppContact "sshztx@outlook.com"
#define AppExeName "PolyXRD.exe"
#define BuildOutputDir "..\dist\PolyXRD"
;# 中文语言文件所在目录 (相对本 .iss 文件)
#define LangDir "languages"

[Setup]
AppId={{A8F91C6B-2B3D-4F5E-8B3C-4E01A2C33D01}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
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
; lowest = 默认按当前用户安装 (无需管理员); 同时允许用户在向导里切换为"为所有用户安装"
;   -> 若用户把安装目录改到需要管理员权限的位置 (如 D:\Program Files\...)，可勾选管理员安装，
;      避免"权限不足、无法写入目标目录"导致安装无法继续。
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
DisableProgramGroupPage=yes
DisableDirPage=no
UninstallDisplayIcon={app}\{#AppExeName}
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} v{#AppVersion} Setup
VersionInfoCompany={#AppPublisher}
VersionInfoCopyright=(C) 2026 PolyXRD Team
; v2.0.1: 安装过程自动写日志到 %TEMP%\Setup Log <日期> #NNN.txt，
;   便于安装异常时定位 (无日志=安装根本没跑起来，如被杀软拦截)。
SetupLogging=yes

[Languages]
; 中文放最前: 系统语言为中文时向导自动选中中文
Name: "chinesesimplified"; MessagesFile: "{#LangDir}\ChineseSimplified.isl"
Name: "chinesetraditional"; MessagesFile: "{#LangDir}\ChineseTraditional.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[CustomMessages]
; 简体中文
chinesesimplified.AdditionalIcons=附加图标:
chinesesimplified.CreateDesktopIcon=创建桌面快捷方式(&D)
chinesesimplified.CreateQuickLaunchIcon=创建任务栏快捷方式(&Q)
chinesesimplified.UninstallShortcut=卸载 {#AppName}
chinesesimplified.LaunchApp=立即启动 {#AppName}
; 繁體中文
chinesetraditional.AdditionalIcons=附加圖示:
chinesetraditional.CreateDesktopIcon=建立桌面捷徑(&D)
chinesetraditional.CreateQuickLaunchIcon=建立工作列捷徑(&Q)
chinesetraditional.UninstallShortcut=解除安裝 {#AppName}
chinesetraditional.LaunchApp=立即啟動 {#AppName}
; English
english.AdditionalIcons=Additional icons:
english.CreateDesktopIcon=Create a &desktop shortcut
english.CreateQuickLaunchIcon=Create a &Quick Launch shortcut
english.UninstallShortcut=Uninstall {#AppName}
english.LaunchApp=Launch {#AppName} now
; 日本語
japanese.AdditionalIcons=追加アイコン:
japanese.CreateDesktopIcon=デスクトップにショートカットを作成(&D)
japanese.CreateQuickLaunchIcon=クイック起動にショートカットを作成(&Q)
japanese.UninstallShortcut={#AppName} をアンインストール
japanese.LaunchApp={#AppName} を起動

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#BuildOutputDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallShortcut}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\PolyXRD"; Check: not DirExists('{userappdata}\PolyXRD')
Type: filesandordirs; Name: "{userappdata}\PolyXRD"
