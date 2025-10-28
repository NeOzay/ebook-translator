"""
Renderers encapsulés pour les templates Jinja2 avec typage fort.

Ce module fournit une API simplifiée et typée pour rendre les templates,
en encapsulant toute la logique métier nécessaire (extraction texte,
export glossaire, calculs, etc.).
"""

from typing import TYPE_CHECKING, Literal

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import TemplateNames

from .template_params import (
    TranslateParams,
    RefineParams,
    MissingLinesParams,
    RetryFragmentsParams,
    RetryFragmentsFlexibleParams,
    RetryPunctuationParams,
)

if TYPE_CHECKING:
    from .llm import LLM
    from ..segment import Chunk
    from ..glossary import Glossary
    from ..stores.multi_store import MultiStore


class TemplateRenderer:
    """
    Encapsule le rendu des templates avec typage fort et logique métier centralisée.

    Cette classe simplifie l'utilisation des templates en :
    - Fournissant des méthodes typées pour chaque template
    - Encapsulant la logique métier (extraction texte, export glossaire, etc.)
    - Validant automatiquement les paramètres requis
    - Réduisant la duplication de code dans les modules appelants

    Example:
        >>> llm = LLM(...)
        >>> renderer = TemplateRenderer(llm)
        >>> prompt = renderer.render_translate(target_language="fr")
        >>> llm_output = llm.query(prompt, source_content)
    """

    def __init__(
        self,
        prompt_dir: str = "template",
    ):
        """
        Initialise le renderer avec une instance LLM.

        Args:
            llm: Instance LLM pour accéder à render_prompt()
        """
        self.env = Environment(
            loader=FileSystemLoader(prompt_dir),
            autoescape=select_autoescape(["html", "xml"]),
        )

    # -----------------------------------
    # 🔹 Rendu du template
    # -----------------------------------
    def render_prompt(self, template_name: str, **kwargs) -> str:
        """
        Rend un template Jinja2 avec les variables données.

        Note:
            Cette méthode est conservée pour rétrocompatibilité.
            Pour une API typée et simplifiée, utilisez `self.renderer.render_XXX()`.

        Example:
            >>> # API recommandée (typée)
            >>> prompt = llm.renderer.render_translate(target_language="fr")
            >>>
            >>> # API legacy (non typée, conservée pour compatibilité)
            >>> prompt = llm.render_prompt("translate.jinja", target_language="fr")

        Args:
            template_name: Nom du fichier template (ex: "translate.jinja")
            **kwargs: Variables à passer au template

        Returns:
            Prompt rendu
        """
        template = self.env.get_template(template_name)
        return template.render(**kwargs)

    def render_translate(self, target_language: str) -> str:
        """
        Rend le template translate.jinja (Phase 1 - Traduction initiale).

        Ce template est utilisé pour la première passe de traduction avec
        des gros blocs (2000 tokens par défaut).

        Args:
            target_language: Code langue cible ISO 639-1 (ex: "fr", "en", "es")

        Returns:
            Prompt système rendu prêt pour envoi au LLM

        Example:
            >>> prompt = renderer.render_translate(target_language="fr")
            >>> llm_output = llm.query(prompt, str(chunk))
        """
        params: TranslateParams = {
            "target_language": target_language,
        }
        return self.render_prompt(TemplateNames.First_Pass_Template, **params)

    def render_refine(
        self,
        chunk: "Chunk",
        multi_store: "MultiStore",
        glossary: "Glossary",
        target_language: str,
    ) -> str:
        """
        Rend le template refine.jinja (Phase 2 - Affinage avec glossaire).

        Ce template est utilisé pour affiner les traductions initiales avec :
        - Segmentation fine (300 tokens par défaut)
        - Glossaire appris en Phase 1
        - Traduction initiale comme base

        La méthode encapsule automatiquement :
        - Récupération traduction initiale depuis MultiStore
        - Extraction texte original (head + body + tail)
        - Export du glossaire appris
        - Calcul du nombre de lignes attendues (expected_count)

        Args:
            chunk: Chunk à affiner (300 tokens)
            multi_store: MultiStore pour accès initial_store et refined_store
            glossary: Glossary appris en Phase 1
            target_language: Code langue cible ISO 639-1

        Returns:
            Prompt système rendu prêt pour envoi au LLM

        Raises:
            ValueError: Si la traduction initiale est manquante (Phase 1 incomplète)

        Example:
            >>> prompt = renderer.render_refine(
            ...     chunk=chunk,
            ...     multi_store=multi_store,
            ...     glossary=glossary,
            ...     target_language="fr"
            ... )
            >>> llm_output = llm.query(prompt, "")  # Tout dans le prompt
        """
        # 1. Récupérer traduction initiale (Phase 1)
        initial_translation, has_missing = chunk.get_translation_for_prompt(
            multi_store.initial_store
        )
        if has_missing:
            raise ValueError(
                f"Chunk {chunk.index}: Traduction initiale manquante (Phase 1 incomplète)"
            )

        # 2. Extraire texte original (head + body + tail)
        original_text = str(chunk)

        # 3. Exporter glossaire appris en Phase 1
        glossary_export = glossary.export_for_prompt(max_terms=50, min_confidence=0.5)

        # 4. Calculer nombre de lignes attendues (body uniquement)
        expected_count = chunk.get_body_size()

        # 5. Construire paramètres typés
        params: RefineParams = {
            "target_language": target_language,
            "original_text": original_text,
            "initial_translation": initial_translation,
            "glossaire": glossary_export or "Aucun terme dans le glossaire.",
            "expected_count": expected_count,
        }

        return self.render_prompt(TemplateNames.Refine_Template, **params)

    def render_missing_lines(
        self,
        chunk: "Chunk",
        missing_indices: list[int],
        target_language: str,
    ) -> str:
        """
        Rend le template retry_missing_lines_targeted.jinja (Correction lignes manquantes).

        Ce template est utilisé pour corriger les lignes manquantes détectées
        par LineCountCheck. Seules les lignes manquantes sont numérotées,
        le reste sert de contexte.

        La méthode encapsule automatiquement :
        - Construction du source_content avec numérotation sélective
        - Génération du message d'erreur contextuel
        - Formatage des indices manquants

        Args:
            chunk: Chunk source avec toutes les lignes
            missing_indices: Liste des indices de lignes manquantes à traduire
            target_language: Code langue cible ISO 639-1

        Returns:
            Prompt système rendu prêt pour envoi au LLM

        Example:
            >>> prompt = renderer.render_missing_lines(
            ...     chunk=chunk,
            ...     missing_indices=[5, 7, 12],
            ...     target_language="fr"
            ... )
            >>> llm_output = llm.query(prompt, "")
        """
        # 1. Construire source_content avec numérotation sélective
        # Seules les lignes manquantes sont marquées <N/>
        source_content = chunk.mark_lines_to_numbered(missing_indices)

        # 2. Générer message d'erreur contextuel
        num_missing = len(missing_indices)
        indices_preview = ", ".join(f"<{idx}/>" for idx in missing_indices[:5])
        if num_missing > 5:
            indices_preview += f" ... (+{num_missing - 5} autres)"

        error_message = (
            f"Tu as oublié {num_missing} ligne(s) numérotée(s) : {indices_preview}"
        )

        params: MissingLinesParams = {
            "target_language": target_language,
            "missing_indices": missing_indices,
            "source_content": source_content,
            "error_message": error_message,
        }

        return self.render_prompt(
            TemplateNames.Missing_Lines_Targeted_Template, **params
        )

    def render_retry_fragments(
        self,
        target_language: str,
        original_text: str,
        incorrect_translation: str,
        expected_separators: int,
        actual_separators: int,
        mode: Literal["NORMAL", "FLEXIBLE"] = "NORMAL",
    ) -> str:
        """
        Rend le template de retry pour correction du nombre de fragments.

        Sélectionne automatiquement le template approprié selon le mode :
        - NORMAL: retry_fragments.jinja (préservation stricte des positions)
        - FLEXIBLE: retry_fragments_flexible.jinja (placement libre, même nombre)

        Ce template est utilisé pour corriger les traductions avec un nombre
        incorrect de séparateurs `</>`. Il affiche l'erreur détectée et demande
        une re-traduction en respectant la structure.

        Args:
            target_language: Code langue cible ISO 639-1
            original_text: Texte source original
            incorrect_translation: Traduction produite avec nombre incorrect de séparateurs
            expected_separators: Nombre de séparateurs `</>` attendus
            actual_separators: Nombre de séparateurs `</>` trouvés dans la traduction
            mode: Mode de correction ("NORMAL" ou "FLEXIBLE"), défaut "NORMAL"

        Returns:
            Prompt système rendu prêt pour envoi au LLM

        Raises:
            ValueError: Si le mode n'est pas "NORMAL" ou "FLEXIBLE"

        Example:
            >>> # Première tentative en mode NORMAL
            >>> prompt = renderer.render_retry_fragments(
            ...     target_language="fr",
            ...     original_text="Hello</>world</>!",
            ...     incorrect_translation="Bonjour monde !",
            ...     expected_separators=2,
            ...     actual_separators=0,
            ...     mode="NORMAL"
            ... )
            >>> # Si échec, deuxième tentative en mode FLEXIBLE
            >>> prompt = renderer.render_retry_fragments(
            ...     target_language="fr",
            ...     original_text="Hello</>world</>!",
            ...     incorrect_translation="Bonjour monde !",
            ...     expected_separators=2,
            ...     actual_separators=0,
            ...     mode="FLEXIBLE"
            ... )
        """
        if mode == "FLEXIBLE":
            params_flexible: RetryFragmentsFlexibleParams = {
                "target_language": target_language,
                "original_text": original_text,
                "incorrect_translation": incorrect_translation,
                "expected_separators": expected_separators,
                "actual_separators": actual_separators,
            }
            return self.render_prompt(
                TemplateNames.Retry_Fragments_Flexible_Template, **params_flexible
            )
        else:  # mode == "NORMAL"
            params_normal: RetryFragmentsParams = {
                "target_language": target_language,
                "original_text": original_text,
                "incorrect_translation": incorrect_translation,
                "expected_separators": expected_separators,
                "actual_separators": actual_separators,
            }
            return self.render_prompt(
                TemplateNames.Retry_Fragments_Template, **params_normal
            )

    def render_retry_punctuation(
        self,
        target_language: str,
        original_text: str,
        incorrect_translation: str,
        expected_pairs: int,
        actual_pairs: int,
    ) -> str:
        """
        Rend le template retry_punctuation.jinja (Correction paires de guillemets).

        Ce template est utilisé pour corriger les traductions avec un nombre
        incorrect de paires de guillemets (dialogues fusionnés, interruptions
        narratives perdues).

        Args:
            target_language: Code langue cible ISO 639-1
            original_text: Texte source original
            incorrect_translation: Traduction avec nombre incorrect de paires
            expected_pairs: Nombre de paires de guillemets attendues
            actual_pairs: Nombre de paires trouvées dans la traduction

        Returns:
            Prompt système rendu prêt pour envoi au LLM

        Example:
            >>> prompt = renderer.render_retry_punctuation(
            ...     target_language="fr",
            ...     original_text='"Hello," he said, "world!"',
            ...     incorrect_translation='« Bonjour, dit-il, monde ! »',
            ...     expected_pairs=2,
            ...     actual_pairs=1
            ... )
            >>> llm_output = llm.query(prompt, "")
        """
        params: RetryPunctuationParams = {
            "target_language": target_language,
            "original_text": original_text,
            "incorrect_translation": incorrect_translation,
            "expected_pairs": expected_pairs,
            "actual_pairs": actual_pairs,
        }

        return self.render_prompt("retry_punctuation.jinja", **params)
