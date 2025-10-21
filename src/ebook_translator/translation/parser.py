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
            f"  • Vérifiez le template de prompt (template/translate.jinja)\n"
            f"  • Consultez les logs LLM pour voir la réponse complète\n"
            f"  • Essayez avec un autre modèle LLM"
        )

    return translations


def count_expected_lines(content: str) -> int:
    """
    Compte le nombre de lignes numérotées <N/> dans le contenu source.

    Args:
        content: Contenu source envoyé au LLM (avec balises <N/>)

    Returns:
        Nombre de lignes numérotées trouvées

    Example:
        >>> content = "<0/>Hello\\n<1/>World\\nContext line\\n<2/>!"
        >>> count_expected_lines(content)
        3
    """
    pattern = re.compile(r"^<(\d+)\/>", re.MULTILINE)
    matches = pattern.findall(content)
    return len(matches)


def validate_line_count(
    translations: dict[int, str],
    expected_count: Optional[int] = None,
    source_content: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    """
    Valide que le nombre de lignes traduites correspond au nombre attendu.

    Args:
        translations: Dictionnaire {index: texte_traduit} retourné par le parser
        expected_count: Nombre de lignes attendues (optionnel)
        source_content: Contenu source pour calculer expected_count automatiquement

    Returns:
        Tuple (is_valid, error_message)
        - is_valid: True si le compte est correct, False sinon
        - error_message: Message d'erreur détaillé si invalide, None sinon

    Raises:
        ValueError: Si ni expected_count ni source_content n'est fourni
    """
    if expected_count is None and source_content is None:
        raise ValueError(
            "Au moins un de expected_count ou source_content doit être fourni"
        )

    if expected_count is None and source_content is not None:
        expected_count = count_expected_lines(source_content)

    actual_count = len(translations)

    if actual_count == expected_count:
        return True, None

    # Trouver les lignes manquantes
    expected_indices = set(range(expected_count))
    actual_indices = set(translations.keys())
    missing_indices = sorted(expected_indices - actual_indices)
    extra_indices = sorted(actual_indices - expected_indices)

    error_parts = [
        f"❌ Nombre de lignes incorrect dans la traduction:",
        f"  • Attendu: {expected_count} lignes",
        f"  • Reçu: {actual_count} lignes",
    ]

    if missing_indices:
        # Afficher les premiers indices manquants
        missing_preview = missing_indices[:10]
        missing_str = ", ".join(f"<{i}/>" for i in missing_preview)
        if len(missing_indices) > 10:
            missing_str += f" ... (+{len(missing_indices) - 10} autres)"
        error_parts.append(f"  • Lignes manquantes: {missing_str}")

    if extra_indices:
        # Afficher les premiers indices en trop
        extra_preview = extra_indices[:10]
        extra_str = ", ".join(f"<{i}/>" for i in extra_preview)
        if len(extra_indices) > 10:
            extra_str += f" ... (+{len(extra_indices) - 10} autres)"
        error_parts.append(f"  • Lignes en trop: {extra_str}")

    error_parts.extend(
        [
            "",
            "💡 Causes possibles:",
            "  • Le LLM a ignoré certaines lignes (copyright, métadonnées, etc.)",
            "  • Le LLM a ajouté des lignes non demandées",
            "  • Erreur de parsing du format",
            "",
            "🔧 Solutions:",
            "  • Le système va automatiquement réessayer avec un prompt strict",
            "  • Vérifiez les logs LLM pour voir quelles lignes ont été ignorées",
            "  • Augmentez max_tokens si la traduction est tronquée",
        ]
    )

    return False, "\n".join(error_parts)
