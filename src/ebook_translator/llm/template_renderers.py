"""
Renderers encapsulés pour les templates Jinja2 avec typage fort.

Ce module fournit une API simplifiée et typée pour rendre les templates,
en encapsulant toute la logique métier nécessaire (extraction texte,
export glossaire, calculs, etc.).
"""

from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ebook_translator.segmentation.chapter_chunk import ChapterPartChunk
from ebook_translator.validator.translation_context import ContexteTraduction

from ..segmentation import Chunk, ChunkProtocol, TranslatedChunk

if TYPE_CHECKING:
    from template.template_params import (
        AnalyzeChapterLayeredParams,
        AnalyzeChapterParams,
        GlossaryParams,
        MissingLinesParams,
        RefineParams,
        RetryAnalysisInvalidJsonParams,
        RetryAnalysisMissingSectionsParams,
        RetryFragmentsParams,
        RetryPunctuationParams,
        RetrySentenceParams,
        TranslateParams,
    )

    from ..glossary import Glossary
    from ..stores import Store


class Template(StrEnum):
    def __init__(self, s: str) -> None:
        self.prefix = ""

    def get_templates(self) -> tuple[str, str]:
        prefix = self.prefix
        return prefix + self + "_system.jinja", prefix + self + "_user.jinja"

    def get_system(self) -> str:
        return self.prefix + self + "_system.jinja"

    def get_user(self) -> str:
        return self.prefix + self + "_user.jinja"


class PhaseTemplate(Template):
    def __init__(self, s: str) -> None:
        self.prefix = "phase/"

    Analyze_Chapter = "analyze_chapter"
    Analyze_Chapter_Layered = "analyze_chapter_layered"
    First_Pass_Template = "translate_base"
    Refine_Template = "translate_refine"
    Glossary = "glossary"


class RetryTemplate(Template):
    def __init__(self, s: str) -> None:
        self.prefix = "retry/"

    Retry_Analysis_Invalid_Json_Template = "retry_correct_analysis_invalid_json"
    Retry_Analysis_Missing_Sections_Template = "retry_correct_analysis_missing_sections"
    Retry_Fragments_Template = "retry_correct_fragments"
    Retry_Missing_Lines_Targeted_Template = "retry_translate_missing_lines_targeted"
    Retry_Sentence_Template = "retry_translate_sentence"
    Retry_Punctuation_Template = "retry_correct_punctuation"


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
        glossary_max_terms: int = 25,
        genre: str = "fiction",
    ):
        """
        Initialise le renderer avec une instance LLM.

        Args:
            llm: Instance LLM pour accéder à render_prompt()
            glossary_max_terms: Nombre maximum de termes envoyés au LLM dans le glossaire
        """
        self.env = Environment(
            loader=FileSystemLoader(prompt_dir),
            autoescape=select_autoescape(["html", "xml"]),
        )
        self._glossary_max_terms = glossary_max_terms
        self._genre = genre

    def set_genre(self, genre: str) -> None:
        """
        Met à jour le genre littéraire utilisé dans les templates.

        Args:
            genre: Nouveau genre littéraire (ex: "fiction", "non-fiction", "fantasy", "science-fiction")
        """
        self._genre = genre

    # -----------------------------------
    # 🔹 Rendu du template
    # -----------------------------------
    def render_prompt(self, template_name: Template, **kwargs: Any) -> tuple[str, str]:
        """
        Rend un template Jinja2 avec les variables données.

        Méthode de bas niveau utilisée en interne par toutes les méthodes `render_XXX`.
        Préférer les méthodes typées (`render_translate`, `render_refine`, etc.) pour
        un usage applicatif.

        Args:
            template_name: Nom du fichier template (ex: "translate_base.jinja")
                ou tuple de deux noms (system_template, user_template).
            **kwargs: Variables à passer au(x) template(s).

        Returns:
            `tuple[str, str]` (system, user)

        Example:
            >>> # Prompt simple (system uniquement)
            >>> prompt = renderer.render_prompt("translate_base.jinja", target_language="fr")
            >>>
            >>> # Prompt double (system + user)
            >>> system, user = renderer.render_prompt(
            ...     ("system.jinja", "user.jinja"),
            ...     target_language="fr"
            ... )
        """

        system = self.env.get_template(template_name.get_system()).render(**kwargs)
        user = self.env.get_template(template_name.get_user()).render(**kwargs)
        return (system, user)

    def render_translate(
        self,
        target_language: str,
        source_text: str,
        glossary: Glossary,
        literary_context: ContexteTraduction | None = None,
    ) -> tuple[str, str]:
        """
        Rend le template translate_base.jinja (Phase 1 - Traduction initiale).

        Ce template est utilisé pour la première passe de traduction avec
        des gros blocs (2000 tokens par défaut).

        Args:
            target_language: Code langue cible ISO 639-1 (ex: "fr", "en", "es")
            literary_context: Analyse littéraire du chapitre (optionnel, depuis Phase 0)

        Returns:
            Prompt système rendu prêt pour envoi au LLM

        Example:
            >>> prompt = renderer.render_translate(target_language="fr")
            >>> llm_output = llm.query(prompt, str(chunk))
        """
        params: TranslateParams = {
            "target_language": target_language,
            "source_text": source_text,
            "glossary": glossary.collect_entry(source_text, self._glossary_max_terms),
            "literary_context": (
                literary_context["analyse"] if literary_context else None
            ),
            "genre": self._genre,
        }
        return self.render_prompt(PhaseTemplate.First_Pass_Template, **params)

    def render_refine(
        self,
        chunk: Chunk,
        store: Store,
        glossary: Glossary,
        target_language: str,
        literary_context: ContexteTraduction | None = None,
    ) -> tuple[str, str]:
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
            literary_context: Analyse littéraire du chapitre (optionnel, depuis Phase 0)

        Returns:
            Prompt système rendu prêt pour envoi au LLM

        Raises:
            Error: Si la traduction initiale est manquante (Phase 1 incomplète)

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

        head, original_text, tail = chunk.prepare_for_prompt_split()

        params: RefineParams = {
            "target_language": target_language,
            "head_context": head,
            "original_text": original_text,
            "initial_translation": initial_translation,
            "tail_context": tail,
            "glossary": glossary.collect_entry(original_text, self._glossary_max_terms),
            "literary_context": (
                literary_context["analyse"] if literary_context else None
            ),
            "genre": self._genre,
        }

        return self.render_prompt(PhaseTemplate.Refine_Template, **params)

    def render_missing_lines(
        self,
        chunk: ChunkProtocol,
        missing_indices: list[int],
        target_language: str,
    ) -> tuple[str, str]:
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
        source_content = chunk.prepare_for_prompt(missing_indices)

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
            RetryTemplate.Retry_Missing_Lines_Targeted_Template, **params
        )

    def render_retry_fragments(
        self,
        target_language: str,
        original_text: str,
        incorrect_translation: str,
        expected_separators: int,
        actual_separators: int,
        mode: Literal["strict", "flexible"] = "strict",
    ) -> tuple[str, str]:
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
           Error: Si le mode n'est pas "NORMAL" ou "FLEXIBLE"

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

        params_normal: RetryFragmentsParams = {
            "target_language": target_language,
            "original_text": original_text,
            "incorrect_translation": incorrect_translation,
            "expected_separators": expected_separators,
            "actual_separators": actual_separators,
            "mode": mode,
        }
        return self.render_prompt(
            RetryTemplate.Retry_Fragments_Template, **params_normal
        )

    def render_retry_punctuation(
        self,
        target_language: str,
        original_text: str,
        incorrect_translation: str,
        expected_pairs: int,
        actual_pairs: int,
    ) -> tuple[str, str]:
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

        return self.render_prompt(RetryTemplate.Retry_Punctuation_Template, **params)

    def render_retry_sentence(
        self,
        chunk: ChunkProtocol,
        target_language: str,
        missing_indices: list[int],
        previous_translation: TranslatedChunk | None = None,
    ) -> tuple[str, str]:
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
        source_content = chunk.prepare_for_prompt(missing_indices)
        previous_content = (
            previous_translation.prepare_for_prompt(missing_indices)
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
        }

        return self.render_prompt(RetryTemplate.Retry_Sentence_Template, **params)

    # -----------------------------------
    # 🔹 Phase 0 : Analyse littéraire
    # -----------------------------------

    def render_analyze_chapter(
        self,
        chunk: ChapterPartChunk,
        target_language: str,
        partial_analysis_json: str | None = None,
    ) -> tuple[str, str]:
        """

        Args:

        Returns:
            Prompt système rendu prêt pour envoi au LLM avec use_json_mode=True

        """
        chapter_name: str = chunk.chapter.name
        current_block: int = chunk.part + 1  # index 0-based -> block 1-based
        total_blocks: int = chunk.total_parts
        block_text: str = chunk.prepare_for_prompt([])

        params: AnalyzeChapterParams = {
            "chapter_name": chapter_name,
            "current_block": current_block,
            "total_blocks": total_blocks,
            "existing_analysis": partial_analysis_json,
            "chapter_text": block_text,
            "is_last_block": chunk.is_last(),
            "genre": self._genre,
            "target_language": target_language,
        }

        return self.render_prompt(PhaseTemplate.Analyze_Chapter, **params)

    def render_analyze_chapter_layered(
        self,
        chunk: ChapterPartChunk,
        target_language: str,
        existing_analysis_json: str | None = None,
        seed_analysis_json: str | None = None,
        bootstrap: bool = False,
    ) -> tuple[str, str]:
        chapter_name: str = chunk.chapter.name
        current_block: int = chunk.part + 1  # index 0-based -> block 1-based
        total_blocks: int = chunk.total_parts
        block_text: str = chunk.prepare_for_prompt([])

        if bootstrap:
            params: AnalyzeChapterLayeredParams = {
                "target_language": target_language,
                "chapter_name": chapter_name,
                "current_block": current_block,
                "total_blocks": total_blocks,
                "chapter_text": block_text,
                "is_last_block": chunk.is_last(),
                "genre": self._genre,
            }
        elif current_block == 1 and seed_analysis_json:
            params = {
                "target_language": target_language,
                "chapter_name": chapter_name,
                "current_block": current_block,
                "total_blocks": total_blocks,
                "chapter_text": block_text,
                "is_last_block": chunk.is_last(),
                "genre": self._genre,
                "previous_chapter_analysis": seed_analysis_json,  # TODO: Passer l'analyse du chapitre précédent pour contexte inter-chapitre
            }
        elif existing_analysis_json is not None:
            params = {
                "target_language": target_language,
                "chapter_name": chapter_name,
                "current_block": current_block,
                "total_blocks": total_blocks,
                "chapter_text": block_text,
                "is_last_block": chunk.is_last(),
                "genre": self._genre,
                "existing_analysis": existing_analysis_json,
            }
        else:
            raise ValueError(
                "Paramètres insuffisants pour déterminer le mode d'analyse (bootstrap, seed ou incremental)"
            )

        return self.render_prompt(PhaseTemplate.Analyze_Chapter_Layered, **params)

    def render_retry_analysis_invalid_json(
        self,
        chapter_name: str,
        target_language: str,
        json_error_message: str,
        invalid_response: str,
    ) -> tuple[str, str]:
        """
        Rend le template retry_correct_analysis_invalid_json.jinja.

        Template de correction pour erreurs de syntaxe JSON lors de l'analyse littéraire.
        Fournit des conseils détaillés sur la syntaxe JSON et les erreurs courantes.

        Args:
            chapter_name: Nom du chapitre (ex: "Chapter 1", "Prologue")
            target_language: Langue cible pour les propositions de traduction
            json_error_message: Message d'erreur du JSONDecodeError
            invalid_response: Réponse JSON invalide du LLM (sera tronquée à 500 chars dans template)

        Returns:
            Prompt de correction rendu prêt pour retry avec reasoning

        Example:
            >>> prompt = renderer.render_retry_analysis_invalid_json(
            ...     chapter_name="Chapter 1",
            ...     target_language="français",
            ...     json_error_message="Expecting ',' delimiter: line 5 column 2",
            ...     invalid_response='{"chapitre": "Chapter 1" "analyse": {...}}'
            ... )
        """

        params: RetryAnalysisInvalidJsonParams = {
            "chapter_name": chapter_name,
            "target_language": target_language,
            "json_error_message": json_error_message,
            "invalid_response": invalid_response,
        }

        return self.render_prompt(
            RetryTemplate.Retry_Analysis_Invalid_Json_Template,
            **params,
        )

    def render_retry_analysis_missing_sections(
        self,
        chapter_name: str,
        target_language: str,
        missing_sections: list[str],
        incomplete_response: str,
        chapter_text: str,
    ) -> tuple[str, str]:
        """
        Rend le template retry_correct_analysis_missing_sections.jinja.

        Template de correction pour sections manquantes dans l'analyse littéraire.
        Liste les sections manquantes avec guidance pour chaque type de section.

        Args:
            chapter_name: Nom du chapitre (ex: "Chapter 1", "Prologue")
            target_language: Langue cible pour les propositions de traduction
            missing_sections: Liste des sections manquantes (ex: ["analyse.resume_narratif", "glossaire[2].sexe"])

        Returns:
            Prompt de correction rendu prêt pour retry avec reasoning

        Example:
            >>> prompt = renderer.render_retry_analysis_missing_sections(
            ...     chapter_name="Chapter 1",
            ...     target_language="français",
            ...     missing_sections=["analyse.resume_narratif", "glossaire[0].sexe"]
            ... )
        """

        params: RetryAnalysisMissingSectionsParams = {
            "chapter_name": chapter_name,
            "target_language": target_language,
            "missing_sections": missing_sections,
            "incomplete_response": incomplete_response,
            "chapter_text": chapter_text,
        }

        return self.render_prompt(
            RetryTemplate.Retry_Analysis_Missing_Sections_Template,
            **params,
        )

    # -----------------------------------
    # 🔹 Phase 0 : Glossaire
    # -----------------------------------

    def render_glossary(
        self,
        chunk: Chunk,
        target_language: str,
        glossary: Glossary | None = None,
    ) -> tuple[str, str]:
        """
        Placeholder pour futur template de correction du glossaire.

        Ce template sera utilisé pour corriger les entrées du glossaire qui sont
        incorrectes, incomplètes ou mal formatées. Il fournira des instructions
        spécifiques selon le type d'erreur
        """
        block_text = chunk.prepare_for_prompt([])
        params: GlossaryParams = {
            "block_text": block_text,
            "target_language": target_language,
            "genre": self._genre,
            "existing_glossary": (
                glossary.collect_entry_with_conflicts(block_text) if glossary else None
            ),
        }
        return self.render_prompt(PhaseTemplate.Glossary, **params)
