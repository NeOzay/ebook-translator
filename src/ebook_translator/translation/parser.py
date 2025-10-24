"""
Parsing des sorties de traduction des LLM.
"""

import re
from typing import Optional


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

    # Détecter les messages d'erreur du LLM
    if output.startswith("[ERREUR"):
        raise ValueError(
            f"❌ Le LLM a retourné une erreur :\n{output}\n\n"
            f"💡 Causes possibles:\n"
            f"  • Timeout du serveur\n"
            f"  • Rate limit atteint\n"
            f"  • Erreur API\n"
            f"\n🔧 Solutions:\n"
            f"  • Le système va automatiquement réessayer\n"
            f"  • Vérifiez les logs pour plus de détails\n"
            f"  • Réduisez le nombre de requêtes parallèles"
        )

    # Vérifier la présence du marqueur de fin
    if not output.endswith("[=[END]=]"):
        # Donner un aperçu de la sortie pour debug
        preview = output[:200] + "..." if len(output) > 200 else output
        raise ValueError(
            f"❌ Traduction incomplète : le marqueur [=[END]=] est manquant.\n\n"
            f"📝 Aperçu de la sortie LLM:\n{preview}\n\n"
            f"💡 Causes possibles:\n"
            f"  • Le LLM a été interrompu avant la fin\n"
            f"  • La limite de tokens max_tokens est trop basse\n"
            f"  • Le LLM n'a pas suivi le format demandé\n"
            f"\n🔧 Solutions:\n"
            f"  • Augmentez max_tokens dans la config LLM\n"
            f"  • Réduisez la taille des chunks à traduire\n"
            f"  • Vérifiez le prompt de traduction"
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
        # Donner un aperçu de la sortie pour debug
        preview = output[:300] + "..." if len(output) > 300 else output
        raise ValueError(
            f"❌ Aucun segment trouvé. Le format de la sortie LLM est invalide.\n\n"
            f"📝 Sortie reçue:\n{preview}\n\n"
            f"✅ Format attendu:\n"
            f"  <0/>Texte traduit ligne 0\n"
            f"  <1/>Texte traduit ligne 1\n"
            f"  ...\n"
            f"  [=[END]=]\n\n"
            f"💡 Causes possibles:\n"
            f"  • Le LLM n'a pas respecté le format de numérotation\n"
            f"  • Le prompt de traduction est mal configuré\n"
            f"  • Le LLM a généré du texte libre au lieu de traduire\n"
            f"\n🔧 Solutions:\n"
            f"  • Vérifiez le template de prompt \n"
            f"  • Consultez les logs LLM pour voir la réponse complète\n"
            f"  • Essayez avec un autre modèle LLM"
        )

    return translations


def validate_retry_indices(
    retry_translations: dict[int, str],
    expected_indices: list[int],
) -> tuple[bool, Optional[str]]:
    """
    Valide que le retry a fourni exactement les indices demandés.

    Vérifie que :
    - Tous les indices attendus sont présents dans retry_translations
    - Aucun indice supplémentaire/invalide n'est présent

    Args:
        retry_translations: Dictionnaire {index: texte_traduit} retourné par le retry
        expected_indices: Liste des indices qui devaient être traduits

    Returns:
        Tuple (is_valid, error_message)
        - is_valid: True si les indices correspondent exactement, False sinon
        - error_message: Message d'erreur détaillé si invalide, None sinon

    Example:
        >>> retry_trans = {5: "Hello", 10: "World"}
        >>> expected = [5, 10]
        >>> validate_retry_indices(retry_trans, expected)
        (True, None)

        >>> retry_trans = {5: "Hello", 99: "Invalid"}
        >>> expected = [5, 10]
        >>> validate_retry_indices(retry_trans, expected)
        (False, "❌ Le retry n'a pas fourni les indices corrects...")
    """
    expected_set = set(expected_indices)
    received_set = set(retry_translations.keys())

    missing = expected_set - received_set
    extra = received_set - expected_set

    if not missing and not extra:
        return True, None

    # Construire le message d'erreur
    error_parts = [
        "❌ Le retry n'a pas fourni les indices corrects:",
        f"  • Indices demandés: {sorted(expected_set)[:20]}{'...' if len(expected_set) > 20 else ''}",
        f"  • Indices reçus: {sorted(received_set)[:20]}{'...' if len(received_set) > 20 else ''}",
    ]

    if missing:
        missing_preview = sorted(missing)[:10]
        missing_str = ", ".join(f"<{i}/>" for i in missing_preview)
        if len(missing) > 10:
            missing_str += f" ... (+{len(missing) - 10} autres)"
        error_parts.append(f"  • Toujours manquants: {missing_str}")

    if extra:
        extra_preview = sorted(extra)[:10]
        extra_str = ", ".join(f"<{i}/>" for i in extra_preview)
        if len(extra) > 10:
            extra_str += f" ... (+{len(extra) - 10} autres)"
        error_parts.append(f"  • Indices invalides (non demandés): {extra_str}")

    error_parts.extend(
        [
            "",
            "💡 Causes possibles:",
            "  • Le LLM n'a pas respecté la liste des lignes à traduire",
            "  • Le LLM a traduit des lignes déjà présentes (contexte)",
            "  • Erreur de numérotation dans la réponse du LLM",
            "",
            "🔧 Solutions:",
            "  • Le système va réessayer avec un prompt encore plus strict",
            "  • Vérifiez les logs LLM pour voir la réponse complète",
        ]
    )

    return False, "\n".join(error_parts)
