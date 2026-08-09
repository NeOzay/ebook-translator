"""
Système de glossaire unifié pour cohérence terminologique.

Ce module fournit un glossaire qui combine :
- Apprentissage automatique depuis paires texte/traduction
- Validation post-traduction et détection de conflits
- Export formaté pour injection dans prompts LLM
- Persistance JSON avec reload automatique

Utilisé à la fois pour :
- Phase 1 : Apprentissage automatique des traductions
- Phase 2 : Injection du glossaire dans le prompt d'affinage
- Validation : Détection d'incohérences terminologiques
"""

import json
import math
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Self, TypedDict, cast

from template.phase.glossary_models import GlossaryEntrySexe, GlossaryEntryType

if TYPE_CHECKING:
    from template.phase.glossary_models import (
        GlossaryEntry,
        GlossaryMultipleValueEntry,
        LLMTermeGlossary,
    )


def _get_most_frequent[S: str](d: dict[S, int]) -> S | None:
    if not d:
        return None
    return max(d, key=lambda k: d[k])


def _compute_confidence(d: list[int]) -> float:
    if not d or sum(d) == 0:
        return 0.0

    total = sum(d)
    max_val = max(d)
    ratio = max_val / total
    dominance = math.pow(ratio, 0.5)
    k = 2
    masse = total / (total + k)
    score = dominance * masse
    return round(score, 2)


def _compute_dominance(d: list[int]) -> float:
    """Stabilité pure, sans facteur de masse."""
    if not d or sum(d) == 0:
        return 0.0
    total = sum(d)
    max_val = max(d)
    return round(math.pow(max_val / total, 0.5), 2)


def _get_possible_translations[S: str](
    d: dict[S, int], threshold: float = 0.7
) -> list[tuple[S, int]]:
    """
    Retourne les traductions possibles en ajoutant des propositions
    jusqu'à ce que la confiance cumulée atteigne le seuil.
    Utilise la même formule que compute_confidence, appliquée
    sur la fraction couverte de la distribution originale.
    """
    if not d:
        return []

    total = sum(d.values())
    d_sorted = sorted(d.items(), key=lambda t: t[1], reverse=True)
    collected: list[tuple[S, int]] = []
    covered = 0

    for name, occurrence in d_sorted:
        collected.append((name, occurrence))
        covered += occurrence
        # ratio couvert de la distribution originale
        ratio = covered / total
        # même transformation que compute_confidence
        dominance = math.pow(ratio, 0.5)
        k = 2
        masse = total / (total + k)
        score = dominance * masse
        if score >= threshold:
            return collected

    return collected


def _get_confidence_level(score: float) -> Literal["low", "medium", "high"]:
    if score >= 0.7:
        return "high"
    elif score >= 0.6:
        return "medium"
    else:
        return "low"


DEFAULT_MIN_REINJECTION_WEIGHT = 3
"""Poids à partir duquel un terme est réinjecté avec ses propositions.

Seuil de partage de `glossary_existing_block.jinja`. Tous les termes présents
dans le bloc sont montrés au LLM ; en deçà de ce poids, seule leur forme l'est,
sans les traductions candidates — assez pour que le modèle réutilise la même clé
plutôt qu'une variante, pas assez pour l'ancrer sur une proposition isolée.
"""


DEFAULT_MAX_REINJECTED_TERMS = 80
"""Borne du nombre de termes réinjectés dans le prompt de la phase glossaire.

Borne de prompt, pas jugement de pertinence : sur un livre long au glossaire
appris en cours de route, un bloc emploie une cinquantaine de termes connus au
plus, et le plafond ne mord jamais. Il n'existe que pour le cas où le glossaire
a été prérempli — import de plusieurs tomes, seed — où rien ne limiterait
autrement la taille d'un fragment que son contenu variable empêche de mettre
en cache.
"""

ReinjectionGroup = Literal["arbitrer", "emergent", "valide"]
"""Groupe d'affichage d'un terme dans `glossary_existing_block.jinja`."""

_ORDRE_REINJECTION: dict[ReinjectionGroup, int] = {
    "arbitrer": 0,
    "emergent": 1,
    "valide": 2,
}
"""Priorité de conservation quand le plafond mord.

Un terme *à arbitrer* est la raison d'être du bloc : le taire fige son conflit.
Un terme *émergent* coûte quelques tokens et, invisible, revient sous une forme
voisine qui divise son poids — c'est le mal que le bloc existe pour éviter. Un
terme *validé* n'est là qu'en rappel : l'omettre fait au pire réémettre un terme
déjà stable, qui ne bougera pas pour autant.
"""


def reinjection_group(
    entry: GlossaryMultipleValueEntry,
    min_reinjection_weight: int = DEFAULT_MIN_REINJECTION_WEIGHT,
) -> ReinjectionGroup:
    """Groupe sous lequel le prompt présentera ce terme.

    Reproduit le découpage de `common/glossary_existing_block.jinja`, qui trie
    sur les deux mêmes champs. Toute modification de l'un doit suivre dans
    l'autre.

    Args:
        entry: Entrée multi-propositions du terme.
        min_reinjection_weight: Poids à partir duquel les propositions sont
            montrées.

    Returns:
        `valide`, `arbitrer` ou `emergent`.

    Example:
        >>> reinjection_group({"terme": "x", "traductions": [], "types": [],
        ...                    "sexes": [], "weight": 1, "confidence": "low"})
        'emergent'
    """
    if entry["confidence"] == "high":
        return "valide"
    if entry["weight"] >= min_reinjection_weight:
        return "arbitrer"
    return "emergent"


def confidence_level(weights: Sequence[int]) -> Literal["low", "medium", "high"]:
    """Niveau de confiance d'une distribution de propositions.

    Args:
        weights: Effectifs des propositions concurrentes d'un même terme.

    Returns:
        `low`, `medium` ou `high`.

    Example:
        >>> confidence_level([5])
        'high'
    """
    return _get_confidence_level(_compute_confidence(list(weights)))


def converged_weight(search_limit: int = 100) -> int:
    """Poids unanime minimal pour qu'un terme atteigne la confiance haute.

    Un terme n'est retiré de la sortie attendue (`Termes validés — NE PAS
    inclure`) qu'une fois `high`. Le facteur de masse `total / (total + 2)`
    borne donc par le bas le nombre d'émissions nécessaires, même sans le
    moindre désaccord : un livre plus court que ce seuil ne peut faire
    converger aucun terme.

    Args:
        search_limit: Poids au-delà duquel la recherche abandonne.

    Returns:
        Le premier poids unanime classé `high`, ou `search_limit` si aucun
        ne l'atteint.

    Example:
        >>> converged_weight()
        5
    """
    for poids in range(1, search_limit + 1):
        if confidence_level([poids]) == "high":
            return poids
    return search_limit


def _bump_casing(casing: dict[str, dict[str, int]], key: str, surface: str) -> None:
    """Enregistre une graphie observée pour une proposition.

    Args:
        casing: Graphies mémorisées du terme, par proposition minuscule.
        key: Proposition en minuscules, clé de décompte.
        surface: Proposition telle que le LLM l'a écrite.
    """
    graphies = casing.setdefault(key, {})
    graphies[surface] = graphies.get(surface, 0) + 1


def _preferred_casing(casing: dict[str, dict[str, int]], key: str) -> str:
    """Graphie à restituer pour une proposition.

    Args:
        casing: Graphies mémorisées du terme, par proposition minuscule.
        key: Proposition en minuscules.

    Returns:
        La graphie la plus fréquemment observée, ou la clé minuscule si aucune
        n'a été mémorisée — cas d'un cache écrit avant que la casse soit suivie.
    """
    graphies = casing.get(key)
    if not graphies:
        return key
    return max(graphies, key=lambda forme: (graphies[forme], forme))


class GlossaryStatistics(TypedDict):
    total_terms: int
    user_terms: int
    conflicting_terms: int


class Glossary:
    class _Entry(TypedDict):
        translations: dict[str, int]
        term_types: dict[GlossaryEntryType, int]
        sexes: dict[GlossaryEntrySexe, int]
        translation_casing: dict[str, dict[str, int]]

    @staticmethod
    def _new_entry() -> Glossary._Entry:
        return {
            "translations": defaultdict(int),
            "term_types": defaultdict(int),
            "sexes": defaultdict(int),
            "translation_casing": defaultdict(lambda: defaultdict(int)),
        }

    """
    Glossaire unifié pour cohérence terminologique.

    Gère l'apprentissage automatique, la validation et l'export de traductions
    de noms propres et termes techniques pour garantir la cohérence.

    Features:
    - learn(): Apprentissage terme par terme
    - learn_pair(): Apprentissage depuis textes complets avec extraction auto
    - get_translation(): Récupération avec seuil de confiance
    - export_for_prompt(): Export formaté pour prompts LLM
    - get_conflicts(): Détection d'incohérences
    - Persistance JSON automatique

    Example:
        >>> glossary = Glossary(Path("cache/glossary.json"))
        >>> # Apprentissage basique
        >>> glossary.learn("Matrix", "Matrice")
        >>> # Apprentissage depuis paire
        >>> glossary.learn_pair(
        ...     "Dr. Sakamoto activated the Matrix.",
        ...     "Le Dr Sakamoto activa la Matrice."
        ... )
        >>> # Export pour prompt
        >>> prompt_glossary = glossary.export_for_prompt()
        >>> # 'Matrix → Matrice, Sakamoto → Sakamoto'
    """

    def __init__(self, cache_path: Path | str | None = None):
        """
        Initialise le glossaire.

        Args:
            cache_path: Chemin optionnel pour sauvegarder/charger le glossaire
        """
        self._glossary: dict[str, Glossary._Entry] = defaultdict(self._new_entry)
        # {terme_source: traduction_validée}
        self._user: dict[str, GlossaryEntry] = {}
        self._entries_cache: dict[str, GlossaryEntry] = {}
        cache_path = Path(cache_path) if cache_path else None

        self.cache_path: Path | None = None
        if cache_path and cache_path.exists():
            self.cache_path = cache_path
            self._load_from_cache()

    # =========================================================================
    # API basique : Apprentissage et récupération
    # =========================================================================

    def learn(self, term: LLMTermeGlossary) -> None:
        """
        Enregistre une traduction observée.

        Deux cas sont ignorés, l'un et l'autre parce que la question est déjà
        tranchée :

        - le terme est **validé manuellement** — l'entrée `user` fait autorité ;
        - le terme a **convergé** (confiance haute). Le prompt le liste alors
          sous « Termes validés — NE PAS inclure », consigne que le modèle
          suit mal : mesuré sur un tome complet, 10 termes convergés sur 11
          sont réémis, jusqu'à 13 fois pour le plus fréquent. Renforcer la
          consigne n'y change rien et coûte du rappel ; le filtre est donc
          posé ici, où il ne dépend pas de l'obéissance du modèle.

        La comparaison porte sur la forme minuscule, seule forme sous laquelle
        les clés `user` sont rangées — le LLM, lui, émet le terme dans sa casse
        d'origine.

        Note:
            Le gel est total, contradictions comprises : une fois la confiance
            haute atteinte, le terme n'est plus candidat à révision. Une entrée
            `user` peut encore le **masquer** — `collect_entry` la place en tête
            et écarte le terme appris — mais rien ne modifie plus la
            distribution elle-même.

            Compter les seules propositions divergentes aurait l'effet inverse
            de celui recherché : la dominante cessant d'être alimentée, un
            désaccord isolé suffirait à faire chuter la confiance d'un terme
            pourtant stable.

        Args:
            term: Dictionnaire avec les clés "terme", "proposition_traduction", "type", "sexe"
        """
        source_term = term["terme"].lower()
        if source_term in self._user:
            return

        # `_glossary` est un defaultdict : passer par `get` pour ne pas créer
        # l'entrée du terme au moment même où l'on teste s'il en a une.
        connu = self._glossary.get(source_term)
        if (
            connu is not None
            and confidence_level(list(connu["translations"].values())) == "high"
        ):
            return

        proposition = term["proposition_traduction"]
        translated_term = proposition.lower()
        term_type = cast(GlossaryEntryType, term["type"].lower())
        sexe = cast(GlossaryEntrySexe, term["sexe"].lower())

        entry = self._glossary[source_term]
        # Incrémenter le compteur. Le décompte porte sur la forme minuscule :
        # `Jean` et `jean` sont la même proposition et doivent cumuler leur
        # poids. La graphie, elle, est retenue à part pour être restituée.
        entry["translations"][translated_term] += 1
        entry["term_types"][term_type] += 1
        entry["sexes"][sexe] += 1
        _bump_casing(entry["translation_casing"], translated_term, proposition)

        self._entries_cache.pop(source_term, None)

    def get_translation(
        self,
        source_term: str,
    ) -> GlossaryEntry | None:
        """
        Récupère la traduction recommandée d'un terme.

        Retourne la traduction validée, ou à défaut la plus fréquente
        si elle dépasse le seuil de confiance.

        Args:
            source_term: Le terme à traduire
            min_confidence: Seuil de confiance minimum (ratio de la traduction dominante)

        Returns:
            Traduction recommandée, ou None si aucune traduction fiable

        Example:
            >>> glossary.get_translation("Matrix")
            'Matrice'
            >>> glossary.get_translation("UnknownTerm")
            None
        """
        # 1. Vérifier s'il y a une traduction validée manuellement
        # if source_term in self._validated:
        #     return self._validated[source_term]

        # 2. Sinon, chercher dans les traductions apprises
        if source_term not in self._glossary:
            return None

        if source_term in self._entries_cache:
            return self._entries_cache[source_term]

        term = self._glossary[source_term]
        translation = _get_most_frequent(term["translations"])
        if not translation:
            return None

        translation_weigths = list(term["translations"].values())
        confidance = _get_confidence_level(_compute_confidence(translation_weigths))
        if confidance == "low" and _compute_dominance(translation_weigths) < 0.95:
            return None
        term_type = _get_most_frequent(term["term_types"])
        if not term_type:
            return None
        sexe = _get_most_frequent(term["sexes"]) or "nc"
        weight = sum(term["translations"].values())

        entry: GlossaryEntry = {
            "terme": source_term,
            "traduction": _preferred_casing(term["translation_casing"], translation),
            "type": term_type,
            "sexe": sexe,
            "weight": weight,
            "confidence": confidance,
        }
        self._entries_cache[source_term] = entry
        return entry

    def get_translations_until_confidence(
        self, source_term: str, confidence: float
    ) -> GlossaryMultipleValueEntry | None:
        """
        Revoir les traductions possibles d'un terme jusqu'à atteindre un seuil de confiance cumulé.
        """
        if source_term not in self._glossary:
            return None
        if source_term in self._user:
            return None  # Les entrées user sont considérées comme fiables à 100% (pas de conflit)

        term = self._glossary[source_term]
        weight = sum(term["translations"].values())
        _get_possible_translations(term["translations"], confidence)

        v = _compute_confidence(list(term["translations"].values()))

        return {
            "terme": source_term,
            "traductions": [
                (_preferred_casing(term["translation_casing"], proposition), poids)
                for proposition, poids in _get_possible_translations(
                    term["translations"], confidence
                )
            ],
            "types": _get_possible_translations(term["term_types"], confidence),
            "sexes": _get_possible_translations(term["sexes"], confidence),
            "weight": weight,
            "confidence": _get_confidence_level(v),
        }

    def add_user_translation(
        self,
        terme: str,
        translation: str,
        sexe: GlossaryEntrySexe,
        terme_type: GlossaryEntryType,
    ) -> Self:
        """
        Valide manuellement une traduction.

        Les traductions validées ont priorité sur celles apprises automatiquement.

        La clé est normalisée en minuscules : les deux collecteurs cherchent le
        terme dans un texte déjà passé en minuscules et excluent les entrées
        apprises par `terme_lower in self._user`. Une clé conservée dans sa
        casse d'origine ne serait jamais retrouvée, ni dans le texte ni dans
        cette exclusion.

        Args:
            terme: Terme source.
            translation: Traduction validée.
            sexe: Genre grammatical portant les accords en langue cible.
            terme_type: Catégorie du terme.

        Returns:
            Le glossaire, pour chaînage.

        Example:
            >>> glossary.add_user_translation("Matrix", "Matrice", "f", "terme_technique")
            >>> # Cette traduction sera toujours utilisée
        """
        cle = terme.lower()
        term: GlossaryEntry = {
            "terme": cle,
            "traduction": translation,
            "type": terme_type,
            "sexe": sexe,
            "confidence": "high",
        }

        self._user[cle] = term
        return self

    # =========================================================================
    # Export et validation
    # =========================================================================

    def collect_entry(self, text: str, max_terms: int = 25) -> list[GlossaryEntry]:
        """
        Collecte les entrées de glossaire à partir d'un texte.

        Les entrées user sont incluses en priorité (sans tri).
        Les entrées apprises sont triées par : occurrences dans le texte (desc),
        puis poids historique (desc).

        Args:
            text: Texte à analyser
            max_terms: Nombre maximum de termes à retourner

        Returns:
            Liste d'entrées de glossaire extraites

        Example:
            >>> entries = glossary.collect_entry(chunk)
            >>> # [GlossaryEntry(term='Matrix', traduction='Matrice', ...), ...]
        """
        text = text.lower()
        result: list[GlossaryEntry] = []
        for terme in self._user:
            if terme in text:
                result.append(self._user[terme])

        if len(result) >= max_terms:
            return result

        entries: list[tuple[int, GlossaryEntry]] = []
        for terme in self._glossary:
            terme_lower = terme.lower()
            if terme_lower in self._user:
                continue
            count = text.count(terme_lower)
            if count == 0:
                continue
            entry = self.get_translation(terme)
            if entry:
                entries.append((count, entry))

        entries.sort(key=lambda t: (t[0], t[1].get("weight", 0)), reverse=True)
        result.extend(e for _, e in entries[: max_terms - len(result)])
        return result

    def collect_entry_with_conflicts(
        self,
        text: str,
        confidence_accumulate: float = 0.7,
        max_terms: int = DEFAULT_MAX_REINJECTED_TERMS,
        min_reinjection_weight: int = DEFAULT_MIN_REINJECTION_WEIGHT,
    ) -> list[GlossaryMultipleValueEntry]:
        """Collecte les termes déjà appris que le bloc courant emploie.

        Aucun filtre de poids : un terme trop léger pour être arbitré doit
        quand même être montré, sans quoi il reste invisible au LLM, qui le
        réémet sous une forme voisine et divise d'autant son poids. Le tri par
        poids revient à `glossary_existing_block.jinja`, qui montre les
        propositions au-delà de `DEFAULT_MIN_REINJECTION_WEIGHT` et la seule
        forme du terme en deçà.

        `max_terms` n'est pas un filtre mais une borne du prompt, et il ne
        s'applique qu'au-delà de ce qu'un livre produit de lui-même. En deçà,
        les entrées sortent dans l'ordre de découverte, inchangé. Quand il
        mord, la troncature suit `_ORDRE_REINJECTION` avant les occurrences :
        garder les termes les plus fréquents reviendrait à sacrifier d'abord
        les émergents, rares par construction, qui sont précisément ceux que
        l'invisibilité condamne à ne jamais converger.

        Args:
            text: Texte du bloc courant.
            confidence_accumulate: Couverture visée par les propositions listées.
            max_terms: Nombre maximum de termes réinjectés.
            min_reinjection_weight: Poids séparant les termes à arbitrer des
                termes émergents, pour la priorité de troncature.

        Returns:
            Une entrée par terme appris présent dans le bloc, entrées `user`
            exclues, dans la limite de `max_terms`.
        """
        text = text.lower()
        collected: list[tuple[int, int, GlossaryMultipleValueEntry]] = []
        for terme in self._glossary:
            terme_lower = terme.lower()
            if terme_lower in self._user:
                continue
            count = text.count(terme_lower)
            if count == 0:
                continue
            entry = self.get_translations_until_confidence(terme, confidence_accumulate)
            if entry:
                groupe = reinjection_group(entry, min_reinjection_weight)
                collected.append((_ORDRE_REINJECTION[groupe], count, entry))

        if len(collected) > max_terms:
            collected.sort(key=lambda t: (t[0], -t[1], -t[2]["weight"]))
            del collected[max_terms:]

        return [entry for _, _, entry in collected]

    def get_conflicts(self) -> dict[str, GlossaryMultipleValueEntry]:
        """
        Identifie les termes avec des traductions conflictuelles.

        Retourne les termes dont au moins un champ (traductions, types, sexes) est
        ambigu — aucune valeur ne domine à >70%. Chaque champ conflictuel est
        inclus avec ses compteurs d'occurrences, triés par fréquence décroissante.

        Returns:
            Dictionnaire {terme: ConflictDetail} où ConflictDetail contient
            uniquement les champs en conflit avec leurs compteurs.

        Example:
            >>> conflicts = glossary.get_conflicts()
            >>> # {'matrix': {'translations': {'matrice': 5, 'système': 4}}}
        """
        conflicts: dict[str, GlossaryMultipleValueEntry] = {}

        for source_term in self._glossary:
            if source_term in self._user:
                continue
            detail = self.get_translations_until_confidence(source_term, confidence=1)

            if detail and detail["confidence"] != "high":
                conflicts[source_term] = detail

        return conflicts

    def print_valided(self) -> None:
        for _term in sorted(
            self._glossary.items(),
            key=lambda t: sum(t[1]["translations"].values()),
            reverse=True,
        ):
            term = self.get_translation(_term[0])
            if not term:
                continue
            print(
                f"{term['terme']} ({term['confidence']}, {term.get('weight', '?')}) → {term['traduction']} (type: {term['type']}, sexe: {term['sexe']})"
            )

    def print_conflicts(self) -> None:
        """
        Affiche les conflits terminologiques sous forme lisible.

        Pour chaque terme conflictuel, liste les valeurs en compétition
        avec leur nombre d'occurrences.

        Example:
            >>> glossary.print_conflicts()
            >>> # matrix:
            >>> #   traductions: matrice (5), système (4)
        """
        conflicts = self.get_conflicts()
        if not conflicts:
            print("Aucun conflit détecté.")
            return

        def _fmt[Str: str](counts: list[tuple[Str, int]]) -> str:
            return ", ".join(f"{v} ({n})" for (v, n) in counts)

        for term in sorted(conflicts.values(), key=lambda d: d["weight"], reverse=True):
            print(f"{term['terme']} ({term['confidence']}): w = {term['weight']}")
            if "traductions" in term:
                print(f"  traductions: {_fmt(term['traductions'])}")
            if "types" in term:
                print(f"  types: {_fmt(term['types'])}")
            if "sexes" in term:
                print(f"  sexes: {_fmt(term['sexes'])}")
            print()

    # =========================================================================
    # Statistiques et utilitaires
    # =========================================================================

    def get_term_count(self) -> int:
        """
        Retourne le nombre de termes dans le glossaire.

        Returns:
            Nombre de termes uniques
        """
        return len(self._glossary)

    def get_statistics(self) -> GlossaryStatistics:
        """
        Retourne des statistiques sur le glossaire.

        Returns:
            Dictionnaire avec les stats

        Example:
            >>> stats = glossary.get_statistics()
            >>> print(f"Termes: {stats['total_terms']}, Conflits: {stats['conflicting_terms']}")
        """
        return GlossaryStatistics(
            total_terms=len(self._glossary),
            user_terms=len(self._user),
            conflicting_terms=len(self.get_conflicts()),
        )

    # =========================================================================
    # Nettoyage du glossaire
    # =========================================================================

    # =========================================================================
    # Persistance
    # =========================================================================

    def save(self, path: Path | None = None) -> None:
        """
        Sauvegarde le glossaire sur disque.

        Args:
            path: Chemin de sauvegarde (utilise cache_path si non fourni)

        Raises:
            ValueError: Si aucun chemin fourni
        """
        save_path = path or self.cache_path
        if not save_path:
            raise ValueError("No save path provided")

        save_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "glossary": {
                source: dict(translations)
                for source, translations in self._glossary.items()
            },
            "user": self._user,
        }

        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def clean_all(self) -> None:
        """Vide toutes les entrées apprises du glossaire."""
        self._glossary.clear()
        self._entries_cache.clear()

    def import_from_volume(self, path: Path, decay: float = 0.1) -> None:
        """
        Importe un glossaire d'un volume précédent en appliquant un decay aux poids.

        Les counts de chaque traduction sont multipliés par `decay`, puis arrondis
        à l'entier supérieur (min 1) pour préserver la confiance relative sans
        gonfler les poids face aux nouveaux termes du volume courant.
        Les entrées user sont fusionnées sans decay (priorité absolue).

        Args:
            path: Chemin vers le glossaire JSON du volume précédent
            decay: Facteur multiplicatif appliqué aux counts (défaut: 0.1)

        Raises:
            ValueError: Si decay n'est pas dans ]0, 1]

        Example:
            >>> glossary = Glossary(Path("cache/vol2/glossary.json"))
            >>> glossary.import_from_volume(Path("cache/vol1/glossary.json"), decay=0.1)
        """
        import math

        if not (0 < decay <= 1):
            raise ValueError(f"decay must be in ]0, 1], got {decay}")

        if not path.exists():
            return

        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"⚠️ Erreur lors du chargement du glossaire précédent: {e}")
            return

        for source, entry in data.get("glossary", {}).items():
            for trans, count in entry.get("translations", {}).items():
                decayed = max(1, math.ceil(count * decay))
                self._glossary[source]["translations"][trans] += decayed
            for term_type, count in entry.get("term_types", {}).items():
                decayed = max(1, math.ceil(count * decay))
                self._glossary[source]["term_types"][term_type] += decayed
            for sexe, count in entry.get("sexes", {}).items():
                decayed = max(1, math.ceil(count * decay))
                self._glossary[source]["sexes"][sexe] += decayed
            # Les graphies ne subissent pas le decay : elles ne pondèrent rien,
            # elles départagent l'écriture d'une proposition déjà pondérée.
            for proposition, graphies in entry.get("translation_casing", {}).items():
                for surface, count in graphies.items():
                    cible = self._glossary[source]["translation_casing"].setdefault(
                        proposition, {}
                    )
                    cible[surface] = cible.get(surface, 0) + count

        # Entrées user : fusion sans decay (la traduction validée reste valide).
        # La clé est normalisée comme dans `add_user_translation` — un cache
        # écrit avant cette normalisation peut porter des clés en casse mixte.
        for terme, entry in data.get("user", {}).items():
            cle = terme.lower()
            if cle not in self._user:
                self._user[cle] = entry

        self._entries_cache.clear()

    def _load_from_cache(self) -> None:
        """Charge le glossaire depuis le cache."""
        if not self.cache_path or not self.cache_path.exists():
            return
        self.import_from_volume(self.cache_path, decay=1.0)

    def __repr__(self) -> str:
        """Représentation pour le debug."""
        stats = self.get_statistics()
        return (
            f"Glossary(\n"
            f"  termes: {stats['total_terms']}\n"
            f"  user: {stats['user_terms']}\n"
            f"  conflits: {stats['conflicting_terms']}\n"
            f")"
        )

    def __len__(self) -> int:
        """Nombre de termes dans le glossaire."""
        return self.get_term_count()

    def __str__(self) -> str:
        """Représentation textuelle du glossaire."""
        return self.__repr__()
