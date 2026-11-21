"""PC : mémoire, processeur, carte graphique — qui consomme, combien, et ce qu'on peut libérer (Windows, sans dépendance).

`brain pc` : deux instantanés de tous les processus (NtQuerySystemInformation, aucun handle ouvert), lignes de commande
des seuls processus utiles, compteurs GPU (PDH, noms anglais : marche sur un Windows français), métadonnées des sessions
de l'app Claude. Chaque action proposée est chiffrée (Go, cœurs).
Veille (hooks) : mesure légère au plus toutes les `check_minutes`. Elle ne ferme jamais rien d'elle-même (décision de
l'utilisateur) : elle repère les serveurs MCP dont la session est morte (parent disparu, serveur MCP reconnu) et le dit
en une ligne. `brain pc --clean` les liste ; `brain pc --clean --oui` les ferme. Les sessions Claude, ouvertes ou
archivées, ne sont jamais ralenties ni fermées par la veille. Historique dans state/pc_history.jsonl.
"""
import ctypes
import json
import os
import re
import time
from pathlib import Path

from .common import STATE_DIR, log, read_json, short, write_json

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


# ------------------------------------------------------------------------------------------ le reste
# Analyse des processus (pc_analyse) et rapport chiffré (pc_rapport) : découpés (étape 8 du plan : aucun fichier de
# plus de 1 000 lignes). Les anciens noms restent joignables ici (pc.find_orphans, pc.report…), chargés au
# premier usage.
_PARTS = {
    "pc_analyse": (
        "app_sessions", "_transcripts", "RX_TOOL_USE", "_count_tool_uses", "mcp_usage", "ft_to_unix", "_parent",
        "children_map", "subtree", "RX_NPX", "RX_NODE_MODULES", "RX_SCOPED", "RX_SCRIPT", "server_sig", "RX_MCP",
        "RX_LAUNCHER_MCP", "mcp_reason", "usage_token", "is_session", "_session_ids", "_lineage", "plugin_servers",
        "find_orphans", "kill_orphans", "_own_label", "_session_rows", "_current_session", "analyze", "measure",
    ),
    "pc_rapport": (
        "_gb", "_size", "_pct", "_cores", "_dur", "_name", "idle_sessions", "spinning_sessions", "actions", "report",
        "candidates_text", "clean", "clean_report", "_remember_kills",
    ),
}
_WHERE = {name: part for part, names in _PARTS.items() for name in names}


def __getattr__(name):
    """Nom déplacé dans pc_analyse ou pc_rapport : chargé au premier usage."""
    part = _WHERE.get(name)
    if part is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    return getattr(importlib.import_module(f"{__package__}.{part}"), name)


# ------------------------------------------------------------------------------------------ veille (hooks)
def watch(cfg, force=False) -> str:
    """Mesure légère ; ne ferme RIEN : repère les serveurs MCP orphelins (parent mort) et les propose une fois (une
    ligne) ; apprend leurs signatures pour les reconnaître plus tard ; une autre ligne seulement si le PC est saturé
    ou qu'une session boucle."""
    from .pc_analyse import _parent, analyze, children_map, ft_to_unix, is_session, plugin_servers
    from .pc_rapport import _cores, _gb, _name, idle_sessions, spinning_sessions
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
    suspects = suspect_line(st, [o for o in a["orphans"] if o.get("auto")], pcfg)
    done = []  # la veille ne ferme jamais rien
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
        line = ("🖥️ PC saturé : " + " · ".join(bits) + ". En fin de réponse, propose en une phrase de libérer la RAM "
                "(archiver les sessions inactives avec l'accord de l'utilisateur : outil archive_session) ; "
                "détail chiffré : `brain pc`.")
        st["alerted"] = now
    if suspects:
        line = f"{line}\n{suspects}" if line else suspects
    st.update({"checked": now, "idle_cpu": procs[0].cpu if procs.get(0) else None, "sigs": sigs,
               "prev": {str(pid): [p.create, p.cpu] for pid, p in procs.items() if p.name.lower() == "claude.exe"},
               "last": {"avail": mem["avail"], "total": mem["total"], "load": mem["load"], "sessions": len(a["sessions"]),
                        "idle": len(idle), "idle_ram": sum(s["ram"] for s in idle), "spin": len(spin)}})
    write_json(STATE_FILE, st)
    _history_add({"ts": int(now), "avail": round(mem["avail"] / GB, 2), "total": round(mem["total"] / GB, 1),
                  "load": mem["load"], "commit": round(mem["commit"] / GB, 1),
                  "cpu": None if cpu_total is None else round(cpu_total, 1), "sessions": len(a["sessions"]),
                  "sess_gb": round(sum(s["ram"] for s in a["sessions"]) / GB, 2), "idle": len(idle),
                  "idle_gb": round(sum(s["ram"] for s in idle) / GB, 2), "spin": len(spin), "killed": len(done),
                  "killed_mb": sum(o["ram"] for o in done) // MB, "alert": bool(line)}, pcfg.get("history_days", 14))
    return line


def suspect_line(st, suspects, pcfg) -> str:
    """La ligne qui propose de fermer les serveurs MCP orphelins : dite une fois par suspect (st["proposed"] garde les
    suspects déjà signalés, élagué à ceux encore là). Aucune fermeture. `auto_clean` = « lister automatiquement ». Pure."""
    from .pc_rapport import _size
    if not pcfg.get("auto_clean", True):
        st["proposed"] = []
        return ""
    ids = [f"{o['pid']}:{o.get('since', 0)}" for o in suspects]
    seen = set(st.get("proposed") or [])
    st["proposed"] = ids
    if not suspects or not set(ids) - seen:
        return ""
    ram = sum(o["ram"] for o in suspects)
    return (f"🖥️ {len(suspects)} serveur(s) MCP orphelin(s) trouvé(s) (≈ {_size(ram)}) : dis-le en une phrase, "
            "avec la commande pour les fermer : `brain pc --clean --oui` (liste d'abord : `brain pc --clean`).")


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
         f"Orphelins fermés (sur demande) : {sum(r['killed'] for r in rows)} ({sum(r['killed_mb'] for r in rows)} Mo) · "
         f"alertes : {sum(1 for r in rows if r.get('alert'))}"]
    if cpus:
        L.append(f"CPU moyen entre deux mesures : {sum(cpus) / len(cpus):.1f} % (max {max(cpus):.1f} %)".replace(".", ","))
    L.append("")
    for r in rows[-12:]:
        L.append(f"  {time.strftime('%d/%m %H:%M', time.localtime(r['ts']))}  {r['avail']:>5.1f} Go libres · "
                 f"{r['sessions']:>2} sessions ({r['sess_gb']:.1f} Go) · CPU "
                 f"{'?' if r.get('cpu') is None else r['cpu']} %".replace(".", ","))
    return "\n".join(L)
