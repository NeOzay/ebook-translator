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
    RetrySentenceParams,
)

from ..segmentation import Chunk, TranslatedChunk

if TYPE_CHECKING:
    from ..glossary import Glossary
    from ..stores.multi_store import Store


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
    def render_prompt(self, template_name: TemplateNames, **kwargs) -> str:
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
            >>> prompt = llm.render_prompt("translate_base.jinja", target_language="fr")

        Args:
            template_name: Nom du fichier template (ex: "translate_base.jinja")
            **kwargs: Variables à passer au template

        Returns:
            Prompt rendu
        """
        template = self.env.get_template(template_name.value)
        return template.render(**kwargs)

    def render_translate(self, target_language: str) -> str:
        """
        Rend le template translate_base.jinja (Phase 1 - Traduction initiale).

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
        store: "Store",
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
        # 1. Récupérer traduction initiale (Phase 1 ou Phase 2 si disponible)
        translated_chunk = TranslatedChunk(chunk, store)

        if translated_chunk.has_missing:
            raise ValueError(
                f"Chunk {chunk.index}: Traduction initiale manquante (Phase 1 incomplète)"
            )

        initial_translation = str(translated_chunk)

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
            TemplateNames.Retry_Missing_Lines_Targeted_Template, **params
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

        return self.render_prompt(TemplateNames.Retry_Punctuation_Template, **params)

    def render_retry_sentence(
        self,
        chunk: "Chunk",
        target_language: str,
        previous_translation: "TranslatedChunk | None",
        missing_indices: list[int],
    ) -> str:
        """
        Rend le template retry_sentence.jinja (Correction nombre de phrases).

        Ce template est utilisé pour corriger les traductions avec un nombre
        incorrect de phrases, typiquement lors du raffinage où le LLM tronque
        le contenu au lieu de l'améliorer. Il fournit à la fois la traduction
        initiale (Phase 1) et la traduction raffinée actuelle (Phase 2) pour
        permettre au LLM de comprendre ce qui a été perdu.

        Args:
            target_language: Code langue cible ISO 639-1
            original_text: Texte source original
            incorrect_translation: Traduction raffinée avec nombre incorrect de phrases
            previous_translation: Traduction initiale (Phase 1) servant de référence
            expected_sentences: Nombre de phrases attendu (basé sur original)
            actual_sentences: Nombre de phrases dans traduction raffinée actuelle

        Returns:
            Prompt système rendu prêt pour envoi au LLM

        Example:
            >>> prompt = renderer.render_retry_sentence(
            ...     target_language="fr",
            ...     original_text="Sentence 1. Sentence 2. Sentence 3.",
            ...     incorrect_translation="Phrase 1.",
            ...     previous_translation="Phrase 1. Phrase 2. Phrase 3.",
            ...     expected_sentences=3,
            ...     actual_sentences=1
            ... )
            >>> llm_output = llm.query(prompt, "")
        """
        # 1. Construire source_content avec numérotation sélective
        # Seules les lignes manquantes sont marquées <N/>
        source_content = chunk.mark_lines_to_numbered(missing_indices)
        previous_content = (
            previous_translation.mark_lines_to_numbered(missing_indices)
            if previous_translation
            else ""
        )

        # 2. Générer message d'erreur contextuel
        num_missing = len(missing_indices)
        indices_preview = ", ".join(f"<{idx}/>" for idx in missing_indices[:5])
        if num_missing > 5:
            indices_preview += f" ... (+{num_missing - 5} autres)"

        params: RetrySentenceParams = {
            "target_language": target_language,
            "original_text": source_content,
            "previous_translation": previous_content,
            "missing_indices": indices_preview,
            "num_lines": num_missing,
        }

        return self.render_prompt(TemplateNames.Retry_Sentence_Template, **params)

    # -----------------------------------
    # 🔹 Phase 0 : Analyse littéraire
    # -----------------------------------

    def render_analyze_initial(
        self,
        chapter_name: str,
        total_blocks: int,
        block_text: str,
        genre: str = "fiction",
    ) -> str:
        """
        Rend le template analyze_chapter_initial.jinja (Phase 0 - Premier bloc d'analyse).

        Ce template est utilisé pour initialiser l'analyse littéraire d'un chapitre
        lors du traitement du premier bloc (~4000 tokens).

        Génère une structure JSON complète avec status="in_progress" et blocks_analyzed=1.

        Args:
            chapter_name: Nom du chapitre (ex: "Chapter 1", "Prologue")
            total_blocks: Nombre total de blocs pour ce chapitre
            block_text: Contenu textuel du premier bloc (~4000 tokens)
            genre: Genre littéraire du livre (défaut: "fiction")

        Returns:
            Prompt système rendu prêt pour envoi au LLM avec use_json_mode=True

        Example:
            >>> prompt = renderer.render_analyze_initial(
            ...     chapter_name="Chapter 1",
            ...     total_blocks=3,
            ...     block_text="It was a dark and stormy night...",
            ...     genre="fiction"
            ... )
            >>> json_output = llm.query(prompt, "", use_json_mode=True)
        """
        return self.render_prompt(
            TemplateNames.Analyze_Initial,
            chapter_name=chapter_name,
            total_blocks=total_blocks,
            block_text=block_text,
            genre=genre,
        )

    def render_analyze_incremental(
        self,
        chapter_name: str,
        current_block: int,
        total_blocks: int,
        partial_analysis_json: str,
        block_text: str,
        is_last_block: bool,
        genre: str = "fiction",
    ) -> str:
        """
        Rend le template analyze_chapter_incremental.jinja (Phase 0 - Blocs 2, 3, ..., N).

        Ce template est utilisé pour enrichir progressivement l'analyse littéraire
        d'un chapitre en traitant les blocs suivants (~4000 tokens chacun).

        Met à jour la structure JSON existante en ajoutant de nouvelles informations
        sans jamais supprimer les données précédentes (approche cumulative).

        Args:
            chapter_name: Nom du chapitre (ex: "Chapter 1", "Prologue")
            current_block: Numéro du bloc actuel (2, 3, ..., N)
            total_blocks: Nombre total de blocs pour ce chapitre
            partial_analysis_json: JSON stringifié de l'analyse partielle (blocs 1...current_block-1)
            block_text: Contenu textuel du bloc actuel (~4000 tokens)
            is_last_block: True si c'est le dernier bloc (active status="complete")
            genre: Genre littéraire du livre (défaut: "fiction")

        Returns:
            Prompt système rendu prêt pour envoi au LLM avec use_json_mode=True

        Example:
            >>> # Bloc 2/3
            >>> prompt = renderer.render_analyze_incremental(
            ...     chapter_name="Chapter 1",
            ...     current_block=2,
            ...     total_blocks=3,
            ...     partial_analysis_json='{"chapter_name": "Chapter 1", ...}',
            ...     block_text="The next morning...",
            ...     is_last_block=False,
            ...     genre="fiction"
            ... )
            >>> json_output = llm.query(prompt, "", use_json_mode=True)
            >>>
            >>> # Dernier bloc 3/3
            >>> prompt = renderer.render_analyze_incremental(
            ...     chapter_name="Chapter 1",
            ...     current_block=3,
            ...     total_blocks=3,
            ...     partial_analysis_json='{"chapter_name": "Chapter 1", ...}',
            ...     block_text="And they lived happily ever after.",
            ...     is_last_block=True,  # Activera status="complete"
            ...     genre="fiction"
            ... )
        """
        return self.render_prompt(
            TemplateNames.Analyze_Incremental,
            chapter_name=chapter_name,
            current_block=current_block,
            total_blocks=total_blocks,
            partial_analysis_json=partial_analysis_json,
            block_text=block_text,
            is_last_block=is_last_block,
            genre=genre,
        )

    def render_chapter_grouping(self, filenames: list[str]) -> str:
        """
        Rend le template chapter_grouping.jinja (Détection de chapitres - Fallback LLM).

        Ce template est utilisé comme fallback lorsque la détection automatique
        basée sur les patterns regex produit des résultats ambigus. Le LLM analyse
        les noms de fichiers de la spine EPUB et groupe logiquement les fichiers
        en chapitres.

        Args:
            filenames: Liste des noms de fichiers HTML dans l'ordre de la spine EPUB

        Returns:
            Prompt système rendu prêt pour envoi au LLM avec use_json_mode=True

        Example:
            >>> prompt = renderer.render_chapter_grouping(
            ...     filenames=[
            ...         "prologue.xhtml",
            ...         "chapter1.xhtml",
            ...         "chapter1_a.xhtml",
            ...         "insert1.xhtml",
            ...         "chapter2.xhtml",
            ...     ]
            ... )
            >>> json_output = llm.query(prompt, "", use_json_mode=True)
            >>> # Attendu: {"chapters": [{"chapter_name": "Prologue", "files": [...]}]}
        """
        return self.render_prompt(
            TemplateNames.Chapter_Grouping,
            filenames=filenames,
        )
