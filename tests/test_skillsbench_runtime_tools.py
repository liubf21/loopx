from loopx.benchmark_adapters import skillsbench_dockerfile_runtime
from scripts.skillsbench_automation_loop import (
    DOCKER_CODEX_ACP_RUNTIME_TOOLS_BEGIN,
    patch_dockerfile_codex_acp_runtime_tools,
)


def test_runtime_tools_retries_apt_with_public_mirrors(tmp_path) -> None:
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM ubuntu:24.04\n", encoding="utf-8")

    assert patch_dockerfile_codex_acp_runtime_tools(dockerfile) is True

    staged_text = dockerfile.read_text(encoding="utf-8")
    assert DOCKER_CODEX_ACP_RUNTIME_TOOLS_BEGIN in staged_text
    assert "if ! apt-get update -qq; then" in staged_text
    assert (
        skillsbench_dockerfile_runtime.DEFAULT_UBUNTU_APT_MIRROR_BASE
        in staged_text
    )
    assert (
        skillsbench_dockerfile_runtime.DEFAULT_DEBIAN_APT_MIRROR_BASE
        in staged_text
    )
    assert (
        skillsbench_dockerfile_runtime.DEFAULT_DEBIAN_SECURITY_MIRROR_BASE
        in staged_text
    )
    assert staged_text.count("apt-get update -qq") == 2
    assert (
        staged_text.index("if ! apt-get update -qq; then")
        < staged_text.index("apt-get install -y -qq")
    )
    assert patch_dockerfile_codex_acp_runtime_tools(dockerfile) is False
    assert dockerfile.read_text(encoding="utf-8") == staged_text
