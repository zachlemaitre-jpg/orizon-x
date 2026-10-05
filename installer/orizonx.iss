; Orizon X installer (Inno Setup 6.7+). Built by build-pc.ps1:
;   ISCC.exe /DAppVersion=0.5.0 /DSourceDir=<repo>\dist\OrizonX-PC /O<repo>\dist installer\orizonx.iss
; Spec: docs/superpowers/specs/2026-10-05-installer-virtual-display-design.md §6 and §8 (§8 wins).
; Notes: docs/notes/vdd-control.md §6 and "E. Task 9".
;
; The driver work is done by OrizonX.exe itself (app/admin.py), run hidden and elevated from [Code] so that every
; exit code is checked (0 = success, 1 = failure, details in the app's log):
;   --configure-vdd [--restart], --install-driver <inf>, --remove-driver, --cleanup.
; No devcon (Microsoft's tool is not redistributable).

#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif
#ifndef SourceDir
  ; dossier de l'appli compilée par PyInstaller (build-pc.ps1)
  #define SourceDir "..\dist\OrizonX-PC"
#endif
#define AppName "Orizon X"
#define AppExe "OrizonX.exe"
; Doit rester celui de app/autostart.py (VALUE_NAME) et la commande celle de command_for().
#define RunValueName "OrizonX"
; Dossier du XML de VDD utilisé par l'appli (vdd.DEFAULT_SETTINGS_PATH).
#define VddConfigDir "C:\VirtualDisplayDriver"

[Setup]
; Ne jamais changer l'AppId : c'est lui qui fait d'une nouvelle installation une mise à jour.
AppId={{9BED2225-7EBE-4D0D-9CED-A8CDE89345D0}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Orizon X
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
ShowLanguageDialog=yes
LicenseFile=LICENSES.txt
SetupIconFile=..\host-prototype\app\assets\orizonx.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
OutputDir=..\dist
OutputBaseFilename=OrizonX-Setup
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
; HKCU (langue, démarrage auto) : c'est la ruche du compte qui élève Setup ; voir docs/notes/vdd-control.md §6.
UsedUserAreasWarning=no
SetupLogging=yes

[Languages]
; English first = default; the dialog preselects the Windows display language when it is one of these.
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"

[CustomMessages]
en.LaunchApp=Launch Orizon X
fr.LaunchApp=Lancer Orizon X
en.AutoStartTask=Start Orizon X when Windows starts
fr.AutoStartTask=Démarrer Orizon X avec Windows
en.StartupGroup=Startup:
fr.StartupGroup=Démarrage :
en.DriverPageCaption=Virtual display driver
fr.DriverPageCaption=Pilote d'écran virtuel
en.DriverPageDescription=Windows will ask for your permission during the installation.
fr.DriverPageDescription=Windows va vous demander votre accord pendant l'installation.
en.DriverPageText=Orizon X installs a virtual display driver so that the tablet can extend your desktop.%n%nWindows will ask you to install the virtual display driver (publisher: SignPath Foundation). Click Install.%n%nIf that window does not come to the front, look for it in the taskbar. If you refuse, Orizon X will work in Duplicate mode only.
fr.DriverPageText=Orizon X installe un pilote d'écran virtuel pour que la tablette prolonge votre bureau.%n%nWindows va vous demander d'installer le pilote d'écran virtuel (éditeur : SignPath Foundation). Cliquez sur Installer.%n%nSi cette fenêtre ne passe pas au premier plan, cherchez-la dans la barre des tâches. Si vous refusez, Orizon X fonctionnera seulement en mode Dupliquer.
en.VddInstallFailed=The virtual display driver could not be installed. Orizon X will work in Duplicate mode.
fr.VddInstallFailed=Le pilote d'écran virtuel n'a pas pu être installé. Orizon X fonctionnera en mode Dupliquer.
en.RemoveVddQuestion=Also remove the virtual display driver? (another program may use it)
fr.RemoveVddQuestion=Supprimer aussi le pilote d'écran virtuel ? (un autre programme peut l'utiliser)
en.VddRemoveFailed=The virtual display driver could not be removed. You can remove "Virtual Display Driver" in Device Manager (Display adapters).
fr.VddRemoveFailed=Le pilote d'écran virtuel n'a pas pu être supprimé. Vous pouvez supprimer « Virtual Display Driver » dans le Gestionnaire de périphériques (Cartes graphiques).

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart"; Description: "{cm:AutoStartTask}"; GroupDescription: "{cm:StartupGroup}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Pilote VDD x64 signé : ne jamais modifier ces fichiers (le .cat signe leurs octets exacts).
Source: "vdd\*"; DestDir: "{app}\vdd"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
; Langue choisie dans l'installateur : l'appli lit ses réglages, puis HKCU, puis HKLM, puis l'anglais (spec §8).
Root: HKCU; Subkey: "Software\OrizonX"; ValueType: string; ValueName: "Language"; ValueData: "{language}"; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKLM; Subkey: "Software\OrizonX"; ValueType: string; ValueName: "Language"; ValueData: "{language}"; Flags: uninsdeletekey
; Même valeur que app/autostart.py : l'appli la reconnaît comme « Lancer avec Windows » activé.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#RunValueName}"; ValueData: """{app}\{#AppExe}"" --minimized"; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Description: "{cm:LaunchApp}"; Flags: postinstall nowait skipifsilent runasoriginaluser

[Code]
const
  VddEnumKey = 'SYSTEM\CurrentControlSet\Enum\ROOT\DISPLAY';
  OrizonKey = 'Software\OrizonX';
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';

var
  DriverPresentAtStart: Boolean;
  DriverPage: TOutputMsgWizardPage;

{ Détection du pilote : le nœud créé pour VDD s'appelle ROOT\DISPLAY\NNNN (pas ROOT\MTTVDD\...), on cherche donc
  l'ID matériel Root\MttVDD dans le registre. Lisible sans droits admin, indépendant de la langue de Windows, et
  identique à vdd_device.find_device() de l'appli. }
function FindVddInstance(var InstanceId: String): Boolean;
var
  Keys: TArrayOfString;
  I: Integer;
  Ids: String;
begin
  Result := False;
  InstanceId := '';
  if not RegGetSubkeyNames(HKLM, VddEnumKey, Keys) then
    Exit;
  for I := 0 to GetArrayLength(Keys) - 1 do
    if RegQueryMultiStringValue(HKLM, VddEnumKey + '\' + Keys[I], 'HardwareID', Ids)
       and (Pos('root\mttvdd', Lowercase(Ids)) > 0) then
    begin
      InstanceId := 'ROOT\DISPLAY\' + Keys[I];
      Result := True;
      Exit;
    end;
end;

function VddPresent(): Boolean;
var
  Inst: String;
begin
  Result := FindVddInstance(Inst);
  if Result then
    Log('Virtual display device found: ' + Inst)
  else
    Log('No virtual display device (Root\MttVDD)');
end;

{ Lance un programme caché avec les droits de Setup (admin) et attend la fin. -1 = impossible de le lancer. }
function RunHidden(const Exe, Params: String): Integer;
begin
  if not Exec(Exe, Params, ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, Result) then
  begin
    Log(Format('Cannot start %s %s: %s', [Exe, Params, SysErrorMessage(Result)]));
    Result := -1;
  end
  else
    Log(Format('%s %s -> exit code %d', [Exe, Params, Result]));
end;

function RunApp(const Params: String): Integer;
begin
  Result := RunHidden(ExpandConstant('{app}\{#AppExe}'), Params);
end;

{ Termine les processus Name lancés depuis Folder (WMI). Sert à libérer les fichiers du dossier de l'appli : adb.exe reste
  lancé en serveur après la fermeture de l'appli, et l'outil de désinstallation ne sait pas fermer les applis. }
procedure TerminateProcessesIn(const Folder, Name: String);
var
  Locator, Service, Procs, Proc: Variant;
  Prefix, Path: String;
  I: Integer;
begin
  Prefix := Lowercase(AddBackslash(Folder));
  try
    Locator := CreateOleObject('WbemScripting.SWbemLocator');
    Service := Locator.ConnectServer('.', 'root\CIMV2');
    Procs := Service.ExecQuery('SELECT ProcessId, ExecutablePath FROM Win32_Process WHERE Name = ''' + Name + '''');
    for I := 0 to Procs.Count - 1 do
    begin
      Proc := Procs.ItemIndex(I);
      if not VarIsNull(Proc.ExecutablePath) then
      begin
        Path := Proc.ExecutablePath;
        if Pos(Prefix, Lowercase(Path)) = 1 then
        begin
          Log('Terminating ' + Path);
          Proc.Terminate(0);
        end;
      end;
    end;
  except
    Log('Cannot list or stop ' + Name + ': ' + GetExceptionMessage);
  end;
end;

function InitializeSetup(): Boolean;
begin
  DriverPresentAtStart := VddPresent();
  Result := True;
end;

procedure InitializeWizard();
begin
  { Page affichée seulement si le pilote doit être installé, juste avant « Prêt à installer » (spec §8). }
  DriverPage := CreateOutputMsgPage(wpSelectTasks, CustomMessage('DriverPageCaption'),
    CustomMessage('DriverPageDescription'), CustomMessage('DriverPageText'));
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (DriverPage <> nil) and (PageID = DriverPage.ID) and DriverPresentAtStart;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  { Mise à jour : Restart Manager ferme OrizonX.exe (CloseApplications), mais pas le serveur adb, sans fenêtre,
    qui verrouillerait tools\adb.exe. L'appli le relance quand il lui faut. }
  TerminateProcessesIn(AddBackslash(WizardDirValue) + 'tools', 'adb.exe');
  Result := '';
end;

procedure SetupVirtualDisplay();
var
  RC: Integer;
  ByUs: Cardinal;
begin
  if VddPresent() then
  begin
    { Pilote déjà là (installé par nous ou par un autre programme) : on ne crée pas de second périphérique ; on
      écrit les résolutions et on redémarre le périphérique pour qu'il relise le XML. }
    RC := RunApp('--configure-vdd --restart');
    if RC <> 0 then
      Log('Configuring or restarting the existing virtual display failed; it keeps its previous resolutions');
    { Une mise à jour garde la valeur notée par l'installation qui a posé le pilote. }
    if not RegQueryDWordValue(HKLM, OrizonKey, 'VddInstalledByUs', ByUs) then
      RegWriteDWordValue(HKLM, OrizonKey, 'VddInstalledByUs', 0);
  end
  else
  begin
    { XML d'abord : le pilote le lit au démarrage du périphérique, donc pas de redémarrage à prévoir. }
    RC := RunApp('--configure-vdd');
    if RC <> 0 then
      Log('Configuring the virtual display failed; the driver will use its built-in settings');
    RC := RunApp('--install-driver "' + ExpandConstant('{app}\vdd\MttVDD.inf') + '"');
    if RC = 0 then
      RegWriteDWordValue(HKLM, OrizonKey, 'VddInstalledByUs', 1)
    else
    begin
      { L'appli retire le nœud à moitié créé : rien à noter, une prochaine installation réessaiera. }
      RegWriteDWordValue(HKLM, OrizonKey, 'VddInstalledByUs', 0);
      SuppressibleMsgBox(CustomMessage('VddInstallFailed'), mbError, MB_OK, IDOK);
    end;
  end;
  { Droits « Modifier » pour Utilisateurs : l'appli écrit le XML sans droits admin (« Add exact resolution »
    passe par une élévation, mais la position/échelle et les futurs réglages non). }
  if DirExists('{#VddConfigDir}') then
    RunHidden(ExpandConstant('{sys}\icacls.exe'), '"{#VddConfigDir}" /grant *S-1-5-32-545:(OI)(CI)M')
  else
    Log('{#VddConfigDir} does not exist, no ACL to set');
  { Écran virtuel éteint tant qu'aucune tablette n'est connectée (Windows l'allume à l'apparition du pilote ou
    après le redémarrage du périphérique). L'appli refait ce nettoyage à chaque lancement. }
  RunApp('--cleanup');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    SetupVirtualDisplay();
end;

procedure RemoveOurRunValue();
var
  Command: String;
begin
  { « Lancer avec Windows » a pu être activé depuis l'appli après l'installation : on retire la valeur si elle
    lance cette copie d'Orizon X. }
  if RegQueryStringValue(HKCU, RunKey, '{#RunValueName}', Command)
     and (Pos(Lowercase(ExpandConstant('{app}\{#AppExe}')), Lowercase(Command)) > 0) then
    RegDeleteValue(HKCU, RunKey, '{#RunValueName}');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ByUs: Cardinal;
begin
  { usUninstall : avant la suppression des fichiers, donc OrizonX.exe est encore là. }
  if CurUninstallStep <> usUninstall then
    Exit;
  TerminateProcessesIn(ExpandConstant('{app}'), '{#AppExe}');
  TerminateProcessesIn(ExpandConstant('{app}'), 'adb.exe');
  RunApp('--cleanup');
  if RegQueryDWordValue(HKLM, OrizonKey, 'VddInstalledByUs', ByUs) and (ByUs = 1) and VddPresent()
     and not UninstallSilent()
     and (MsgBox(CustomMessage('RemoveVddQuestion'), mbConfirmation, MB_YESNO) = IDYES) then
  begin
    if RunApp('--remove-driver') <> 0 then
      MsgBox(CustomMessage('VddRemoveFailed'), mbError, MB_OK);
  end;
  RemoveOurRunValue();
  { Réglages de l'utilisateur (%APPDATA%\OrizonX) et XML de VDD gardés. }
end;
