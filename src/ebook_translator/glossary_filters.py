"""
Filtres pour nettoyage du glossaire.

Ce module fournit des listes de mots à exclure du glossaire terminologique :
- Mots grammaticaux (articles, pronoms, prépositions, etc.)
- Mots très courants qui ne devraient pas être dans un glossaire
- Helpers pour détection d'erreurs d'extraction
"""

# Mots grammaticaux à TOUJOURS exclure du glossaire
# Ces mots sont contextuels et varient selon la phrase
GRAMMATICAL_STOPWORDS = {
    # Articles
    "a",
    "an",
    "the",
    # Pronoms personnels
    "i",
    "you",
    "he",
    "she",
    "it",
    "we",
    "they",
    "me",
    "him",
    "her",
    "us",
    "them",
    # Pronoms possessifs
    "my",
    "your",
    "his",
    "her",
    "its",
    "our",
    "their",
    "mine",
    "yours",
    "hers",
    "ours",
    "theirs",
    # Pronoms démonstratifs
    "this",
    "that",
    "these",
    "those",
    # Prépositions
    "in",
    "on",
    "at",
    "by",
    "with",
    "from",
    "to",
    "of",
    "for",
    "about",
    "after",
    "before",
    "behind",
    "beside",
    "between",
    "among",
    "through",
    "during",
    "above",
    "below",
    "under",
    "over",
    "into",
    "onto",
    "upon",
    "across",
    "along",
    "around",
    "near",
    "against",
    "toward",
    "towards",
    "within",
    "without",
    # Conjonctions
    "and",
    "or",
    "but",
    "so",
    "yet",
    "for",
    "nor",
    "as",
    "if",
    "although",
    "though",
    "because",
    "since",
    "unless",
    "until",
    "while",
    "when",
    "where",
    "whether",
    # Auxiliaires (be, have, do, modaux)
    "am",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "having",
    "do",
    "does",
    "did",
    "doing",
    "can",
    "could",
    "will",
    "would",
    "shall",
    "should",
    "may",
    "might",
    "must",
    # Déterminants
    "all",
    "any",
    "some",
    "many",
    "much",
    "few",
    "little",
    "more",
    "most",
    "each",
    "every",
    "both",
    "either",
    "neither",
    "other",
    "another",
    "such",
    # Adverbes très courants
    "very",
    "too",
    "quite",
    "rather",
    "really",
    "just",
    "only",
    "also",
    "even",
    "still",
    "already",
    "yet",
    "again",
    "once",
    "twice",
    "always",
    "never",
    "often",
    "sometimes",
    "usually",
    "here",
    "there",
    "now",
    "then",
    "soon",
    "later",
    "ago",
    "today",
    "tomorrow",
    "yesterday",
    # Verbes très courants/génériques
    "come",
    "go",
    "get",
    "make",
    "take",
    "bring",
    "put",
    "give",
    "keep",
    "let",
    "seem",
    "become",
    "turn",
    # Mots de liaison
    "well",
    "oh",
    "yes",
    "no",
    "okay",
    "ok",
    "anyway",
    "however",
    "therefore",
    "moreover",
    "furthermore",
    "meanwhile",
    "otherwise",
    # Pronoms interrogatifs
    "who",
    "whom",
    "whose",
    "what",
    "which",
    "why",
    "how",
    # Onomatopées/Interjections très courantes
    "ah",
    "oh",
    "uh",
    "um",
    "hmm",
    "huh",
    "hey",
    "wow",
}

# Patterns de mots à exclure
# Utilisés pour filtrage additionnel
EXCLUDE_PATTERNS = {
    "single_letter": lambda word: len(word) == 1,  # A, B, C, etc.
    "two_letters_lowercase": lambda word: len(word) == 2
    and word.islower(),  # am, is, at, etc.
}


def is_grammatical_stopword(word: str) -> bool:
    """
    Vérifie si un mot est un stopword grammatical.

    Args:
        word: Mot à vérifier

    Returns:
        True si le mot est un stopword, False sinon

    Example:
        >>> is_grammatical_stopword("the")
        True
        >>> is_grammatical_stopword("Matrix")
        False
    """
    return word.lower() in GRAMMATICAL_STOPWORDS


def should_exclude_from_glossary(word: str) -> bool:
    """
    Détermine si un mot doit être exclu du glossaire.

    Critères d'exclusion :
    - Mots grammaticaux (stopwords)
    - Mots très courts (<= 2 chars) sauf noms propres
    - Mots correspondant aux patterns d'exclusion

    Args:
        word: Mot à vérifier

    Returns:
        True si le mot doit être exclu, False sinon

    Example:
        >>> should_exclude_from_glossary("the")
        True
        >>> should_exclude_from_glossary("at")
        True
        >>> should_exclude_from_glossary("Matrix")
        False
        >>> should_exclude_from_glossary("Dr")
        False  # Nom propre court accepté
    """
    # Stopwords grammaticaux
    if is_grammatical_stopword(word):
        return True

    # Mots très courts (1 lettre) toujours exclus
    if len(word) == 1:
        return True

    # Mots de 2 lettres exclus SAUF si commencent par majuscule (ex: "Dr")
    if len(word) == 2 and word[0].islower():
        return True

    return False


def is_likely_extraction_error(
    source_term: str, translated_term: str, source_context: str = ""
) -> bool:
    """
    Détecte si une paire source/traduction est probablement une erreur d'extraction.

    Heuristiques :
    - Source grammatical → Traduction nom propre (ex: "after" → "Flio")
    - Source très différent de traduction en longueur (ratio > 5)

    Args:
        source_term: Terme source
        translated_term: Terme traduit
        source_context: Contexte source optionnel (phrase complète)

    Returns:
        True si probablement une erreur, False sinon

    Example:
        >>> is_likely_extraction_error("after", "Flio")
        True  # "after" est grammatical, "Flio" est un nom propre
        >>> is_likely_extraction_error("Matrix", "Matrice")
        False  # Traduction légitime
    """
    # Cas 1 : Source grammatical + Traduction commence par majuscule
    if is_grammatical_stopword(source_term) and translated_term[0].isupper():
        return True

    # Cas 2 : Différence de longueur excessive (ratio > 5)
    if len(source_term) > 0 and len(translated_term) > 0:
        ratio = max(len(source_term), len(translated_term)) / min(
            len(source_term), len(translated_term)
        )
        if ratio > 5:
            return True  # Ex: "of" (2) → "Association" (11)

    return False


def categorize_conflict(source_term: str, translations: list[str]) -> str:
    """
    Catégorise un conflit terminologique.

    Catégories :
    - "grammatical" : Mot grammatical (ne devrait pas être dans glossaire)
    - "proper_noun" : Nom propre avec variantes (ex: "Association" vs "Aventuriers")
    - "onomatopoeia" : Interjection/onomatopée (variations légitimes)
    - "contextual" : Mot contextuel (variations selon phrase)

    Args:
        source_term: Terme source en conflit
        translations: Liste des traductions conflictuelles

    Returns:
        Catégorie du conflit

    Example:
        >>> categorize_conflict("after", ["Après", "Au", "Flio"])
        "grammatical"
        >>> categorize_conflict("Ahh", ["Ahh", "Aah"])
        "onomatopoeia"
        >>> categorize_conflict("Association", ["Association", "Guilde"])
        "proper_noun"
    """
    # Catégorie 1 : Grammatical
    if is_grammatical_stopword(source_term):
        return "grammatical"

    # Catégorie 2 : Onomatopée (3 lettres ou moins, répétition de lettres)
    if len(source_term) <= 4 and any(
        source_term.count(c) >= 2 for c in set(source_term)
    ):
        return "onomatopoeia"

    # Catégorie 3 : Nom propre (commence par majuscule)
    if source_term[0].isupper():
        # Si toutes traductions commencent par majuscule → nom propre
        if all(t[0].isupper() for t in translations):
            return "proper_noun"

    # Catégorie 4 : Contextuel (par défaut)
    return "contextual"


def get_high_priority_conflicts(conflicts: dict[str, list[str]]) -> dict[str, list[str]]:
    """
    Filtre les conflits haute priorité (noms propres/termes techniques).

    Args:
        conflicts: Dictionnaire {terme: [traductions]}

    Returns:
        Sous-ensemble de conflits haute priorité

    Example:
        >>> conflicts = {
        ...     "after": ["Après", "Au"],
        ...     "Association": ["Association", "Guilde"]
        ... }
        >>> high_priority = get_high_priority_conflicts(conflicts)
        >>> "Association" in high_priority
        True
        >>> "after" in high_priority
        False
    """
    high_priority = {}

    for source, translations in conflicts.items():
        category = categorize_conflict(source, translations)

        # Haute priorité : noms propres et contextuels
        if category in ["proper_noun", "contextual"]:
            # Exclure si toutes traductions sont grammaticales
            if not all(is_grammatical_stopword(t) for t in translations):
                high_priority[source] = translations

    return high_priority


def get_low_priority_conflicts(conflicts: dict[str, list[str]]) -> dict[str, list[str]]:
    """
    Filtre les conflits basse priorité (grammaticaux, onomatopées).

    Args:
        conflicts: Dictionnaire {terme: [traductions]}

    Returns:
        Sous-ensemble de conflits basse priorité

    Example:
        >>> conflicts = {
        ...     "after": ["Après", "Au"],
        ...     "Ahh": ["Ahh", "Aah"]
        ... }
        >>> low_priority = get_low_priority_conflicts(conflicts)
        >>> "after" in low_priority
        True
        >>> "Ahh" in low_priority
        True
    """
    low_priority = {}

    for source, translations in conflicts.items():
        category = categorize_conflict(source, translations)

        # Basse priorité : grammaticaux et onomatopées
        if category in ["grammatical", "onomatopoeia"]:
            low_priority[source] = translations

    return low_priority
