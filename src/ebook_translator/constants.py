"""
Constantes utilisées pour le parsing et la manipulation des pages HTML.
"""

# Séparateur utilisé pour joindre les fragments de texte multiples
FRAGMENT_SEPARATOR = "</>"

# Balises HTML considérées comme racines pour le regroupement de texte
VALID_ROOT_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6"}

# Balises à ignorer lors de l'extraction de texte
IGNORED_TAGS = {"script", "style"}

# Ratio par défaut du chevauchement entre chunks (15%)
DEFAULT_OVERLAP_RATIO = 0.15

# Encodage par défaut pour le comptage de tokens (OpenAI o200k_base)
DEFAULT_ENCODING = "o200k_base"
