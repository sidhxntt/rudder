"""The agent runs only fixed Docker Compose lifecycle commands."""

import subprocess

from rudder_agent.docker_ops import DockerOps

from .fakes import FakeDockerClient


def _runner(commands: list[list[str]], output: str = ""):
    def run(command: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    return run


async def test_compose_up_writes_under_state_directory_and_uses_fixed_command(tmp_path) -> None:
    commands: list[list[str]] = []
    ops = DockerOps(
        FakeDockerClient(),
        compose_state_dir=str(tmp_path / "state"),
        compose_runner=_runner(commands, "Container app Started\n"),
    )

    result = await ops.compose_up("rudder-shop", "services:\n  app: {image: nginx}\n")

    manifest = tmp_path / "state" / "rudder-shop" / "compose.yaml"
    assert result.project_name == "rudder-shop"
    assert "Started" in result.log
    assert manifest.read_text() == "services:\n  app: {image: nginx}\n"
    assert commands == [
        [
            "docker",
            "compose",
            "--project-name",
            "rudder-shop",
            "--file",
            str(manifest),
            "up",
            "--detach",
            "--remove-orphans",
        ]
    ]


async def test_compose_ps_parses_only_docker_compose_json(tmp_path) -> None:
    commands: list[list[str]] = []
    ops = DockerOps(
        FakeDockerClient(),
        compose_state_dir=str(tmp_path / "state"),
        compose_runner=_runner(
            commands,
            '[{"Service":"app","ID":"abc","State":"running","Health":"healthy"}]',
        ),
    )
    await ops.compose_up("rudder-shop", "services: {}\n")

    states = await ops.compose_ps("rudder-shop")

    assert states[0].service == "app"
    assert states[0].container_id == "abc"
    assert states[0].health == "healthy"
    assert commands[-1][-3:] == ["ps", "--format", "json"]
