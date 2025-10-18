"""
Parsing des sorties de traduction des LLM.
"""

import re


def parse_llm_translation_output(output: str) -> dict[int, str]:
    """
    Parse la sortie d'un LLM au format numéroté.

    Format attendu:
        <0/>Texte traduit ligne 0...
        <1/>Texte traduit ligne 1...
        ...
        [=[END]=]

    Args:
        output: Sortie brute du LLM

    Returns:
        Dictionnaire {index: texte_traduit}

    Raises:
        ValueError: Si le format est invalide ou incomplet

    Example:
        >>> output = "<0/>Hello\\n<1/>World\\n[=[END]=]"
        >>> result = parse_llm_translation_output(output)
        >>> result
        {0: 'Hello', 1: 'World'}
    """
    output = output.strip()

    # Vérifier la présence du marqueur de fin
    if not output.endswith("[=[END]=]"):
        raise ValueError(
            "❌ Traduction incomplète : le marqueur [=[END]=] est manquant."
        )

    # Supprimer le marqueur de fin
    output = output.replace("[=[END]=]", "").strip()

    # Expression régulière pour capturer les segments numérotés
    # - ^<(\\d+)\\/> : capture le numéro de ligne
    # - (.*?) : capture le texte traduit (non-greedy)
    # - (?=^<\\d+\\/>|$) : arrêt avant la prochaine balise ou fin
    pattern = re.compile(r"^<(\d+)\/>(.*?)(?=^<\d+\/>|$)", re.DOTALL | re.MULTILINE)

    translations: dict[int, str] = {}
    for match in pattern.finditer(output):
        line_number = int(match.group(1))
        text = match.group(2).strip()
        translations[line_number] = text

    if not translations:
        raise ValueError("❌ Aucun segment trouvé. Vérifie le format de la sortie LLM.")

    return translations
