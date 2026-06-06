from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_docker_runtime_includes_agent_process_tools() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "@earendil-works/pi-coding-agent@${PI_CODING_AGENT_VERSION}" in dockerfile
    assert "tmux" in dockerfile
    assert "zsh" in dockerfile
    assert "git" in dockerfile
    assert "ULTRA_FAST_RAG_DATA_ROOT=/app/data" in dockerfile
    assert "SCRAPE_PLANNER_DATA_ROOT_STRICT=1" in dockerfile
    assert "PI_CODING_AGENT_DIR=/app/data/pi-agent" in dockerfile
    assert "ln -s /opt/pi-cli/node_modules/@earendil-works/pi-coding-agent/dist/cli.js /usr/local/bin/pi" in dockerfile


def test_docker_context_keeps_pi_skill_markdown() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "*.md" in dockerignore
    assert "!.pi/skills/**/*.md" in dockerignore


def test_docker_compose_passes_agent_and_provider_runtime_env() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "container_name:" not in compose
    for expected in (
        "ULTRA_FAST_RAG_DATA_ROOT: /app/data",
        'SCRAPE_PLANNER_DATA_ROOT_STRICT: "1"',
        "PI_CODING_AGENT_DIR: /app/data/pi-agent",
        "PI_CODING_AGENT_SESSION_DIR: /app/data/pi-agent/sessions",
        "OPENROUTER_API_KEY: ${OPENROUTER_API_KEY:-}",
        "TAVILY_API_KEY: ${TAVILY_API_KEY:-}",
        "GEMINI_API_KEY: ${GEMINI_API_KEY:-}",
    ):
        assert expected in compose


def test_pi_skill_scripts_fall_back_to_container_python() -> None:
    for script in (
        ROOT / ".pi/skills/site-discovery/scripts/discover_site.sh",
        ROOT / ".pi/skills/site-url-curation/scripts/curate_urls.sh",
    ):
        text = script.read_text(encoding="utf-8")
        assert 'PYTHON="${ROOT}/.venv/bin/python"' in text
        assert 'PYTHON="${PYTHON_BIN:-python3}"' in text


def test_verify_docker_script_builds_runs_and_smokes_stack() -> None:
    script = (ROOT / "scripts/verify-docker.sh").read_text(encoding="utf-8")
    smoke = (ROOT / "scripts" / "docker-smoke.sh").read_text(encoding="utf-8")

    for expected in (
        "compose build app",
        "compose up -d redis app",
        'export WEBAPP_HOST_PORT="${WEBAPP_HOST_PORT:-18080}"',
        "curl -fsS \"${BASE_URL}/api/health\"",
        'assert p.get(\\"data_root\\") == \\"/app/data\\"',
        "command -v python3 && command -v tmux && command -v zsh && command -v git && command -v pi",
        "python3 -m py_compile src/scrape_planner/webapp/api.py src/scrape_planner/app/pi_agent.py",
        "pi --version >/dev/null",
        "./scripts/docker-smoke.sh",
        "DOCKER_VERIFY_BUILD_TIMEOUT_SECONDS",
        "DOCKER_VERIFY_ANONYMOUS_DOCKER_CONFIG",
        "DOCKER_CONFIG=\"$TEMP_DOCKER_CONFIG\"",
        "ln -s \"$HOME/.docker/cli-plugins\" \"$TEMP_DOCKER_CONFIG/cli-plugins\"",
        "Docker cannot resolve or pull a required base image",
    ):
        assert expected in script
    assert "expected at least one seeded workspace" in smoke


def test_docker_image_includes_demo_workspace_seed() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "fixtures" not in dockerignore.splitlines()
    assert (ROOT / "fixtures" / "demo-workspace" / "sites" / "codex.test.edu").is_dir()
