# Standards de Code - ebook-translator

Référence technique complète des standards de code pour **ebook-translator**.

## 📋 Table des matières

- [Typage Python](#typage-python)
- [Documentation et Docstrings](#documentation-et-docstrings)
- [Gestion d'erreurs](#gestion-derreurs)
- [Logging](#logging)
- [Architecture et Design](#architecture-et-design)
- [Tests](#tests)
- [Style et formatage](#style-et-formatage)

---

## 🔤 Typage Python

### Mode strict obligatoire

Le projet utilise **basedpyright en mode strict**. Toutes les erreurs de typage doivent être corrigées.

```bash
# Vérifier les types
uv run basedpyright src/

# Doit retourner : "0 errors, 0 warnings"
```

### 1. Paramètres et retours de fonction

**Tous les paramètres et retours doivent être typés.**

```python
# ✅ BON
def translate_chunk(
    chunk: Chunk,
    target_language: str,
    llm: LLM,
    max_retries: int = 3,
    use_reasoning: bool = False
) -> dict[int, str]:
    """Traduit un chunk avec typage complet."""
    translations: dict[int, str] = {}
    return translations

# ❌ MAUVAIS : Pas de typage
def translate_chunk(chunk, target_language, llm, max_retries=3):
    translations = {}
    return translations

# ❌ MAUVAIS : Typage partiel
def translate_chunk(chunk: Chunk, target_language, llm) -> dict:
    ...
```

### 2. Variables complexes

**Variables avec types non évidents doivent être typées explicitement.**

```python
# ✅ BON : Typage explicite
translations: dict[int, str] = {}
error_lines: set[int] = set()
chunks: list[Chunk] = []
cache: dict[str, list[str]] = defaultdict(list)

# ❌ MAUVAIS : Type implicite (peut être ambigu)
translations = {}  # dict[int, str] ? dict[str, str] ? Impossible à savoir
error_lines = set()  # set[int] ? set[str] ?
chunks = []  # list[Chunk] ? list[str] ?
```

**Variables simples peuvent rester implicites si évident :**

```python
# ✅ OK : Type évident par inférence
count = 0  # int évident
name = "test"  # str évident
is_valid = True  # bool évident
```

### 3. Type Aliases

**Utiliser TypeAlias pour types complexes réutilisés.**

```python
from typing import TypeAlias

# ✅ BON : Type alias pour clarté
GlossaryEntry: TypeAlias = dict[str, int]
GlossaryData: TypeAlias = dict[str, GlossaryEntry]
TranslationMap: TypeAlias = dict[int, str]
ErrorData: TypeAlias = dict[str, list[int] | dict[int, str]]

def load_glossary() -> GlossaryData:
    """Charge le glossaire avec type clair."""
    ...

def collect_errors() -> ErrorData:
    """Retourne les erreurs avec type clair."""
    ...

# ❌ MAUVAIS : Type complexe répété partout
def load_glossary() -> dict[str, dict[str, int]]:
    ...

def save_glossary(data: dict[str, dict[str, int]]) -> None:
    ...
```

### 4. Protocols pour duck typing

**Préférer Protocol aux classes abstraites pour interfaces.**

```python
from typing import Protocol, runtime_checkable

# ✅ BON : Protocol pour interface
@runtime_checkable
class ContentCheck[DT, CtxT](Protocol):
    """Interface pour les checks de contenu (cf. checks/content_check.py)."""

    error_type: ClassVar[ErreursType]
    max_attempts: ClassVar[int]

    def run(self, data: DT, source: ChunkSource) -> list[ValidationFailure[CtxT]]:
        """Détecte les écarts entre `data` et la source."""
        ...

# Les implémentations n'ont pas besoin d'hériter
class LineCountCheck:
    error_type: ClassVar[ErreursType] = ErreursType.LINES_MISSING
    max_attempts: ClassVar[int] = 2

    def run(self, data: LineIndexed, source: ChunkSource) -> list[ValidationFailure[Any]]:
        ...

# Le type checking fonctionne
check: ContentCheck[LineIndexed, Any] = LineCountCheck()  # ✅ OK

# ❌ MOINS BON : classe abstraite (héritage requis)
from abc import ABC, abstractmethod

class ContentCheck(ABC):
    @abstractmethod
    def run(self, data: Any, source: ChunkSource) -> list[ValidationFailure[Any]]:
        ...

# Toutes les implémentations DOIVENT hériter
class LineCountCheck(ContentCheck):  # Héritage obligatoire
    ...
```

Le protocole réel est dans [checks/content_check.py](../src/ebook_translator/checks/content_check.py), ses implémentations dans [checks/content/](../src/ebook_translator/checks/content/).

### 5. Union types (moderne)

**Utiliser `|` pour unions (Python 3.12+).**

```python
# ✅ BON : Syntaxe moderne
def process(value: str | int) -> str | None:
    ...

def get_result() -> dict[str, str] | None:
    ...

# ❌ MAUVAIS : Ancienne syntaxe (Python 3.9)
from typing import Optional, Union

def process(value: Union[str, int]) -> Optional[str]:
    ...
```

### 6. Génériques

**Typage correct pour collections génériques.**

```python
# ✅ BON : Génériques typés
def get_chunks() -> list[Chunk]:
    ...

def get_translations() -> dict[int, str]:
    ...

def get_errors() -> set[int]:
    ...

# ❌ MAUVAIS : Génériques non typés
def get_chunks() -> list:  # list de quoi ?
    ...

def get_translations() -> dict:  # dict[?, ?]
    ...
```

### 7. TYPE_CHECKING pour éviter imports circulaires

**Utiliser TYPE_CHECKING pour types utilisés uniquement pour annotation.**

```python
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ebook_translator.llm import LLM
    from ebook_translator.segmentation.chunk import Chunk

# Ces imports ne s'exécutent qu'au type checking, pas au runtime
# Évite les imports circulaires

def process_chunk(chunk: Chunk, llm: LLM) -> str:
    """chunk et llm sont des strings au runtime, des types au type checking."""
    ...
```

### 8. Type: ignore (à éviter)

**Éviter `# type: ignore` autant que possible. Si nécessaire, justifier.**

```python
# ✅ Acceptable : Avec commentaire justificatif
result = external_lib.function()  # type: ignore[no-untyped-call]  # external_lib n'a pas de stubs

# ❌ MAUVAIS : Sans justification
result = function()  # type: ignore
```

---

## 📝 Documentation et Docstrings

### Format Google obligatoire

**⚠️ IMPORTANT** : Le format Google est le **seul format autorisé** pour les docstrings dans ce projet.

**Toutes les fonctions/classes publiques doivent avoir des docstrings au format Google.**

Aucun autre format (reStructuredText, NumPy, etc.) n'est accepté. Cette standardisation garantit :
- Cohérence totale de la documentation
- Lisibilité optimale du code
- Compatibilité avec les outils de génération de documentation

### Structure complète

```python
def validate_data[DT](
    content_checks: Sequence[ContentCheck[DT, Any]],
    data: DT,
    source: ChunkSource,
) -> list[ValidationFailure[Any]]:
    """
    Applique une séquence de checks de contenu à une donnée validée en schéma.

    Chaque check est exécuté dans l'ordre fourni et ses échecs sont agrégés.
    Aucune correction n'est tentée ici : la fonction se contente de détecter.

    Args:
        content_checks: Checks à exécuter, dans l'ordre de déclaration
            de la phase. Exemple : (LineCountCheck(), FragmentCountCheck())
        data: Vue TypedDict produite par `payload.build()`.
        source: Accès à la source du chunk (`line_indices()`, `text_at()`).

    Returns:
        Liste des `ValidationFailure` collectées, vide si tout passe.
        Chaque échec porte son `error_type`, son diagnostic typé `ctx`
        et ses `relevant_indices`.

    Raises:
        RuntimeError: Si un check lève une exception inattendue.

    Example:
        >>> checks = (LineCountCheck(), FragmentCountCheck())
        >>> failures = validate_data(checks, data, source)
        >>> assert not failures

    Note:
        Tous les checks sont exécutés même si l'un d'eux échoue, afin de
        collecter l'ensemble des erreurs en un seul passage. Le routage
        vers les prompts de correction relève de `RETRY_REGISTRY`.
    """
    ...
```

### Sections obligatoires

1. **Description courte** (première ligne)
   - Résumé en une phrase
   - Commence par un verbe (Valide, Traduit, Crée, etc.)

2. **Description détaillée** (optionnelle)
   - Paragraphe(s) expliquant le comportement
   - Contexte d'utilisation

3. **Args** (obligatoire si paramètres)
   - Tous les paramètres documentés
   - Type implicite (déjà dans signature)
   - Description claire avec exemples si nécessaire

4. **Returns** (obligatoire si retour non-None)
   - Type de retour (même si dans signature)
   - Description de ce qui est retourné
   - Structure pour types complexes

5. **Raises** (si exceptions levées)
   - Toutes les exceptions possibles
   - Conditions dans lesquelles elles sont levées

6. **Example** (recommandé pour fonctions complexes)
   - Code exécutable
   - Utilisation typique
   - Format doctest si possible

7. **Note** (optionnel)
   - Informations importantes
   - Comportements non évidents
   - Limitations

### Docstrings de classe

```python
class ValidationWorkerPool:
    """
    Pool de workers pour validation parallèle avec sauvegarde thread-safe.

    Cette classe gère N ValidationWorkers qui valident les traductions
    en parallèle, et 1 SaveWorker qui sauvegarde les résultats de manière
    thread-safe. La séparation validation/sauvegarde améliore le throughput
    de 33-50%.

    Attributes:
        validation_workers: Liste des workers de validation
        save_worker: Worker unique pour sauvegarde thread-safe
        validation_queue: Queue des tâches de validation
        save_queue: Queue des tâches de sauvegarde
        max_workers: Nombre de workers de validation

    Example:
        >>> pool = ValidationWorkerPool(max_workers=4)
        >>> pool.start()
        >>> pool.submit_validation(chunk, translations)
        >>> pool.wait_completion()
        >>> pool.stop()

    Note:
        Le SaveWorker est unique pour garantir que les sauvegardes
        se font dans l'ordre et sans race conditions.
    """
    ...
```

### Docstrings de module

```python
"""
Module de validation structurelle des traductions.

Ce module fournit un système de validation multi-thread avec checks
paramétrables et corrections LLM ciblées. Il s'intègre au pipeline de
traduction pour garantir la qualité structurelle des traductions (nombre
de lignes, fragments, ponctuation, etc.).

Classes principales:
    ValidationWorkerPool: Pool de workers pour validation parallèle
    UnifiedValidationWorker: Cycle check-par-check et retry ciblé
    SaveWorker: Écriture différée via le ChunkPersister de la phase

Exemple d'utilisation:
    >>> from ebook_translator.validation import ValidationWorkerPool
    >>> pool = ValidationWorkerPool(num_workers=4, phase=phase)
    >>> pool.start()
    >>> # ... soumission de tâches ...
    >>> pool.wait_completion()
"""
```

---

## ⚠️ Gestion d'erreurs

### 1. Exceptions spécifiques

**Toujours lever des exceptions spécifiques, jamais `Exception` générique.**

```python
# ✅ BON : Exceptions spécifiques
if not translated_texts:
    raise ValueError(
        f"Aucune traduction trouvée pour le chunk {chunk.index}. "
        f"💡 Vérifiez que le LLM a bien retourné des traductions."
    )

if chunk.index < 0:
    raise ValueError(f"Index de chunk invalide : {chunk.index} (doit être >= 0)")

if not api_key:
    raise RuntimeError(
        "Clé API non configurée. "
        "🔧 Définissez DEEPSEEK_API_KEY dans .env ou les variables d'environnement."
    )

# ❌ MAUVAIS : Exception générique
if not translated_texts:
    raise Exception("Error")

if chunk.index < 0:
    raise Exception(f"Invalid index: {chunk.index}")
```

### 2. Messages d'erreur clairs

**Messages avec contexte et suggestions de résolution.**

```python
# ✅ BON : Contexte + suggestion
if line_count_original != line_count_translated:
    raise ValueError(
        f"Nombre de lignes différent :\n"
        f"  Original : {line_count_original} lignes\n"
        f"  Traduit  : {line_count_translated} lignes\n"
        f"  Chunk    : {chunk.index}\n"
        f"💡 Causes possibles :\n"
        f"  - Traduction incomplète du LLM\n"
        f"  - Numérotation incorrecte (<N/>)\n"
        f"🔧 Solutions :\n"
        f"  - Vérifier le prompt LLM\n"
        f"  - Activer le retry avec mode reasoning"
    )

# ❌ MAUVAIS : Message vague
if line_count_original != line_count_translated:
    raise ValueError("Line count mismatch")
```

### 3. Exceptions custom pour domaine métier

**Créer exceptions custom pour erreurs spécifiques au domaine.**

```python
# ✅ BON : Exceptions custom
class TranslationError(Exception):
    """Erreur lors de la traduction d'un chunk."""
    pass

class ValidationError(Exception):
    """Erreur lors de la validation d'une traduction."""

    def __init__(self, check_name: str, error_data: dict, chunk_index: int):
        self.check_name = check_name
        self.error_data = error_data
        self.chunk_index = chunk_index
        super().__init__(f"Validation failed: {check_name} (chunk {chunk_index})")

class RetryExhaustedError(TranslationError):
    """Toutes les tentatives de retry ont échoué."""

    def __init__(self, chunk_index: int, attempts: int, last_error: str):
        self.chunk_index = chunk_index
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(
            f"Retry exhausted for chunk {chunk_index} after {attempts} attempts. "
            f"Last error: {last_error}"
        )

# Utilisation
try:
    result = validate(chunk)
except ValidationError as e:
    logger.error(f"Validation failed: {e.check_name} for chunk {e.chunk_index}")
    # Récupération spécifique
```

### 4. Try/except avec contexte

**Catch spécifique, log avec contexte, re-raise si nécessaire.**

```python
# ✅ BON : Catch spécifique avec contexte
try:
    response = llm.query(prompt, content)
except APITimeoutError as e:
    logger.warning(
        f"⏱️ Timeout API pour chunk {chunk.index} "
        f"(tentative {attempt}/{max_retries}): {e}"
    )
    if attempt < max_retries - 1:
        time.sleep(retry_delay * (2 ** attempt))
        continue
    else:
        raise RetryExhaustedError(chunk.index, max_retries, str(e))

except RateLimitError as e:
    logger.warning(f"🚦 Rate limit atteint : {e}")
    time.sleep(retry_delay * (3 ** attempt))  # Backoff plus agressif
    continue

except Exception as e:
    logger.error(f"❌ Erreur inattendue pour chunk {chunk.index}: {e}")
    raise  # Re-raise pour ne pas masquer

# ❌ MAUVAIS : Catch trop large sans contexte
try:
    response = llm.query(prompt, content)
except Exception as e:
    print(f"Error: {e}")
```

---

## 📊 Logging

### 1. Logger structuré (pas de print)

**Toujours utiliser `logging`, jamais `print()`.**

```python
import logging

logger = logging.getLogger(__name__)

# ✅ BON : Logging avec niveaux appropriés
logger.debug(f"Début traduction chunk {chunk.index}")
logger.info(f"✅ Chunk {chunk.index} traduit avec succès")
logger.warning(f"⚠️ Retry nécessaire pour chunk {chunk.index} (tentative {attempt})")
logger.error(f"❌ Échec définitif chunk {chunk.index}: {error}")

# ❌ MAUVAIS : Utiliser print()
print(f"Chunk {chunk.index} traduit")
print(f"Error: {error}")
```

### 2. Niveaux de log appropriés

```python
# DEBUG : Détails techniques pour debugging
logger.debug(f"Paramètres LLM : model={model}, temp={temperature}")
logger.debug(f"Tokens utilisés : {token_count}/{max_tokens}")

# INFO : Opérations importantes et état nominal
logger.info(f"Démarrage traduction : {len(chunks)} chunks à traduire")
logger.info(f"✅ Chunk {index} validé (tentative {attempt})")

# WARNING : Situations anormales mais récupérables
logger.warning(f"⚠️ Retry nécessaire pour chunk {index}")
logger.warning(f"⏱️ Timeout API, nouvelle tentative dans {delay}s")

# ERROR : Erreurs qui empêchent l'opération
logger.error(f"❌ Validation échouée pour chunk {index} : {error}")
logger.error(f"❌ Échec après {max_retries} tentatives")

# CRITICAL : Erreurs critiques qui arrêtent le programme
logger.critical(f"🔥 Impossible de charger la configuration : {error}")
```

### 3. Logging contextuel

**Inclure suffisamment de contexte pour debugging.**

```python
# ✅ BON : Contexte complet
logger.info(
    f"Validation chunk {chunk.index} : "
    f"phase={phase}, "
    f"tentative={attempt}/{max_retries}, "
    f"checks=[{', '.join(c.name for c in checks)}]"
)

# ❌ MAUVAIS : Pas assez de contexte
logger.info("Validation en cours")
```

### 4. Emojis pour visibilité (optionnel)

```python
# ✅ Emojis pour catégories visuelles
logger.info(f"✅ Succès : chunk {index} validé")
logger.warning(f"⚠️ Avertissement : retry nécessaire")
logger.error(f"❌ Erreur : validation échouée")
logger.info(f"⏱️ Timeout : {delay}s")
logger.info(f"🚦 Rate limit : pause de {delay}s")
logger.info(f"💡 Suggestion : vérifier le prompt")
logger.info(f"🔧 Action : correction automatique activée")
```

---

## 🏗️ Architecture et Design

### 1. Principes SOLID

**Single Responsibility Principle**

```python
# ✅ BON : Une classe = une responsabilité
class ChunkValidator:
    """Valide uniquement les chunks."""
    def validate(self, chunk: Chunk) -> bool:
        ...

class ChunkCorrector:
    """Corrige uniquement les chunks invalides."""
    def correct(self, chunk: Chunk, errors: dict) -> Chunk:
        ...

# ❌ MAUVAIS : Classe qui fait trop
class ChunkProcessor:
    def validate(self, chunk: Chunk) -> bool:
        ...
    def correct(self, chunk: Chunk) -> Chunk:
        ...
    def translate(self, chunk: Chunk) -> str:
        ...
    def save(self, chunk: Chunk) -> None:
        ...
```

**Dependency Injection**

```python
# ✅ BON : Dépendances injectées
class Translator:
    def __init__(self, llm: LLM, validator: Validator):
        self.llm = llm
        self.validator = validator

    def translate(self, chunk: Chunk) -> str:
        translation = self.llm.query(...)
        if self.validator.validate(translation):
            return translation
        ...

# Utilisation (facile à tester avec mocks)
llm = LLM(api_key="...")
validator = Validator()
translator = Translator(llm, validator)

# ❌ MAUVAIS : Dépendances hardcodées
class Translator:
    def __init__(self):
        self.llm = LLM(api_key="hardcoded")  # Difficile à tester
        self.validator = Validator()
```

### 2. Immutabilité

**Préférer dataclasses frozen pour données immuables.**

```python
from dataclasses import dataclass

# ✅ BON : Dataclass immuable
@dataclass(frozen=True)
class Chunk:
    index: int
    body: list[str]
    head: list[str] | None = None
    tail: list[str] | None = None

# Impossible de modifier après création
chunk = Chunk(index=0, body=["text"])
# chunk.index = 1  # ❌ Erreur : FrozenInstanceError

# ❌ MOINS BON : Classe mutable
@dataclass
class Chunk:
    index: int
    body: list[str]

# Peut être modifié accidentellement
chunk = Chunk(index=0, body=["text"])
chunk.index = 1  # ✅ Mais peut créer des bugs subtils
```

### 3. Composition > Héritage

```python
# ✅ BON : Composition
class TranslationPipeline:
    def __init__(
        self,
        segmentator: Segmentator,
        translator: Translator,
        validator: Validator
    ):
        self.segmentator = segmentator
        self.translator = translator
        self.validator = validator

    def run(self) -> None:
        chunks = self.segmentator.get_all_segments()
        for chunk in chunks:
            translation = self.translator.translate(chunk)
            self.validator.validate(translation)

# ❌ MOINS BON : Héritage multiple
class TranslationPipeline(Segmentator, Translator, Validator):
    def run(self) -> None:
        chunks = self.get_all_segments()
        for chunk in chunks:
            translation = self.translate(chunk)
            self.validate(translation)
```

---

## 🧪 Tests

### 1. Organisation

**Structure miroir de src/ dans tests/.**

```
src/ebook_translator/
├── checks/
│   └── content/
│       └── line_count_check.py

tests/
├── checks/
│   └── test_line_count_check.py
```

### 2. Nommage

```python
# Format : test_<function>_<scenario>

class TestLineCountCheck:
    """Tests pour LineCountCheck."""

    def test_run_all_lines_present(self):
        """Vérifie que run() ne retourne aucun échec si toutes les lignes sont là."""
        ...

    def test_run_missing_lines(self):
        """Vérifie que run() signale les lignes absentes."""
        ...

    def test_relevant_indices_target_missing_lines(self):
        """Vérifie que relevant_indices porte bien les indices manquants."""
        ...
```

### 3. AAA Pattern (Arrange-Act-Assert)

```python
def test_run_unbalanced_quotes(self):
    """Vérifie la détection des paires de guillemets manquantes."""
    # Arrange : Setup
    check = PunctuationCheck()
    source = FakeChunkSource({0: "He said: « Hello. »"})
    data = LineIndexed({0: "Il dit : « Bonjour."})  # guillemet fermant manquant

    # Act : Exécution
    failures = check.run(data, source)

    # Assert : Vérification
    assert len(failures) == 1
    assert failures[0].error_type is ErreursType.PUNCTUATION_MISMATCH
    assert failures[0].relevant_indices == frozenset({0})
    assert failures[0].ctx["expected_pairs"] == 1
```

### 4. Mocking

```python
from unittest.mock import Mock, MagicMock, patch

# Mock d'objets
def test_translation_with_mock_llm(self):
    """Test traduction avec LLM mocké."""
    # Arrange
    mock_llm = Mock()
    mock_llm.query.return_value = "<0/>Bonjour\n[=[END]=]"

    translator = Translator(llm=mock_llm)
    chunk = Chunk(index=0, body=["Hello"])

    # Act
    result = translator.translate(chunk)

    # Assert
    assert result == {0: "Bonjour"}
    mock_llm.query.assert_called_once()

# Mock de fonctions/méthodes
def test_retry_with_backoff(self):
    """Test retry avec backoff exponentiel."""
    with patch('time.sleep') as mock_sleep:
        # ... test sans vraiment attendre ...
        mock_sleep.assert_called_with(2.0)  # Vérifie le délai
```

### 5. Fixtures pytest

```python
import pytest

@pytest.fixture
def sample_chunk() -> Chunk:
    """Fixture : chunk de test standard."""
    return Chunk(
        index=42,
        body=["Line 1", "Line 2"],
        head=["Context"],
        tail=None
    )

@pytest.fixture
def mock_llm() -> Mock:
    """Fixture : LLM mocké."""
    llm = Mock()
    llm.query.return_value = "<0/>Translation\n[=[END]=]"
    return llm

def test_with_fixtures(sample_chunk, mock_llm):
    """Test utilisant les fixtures."""
    translator = Translator(llm=mock_llm)
    result = translator.translate(sample_chunk)
    assert result is not None
```

---

## 🎨 Style et formatage

### Configuration automatique

**Tous les outils sont configurés dans `pyproject.toml`.**

```bash
# Formater le code
uv run black src/ tests/

# Linting (les règles I de ruff trient aussi les imports)
uv run ruff check src/ tests/
uv run ruff check --fix src/ tests/  # Auto-fix

# Tout en une fois
uv run pre-commit run --all-files
```

### Conventions

- **Ligne max** : 88 caractères (black default)
- **Imports** : Triés par les règles `I` de ruff (stdlib, third-party, local)
- **Quotes** : Doubles quotes `"` préférées (black default)
- **Indentation** : 4 espaces (jamais tabs)

---

## 📚 Résumé : Checklist qualité

### Avant chaque commit

- [ ] Tous les paramètres/retours typés
- [ ] basedpyright strict sans erreurs
- [ ] Docstrings format Google UNIQUEMENT pour nouvelles fonctions publiques
- [ ] Exceptions spécifiques (pas `Exception`)
- [ ] Logging au lieu de print()
- [ ] Tests unitaires ajoutés
- [ ] Pre-commit hooks OK

### Vérification

```bash
uv run pytest                       # Tests
uv run basedpyright src/                 # Types
uv run pre-commit run --all-files   # Qualité
```

---

**Bon code ! 🚀**
