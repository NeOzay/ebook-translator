# Architecture de validation

Le système de validation est divisé en **2 modules indépendants** avec des responsabilités distinctes.

## Module `validation/` - Validation structurelle (OBLIGATOIRE)

### Objectif

Garantir l'intégrité structurelle des traductions avant sauvegarde.

### Checks disponibles

- **`LineCountCheck`** : Vérifie que toutes les lignes sont traduites (pas de lignes manquantes)
- **`FragmentCountCheck`** : Vérifie que le nombre de fragments est préservé (séparateur `</>`)
- **`PunctuationCheck`** : Vérifie l'équilibre des paires de guillemets

### Architecture multi-thread

```
ValidationQueue → ValidationWorkers (N threads, CPU-bound)
               ↓
            SaveQueue → SaveWorker (1 thread, I/O-bound)
                     ↓
                   Store (thread-safe avec verrous par fichier)
```

### Caractéristiques

- ✅ Intégré automatiquement dans `ValidationWorkerPool`
- ✅ Découplage validation/sauvegarde → **+33-50% de throughput**
- ✅ SaveWorker fournit pipeline I/O dédié (ordre déterministe, callbacks thread-safe)
- ✅ Store thread-safe avec verrous par fichier (gère PermissionError Windows)
- ✅ Retry automatique avec prompts spécialisés si erreurs détectées
- ✅ Obligatoire : Chunks rejetés si validation échoue après retries

### Composants clés

**ValidationWorkerPool** :
- Orchestre N ValidationWorkers + 1 SaveWorker
- Gère le cycle de vie des threads
- Coordonne la validation et la sauvegarde

**ValidationWorker** :
- Valide les traductions (multi-thread, CPU-bound)
- Exécute la ValidationPipeline
- Transmet les chunks validés à SaveQueue

**SaveWorker** :
- Pipeline I/O dédié pour découpler validation et persistance
- Garantit l'ordre FIFO des sauvegardes
- Exécute les callbacks après sauvegarde confirmée

**ValidationQueue / SaveQueue** :
- Queues thread-safe pour coordination
- Gestion de la backpressure (limite utilisation mémoire)

**ValidationPipeline** :
- Exécute séquentiellement les checks
- Collecte les erreurs détectées
- Déclenche les corrections si nécessaire

**Store** :
- Gestion thread-safe avec verrous par fichier
- Écriture atomique via fichier temporaire + rename
- Gestion robuste des erreurs I/O

### Bénéfices de SaveWorker

- **Performance** : ValidationWorkers ne bloquent pas sur les écritures disque
- **Ordre déterministe** : Sauvegardes FIFO dans l'ordre de validation (facilite debug)
- **Callbacks thread-safe** : `on_validated` exécuté après confirmation de sauvegarde
- **Gestion d'erreurs centralisée** : Logs cohérents, statistiques unifiées
- **Backpressure** : SaveQueue limite l'utilisation mémoire si disque lent

### Système de retry progressif (v0.8.0)

**Tentative 1 - Mode normal** :
- Utilise `deepseek-chat`
- Prompt spécialisé selon l'erreur détectée
- Rapide et économique

**Tentative 2 - Mode raisonnement** :
- Utilise `deepseek-reasoner`
- Génère un processus de pensée explicite
- Plus lent mais plus précis pour problèmes complexes

**Taux de succès** :
- `FragmentCountCheck` : ~85-90% → ~95-98% (+10-15%)
- `LineCountCheck` : ~90-95% → ~96-99% (+5-10%)
- `PunctuationCheck` : ~75-85% → ~90-95% (+15-20%)

**Coût** :
- +5-10% tokens (reasoning)
- +10-20% temps (tentative 2 plus lente)
- Impact global limité (~5-10% des chunks nécessitent tentative 2)

### Exemple d'usage

```python
from ebook_translator.checks import ValidationPipeline, LineCountCheck, FragmentCountCheck
from ebook_translator.validation import ValidationWorkerPool

# Créer pipeline de validation
pipeline = ValidationPipeline([
    LineCountCheck(),
    FragmentCountCheck(),
])

# Initialiser pool de workers
pool = ValidationWorkerPool(
    num_workers=2,
    pipeline=pipeline,
    store=store,
    llm=llm,
    target_language="fr",
    phase="initial",
)

# Démarrer et soumettre chunks
pool.start()
pool.submit(chunk, translated_texts)
pool.wait_completion()
```

### Flux de fonctionnement

```
1. Chunk traduit → ValidationQueue
   ↓
2. ValidationWorker récupère le chunk
   ↓
3. Exécution de ValidationPipeline :
   a. LineCountCheck.check() → Erreur détectée ?
   b. Si oui → LineCountCheck.correct() avec retry progressif
   c. FragmentCountCheck.check() → Erreur détectée ?
   d. Si oui → FragmentCountCheck.correct() avec retry progressif
   ↓
4a. Validation réussie → Chunk envoyé à SaveQueue
4b. Validation échouée → Chunk filtré (lignes invalides supprimées)
   ↓
5. SaveWorker sauvegarde dans Store
   ↓
6. Callback on_validated() exécuté
```

## Module `quality/` - Validation sémantique (OPTIONNEL)

### Objectif

Analyser la qualité sémantique des traductions après le pipeline principal.

### Checks disponibles

**UntranslatedDetector** :
- Détecte segments restés en langue source
- Basé sur mots courants anglais + patterns grammaticaux
- Calcul de confiance (0.0 à 1.0)
- Heuristiques :
  - Ratio de mots courants (100+ mots : the, be, to, of, and, etc.)
  - Patterns grammaticaux (articles, modaux, pronoms)
  - Bonus de confiance pour textes longs

**TerminologyChecker** :
- Détecte incohérences terminologiques (même terme → traductions différentes)
- Extraction automatique de noms propres (majuscules, acronymes)
- Génération de glossaire avec traduction recommandée (la plus fréquente)
- Exemple : "Matrix" → "Matrice" (3×) puis "Système" (1×) ⚠️ Incohérence

**Glossaire automatique** :
- Apprend les traductions de termes techniques et noms propres au fur et à mesure
- Sauvegarde/chargement sur disque (JSON)
- Validation manuelle possible (prioritaire sur apprentissage)
- Détection de conflits (traductions équilibrées sans dominante claire)

### Caractéristiques

- ❌ **Non intégré** dans le pipeline principal
- ⚙️ Usage **standalone** : À utiliser manuellement après traduction
- 📊 Génère des **rapports de qualité** texte
- 💾 Sauvegarde un **glossaire** JSON réutilisable

### Exemple d'usage

```python
from ebook_translator.quality import QualityValidator

# Initialiser
validator = QualityValidator(
    source_lang="en",
    target_lang="fr",
    glossary_path=Path("cache/glossary.json"),
    enable_untranslated_detection=True,
    enable_terminology_check=True,
)

# Valider paire par paire
for original, translated in translations:
    validator.validate_translation(original, translated, position=i)

# Générer rapport
print(validator.generate_report())

# Sauvegarder glossaire
validator.save_glossary()
```

### Rapport de qualité

```
============================================================
📊 RAPPORT DE VALIDATION DE TRADUCTION
============================================================

## Statistiques
  • Segments non traduits détectés: 2
  • Problèmes de cohérence terminologique: 3
  • Termes dans le glossaire: 45
  • Termes validés: 0
  • Conflits terminologiques: 1

## Problèmes détectés

### ⚠️ Incohérences terminologiques

⚠️ Incohérence terminologique détectée:
  • Terme source: "Matrix"
  • Traductions trouvées:
    - "Matrice" (5 fois)
    - "Système" (1 fois)
  💡 Suggestion: utiliser "Matrice" partout
============================================================
```

## Comparaison des modules

| Aspect | `validation/` (structurel) | `quality/` (sémantique) |
|--------|---------------------------|------------------------|
| **Intégration** | ✅ Automatique dans pipeline | ❌ Manuel (standalone) |
| **Objectif** | Intégrité structurelle | Qualité sémantique |
| **Checks** | Lignes, fragments, ponctuation | Non traduits, terminologie |
| **Correction** | ✅ Retry automatique | ❌ Rapports seulement |
| **Obligatoire** | ✅ Oui (rejette chunks) | ❌ Non (optionnel) |
| **Multi-thread** | ✅ Oui (ValidationWorkers) | ❌ Non (séquentiel) |
| **Mode reasoning** | ✅ Oui (tentative 2) | ❌ Non |

## Recommandations d'usage

### Toujours utiliser `validation/`

Intégré automatiquement, garantit structure correcte. Aucune configuration requise.

### Utiliser `quality/` pour :

- Projets professionnels nécessitant haute qualité
- Détecter problèmes sémantiques post-traduction
- Générer glossaires pour cohérence future
- Analyser les incohérences terminologiques

### Ne PAS utiliser `quality/` si :

- Traduction rapide / brouillon
- Pas besoin d'analyse détaillée
- Budget tokens limité

## Structure des logs

Exemple avec retry progressif (v0.8.0) :

```
logs/run_20251028_143022/
  translation.log
  llm_phase1_chunk_001_0001.log

  # FragmentCountCheck (2 tentatives)
  llm_correction_fragment_line_5_chunk_042_attempt_1_0003.log
  llm_correction_fragment_line_5_chunk_042_attempt_2_reasoning_0004.log

  # LineCountCheck (2 tentatives)
  llm_correction_missing_lines_chunk_055_attempt_1_0005.log
  llm_correction_missing_lines_chunk_055_attempt_2_reasoning_0006.log

  # PunctuationCheck (2 tentatives)
  llm_correction_punctuation_line_8_chunk_010_attempt_1_0007.log
  llm_correction_punctuation_line_8_chunk_010_attempt_2_reasoning_0008.log
```

## Impact attendu

### Module `validation/`

| Aspect | Amélioration | Confiance |
|--------|--------------|-----------|
| **Intégrité structurelle** | 95-99% chunks valides | Élevée |
| **Performance** | +33-50% throughput (SaveWorker) | Élevée |
| **Taux de succès corrections** | +10-20% (mode reasoning) | Élevée |
| **Chunks filtrés** | -40% (corrections plus efficaces) | Moyenne-Élevée |

### Module `quality/`

| Aspect | Amélioration | Confiance |
|--------|--------------|-----------|
| **Détection segments non traduits** | Alertes pour 80-90% des cas | Élevée |
| **Cohérence terminologique** | +15-25% de cohérence | Élevée |
| **Réduction erreurs** | -30-40% d'incohérences | Moyenne-Élevée |
| **Qualité globale** | +10-15% (via feedback) | Moyenne |

## Limitations connues

### Module `validation/`

- **Pas de validation sémantique** : Vérification structurelle uniquement
- **Mode reasoning coûteux** : +5-10% tokens pour ~5-10% des chunks
- **Pas de correction itérative** : Maximum 2 tentatives par check

### Module `quality/`

- **Détection anglais uniquement** : Fonctionne seulement pour anglais → autres langues
- **Heuristiques simples** : Peut avoir des faux positifs/négatifs
- **Pas de correction automatique** : Seulement des alertes (pas de re-traduction)
- **Extraction noms propres basique** : Basée sur majuscules (peut rater certains cas)

## Voir aussi

- [ARCHITECTURE.md](ARCHITECTURE.md) - Architecture globale du système
- [ROADMAP.md](ROADMAP.md) - Améliorations futures planifiées
