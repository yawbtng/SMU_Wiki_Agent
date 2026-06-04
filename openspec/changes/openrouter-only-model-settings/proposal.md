## Why

The operator path should use OpenRouter only. Ollama/local-provider settings create confusion, hidden local dependencies, and cost fields that do not match the deployed model path.

## What Changes

- Remove Ollama/local provider normalization from app state.
- Make model settings explicit OpenRouter selectors.
- Show estimated cost for the selected OpenRouter models in the Settings UI.
- Change embedding client configuration from Ollama defaults to OpenRouter defaults.

## Impact

- Affected frontend: Settings model and Settings UI.
- Affected backend: app-state normalization and embedding client defaults.
- Affected tests: settings/state/embedding client tests.
