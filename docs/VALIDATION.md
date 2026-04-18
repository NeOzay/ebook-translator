# Système de validation

## Architecture multi-thread

La validation est découplée de la sauvegarde pour maximiser le throughput :

```
ValidationQueue → N × ValidationWorker (CPU-bound)
                        ↓ (si succès)
                     SaveQueue → 1 × SaveWorker (I/O-bound) → Store
```

**Fichiers clés** :
- Pool : [validation/validation_worker_pool.py](../src/ebook_translator/validation/validation_worker_pool.py)
- Worker : [validation/validation_worker.py](../src/ebook_translator/validation/validation_worker.py)
- Save : [validation/save_worker.py](../src/ebook_translator/validation/save_worker.py)
- Queues : [validation/validation_queue.py](../src/ebook_translator/validation/validation_queue.py)

## ValidationWorkerPool

Interface principale utilisée par `PhaseExecutor` :
- `switch_phase(phase, store)` : reconfigure workers pour une nouvelle phase
- `submit(ValidationItem)` : soumet un chunk traduit à valider
- `wait_completion()` : bloque jusqu'à ce que toutes les queues soient vides
- `get_statistics()` : retourne les métriques (chunks validés, rejetés, durée)

## ValidationWorker

Pour chaque item de la `ValidationQueue` :
1. Construit un `ValidationContext` (chunk + traductions + config)
2. Appelle `ValidationPipeline.validate_and_correct(context)`
3. Si succès → envoie `SaveItem` à `SaveQueue`
4. Si échec après tous les retries → log l'erreur, chunk rejeté

## SaveWorker

Écrit dans `Store` en ordre FIFO. Bénéfices :
- Les `ValidationWorker` ne bloquent jamais sur les écritures disque
- Les callbacks `on_save` s'exécutent après confirmation d'écriture
- Ordre déterministe des sauvegardes (facilite le débogage)

## ValidationPipeline

**Fichier** : [checks/pipeline.py](../src/ebook_translator/checks/pipeline.py)

Exécute les `Check` séquentiellement. Stratégie de correction :

1. **Validation initiale** : exécute tous les checks
2. **Si erreurs — tentative 1** : appel LLM normal avec prompt de correction spécialisé
3. **Si erreurs — tentative 2** : appel LLM reasoning (`deepseek-reasoner`) pour les cas complexes
4. **Si toujours des erreurs** : chunk rejeté et loggé

## Checks disponibles

**Répertoire** : [checks/check_tests/](../src/ebook_translator/checks/check_tests/)

| Check | Validation | Correction |
|-------|-----------|-----------|
| `LineCountCheck` | Toutes les lignes sont traduites | Retraduire les lignes manquantes |
| `FragmentCountCheck` | Nombre de `</>` préservé | Corriger les positions de fragments |
| `PunctuationCheck` | Équilibre guillemets `«»`, `""` | Rééquilibrer les paires |
| `SentenceCheck` | Phrases complètes (non tronquées) | Compléter les phrases |

## Interface Check

**Fichier** : [checks/check_tests/base.py](../src/ebook_translator/checks/check_tests/base.py)

```
Check[ErrorData]
├── validate(context) → CheckResult      # Détecte les erreurs
├── correct(context, error_data) → dict  # Tente la correction via LLM
└── validation_context(context) → ...   # Contexte pour les prompts
```

## Templates de correction

Les prompts de correction se trouvent dans `template/retry_*.jinja` :
- `retry_translate_missing_lines_targeted.jinja` — Lignes manquantes
- `retry_translate_sentence.jinja` — Phrases tronquées
- `retry_correct_fragments.jinja` — Fragments `</>` (positions exactes)
- `retry_correct_fragments_flexible.jinja` — Fragments (positions flexibles)
- `retry_correct_punctuation.jinja` — Guillemets déséquilibrés

## Retry automatique LLM

**Fichier** : [llm/llm.py](../src/ebook_translator/llm/llm.py)

Indépendamment de la validation, le client LLM gère les erreurs réseau :
- `APITimeoutError` : backoff × 2 (1s, 2s, 4s)
- `RateLimitError` : backoff × 3 (1s, 3s, 9s)
- Maximum 3 tentatives par défaut
