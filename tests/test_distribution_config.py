from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_has_runtime_healthcheck() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()

    assert "HEALTHCHECK" in dockerfile
    assert "127.0.0.1:5995/api/v1/health" in dockerfile


def test_compose_example_uses_versioned_image_and_healthcheck() -> None:
    compose = (ROOT / "docker-compose.example.yml").read_text()

    assert "image: ghcr.io/dosk3n/glyphhold:2.0.4" in compose
    assert "127.0.0.1:5995:5995" in compose
    assert "glyphhold2-data:/data" in compose
    assert "container_name: glyphhold" not in compose
    assert "healthcheck:" in compose
    assert "127.0.0.1:5995/api/v1/health" in compose
