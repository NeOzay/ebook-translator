---
name: bench-judge
description: Lance l'arbitrage d'un run de banc d'essais de pipelines de traduction. Déclencher quand l'utilisateur dit "arbitre le banc d'essais", "juge le run", "compare les variantes", "/bench-judge", ou après un run de `python -m ebook_translator.bench`. Résout le run, vérifie qu'il est arbitrable, puis délègue à l'agent bench-judge.
---

# Arbitrage d'un run de banc d'essais

L'arbitrage est délégué à l'agent `bench-judge`, qui démarre à contexte vide. Ce n'est
pas un détail d'implémentation : l'aveugle ne tient que si le juge ignore tout de
l'historique de la conversation — quels paramètres ont été essayés, quel modèle
l'utilisateur préfère. Ne fais donc **jamais** l'arbitrage toi-même dans la
conversation courante, même pour « aller plus vite ».

## 1. Résoudre le run

L'argument est un `run_id` (par exemple `20260802_143005`) ou un chemin de répertoire.
Sans argument, prendre le run le plus récent :

```bash
ls -1d bench/runs/*/ | sort | tail -1
```

Répertoire attendu : `bench/runs/<run_id>/`. S'il n'existe pas, lister les runs
disponibles et demander lequel arbitrer plutôt que de deviner.

## 2. Vérifier que le run est arbitrable

```bash
ls bench/runs/<run_id>/ bench/runs/<run_id>/compare/
```

- `README.md`, `metrics.md`, `manifest.json` et `compare/` doivent être présents.
  S'il en manque, le run n'a pas été rendu : proposer de relancer
  `uv run python -m ebook_translator.bench <config>` plutôt que d'arbitrer à moitié.
- `compare/` vide → rien à comparer. Cause habituelle : toutes les variantes ont
  produit un texte identique, ou les phases de traduction n'étaient pas dans le
  pipeline. Le signaler, ne pas lancer l'agent.
- `verdict.md` déjà présent → le run a déjà été arbitré. Demander confirmation avant
  d'écraser.

**Ne lis pas `manifest.json` toi-même** et ne restitue pas son contenu : tu
contaminerais la restitution en révélant les paramètres avant le verdict.

## 3. Lancer l'agent

Un seul appel à l'outil Agent, `subagent_type: "bench-judge"`, avec un prompt qui
donne le chemin du run et rien d'autre :

> Arbitre le run de banc d'essais situé dans `bench/runs/<run_id>/`. Suis la
> procédure de ton agent : cadrage, lecture du corpus, écriture de `verdict.md`,
> puis levée d'anonymat. N'ouvre `manifest.json` qu'après avoir écrit ton classement.

N'ajoute au prompt aucun élément de contexte sur les variantes, les modèles employés
ou les résultats attendus : ce serait rendre l'aveugle inopérant.

## 4. Restituer

L'agent écrit `verdict.md` dans le répertoire du run et renvoie une synthèse. Relaie
cette synthèse à l'utilisateur — son rapport ne lui est pas montré directement — et
donne le chemin du verdict complet.
