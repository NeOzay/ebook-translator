---
name: phase-audit
description: Audite une phase du pipeline contre son cahier des charges, puis en fait tirer les conclusions par un agent. Déclencher quand l'utilisateur dit "audite la phase glossaire", "le glossaire sur-extrait", "vérifie ce que produit la phase X", "/phase-audit", ou après un run dont il veut examiner une phase seule. À ne pas confondre avec /bench-judge, qui compare des variantes entre elles.
---

# Audit d'une phase

Deux temps : des **métriques déterministes** mesurées sur le cache d'un run, puis un
**agent** qui les instruit contre le cahier des charges de la phase.

La distinction avec `/bench-judge` est nette. Le banc compare N variantes entre elles
et les classe ; deux variantes également mauvaises s'y départagent quand même.
L'audit confronte une seule sortie à ce qu'elle devait être. Si l'utilisateur veut
savoir « laquelle est la meilleure », c'est `/bench-judge` ; s'il veut savoir « est-ce
que ça fait le travail », c'est ici.

## 1. Résoudre le cache

L'argument est un répertoire de cache, ou rien.

- Cache d'un run ordinaire : `<répertoire de l'epub>/.<stem>_cache/`
- Cache d'une variante de banc : `bench/runs/<run_id>/work/<variant_id>/cache/`

Sans argument, prendre la variante la plus récente du run de banc le plus récent :

```bash
ls -1d bench/runs/*/ | sort | tail -1
```

S'il y a plusieurs variantes, **demander laquelle auditer** plutôt que de deviner :
elles n'ont pas produit la même chose, c'est tout l'intérêt.

## 2. Mesurer

```bash
uv run ebook-audit "<cache_dir>" --phase glossary
```

Aucun appel LLM : la matière est déjà sur le disque. Le répertoire d'audit est écrit
sous `audit/runs/<horodatage>-<phase>/` ; l'option `--out` le déplace.

Codes de sortie : 0 si l'audit a abouti, 1 si le cache est introuvable ou si la phase
n'a rien écrit. Dans ce dernier cas, la commande liste les phases présentes — les
relayer à l'utilisateur plutôt que de réessayer au hasard.

Seule la phase `glossary` a un auditeur pour l'instant. `--phase` refuse les autres
avec la liste des valeurs acceptées.

## 3. Lancer l'agent

Un seul appel à l'outil Agent, `subagent_type: "phase-auditor"`, avec un prompt qui
donne le chemin de l'audit :

> Audite le répertoire `audit/runs/<audit_id>/`. Suis la procédure de ton agent :
> lis `spec.md` avant `report.md`, instruis chaque catégorie du catalogue en triant
> les faux positifs, réponds aux questions que la spec déclare non tranchées par les
> métriques, puis écris `verdict.md`.

**N'instruis pas le rapport toi-même dans la conversation courante.** L'agent démarre
à contexte vide, ce qui le tient à l'écart de ce qui a déjà été dit sur cette phase —
les hypothèses formulées plus tôt dans la discussion, les corrections envisagées. Un
audit qui confirme ce qu'on attendait de lui ne mesure rien.

Contrairement à `/bench-judge`, il n'y a pas d'aveugle à préserver : aucune variante
n'est en concurrence, rien n'est anonymisé.

## 4. Restituer

L'agent écrit `verdict.md` dans le répertoire d'audit et renvoie une synthèse. La
relayer — son rapport n'est pas montré à l'utilisateur — et donner le chemin du
verdict.

Si l'utilisateur veut appliquer les ajustements de prompt proposés, c'est un travail
distinct : ils touchent `src/template/phase/`, qui est un sous-module. Le lui signaler
avant de modifier quoi que ce soit.
