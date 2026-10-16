"""PC : mémoire, processeur, carte graphique — qui consomme, combien, et ce qu'on peut libérer (Windows, sans dépendance).

`brain pc` : deux instantanés de tous les processus (NtQuerySystemInformation, aucun handle ouvert), lignes de commande
des seuls processus utiles, compteurs GPU (PDH, noms anglais : marche sur un Windows français), métadonnées des sessions
de l'app Claude. Chaque action proposée est chiffrée (Go, cœurs).
Veille (hooks) : mesure légère au plus toutes les `check_minutes`. Sa seule action automatique : fermer les serveurs MCP
dont la session est morte (parent disparu, signature de serveur connue). Les sessions Claude, ouvertes ou archivées, ne
sont jamais ralenties ni fermées par la veille : mesure et propositions chiffrées seulement (`brain pc --clean` à la
main). Une ligne pour Claude seulement si c'est critique ; historique dans state/pc_history.jsonl.
"""
import ctypes
import glob
import json
import os
import re
import time
from pathlib import Path

from .common import CLAUDE_HOME, STATE_DIR, load_config, log, read_json, short, write_json
from .privacy import mask

WIN = os.name == "nt"
STATE_FILE = STATE_DIR / "pc.json"
HISTORY_FILE = STATE_DIR / "pc_history.jsonl"
META_CACHE = STATE_DIR / "pc_meta.json"
NCPU = os.cpu_count() or 1
GB, MB = 1 << 30, 1 << 20
EPOCH_FT = 116444736000000000  # 1601 → 1970, en centaines de ns
RX_SESSION = re.compile(r"--(?:resume|session-id)[= ]\"?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.I)
CMD_IMAGES = {"claude.exe", "node.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "python.exe", "pythonw.exe", "py.exe",
              "bash.exe", "sh.exe", "uv.exe", "uvx.exe", "bun.exe", "deno.exe"}
# Seules ces images peuvent être fermées comme orphelines (jamais un shell : il peut porter un serveur voulu).
ORPHAN_IMAGES = {"node.exe", "cmd.exe", "python.exe", "pythonw.exe", "uv.exe", "uvx.exe", "bun.exe", "deno.exe", "claude.exe"}
SHELLS = {"bash.exe", "sh.exe", "powershell.exe", "pwsh.exe"}  # enfants d'une session = outils Bash/PowerShell, pas MCP
# Lanceurs génériques : jamais pris pour la signature d'un serveur MCP (un `npx vite` orphelin n'est pas un serveur MCP)
NOT_SERVERS = {"tsx", "ts-node", "node", "npm", "pnpm", "yarn", "bun", "deno", "python", "uv", "pip", "vite", "next",
               "serve", "http-server", "nodemon", "esbuild", "webpack", "tsc", "jest", "vitest", "playwright", "prettier",
               "eslint"}
TERM_MARK = "CLAUDE_DESKTOP_TERMINAL_HOOKS"  # shells du panneau Terminal de l'app

FAMILIES = (
    ("Chrome", ("chrome.exe",)),
    ("Edge / WebView2", ("msedge.exe", "msedgewebview2.exe")),
    ("Firefox", ("firefox.exe",)),
    ("Opera", ("opera.exe",)),
    ("Brave", ("brave.exe",)),
    ("Discord", ("discord.exe",)),
    ("Steam", ("steam.exe", "steamwebhelper.exe", "steamservice.exe")),
    ("EA app", ("eadesktop.exe", "eacefsubprocess.exe", "eabackgroundservice.exe", "ealocalhostsvc.exe")),
    ("Epic Games", ("epicgameslauncher.exe", "epicwebhelper.exe", "epiconlineservicesuserhelper.exe")),
    ("Battle.net", ("battle.net.exe", "battle.net helper.exe")),
    ("Riot", ("riotclientservices.exe", "riotclientux.exe", "riotclientuxrender.exe", "vgtray.exe")),
    ("Ubisoft Connect", ("upc.exe", "uplaywebcore.exe", "ubisoftconnect.exe")),
    ("NVIDIA (app, overlay)", ("nvidia overlay.exe", "nvidia app.exe", "nvidia share.exe", "nvidia web helper.exe",
                               "nvcontainer.exe", "nvsphelper64.exe", "nvdisplay.container.exe", "nvbroadcast.exe")),
    ("AMD Adrenalin", ("radeonsoftware.exe", "amdrsserv.exe", "amdrssrcext.exe", "amdow.exe", "cncmd.exe", "atieclxx.exe")),
    ("Spotify", ("spotify.exe",)),
    ("Teams", ("ms-teams.exe", "msteams.exe", "teams.exe")),
    ("OneDrive", ("onedrive.exe", "onedrive.sync.service.exe")),
    ("WhatsApp", ("whatsapp.exe", "whatsapp.root.exe")),
    ("Telegram", ("telegram.exe",)),
    ("Slack", ("slack.exe",)),
    ("Zoom", ("zoom.exe",)),
    ("Adobe", ("creative cloud.exe", "adobe desktop service.exe", "ccxprocess.exe", "adobeipcbroker.exe", "coresync.exe",
               "acrobat.exe", "acrocef.exe")),
    ("Razer Synapse", ("razer synapse 3.exe", "razer synapse service.exe", "razercentralservice.exe", "razer central.exe")),
    ("Corsair iCUE", ("icue.exe", "corsair.service.exe")),
    ("Logitech G HUB", ("lghub.exe", "lghub_agent.exe", "lghub_system_tray.exe", "lghub_updater.exe")),
    ("Wallpaper Engine", ("wallpaper32.exe", "wallpaper64.exe", "webwallpaper32.exe")),
    ("Overwolf", ("overwolf.exe", "overwolfbrowser.exe", "overwolfhelper.exe", "overwolfhelper64.exe")),
    ("Medal", ("medal.exe",)),
    ("Docker", ("docker desktop.exe", "com.docker.backend.exe", "com.docker.build.exe")),
    ("VS Code", ("code.exe",)),
    ("Cursor", ("cursor.exe",)),
    ("Machine virtuelle (vmmem)", ("vmmem", "vmmem.exe", "vmmemwsa", "vmwp.exe")),
    ("Mémoire compressée (Windows)", ("memory compression",)),
    ("Antivirus Windows", ("msmpeng.exe", "mpdefendercoreservice.exe", "nissrv.exe")),
    ("Bureau Windows", ("explorer.exe", "searchhost.exe", "startmenuexperiencehost.exe", "shellexperiencehost.exe",
                        "textinputhost.exe", "widgets.exe", "widgetservice.exe", "phoneexperiencehost.exe",
                        "searchindexer.exe", "lockapp.exe", "shellhost.exe")),
    ("Windows (services)", ("idle", "system", "registry", "secure system", "smss.exe", "csrss.exe", "wininit.exe",
                            "services.exe", "lsass.exe", "lsaiso.exe", "svchost.exe", "dwm.exe", "fontdrvhost.exe",
                            "winlogon.exe", "spoolsv.exe", "audiodg.exe", "wudfhost.exe", "dllhost.exe", "sihost.exe",
                            "ctfmon.exe", "runtimebroker.exe", "taskhostw.exe", "conhost.exe", "wmiprvse.exe",
                            "dashost.exe", "smartscreen.exe", "securityhealthservice.exe", "securityhealthsystray.exe",
                            "applicationframehost.exe", "backgroundtaskhost.exe", "unsecapp.exe", "taskmgr.exe",
                            "searchprotocolhost.exe", "searchfilterhost.exe", "mousocoreworker.exe", "tiworker.exe",
                            "aggregatorhost.exe", "crossdeviceservice.exe", "wlanext.exe", "sgrmbroker.exe")),
)
FAMILY_OF = {img: label for label, imgs in FAMILIES for img in imgs}
BACKGROUND = {"Discord", "Steam", "EA app", "Epic Games", "Battle.net", "Riot", "Ubisoft Connect", "NVIDIA (app, overlay)",
              "AMD Adrenalin", "Spotify", "Teams", "WhatsApp", "Telegram", "Slack", "Zoom", "Adobe", "Razer Synapse",
              "Corsair iCUE", "Logitech G HUB", "Wallpaper Engine", "Overwolf", "Medal", "Docker"}
BROWSERS = {"Chrome", "Edge / WebView2", "Firefox", "Opera", "Brave"}
NO_INHERIT = {"Windows (services)", "Bureau Windows", "Antivirus Windows"}
F_SESS, F_APP, F_ORPH = "Claude — sessions Code + serveurs MCP", "Claude — app (fenêtre, rendu, aperçus)", "Orphelins"
F_BRAIN = "Cerveau (tâches de fond)"
F_TERM = "Claude — terminaux (panneau Terminal)"


# ------------------------------------------------------------------------------------------ Windows (ctypes)
class _US(ctypes.Structure):
    _fields_ = [("Length", ctypes.c_ushort), ("MaximumLength", ctypes.c_ushort), ("Buffer", ctypes.c_void_p)]


class _SPI(ctypes.Structure):  # SYSTEM_PROCESS_INFORMATION (les champs utiles, dans l'ordre exact)
    _fields_ = [("NextEntryOffset", ctypes.c_ulong), ("NumberOfThreads", ctypes.c_ulong),
                ("WorkingSetPrivateSize", ctypes.c_longlong), ("HardFaultCount", ctypes.c_ulong),
                ("NumberOfThreadsHighWatermark", ctypes.c_ulong), ("CycleTime", ctypes.c_ulonglong),
                ("CreateTime", ctypes.c_longlong), ("UserTime", ctypes.c_longlong), ("KernelTime", ctypes.c_longlong),
                ("ImageName", _US), ("BasePriority", ctypes.c_long), ("UniqueProcessId", ctypes.c_void_p),
                ("InheritedFromUniqueProcessId", ctypes.c_void_p), ("HandleCount", ctypes.c_ulong),
                ("SessionId", ctypes.c_ulong), ("UniqueProcessKey", ctypes.c_void_p), ("PeakVirtualSize", ctypes.c_size_t),
                ("VirtualSize", ctypes.c_size_t), ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivatePageCount", ctypes.c_size_t)]


class _MSX(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


class _PDHV(ctypes.Union):
    _fields_ = [("d", ctypes.c_double), ("ll", ctypes.c_longlong)]


class _PDHI(ctypes.Structure):  # PDH_FMT_COUNTERVALUE_ITEM_W
    _fields_ = [("name", ctypes.c_wchar_p), ("status", ctypes.c_ulong), ("v", _PDHV)]


class _PPTS(ctypes.Structure):  # PROCESS_POWER_THROTTLING_STATE
    _fields_ = [("Version", ctypes.c_ulong), ("ControlMask", ctypes.c_ulong), ("StateMask", ctypes.c_ulong)]


_A = None


def _api():
    global _A
    if _A is None:
        import ctypes.wintypes as wt
        nt, k = ctypes.WinDLL("ntdll"), ctypes.WinDLL("kernel32", use_last_error=True)
        nt.NtQuerySystemInformation.argtypes = [ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong,
                                                ctypes.POINTER(ctypes.c_ulong)]
        nt.NtQuerySystemInformation.restype = ctypes.c_long
        nt.NtQueryInformationProcess.argtypes = [wt.HANDLE, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong,
                                                 ctypes.POINTER(ctypes.c_ulong)]
        nt.NtQueryInformationProcess.restype = ctypes.c_long
        nt.NtQueryInformationFile.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int]
        nt.NtQueryInformationFile.restype = ctypes.c_long
        for name, args, res in (("OpenProcess", [wt.DWORD, wt.BOOL, wt.DWORD], wt.HANDLE),
                                ("CloseHandle", [wt.HANDLE], wt.BOOL),
                                ("TerminateProcess", [wt.HANDLE, wt.UINT], wt.BOOL),
                                ("GetProcessTimes", [wt.HANDLE] + [ctypes.POINTER(ctypes.c_ulonglong)] * 4, wt.BOOL),
                                ("GlobalMemoryStatusEx", [ctypes.c_void_p], wt.BOOL),
                                ("GetCurrentProcess", [], wt.HANDLE),
                                ("SetPriorityClass", [wt.HANDLE, wt.DWORD], wt.BOOL),
                                ("SetProcessInformation", [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD], wt.BOOL),
                                ("CreateFileW", [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD,
                                                 wt.HANDLE], wt.HANDLE)):
            f = getattr(k, name)
            f.argtypes, f.restype = args, res
        _A = (nt, k)
    return _A


class Proc:
    __slots__ = ("pid", "ppid", "name", "create", "cpu", "ws", "private", "pct")

    def __init__(self, pid, ppid, name, create, cpu, ws, private):
        self.pid, self.ppid, self.name, self.create, self.cpu = pid, ppid, name, create, cpu
        self.ws, self.private, self.pct = ws, private, 0.0


def snapshot() -> dict:
    """Tous les processus en un appel système : pid → Proc (RAM privée comme le Gestionnaire des tâches, temps CPU)."""
    nt, _ = _api()
    size = 1 << 21
    for _ in range(8):
        buf, need = ctypes.create_string_buffer(size), ctypes.c_ulong(0)
        status = nt.NtQuerySystemInformation(5, buf, size, ctypes.byref(need)) & 0xFFFFFFFF
        if status == 0xC0000004:  # STATUS_INFO_LENGTH_MISMATCH : la liste a grossi
            size = max(size * 2, need.value + (1 << 16))
            continue
        if status:
            raise OSError(f"NtQuerySystemInformation 0x{status:08X}")
        break
    else:
        raise OSError("NtQuerySystemInformation : tampon trop petit")
    procs, base, off = {}, ctypes.addressof(buf), 0
    while True:
        e = _SPI.from_address(base + off)
        pid = e.UniqueProcessId or 0
        name = (ctypes.wstring_at(e.ImageName.Buffer, e.ImageName.Length // 2) if e.ImageName.Buffer
                else ("Idle" if pid == 0 else "System"))
        procs[pid] = Proc(pid, e.InheritedFromUniqueProcessId or 0, name, e.CreateTime, e.UserTime + e.KernelTime,
                          e.WorkingSetPrivateSize, e.PrivatePageCount)
        if not e.NextEntryOffset:
            break
        off += e.NextEntryOffset
    return procs


def cmdline(pid):
    """Ligne de commande d'un processus (None si inaccessible : processus protégé ou déjà fini)."""
    nt, k = _api()
    h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        need = ctypes.c_ulong(0)
        buf = ctypes.create_string_buffer(8192)
        status = nt.NtQueryInformationProcess(h, 60, buf, len(buf), ctypes.byref(need)) & 0xFFFFFFFF
        if status in (0xC0000004, 0x80000005, 0xC0000023) and need.value:
            buf = ctypes.create_string_buffer(need.value + 64)
            status = nt.NtQueryInformationProcess(h, 60, buf, len(buf), ctypes.byref(need)) & 0xFFFFFFFF
        if status:
            return None
        us = _US.from_buffer(buf)
        return ctypes.wstring_at(us.Buffer, us.Length // 2) if us.Buffer else ""
    finally:
        k.CloseHandle(h)


def memory() -> dict:
    _, k = _api()
    m = _MSX()
    m.dwLength = ctypes.sizeof(m)
    k.GlobalMemoryStatusEx(ctypes.byref(m))
    return {"total": m.ullTotalPhys, "avail": m.ullAvailPhys, "load": m.dwMemoryLoad,
            "commit": m.ullTotalPageFile - m.ullAvailPageFile, "commit_limit": m.ullTotalPageFile}


def _same_process(h, create) -> bool:
    _, k = _api()
    t = [ctypes.c_ulonglong(0) for _ in range(4)]
    return bool(k.GetProcessTimes(h, *[ctypes.byref(x) for x in t])) and t[0].value == create


def terminate(pid, create) -> bool:
    """Ferme un processus, seulement si c'est bien celui mesuré (même date de création : pas un PID réutilisé)."""
    _, k = _api()
    h = k.OpenProcess(0x0001 | 0x1000, False, pid)  # PROCESS_TERMINATE | QUERY_LIMITED
    if not h:
        return False
    try:
        return _same_process(h, create) and bool(k.TerminateProcess(h, 1))
    finally:
        k.CloseHandle(h)


def background_mode() -> None:
    """Tâche de fond du cerveau : CPU, disque et mémoire en priorité basse + EcoQoS (ne gêne jamais un jeu ni l'app)."""
    try:
        if not WIN:
            os.nice(10)
            return
        _, k = _api()
        me = k.GetCurrentProcess()
        k.SetPriorityClass(me, 0x00100000)  # PROCESS_MODE_BACKGROUND_BEGIN
        state = _PPTS(1, 1, 1)  # PROCESS_POWER_THROTTLING_EXECUTION_SPEED activé
        k.SetProcessInformation(me, 4, ctypes.byref(state), ctypes.sizeof(state))  # ProcessPowerThrottling
    except Exception as exc:
        log(f"mode arrière-plan : {exc!r}")


def vm_disk_in_use():
    """Le disque de la machine virtuelle de l'app Claude est-il ouvert (VM en marche) ? None si inconnu ou pas de VM.
    Ouverture « attributs seuls » avec partage total : ne gêne jamais la VM (ni maintenant ni si elle démarre pendant
    l'appel) ; puis la liste des processus qui ont ce fichier ouvert (FileProcessIdsUsingFileInformation)."""
    p = Path(os.environ.get("APPDATA", "")) / "Claude" / "vm_bundles" / "claudevm.bundle" / "rootfs.vhdx"
    if not WIN or not p.exists():
        return None
    nt, k = _api()
    h = k.CreateFileW(str(p), 0x80, 7, None, 3, 0x80, None)  # FILE_READ_ATTRIBUTES, partage lecture+écriture+suppression
    if h in (None, 0, (1 << (8 * ctypes.sizeof(ctypes.c_void_p))) - 1):
        return None
    try:
        iosb, ptr = ctypes.create_string_buffer(16), ctypes.sizeof(ctypes.c_void_p)
        buf = ctypes.create_string_buffer(ptr * 257)
        status = nt.NtQueryInformationFile(h, iosb, buf, len(buf), 47) & 0xFFFFFFFF
        if status not in (0, 0x80000005):  # STATUS_BUFFER_OVERFLOW : liste tronquée, le début suffit
            return None
        n = min(ctypes.c_ulong.from_buffer(buf).value, 256)
        pids = [ctypes.c_size_t.from_buffer(buf, ptr * (i + 1)).value for i in range(n)]
        return any(x != os.getpid() for x in pids)
    finally:
        k.CloseHandle(h)


# ------------------------------------------------------------------------------------------ GPU (PDH)
GPU_COUNTERS = (("util", r"\GPU Engine(*)\Utilization Percentage", 0x200),
                ("vram", r"\GPU Process Memory(*)\Dedicated Usage", 0x400),
                ("adapter", r"\GPU Adapter Memory(*)\Dedicated Usage", 0x400))


def _gpu_open():
    try:
        pdh = ctypes.WinDLL("pdh")
        q = ctypes.c_void_p()
        if pdh.PdhOpenQueryW(None, None, ctypes.byref(q)):
            return None
        cs = {}
        for key, path, fmt in GPU_COUNTERS:
            c = ctypes.c_void_p()
            if pdh.PdhAddEnglishCounterW(q, ctypes.c_wchar_p(path), None, ctypes.byref(c)) == 0:
                cs[key] = (c, fmt)
        pdh.PdhCollectQueryData(q)
        return pdh, q, cs
    except Exception as exc:
        log(f"GPU (ouverture) : {exc!r}")
        return None


def _gpu_read(h) -> dict:
    pdh, q, cs = h
    out = {}
    try:
        pdh.PdhCollectQueryData(q)
        for key, (c, fmt) in cs.items():
            size, count = ctypes.c_ulong(0), ctypes.c_ulong(0)
            if pdh.PdhGetFormattedCounterArrayW(c, fmt, ctypes.byref(size), ctypes.byref(count), None) & 0xFFFFFFFF \
                    != 0x800007D2:  # PDH_MORE_DATA attendu
                continue
            buf = (ctypes.c_byte * size.value)()
            if pdh.PdhGetFormattedCounterArrayW(c, fmt, ctypes.byref(size), ctypes.byref(count), buf):
                continue
            items = ctypes.cast(buf, ctypes.POINTER(_PDHI))
            out[key] = [(items[i].name or "", items[i].v.d if fmt == 0x200 else items[i].v.ll)
                        for i in range(count.value) if items[i].status in (0, 1)]  # données valides seulement
    except Exception as exc:
        log(f"GPU (lecture) : {exc!r}")
    finally:
        pdh.PdhCloseQuery(q)
    return out


RX_GPU_PID, RX_GPU_ENG = re.compile(r"pid_(\d+)_"), re.compile(r"engtype_(.+)$")


def gpu_by_pid(raw) -> dict:
    """Compteurs bruts → utilisation par pid (max des moteurs, comme le Gestionnaire des tâches), VRAM par pid, total."""
    per, tot = {}, {}
    for name, v in raw.get("util", []):
        m, e = RX_GPU_PID.search(name), RX_GPU_ENG.search(name)
        if not m or not 0 <= v <= 100.5:
            continue
        eng = e.group(1) if e else "?"
        d = per.setdefault(int(m.group(1)), {})
        d[eng] = d.get(eng, 0.0) + v
        tot[eng] = tot.get(eng, 0.0) + v
    vram = {}
    for name, v in raw.get("vram", []):
        m = RX_GPU_PID.search(name)
        if m and 0 <= v < 64 * GB:  # l'overlay NVIDIA annonce parfois 700 Go : écarté
            vram[int(m.group(1))] = vram.get(int(m.group(1)), 0) + v
    used = [v for _, v in raw.get("adapter", []) if 0 <= v < 64 * GB]
    return {"util": {pid: min(100.0, max(d.values())) for pid, d in per.items()}, "vram": vram,
            "total": min(100.0, max(tot.values())) if tot else None, "vram_used": max(used) if used else None}


# ------------------------------------------------------------------------------------------ sessions de l'app Claude
def app_sessions() -> dict:
    """cliSessionId → {id local_…, titre, archivée, création, dernière activité} (métadonnées de l'app Claude).
    Cache par taille+date de fichier dans state/pc_meta.json : les fichiers inchangés ne sont pas relus."""
    roots = [Path(os.environ.get("APPDATA", "")) / "Claude" / "claude-code-sessions"]
    roots += [Path(p) / "LocalCache" / "Roaming" / "Claude" / "claude-code-sessions"
              for p in glob.glob(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Packages", "Claude_*"))]
    files = {}
    for root in roots:
        for f in glob.glob(str(root / "*" / "*" / "local_*.json")):
            try:
                stt = os.stat(f)
            except OSError:
                continue
            base = os.path.basename(f)
            prev = files.get(base)
            if prev is None or stt.st_mtime_ns > prev[1].st_mtime_ns:  # doublon APPDATA/MSIX : le plus récent gagne
                files[base] = (f, stt)
    cache = read_json(META_CACHE, {}) or {}
    new, out = {}, {}
    for f, stt in files.values():
        key = f"{stt.st_size}:{stt.st_mtime_ns}"
        row = cache.get(key)
        if not isinstance(row, dict):
            m = read_json(f, None)
            if not isinstance(m, dict) or not m.get("cliSessionId"):
                continue
            row = {"cli": str(m["cliSessionId"]).lower(), "id": m.get("sessionId"), "title": m.get("title") or "",
                   "archived": bool(m.get("isArchived")), "created": (m.get("createdAt") or 0) / 1000,
                   "activity": max(m.get("lastActivityAt") or 0, m.get("lastFocusedAt") or 0) / 1000}
        new[key] = row
        out[row["cli"]] = {"id": row["id"], "title": row["title"], "archived": row["archived"],
                           "created": row["created"], "activity": row["activity"]}
    if new != cache:
        write_json(META_CACHE, new)
    return out


def _transcripts() -> dict:
    out = {}
    try:
        for d in os.scandir(CLAUDE_HOME / "projects"):
            if d.is_dir():
                for f in os.scandir(d.path):
                    if f.name.endswith(".jsonl"):
                        out[f.name[:-6].lower()] = f.stat().st_mtime
    except OSError:
        pass
    return out


RX_TOOL_USE = re.compile(rb'"type":"tool_use","id":"[^"]{1,100}","name":"(mcp__[^"]{1,200})"')


def _count_tool_uses(data, counts) -> None:
    for m in RX_TOOL_USE.finditer(data):
        name = m.group(1).decode("utf-8", "replace")
        server = name[5:name.rfind("__")] if name.rfind("__") > 5 else name[5:]
        counts[server] = counts.get(server, 0) + 1


def mcp_usage(days=7) -> dict:
    """Appels d'outils MCP dans les transcripts des `days` derniers jours : serveur (mcp__<serveur>__) → nombre.
    Lecture par blocs de 1 Mo (pic mémoire ≈ la plus grosse ligne, pas le plus gros fichier)."""
    cut, counts = time.time() - days * 86400, {}
    for dirpath, _, files in os.walk(CLAUDE_HOME / "projects"):
        for fn in files:
            p = os.path.join(dirpath, fn)
            try:
                if not fn.endswith(".jsonl") or os.path.getmtime(p) < cut:
                    continue
                with open(p, "rb") as fh:
                    tail = b""
                    for block in iter(lambda fh=fh: fh.read(1 << 20), b""):
                        data = tail + block
                        i = data.rfind(b"\n") + 1  # on ne coupe jamais au milieu d'une ligne (un tool_use y tient)
                        tail = data[i:]
                        _count_tool_uses(data[:i], counts)
                    _count_tool_uses(tail, counts)
            except OSError:
                continue
    return counts


# ------------------------------------------------------------------------------------------ arbre, familles, orphelins
def ft_to_unix(ft) -> float:
    return (ft - EPOCH_FT) / 1e7


def _parent(p, procs):
    par = procs.get(p.ppid)
    return par if par is not None and par.pid != p.pid and par.create <= p.create else None  # sinon PID réutilisé


def children_map(procs) -> dict:
    kids = {}
    for p in procs.values():
        par = _parent(p, procs)
        if par is not None:
            kids.setdefault(par.pid, []).append(p.pid)
    return kids


def subtree(pid, kids, stop=()) -> list:
    out, stack = [], [pid]
    while stack:
        x = stack.pop()
        out.append(x)
        stack.extend(c for c in kids.get(x, ()) if c not in stop)
    return out


RX_NPX = re.compile(r"\b(?:npx|npx-cli\.js|uvx|bunx|dlx)\"?\s+(?:(?:-y|--yes|--quiet|-q)\s+|"
                    r"(?:--python|--from|--with|--package|-p)[= ]\S+\s+)*\"?(@?[\w.-]+(?:/[\w.-]+)?)", re.I)
RX_NODE_MODULES = re.compile(r"node_modules[\\/]+(?:\.bin[\\/]+\.\.[\\/]+)?(@[\w.-]+[\\/]+[\w.-]+|[\w.-]+)", re.I)
RX_SCOPED = re.compile(r"(@[\w.-]+[\\/][\w.-]+)")
RX_SCRIPT = re.compile(r"([\w.-]+\.(?:pyw?|m?js|cjs|ts))\b", re.I)


def server_sig(cmd):
    """Paquet du serveur MCP lancé par une ligne de commande (npx/uvx, node_modules, @scope/nom), sans version."""
    if not cmd:
        return None
    m, name = RX_NPX.search(cmd), None
    if m and m.group(1).lower() not in ("npm", "-y"):
        name = m.group(1)
    else:
        mods = [x for x in RX_NODE_MODULES.findall(cmd) if x.lower() not in ("npm", ".bin")]
        if mods:
            name = mods[-1]
        else:
            m = RX_SCOPED.search(cmd)
            name = m.group(1) if m else None
    if not name:
        return None
    return re.sub(r"(?<=.)@[\w.^~<>=-]*$", "", name.replace("\\", "/")).lower()


def usage_token(sig) -> str:
    base = sig.split("/")[-1]
    return re.sub(r"^(?:mcp-server-|server-|mcp-)|(?:-mcp-server|-mcp|-server)$", "", base)


def is_session(p, c) -> bool:
    """claude.exe qui est une session Code (ni le process principal de l'app, ni un sous-process Electron --type=)."""
    if p.name.lower() != "claude.exe" or not c or "--type=" in c:
        return False
    lc = c.lower()
    return "stream-json" in lc or "\\claude-code\\" in lc or "\\.local\\bin\\" in lc or bool(RX_SESSION.search(c))


def _session_ids(procs, cmds, roots, meta) -> dict:
    """pid de session → uuid local_… : d'abord via --resume/--session-id, puis en appariant les sessions fraîches
    (sans uuid dans la commande) au createdAt de métadonnées le plus proche (lancement 0–30 s après l'écriture)."""
    out = {}
    for pid in roots:
        m = RX_SESSION.search(cmds.get(pid) or "")
        if m:
            out[pid] = m.group(1).lower()
    used, pairs = set(out.values()), []
    for pid in roots:
        if pid in out:
            continue
        t = ft_to_unix(procs[pid].create)
        for uid, md in meta.items():
            if uid not in used and md.get("created") and -3 <= t - md["created"] <= 30:
                pairs.append((abs(t - md["created"]), pid, uid))
    for _, pid, uid in sorted(pairs):
        if pid not in out and uid not in used:
            out[pid] = uid
            used.add(uid)
    return out


def _lineage(procs) -> set:
    """Ce processus et tous ses ancêtres : jamais fermés (on ne scie pas la branche sur laquelle on est assis)."""
    out, p = set(), procs.get(os.getpid())
    while p is not None and p.pid not in out and len(out) < 64:
        out.add(p.pid)
        p = _parent(p, procs)
    return out


def plugin_servers() -> dict:
    """Signature de serveur MCP → nom du plugin qui le fournit (configs des plugins installés)."""
    bases = [Path(os.environ.get("APPDATA", "")) / "Claude" / "rpm"]
    bases += [Path(p) / "LocalCache" / "Roaming" / "Claude" / "rpm"
              for p in glob.glob(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Packages", "Claude_*"))]
    dirs = {}
    for base in bases:
        for d in glob.glob(str(base / "*" / "*" / "plugin_*")):
            dirs.setdefault(os.path.basename(d), d)
    out = {}
    for d in dirs.values():
        pj = read_json(os.path.join(d, ".claude-plugin", "plugin.json"), None)
        if not isinstance(pj, dict):
            continue
        name = pj.get("name") or os.path.basename(d)
        blocks, ms = [], pj.get("mcpServers")
        if isinstance(ms, str):
            ms = read_json(os.path.join(d, ms), None)
        if isinstance(ms, dict):
            blocks.append(ms)
        mj = read_json(os.path.join(d, ".mcp.json"), None)
        if isinstance(mj, dict):
            blocks.append(mj)
        for block in blocks:
            servers = block.get("mcpServers") if isinstance(block.get("mcpServers"), dict) else block
            if not isinstance(servers, dict):
                continue
            for srv in servers.values():
                if not isinstance(srv, dict) or not isinstance(srv.get("command"), str):
                    continue
                sig = server_sig(" ".join([srv["command"], *(str(a) for a in srv.get("args") or [])]))
                if sig and sig not in NOT_SERVERS:
                    out.setdefault(sig, name)
    return out


def find_orphans(procs, cmds, kids, now, pcfg, sessions=(), known=()) -> list:
    """Processus Claude qui ne servent plus à rien (parent mort, assez anciens). Seul « serveur sans session » est
    fermable automatiquement (auto=True) : serveur MCP identifié (signature connue d'une session vivante ou d'un plugin,
    ou « mcp » dans la commande). Les restes de sessions et les sessions archivées encore en vie ne partent qu'à la
    main (`brain pc --clean`)."""
    min_age = pcfg.get("orphan_min_minutes", 10) * 60
    pats = [x.lower() for x in pcfg.get("orphan_patterns") or []]
    known = {x for x in known if x and x not in NOT_SERVERS}
    mine = _lineage(procs)
    roots = []
    for p in procs.values():
        pid = p.pid
        if not pid or pid in mine or p.name.lower() not in ORPHAN_IMAGES:
            continue
        if _parent(p, procs) is not None or now - ft_to_unix(p.create) < min_age:
            continue
        c = cmds.get(pid) or ""
        lc = c.lower()
        if not lc or "brain.py" in lc:  # illisible → on ne touche pas ; tâches du cerveau → finissent seules
            continue
        if p.name.lower() == "claude.exe":
            if "stream-json" in lc and "--type=" not in lc:
                roots.append((pid, "session sans app"))
        elif server_sig(c) in known or "mcp" in lc:
            roots.append((pid, "serveur sans session"))
        elif any(x in lc for x in pats):
            roots.append((pid, "outil Claude sans parent"))
    for s in sessions:
        if s.get("archived") and s.get("app") and not s.get("current") and s["pid"] not in mine \
                and s.get("idle", 0) >= min_age:
            roots.append((s["pid"], "session archivée encore en vie"))
    out, taken = [], set()
    for pid, kind in roots:
        if pid in taken or pid not in procs:
            continue
        tree = [x for x in subtree(pid, kids) if x not in taken]
        taken.update(tree)
        name = procs[pid].name
        out.append({"pid": pid, "name": name, "kind": kind, "auto": kind == "serveur sans session", "tree": tree,
                    "ram": sum(procs[x].ws for x in tree), "label": short(mask(cmds.get(pid) or name)[0], 90)})
    return out


def kill_orphans(orphans, procs) -> list:
    mine = _lineage(procs)
    done = []
    for o in orphans:
        if mine & set(o["tree"]):  # garde-fou : jamais un processus dont nous dépendons
            continue
        n = sum(1 for pid in o["tree"] if pid in procs and terminate(pid, procs[pid].create))
        if n:
            done.append({**o, "killed": n})
            log(f"pc : orphelin fermé ({o['kind']}) pid {o['pid']} · {n} processus · {o['ram'] // MB} Mo · {o['label']}")
    return done


def _own_label(p, cmds) -> str:
    c = cmds.get(p.pid) or ""
    if "brain.py" in c:
        return F_BRAIN
    if p.name.lower() in ("python.exe", "pythonw.exe", "node.exe"):
        m = RX_SCRIPT.search(c.split(None, 1)[1] if " " in c.strip() else "")
        if m:
            return f"{p.name} ({m.group(1)})"
    return p.name


def _session_rows(procs, cmds, kids, now, roots, cur, meta=None):
    meta = app_sessions() if meta is None else meta
    tx = _transcripts()
    ids = _session_ids(procs, cmds, roots, meta)
    rows = []
    for pid in roots:
        p = procs[pid]
        uid = ids.get(pid)
        md = (meta.get(uid) or {}) if uid else {}
        tree = subtree(pid, kids, stop=roots - {pid})
        if uid:
            last = max(md.get("activity") or 0, tx.get(uid, 0), md.get("created") or 0, ft_to_unix(p.create))
            idle = max(0.0, now - last)
        else:
            idle = 0.0  # session trop fraîche pour être appariée : active, jamais proposée à l'archivage
        rows.append({"pid": pid, "uuid": uid, "id": md.get("id"), "title": md.get("title") or "", "current": pid == cur,
                     "archived": bool(md.get("archived")), "app": bool(md), "idle": idle, "tree": tree,
                     "ram": sum(procs[x].ws for x in tree), "commit": sum(procs[x].private for x in tree),
                     "cpu": sum(procs[x].pct for x in tree), "cpu_self": p.pct, "create": p.create})
    rows.sort(key=lambda s: -s["ram"])
    return rows


def _current_session(procs, roots):
    pid = os.getpid()
    for _ in range(40):
        if pid in roots:
            return pid
        p = procs.get(pid)
        par = _parent(p, procs) if p else None
        if par is None:
            return None
        pid = par.pid
    return None


def analyze(procs, cmds, mem, gpu, now, pcfg, cpu_total, usage=None, known=None, plugins=None, meta=None) -> dict:
    """Tout le diagnostic à partir des mesures. Quasi pure : métadonnées (meta), configs plugins (plugins) et
    signatures connues (known) sont injectables → testable sans toucher au disque."""
    kids = children_map(procs)
    roots = {pid for pid, p in procs.items() if is_session(p, cmds.get(pid))}
    cur = _current_session(procs, roots)
    sessions = _session_rows(procs, cmds, kids, now, roots, cur, meta)
    # Serveurs MCP lancés par chaque session (avant les orphelins : leurs signatures protègent ceux encore attachés)
    servers = {}
    for s in sessions:
        seen = set()
        for child in kids.get(s["pid"], ()):
            if child in roots or procs[child].name.lower() in SHELLS:  # un shell enfant = outil Bash, pas un serveur
                continue
            sub = subtree(child, kids, stop=roots)
            sig = None
            for x in sub:
                sig = server_sig(cmds.get(x))
                if sig:
                    break
            if not sig:
                continue
            d = servers.setdefault(sig, {"sig": sig, "copies": 0, "ram": 0, "commit": 0, "ram_active": 0, "procs": 0})
            ram = sum(procs[x].ws for x in sub)
            d["ram"] += ram
            d["commit"] += sum(procs[x].private for x in sub)
            d["procs"] += len(sub)
            if s["idle"] < pcfg.get("idle_hours", 3) * 3600 or s["current"]:
                d["ram_active"] += ram
            if sig not in seen:
                seen.add(sig)
                d["copies"] += 1
    plugins = plugin_servers() if plugins is None else plugins
    orphans = find_orphans(procs, cmds, kids, now, pcfg, sessions, set(servers) | set(known or ()) | set(plugins))
    fam = {}
    for o in orphans:
        for x in o["tree"]:
            fam[x] = F_ORPH
    for s in sessions:
        for x in s["tree"]:
            fam.setdefault(x, F_SESS)
    terms = []
    for pid in list(procs):
        if pid not in fam and TERM_MARK in (cmds.get(pid) or ""):  # shells du panneau Terminal de l'app
            sub = subtree(pid, kids, stop=set(fam))
            for x in sub:
                fam.setdefault(x, F_TERM)
            terms.extend(sub)
    for p in procs.values():
        if p.name.lower() == "claude.exe" and p.pid not in fam:
            for x in subtree(p.pid, kids, stop=set(fam)):
                fam.setdefault(x, F_APP)
    vm = None
    for p in procs.values():
        if p.pid in fam:
            continue
        label = FAMILY_OF.get(p.name.lower())
        if label is None:
            q, label = p, None
            for _ in range(30):  # hérite de l'ancêtre connu le plus proche (pas de Windows : tout en descend)
                q = _parent(q, procs)
                if q is None:
                    break
                up = fam.get(q.pid) or FAMILY_OF.get(q.name.lower())
                if up and up not in NO_INHERIT:
                    label = up
                    break
            label = label or _own_label(p, cmds)
        if label == "Machine virtuelle (vmmem)" and vm is None:
            vm = vm_disk_in_use()
        fam[p.pid] = label
    if vm:
        fam = {pid: ("Machine virtuelle de l'app Claude (vmmem)" if v == "Machine virtuelle (vmmem)" else v)
               for pid, v in fam.items()}
    gutil, gvram = (gpu or {}).get("util", {}), (gpu or {}).get("vram", {})
    groups = {}
    for pid, label in fam.items():
        p = procs[pid]
        g = groups.setdefault(label, {"label": label, "n": 0, "ram": 0, "cpu": 0.0, "gpu": 0.0, "vram": 0})
        g["n"] += 1
        g["ram"] += p.ws
        g["cpu"] += p.pct
        g["gpu"] = max(g["gpu"], gutil.get(pid, 0.0))
        g["vram"] += gvram.get(pid, 0)
    for d in servers.values():
        plug = plugins.get(d["sig"])
        if plug:
            keys = [k for k in (usage or {}) if k.startswith(f"plugin_{plug}_")]
        else:
            tok = usage_token(d["sig"])
            keys = [k for k in (usage or {}) if len(tok) >= 3 and tok in k.lower()]
        d["uses"] = sum(usage[k] for k in keys) if usage is not None else None
        d["plugin"] = plug
    return {"now": now, "mem": mem, "cpu": cpu_total, "gpu": gpu, "procs": len(procs), "sessions": sessions,
            "orphans": orphans, "groups": sorted(groups.values(), key=lambda g: -g["ram"]),
            "servers": sorted(servers.values(), key=lambda d: -d["ram"]), "fam": fam, "terminals": len(terms)}


def measure(seconds=2.0, cfg=None, with_gpu=True, usage_days=7) -> dict:
    cfg = cfg or load_config()
    g = _gpu_open() if with_gpu else None
    t1, p1 = time.perf_counter(), snapshot()
    time.sleep(max(0.2, seconds))
    t2, procs = time.perf_counter(), snapshot()
    graw = _gpu_read(g) if g else {}
    dt = t2 - t1
    for pid, p in procs.items():
        q = p1.get(pid)
        if pid and q is not None and q.create == p.create:
            p.pct = max(0.0, (p.cpu - q.cpu) / 1e7 / dt / NCPU * 100)
    idle = procs.get(0)
    cpu_total = max(0.0, 100 - (idle.cpu - p1[0].cpu) / 1e7 / dt / NCPU * 100) if idle and 0 in p1 else None
    cmds = {pid: cmdline(pid) for pid, p in procs.items() if p.name.lower() in CMD_IMAGES}
    usage = mcp_usage(usage_days) if usage_days else None
    known = set((read_json(STATE_FILE, {}) or {}).get("sigs") or ())
    a = analyze(procs, cmds, memory(), gpu_by_pid(graw) if graw else None, time.time(), cfg["pc"], cpu_total, usage,
                known=known)
    a["seconds"], a["usage_days"], a["_procs"], a["_cmds"] = seconds, usage_days, procs, cmds
    return a


# ------------------------------------------------------------------------------------------ actions chiffrées
def _gb(b) -> str:
    return f"{b / GB:.1f}".replace(".", ",") + " Go"


def _size(b) -> str:
    return f"{b / MB:.0f} Mo" if b < GB else _gb(b)


def _pct(x) -> str:
    return f"{x:.1f}".replace(".", ",") + " %"


def _cores(pct) -> str:
    return f"{pct / 100 * NCPU:.1f}".replace(".", ",") + " cœur" + ("s" if pct / 100 * NCPU >= 2 else "")


def _dur(s) -> str:
    if s < 3600:
        return f"{s / 60:.0f} min"
    if s < 86400 * 2:
        return f"{s / 3600:.0f} h"
    return f"{s / 86400:.0f} j"


def _name(s) -> str:
    return s["title"] or s["uuid"] or f"pid {s['pid']}"


def idle_sessions(a, pcfg) -> list:
    # seulement les sessions que l'app connaît (app=True) : on ne propose d'archiver que ce qu'elle sait rouvrir
    return [s for s in a["sessions"] if s.get("app") and not s["current"] and not s["archived"]
            and s["idle"] >= pcfg["idle_hours"] * 3600]


def spinning_sessions(a, pcfg) -> list:
    """claude.exe qui brûle du CPU sans aucune activité depuis 15 min (boucle bloquée)."""
    return [s for s in a["sessions"] if s.get("uuid") and s["cpu_self"] / 100 * NCPU >= pcfg["spin_cores"]
            and s["idle"] >= 900]


def actions(a, pcfg) -> list:
    """(Go libérés, % CPU libéré, texte) — du plus gros gain au plus petit."""
    out = []
    idle = idle_sessions(a, pcfg)
    if idle:
        out.append((sum(s["ram"] for s in idle), sum(s["cpu"] for s in idle),
                    f"Archiver {len(idle)} session{'s' * (len(idle) > 1)} Claude inactive{'s' * (len(idle) > 1)} "
                    f"depuis plus de {pcfg['idle_hours']} h : −{_gb(sum(s['ram'] for s in idle))} (l'app arrête leur "
                    "processus et leurs serveurs MCP ; elles restent rouvrables dans « Archivées »)"))
    for s in spinning_sessions(a, pcfg):
        out.append((0 if s in idle else s["ram"], s["cpu_self"],
                    f"Session « {short(_name(s), 50)} » : tourne à vide ({_cores(s['cpu_self'])}, aucune activité "
                    f"depuis {_dur(s['idle'])}) → l'archiver, ou la relancer si elle est bloquée (en attendant : "
                    f"Gestionnaire des tâches, pid {s['pid']} → clic droit → Mode efficacité)"))
    auto = [o for o in a["orphans"] if o.get("auto")]
    man = [o for o in a["orphans"] if not o.get("auto")]
    if auto:
        ram = sum(o["ram"] for o in auto)
        out.append((ram, 0.0, f"{len(auto)} serveur(s) MCP sans session : −{_size(ram)} → la veille les ferme seule "
                              "(ou `brain pc --clean` tout de suite)"))
    if man:
        ram = sum(o["ram"] for o in man)
        kinds = ", ".join(sorted({o["kind"] for o in man}))
        out.append((ram, 0.0, f"{len(man)} processus Claude sans utilité ({kinds}) : −{_size(ram)} → "
                              "`brain pc --clean` (jamais fait automatiquement)"))
    for d in a["servers"]:
        if d["copies"] >= 3 and d["uses"] is not None and d["uses"] <= 2 and d.get("plugin"):
            out.append((d["ram_active"], 0.0,
                        f"Plugin « {d['plugin']} » : lancé dans chaque session ({d['copies']} copies, {_gb(d['ram'])}), "
                        f"{d['uses']} appel(s) en {a.get('usage_days', 7)} j → le désactiver dans claude.ai "
                        f"(Paramètres → plugins) libère ≈ {_size(d['ram'] // max(1, d['copies']))} par session ouverte"))
    groups = {g["label"]: g for g in a["groups"]}
    term = groups.get(F_TERM)
    if term and term["ram"] >= 300 * MB:
        out.append((0, 0.0, f"Panneau Terminal : {_size(term['ram'])} ({term['n']} processus) → fermer les onglets "
                            "Terminal qui ne servent plus"))
    for b in sorted(BROWSERS & set(groups), key=lambda x: -groups[x]["ram"]):
        if groups[b]["ram"] >= 3 * GB:
            out.append((0, 0.0, f"{b} : {_gb(groups[b]['ram'])} ({groups[b]['n']} processus) → activer l'Économiseur "
                                "de mémoire (chrome://settings/performance) et fermer les onglets inutiles"))
    bg = sorted((g for g in a["groups"] if g["label"] in BACKGROUND and g["ram"] >= 200 * MB), key=lambda g: -g["ram"])
    if bg:
        out.append((0, 0.0, "Applis en fond, à fermer quand elles ne servent pas : "
                    + " · ".join(f"{g['label']} {_size(g['ram'])}" for g in bg[:6])))
    return out


def report(seconds=2.0, show_all=False, cfg=None) -> str:
    cfg = cfg or load_config()
    pcfg = cfg["pc"]
    a = measure(seconds, cfg)
    m, L = a["mem"], []
    gpu = a.get("gpu") or {}
    head = (f"RAM : {_gb(m['avail'])} libres sur {_gb(m['total'])} ({m['load']} % utilisés) · mémoire validée "
            f"{_gb(m['commit'])} / {_gb(m['commit_limit'])}")
    if a["cpu"] is not None:
        head += f" · CPU {_pct(a['cpu'])} ({NCPU} threads)"
    if gpu.get("total") is not None:
        head += f" · GPU {_pct(gpu['total'])}"
    L += [f"🖥️ PC — {a['procs']} processus, mesuré sur {seconds:g} s", head, "", "Qui consomme (RAM privée · CPU) :"]
    groups = [g for g in a["groups"] if g["ram"] >= 50 * MB or g["cpu"] >= 1]
    for g in groups[: None if show_all else 12]:
        L.append(f"  {g['label'][:44]:<44} {_size(g['ram']):>8} · {_pct(g['cpu']):>7}"
                 + (f" · {g['n']} proc." if g["n"] > 1 else ""))
    brain = next((g for g in a["groups"] if g["label"] == F_BRAIN), None)
    L.append("  Cerveau : " + (f"{brain['n']} tâche(s) de fond en cours ({_size(brain['ram'])}, priorité basse)" if brain
                               else "aucun processus résident (hooks ≈ 0,1 s par message, rien entre deux)"))
    if a["sessions"]:
        L += ["", f"Sessions Claude ouvertes ({len(a['sessions'])}, {_gb(sum(s['ram'] for s in a['sessions']))} · "
              f"validée {_gb(sum(s['commit'] for s in a['sessions']))}) :"]
        spin = {s["pid"] for s in spinning_sessions(a, pcfg)}
        for s in a["sessions"][: None if show_all else 10]:
            flag = " ⚠ tourne à vide" if s["pid"] in spin else (" (cette session)" if s["current"] else "")
            flag += " · archivée !" if s["archived"] else ""
            L.append(f"  {_size(s['ram']):>8} · CPU {_pct(s['cpu']):>6} · inactive {_dur(s['idle']):>6} · "
                     f"« {short(_name(s), 46)} »{flag}" + (f" {s['id']}" if s["id"] else ""))
        if not show_all and len(a["sessions"]) > 10:
            L.append(f"  … +{len(a['sessions']) - 10} (`brain pc --all`)")
    if a["servers"]:
        L += ["", "Serveurs MCP lancés par les sessions :"]
        for d in a["servers"][:6]:
            uses = "" if d["uses"] is None else f" · {d['uses']} appel(s) en {a['usage_days']} j"
            L.append(f"  {d['plugin'] or d['sig']} : {d['copies']} copie(s), {d['procs']} processus, {_size(d['ram'])} "
                     f"(validée {_size(d.get('commit', 0))}){uses}")
    acts = actions(a, pcfg)
    if acts:
        L += ["", "Ce qu'on peut libérer :"]
        for i, (_, _, text) in enumerate(acts, 1):
            L.append(f"  {i}. {text}")
        claude_gain = sum(g for g, _, t in acts if g)
        if claude_gain:
            L.append(f"  → RAM récupérable côté Claude : ≈ {_gb(claude_gain)}")
    if gpu.get("util") or gpu.get("vram"):
        fam = a["fam"]
        top = sorted(set(gpu.get("util", {})) | set(gpu.get("vram", {})),
                     key=lambda pid: (-gpu["util"].get(pid, 0), -gpu["vram"].get(pid, 0)))[:4]
        procs = a["_procs"]

        def who(pid):
            lab = fam.get(pid) or (procs[pid].name if pid in procs else f"pid {pid}")
            return procs[pid].name if lab in NO_INHERIT and pid in procs else lab

        used = f" · VRAM utilisée {_gb(gpu['vram_used'])}" if gpu.get("vram_used") else ""
        L += ["", f"GPU : {_pct(gpu.get('total') or 0)}{used} — " + " · ".join(
            f"{who(pid)} {_pct(gpu['util'].get(pid, 0))}, {_size(gpu['vram'].get(pid, 0))}" for pid in top)]
    last = read_json(STATE_FILE, {}) or {}
    if last.get("killed_total"):
        L.append(f"Veille : {last['killed_total']} orphelin(s) fermé(s) automatiquement depuis l'installation "
                 f"({_size(last.get('killed_ram_total', 0))}).")
    return "\n".join(L)


def clean(cfg=None) -> str:
    cfg = cfg or load_config()
    a = measure(0.3, cfg, with_gpu=False, usage_days=0)
    if not a["orphans"]:
        return "Aucun orphelin : rien à fermer."
    before = memory()["avail"]
    done = kill_orphans(a["orphans"], a["_procs"])
    time.sleep(1.5)
    after = memory()["avail"]
    _remember_kills(done)
    lines = [f"🧹 {len(done)} orphelin(s) fermé(s) sur {len(a['orphans'])} trouvé(s) :"]
    lines += [f"  {o['kind']} · {o['killed']} processus · {_size(o['ram'])} · {o['label']}" for o in done]
    lines.append(f"RAM libre : {_gb(before)} → {_gb(after)} ({'+' if after >= before else ''}{_size(after - before)})")
    return "\n".join(lines)


def _remember_kills(done) -> None:
    if not done:
        return
    st = read_json(STATE_FILE, {}) or {}
    st["killed_total"] = st.get("killed_total", 0) + len(done)
    st["killed_ram_total"] = st.get("killed_ram_total", 0) + sum(o["ram"] for o in done)
    write_json(STATE_FILE, st)


# ------------------------------------------------------------------------------------------ veille (hooks)
def watch(cfg, force=False) -> str:
    """Mesure légère ; ferme seuls les serveurs MCP orphelins (parent mort) ; apprend leurs signatures pour
    les reconnaître plus tard ; une ligne pour Claude seulement si le PC est saturé ou qu'une session boucle."""
    pcfg = cfg["pc"]
    st = read_json(STATE_FILE, {}) or {}
    now = time.time()
    if not force and now - st.get("checked", 0) < pcfg["check_minutes"] * 60:
        return ""
    procs, mem = snapshot(), memory()
    window = now - st.get("checked", 0)
    prev = st.get("prev") or {}
    for pid, p in procs.items():
        q = prev.get(str(pid))
        if q and q[0] == p.create and 0 < window < 86400:
            p.pct = max(0.0, (p.cpu - q[1]) / 1e7 / window / NCPU * 100)
    cpu_total = None
    if procs.get(0) and st.get("idle_cpu") and 0 < window < 86400:
        cpu_total = max(0.0, 100 - (procs[0].cpu - st["idle_cpu"]) / 1e7 / window / NCPU * 100)
    # Lignes de commande ciblées (veille légère) : toutes les claude.exe, puis les enfants directs des sessions
    # (signatures des serveurs MCP), puis les orphelins candidats (parent mort, assez anciens).
    kids = children_map(procs)
    claude = [pid for pid, p in procs.items() if p.name.lower() == "claude.exe"]
    cmds = {pid: cmdline(pid) for pid in claude}
    roots = {pid for pid in claude if is_session(procs[pid], cmds.get(pid))}
    min_age = pcfg.get("orphan_min_minutes", 10) * 60
    for pid in roots:
        for child in kids.get(pid, ()):
            if child not in cmds and procs[child].name.lower() in CMD_IMAGES:
                cmds[child] = cmdline(child)
    for pid, p in procs.items():
        if pid not in cmds and p.name.lower() in ORPHAN_IMAGES and _parent(p, procs) is None \
                and now - ft_to_unix(p.create) >= min_age:
            cmds[pid] = cmdline(pid)
    # Signatures de serveurs MCP apprises (gardées 30 j) + plugins installés (rescan disque une fois par jour)
    sigs = {s: t for s, t in (st.get("sigs") or {}).items() if now - t < 30 * 86400}
    if not st.get("plugins") or now - st.get("plugins_ts", 0) >= 86400:
        st["plugins"], st["plugins_ts"] = plugin_servers(), now
    a = analyze(procs, cmds, mem, None, now, pcfg, cpu_total, known=set(sigs), plugins=st.get("plugins") or {})
    for d in a["servers"]:
        sigs[d["sig"]] = now  # serveur vu attaché à une session vivante → on saura le reconnaître orphelin
    auto = [o for o in a["orphans"] if o.get("auto")]
    done = kill_orphans(auto, procs) if pcfg.get("auto_clean", True) and auto else []
    idle = idle_sessions(a, pcfg)
    spin = spinning_sessions(a, pcfg) if 300 <= window <= 6 * 3600 else []
    crit = mem["avail"] < pcfg["ram_alert_gb"] * GB or mem["load"] >= pcfg["ram_alert_pct"] \
        or mem["commit"] >= 0.92 * mem["commit_limit"]
    line = ""
    if (crit or spin) and now - st.get("alerted", 0) >= pcfg["alert_repeat_minutes"] * 60:
        bits = []
        if crit:
            bits.append(f"RAM {_gb(mem['avail'])} libres sur {_gb(mem['total'])} ({mem['load']} %)")
            if mem["commit"] >= 0.92 * mem["commit_limit"]:
                bits.append(f"mémoire validée {_gb(mem['commit'])}/{_gb(mem['commit_limit'])} (risque de plantage)")
        if idle:
            bits.append(f"{len(idle)} session(s) Claude inactive(s) > {pcfg['idle_hours']} h = {_gb(sum(s['ram'] for s in idle))}")
        if spin:
            bits.append(f"{len(spin)} tourne(nt) à vide ({_cores(sum(s['cpu_self'] for s in spin))}) : "
                        + ", ".join(f"« {short(_name(s), 40)} »" for s in spin[:3]))
        if done:
            bits.append(f"{len(done)} orphelin(s) déjà fermé(s) (−{_size(sum(o['ram'] for o in done))})")
        line = ("🖥️ PC saturé : " + " · ".join(bits) + ". En fin de réponse, propose en une phrase de libérer la RAM "
                "(archiver les sessions inactives avec l'accord de l'utilisateur : outil archive_session) ; "
                "détail chiffré : `brain pc`.")
        st["alerted"] = now
    st.update({"checked": now, "idle_cpu": procs[0].cpu if procs.get(0) else None, "sigs": sigs,
               "prev": {str(pid): [p.create, p.cpu] for pid, p in procs.items() if p.name.lower() == "claude.exe"},
               "last": {"avail": mem["avail"], "total": mem["total"], "load": mem["load"], "sessions": len(a["sessions"]),
                        "idle": len(idle), "idle_ram": sum(s["ram"] for s in idle), "spin": len(spin)}})
    if done:
        st["killed_total"] = st.get("killed_total", 0) + len(done)
        st["killed_ram_total"] = st.get("killed_ram_total", 0) + sum(o["ram"] for o in done)
    write_json(STATE_FILE, st)
    _history_add({"ts": int(now), "avail": round(mem["avail"] / GB, 2), "total": round(mem["total"] / GB, 1),
                  "load": mem["load"], "commit": round(mem["commit"] / GB, 1),
                  "cpu": None if cpu_total is None else round(cpu_total, 1), "sessions": len(a["sessions"]),
                  "sess_gb": round(sum(s["ram"] for s in a["sessions"]) / GB, 2), "idle": len(idle),
                  "idle_gb": round(sum(s["ram"] for s in idle) / GB, 2), "spin": len(spin), "killed": len(done),
                  "killed_mb": sum(o["ram"] for o in done) // MB, "alert": bool(line)}, pcfg.get("history_days", 14))
    return line


def _history_add(row, keep_days) -> None:
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        if HISTORY_FILE.stat().st_size > 600_000:
            cut = time.time() - keep_days * 86400
            rows = [x for x in HISTORY_FILE.read_text(encoding="utf-8").splitlines()
                    if x.strip() and json.loads(x).get("ts", 0) >= cut]
            HISTORY_FILE.write_text("\n".join(rows) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        log(f"pc historique : {exc!r}")


def history(hours=24) -> str:
    cut, rows = time.time() - hours * 3600, []
    try:
        for x in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
            if x.strip():
                r = json.loads(x)
                if r.get("ts", 0) >= cut:
                    rows.append(r)
    except (OSError, ValueError):
        pass
    if not rows:
        return "Pas encore d'historique : la veille mesure le PC toutes les 10 min pendant que Claude sert."
    free = sorted(r["avail"] for r in rows)
    cpus = [r["cpu"] for r in rows if r.get("cpu") is not None]
    L = [f"Historique PC — {len(rows)} mesures sur {hours:g} h",
         f"RAM libre : min {free[0]:.1f} · médiane {free[len(free) // 2]:.1f} · dernière {rows[-1]['avail']:.1f} Go "
         f"(sur {rows[-1]['total']:.0f})".replace(".", ","),
         f"Sessions Claude : max {max(r['sessions'] for r in rows)} · dernière {rows[-1]['sessions']} "
         f"({rows[-1]['sess_gb']:.1f} Go)".replace(".", ","),
         f"Orphelins fermés seuls : {sum(r['killed'] for r in rows)} ({sum(r['killed_mb'] for r in rows)} Mo) · "
         f"alertes : {sum(1 for r in rows if r.get('alert'))}"]
    if cpus:
        L.append(f"CPU moyen entre deux mesures : {sum(cpus) / len(cpus):.1f} % (max {max(cpus):.1f} %)".replace(".", ","))
    L.append("")
    for r in rows[-12:]:
        L.append(f"  {time.strftime('%d/%m %H:%M', time.localtime(r['ts']))}  {r['avail']:>5.1f} Go libres · "
                 f"{r['sessions']:>2} sessions ({r['sess_gb']:.1f} Go) · CPU "
                 f"{'?' if r.get('cpu') is None else r['cpu']} %".replace(".", ","))
    return "\n".join(L)
