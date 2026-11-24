"""Serveur MCP, étape 16 du plan (serveurs de référence), piloté par stdio comme le lance un client : erreurs conformes
(outil inconnu → erreur JSON-RPC -32602 ; ajout ou modification en partie refusés → « ignoré : … » sans échec),
ressources memoire://{id}, structuredContent et protocole 2026-07-28 (server/discover, _meta par requête) à côté de
`initialize`, sans un caractère de plus dans la liste des outils.

Lancement : python tests/test_serveur_mcp.py   (sortie : « N vérifications OK, M échec(s) »)"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="cerveau-serveur-mcp-test-"))
CODE = Path(__file__).resolve().parent.parent
OK, FAIL = [], []
for k in ("BRAIN_WIKI", "CLAUDE_CODE_REMOTE", "CERVEAU_CLOUD", "BRAIN_IMPL", "BRAIN_PLUS"):
    os.environ.pop(k, None)
os.environ.update(CLAUDE_CONFIG_DIR=str(TMP / "claude"), BRAIN_HOME=str(TMP / "brain"), HOME=str(TMP / "home"),
                  USERPROFILE=str(TMP / "home"), BRAIN_OFFLINE="1")
WORK = TMP / "travail"  # hors de tout projet et de tout wiki
for d in (WORK, TMP / "home", TMP / "claude"):
    d.mkdir(parents=True)
os.chdir(WORK)
sys.path.insert(0, str(CODE))

from brainkit import mcp_server  # noqa: E402


def check(cond, label, detail=""):
    (OK if cond else FAIL).append(label)
    if not cond:
        print(f"✗ {label}" + (f" — {str(detail)[-700:]}" if detail else ""))


NEW = "2026-07-28"
META = {"io.modelcontextprotocol/protocolVersion": NEW, "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {"name": "essai", "version": "1"}}


def serve(*msgs, legacy=True):
    """Un processus `brain mcp` (comme le lance le client) ; legacy : `initialize` d'abord. → {id: réponse}"""
    head = [{"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"}] if legacy else []
    lines = [json.dumps(m, ensure_ascii=False) for m in head + list(msgs)]
    r = subprocess.run([sys.executable, "-I", "-S", str(CODE / "brain.py"), "mcp"], capture_output=True, timeout=300,
                       input=("\n".join(lines) + "\n").encode("utf-8"), cwd=str(WORK), env=dict(os.environ))
    out = {}
    for line in r.stdout.decode("utf-8", "replace").splitlines():
        if line.strip():
            o = json.loads(line)
            out[o.get("id")] = o
    check(r.returncode == 0 and "Traceback" not in r.stderr.decode("utf-8", "replace"), "stdio : le serveur finit "
          "proprement", r.stderr[-400:])
    return out


def call(mid, name, meta=None, **args):
    params = {"name": name, "arguments": args}
    if meta:
        params["_meta"] = meta
    return {"jsonrpc": "2.0", "id": mid, "method": "tools/call", "params": params}


def text_of(resp):
    res = resp.get("result") or {}
    return (res.get("content") or [{}])[0].get("text", ""), res.get("isError")


# ------------------------------------------------------------------ 0. liste des outils : pas un caractère de plus
size = len(json.dumps({"tools": mcp_server.tools({})}, ensure_ascii=False, separators=(",", ":")))
check(size <= 3204, f"liste des 6 outils de la mémoire : {size} caractères (3 204 avant l'étape 16)", size)
check(not any("outputSchema" in t or "annotations" in t for t in mcp_server.TOOLS),
      "aucun outputSchema ni annotation ajoutés aux outils (ils allongeraient chaque session)")

# ------------------------------------------------------------------ 1. erreurs conformes
got = serve(call(1, "memory_add", type="fact", title="Robots.txt de la boutique Shopify",
                 body="Le fichier robots.txt se modifie dans le modèle robots.txt.liquid du thème."),
            call(2, "outil_inexistant"),
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "memory_search", "arguments": [1]}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"arguments": {}}},
            call(5, "memory_search"), call(6, "memory_show", id="souvenir-qui-n-existe-pas"),
            call(7, "memory_update", id="robots-txt-de-la-boutique-shopify"),
            call(8, "memory_add", type="fact", title="Robots.txt de la boutique Shopify",
                 body="Le fichier robots.txt se modifie dans le modèle robots.txt.liquid du thème.", due="demain",
                 keys="seo crawl", commun="non"),
            call(9, "memory_add", type="todo", title="Relancer le fournisseur de cartons", body="Avant vendredi."),
            call(10, "memory_update", id="relancer-le-fournisseur-de-cartons", append="Relancé par courriel.",
                 done=True, archive=True),
            call(11, "memory_update", id="robots-txt-de-la-boutique-shopify", append="Vérifié en novembre.",
                 done=True),
            call(12, "memory_show", id="relancer-le-fournisseur-de-cartons"))
text, err = text_of(got.get(1, {}))
check(err is False and "✓ mémorisé `robots-txt-de-la-boutique-shopify`" in text, "memory_add : souvenir créé", text)
e = got.get(2, {}).get("error") or {}
check(e.get("code") == -32602 and "outil inconnu : outil_inexistant" in e.get("message", "")
      and "memory_search" in e.get("message", "") and "result" not in got.get(2, {}),
      "outil inconnu : erreur JSON-RPC -32602 (pas un résultat isError), avec la liste des outils, en français",
      got.get(2))
for mid, want in ((3, "« arguments » : objet JSON attendu"), (4, "nom d'outil manquant")):
    e = got.get(mid, {}).get("error") or {}
    check(e.get("code") == -32602 and want in e.get("message", ""), f"requête malformée : -32602 (« {want} »)",
          got.get(mid))
for mid, want in ((5, "argument manquant : « query »"), (6, "introuvable"), (7, "rien à modifier")):
    text, err = text_of(got.get(mid, {}))
    check(err is True and text.startswith("✗ ") and want in text,
          f"échec d'un outil : résultat isError, préfixe stable « ✗ » (« {want} »)", got.get(mid))
text, err = text_of(got.get(8, {}))
check(err is False and "≈ déjà connu → complété dans `robots-txt-de-la-boutique-shopify`" in text
      and "ignoré : nouveau souvenir — déjà connu" in text and "non appliqués : due, keys, commun" in text
      and "--force" not in text,
      "memory_add d'un fait déjà connu : complété, et ce qui n'est pas appliqué est dit (« ignoré : … »), sans échec ni "
      "option --force que le serveur n'a pas", text)
text, err = text_of(got.get(10, {}))
check(err is False and "✓ modifié" in text and "✓ terminé" in text
      and "ignoré : archive — avec done, seul done est appliqué" in text,
      "memory_update append + done + archive : l'ajout puis done appliqués, archive dite ignorée", text)
text, err = text_of(got.get(11, {}))
check(err is False and "✓ modifié" in text and "ignoré : done — `robots-txt-de-la-boutique-shopify` n'est pas un "
      "à-faire" in text, "memory_update append + done sur un fait : l'ajout fait, done dit ignoré, sans échec", text)
text, err = text_of(got.get(12, {}))
check("Relancé par courriel." in text and "archivé" in text,
      "l'ajout demandé avec done est bien dans l'à-faire terminé (avant : perdu sans un mot)", text)

# ------------------------------------------------------------------ 2. ressources memoire://{id}
URI = "memoire://robots-txt-de-la-boutique-shopify"
got = serve({"jsonrpc": "2.0", "id": 1, "method": "resources/templates/list"},
            {"jsonrpc": "2.0", "id": 2, "method": "resources/read", "params": {"uri": URI}},
            {"jsonrpc": "2.0", "id": 3, "method": "resources/read", "params": {"uri": "memoire://zzz-inconnu"}},
            {"jsonrpc": "2.0", "id": 4, "method": "resources/read", "params": {"uri": "file:///etc/passwd"}},
            {"jsonrpc": "2.0", "id": 5, "method": "resources/read", "params": {}},
            {"jsonrpc": "2.0", "id": 6, "method": "resources/list"},
            call(7, "memory_show", id="robots-txt-de-la-boutique-shopify"))
caps = (got.get(0, {}).get("result") or {}).get("capabilities") or {}
check("resources" in caps and "tools" in caps and "prompts" in caps, "initialize : capacité resources annoncée", caps)
tpl = (got.get(1, {}).get("result") or {}).get("resourceTemplates") or []
check(len(tpl) == 1 and tpl[0].get("uriTemplate") == "memoire://{id}" and "souvenir" in tpl[0].get("description", "")
      and tpl[0].get("name"), "resources/templates/list : un modèle memoire://{id}, décrit en français", tpl)
contents = (got.get(2, {}).get("result") or {}).get("contents") or []
shown, _ = text_of(got.get(7, {}))
seen = re.compile(r"montré \d+×")  # chaque lecture compte : le compteur avance d'une lecture à l'autre
check(len(contents) == 1 and contents[0].get("uri") == URI and contents[0].get("mimeType") == "text/plain"
      and seen.sub("", contents[0].get("text", "")) == seen.sub("", shown) and "robots.txt.liquid" in shown,
      "resources/read memoire://<id> : le même texte que memory_show", (contents, shown))
e = got.get(3, {}).get("error") or {}
check(e.get("code") == -32002 and "ressource introuvable" in e.get("message", "")
      and (e.get("data") or {}).get("uri") == "memoire://zzz-inconnu",
      "souvenir inconnu (protocole ≤ 2025-11-25) : erreur -32002, avec l'uri, jamais une liste vide", got.get(3))
e = got.get(4, {}).get("error") or {}
check(e.get("code") == -32002 and "memoire://<id>" in e.get("message", ""), "autre schéma qu'memoire:// : introuvable, "
      "rien d'autre n'est lu", got.get(4))
check((got.get(5, {}).get("error") or {}).get("code") == -32602, "resources/read sans uri : -32602", got.get(5))
check((got.get(6, {}).get("result") or {}).get("resources") == [], "resources/list : vide (rien de lourd)", got.get(6))
big = "\n".join(f"- Ligne {i} des notes : " + "x" * 60 for i in range(300))
got = serve(call(1, "memory_add", type="reference", title="Notes très longues du salon", body=big),
            {"jsonrpc": "2.0", "id": 2, "method": "resources/read",
             "params": {"uri": "memoire://notes-tres-longues-du-salon"}})
long_text = ((got.get(2, {}).get("result") or {}).get("contents") or [{}])[0].get("text", "")
check(0 < len(long_text) <= 8000 + 200 and "page: 2" in long_text and "memory_show" in long_text,
      "un long souvenir lu en ressource : borné comme les outils (mcp.max_car), la fin dit comment lire la suite",
      len(long_text))

# ------------------------------------------------------------------ 3. structuredContent et protocole 2026-07-28
got = serve({"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": META}},
            {"jsonrpc": "2.0", "id": 2, "method": "server/discover",
             "params": {"_meta": {**META, "io.modelcontextprotocol/protocolVersion": "1900-01-01"}}},
            {"jsonrpc": "2.0", "id": 3, "method": "server/discover", "params": {}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {"_meta": META}},
            call(5, "memory_search", META, query="robots shopify"),
            {"jsonrpc": "2.0", "id": 6, "method": "resources/read",
             "params": {"uri": "memoire://zzz-inconnu", "_meta": META}},
            call(7, "outil_inexistant", META),
            {"jsonrpc": "2.0", "id": 8, "method": "tools/list",
             "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": NEW}}},
            {"jsonrpc": "2.0", "id": 9, "method": "resources/read", "params": {"uri": URI, "_meta": META}},
            call(10, "memory_add", META, type="fact", title="Robots.txt de la boutique Shopify",
                 body="Le fichier robots.txt se modifie dans le modèle robots.txt.liquid du thème.", due="demain"),
            legacy=False)
d = got.get(1, {}).get("result") or {}
check(d.get("resultType") == "complete" and d.get("supportedVersions") == [NEW]
      and {"tools", "prompts", "resources"} <= set(d.get("capabilities") or {})
      and (d.get("_meta") or {}).get("io.modelcontextprotocol/serverInfo", {}).get("name") == "cerveau"
      and d.get("instructions") and isinstance(d.get("ttlMs"), int) and d["ttlMs"] >= 0
      and d.get("cacheScope") in ("public", "private"),
      "server/discover (2026-07-28) : versions, capacités, serverInfo dans _meta, resultType, indications de cache", d)
e = got.get(2, {}).get("error") or {}
check(e.get("code") == -32022 and (e.get("data") or {}).get("supported") == [NEW]
      and (e.get("data") or {}).get("requested") == "1900-01-01" and "non prise en charge" in e.get("message", ""),
      "version inconnue dans _meta : -32022 avec les versions prises en charge (UnsupportedProtocolVersionError)", e)
check((got.get(3, {}).get("error") or {}).get("code") == -32602, "server/discover sans _meta : -32602 (champ requis)",
      got.get(3))
lst = got.get(4, {}).get("result") or {}
check([t["name"] for t in lst.get("tools", [])] == [t["name"] for t in mcp_server.tools({})]
      and lst.get("resultType") == "complete" and lst.get("cacheScope") == "public" and "ttlMs" in lst,
      "tools/list sans initialize (2026-07-28) : la même liste, avec resultType et cache", lst)
res = got.get(5, {}).get("result") or {}
sc = res.get("structuredContent") or {}
rows = sc.get("souvenirs") or []
check(res.get("resultType") == "complete" and rows and rows[0].get("id") == "robots-txt-de-la-boutique-shopify"
      and set(rows[0]) == {"id", "type", "title", "project", "score"} and isinstance(rows[0]["score"], (int, float))
      and sc.get("texte") == text_of(got.get(5, {}))[0] and "robots.txt.liquid" in sc.get("texte", ""),
      "memory_search (2026-07-28) : structuredContent {souvenirs : id, type, title, project, score} et le texte "
      "entier (Claude Code ne passe que lui au modèle)", res)
e = got.get(6, {}).get("error") or {}
check(e.get("code") == -32602 and "ressource introuvable" in e.get("message", ""),
      "souvenir inconnu (2026-07-28) : -32602, le code de cette version (-32002 avant)", got.get(6))
check((got.get(7, {}).get("error") or {}).get("code") == -32602, "outil inconnu (2026-07-28) : -32602", got.get(7))
check((got.get(8, {}).get("error") or {}).get("code") == -32602
      and "clientCapabilities" in (got.get(8, {}).get("error") or {}).get("message", ""),
      "_meta sans clientCapabilities : -32602", got.get(8))
rd = got.get(9, {}).get("result") or {}
check(rd.get("cacheScope") == "private" and rd.get("ttlMs") == 0 and rd.get("contents"),
      "resources/read (2026-07-28) : privé, jamais gardé (un souvenir change)", rd)
sc = (got.get(10, {}).get("result") or {}).get("structuredContent") or {}
check(sc.get("id") == "robots-txt-de-la-boutique-shopify" and sc.get("ignores")
      and sc["ignores"][0].startswith("nouveau souvenir — déjà connu") and "due" in sc["ignores"][0],
      "memory_add (2026-07-28) : structuredContent {id, ignores}", sc)
got = serve(call(1, "memory_search", query="robots shopify"))
res = got.get(1, {}).get("result") or {}
check(res and "structuredContent" not in res and "resultType" not in res and "_meta" not in res,
      "après initialize (Claude Code d'aujourd'hui) : réponse inchangée, sans structuredContent (le texte resterait "
      "seul visible du modèle), pas un caractère de plus", res)

print(f"{len(OK)} vérifications OK, {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
