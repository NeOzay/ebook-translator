# Phase 0 : Analyse littéraire

## Objectif

La Phase 0 analyse le contenu d'un EPUB **avant la traduction** pour produire, par chapitre, une fiche `AnalyseChapter` : caractéristiques stables du livre (genre affiné, registre, style, tonalité, pistes de traduction) et état du récit au point courant (résumé, arcs, tensions, thèmes, références culturelles).

Ce contexte est injecté dans les phases de traduction pour améliorer la cohérence stylistique et narrative. L'extraction terminologique, elle, relève d'une **phase distincte** (`GlossaryPhase`) : Phase 0 ne peuple pas le glossaire.

## Composants

### LiteraryAnalysisPhase

**Fichier** : [pipeline/phases/literary_analysis.py](../src/ebook_translator/pipeline/phases/literary_analysis.py)

Phase concrète `PhaseBase[ChapterPartChunk, AnalyseChapter, AnalyseChapter]` :

| Attribut | Valeur |
|---|---|
| `chunk_type` | `ChapterPartChunk` |
| `max_tokens` | 5000 |
| `overlap_ratio` | 0.0 (figé, `init=False`) |
| `execution_mode` | `SEQUENTIAL`, 1 worker |
| `payload_type` / `data_type` | `AnalyseChapter` |
| `content_checks` | `()` — schéma seul |
| `persister` | `MemoizedChunkPersister(AnalyseChapter)` |

La validation est **entièrement portée par le schéma** : `AnalyseChapter` est passé au LLM via Instructor (`JsonRequestConfig`, `Mode.TOOLS_STRICT`), qui garantit la structure côté API. Aucun check de contenu n'est nécessaire.

### Analyse incrémentale

Un chapitre trop long est découpé en plusieurs `ChapterPartChunk`. Chaque bloc **reprend la fiche du bloc précédent et la met à jour** — la structure JSON est identique dans tous les cas, seules les consignes de mise à jour changent. `render_prompt()` résout trois modes selon les snapshots disponibles :

| Mode | Condition | Amorce fournie au LLM |
|---|---|---|
| `incremental` | bloc N > 0 du chapitre | fiche du bloc précédent (`existing_analysis`) |
| `seed` | premier bloc du chapitre | fiche finale du chapitre précédent (`previous_chapter_analysis`) |
| `bootstrap` | tout premier bloc du livre | aucune |

`latest_analysis_for(chapter_name)` retourne la **dernière** fiche écrite d'un chapitre : les fiches étant cumulatives, c'est elle qui consolide l'ensemble.

### SequentialChapterDetector

**Fichier** : [segmentation/chapter_detector.py](../src/ebook_translator/segmentation/chapter_detector.py)

Parcourt le spine EPUB séquentiellement et reconstruit des `ChapterInfo`. Supporte plusieurs patterns de nommage (numérique, romain, textuel) en français et en anglais, avec croisement de la table des matières.

### AnalysisExporter

**Fichier** : [exporter/analysis_exporter.py](../src/ebook_translator/exporter/analysis_exporter.py)

`on_save()` exporte chaque fiche en Markdown lisible dans le répertoire de cache de la phase (`<cache>/literary_analysis/<outer_key>-<inner_key>.md`), pour revue humaine. Le hook est appelé par le `SaveWorker`, donc uniquement sur une fiche validée et écrite ; l'`inner_key` dans le nom évite qu'un bloc écrase le précédent au sein d'un même chapitre.

Les libellés d'export sont validés **à l'import du module** contre `model_fields` et `get_args(SignalCloture)` (`_checked_labels`, `_checked_signal_labels`) : un champ renommé dans le schéma casse immédiatement, plutôt que de produire un export silencieusement incomplet.

---

## Schéma AnalyseChapter

**Fichier** : [template/phase/analyze_chapter_layered_models.py](../src/template/phase/analyze_chapter_layered_models.py)

C'est la **source de vérité unique** de la structure JSON produite par le LLM : le prompt ne décrit plus la structure. Tous les modèles sont en `extra="forbid"`.

```
AnalyseChapter
├── chapitre: str                            — nom du chapitre analysé
├── noyau_stable: NoyauStable                — invariants du livre, évoluent lentement
│   ├── genre_affine: str                    — ex. « thriller psychologique »
│   ├── registre: str                        — 1 à 2 phrases
│   ├── style_auctorial: str                 — 1 à 2 phrases
│   ├── tonalite_generale: str               — 1 à 2 phrases
│   └── pistes_traduction: list[str]         — 1 à 15 entrées, non vides
└── couche_narrative: CoucheNarrative        — état du récit au bloc courant
    ├── resume_narratif: str                 — max 8 lignes
    ├── arcs_en_cours: list[Arc]
    │   ├── arc: str
    │   └── signal_cloture: "aucun" | "resolution_explicite" | "ambigu"
    ├── tensions: list[str]
    ├── themes_emergents: list[str]
    └── references_culturelles_rencontrees: list[str]
```

La stratification est le point clé : `noyau_stable` change peu d'un bloc à l'autre, `couche_narrative` est réécrite à chaque bloc.

`AnalyseChapter` est un `ConvertibleModel` paramétré **sur lui-même** : contrairement aux phases de traduction, la vue métier n'est pas un `TypedDict` dérivé mais le modèle lui-même, donc `build()` retourne `self`.

---

## Intégration dans le pipeline

- `Pipeline` récupère `LiteraryAnalysisPhase.latest_analysis_for` et l'injecte dans `Chapters` sous forme de callable `AnalysisLookup`. `segmentation` n'a ainsi à connaître ni le `StoreManager`, ni le `ByteStore`, ni le persister de la phase.
- Les phases 1 et 2 accèdent à la fiche de leur chunk via `Chapters.get_literary_analysis(chunk)`, injectée dans les prompts par `literary_context_block.jinja`.
- Si `LiteraryAnalysisPhase` n'est pas dans le pipeline, `AnalysisLookup` vaut `None` et les phases aval traduisent sans contexte littéraire.
- Les fiches sont mémoïsées par empreinte de chunk, un fichier de cache par chapitre (`MemoizedChunkPersister`, `outer_key` = nom du chapitre).

## Différences avec les phases de traduction

| Aspect | Phase 0 | Phases 1 & 2 |
|---|---|---|
| Granularité | Bloc de chapitre (5000 tokens) | Chunks de 300 à 1500 tokens |
| Parallélisation | Séquentielle, 1 worker | Parallèle (Phase 1), séquentielle (Phase 2) |
| Voie LLM | Instructor, sortie structurée | Texte numéroté `<N/>` |
| Validation | Schéma Pydantic seul | Schéma + 4 `content_checks` |
| `DT` | `AnalyseChapter` (le modèle lui-même) | `LineIndexed` (`TypedDict`) |
| Persistance | `MemoizedChunkPersister` | `LineIndexedPersister` |
