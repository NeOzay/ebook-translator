"""Protocol `ContentCheck` : validation post-parsing du payload typé.

Sépare deux responsabilités :

- **schéma** : le modèle Pydantic (`ConvertibleModel[...]`) garantit la
  structure (parsing, indices uniques, marqueur de fin...).
- **contenu** : un `ContentCheck` vérifie la fidélité au source (couverture
  des lignes, paires de fragments, ponctuation, phrases...).

Un check ne tourne jamais si le schéma est KO ; il reçoit donc toujours un
payload structurellement valide. Son `ctx` est purement diagnostique :
aucune fuite d'environnement (target_language, glossaire, source_text...).
L'environnement est injecté plus tard par le `build` du `RETRY_REGISTRY`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, ClassVar, Protocol

from template.types import ConvertibleModel

from ..validation.diagnostics import ErreursType
from ..validation.failure import ValidationFailure
from ..validation.retry_strategy import RetryStrategy


class ChunkSource(Protocol):
    """Vue read-only du chunk source consommée par les `ContentCheck`.

    `line_indices` : liste des indices de ligne attendus (utilisé par
    `LineCountCheck` pour la couverture).
    `text_at(index)` : texte source de la ligne `index`, utilisé par les
    checks Fragment / Punctuation / Sentence pour dériver les comptes
    attendus.

    Doit lever `KeyError` si `index` n'existe pas dans la source.
    """

    @property
    def line_indices(self) -> Iterable[int]: ...

    def text_at(self, index: int) -> str: ...


class ContentCheck[M: ConvertibleModel[Any], CtxT: Mapping[str, Any]](Protocol):
    """Validation contenu d'un payload typé contre la source du chunk.

    Trois `ClassVar` portent les métadonnées du check :

    - `error_type` : code d'erreur stable, clé du `RETRY_REGISTRY`.
    - `retry_strategy` : politique de bascule de modèle entre tentatives
      (un check de fragments peut vouloir reasoning dès T1, un check de
      ponctuation rester normal). Décision **par erreur**, pas par phase.
    - `max_attempts` : nombre max de tentatives (T0 + retries) avant rejet.
      Permet de limiter le coût d'un check qui rate souvent.

    Cela permet à `RETRY_REGISTRY[check.error_type]` et au worker de
    fonctionner sans instancier le check ni connaître la phase.
    """

    error_type: ClassVar[ErreursType]
    retry_strategy: ClassVar[RetryStrategy]
    max_attempts: ClassVar[int]

    def run(self, payload: M, source: ChunkSource) -> list[ValidationFailure[CtxT]]:
        """Retourne la liste des failures détectées. Vide si payload conforme.

        Sémantique :
            - 0 failure : check passe.
            - 1 failure agrégée : le retry template associé est batch
              (cf. `LineCountCheck`, `SentenceCheck`).
            - N failures : le retry template associé est mono-ligne
              (cf. `FragmentCountCheck`, `PunctuationCheck`).

        Le worker traite les failures séquentiellement ; chaque retry
        produit un nouveau payload qui repasse l'ensemble des checks.
        """
        ...
