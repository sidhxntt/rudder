"""Tests for services/detect.py.

Real temp directories throughout — the module's whole job is reading a working
tree off disk, so mocking the filesystem would test nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rudder_cp.services.detect import (
    TEMPLATE_DIR,
    DetectionResult,
    detect,
    render_dockerfile,
)


def write(repo: Path, relative: str, content: str = "") -> Path:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def node_repo(repo: Path, package_json: dict[str, object] | None = None) -> Path:
    write(repo, "package.json", json.dumps(package_json or {"name": "api"}))
    return repo


# --- detection ---------------------------------------------------------------


def test_detects_node(tmp_path: Path) -> None:
    result = detect(node_repo(tmp_path))

    assert result.language == "node"
    assert result.has_dockerfile is False
    assert result.is_unknown is False
    assert result.node is not None
    assert result.python is None and result.go is None


def test_detects_python_from_requirements(tmp_path: Path) -> None:
    write(tmp_path, "requirements.txt", "fastapi\n")

    result = detect(tmp_path)

    assert result.language == "python"
    assert result.python is not None
    assert result.python.toolchain == "pip"


def test_detects_python_from_pyproject(tmp_path: Path) -> None:
    write(tmp_path, "pyproject.toml", '[project]\nname = "api"\nrequires-python = ">=3.11"\n')

    result = detect(tmp_path)

    assert result.language == "python"
    assert result.python is not None
    assert result.python.python_version == "3.11"


def test_detects_go(tmp_path: Path) -> None:
    write(tmp_path, "go.mod", "module github.com/me/shop-api\n\ngo 1.23\n")

    result = detect(tmp_path)

    assert result.language == "go"
    assert result.go is not None
    assert result.go.module == "github.com/me/shop-api"
    assert result.go.go_version == "1.23"
    assert result.go.binary_name == "shop-api"


def test_go_module_major_version_suffix_is_stripped(tmp_path: Path) -> None:
    write(tmp_path, "go.mod", "module github.com/me/shop-api/v2\n")

    result = detect(tmp_path)

    assert result.go is not None
    assert result.go.binary_name == "shop-api"
    assert result.go.go_version == "1.22"  # no directive -> default


def test_dockerfile_short_circuits_detection(tmp_path: Path) -> None:
    node_repo(tmp_path)
    write(tmp_path, "Dockerfile", "FROM node:20\n")

    result = detect(tmp_path)

    assert result.has_dockerfile is True
    assert result.dockerfile_path == "Dockerfile"
    assert result.language is None
    assert result.node is None
    assert result.is_unknown is False


def test_caller_supplied_dockerfile_path(tmp_path: Path) -> None:
    node_repo(tmp_path)
    write(tmp_path, "docker/prod.Dockerfile", "FROM node:20\n")

    result = detect(tmp_path, dockerfile_path="docker/prod.Dockerfile")

    assert result.has_dockerfile is True
    assert result.dockerfile_path == "docker/prod.Dockerfile"
    assert result.language is None


def test_missing_caller_supplied_dockerfile_path_does_not_fall_back(tmp_path: Path) -> None:
    node_repo(tmp_path)

    result = detect(tmp_path, dockerfile_path="docker/prod.Dockerfile")

    assert result.is_unknown is True
    assert result.has_dockerfile is False
    assert "docker/prod.Dockerfile" in result.reason


def test_dockerfile_path_outside_the_repo_is_rejected(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    write(tmp_path, "Dockerfile", "FROM scratch\n")

    result = detect(repo, dockerfile_path="../Dockerfile")

    assert result.is_unknown is True
    assert "outside the repo" in result.reason


def test_unknown_repo_returns_unknown_outcome(tmp_path: Path) -> None:
    write(tmp_path, "README.md", "# nothing to see here\n")

    result = detect(tmp_path)

    assert result.is_unknown is True
    assert result.language is None
    assert result.has_dockerfile is False
    assert result.dockerfile_path is None
    assert "package.json" in result.reason  # readable enough to show the user


def test_detection_order_prefers_node_over_python(tmp_path: Path) -> None:
    node_repo(tmp_path)
    write(tmp_path, "requirements.txt", "fastapi\n")

    assert detect(tmp_path).language == "node"


def test_malformed_package_json_still_detects_node(tmp_path: Path) -> None:
    write(tmp_path, "package.json", "{ this is not json")

    result = detect(tmp_path)

    assert result.language == "node"
    assert result.node is not None
    assert result.node.has_build_script is False
    assert result.node.start_script is None


# --- node facts --------------------------------------------------------------


@pytest.mark.parametrize(
    ("lockfile", "expected"),
    [
        ("package-lock.json", "npm"),
        ("yarn.lock", "yarn"),
        ("pnpm-lock.yaml", "pnpm"),
    ],
)
def test_package_manager_from_lockfile(tmp_path: Path, lockfile: str, expected: str) -> None:
    node_repo(tmp_path)
    write(tmp_path, lockfile, "")

    result = detect(tmp_path)

    assert result.node is not None
    assert result.node.package_manager == expected
    assert result.node.lockfile == lockfile


def test_package_manager_defaults_to_npm_without_a_lockfile(tmp_path: Path) -> None:
    result = detect(node_repo(tmp_path))

    assert result.node is not None
    assert result.node.package_manager == "npm"
    assert result.node.lockfile is None


def test_pnpm_wins_over_a_stale_npm_lockfile(tmp_path: Path) -> None:
    node_repo(tmp_path)
    write(tmp_path, "package-lock.json", "")
    write(tmp_path, "pnpm-lock.yaml", "")

    result = detect(tmp_path)

    assert result.node is not None
    assert result.node.package_manager == "pnpm"


def test_node_scripts_and_engines(tmp_path: Path) -> None:
    node_repo(
        tmp_path,
        {
            "name": "api",
            "scripts": {"build": "tsc -p .", "start": "node dist/index.js"},
            "engines": {"node": "^22.3.0"},
        },
    )

    result = detect(tmp_path)

    assert result.node is not None
    assert result.node.has_build_script is True
    assert result.node.start_script == "node dist/index.js"
    assert result.node.engines_node == "^22.3.0"
    assert result.node.node_version == "22"


def test_node_version_defaults_when_engines_absent(tmp_path: Path) -> None:
    result = detect(node_repo(tmp_path))

    assert result.node is not None
    assert result.node.engines_node is None
    assert result.node.node_version == "20"


# --- python facts ------------------------------------------------------------


def test_python_toolchain_poetry(tmp_path: Path) -> None:
    write(tmp_path, "pyproject.toml", '[tool.poetry]\nname = "api"\n')
    write(tmp_path, "poetry.lock", "")

    result = detect(tmp_path)

    assert result.python is not None
    assert result.python.toolchain == "poetry"


def test_python_toolchain_uv(tmp_path: Path) -> None:
    write(tmp_path, "pyproject.toml", '[project]\nname = "api"\n')
    write(tmp_path, "uv.lock", "")

    result = detect(tmp_path)

    assert result.python is not None
    assert result.python.toolchain == "uv"


def test_python_toolchain_pip(tmp_path: Path) -> None:
    write(tmp_path, "requirements.txt", "flask\n")

    result = detect(tmp_path)

    assert result.python is not None
    assert result.python.toolchain == "pip"


def test_python_version_from_poetry_dependency(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pyproject.toml",
        '[tool.poetry]\nname = "api"\n\n[tool.poetry.dependencies]\npython = "^3.13"\n',
    )

    result = detect(tmp_path)

    assert result.python is not None
    assert result.python.python_version == "3.13"


def test_asgi_entrypoint_detected(tmp_path: Path) -> None:
    write(tmp_path, "requirements.txt", "fastapi\nuvicorn\n")
    write(tmp_path, "app/main.py", "from fastapi import FastAPI\n\napp = FastAPI()\n")

    result = detect(tmp_path)

    assert result.python is not None
    assert result.python.is_asgi is True
    assert result.python.asgi_target == "app.main:app"


def test_non_asgi_python_falls_back_to_a_script_entrypoint(tmp_path: Path) -> None:
    write(tmp_path, "requirements.txt", "requests\n")
    write(tmp_path, "main.py", "def run():\n    pass\n")

    result = detect(tmp_path)

    assert result.python is not None
    assert result.python.is_asgi is False
    assert result.python.asgi_target is None
    assert result.python.entrypoint == "main.py"


def test_django_asgi_module_detected(tmp_path: Path) -> None:
    write(tmp_path, "requirements.txt", "django\n")
    write(
        tmp_path,
        "asgi.py",
        "from django.core.asgi import get_asgi_application\n\n"
        "application = get_asgi_application()\n",
    )

    result = detect(tmp_path)

    assert result.python is not None
    assert result.python.asgi_target == "asgi:application"


# --- rendering ---------------------------------------------------------------


def assert_looks_like_a_dockerfile(text: str) -> None:
    assert text.strip(), "template rendered empty"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    froms = [line for line in lines if line.startswith("FROM ")]
    assert len(froms) >= 2, "template is not multi-stage"
    assert any(line.startswith("USER ") for line in lines), "no non-root USER"
    assert any(line.startswith("ARG PORT") for line in lines), "no PORT build arg"
    assert any(line.startswith("CMD ") for line in lines), "no CMD"
    assert "{{" not in text and "{%" not in text, "unrendered Jinja left in output"


def test_templates_are_checked_in() -> None:
    for name in ("node", "python", "go"):
        assert (TEMPLATE_DIR / f"{name}.Dockerfile.j2").is_file()


def test_render_node(tmp_path: Path) -> None:
    node_repo(
        tmp_path,
        {"scripts": {"build": "tsc", "start": "node dist/index.js"}},
    )
    write(tmp_path, "pnpm-lock.yaml", "")

    text = render_dockerfile(detect(tmp_path), container_port=3000)

    assert_looks_like_a_dockerfile(text)
    assert "FROM node:${NODE_VERSION}-alpine AS builder" in text
    assert "pnpm install --frozen-lockfile" in text
    assert "pnpm run build" in text
    assert 'CMD ["pnpm", "run", "start"]' in text
    assert "ARG PORT=3000" in text


def test_render_node_without_a_lockfile_uses_npm_install(tmp_path: Path) -> None:
    text = render_dockerfile(detect(node_repo(tmp_path)), container_port=3000)

    assert "RUN npm install" in text
    assert "npm ci" not in text
    assert 'CMD ["node", "."]' in text


def test_render_node_with_lockfile_uses_npm_ci(tmp_path: Path) -> None:
    node_repo(tmp_path)
    write(tmp_path, "package-lock.json", "")

    text = render_dockerfile(detect(tmp_path), container_port=3000)

    assert "RUN npm ci" in text


def test_render_python_asgi(tmp_path: Path) -> None:
    write(tmp_path, "requirements.txt", "fastapi\nuvicorn\n")
    write(tmp_path, "main.py", "from fastapi import FastAPI\n\napp = FastAPI()\n")

    text = render_dockerfile(detect(tmp_path), container_port=8000)

    assert_looks_like_a_dockerfile(text)
    assert "uvicorn main:app --host 0.0.0.0 --port ${PORT}" in text
    assert "ARG PORT=8000" in text


def test_render_python_poetry(tmp_path: Path) -> None:
    write(tmp_path, "pyproject.toml", '[tool.poetry]\nname = "api"\n')
    write(tmp_path, "poetry.lock", "")

    text = render_dockerfile(detect(tmp_path), container_port=8000)

    assert_looks_like_a_dockerfile(text)
    assert "poetry export" in text
    assert "uv export" not in text


def test_render_go(tmp_path: Path) -> None:
    write(tmp_path, "go.mod", "module github.com/me/shop-api\n\ngo 1.23\n")

    text = render_dockerfile(detect(tmp_path), container_port=8080)

    assert_looks_like_a_dockerfile(text)
    assert "ARG GO_VERSION=1.23" in text
    assert "-o /out/shop-api ." in text
    assert 'CMD ["/usr/local/bin/shop-api"]' in text


def test_start_command_overrides_every_default(tmp_path: Path) -> None:
    node_repo(tmp_path, {"scripts": {"start": "node dist/index.js"}})

    text = render_dockerfile(
        detect(tmp_path),
        container_port=3000,
        start_command="node dist/server.js --cluster",
    )

    assert 'CMD ["sh", "-c", "exec node dist/server.js --cluster"]' in text
    assert 'CMD ["npm", "run", "start"]' not in text


def test_start_command_with_shell_metacharacters_is_escaped(tmp_path: Path) -> None:
    write(tmp_path, "go.mod", "module example.com/api\n")

    text = render_dockerfile(
        detect(tmp_path),
        container_port=8080,
        start_command='api --flag="a b" && echo 1>&2',
    )

    # Quotes survive as JSON escapes; < and > are not mangled into <.
    assert r"\"a b\"" in text
    assert "1>&2" in text
    assert "u003" not in text


def test_render_rejects_an_unknown_repo(tmp_path: Path) -> None:
    result = detect(tmp_path)

    assert result.is_unknown is True
    with pytest.raises(ValueError, match="nothing to render"):
        render_dockerfile(result, container_port=8080)


def test_render_rejects_a_repo_that_ships_its_own_dockerfile(tmp_path: Path) -> None:
    node_repo(tmp_path)
    write(tmp_path, "Dockerfile", "FROM node:20\n")

    with pytest.raises(ValueError, match="nothing to render"):
        render_dockerfile(detect(tmp_path), container_port=3000)


def test_result_is_a_pydantic_model_and_round_trips(tmp_path: Path) -> None:
    result = detect(node_repo(tmp_path))

    assert DetectionResult.model_validate(result.model_dump()) == result
