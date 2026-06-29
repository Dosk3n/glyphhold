from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_has_runtime_healthcheck() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()

    assert "HEALTHCHECK" in dockerfile
    assert "127.0.0.1:5995/api/v1/health" in dockerfile


def test_compose_example_uses_published_image_and_healthcheck() -> None:
    compose = (ROOT / "docker-compose.example.yml").read_text()

    assert "ghcr.io/dosk3n/glyphhold:0.2.0-beta" in compose
    assert "ghcr.io/Dosk3n" not in compose
    assert "healthcheck:" in compose
    assert "127.0.0.1:5995/api/v1/health" in compose
