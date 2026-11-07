; Muzix Desktop's installer for Windows (Inno Setup 6), made from PyInstaller's folder by the desktop
; workflow (.github/workflows/desktop.yml):
;   iscc /DAppVersion=0.1.0 /DSource=<dist\Muzix Desktop> /O<out> muzix-desktop.iss
; It installs for the user who runs it (no administrator needed), into their own Programs folder.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{C55116A4-84F6-47AA-AC2F-EEE3BA134EA2}
AppName=Muzix Desktop
AppVersion={#AppVersion}
AppVerName=Muzix Desktop {#AppVersion}
AppPublisher=Muzix
AppPublisherURL=https://github.com/svennefenne/muzix
AppSupportURL=https://github.com/svennefenne/muzix/issues
DefaultDirName={autopf}\Muzix Desktop
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=muzix-desktop-windows-x64-setup
SetupIconFile=..\..\muzix_desktop\assets\icon.ico
UninstallDisplayIcon={app}\Muzix Desktop.exe
UninstallDisplayName=Muzix Desktop
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; a running Muzix Desktop is closed for an update or an uninstall
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; an update brings all of the bundled files anew: none of an earlier version's are left behind
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#Source}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Muzix Desktop"; Filename: "{app}\Muzix Desktop.exe"
Name: "{autodesktop}\Muzix Desktop"; Filename: "{app}\Muzix Desktop.exe"; Tasks: desktopicon

[Registry]
; "Start Muzix Desktop when I log in" (set in its Settings) goes with it
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "Muzix Desktop"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\Muzix Desktop.exe"; Description: "{cm:LaunchProgram,Muzix Desktop}"; Flags: nowait postinstall skipifsilent
