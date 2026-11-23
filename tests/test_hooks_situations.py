"""Caractérisation des hooks avant leur découpage en modules (étape 8 du plan, « aucun fichier de plus de 1 000 lignes ») :
chaque hook dans les situations qu'il distingue — démarrage dans un projet connu, un dossier vide, un nouveau projet,
reprise, compaction, /clear, réglage faux, messages de l'étape 7, mémoire native trop grosse, mode éco, wiki ; rappel,
« retiens… », commande, avis de l'appli ; fin de tour, compaction, fin de session — avec les tâches de fond qu'il
demande (enregistrées, jamais lancées). Aussi : les noms que hooks, eco, pc et skills exposaient restent tous joignables,
et les remplacements que font les tests et `brain recall` (hooks.bump_hits, hooks.spawn_background) prennent effet.

Lancement : python tests/test_hooks_situations.py   (sortie : « N vérifications OK, M échec(s) »)"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-situations-test-")).resolve()
CODE = Path(__file__).resolve().parent.parent
OK, FAIL = [], []
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD", "BRAIN_IMPL", "BRAIN_PLUS"):
    os.environ.pop(k, None)
os.environ.update(CLAUDE_CONFIG_DIR=str(TMP / "claude"), BRAIN_HOME=str(TMP / "brain"), HOME=str(TMP / "home"),
                  USERPROFILE=str(TMP / "home"), BRAIN_OFFLINE="1", PYTHONHASHSEED="0")
SHOP, EMPTY, NEW = TMP / "boutique", TMP / "dossier-vide", TMP / "nouveau-site"
for d in (SHOP, EMPTY, NEW / "src", TMP / "home", TMP / "claude", TMP / "brain" / "state"):
    d.mkdir(parents=True)
(NEW / "package.json").write_text('{"name": "nouveau-site", "version": "1.0.0"}\n', encoding="utf-8")
(NEW / "src" / "index.js").write_text("exports.total = (a, b) => a + b;\n", encoding="utf-8")
os.chdir(TMP)
sys.path.insert(0, str(CODE))

from brainkit import common, eco, hooks, pc, skills  # noqa: E402
from brainkit.common import GRAPH_FILE, STATE_DIR, read_json, remove_tree  # noqa: E402
from brainkit.store import Brain  # noqa: E402

SPAWN = TMP / "taches.jsonl"
PILOTE = TMP / "pilote.py"
# Lance `brain.py <arguments>` comme Claude Code, mais les tâches de fond demandées sont notées au lieu d'être lancées :
# rien d'autre n'écrit dans le cerveau pendant le test, et on voit ce que chaque hook a demandé.
PILOTE.write_text('''import json, os, runpy, subprocess, sys
CODE, ARGS = sys.argv[1], sys.argv[2:]
real = subprocess.Popen
class Fake:
    pid, returncode = 0, 0
    def poll(self): return 0
    def wait(self, *a, **k): return 0
    def communicate(self, *a, **k): return b"", b""
    def __enter__(self): return self
    def __exit__(self, *a): return False
def popen(cmd, *a, **k):
    args = [str(x) for x in (cmd if isinstance(cmd, (list, tuple)) else [cmd])]
    if any(x.endswith("brain.py") for x in args):
        i = next(i for i, x in enumerate(args) if x.endswith("brain.py"))
        with open(os.environ["SPAWN_LOG"], "a", encoding="utf-8") as fh:
            fh.write(json.dumps(args[i + 1:], ensure_ascii=False) + "\\n")
        return Fake()
    return real(cmd, *a, **k)
subprocess.Popen = popen
sys.argv = [os.path.join(CODE, "brain.py"), *ARGS]
sys.path.insert(0, CODE)
runpy.run_path(os.path.join(CODE, "brain.py"), run_name="__main__")
''', encoding="utf-8")


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-700:]}" if detail else ""))


def hook(event, payload, cwd=SHOP):
    """→ (objet JSON écrit par le hook ou {}, tâches de fond demandées : [[arguments], …])."""
    SPAWN.write_text("", encoding="utf-8")
    env = dict(os.environ, SPAWN_LOG=str(SPAWN))
    r = subprocess.run([sys.executable, "-I", "-S", str(PILOTE), str(CODE), "hook", event],
                       input=json.dumps(payload, ensure_ascii=False).encode(), capture_output=True, env=env,
                       cwd=str(cwd), timeout=180)
    out = r.stdout.decode("utf-8", "replace")
    tasks = [json.loads(x) for x in SPAWN.read_text(encoding="utf-8").splitlines() if x.strip()]
    try:
        obj = json.JSONDecoder().raw_decode(out.lstrip())[0] if out.strip() else {}
    except ValueError:
        obj = {"brut": out + r.stderr.decode("utf-8", "replace")}
    return obj, tasks


def ctx(obj) -> str:
    return (obj.get("hookSpecificOutput") or {}).get("additionalContext") or obj.get("brut", "")


def msg(obj) -> str:
    return obj.get("systemMessage") or ""


def first(tasks):
    return [t[0] for t in tasks if t]


def transcript(name, users):
    lines = []
    for i, u in enumerate(users):
        lines.append({"type": "user", "uuid": f"u{i}", "timestamp": f"2026-11-21T10:0{i}:00.000Z",
                      "message": {"role": "user", "content": u}})
        lines.append({"type": "assistant", "uuid": f"a{i}", "timestamp": f"2026-11-21T10:0{i}:30.000Z",
                      "message": {"id": f"m{i}", "role": "assistant", "model": "x",
                                  "content": [{"type": "text", "text": "ok"}],
                                  "usage": {"input_tokens": 1000, "cache_read_input_tokens": 1000}}})
    p = TMP / "home" / "projects" / "-demo" / f"{name}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n", encoding="utf-8")
    return str(p)


# ------------------------------------------------------------------ 0. les noms d'avant restent joignables
NAMES = {
    "hooks": "CAPTURE_RX COMPACT_ITEMS COMPACT_MAX_AGE COMPACT_MIN_COV COMPACT_MIN_SCORE DIRS_FILE FICHE_CHARS FRIEND_ID "
             "HANDLERS MEM_HEADER NUM_NOISE NUM_VAL OBS_HEADER OBS_HOW OBS_SESSION_CAP PAUSE_MIN_CTX RECALL_RX "
             "REFRESH_EVERY REFRESH_MARK REMEMBER_RX REM_ANAPHORA_RX REM_BLOCK_RX REM_BODY REM_LEAD_RX REM_LINK_RX REM_MAX "
             "REM_OBJECT_RX REM_PRONOUN_RX REM_STATEMENT_RX REM_TITLE STOP_REASON TAIL_BYTES TASK_CUES TODO_PREFIX "
             "WIKI_REASON YEARS _DEADLINE _EMITTED _Later _NOT_A_NAME _NOT_A_ORDER _NOW_VERBS _OTHER_PERSON_RX _PRIVATE_RX "
             "_PRIVATE_TOPICS _Rx _auto_sync _cache_ttl _duree _epoch _key_terms _known_already _mappable _merge_outils "
             "_project_path _recent _remember_one _rule_picks _run _state_file _text_picks _within after_turn "
             "cleanup_states compact_recall config_warning context_alert context_query daily_due diagnose durable_cue emit "
             "garde_due gist idx is_used journal_catchup label last_context last_request load_state memory_line "
             "note_project on_post_compact on_prompt on_session_end on_session_start on_stop outil_reflex overview_lines "
             "pause_alert pc_watch pick_memories private_about_other project_of recall_context recall_query refresh_later "
             "remember_now remember_texts run save_state search skill_reflex spawn_background track_usage "
             "unsaved_durable wiki_start CMD bump_hits bump_used Brain TYPES journal",
    "eco": "ABSENT BACKUP CACHE_CHOICES CACHE_DAYS CACHE_ENVS CACHE_GAIN_NEW CACHE_GAIN_SWITCH CACHE_KEY CACHE_MIN_REQS "
           "CLAUDE_AI DEFAULT_OUT DEFAULT_WIN DENY DESC_CHARS DESC_KEY GIT_TOKENS KEEP_SERVERS KEEP_TOOLS LEVIERS "
           "MEMORY_ENV MEMORY_KEY OUT_KEY OUT_RANGE OWN_PLUGIN PREVIEW_CHARS PROPOSALS RECENT_DAYS SKILLS_FRACTION "
           "SKILLS_KEY STYLE_KEY STYLE_OFF SYNC_KEY TOOL_WEIGHTS UNUSED_DAYS WIN_KEY WIN_RANGE _COMMAND _RETRY _SCANS "
           "_TOOL_NAME _TOOL_USE _UUID _announce _app_connector _attachment _audit _cache_line _changed_since "
           "_commit_once _deferred_in _del _disable _env_value _forget_rules _get _idle_servers _int _k _mcp_count "
           "_memory_lever _n _pct _propose_plugins _protected _prune _put _recent _refs_in _restore _restore_file "
           "_restore_once _same _scan _scan_all _section _server _servers_detail _tok _ttl _unset _val _weight _write "
           "apply_eco apply_plugins apply_report auto_plugins auto_start cache_auto commit current disable "
           "fix_app_connectors give_back installed_plugins notice pose_proposals proposals read_settings refuse run "
           "set_cache settings_path start status summary sync_style synced_plugins take_annonce targets undo "
           "unused_plugins unused_synced wanted_style warnings watch_plugins withdraw",
    "pc": "BACKGROUND BROWSERS CMD_IMAGES EPOCH_FT FAMILIES FAMILY_OF F_APP F_BRAIN F_ORPH F_SESS F_TERM GB GPU_COUNTERS "
          "HISTORY_FILE MB META_CACHE NCPU NOT_SERVERS NO_INHERIT ORPHAN_IMAGES Proc RX_GPU_ENG RX_GPU_PID "
          "RX_LAUNCHER_MCP RX_MCP RX_NODE_MODULES RX_NPX RX_SCOPED RX_SCRIPT RX_SESSION RX_TOOL_USE SHELLS STATE_FILE "
          "TERM_MARK WIN _A _MSX _PDHI _PDHV _PPTS _SPI _US _api _cores _count_tool_uses _current_session _dur _gb "
          "_gpu_open _gpu_read _history_add _lineage _name _own_label _parent _pct _remember_kills _same_process "
          "_session_ids _session_rows _size _transcripts actions analyze app_sessions background_mode candidates_text "
          "children_map clean clean_report cmdline find_orphans ft_to_unix gpu_by_pid history idle_sessions is_session "
          "kill_orphans mcp_reason mcp_usage measure memory plugin_servers report server_sig snapshot spinning_sessions "
          "subtree suspect_line terminate usage_token vm_disk_in_use watch",
    "skills": "AI_SKILLS AS_REF AUTO_MAX_CHARS BLOCK CACHE_FILE CACHE_V CAP_RE CODE_RE CODE_SPAN_RE COPY_MARK DESC_STOP "
              "FILE_RE FM_RE FP_STOP GENERIC_NAME LINK_RE MAP_KEYS MARKERS NAME_RE NEG_RE OFF_VALUES OWN_PLUGIN "
              "PASTE_TAG PLACEHOLDER_RE PLUGINS_FILE QUOTE_RE Query RACY_NS RAW_FILE SKILLS_DIR SLASH_RE STATS_FILE "
              "STRUCT_RE TRIGGERS_KEY UUID_RE _covered _crc _dedupe _dump _enabled _entities _files _inside _like _norm "
              "_plugin_name _read_cache _rebuild _settings _settled _subdirs _tok3 _trigger _unquote _write_cache "
              "auto_block bump call_name check desc_stop fingerprint frontmatter hint_line index literal load_stats "
              "manual match notice overrides parse paste_line pasted_method phrase_groups phrase_hit plugin_roots quoted "
              "record_usage scaffold similar_skill split_desc synced_dirs synced_roots trigger_hit usable usable_phrase "
              "with_triggers time",
}
for name, mod in (("hooks", hooks), ("eco", eco), ("pc", pc), ("skills", skills)):
    missing = []
    for attr in NAMES[name].split():
        try:
            getattr(mod, attr)
        except AttributeError:
            missing.append(attr)
    check(not missing, f"{name} : les {len(NAMES[name].split())} noms d'avant restent joignables", missing)
check(set(hooks.HANDLERS) == {"session-start", "prompt", "stop", "pre-compact", "post-compact", "session-end"},
      "hooks : un gestionnaire par événement de Claude Code", sorted(hooks.HANDLERS))

# ------------------------------------------------------------------ 1. un cerveau avec un projet et des souvenirs
with Brain.edit() as b:
    proj, _ = b.ensure_project(str(SHOP), title="Boutique Shopify", source="map")
    pid = proj["id"]
    b.add("fact", "Transporteur de la boutique", "La livraison de la boutique passe par Colissimo, suivi par mail.",
          project=pid)
    b.add("decision", "Thème de la boutique", "Le thème Dawn est gardé pour la boutique, couleurs vert sapin.",
          project=pid)
    b.add("feedback", "Toujours tutoyer", "Toujours tutoyer les clients dans les mails de la boutique.")
    b.add("fact", "Prix du transport international", "Le transport international coûte 14,90 € par colis.",
          project=pid)
    # assez d'autres souvenirs pour que l'index du démarrage ne les montre pas tous : le rappel a de quoi faire
    for i, (sujet, mot) in enumerate([("bannière", "soldes"), ("newsletter", "abonnés"), ("photos", "lumière"),
                                      ("avis clients", "étoiles"), ("fiscalité", "TVA"), ("stock", "inventaire"),
                                      ("fournisseur", "grossiste"), ("emballage", "carton"), ("retours", "remboursement"),
                                      ("publicité", "campagne"), ("SEO", "mots-clés"), ("paiement", "Stripe"),
                                      ("domaine", "DNS"), ("mentions légales", "CGV"), ("traduction", "anglais"),
                                      ("collection", "été"), ("cadeau", "code promo"), ("vidéo", "tutoriel")]):
        b.add("fact", f"Boutique : {sujet}", f"Pour la boutique, {sujet} : {mot} réglé le {i + 1} du mois.",
              project=pid, importance=4)
    b.add("fact", "Douane des colis hors Europe", "Les colis hors Europe partent avec une déclaration CN23 et DHL "
          "Express ; compter quatre jours ouvrés.", project=pid, importance=1)
check(GRAPH_FILE.exists(), "cerveau d'essai écrit")
TP = transcript("s1", ["configure le thème de la boutique pour la livraison",
                       "désormais utilise toujours pnpm pour ce projet, jamais npm"])
S1 = {"session_id": "s1", "cwd": str(SHOP), "transcript_path": TP}

# ------------------------------------------------------------------ 2. démarrage
o, t = hook("session-start", dict(S1, source="startup"))
text = ctx(o)
check("Boutique Shopify" in text and pid in text, "démarrage dans un projet connu : sa fiche est injectée", text[-500:])
check(text.startswith("# 🧠 Cerveau persistant"), "plugin : les consignes du cerveau ouvrent l'injection", text[:300])
check(["vues", "--fond"] in t and "map" in first(t), "démarrage : carte du projet et vues demandées en arrière-plan", t)
st = read_json(STATE_DIR / "sessions" / "s1.json", {}) or {}
check(st.get("project") == pid and st.get("started") and st.get("injected_at"),
      "démarrage : l'état de la session note le projet et l'heure", st)

o, t = hook("prompt", dict(S1, prompt="comment déclarer en douane un colis hors Europe avec DHL Express ?"))
check("🧠 Souvenirs liés" in ctx(o) and "Douane des colis" in ctx(o), "message : rappel des souvenirs liés", ctx(o))
o, t = hook("prompt", dict(S1, prompt="retiens que le colis part toujours le mardi matin depuis l'entrepôt"))
check("Retenu" in msg(o) and "Déjà enregistré" in ctx(o), "« retiens que… » : enregistré par le hook, et dit",
      (msg(o), ctx(o)))
check(any("mardi matin" in n["title"] for n in Brain.load().nodes.values()), "« retiens que… » : le souvenir existe")
o, t = hook("prompt", dict(S1, prompt="retiens que ma collègue Julie est enceinte"))
check("information privée" in msg(o) and not any("Julie" in n["title"] for n in Brain.load().nodes.values()),
      "« retiens que… » sur la vie privée d'un tiers : écarté, et dit", msg(o))
o, t = hook("prompt", dict(S1, prompt="/compact"))
check(not ctx(o), "commande « / » : aucun rappel", o)
o, t = hook("prompt", dict(S1, prompt="<task-notification>le transporteur de la boutique</task-notification>"))
check("Souvenirs liés" not in ctx(o), "avis de l'appli : aucun rappel", ctx(o))
o, t = hook("prompt", dict(S1, prompt="tu te souviens de ce qu'on avait décidé pour le thème de la boutique ?"))
check("fait appel à un souvenir" in ctx(o) or "Thème de la boutique" in ctx(o), "appel à un souvenir : signalé", ctx(o))

# ------------------------------------------------------------------ 3. fin de tour, compaction
o, t = hook("stop", dict(S1))
check(o.get("decision") == "block" and "pnpm" in o.get("reason", ""), "fin de tour : phrase durable → rappel de mémoriser",
      o)
o, t = hook("stop", dict(S1, stop_hook_active=True))
check(not o, "fin de tour déjà bloquée : jamais deux blocages de suite", o)
o, t = hook("pre-compact", dict(S1))
check(not o and ["vues", "--fond"] in t, "avant compaction : muet, vues demandées", (o, t))
o, t = hook("post-compact", dict(S1, compact_summary="Primary Request: boutique.\n\nCurrent Work: déclaration "
                                                     "en douane CN23 des colis hors Europe avec DHL Express, délai de "
                                                     "quatre jours ouvrés.\n\nOptional Next Step: tester."))
check(not o and (read_json(STATE_DIR / "sessions" / "s1.json", {}) or {}).get("compact_summary"),
      "après compaction : résumé gardé, rien affiché", o)
o, t = hook("session-start", dict(S1, source="compact"))
check("Boutique Shopify" in ctx(o) and "Souvenirs liés au travail en cours" in ctx(o),
      "démarrage après compaction : index et souvenirs du travail en cours", ctx(o)[-600:])
o, t = hook("session-start", dict(S1, source="resume"))
check("Boutique Shopify" not in ctx(o), "reprise : seulement les nouveautés, pas tout l'index", ctx(o)[-300:])
o, t = hook("session-start", dict(S1, source="clear"))
check("Boutique Shopify" in ctx(o), "après /clear : l'index revient", ctx(o)[-300:])
o, t = hook("session-end", dict(S1))
check(not o and ["vues", "--fond"] in t and ["consolidate", "--auto"] in t and ["backup", "--auto"] in t,
      "fin de session : vues, entretien et sauvegarde du jour demandés", t)
o, t = hook("session-end", {"session_id": "s1b", "cwd": str(SHOP)})
check(["consolidate", "--auto"] not in t, "fin de session : l'entretien du jour une seule fois", t)

# ------------------------------------------------------------------ 4. autres dossiers
o, t = hook("session-start", {"session_id": "s2", "cwd": str(EMPTY), "source": "startup"}, cwd=EMPTY)
check("map" not in first(t) and not any(n.get("meta", {}).get("path") == str(EMPTY) for n in Brain.load().projects()),
      "dossier vide : ni projet créé, ni carte", t)
o, t = hook("session-start", {"session_id": "s3", "cwd": str(NEW), "source": "startup"}, cwd=NEW)
check(any(common.norm_path((n.get("meta") or {}).get("path", "")) == common.norm_path(NEW) for n in Brain.load().projects())
      and "map" in first(t), "nouveau projet (package.json) : créé et cartographié en arrière-plan", t)

# ------------------------------------------------------------------ 5. ce qui est dit une fois à l'utilisateur
cfgp = TMP / "brain" / "config.json"
cfg = read_json(cfgp, {}) or {}
cfg.setdefault("recall", {})["max_items"] = "abc"
cfgp.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
o, t = hook("session-start", {"session_id": "s4", "cwd": str(SHOP), "source": "startup"})
check("recall.max_items" in msg(o) and ctx(o), "réglage faux : dit une fois à l'utilisateur, le démarrage continue", msg(o))
o, t = hook("session-start", {"session_id": "s4b", "cwd": str(SHOP), "source": "startup"})
check("recall.max_items" not in msg(o), "réglage faux : pas redit au démarrage suivant", msg(o))
cfg["recall"].pop("max_items")
cfgp.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
common.tell_user("essai", "🩹 message de l'étape 7 (essai)")
mem = TMP / "claude" / "projects" / "-x" / "memory"
mem.mkdir(parents=True)
(mem / "gros.md").write_text("# gros\n" + "x" * 300_000, encoding="utf-8")
o, t = hook("session-start", {"session_id": "s5", "cwd": str(SHOP), "source": "startup"})
check("message de l'étape 7" in msg(o) and "mémoire de Claude Code non importée" in msg(o),
      "messages de l'étape 7 et mémoire native trop grosse : dits à l'utilisateur", msg(o))
o, t = hook("session-start", {"session_id": "s5b", "cwd": str(SHOP), "source": "startup"})
check("message de l'étape 7" not in msg(o), "message de l'étape 7 : dit une seule fois", msg(o))

# ------------------------------------------------------------------ 6. remplacements (tests, `brain recall`)
seen = []
real_bump, real_spawn = hooks.bump_hits, hooks.spawn_background
hooks.bump_hits = lambda ids: seen.append(list(ids))
import contextlib  # noqa: E402
import io  # noqa: E402
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    hooks.on_prompt({"prompt": "le transporteur de la boutique et la livraison", "cwd": str(SHOP), "session_id": None,
                     "simulation": True}, common.load_config())
hooks.bump_hits = real_bump
check(seen and buf.getvalue(), "hooks.bump_hits remplacé (brain recall) : le rappel passe par le remplaçant", seen)
asked = []
hooks.spawn_background = lambda args: asked.append(list(args)) or True
for f in (STATE_DIR / "last_consolidate", STATE_DIR / "last_backup"):
    f.unlink(missing_ok=True)
with contextlib.redirect_stdout(io.StringIO()):
    hooks.on_session_end({"session_id": "s9", "cwd": str(SHOP)}, common.load_config())
hooks.spawn_background = real_spawn
check(["consolidate", "--auto"] in asked and ["vues", "--fond"] in asked,
      "hooks.spawn_background remplacé : la fin de session passe par le remplaçant", asked)

# ------------------------------------------------------------------ 7. wiki
r = subprocess.run([sys.executable, "-I", "-S", str(PILOTE), str(CODE), "wiki", "init", str(TMP / "wiki")],
                   capture_output=True, env=dict(os.environ, SPAWN_LOG=str(SPAWN)), cwd=str(TMP), timeout=300)
check(r.returncode == 0, "wiki init", r.stdout.decode("utf-8", "replace")[-300:] + r.stderr.decode("utf-8", "replace")[-300:])
o, t = hook("session-start", {"session_id": "s6", "cwd": str(SHOP), "source": "startup"})
check("📚 Le cerveau vit dans le wiki" in ctx(o), "démarrage en mode wiki : la ligne du wiki", ctx(o)[-400:])
o, t = hook("session-start", {"session_id": "s7", "cwd": str(TMP / "wiki"), "source": "startup"}, cwd=TMP / "wiki")
check("map" not in first(t), "démarrage dans le dossier du wiki : pas une carte de projet", t)

# ------------------------------------------------------------------ 8. wiki : fin de session (après la 8.32.0)
# Le hook ne garde que ce qui doit être sur le disque avant qu'il rende la main (journal de ce PC, entrée « session » de
# log.md, avant le commit de la synchronisation) ; index.md, la page Cerveau et la carte du coffre (250 à 300 ms à 3 000
# pages) passent à la tâche de fond des vues. Ici, la tâche est notée par le hook, puis lancée à la main.
WIKI = TMP / "wiki"
ident = ["-c", "user.name=Essai", "-c", "user.email=essai" + "@" + "exemple.invalid", "-c", "core.autocrlf=false"]
for args in (["init", "-q", "-b", "main"], [*ident, "add", "-A"], [*ident, "commit", "-qm", "wiki d'essai"]):
    subprocess.run(["git", "-C", str(WIKI), *args], capture_output=True, check=True)


def cli(*args):
    r = subprocess.run([sys.executable, "-I", "-S", str(PILOTE), str(CODE), *args], capture_output=True, cwd=str(SHOP),
                       env=dict(os.environ, SPAWN_LOG=str(SPAWN)), timeout=300)
    return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


def wpage(name):
    p = WIKI / name
    return p.read_text(encoding="utf-8") if p.is_file() else ""


code_, out_ = cli("add", "-t", "todo", "-T", "Relancer le torréfacteur de Shizuoka", "-b", "Avant la fin du mois.")
check(code_ == 0, "mode wiki : un à-faire ajouté pendant la session", out_[-300:])
mark = STATE_DIR / "vues-wiki"
before = {n: wpage(n) for n in ("index.md", "Cerveau.md", "Carte du cerveau.canvas")}
o, t = hook("session-end", {"session_id": "s8", "cwd": str(SHOP), "transcript_path": TP})
check("session |" in wpage("log.md") and "Relancer le torréfacteur" in wpage("log.md"),
      "fin de session en mode wiki : l'entrée « session » de log.md est écrite par le hook lui-même",
      wpage("log.md")[-400:])
check({n: wpage(n) for n in before} == before and mark.is_file() and ["vues", "--fond"] in t,
      "fin de session en mode wiki : index.md, page Cerveau et carte laissés à la tâche des vues (demandée, marque posée)",
      (t, mark.is_file()))
code_, out_ = cli("vues", "--attendre")
check(code_ == 0 and "Relancer le torréfacteur" in wpage("index.md") and "Relancer le torréfacteur" in wpage("Cerveau.md")
      and wpage("Carte du cerveau.canvas") and not mark.exists(),
      "tâche des vues : index.md, page Cerveau et carte du wiki refaits, marque retirée", out_[-300:])
code_, out_ = cli("vues", "--attendre")
check(code_ == 0 and not mark.exists(), "tâche des vues sans fin de session : les pages du wiki ne sont pas refaites")
code_, out_ = cli("add", "-t", "todo", "-T", "Commander les sachets kraft", "-b", "Pour la boutique.")
real_spawn = hooks.spawn_background
hooks.spawn_background = lambda args: False  # aucune tâche de fond possible : le hook refait les pages lui-même
from brainkit import hooks_fin  # noqa: E402
hooks_fin.h.spawn_background = hooks.spawn_background
with contextlib.redirect_stdout(io.StringIO()):
    hooks.on_session_end({"session_id": "s8b", "cwd": str(SHOP)}, common.load_config())
hooks.spawn_background = hooks_fin.h.spawn_background = real_spawn
check("Commander les sachets kraft" in wpage("index.md") and "Commander les sachets kraft" in wpage("Cerveau.md"),
      "fin de session en mode wiki sans tâche de fond possible : les pages refaites dans le hook, comme avant",
      wpage("index.md")[-300:])

print(f"\n{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
if FAIL:
    print(f"(dossier gardé : {TMP})")
elif not remove_tree(TMP, wait=60):
    print(f"(dossier pas effacé : {TMP})")
sys.exit(1 if FAIL else 0)
