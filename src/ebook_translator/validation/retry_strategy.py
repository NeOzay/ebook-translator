"""Stratégies de progression du modèle LLM entre tentatives de retry."""

from __future__ import annotations

from enum import StrEnum


class RetryStrategy(StrEnum):
    """Politique de sélection du modèle entre tentatives.

    - `NORMAL_ONLY`: toutes les tentatives utilisent le modèle normal
      (par exemple `deepseek-chat`).
    - `PROGRESSIVE_REASONING`: tentative 0 normale, tentatives suivantes
      bascules sur le modèle reasoning (par exemple `deepseek-reasoner`).
    - `REASONING_ONLY`: toutes les tentatives utilisent le modèle reasoning.
    """

    NORMAL_ONLY = "normal_only"
    PROGRESSIVE_REASONING = "progressive"
    REASONING_ONLY = "reasoning_only"
