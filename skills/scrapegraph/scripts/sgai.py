"""ScrapeGraphAI en une commande : extraire en JSON ce qu'on demande d'une page, de plusieurs, ou d'une recherche web.

Usage (avec le Python de l'environnement ~/.scrapegraphai/venv) :
  python sgai.py "liste les produits avec nom et prix" https://exemple.fr/boutique
  python sgai.py "compare les tarifs" https://a.fr https://b.fr          (plusieurs pages, appels en parallèle)
  python sgai.py "meilleures gourdes isothermes" --search 5              (recherche DuckDuckGo puis extraction)
  python sgai.py "résume ce document" page.html                          (fichier local : HTML, texte, Markdown)

LLM local par défaut (Ollama, gratuit) : --model qwen3.5:9b, ou la variable SGAI_MODEL.
Autre fournisseur : --model openai/gpt-4o-mini (clé lue dans la variable d'environnement du fournisseur).
"""
import argparse
import json
import os
import sys
from pathlib import Path

# Avant tout import de scrapegraphai : sa télémétrie envoie prompt, contenu de la page et réponse à leur serveur.
os.environ["SCRAPEGRAPHAI_TELEMETRY_ENABLED"] = "false"


def main() -> int:
    ap = argparse.ArgumentParser(description="ScrapeGraphAI : extraire en JSON ce qu'on demande d'une page.")
    ap.add_argument("prompt", help="ce qu'il faut extraire, en langage naturel")
    ap.add_argument("sources", nargs="*", help="URL(s) ou fichier(s) locaux ; aucune avec --search")
    ap.add_argument("--search", type=int, metavar="N", help="chercher sur le web et lire les N premiers résultats")
    ap.add_argument("--model", default=os.environ.get("SGAI_MODEL", "qwen3.5:9b"),
                    help="modèle (défaut qwen3.5:9b via Ollama)")
    ap.add_argument("--ctx", type=int, default=32768, help="fenêtre de contexte en tokens (défaut 32768)")
    ap.add_argument("--chromium", action="store_true",
                    help="Chromium de Playwright au lieu du Chrome installé (après `playwright install chromium`)")
    ap.add_argument("--show", action="store_true", help="afficher la fenêtre du navigateur")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    if bool(a.search) == bool(a.sources):
        ap.error("donner soit une ou plusieurs sources, soit --search N")

    model = a.model if "/" in a.model else f"ollama/{a.model}"
    llm = {"model": model, "model_tokens": a.ctx, "temperature": 0}
    if model.startswith("ollama/"):
        llm.update(num_ctx=a.ctx, reasoning=False)  # réflexion coupée : plus rapide, JSON propre
    config = {"llm": llm, "headless": not a.show, "verbose": a.verbose}
    if not a.chromium:
        config["loader_kwargs"] = {"channel": "chrome"}

    from scrapegraphai.graphs import SearchGraph, SmartScraperGraph, SmartScraperMultiGraph

    if a.search:
        config["max_results"] = a.search
        graph = SearchGraph(prompt=a.prompt, config=config)
    else:
        sources = [Path(s).read_text(encoding="utf-8", errors="replace") if Path(s).is_file() else s
                   for s in a.sources]
        graph = (SmartScraperGraph(prompt=a.prompt, source=sources[0], config=config) if len(sources) == 1
                 else SmartScraperMultiGraph(prompt=a.prompt, source=sources, config=config))

    result = graph.run()
    if isinstance(result, dict) and list(result) == ["content"] and isinstance(result["content"], str):
        try:  # le modèle renvoie souvent son JSON sous forme de texte : le déballer
            result = json.loads(result["content"])
        except ValueError:
            pass
    if a.search:
        result = {"reponse": result, "sources": graph.get_considered_urls()}
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
