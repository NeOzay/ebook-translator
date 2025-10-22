"""
Tests pour vérifier les améliorations de qualité de traduction (v0.4.0).

Ces tests vérifient :
1. La température par défaut est optimisée pour la cohérence
2. Le prompt contient les instructions de style et registre
3. Le prompt contient des exemples few-shot learning
"""

import pytest
from ebook_translator.llm import LLM


class TestLLMConfiguration:
    """Tests de configuration du LLM."""

    def test_default_temperature_is_optimized(self):
        """Vérifie que la température par défaut favorise la cohérence."""
        llm = LLM(
            model_name="test-model",
            url="https://api.example.com",
            api_key="test-key",
        )

        # La température doit être <= 0.5 pour plus de cohérence
        assert llm.temperature <= 0.5, (
            f"Temperature should be <= 0.5 for consistency, got {llm.temperature}"
        )

    def test_custom_temperature_is_respected(self):
        """Vérifie que la température personnalisée est respectée."""
        llm = LLM(
            model_name="test-model",
            url="https://api.example.com",
            api_key="test-key",
            temperature=0.8,
        )

        assert llm.temperature == 0.8


class TestPromptEnhancements:
    """Tests pour les améliorations du prompt de traduction."""

    @pytest.fixture
    def llm(self):
        """Fixture pour créer une instance LLM."""
        return LLM(
            model_name="test-model",
            url="https://api.example.com",
            api_key="test-key",
        )

    def test_prompt_contains_style_instructions(self, llm):
        """Vérifie que le prompt contient les instructions de style."""
        prompt = llm.render_prompt(
            "translate.jinja",
            target_language="français",
            user_prompt=None,
        )

        # Instructions de préservation du style
        assert "Préservation du style et du registre" in prompt
        assert "registre de langue" in prompt
        assert "figures de style" in prompt
        assert "métaphores" in prompt
        assert "tutoiement/vouvoiement" in prompt

    def test_prompt_contains_terminology_consistency(self, llm):
        """Vérifie que le prompt contient les instructions de cohérence terminologique."""
        prompt = llm.render_prompt(
            "translate.jinja",
            target_language="français",
            user_prompt=None,
        )

        assert "Cohérence terminologique" in prompt
        assert "noms propres" in prompt
        assert "termes techniques" in prompt
        assert "cohérence" in prompt

    def test_prompt_contains_few_shot_examples(self, llm):
        """Vérifie que le prompt contient des exemples few-shot."""
        prompt = llm.render_prompt(
            "translate.jinja",
            target_language="français",
            user_prompt=None,
        )

        # Section d'exemples
        assert "Exemples de traduction de qualité" in prompt
        assert "✅ Bonne traduction" in prompt
        assert "❌ Mauvaise traduction" in prompt

    def test_prompt_contains_style_preservation_example(self, llm):
        """Vérifie qu'il y a un exemple de préservation du style."""
        prompt = llm.render_prompt(
            "translate.jinja",
            target_language="français",
            user_prompt=None,
        )

        # Exemple de préservation du style narratif
        assert "Préservation du style narratif" in prompt
        assert "préserve métaphore" in prompt

    def test_prompt_contains_terminology_consistency_example(self, llm):
        """Vérifie qu'il y a un exemple de cohérence terminologique."""
        prompt = llm.render_prompt(
            "translate.jinja",
            target_language="français",
            user_prompt=None,
        )

        # Exemple de cohérence terminologique
        assert "Cohérence des noms propres" in prompt
        assert "cohérence terminologique" in prompt

    def test_prompt_contains_fragment_separator_example(self, llm):
        """Vérifie qu'il y a un exemple de gestion des séparateurs."""
        prompt = llm.render_prompt(
            "translate.jinja",
            target_language="français",
            user_prompt=None,
        )

        # Exemple de gestion des balises </> multiples
        assert "Gestion des balises `</>`" in prompt
        assert "même nombre" in prompt

    def test_prompt_contains_register_preservation_example(self, llm):
        """Vérifie qu'il y a un exemple de préservation du registre."""
        prompt = llm.render_prompt(
            "translate.jinja",
            target_language="français",
            user_prompt=None,
        )

        # Exemple de préservation du registre de langue
        assert "Préservation du registre de langue" in prompt
        assert "registre familier" in prompt or "conversation informelle" in prompt

    def test_prompt_forbids_style_changes(self, llm):
        """Vérifie que le prompt interdit de changer le style."""
        prompt = llm.render_prompt(
            "translate.jinja",
            target_language="français",
            user_prompt=None,
        )

        # Interdiction de changer le style
        assert "Changer le niveau de formalité" in prompt or "style narratif" in prompt


class TestBackwardCompatibility:
    """Tests pour vérifier la compatibilité ascendante."""

    def test_llm_can_be_created_without_temperature(self):
        """Vérifie que LLM peut être créé sans spécifier la température."""
        llm = LLM(
            model_name="test-model",
            url="https://api.example.com",
            api_key="test-key",
        )

        # Doit avoir une température par défaut
        assert hasattr(llm, "temperature")
        assert isinstance(llm.temperature, float)

    def test_prompt_still_has_mandatory_rules(self):
        """Vérifie que les règles obligatoires sont toujours présentes."""
        llm = LLM(
            model_name="test-model",
            url="https://api.example.com",
            api_key="test-key",
        )

        prompt = llm.render_prompt(
            "translate.jinja",
            target_language="français",
            user_prompt=None,
        )

        # Règles obligatoires
        assert "RÈGLE ABSOLUE" in prompt
        assert ("TOUTES les lignes" in prompt or "TOUTES ET SEULEMENT les lignes" in prompt)
        assert "SANS EXCEPTION" in prompt
        assert "[=[END]=]" in prompt
