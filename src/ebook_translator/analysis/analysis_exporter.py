"""
Exporteur d'analyses littéraires au format Markdown.

Ce module transforme les fiches d'analyse JSON (format machine)
en documents Markdown formatés pour lecture humaine.

Formats de sortie:
- JSON: Format brut pour parsing programmatique
- Markdown: Format lisible pour revue manuelle, rapports, documentation

Structure Markdown générée:
1. En-tête (metadata)
2. Personnages (tableau avec rôles, relations)
3. Lieux (primaire + secondaires)
4. Intrigue (événements, conflits, révélations)
5. Thèmes et symboles
6. Techniques narratives (POV, ton, dispositifs)
7. Terminologie (termes spécialisés + noms propres)
8. Notes stylistiques
9. Considérations pour la traduction
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from .schema import ChapterAnalysis

if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


class AnalysisExporter:
    """
    Exporte les analyses littéraires au format Markdown.

    Génère des documents Markdown structurés et lisibles pour
    revue manuelle, rapports et documentation.

    Example:
        >>> exporter = AnalysisExporter()
        >>> markdown = exporter.export_to_markdown(analysis)
        >>> exporter.save_markdown(markdown, "Chapter_1.md")
    """

    def __init__(self):
        """Initialise l'exporteur."""
        pass

    def export_to_markdown(self, analysis: ChapterAnalysis) -> str:
        """
        Exporte une analyse au format Markdown.

        Génère un document structuré avec sections, tableaux et listes
        pour faciliter la lecture humaine.

        Args:
            analysis: Analyse à exporter

        Returns:
            Contenu Markdown formaté

        Example:
            >>> md = exporter.export_to_markdown(analysis)
            >>> print(md[:100])
            # Chapter 1

            **Status**: complete
            ...
        """
        parts: list[str] = []

        # 1. En-tête
        parts.append(f"# {analysis['chapter_name']}\n")
        parts.append(f"**Status**: {analysis['status']}\n")
        parts.append(
            f"**Blocs analysés**: {analysis['blocks_analyzed']}/{analysis['total_blocks']}\n"
        )
        parts.append(f"**Version**: {analysis['analysis_version']}\n")
        parts.append("\n---\n")

        # 2. Personnages
        parts.append("\n## 👤 Personnages\n")
        characters = analysis.get("characters", {})

        present = characters.get("present", [])
        if present:
            parts.append("\n### Présents dans ce chapitre\n")
            for char in present:
                name = char.get("name", "Inconnu")
                role = char.get("role", "N/A")
                desc = char.get("description", "")
                dev_notes = char.get("development_notes", "")

                parts.append(f"\n**{name}** ({role})")
                if desc:
                    parts.append(f"\n- Description: {desc}")
                if dev_notes:
                    parts.append(f"\n- Développement: {dev_notes}")

                relationships = char.get("relationships", [])
                if relationships:
                    parts.append(f"\n- Relations: {', '.join(relationships)}")

                parts.append("\n")

        mentioned = characters.get("mentioned", [])
        if mentioned:
            parts.append("\n### Mentionnés\n")
            parts.append(", ".join(mentioned))
            parts.append("\n")

        # 3. Lieux
        parts.append("\n## 📍 Lieux\n")
        locations = analysis.get("locations", {})

        primary = locations.get("primary", {})
        if primary and isinstance(primary, dict):
            name = primary.get("name", "")
            if name:
                parts.append(f"\n### Lieu principal: {name}\n")
                desc = primary.get("description", "")
                if desc:
                    parts.append(f"- Description: {desc}\n")
                atmosphere = primary.get("atmosphere", "")
                if atmosphere:
                    parts.append(f"- Atmosphère: {atmosphere}\n")

        secondary = locations.get("secondary", [])
        if secondary:
            parts.append("\n### Lieux secondaires\n")
            for loc in secondary:
                if isinstance(loc, dict):
                    loc_name = loc.get("name", "")
                elif isinstance(loc, str):
                    loc_name = loc
                else:
                    loc_name = ""

                if loc_name:
                    parts.append(f"- {loc_name}\n")

        # 4. Intrigue
        parts.append("\n## 📖 Intrigue\n")
        plot = analysis.get("plot_elements", {})

        main_events = plot.get("main_events", [])
        if main_events:
            parts.append("\n### Événements principaux\n")
            for event in main_events:
                parts.append(f"- {event}\n")

        conflicts = plot.get("conflicts", [])
        if conflicts:
            parts.append("\n### Conflits\n")
            for conflict in conflicts:
                conflict_type = conflict.get("type", "N/A")
                desc = conflict.get("description", "")
                parties = conflict.get("parties_involved", [])
                parts.append(f"\n**Type**: {conflict_type}\n")
                if desc:
                    parts.append(f"- {desc}\n")
                if parties:
                    parts.append(f"- Parties impliquées: {', '.join(parties)}\n")

        foreshadowing = plot.get("foreshadowing", [])
        if foreshadowing:
            parts.append("\n### Foreshadowing\n")
            for item in foreshadowing:
                parts.append(f"- {item}\n")

        revelations = plot.get("revelations", [])
        if revelations:
            parts.append("\n### Révélations\n")
            for rev in revelations:
                parts.append(f"- {rev}\n")

        # 5. Thèmes
        parts.append("\n## 🎭 Thèmes\n")
        themes = analysis.get("themes", {})

        identified = themes.get("identified", [])
        if identified:
            for theme_entry in identified:
                theme_name = theme_entry.get("theme", "")
                development = theme_entry.get("development", "")
                evidence = theme_entry.get("evidence", [])

                parts.append(f"\n### {theme_name}\n")
                if development:
                    parts.append(f"{development}\n")
                if evidence:
                    parts.append("\n**Éléments de preuve**:\n")
                    for ev in evidence:
                        parts.append(f"- {ev}\n")

        # 6. Techniques narratives
        parts.append("\n## ✍️ Techniques narratives\n")
        narrative = analysis.get("narrative_techniques", {})

        pov = narrative.get("pov", "")
        if pov:
            parts.append(f"- **Point de vue**: {pov}\n")

        tense = narrative.get("tense", "")
        if tense:
            parts.append(f"- **Temps**: {tense}\n")

        tone = narrative.get("tone", "")
        if tone:
            parts.append(f"- **Ton**: {tone}\n")

        devices = narrative.get("narrative_devices", [])
        if devices:
            parts.append(f"- **Dispositifs**: {', '.join(devices)}\n")

        # 7. Terminologie
        parts.append("\n## 📚 Terminologie\n")
        terminology = analysis.get("terminology", {})

        specialized = terminology.get("specialized_terms", [])
        if specialized:
            parts.append("\n### Termes spécialisés\n")
            for term_entry in specialized:
                term = term_entry.get("term", "")
                context = term_entry.get("context", "")
                category = term_entry.get("category", "")
                translation_notes = term_entry.get("translation_notes", "")

                parts.append(f"\n**{term}** ({category})")
                if context:
                    parts.append(f"\n- Contexte: {context}")
                if translation_notes:
                    parts.append(f"\n- Notes traduction: {translation_notes}")
                parts.append("\n")

        proper_nouns = terminology.get("proper_nouns", {})
        if any(proper_nouns.values()):
            parts.append("\n### Noms propres\n")

            names = proper_nouns.get("names", [])
            if names:
                parts.append(f"- **Noms**: {', '.join(names)}\n")

            places = proper_nouns.get("places", [])
            if places:
                parts.append(f"- **Lieux**: {', '.join(places)}\n")

            organizations = proper_nouns.get("organizations", [])
            if organizations:
                parts.append(f"- **Organisations**: {', '.join(organizations)}\n")

        # 8. Notes stylistiques
        parts.append("\n## 🎨 Style\n")
        style = analysis.get("stylistic_notes", {})

        writing_style = style.get("writing_style", "")
        if writing_style:
            parts.append(f"**Style d'écriture**: {writing_style}\n\n")

        motifs = style.get("recurring_motifs", [])
        if motifs:
            parts.append("**Motifs récurrents**:\n")
            for motif in motifs:
                parts.append(f"- {motif}\n")

        symbolic = style.get("symbolic_elements", [])
        if symbolic:
            parts.append("\n**Éléments symboliques**:\n")
            for symbol in symbolic:
                parts.append(f"- {symbol}\n")

        cultural = style.get("cultural_references", [])
        if cultural:
            parts.append("\n**Références culturelles**:\n")
            for ref in cultural:
                parts.append(f"- {ref}\n")

        # 9. Considérations pour la traduction
        parts.append("\n## 🔄 Considérations pour la traduction\n")
        translation_notes = analysis.get("translation_considerations", {})

        challenges = translation_notes.get("challenges", [])
        if challenges:
            parts.append("\n### Défis\n")
            for challenge in challenges:
                parts.append(f"- {challenge}\n")

        consistency_reqs = translation_notes.get("consistency_requirements", [])
        if consistency_reqs:
            parts.append("\n### Exigences de cohérence\n")
            for req in consistency_reqs:
                parts.append(f"- {req}\n")

        return "".join(parts)

    def save_markdown(self, markdown_content: str, output_path: Path | str) -> None:
        """
        Sauvegarde le contenu Markdown dans un fichier.

        Args:
            markdown_content: Contenu Markdown à sauvegarder
            output_path: Chemin du fichier de sortie

        Example:
            >>> md = exporter.export_to_markdown(analysis)
            >>> exporter.save_markdown(md, "cache/analysis/Chapter_1.md")
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("w", encoding="utf-8") as f:
            f.write(markdown_content)

        logger.info(f"Exporté Markdown: {output_path}")

    def export_all_to_markdown(
        self,
        analyses: dict[str, ChapterAnalysis],
        output_dir: Path | str,
    ) -> dict[str, Path]:
        """
        Exporte toutes les analyses au format Markdown.

        Args:
            analyses: Dictionnaire {chapter_name: ChapterAnalysis}
            output_dir: Répertoire de sortie

        Returns:
            Dictionnaire {chapter_name: Path du fichier Markdown}

        Example:
            >>> paths = exporter.export_all_to_markdown(analyses, "cache/analysis")
            >>> for chapter, path in paths.items():
            ...     print(f"{chapter}: {path}")
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        result: dict[str, Path] = {}

        for chapter_name, analysis in analyses.items():
            # Nettoyer le nom de fichier
            safe_name = chapter_name.replace("/", "_").replace("\\", "_").replace(":", "_")
            md_path = output_dir / f"{safe_name}.md"

            # Exporter
            markdown = self.export_to_markdown(analysis)
            self.save_markdown(markdown, md_path)

            result[chapter_name] = md_path

        logger.info(f"Exporté {len(result)} analyses au format Markdown")
        return result
