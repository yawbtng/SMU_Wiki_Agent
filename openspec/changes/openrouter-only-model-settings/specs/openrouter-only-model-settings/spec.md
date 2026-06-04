## ADDED Requirements

### Requirement: OpenRouter-only model settings

The operator app SHALL expose OpenRouter model selections only for LLM/retrieval model configuration.

#### Scenario: Settings UI selects OpenRouter models

- **WHEN** the operator opens Settings
- **THEN** URL reasoning, wiki enrichment, wiki Q&A, and embedding model fields are rendered as OpenRouter model selectors
- **AND** no Ollama/local provider selector is shown.

### Requirement: Model cost estimate

The Settings UI SHALL show an estimated cost for selected OpenRouter models.

#### Scenario: Cost changes with selected model

- **WHEN** the operator changes a selected model
- **THEN** the displayed estimated input/output and total cost updates based on that model's configured pricing.

### Requirement: No Ollama app-state support

The backend SHALL normalize legacy provider state to OpenRouter and avoid persisting Ollama-specific fields.

#### Scenario: Legacy Ollama state is saved

- **WHEN** app state contains `ollama`, `local`, `ollama_model`, or `ollama_base_url`
- **THEN** the persisted state uses OpenRouter provider values
- **AND** Ollama-specific keys are omitted.
