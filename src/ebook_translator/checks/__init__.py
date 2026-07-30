"""Validation contenu des sorties LLM.

Deux niveaux de validation cohabitent dans le pipeline :

- **schéma** : porté par le modèle Pydantic de la phase (`payload_type`),
  qui garantit la structure de la sortie LLM.
- **contenu** : porté par les `ContentCheck` de ce paquet, qui vérifient la
  fidélité au texte source une fois la structure acquise.

Ce paquet n'expose rien à sa racine : importer depuis les sous-modules
(`checks.content_check` pour le Protocol, `checks.content` pour les
implémentations). Un ré-export ici refermerait le cycle
`checks` ↔ `validation` que `validation.failure` évite déjà sous
`TYPE_CHECKING`.
"""
