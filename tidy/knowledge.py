"""What is this file or folder, and can a beginner delete it?

Everything Tidy shows goes through explain(). It answers in plain words with one of three safety levels:

- SAFE   (green)  junk: caches, temp files, crash reports. Apps and Windows make them again when needed.
- CHOICE (amber)  the person's own things: photos, videos, downloads, games. Only they know if it is still wanted.
- KEEP   (red)    Windows, installed programs and app settings. Deleting by hand breaks things, so Tidy never lets
                  these be ticked. Some come with a button to the proper tool (Apps settings, Storage settings).

Known places are matched by path pattern, the longest match wins. Anything unknown falls back to the zone it lives in:
inside Windows or Program Files -> KEEP, inside the person's own folders -> CHOICE with a description of the file type.
"""
import dataclasses
import fnmatch
import functools
import ntpath
import os
from dataclasses import dataclass

SAFE, CHOICE, KEEP = "safe", "choice", "keep"
LABEL = {SAFE: "Safe to delete", CHOICE: "Your choice", KEEP: "Keep"}
RANK = {SAFE: 0, CHOICE: 1, KEEP: 2}

APPS = ("Open Apps settings", "ms-settings:appsfeatures")
STORAGE = ("Open Storage settings", "ms-settings:storagesense")
TEMPFILES = ("Open Temporary files", "ms-settings:storagepolicies")
RESTORE = ("Open System Protection", "shell:::{BB06C0E4-D293-4f75-8A90-CB05B6477EEE}")


@dataclass(frozen=True)
class Info:
    title: str                  # a short name: "Windows Update downloads"
    what: str                   # what it is, in one or two sentences
    safety: str                 # SAFE, CHOICE or KEEP
    advice: str                 # can it go, and what happens after
    action: tuple = None        # (button text, URI) for the proper tool, if any
    keep_folder: bool = False   # deleting it empties it; the folder itself must stay (Temp folders)
    admin: bool = False         # Windows only lets administrators clean it

    @property
    def label(self):
        return LABEL[self.safety]


def I(title, what, safety, advice, **kw):
    return Info(title, what, safety, advice, **kw)


# ---------------------------------------------------------------- shared explanations
CACHE_ADVICE = "Safe to delete. The app downloads or rebuilds it when needed, so it may feel a little slower the " \
               "first time. Close the app first so nothing is in use."
BROWSER = "Safe to delete. Websites load a little slower the first time after. Your passwords, bookmarks, history " \
          "and logins are NOT stored here and are not touched. Close the browser first for the best result."
SHADER = "Safe to delete. Games and apps build it again; the first start of each game can stutter for a minute."
CRASH = "Safe to delete. These reports only help developers find bugs. Nothing you use depends on them."
TEMP = "Safe to delete. Programs leave these behind. Files still in use are skipped automatically, and Tidy only " \
       "removes files older than a day so nothing that is running right now loses its work."
DRIVER_COPIES = "Usually safe if your PC works well: drivers can be downloaded again from the maker's website. " \
                "Keep it if you may need to reinstall drivers without internet."
APPDATA_ADVICE = "Keep it. Deleting it can sign you out of the app, reset its settings or lose its saved data. If " \
                 "you no longer use the app, uninstall it from Settings > Apps and this usually goes with it."
PROGRAM_ADVICE = "Keep it. Deleting program folders by hand leaves the program half-installed and broken. " \
                 "To remove a program, uninstall it from Settings > Apps."
WINDOWS_ADVICE = "Keep it. Deleting anything here can stop Windows from starting or updating."

# ---------------------------------------------------------------- known places
# Patterns use {win} {sys} {users} {pd} {pf} {pf86}; {home} is any account's folder ({users}\*), {local} and
# {roaming} that account's AppData. "**\x" matches a folder named x anywhere.
# applies: "self" = only this exact folder, "tree" = it and everything inside, "inside" = only things inside it.
KNOWN = [
    # -- the drive and Windows
    ("{win}", "tree", I("Windows", "Windows itself: the system files your PC needs to start and run.", KEEP,
                        WINDOWS_ADVICE, action=STORAGE)),
    ("{win}\\Temp", "tree", I("Windows temporary files", "Temporary files left by Windows and installers.", SAFE,
                              TEMP, keep_folder=True, admin=True)),
    ("{win}\\SoftwareDistribution\\Download", "tree", I(
        "Windows Update downloads", "Update files Windows already downloaded and installed.", SAFE,
        "Safe to delete once updates are installed. If an update is waiting for a restart, restart first; "
        "Windows downloads anything it still needs again.", keep_folder=True, admin=True)),
    ("{win}\\ServiceProfiles\\NetworkService\\AppData\\Local\\Microsoft\\Windows\\DeliveryOptimization", "tree", I(
        "Delivery Optimization cache", "Copies of updates Windows shares with other PCs on your network.", SAFE,
        "Safe to delete. Windows only uses it to speed up updates on other PCs.", keep_folder=True, admin=True)),
    ("{win}\\WinSxS", "tree", I(
        "Windows component store", "Every version of Windows' own parts, kept so updates can be repaired or undone. "
        "It looks huge, but many files are shared with System32, so the real size is smaller than shown.", KEEP,
        "Never delete by hand. To shrink it safely use Settings > Storage > Temporary files > Windows Update "
        "Cleanup.", action=TEMPFILES)),
    ("{win}\\Installer", "tree", I(
        "Windows Installer cache", "Copies of program installers that Windows needs to repair or uninstall programs.",
        KEEP, "Keep it. Without these files many programs can no longer be updated or uninstalled.")),
    ("{win}\\System32", "tree", I("System32", "The core of Windows: drivers, system programs and libraries.", KEEP,
                                  WINDOWS_ADVICE)),
    ("{win}\\SysWOW64", "tree", I("SysWOW64", "Windows' parts for 32-bit programs.", KEEP, WINDOWS_ADVICE)),
    ("{win}\\Fonts", "tree", I("Fonts", "The fonts installed on your PC.", KEEP, WINDOWS_ADVICE)),
    ("{win}\\Prefetch", "tree", I("Prefetch", "A small list Windows keeps so your apps start faster.", KEEP,
                                  "Keep it. It is tiny, and deleting it only makes apps start slower for a while.")),
    ("{win}\\Minidump", "tree", I("Blue screen reports", "Small reports Windows saves after a crash (blue screen).",
                                  SAFE, CRASH, keep_folder=True, admin=True)),
    ("{win}\\MEMORY.DMP", "self", I("Big crash dump", "A full copy of memory Windows saved after a blue screen.",
                                    SAFE, CRASH, admin=True)),
    ("{win}\\LiveKernelReports", "tree", I("Hardware error reports", "Reports Windows saves when a driver (often the "
                                           "graphics driver) stops responding.", SAFE, CRASH, keep_folder=True,
                                           admin=True)),
    ("{win}\\Logs", "tree", I("Windows logs", "Records of what Windows did, used to fix problems.", KEEP,
                              "Keep it. These are small and Windows cleans old ones itself.")),
    ("{sys}\\Windows.old", "tree", I(
        "Previous Windows", "Your old copy of Windows, kept after a big upgrade so you can go back.", KEEP,
        "You can remove it if you are happy with this Windows version, but not by hand: use Settings > Storage > "
        "Temporary files > Previous Windows installation(s). After that you can no longer go back.",
        action=TEMPFILES)),
    ("{sys}\\$Recycle.Bin", "tree", I("Recycle Bin", "Files you deleted earlier. They still take up space until the "
                                      "Recycle Bin is emptied.", SAFE,
                                      "Use the Recycle Bin item on the Junk page: it empties the bin properly.")),
    ("{sys}\\System Volume Information", "tree", I(
        "Restore points", "System Restore snapshots that can take your PC back to an earlier day.", KEEP,
        "Never delete by hand. To use less space, lower the limit in System Protection > Configure.",
        action=RESTORE)),
    ("{sys}\\pagefile.sys", "self", I("Page file", "Extra memory on disk that Windows uses when RAM is full.", KEEP,
                                      "Keep it. Without it apps and games can crash when memory runs out.")),
    ("{sys}\\swapfile.sys", "self", I("Swap file", "Memory on disk used by Store apps.", KEEP,
                                      "Keep it. Windows manages it by itself.")),
    ("{sys}\\hiberfil.sys", "self", I(
        "Hibernation file", "Windows saves your open work here when the PC hibernates. It also makes Fast Startup "
        "work.", KEEP, "Don't delete it. If you never hibernate, an administrator can turn it off with the command "
        "'powercfg /h off', which removes it and Fast Startup together.")),
    ("{sys}\\DumpStack.log.tmp", "self", I("Startup log", "A small file Windows uses while starting.", KEEP,
                                           "Keep it. Windows recreates it on every start.")),
    ("{sys}\\Recovery", "tree", I("Recovery", "Tools that repair Windows when it won't start.", KEEP, WINDOWS_ADVICE)),
    ("{sys}\\$WinREAgent", "tree", I("Recovery update", "Windows' own folder for updating the recovery tools.", KEEP,
                                     "Keep it. Windows removes it itself when the update is done.")),
    ("{sys}\\$SysReset", "tree", I("Reset leftovers", "Logs left after a 'Reset this PC'.", KEEP,
                                   "Keep it unless you know you need the space; Windows protects it.")),
    ("{sys}\\PerfLogs", "tree", I("Performance logs", "Windows' performance reports. Usually empty.", KEEP,
                                  "Keep it. It is a Windows folder and is almost always empty.")),
    ("{sys}\\AMD", "tree", I("AMD driver installer files", "Files unpacked while installing an AMD graphics driver.",
                             SAFE, "Safe to delete. Your driver is already installed; only the unpacked installer "
                             "goes.")),
    ("{sys}\\NVIDIA", "tree", I("NVIDIA driver installer files", "Files unpacked while installing an NVIDIA driver.",
                                SAFE, "Safe to delete. Your driver is already installed; only the unpacked installer "
                                "goes.")),
    ("{sys}\\$GetCurrent", "tree", I("Windows upgrade leftovers", "Files left by the Windows Update Assistant "
                                      "after an upgrade that already finished.", SAFE,
                                      "Safe to delete once the upgrade is done.", admin=True)),
    ("{sys}\\$Windows.~BT", "tree", I("Windows upgrade files", "Files Windows uses while installing a big update.",
                                       KEEP, "Don't delete by hand. Use Settings > Storage > Temporary files > "
                                       "Temporary Windows installation files.", action=TEMPFILES)),
    ("{sys}\\$Windows.~WS", "tree", I("Windows upgrade files", "Files Windows uses while installing a big update.",
                                       KEEP, "Don't delete by hand. Use Settings > Storage > Temporary files > "
                                       "Temporary Windows installation files.", action=TEMPFILES)),
    *[("{sys}\\" + folder, "tree", I(title, what, CHOICE, DRIVER_COPIES)) for folder, title, what in (
        ("eSupport", "ASUS driver backup", "Copies of the drivers and ASUS apps your PC came with. MyASUS uses them "
         "to reinstall drivers."),
        ("SWSetup", "HP driver installers", "Copies of the drivers and HP apps your PC came with."),
        ("Drivers", "Driver installers", "Copies of drivers your PC maker or you saved here."),
        ("Intel", "Intel installer files", "Logs and files left by Intel driver installers."))],
    ("{sys}\\OneDriveTemp", "tree", I("OneDrive temporary files", "OneDrive's working folder.", KEEP,
                                       "Keep it. OneDrive cleans it by itself.")),
    ("{sys}\\inetpub", "tree", I("Web server", "Files of Windows' built-in web server (IIS).", KEEP,
                                  "Keep it. Turn the web server off in Windows Features if you don't use it.")),
    ("{pd}\\NVIDIA Corporation\\Downloader", "tree", I(
        "Old NVIDIA driver downloads", "Driver installers NVIDIA's app downloaded.", SAFE,
        "Safe to delete. Your current driver stays installed.", keep_folder=True, admin=True)),
    # -- programs
    ("{pf}", "self", I("Program Files", "Where installed programs live.", KEEP, PROGRAM_ADVICE, action=APPS)),
    ("{pf86}", "self", I("Program Files (x86)", "Where installed 32-bit programs live.", KEEP, PROGRAM_ADVICE,
                         action=APPS)),
    ("{pf}\\WindowsApps", "tree", I("Store apps", "Apps installed from the Microsoft Store.", KEEP,
                                    "Keep it. Uninstall Store apps from Settings > Apps.", action=APPS)),
    ("{pd}", "self", I("ProgramData", "Settings and data that programs share between all accounts on this PC.", KEEP,
                       APPDATA_ADVICE, action=APPS)),
    ("{pd}\\Package Cache", "tree", I("Installer cache", "Installers kept so programs (like Visual C++ or .NET) can "
                                      "be repaired and uninstalled.", KEEP,
                                      "Keep it. Without it some programs can't be updated or removed.")),
    ("{pd}\\Microsoft\\Windows\\WER", "tree", I("Crash reports (all accounts)", "Reports Windows saves when an app "
                                                "crashes.", SAFE, CRASH, keep_folder=True, admin=True)),
    # -- accounts
    ("{users}", "self", I("Users", "Every account on this PC has its own folder here.", KEEP,
                          "Keep it. Look inside your own account folder to find files you can remove.")),
    ("{users}\\Public", "self", I("Public", "A folder shared by every account on this PC.", KEEP,
                                  "Keep the folder; look inside to choose files.")),
    ("{users}\\Default", "tree", I("New account template", "Windows copies this to make new accounts.", KEEP,
                                   WINDOWS_ADVICE)),
    ("{home}", "self", I("Account folder", "Everything that belongs to one account on this PC.", KEEP,
                         "Keep the folder; open it to choose what to remove.")),
    ("{home}\\Desktop", "self", I("Desktop", "Files on your desktop.", KEEP, "Keep the folder; look inside to choose "
                                  "files.")),
    ("{home}\\Documents", "self", I("Documents", "Your documents. Many games also keep saves and settings here.",
                                    KEEP, "Keep the folder; look inside to choose files.")),
    ("{home}\\Downloads", "self", I("Downloads", "Everything you downloaded from the internet.", KEEP,
                                    "Keep the folder. Old installers and zip files inside are often safe to remove; "
                                    "look inside to choose.")),
    ("{home}\\Pictures", "self", I("Pictures", "Your photos and screenshots.", KEEP, "Keep the folder; look inside to "
                                   "choose files.")),
    ("{home}\\Videos", "self", I("Videos", "Your videos and recordings.", KEEP, "Keep the folder; look inside to "
                                 "choose files.")),
    ("{home}\\Music", "self", I("Music", "Your music.", KEEP, "Keep the folder; look inside to choose files.")),
    ("{home}\\OneDrive*", "self", I(
        "OneDrive", "Files synced with your Microsoft cloud.", KEEP,
        "Keep the folder. Careful inside: deleting a file here also deletes it from OneDrive on all your devices. "
        "To free space but keep the file in the cloud, right-click it and pick 'Free up space'.")),
    ("{home}\\OneDrive*", "inside", I(
        "OneDrive file", "A file synced with your Microsoft cloud.", CHOICE,
        "Deleting it here also deletes it from OneDrive everywhere. To free space but keep it in the cloud, "
        "right-click it in File Explorer and pick 'Free up space'.")),
    ("{local}", "self", I("Local app data", "Where apps keep settings, caches and data for this PC only.", KEEP,
                          APPDATA_ADVICE)),
    ("{roaming}", "self", I("Roaming app data", "Where apps keep settings and data that follow your account.", KEEP,
                            APPDATA_ADVICE)),
    ("{locallow}", "self", I("LocalLow app data", "Where some apps and games keep settings and caches.", KEEP,
                             APPDATA_ADVICE)),
    ("{home}\\AppData", "self", I("AppData", "Hidden folder where apps keep their settings, saves and caches.", KEEP,
                                  APPDATA_ADVICE)),
    ("{home}\\.cache", "tree", I("Developer tool cache", "Downloads kept by developer tools (for example AI models "
                                 "from Hugging Face).", CHOICE,
                                 "Usually safe: tools download it again when needed, which can take a long time for "
                                 "big models.")),
    ("{home}\\.nuget\\packages", "tree", I("NuGet packages", "Code libraries downloaded by Visual Studio / .NET.", SAFE,
                                           "Safe to delete. They download again on the next build.")),
    ("{home}\\.gradle\\caches", "tree", I("Gradle cache", "Libraries downloaded by Android Studio / Gradle.", SAFE,
                                          "Safe to delete. They download again on the next build.")),
    ("{home}\\.vscode", "tree", I("VS Code extensions", "Settings and extensions of Visual Studio Code.", KEEP,
                                  "Keep it. Remove extensions from inside VS Code.")),
    # -- AppData: temp and caches
    ("{local}\\Temp", "tree", I("Your temporary files", "Files programs and installers left behind while working.",
                                SAFE, TEMP, keep_folder=True)),
    ("{local}\\CrashDumps", "tree", I("App crash dumps", "Memory copies saved when an app crashed.", SAFE, CRASH,
                                      keep_folder=True)),
    ("{local}\\Microsoft\\Windows\\WER", "tree", I("Crash reports", "Reports Windows saves when an app crashes.", SAFE,
                                                   CRASH, keep_folder=True)),
    ("{local}\\Microsoft\\Windows\\INetCache", "tree", I("Internet cache", "Web pages saved by Windows' own web "
                                                         "parts.", SAFE, CACHE_ADVICE, keep_folder=True)),
    ("{local}\\Microsoft\\Windows\\Explorer\\thumbcache_*.db", "self", I(
        "Thumbnail cache", "Small pictures File Explorer shows for your photos and videos.", SAFE,
        "Safe to delete. Explorer makes them again when you open the folders.")),
    ("{local}\\D3DSCache", "tree", I("DirectX shader cache", "Graphics data games build to load faster.", SAFE,
                                     SHADER, keep_folder=True)),
    ("{local}\\NVIDIA\\DXCache", "tree", I("NVIDIA shader cache", "Graphics data NVIDIA builds so games load faster.",
                                           SAFE, SHADER, keep_folder=True)),
    ("{local}\\NVIDIA\\GLCache", "tree", I("NVIDIA OpenGL cache", "Graphics data NVIDIA builds so apps load faster.",
                                           SAFE, SHADER, keep_folder=True)),
    ("{local}\\AMD\\DxCache", "tree", I("AMD shader cache", "Graphics data AMD builds so games load faster.", SAFE,
                                        SHADER, keep_folder=True)),
    ("{local}\\AMD\\DxcCache", "tree", I("AMD shader cache", "Graphics data AMD builds so games load faster.", SAFE,
                                         SHADER, keep_folder=True)),
    ("{local}\\AMD\\GLCache", "tree", I("AMD OpenGL cache", "Graphics data AMD builds so apps load faster.", SAFE,
                                        SHADER, keep_folder=True)),
    ("{locallow}\\Intel\\ShaderCache", "tree", I("Intel shader cache", "Graphics data Intel builds so games load "
                                                 "faster.", SAFE, SHADER, keep_folder=True)),
    ("{local}\\npm-cache", "tree", I("npm cache", "Packages downloaded by Node.js tools.", SAFE,
                                     "Safe to delete. They download again when a project needs them.")),
    ("{local}\\pip\\Cache", "tree", I("pip cache", "Python packages downloaded by pip.", SAFE,
                                      "Safe to delete. They download again when needed.")),
    ("{local}\\Yarn\\Cache", "tree", I("Yarn cache", "Packages downloaded by Yarn.", SAFE,
                                       "Safe to delete. They download again when needed.")),
    ("{local}\\Docker", "tree", I("Docker data", "Docker's virtual disk with your containers and images.", KEEP,
                                  "Don't delete by hand. Free space from inside Docker Desktop (Troubleshoot > Clean "
                                  "/ Purge data) or with 'docker system prune'.")),
    ("{local}\\Packages", "tree", I("Store app data", "Settings and data of apps from the Microsoft Store.", KEEP,
                                    APPDATA_ADVICE, action=APPS)),
    ("{local}\\Microsoft\\WindowsApps", "tree", I("App shortcuts", "Tiny links Windows uses to start Store apps.",
                                                  KEEP, "Keep it. These take almost no space.")),
    # -- browsers (cache only: never profiles, cookies or passwords)
    *[(base + "\\User Data\\*\\" + sub, "tree", I(name + " cache", "Copies of web pages and images " + name +
                                                  " saved to load sites faster.", SAFE, BROWSER, keep_folder=True))
      for name, base in (("Chrome", "{local}\\Google\\Chrome"), ("Edge", "{local}\\Microsoft\\Edge"),
                         ("Brave", "{local}\\BraveSoftware\\Brave-Browser"), ("Vivaldi", "{local}\\Vivaldi"))
      for sub in ("Cache", "Code Cache", "GPUCache", "Service Worker\\CacheStorage")],
    ("{roaming}\\Opera Software\\*\\Cache", "tree", I("Opera cache", "Web pages Opera saved to load sites faster.",
                                                      SAFE, BROWSER, keep_folder=True)),
    ("{local}\\Opera Software\\*\\Cache", "tree", I("Opera cache", "Web pages Opera saved to load sites faster.", SAFE,
                                                    BROWSER, keep_folder=True)),
    ("{local}\\Mozilla\\Firefox\\Profiles\\*\\cache2", "tree", I("Firefox cache", "Web pages Firefox saved to load "
                                                                 "sites faster.", SAFE, BROWSER, keep_folder=True)),
    # -- apps
    *[(base + "\\" + sub, "tree", I(name + " cache", "Images and data " + name + " saved to open faster.", SAFE,
                                    CACHE_ADVICE, keep_folder=True))
      for name, base in (("Discord", "{roaming}\\discord"), ("VS Code", "{roaming}\\Code"),
                         ("Slack", "{roaming}\\Slack"), ("Teams", "{roaming}\\Microsoft\\Teams"),
                         ("WhatsApp", "{roaming}\\WhatsApp"))
      for sub in ("Cache", "Code Cache", "GPUCache")],
    ("{roaming}\\Code\\CachedData", "tree", I("VS Code cache", "Data VS Code saved to start faster.", SAFE,
                                              CACHE_ADVICE, keep_folder=True)),
    ("{local}\\Spotify\\Storage", "tree", I("Spotify cache", "Songs Spotify keeps so they start faster. (Songs you "
                                            "downloaded for offline are stored elsewhere.)", SAFE, CACHE_ADVICE,
                                            keep_folder=True)),
    ("{local}\\Steam\\htmlcache", "tree", I("Steam web cache", "Store pages and images Steam saved.", SAFE,
                                            CACHE_ADVICE, keep_folder=True)),
    ("{local}\\EpicGamesLauncher\\Saved\\webcache*", "tree", I("Epic Games web cache", "Store pages Epic saved.",
                                                               SAFE, CACHE_ADVICE)),
    # -- anywhere
    ("**\\steamapps\\common", "self", I("Steam games", "Games installed through Steam.", KEEP,
                                        "Keep the folder. To remove a game, uninstall it in Steam (Library > right-"
                                        "click > Manage > Uninstall).")),
    ("**\\steamapps\\common", "inside", I("Steam game", "A game installed through Steam.", KEEP,
                                          "Don't delete game folders by hand: Steam will think it is still installed. "
                                          "Uninstall it in Steam (Library > right-click > Manage > Uninstall).")),
    ("**\\steamapps\\shadercache", "tree", I("Steam shader cache", "Graphics data Steam games build to run smoother.",
                                             SAFE, SHADER, keep_folder=True)),
    ("**\\steamapps\\downloading", "tree", I("Unfinished Steam downloads", "Game downloads or updates that never "
                                             "finished.", CHOICE, "Usually safe if nothing is downloading in Steam "
                                             "right now. Steam starts the download again if it still needs it.")),
    ("**\\Epic Games", "self", I("Epic Games", "Games installed through the Epic Games Launcher.", KEEP,
                                 "Uninstall games from the Epic Games Launcher, not by deleting folders.")),
    ("**\\node_modules", "tree", I("node_modules", "Code libraries a JavaScript project downloaded.", CHOICE,
                                   "Safe if you don't work on this project right now: running 'npm install' in the "
                                   "project downloads it again.")),
    ("**\\__pycache__", "tree", I("Python cache", "Small speed-up files Python makes next to code.", SAFE,
                                  "Safe to delete. Python makes them again.")),
    ("**\\.git", "tree", I("Git history", "The full history of a code project.", KEEP,
                           "Keep it. Deleting it throws away the project's whole history.")),
]
ANYWHERE_IN = ("user", "other", "appdata")      # "**" patterns never override Windows or Program Files...
GAME_STORES = ("steamapps", "epic games")       # ...except game libraries, which live in Program Files by default


# ---------------------------------------------------------------- file types
TYPES = [
    ({".exe", ".msi", ".msix", ".appx"}, "Program or installer",
     "A program file. In Downloads it is usually an installer you already ran, and the app stays installed if you "
     "delete it."),
    ({".iso", ".img", ".vhd", ".vhdx", ".vmdk"}, "Disk image",
     "A whole disk packed in one file (a Windows/Linux installer or a virtual machine's disk). Often very large."),
    ({".zip", ".rar", ".7z", ".tar", ".gz", ".xz", ".bz2"}, "Archive",
     "A packed folder. If you already unpacked it, this is just a spare copy."),
    ({".mp4", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".webm", ".m4v", ".ts"}, "Video", "A video or recording."),
    ({".jpg", ".jpeg", ".png", ".gif", ".bmp", ".heic", ".webp", ".raw", ".cr2", ".nef", ".arw", ".dng", ".tif",
      ".tiff", ".psd"}, "Picture", "A photo, screenshot or image."),
    ({".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma", ".opus"}, "Audio", "A song, recording or sound."),
    ({".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".odt", ".rtf", ".csv", ".epub"},
     "Document", "A document you or someone else wrote."),
    ({".tmp", ".temp", ".crdownload", ".part", ".partial"}, "Temporary file",
     "A leftover or unfinished download. Usually safe to delete when nothing is downloading."),
    ({".dmp", ".mdmp", ".hdmp"}, "Crash dump", "A memory copy saved when a program crashed. Only developers use it."),
    ({".log", ".etl"}, "Log file", "A record a program wrote about what it did. Only useful for fixing problems."),
    ({".bak", ".old", ".backup"}, "Backup copy", "An older copy of a file kept by a program or by you."),
    ({".dll", ".sys", ".drv", ".ocx", ".pyd", ".so"}, "Program part",
     "A piece of a program. Programs stop working if it's missing."),
    ({".pst", ".ost"}, "Outlook mail", "Your Outlook email, stored on this PC."),
    ({".blend", ".prproj", ".aep", ".veg", ".kdenlive", ".osp"}, "Project file", "A project from a creative app."),
    ({".pak", ".ucas", ".utoc", ".vpk", ".bsa", ".bundle", ".assets"}, "Game data", "Part of a game's data."),
]
SAFE_TYPES = {"Temporary file", "Crash dump"}
KEEP_TYPES = {"Program part"}


def file_type(name):
    ext = os.path.splitext(name)[1].lower()
    for exts, title, what in TYPES:
        if ext in exts:
            return title, what
    return None


# ---------------------------------------------------------------- matching
def _env(name, default):
    return os.environ.get(name) or default


def norm(path):
    """A path in one comparable form: absolute, backslashes, lower case, no trailing slash (except "c:\\")."""
    p = ntpath.normcase(ntpath.normpath(ntpath.abspath(path)))
    return p if len(p) <= 3 else p.rstrip("\\")


def _places():
    sysdrive = _env("SystemDrive", "C:")
    win = _env("SystemRoot", sysdrive + "\\Windows")
    users = ntpath.dirname(_env("USERPROFILE", sysdrive + "\\Users\\user"))
    home = users + "\\*"
    return {"win": win, "sys": sysdrive + "\\", "users": users, "home": home, "pd": _env("ProgramData",
            sysdrive + "\\ProgramData"), "pf": _env("ProgramW6432", _env("ProgramFiles", sysdrive + "\\Program Files")),
            "pf86": _env("ProgramFiles(x86)", sysdrive + "\\Program Files (x86)"), "local": home + "\\AppData\\Local",
            "roaming": home + "\\AppData\\Roaming", "locallow": home + "\\AppData\\LocalLow"}


class _Pattern:
    __slots__ = ("parts", "anywhere", "applies", "info")

    def __init__(self, text, applies, info):
        self.anywhere = text.startswith("**\\")
        text = text[3:] if self.anywhere else norm(text)
        self.parts = [p for p in ntpath.normcase(text).split("\\") if p]
        self.applies, self.info = applies, info

    def match(self, parts):
        """How many path parts this pattern covers (its strength), or 0 when it doesn't apply."""
        n = len(self.parts)
        if self.anywhere:
            for start in range(len(parts) - n, -1, -1):
                if all(fnmatch.fnmatchcase(parts[start + i], p) for i, p in enumerate(self.parts)):
                    return self._fits(len(parts) - start - n, n + 100)
            return 0, 0
        if len(parts) < n or not all(fnmatch.fnmatchcase(parts[i], p) for i, p in enumerate(self.parts)):
            return 0, 0
        return self._fits(len(parts) - n, n)

    def _fits(self, below, strength):
        if self.applies == "self":
            return (strength + 0.5 if below == 0 else 0), below
        if self.applies == "inside":
            return (strength + 0.25 if below > 0 else 0), below
        return strength, below


_cache = {}


def patterns():
    key = tuple(sorted(_places().items()))
    if key not in _cache:
        places = dict(key)
        _cache.clear()
        _cache[key] = [_Pattern(text.format(**places), applies, info) for text, applies, info in KNOWN]
    return _cache[key]


def _parts(path):
    p = norm(path)
    drive, rest = ntpath.splitdrive(p)
    if drive:
        return [drive] + [x for x in rest.split("\\") if x]
    return [x for x in p.split("\\") if x]


def zone(path):
    """Where a path lives: "root" (a drive itself), "system", "programs", "appdata", "user" or "other"."""
    places = _places()
    p = norm(path)
    if len(p) <= 3:
        return "root"

    def under(base):
        b = norm(base)
        return p == b or p.startswith(b + "\\")

    if under(places["win"]) or under(places["pd"]):
        return "system"
    if under(places["pf"]) or under(places["pf86"]):
        return "programs"
    users = norm(places["users"])
    if p.startswith(users + "\\"):
        rest = p[len(users) + 1:].split("\\")
        if len(rest) >= 2 and rest[1] == "appdata":
            return "appdata"
        if rest[0] in ("default", "default user", "all users"):
            return "system"
        return "user"
    sysdrive = norm(places["sys"])
    top = p[len(sysdrive):].split("\\")[0] if p.startswith(sysdrive) else ""
    if top.startswith("$") or top in ("system volume information", "recovery", "boot", "efi", "msocache",
                                      "config.msi", "documents and settings"):
        return "system"
    return "other"


def known(path):
    """The best matching known place for a path, or None."""
    parts = _parts(path)
    where = None
    best, info, depth = 0, None, 0
    for pat in patterns():
        if pat.anywhere:
            where = where or zone(path)
            if where not in ANYWHERE_IN and not (where == "programs" and pat.parts[0] in GAME_STORES):
                continue
        s, below = pat.match(parts)
        if s > best:
            best, info, depth = s, pat.info, below
    if info is not None and depth > 0 and info.keep_folder:
        info = _inner(info)         # only the folder itself must stay; what is inside can go whole
    return info


@functools.lru_cache(maxsize=None)
def _inner(info):
    return dataclasses.replace(info, keep_folder=False)


def explain(path, is_dir=None):
    """Plain-words Info for any path. is_dir=None checks the disk."""
    info = known(path)
    if info is not None:
        return info
    if is_dir is None:
        is_dir = os.path.isdir(path)
    name = ntpath.basename(norm(path)) or path
    where = zone(path)
    if where == "root":
        return I("Drive " + path[:2].upper(), "A whole drive.", KEEP, "Open it to see what uses the space.")
    if where == "system" and _under(path, _places()["pd"]):
        app = norm(path)[len(norm(_places()["pd"])) + 1:].split("\\")[0]
        real = ntpath.normpath(ntpath.abspath(path))[len(norm(_places()["pd"])) + 1:].split("\\")[0]
        return I(real or app, "Data the program '%s' shares between every account on this PC." % (real or app), KEEP,
                 APPDATA_ADVICE, action=APPS)
    if where == "system":
        return I("Part of Windows", "This belongs to Windows or a program that serves the whole PC.", KEEP,
                 WINDOWS_ADVICE)
    if where == "programs":
        prog = _program_name(path)
        return I(prog, "Part of the installed program '%s'." % prog, KEEP, PROGRAM_ADVICE, action=APPS)
    if where == "appdata":
        app = _app_name(path)
        what = "Settings, saves or cache of '%s'." % app if app else "Where apps keep settings, saves and caches."
        if not is_dir:
            t = file_type(name)
            if t and t[0] in SAFE_TYPES:
                return I(t[0], t[1], SAFE, "Safe to delete. Programs don't need these after they're written.")
        return I(app or "App data", what, KEEP, APPDATA_ADVICE)
    if not is_dir:
        t = file_type(name)
        if t:
            title, what = t
            if title in SAFE_TYPES:
                return I(title, what, SAFE, "Safe to delete. Nothing you use depends on it.")
            if title in KEEP_TYPES:
                return I(title, what, KEEP, "Keep it unless you know which program it belongs to and you removed "
                         "that program.")
            if title == "Program or installer" and _in_downloads(path):
                return I("Downloaded installer", what, CHOICE, "Usually safe once the program is installed. You "
                         "can always download a fresh copy later.")
            return I(title, what, CHOICE, "Only you know if you still need it. Open it to check before deleting.")
        if where == "other" and _is_top(path):
            return I("File at the top of the drive", "A file stored directly on the drive.", KEEP,
                     "Keep it unless you put it there yourself; Windows and some programs keep files here.")
        return I("File", "A file Tidy doesn't recognise.", CHOICE, "Only you know if you still need it. Open it to "
                 "check first; when unsure, keep it or move it to the Recycle Bin so you can bring it back.")
    if where == "other" and _is_top(path) and norm(path).startswith(norm(_places()["sys"])):
        return I(name, "A folder at the top of your Windows drive. Some programs install here (for example "
                 "games or developer tools).", CHOICE,
                 "Check Settings > Apps first: if a program installed itself here, uninstall it there instead.",
                 action=APPS)
    return I(name, "A folder of your own files.", CHOICE, "Only you know if you still need it. Open it to look "
             "inside first; when unsure, keep it or use the Recycle Bin so you can bring it back.")


def _program_name(path):
    places = _places()
    p = norm(path)
    for key in ("pf", "pf86"):
        base = norm(places[key])
        if p.startswith(base + "\\"):
            return path[len(base) + 1:].split("\\")[0] or "Program"
    return "Program"


def _app_name(path):
    p = norm(path).split("\\")
    try:
        i = p.index("appdata")
    except ValueError:
        return ""
    rest = ntpath.normpath(ntpath.abspath(path)).split("\\")[i + 2:]     # after AppData\Local
    if not rest:
        return ""
    if rest[0].lower() in ("microsoft", "packages", "programs") and len(rest) > 1:
        return rest[1]
    return rest[0]


def _under(path, base):
    p, b = norm(path), norm(base)
    return p == b or p.startswith(b + "\\")


def _in_downloads(path):
    parts = norm(path).split("\\")
    return "downloads" in parts


def _is_top(path):
    return len(_parts(path)) == 2


def worst(*levels):
    """The strictest of some safety levels."""
    return max(levels, key=RANK.__getitem__) if levels else SAFE
