# Pull Request

## Description

<!-- Décrivez brièvement les changements apportés par cette PR -->

## Type de changement

<!-- Cochez la case appropriée -->

- [ ] 🆕 Nouvelle fonctionnalité (feat)
- [ ] 🐛 Correction de bug (fix)
- [ ] ♻️ Refactoring (refactor)
- [ ] 📝 Documentation (docs)
- [ ] ✅ Tests (test)
- [ ] 🔧 Maintenance/Configuration (chore)
- [ ] ⚡ Performance (perf)
- [ ] 💄 Style/Formatage (style)

## Changements détaillés

<!-- Liste des changements principaux -->

-
-
-

## Fichiers modifiés importants

<!-- Listez les fichiers clés qui ont été modifiés -->

- `src/ebook_translator/...`
- `tests/...`

## Motivation et contexte

<!-- Pourquoi ces changements sont-ils nécessaires ? Quel problème résolvent-ils ? -->

## Tests

<!-- Décrivez les tests ajoutés/modifiés -->

- [ ] Tests unitaires ajoutés pour nouveau code
- [ ] Tests unitaires mis à jour pour code modifié
- [ ] Tests d'intégration ajoutés (si applicable)
- [ ] Tous les tests passent localement (`poetry run pytest`)
- [ ] Coverage ≥ 80% pour nouveau code

**Commandes exécutées :**

```bash
# Tests
poetry run pytest

# Coverage (si applicable)
poetry run pytest --cov=src/ebook_translator --cov-report=term-missing
```

## Checklist qualité code

<!-- Vérifiez que tous ces points sont respectés -->

### Typage

- [ ] Tous les paramètres de fonction sont typés
- [ ] Tous les retours de fonction sont typés (`-> Type` ou `-> None`)
- [ ] Variables complexes explicitement typées
- [ ] Pyright strict sans erreurs (`poetry run pyright src/`)

### Documentation

- [ ] Docstrings ajoutées pour nouvelles fonctions/classes publiques
- [ ] Format Google UNIQUEMENT (Args, Returns, Raises, Example) - aucun autre format accepté
- [ ] Documentation inline pour code complexe
- [ ] CHANGELOG.md mis à jour (si version bump)
- [ ] README.md mis à jour (si nouvelle feature majeure)

### Style et formatage

- [ ] Code formaté avec black (`poetry run black src/ tests/`)
- [ ] Imports triés avec isort (`poetry run isort src/ tests/`)
- [ ] Ruff linting OK (`poetry run ruff check src/ tests/`)
- [ ] Pre-commit hooks OK (`poetry run pre-commit run --all-files`)

### Qualité générale

- [ ] Pas de `print()` (utiliser `logger`)
- [ ] Exceptions spécifiques (pas `Exception` générique)
- [ ] Messages d'erreur clairs avec contexte
- [ ] Logging avec niveaux appropriés (DEBUG/INFO/WARNING/ERROR)
- [ ] Pas de code commenté inutilement
- [ ] Pas de `# type: ignore` sans justification

## Git et workflow

- [ ] Commits conventionnels (feat:, fix:, refactor:, etc.)
- [ ] Messages de commit descriptifs
- [ ] Branche nommée correctement (feature/, bugfix/, refactor/, docs/)
- [ ] Pas de conflits avec `master`
- [ ] Commits atomiques (une préoccupation par commit)

## Breaking changes

<!-- Cette PR introduit-elle des breaking changes ? -->

- [ ] Non, cette PR est rétrocompatible
- [ ] Oui, cette PR introduit des breaking changes (détails ci-dessous)

**Détails des breaking changes (si applicable) :**

<!-- Décrivez les breaking changes et comment migrer -->

## Développement incrémental

<!-- Pour features complexes : décrivez la décomposition en sous-tâches -->

**Feature décomposée en sous-tâches :**

- [ ] Sous-tâche 1 : ...
- [ ] Sous-tâche 2 : ...
- [ ] Sous-tâche 3 : ...

**Chaque sous-tâche validée avec tests avant passage à la suivante.**

## Vérifications finales

<!-- Commandes à exécuter avant de soumettre la PR -->

```bash
# Tests
poetry run pytest
# Résultat : ✅ XX passed

# Type checking
poetry run pyright src/
# Résultat : ✅ 0 errors, 0 warnings

# Pre-commit
poetry run pre-commit run --all-files
# Résultat : ✅ All hooks passed
```

## Captures d'écran / Logs (optionnel)

<!-- Si applicable, ajoutez des captures d'écran ou logs démontrant les changements -->

## Références

<!-- Références à issues, discussions, ou documentation externe -->

- Closes #<!-- numéro issue -->
- Related to #<!-- numéro issue -->
- Documentation : [lien]

---

## Notes pour les reviewers

<!-- Informations additionnelles pour faciliter la review -->

**Points d'attention particuliers :**

-
-

**Questions ouvertes :**

-
-

---

**Checklist finale avant soumission :**

- [ ] J'ai relu mon code
- [ ] J'ai testé localement tous les changements
- [ ] J'ai vérifié qu'il n'y a pas de breaking changes non documentés
- [ ] Tous les tests passent
- [ ] Pyright strict sans erreurs
- [ ] Pre-commit hooks OK
- [ ] Documentation à jour
