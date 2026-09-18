"""Tests for repository release metadata and public entry-point contracts."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]

README_CASES = {
    "README.md": {
        "other_language": "[简体中文](README.zh-CN.md)",
        "headings": [
            "Overview",
            "Install",
            "Quick start",
            "Architecture",
            "Usage flow",
            "Context VM",
            "Durable plan workflow",
            "MCP server",
            "Generated artifacts",
            "Development",
            "Known limitations",
            "Roadmap",
            "License",
        ],
        "scope_precedence": "`batch > plan > session > global`",
        "lease": "short-lived lease",
        "source_install": "git clone https://github.com/1084669403/codeatlas-memory",
    },
    "README.zh-CN.md": {
        "other_language": "[English](README.md)",
        "headings": [
            "项目概览",
            "安装",
            "快速开始",
            "架构",
            "使用流程",
            "上下文虚拟内存",
            "持久计划工作流",
            "MCP 服务器",
            "生成产物",
            "开发",
            "已知限制",
            "路线图",
            "许可证",
        ],
        "scope_precedence": "`batch > plan > session > global`",
        "lease": "短租约",
        "source_install": "git clone https://github.com/1084669403/codeatlas-memory",
    },
}


def _relative_markdown_targets(text: str) -> list[str]:
    targets: list[str] = []
    for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", text):
        target = match.group(1).split("#", 1)[0]
        if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
            continue
        targets.append(target)
    return targets


def test_readme_navigation_and_release_sections() -> None:
    for filename, case in README_CASES.items():
        path = ROOT / filename
        assert path.is_file(), f"Missing public entry: {filename}"
        text = path.read_text(encoding="utf-8")

        assert case["other_language"] in text
        for heading in case["headings"]:
            assert f"## {heading}" in text, f"{filename} is missing heading: {heading}"

        assert text.count("```mermaid") >= 2, f"{filename} needs architecture and flow diagrams"
        assert "```mermaid\nflowchart" in text
        assert case["source_install"] in text
        assert "uv sync --extra mcp" in text
        assert "uv run codeatlas --help" in text
        assert case["scope_precedence"] in text
        assert case["lease"] in text
        assert "TaskController" in text
        assert "mark_done" in text

        for target in _relative_markdown_targets(text):
            assert (ROOT / target).is_file(), f"{filename} has broken relative link: {target}"

        for forbidden in (
            "order_total",
            "54 tests",
            "10 tools",
            "Available tools (10)",
            'pip install "codeatlas-memory',
            "uvx --from",
            "last-write-wins",
            "semantic search (local embeddings)",
        ):
            assert forbidden not in text, f"{filename} contains stale text: {forbidden}"


def test_repository_metadata_and_community_files() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]

    assert project["name"] == "codeatlas-memory"
    assert project["requires-python"] == ">=3.11"
    assert project["readme"] == "README.md"
    assert project["license"] == "MIT"
    assert project["urls"] == {
        "Homepage": "https://github.com/1084669403/codeatlas-memory",
        "Repository": "https://github.com/1084669403/codeatlas-memory",
        "Issues": "https://github.com/1084669403/codeatlas-memory/issues",
    }

    for filename in (
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
        "SECURITY.md",
        ".github/ISSUE_TEMPLATE/config.yml",
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml",
        ".github/PULL_REQUEST_TEMPLATE.md",
    ):
        path = ROOT / filename
        assert path.is_file(), f"Missing community file: {filename}"
        assert path.read_text(encoding="utf-8").strip(), f"Empty community file: {filename}"

    config = yaml.safe_load(
        (ROOT / ".github/ISSUE_TEMPLATE/config.yml").read_text(encoding="utf-8")
    )
    assert config["blank_issues_enabled"] is False

    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for required in (
        "workflow_dispatch:",
        "permissions:",
        "contents: read",
        "concurrency:",
        "cancel-in-progress: true",
        "timeout-minutes:",
    ):
        assert required in workflow, f"CI workflow is missing: {required}"
    assert "pypi" not in workflow.lower()
