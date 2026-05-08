"""Helper centralisé pour gérer les retries avec mode raisonnement."""

from collections.abc import Callable

from ebook_translator.checks.check_tests.base import ValidationContext
from ebook_translator.llm.llm_config import GenericLLMConfig
from ebook_translator.logger import get_logger

logger = get_logger(__name__)


def retry_with_reasoning(
    context: ValidationContext,
    render_prompt: Callable[[int, bool], tuple[str, str]],
    validate_result: Callable[[str], bool],
    context_name: str,
    max_attempts: int = 2,
) -> tuple[bool, str | None]:
    """
    Exécute une correction avec retry automatique (normal → reasoning).

    Args:
        context: Contexte de validation
        chunk_index: Index du chunk (pour logs)
        render_prompt: Fonction qui génère le prompt. Prend use_reasoning en paramètre.
        validate_result: Fonction qui valide le résultat LLM. Retourne True si valide.
        context_name: Nom du contexte pour logs (ex: "fragment", "missing_lines", "punctuation")
        max_attempts: Nombre maximum de tentatives (défaut: 2)

    Returns:
        Tuple (succès: bool, résultat_llm: str | None)
        - Si succès: (True, résultat_valide)
        - Si échec après tous les retries: (False, None)

    Flow:
        Tentative 1: Mode normal (deepseek-chat)
        Tentative 2+: Mode reasoning (deepseek-reasoner)
    """
    if context.llm is None:
        logger.warning(f"⚠️ LLM non disponible pour correction {context_name}")
        return False, None

    chunk_index: int = context.chunk.index
    for attempt in range(1, max_attempts + 1):
        # Tentative 1 : mode normal (deepseek-chat)
        # Tentative 2+ : mode reasoning (deepseek-reasoner)
        use_reasoning = attempt == max_attempts

        # Générer le prompt (même template, paramètre use_reasoning pour contexte)
        system, user = render_prompt(attempt, use_reasoning)

        # Construire le contexte de log
        llm_context = (
            f"correction_{context_name}_chunk_{chunk_index:03d}_attempt_{attempt}"
        )

        if use_reasoning:
            llm_context += "_reasoning"

        # Log de la tentative
        if use_reasoning:
            logger.info(
                f"🧠 Tentative {attempt}/{max_attempts} avec mode raisonnement : {context_name}"
            )
        else:
            logger.info(
                f"🔄 Tentative {attempt}/{max_attempts} mode normal : {context_name}"
            )

        # Appeler le LLM
        try:
            llm_output = context.llm.query(
                system_prompt=system,
                content=user,
                log_name=llm_context,
                config=GenericLLMConfig(use_thinking=use_reasoning),
            )
        except Exception as e:
            logger.error(f"❌ Erreur LLM lors de la tentative {attempt} : {e}")
            continue

        # Valider le résultat
        try:
            is_valid = validate_result(llm_output)
            if is_valid:
                logger.info(f"✅ Correction réussie après {attempt} tentative(s)")
                return True, llm_output
            else:
                logger.warning(
                    f"⚠️ Tentative {attempt} échouée, validation non satisfaite"
                )
        except Exception as e:
            logger.warning(f"⚠️ Tentative {attempt} échouée, erreur validation : {e}")

    # Toutes les tentatives ont échoué
    logger.error(
        f"❌ Échec de correction après {max_attempts} tentatives : {context_name}"
    )
    return False, None
