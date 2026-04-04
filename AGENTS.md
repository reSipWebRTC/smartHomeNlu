# Repository Guidelines

## Project Structure & Module Organization
- `runtime/`: core SmartHome NLU runtime (routing, policy, execution, adapters, FastAPI server).
- `runtime/web/`: lightweight web console (`index.html`, `app.js`, `style.css`) for API validation.
- `tests/`: Python unit/integration tests for runtime, adapters, HTTP endpoints, and flow behavior.
- `scripts/`: helper utilities (for example, channel comparison tooling).
- `sherpa-asr-android/`: Android ASR client integrated with `/api/v1/command` and `/api/v1/confirm`.
- `docs/`: design and exported documentation artifacts.

## Build, Test, and Development Commands
- Install dependencies: `python3 -m pip install -r requirements.txt`
- Start runtime directly:
  - `redis-server --port 6379`
  - `SMARTHOME_REDIS_URL=redis://127.0.0.1:6379/0 uvicorn runtime.server:app --host 0.0.0.0 --port 8000`
- One-click local workflow:
  - `./run_local.sh all` (start + acceptance checks)
  - `./run_local.sh up | check | down`
- Run tests:
  - `python3 -m pytest -q`
  - `python3 -m unittest discover -s tests -v`
- Optional Android build:
  - `cd sherpa-asr-android && ./gradlew :app:assembleDebug`

## Coding Style & Naming Conventions
- Python: PEP 8, 4-space indentation, `snake_case` for functions/variables, `PascalCase` for classes, keep type hints where already used.
- Kotlin: 4-space indentation, `PascalCase` classes, `camelCase` members.
- Keep API field naming aligned with runtime contracts (`/api/v1/*` payloads and response envelope).
- Do not commit generated artifacts, logs, or model binaries; rely on `.gitignore`.

## Testing Guidelines
- Place tests under `tests/` with `test_*.py` filenames and `test_*` function names.
- Add/adjust tests for every runtime behavior change (routing, policy, adapter mapping, response shape).
- Validate both success and failure paths (status/code/message/data), especially around confirm and idempotency flows.

## Commit & Pull Request Guidelines
- Follow Conventional Commit style used in history: `feat:`, `fix:`, `docs:`, `chore:`.
- Keep commits focused and module-scoped.
- PRs should include:
  - What changed and why
  - Commands executed (build/tests) and results
  - Sample request/response when API behavior changes
  - Screenshots for web or Android UI updates

## Security & Configuration Tips
- Use environment variables for secrets/tokens (for example `SMARTHOME_HA_MCP_TOKEN`); never hardcode credentials.
- Large local assets are intentionally excluded (Android model assets under `app/src/main/assets/*`, build intermediates, `.runtime_local/`, `docs/*.zip`).
