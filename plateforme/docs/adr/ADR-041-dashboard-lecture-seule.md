# ADR-041 — Dashboard v1 : FastAPI + Jinja2, local, lecture seule

- Statut : accepté (D15 et D16 du plan de phase 5, validées par Lucas le 21/10/2026)
- Date : 2026-10-21
- Phase : 5

## Contexte
Le §17 demande un dashboard v1. Le détail chiffré n'a pas sa place sur Discord (ADR-037).

## Options
1. Streamlit.
2. HTML statique généré.
3. **FastAPI + Jinja2, servi par l'API interne.**

## Décision
Option 3.

- **Pages** : positions et cash du compte paper ; risque (outils `finance_risk`, chiffres cités) ;
  décisions en cours (intentions, approbations en attente, échéances) ; évals (dernier rapport hors
  ligne) ; santé des plugins (registre, dernières erreurs du journal) ; état du kill switch et du
  live.
- **Lecture seule** : uniquement des routes `GET`, aucune approbation, aucun JavaScript, échappement
  automatique de Jinja2.
- **Accès (D16)** : `127.0.0.1` et le jeton de l'API.
- **Dépendance** : Jinja2 3.1.6, BSD-3-Clause (vérifiée le 21/10/2026).

## Conséquences
- Aucune nouvelle surface d'écriture.
- **Tests** : `TestClient`, jeton exigé, aucune route autre que `GET`.
