"""TEMPORAIRE (diagnostic) : lance tests/test_commun.py avec KEEP=1 puis affiche la trace d'alice et l'historique du
dépôt commun. À retirer avant la fusion."""
import os
import re
import subprocess
import sys
from pathlib import Path

r = subprocess.run([sys.executable, "tests/test_commun.py"], capture_output=True, env=dict(os.environ, KEEP="1"))
out = r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
print(out[-6000:])
m = re.search(r"dossier gardé : (.+?)\)", out)
if m:
    tmp = Path(m.group(1).strip())
    for who in ("alice",):
        log = tmp / who / "brain" / "state" / "brain.log"
        print(f"===== {who} brain.log")
        print(log.read_text(encoding="utf-8", errors="replace") if log.exists() else "(absent)")
        st = tmp / who / "brain" / "state" / "commun.json"
        print(f"===== {who} commun.json")
        print(st.read_text(encoding="utf-8", errors="replace") if st.exists() else "(absent)")
        print(f"===== {who} state/")
        print(sorted(p.name for p in (tmp / who / "brain" / "state").iterdir()))
    print("===== bare log")
    print(subprocess.run(["git", "-C", str(tmp / "cerveau-commun.git"), "log", "--all", "--name-status", "--date=iso",
                          "--format=%h %ad %an %s"], capture_output=True, text=True, encoding="utf-8").stdout[-8000:])
sys.exit(r.returncode)
