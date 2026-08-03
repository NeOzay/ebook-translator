# Adaptateur Mistral (SDK `mistralai`)

## Contexte

Le projet ne dispose que d'un seul provider LLM : `Deepseek`. Le socle dont il hérite,
`OpenAIClientBase` ([client.py:110](src/ebook_translator/llm/clients/client.py#L110)), est soudé au
SDK `openai` — il construit un `OpenAI(...)` en dur, appelle `chat.completions.create()`, patche
`instructor.from_openai(mode=Mode.JSON)` et parse un `openai.types.chat.ChatCompletion`.

L'objectif est d'ajouter un provider **Mistral** utilisant le **package officiel `mistralai`**
(et non l'endpoint OpenAI-compatible), avec **Mistral Large** comme modèle visé.

Recherches API effectuées :

| Point | Résultat |
|---|---|
| SDK | `mistralai` 2.8.0, `requires-python >=3.10` (compatible avec le `>=3.14` du projet) |
| Client | `from mistralai import Mistral` → `Mistral(api_key=...)` |
| Appel texte | `client.chat.complete(model, messages, temperature, top_p, max_tokens, stop, random_seed, response_format, tools, presence_penalty, frequency_penalty, n, reasoning_effort, prompt_mode, safe_prompt, prompt_cache_key, ...)` → `ChatCompletionResponse` |
| Modèle cible | `mistral-large-latest` → alias de `mistral-large-2512` (Mistral Large 3, 256k de contexte) |
| Capacités Large 3 | Function calling ✅, Structured Outputs ✅. **Pas de `reasoning_effort` documenté** |
| Structured output | `instructor` 1.15.1 embarque déjà `from_mistral(client, mode=Mode.MISTRAL_TOOLS \| Mode.MISTRAL_STRUCTURED_OUTPUTS)` ([providers/mistral/client.py:28](.venv/lib/python3.14/site-packages/instructor/providers/mistral/client.py)). ⚠️ `Mode.JSON` lève un `ModeError` avec Mistral |

Décisions validées avec l'utilisateur : socle agnostique extrait · `instructor.from_mistral` ·
enum Small/Medium/Large · exceptions internes **ajoutées** sans toucher au chemin DeepSeek.

Résultat attendu : `PipelineBuilder().llm(LLMBuilder().default_client(Mistral(MistralModels.LARGE)))`
fonctionne sur les 4 phases, y compris la Phase 0 (sortie structurée via Instructor), avec les mêmes
logs d'échange et le même comportement de retry que DeepSeek.

---

## Étapes

### 1. Dépendance `mistralai`

`pyproject.toml` → ajouter `"mistralai>=2.8.0,<3.0.0"` aux `dependencies` (dépendance **dure**, comme
`openai` et `instructor` — le repo n'a aucun précédent d'`optional-dependencies`, en introduire un
ici obligerait à rendre l'import conditionnel dans tout le module). Puis `uv sync --group dev`.

### 2. Extraire le socle agnostique — `llm/clients/base.py`

Créer `LLMClientBase[ModelsEnum: StrEnum, ThinkingEnum: str, UserData: UserKwargs, Data: FullKwargs]`
`(ClientProviderProtocol[UserData, Data], ABC)` en **déplaçant tel quel** depuis `client.py` :

- `Models: type[ModelsEnum]`, `_parameters: Data`, propriété `parameters` + setter (l. 118-134)
- `merged_config`, `applied_config` (l. 223-235)
- `set_preset_config`, `set_config`, `get_default_config`, `set_default_config` (l. 179-221)
- les abstraits `_resolve_config` (+ ses 3 `@overload`), `get_model_preset_config`, `get_model_config`
- le logging : `write_header`, `write_prompt`, `write_response` (l. 360-423)
- `__init__(api_key, config)` : conserve la logique de résolution de config (l. 147-152) et délègue
  la construction du SDK à un nouvel abstrait `_build_sdk_client(api_key: str) -> None`

Nouveaux points d'extension abstraits :

| Membre | Signature | OpenAI | Mistral |
|---|---|---|---|
| `_build_sdk_client` | `(self, api_key: str) -> None` | `self.openai = OpenAI(api_key, base_url=self.base_url)` | `self.mistral = MistralSDK(api_key=api_key)` |
| `_send` | `(self, params: Data) -> Any` | `self.openai.chat.completions.create(**params)` | `self.mistral.chat.complete(**params)` |
| `_build_instructor` | `(self) -> instructor.Instructor` | `from_openai(self.openai, mode=Mode.JSON)` | `from_mistral(self.mistral, mode=Mode.MISTRAL_TOOLS)` |
| `parse` | `(self, response: Any) -> LLMResponse` | actuelle (l. 425-456) | nouvelle (voir étape 4) |
| `_api_key_env` | `ClassVar[str \| None]` | `None` | `"MISTRAL_API_KEY"` |

`request` et `json_request` deviennent **concrets et partagés** dans `base.py`, en appelant `_send` /
`_build_instructor` / `parse`. Les `Hooks` de logging (l. 300-346) montent tels quels : ils sont
agnostiques, `log_response` passe simplement par `self.parse`.

⚠️ `parse` passe de `@staticmethod` à méthode d'instance (polymorphisme requis) — vérifier
`reportIncompatibleMethodOverride`.

`client.py` conserve `get_api_key`, `ClientProviderProtocol` (inchangé) et
`OpenAIClientBase(LLMClientBase)` réduite à `base_url`, `_build_sdk_client`, `_send`,
`_build_instructor`, `parse`. **`deepseek.py` n'est pas modifié** — c'est le critère de non-régression.

`get_api_key` est appelée avec `_api_key_env` (et non plus avec la clé elle-même comme en
[client.py:142](src/ebook_translator/llm/clients/client.py#L142)) : `MISTRAL_API_KEY` d'abord,
repli sur `API_KEY`. Comportement DeepSeek inchangé (`_api_key_env = None`).

### 3. Exceptions internes — `llm/errors.py`

```python
class LLMClientError(Exception): ...
class LLMTimeoutError(LLMClientError): ...
class LLMRateLimitError(LLMClientError): ...
class LLMAPIError(LLMClientError): ...
```

Dans [llm.py:122-158](src/ebook_translator/llm/llm.py#L122), élargir les clauses existantes **sans
en retirer aucune** : `except (APITimeoutError, LLMTimeoutError)`, `except (RateLimitError,
LLMRateLimitError)`, `except (APIError, OpenAIError, LLMAPIError)`. Le backoff (`2**attempt` /
`3**attempt`) et les messages sont conservés.

### 4. Le client — `llm/clients/mistral.py`

Calqué sur `deepseek.py` (forward-refs string pour les TypedDicts, alias `type LLMConfigMistral`,
`Models = MistralModels`).

```python
from mistralai import Mistral as MistralSDK   # alias : la classe publique du repo s'appelle Mistral

class MistralModels(StrEnum):
    SMALL = "mistral-small-latest"
    MEDIUM = "mistral-medium-latest"
    LARGE = "mistral-large-latest"
```

- `Mistral(LLMClientBase[MistralModels, Never, "UserMistralKwargs", "FullMistralKwargs"])`
- `__init__(model_name: Models = Models.LARGE, thinking: bool = False, api_key=None, config=None)`
  — même forme que `Deepseek.__init__`, défaut sur **LARGE**
- `get_model_preset_config` : `low → SMALL`, `high → MEDIUM`, `max → LARGE`
- `get_model_config` : `{"model": model_name.value}` + fusion de la config résolue,
  `return LLMConfigExport(merged_config, cls)` (⚠️ `cls` exactement, égalité stricte en
  [llm_config.py:70](src/ebook_translator/llm/llm_config.py#L70))
- `_resolve_config` : branche `GenericLLMConfig` → `temperature` / `top_p` / `max_tokens`.
  **`use_thinking` est ignoré** (Mistral Large 3 n'expose pas de mode raisonnement) : le drop est
  explicite et documenté dans la docstring. `prompt_mode` reste disponible dans le TypedDict pour
  qui veut le forcer à la main.
- `UserMistralKwargs(UserKwargs, total=False)` : `temperature`, `top_p`, `max_tokens`, `stop`,
  `random_seed`, `presence_penalty`, `frequency_penalty`, `n`, `response_format`, `safe_prompt`,
  `prompt_mode`, `prompt_cache_key`
- `FullMistralKwargs(UserMistralKwargs, FullKwargs, total=False, extra_items=Any)` :
  `model: Required[Literal["mistral-small-latest", "mistral-medium-latest", "mistral-large-latest"] | str]`

**`parse(response: ChatCompletionResponse) -> LLMResponse`** — le vrai point d'adaptation :

| Champ `LLMResponse` | Source Mistral |
|---|---|
| `content` | `choices[0].message.content` — peut être `str \| list[ContentChunk] \| None` : concaténer le `.text` des chunks textuels si c'est une liste |
| `reasoning` | `None` |
| `tool_calls` | `choices[0].message.tool_calls` |
| `finish_reason` | `choices[0].finish_reason` (peut être `None` → `""`) |
| `prompt_tokens` / `completion_tokens` | `usage.prompt_tokens` / `usage.completion_tokens` |
| `cached_tokens` / `reasoning_tokens` | `0` (non fournis par l'API) |
| `model` / `response_id` | `response.model` / `response.id` |

`LLMResponse.tool_calls` est typé `list[ChatCompletionMessageToolCallUnion]` (openai) en
[llm_config.py:87](src/ebook_translator/llm/llm_config.py#L87). Élargir vers un `Protocol`
minimal `ToolCallLike` (`type`, `function.name`, `function.arguments`) — c'est tout ce que
`write_response` ([client.py:418-423](src/ebook_translator/llm/clients/client.py#L418)) consomme.

**Traduction des erreurs** : envelopper `_send` et l'appel Instructor pour convertir
`mistralai.models.SDKError` (selon `status_code` : 429 → `LLMRateLimitError`, autre → `LLMAPIError`),
`httpx.TimeoutException` → `LLMTimeoutError`, `httpx.HTTPError` → `LLMAPIError`.

### 5. Exports, exemple, documentation

- `llm/__init__.py` : `from .clients.mistral import Mistral, MistralModels` + `__all__`
- `examples/example_pipeline_mistral.py`, calqué sur `example_pipeline.py`
- `.env.example` (`MISTRAL_API_KEY`), `README.md` + `README.fr.md` (l. ~117), `CLAUDE.md`
  (tableau des variables d'environnement + `Key Modules`), `docs/ARCHITECTURE.md` (l. ~217)

### 6. Tests — `tests/llm/`

Pas de test existant pour les clients : on part de zéro, en réutilisant le pattern de
`tests/pipeline/test_builder.py:37-46` (fixture autouse `monkeypatch.setenv("API_KEY", ...)`
pour neutraliser le `sys.exit(1)` de `get_api_key`).

- `test_mistral_client.py` : construction sans réseau ; `get_model_preset_config` mappe bien
  low/high/max → SMALL/MEDIUM/LARGE ; `_resolve_config` traduit `GenericLLMConfig` et drope
  `use_thinking` ; `parse()` sur un `ChatCompletionResponse` factice (dont le cas `content` en
  liste de chunks) ; `request()` avec `self.mistral.chat.complete` mocké, en vérifiant les kwargs
  transmis ; `Mistral()` satisfait `isinstance(..., ClientProviderProtocol)`
- `test_error_mapping.py` : `SDKError(429)` → `LLMRateLimitError`, `httpx.TimeoutException` →
  `LLMTimeoutError` ; et via `LLM.query`, qu'un `LLMRateLimitError` déclenche bien le backoff et
  le retry
- `test_client_base.py` : non-régression du socle extrait — `merged_config` (`None` ⇒ `pop`),
  `applied_config`, chaîne des presets, sur une sous-classe factice de `LLMClientBase`

---

## Vérification

```bash
uv sync --group dev
uv run basedpyright src/                 # doit rendre 0 erreur
uv run pytest --no-cov                   # tous les tests passent (la gate 80 % échoue déjà, cf. CLAUDE.md)
uv run pre-commit run --all-files        # ruff format + ruff check + basedpyright
```

Non-régression DeepSeek : `uv run pytest --no-cov tests/pipeline/test_builder.py tests/llm/` doit
passer sans modification d'aucun de ces fichiers.

Bout en bout, avec une vraie clé (`MISTRAL_API_KEY` dans `.env`) :

```bash
uv run python examples/example_pipeline_mistral.py     # Phases 1 + 2, chemin texte
uv run python examples/example_phase0_analysis.py      # adapté sur Mistral : chemin Instructor
```

Contrôler dans les logs d'échange (`write_header` / `write_prompt` / `write_response`) que le modèle
est bien `mistral-large-latest`, que les tokens sont comptés, et que la Phase 0 renvoie un
`AnalyseChapter` valide.

---

## Hors-périmètre

- Le chemin **asynchrone** (`complete_async`, `from_mistral(use_async=True)`) — le pipeline est synchrone
- Le **streaming** (`chat.stream`) — non supporté par le socle actuel, quel que soit le provider
- Le **multimodal** (images, documents), les **embeddings**, l'**OCR**, les **agents** Mistral
- La migration du chemin DeepSeek vers les exceptions internes (décidée en « ajout » seulement)
- Les modèles **Magistral** / le mode raisonnement Mistral
