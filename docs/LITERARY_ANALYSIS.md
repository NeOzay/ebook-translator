# Phase 0 : Analyse Littéraire

## Objectif

La Phase 0 analyse le contenu d'un EPUB **avant la traduction** pour extraire :
- Un contexte narratif par chapitre (ton, style, thèmes, références culturelles, pistes de traduction)
- Un glossaire pré-peuplé avec des propositions de traduction pour chaque terme clé

Ce contexte est injecté dans les phases suivantes pour améliorer la cohérence terminologique et réduire les conflits de glossaire.

## Composants

### LiteraryAnalysisPhase

**Fichier** : [pipeline/phases/literary_analysis.py](../src/ebook_translator/pipeline/phases/literary_analysis.py)

Phase concrète héritant de `PhaseBase`. Configuration :
- `chunk_type` : `ChapterPartChunk` — un chunk par chapitre, max 8000 tokens
- `execution_mode` : SEQUENTIAL
- Mode LLM : JSON mode (structured output)
- Template : `analyze_chapter_simplified.jinja`

Flux d'exécution :
1. `SequentialChapterDetector` détecte les chapitres depuis le spine EPUB
2. Chaque chapitre est analysé en JSON via le LLM
3. `AnalysisValidator` valide la structure `ContexteTraduction`
4. `_populate_glossary()` peuple automatiquement le `Glossary` du pipeline

### SequentialChapterDetector

**Fichier** : [segmentation/chapter_detector.py](../src/ebook_translator/segmentation/chapter_detector.py)

Parcourt le spine EPUB séquentiellement. Supporte plusieurs patterns de nommage (numérique, romain, textuel) en français et anglais.

### AnalysisValidator

**Fichier** : [analysis/validator.py](../src/ebook_translator/analysis/validator.py)

Valide que la réponse JSON du LLM correspond au schéma `ContexteTraduction`. Retourne une instance validée ou lève une exception descriptive.

### AnalysisExporter

**Fichier** : [analysis/analysis_exporter.py](../src/ebook_translator/analysis/analysis_exporter.py)

Sauvegarde l'analyse en Markdown lisible dans le répertoire de cache.

---

## Schéma ContexteTraduction

**Fichier** : [analysis/translation_context.py](../src/ebook_translator/analysis/translation_context.py)

```
ContexteTraduction
├── chapitre: str                    — Nom/numéro du chapitre
├── analyse: AnalyseLitteraire
│   ├── resume_narratif: str         — Résumé des événements
│   ├── tonalite: str                — Ton dominant
│   ├── style: str                  — Style d'écriture
│   ├── themes: list[str]           — Thèmes principaux
│   ├── references_culturelles: list[str]
│   └── pistes_traduction: list[str] — Éléments concrets à préserver/adapter
├── glossaire: list[TermeGlossaire]
│   ├── terme: str                  — Terme en langue source
│   ├── type: str                   — Personnage, lieu, concept, etc.
│   ├── sexe: str | None            — Pour les personnages
│   ├── description_role: str
│   ├── notes_traduction: str
│   └── proposition_traduction: str — Traduction recommandée
└── scope: list[str]               — Fichiers HTML couverts
```

Le champ `proposition_traduction` est directement utilisé pour pré-peupler le `Glossary` avec des termes validés avant la traduction.

---

## Intégration dans le pipeline

- `PhaseContext.chapters` contient les `ChapterInfo` avec leur `ContexteTraduction`
- Les phases 1 et 2 accèdent au contexte via `ChunkContext` → `chapters`
- Le `Glossary` est pré-peuplé avant Phase 1 → les terms sont déjà connus dès la première traduction
- L'analyse est mise en cache dans `Store[literary_analysis]` : pas de re-analyse si déjà fait

## Différences avec les phases de traduction

| Aspect | Phase 0 | Phases 1 & 2 |
|--------|---------|--------------|
| Granularité | Chapitre entier (8000 tokens) | Chunks de 300-1500 tokens |
| Parallélisation | Séquentielle | Parallèle (Phase 1) |
| Output LLM | JSON structuré | Texte numéroté (`<N/>`) |
| Validation | Structure JSON | ValidationWorkerPool (checks) |
| Cache | Store[literary_analysis] | Store[initial], Store[refinement] |
