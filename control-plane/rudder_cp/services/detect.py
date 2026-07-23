"""Language detection + Dockerfile generation for the build pipeline.

Phase 1 step 5. Heuristics only — no LLM, no network, no subprocess. Everything
here is plain synchronous file reading over a freshly cloned working tree, so it
stays `def`, not `async def`.

Detection order, per PHASE-1-single-host.md step 5:

    1. a Dockerfile (repo root, or the service's `dockerfile_path`) -> use it
    2. package.json                        -> node
    3. requirements.txt / pyproject.toml   -> python
    4. go.mod                              -> go
    5. nothing                             -> unknown, with a reason the caller
                                              can put straight into
                                              Deployment.error_message

We never guess. An unknown repo is a deploy failure, not a coin flip.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Literal

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel

Language = Literal["node", "python", "go"]
PackageManager = Literal["npm", "yarn", "pnpm"]
PythonToolchain = Literal["pip", "poetry", "uv"]

# control-plane/rudder_cp/services/detect.py -> control-plane/dockerfile_templates
TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "dockerfile_templates"

DEFAULT_NODE_VERSION = "20"
DEFAULT_PYTHON_VERSION = "3.12"
DEFAULT_GO_VERSION = "1.22"
DEFAULT_PYTHON_ENTRYPOINT = "main.py"
DEFAULT_GO_BINARY = "app"

# lockfile -> package manager, checked in this order (pnpm and yarn repos often
# still carry a stale package-lock.json).
_NODE_LOCKFILES: tuple[tuple[str, PackageManager], ...] = (
    ("pnpm-lock.yaml", "pnpm"),
    ("yarn.lock", "yarn"),
    ("package-lock.json", "npm"),
)

# Files we are willing to read looking for an ASGI app object.
_PYTHON_ENTRY_CANDIDATES: tuple[str, ...] = (
    "main.py",
    "app.py",
    "asgi.py",
    "server.py",
    "src/main.py",
    "src/app.py",
    "app/main.py",
    "app/asgi.py",
)

# `app = FastAPI(...)` / `application = get_asgi_application()` and friends.
_ASGI_ASSIGNMENT = re.compile(
    r"^\s*(?P<name>app|application)\s*=\s*"
    r"(?:FastAPI|Starlette|Quart|Litestar|Sanic|get_asgi_application)\s*\(",
    re.MULTILINE,
)

_VERSION_MAJOR = re.compile(r"(\d+)")
_VERSION_MAJOR_MINOR = re.compile(r"(\d+)\.(\d+)")
_GO_MODULE = re.compile(r"^\s*module\s+(?P<module>\S+)", re.MULTILINE)
_GO_DIRECTIVE = re.compile(r"^\s*go\s+(?P<version>\d+(?:\.\d+){1,2})\s*$", re.MULTILINE)
_SAFE_BINARY = re.compile(r"[^A-Za-z0-9._-]")


class NodeFacts(BaseModel):
    """What the node template needs that can only be learned by reading the repo."""

    package_manager: PackageManager
    lockfile: str | None
    has_build_script: bool
    start_script: str | None
    engines_node: str | None
    node_version: str


class PythonFacts(BaseModel):
    """Toolchain + entrypoint shape for the python template."""

    toolchain: PythonToolchain
    python_version: str
    is_asgi: bool
    asgi_target: str | None
    entrypoint: str


class GoFacts(BaseModel):
    """go.mod contents the go template needs."""

    module: str
    go_version: str
    binary_name: str


class DetectionResult(BaseModel):
    """How to build one cloned repo. The build pipeline's only input contract.

    `dockerfile_path` is repo-relative POSIX, which is what buildctl wants for
    `--opt filename=`.
    """

    language: Language | None
    has_dockerfile: bool
    dockerfile_path: str | None = None
    reason: str
    node: NodeFacts | None = None
    python: PythonFacts | None = None
    go: GoFacts | None = None

    @property
    def is_unknown(self) -> bool:
        """True when nothing matched. The caller turns this into a failed Deployment."""
        return self.language is None and not self.has_dockerfile


def detect(repo_path: Path, dockerfile_path: str | None = None) -> DetectionResult:
    """Inspect a cloned repo and decide how it gets built.

    `dockerfile_path` is `Service.dockerfile_path` — an explicit override. If it
    is set and the file is not there we fail rather than falling back to
    generation, because a wrong Dockerfile path is a config error the user needs
    to see.
    """
    repo = Path(repo_path)

    if dockerfile_path:
        return _explicit_dockerfile(repo, dockerfile_path)

    root_dockerfile = repo / "Dockerfile"
    if root_dockerfile.is_file():
        return DetectionResult(
            language=None,
            has_dockerfile=True,
            dockerfile_path="Dockerfile",
            reason="Dockerfile at the repo root — building it directly.",
        )

    if (repo / "package.json").is_file():
        return DetectionResult(
            language="node",
            has_dockerfile=False,
            reason="package.json at the repo root.",
            node=_read_node_facts(repo),
        )

    has_requirements = (repo / "requirements.txt").is_file()
    has_pyproject = (repo / "pyproject.toml").is_file()
    if has_requirements or has_pyproject:
        marker = "requirements.txt" if has_requirements else "pyproject.toml"
        return DetectionResult(
            language="python",
            has_dockerfile=False,
            reason=f"{marker} at the repo root.",
            python=_read_python_facts(repo),
        )

    if (repo / "go.mod").is_file():
        return DetectionResult(
            language="go",
            has_dockerfile=False,
            reason="go.mod at the repo root.",
            go=_read_go_facts(repo),
        )

    return DetectionResult(
        language=None,
        has_dockerfile=False,
        reason=(
            "Could not determine how to build this repo: no Dockerfile, package.json, "
            "requirements.txt, pyproject.toml, or go.mod at the repo root. "
            "Add one, or set dockerfile_path on the service."
        ),
    )


def render_dockerfile(
    result: DetectionResult,
    *,
    container_port: int,
    start_command: str | None = None,
) -> str:
    """Render the template for a detected language and return the Dockerfile text.

    `start_command` is `Service.start_command` and always wins over whatever the
    repo declares; the templates only fall back to a language default when it is
    absent.

    Raises ValueError when there is nothing to render — a repo that ships its own
    Dockerfile, or one we could not classify.
    """
    if result.language is None:
        raise ValueError(f"nothing to render: {result.reason}")

    context: dict[str, object] = {
        "port": container_port,
        "start_command": start_command,
    }

    if result.language == "node":
        if result.node is None:
            raise ValueError("node detection result is missing node facts")
        context |= {
            "package_manager": result.node.package_manager,
            "lockfile": result.node.lockfile,
            "has_build_script": result.node.has_build_script,
            "start_script": result.node.start_script,
            "node_version": result.node.node_version,
        }
    elif result.language == "python":
        if result.python is None:
            raise ValueError("python detection result is missing python facts")
        context |= {
            "toolchain": result.python.toolchain,
            "python_version": result.python.python_version,
            "asgi_target": result.python.asgi_target,
            "entrypoint": result.python.entrypoint,
        }
    else:
        if result.go is None:
            raise ValueError("go detection result is missing go facts")
        context |= {
            "go_version": result.go.go_version,
            "binary_name": result.go.binary_name,
        }

    template = _env().get_template(f"{result.language}.Dockerfile.j2")
    return template.render(**context)


# --- internals ---------------------------------------------------------------


_JINJA_ENV: Environment | None = None


def _env() -> Environment:
    """Jinja environment over the checked-in templates. Built once, reused."""
    global _JINJA_ENV
    if _JINJA_ENV is None:
        env = Environment(
            loader=FileSystemLoader(TEMPLATE_DIR),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
            autoescape=False,
        )
        # Jinja's builtin `tojson` HTML-escapes <, > and & — fine for web pages,
        # wrong for a shell command inside a Dockerfile CMD.
        env.filters["jsonstr"] = json.dumps
        _JINJA_ENV = env
    return _JINJA_ENV


def _explicit_dockerfile(repo: Path, dockerfile_path: str) -> DetectionResult:
    candidate = (repo / dockerfile_path).resolve()
    root = repo.resolve()
    if not candidate.is_relative_to(root):
        return DetectionResult(
            language=None,
            has_dockerfile=False,
            reason=f"dockerfile_path {dockerfile_path!r} points outside the repo.",
        )
    if not candidate.is_file():
        return DetectionResult(
            language=None,
            has_dockerfile=False,
            reason=(
                f"dockerfile_path {dockerfile_path!r} is set on the service but no such "
                "file exists in the repo at this commit."
            ),
        )
    return DetectionResult(
        language=None,
        has_dockerfile=True,
        dockerfile_path=candidate.relative_to(root).as_posix(),
        reason=f"Dockerfile at {dockerfile_path} — building it directly.",
    )


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _read_json(path: Path) -> dict[str, object]:
    text = _read_text(path)
    if text is None:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _read_toml(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _read_node_facts(repo: Path) -> NodeFacts:
    lockfile: str | None = None
    package_manager: PackageManager = "npm"
    for name, manager in _NODE_LOCKFILES:
        if (repo / name).is_file():
            lockfile, package_manager = name, manager
            break

    package_json = _read_json(repo / "package.json")

    scripts = package_json.get("scripts")
    scripts = scripts if isinstance(scripts, dict) else {}
    start_script = scripts.get("start")
    start_script = start_script if isinstance(start_script, str) else None

    engines = package_json.get("engines")
    engines = engines if isinstance(engines, dict) else {}
    engines_node = engines.get("node")
    engines_node = engines_node if isinstance(engines_node, str) else None

    return NodeFacts(
        package_manager=package_manager,
        lockfile=lockfile,
        has_build_script="build" in scripts,
        start_script=start_script,
        engines_node=engines_node,
        node_version=_node_major(engines_node),
    )


def _node_major(engines_node: str | None) -> str:
    """`^20.11.0`, `>=18 <21`, `20.x` -> the first major we see, else the default."""
    if not engines_node:
        return DEFAULT_NODE_VERSION
    match = _VERSION_MAJOR.search(engines_node)
    return match.group(1) if match else DEFAULT_NODE_VERSION


def _read_python_facts(repo: Path) -> PythonFacts:
    pyproject = _read_toml(repo / "pyproject.toml") if (repo / "pyproject.toml").is_file() else {}
    tool = pyproject.get("tool")
    tool = tool if isinstance(tool, dict) else {}

    if (repo / "uv.lock").is_file() or "uv" in tool:
        toolchain: PythonToolchain = "uv"
    elif (repo / "poetry.lock").is_file() or "poetry" in tool:
        toolchain = "poetry"
    else:
        toolchain = "pip"

    asgi_target = _find_asgi_target(repo)
    return PythonFacts(
        toolchain=toolchain,
        python_version=_python_version(pyproject),
        is_asgi=asgi_target is not None,
        asgi_target=asgi_target,
        entrypoint=_python_entrypoint(repo),
    )


def _python_version(pyproject: dict[str, object]) -> str:
    project = pyproject.get("project")
    if isinstance(project, dict):
        requires = project.get("requires-python")
        if isinstance(requires, str):
            match = _VERSION_MAJOR_MINOR.search(requires)
            if match:
                return f"{match.group(1)}.{match.group(2)}"

    tool = pyproject.get("tool")
    poetry = tool.get("poetry") if isinstance(tool, dict) else None
    deps = poetry.get("dependencies") if isinstance(poetry, dict) else None
    python_constraint = deps.get("python") if isinstance(deps, dict) else None
    if isinstance(python_constraint, str):
        match = _VERSION_MAJOR_MINOR.search(python_constraint)
        if match:
            return f"{match.group(1)}.{match.group(2)}"

    return DEFAULT_PYTHON_VERSION


def _find_asgi_target(repo: Path) -> str | None:
    """Return `module.path:app` if a candidate file assigns an ASGI application."""
    for relative in _PYTHON_ENTRY_CANDIDATES:
        path = repo / relative
        if not path.is_file():
            continue
        source = _read_text(path)
        if source is None:
            continue
        match = _ASGI_ASSIGNMENT.search(source)
        if match:
            module = relative[: -len(".py")].replace("/", ".")
            return f"{module}:{match.group('name')}"
    return None


def _python_entrypoint(repo: Path) -> str:
    for relative in _PYTHON_ENTRY_CANDIDATES:
        if (repo / relative).is_file():
            return relative
    return DEFAULT_PYTHON_ENTRYPOINT


def _read_go_facts(repo: Path) -> GoFacts:
    source = _read_text(repo / "go.mod") or ""

    module_match = _GO_MODULE.search(source)
    module = module_match.group("module") if module_match else ""

    version_match = _GO_DIRECTIVE.search(source)
    go_version = version_match.group("version") if version_match else DEFAULT_GO_VERSION

    return GoFacts(module=module, go_version=go_version, binary_name=_go_binary_name(module))


def _go_binary_name(module: str) -> str:
    """`github.com/me/shop-api/v2` -> `shop-api`. Falls back to `app`."""
    segments = [segment for segment in module.split("/") if segment]
    while segments and re.fullmatch(r"v\d+", segments[-1]):
        segments.pop()
    if not segments:
        return DEFAULT_GO_BINARY
    name = _SAFE_BINARY.sub("-", segments[-1]).strip("-")
    return name or DEFAULT_GO_BINARY
