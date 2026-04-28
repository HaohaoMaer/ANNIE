"""Unit tests for skills/registry.py load_dir.

Covers: empty dir, nonexistent dir, valid skill, missing prompt.md,
non-skill subdir, deferred extra_tools validation, multiple skills.
"""
from __future__ import annotations

import pytest

from annie.npc.runtime.skill_runtime import SkillRuntime
from annie.npc.skills.registry import load_dir
from annie.npc.tools.tool_registry import ToolRegistry


def test_empty_directory(tmp_path):
    registry = load_dir(tmp_path)
    assert registry.list_skills() == []


def test_nonexistent_directory(tmp_path):
    registry = load_dir(tmp_path / "no_such_dir")
    assert registry.list_skills() == []


def test_loads_valid_skill(tmp_path):
    d = tmp_path / "myskill"
    d.mkdir()
    (d / "skill.yaml").write_text(
        "name: myskill\none_line: Does something\nextra_tools: []\n"
    )
    (d / "prompt.md").write_text("Do something great.")
    registry = load_dir(tmp_path)
    skill = registry.get("myskill")
    assert skill is not None
    assert skill.name == "myskill"
    assert skill.one_line == "Does something"
    assert "Do something great." in skill.prompt
    assert skill.extra_tools == []


def test_missing_prompt_md_raises(tmp_path):
    d = tmp_path / "broken"
    d.mkdir()
    (d / "skill.yaml").write_text("name: broken\none_line: broken\n")
    with pytest.raises(FileNotFoundError, match="prompt.md"):
        load_dir(tmp_path)


def test_directory_without_yaml_is_skipped(tmp_path):
    """A subdir with only prompt.md (no skill.yaml) is silently ignored."""
    d = tmp_path / "not_a_skill"
    d.mkdir()
    (d / "prompt.md").write_text("Some text")
    registry = load_dir(tmp_path)
    assert registry.list_skills() == []


def test_load_succeeds_with_unresolvable_extra_tools(tmp_path):
    """load_dir() does not resolve extra_tools — that is deferred to activate()."""
    d = tmp_path / "heavy"
    d.mkdir()
    (d / "skill.yaml").write_text(
        "name: heavy\none_line: heavy\nextra_tools:\n  - ghost_tool\n"
    )
    (d / "prompt.md").write_text("Heavy prompt.")
    registry = load_dir(tmp_path)
    skill = registry.get("heavy")
    assert skill is not None
    assert "ghost_tool" in skill.extra_tools


def test_extra_tools_unregistered_raises_on_activate(tmp_path):
    """SkillRuntime.activate() raises ValueError when extra_tools id not in registry."""
    d = tmp_path / "heavy"
    d.mkdir()
    (d / "skill.yaml").write_text(
        "name: heavy\none_line: heavy\nextra_tools:\n  - ghost_tool\n"
    )
    (d / "prompt.md").write_text("Heavy prompt.")
    registry = load_dir(tmp_path)
    runtime = SkillRuntime(registry)
    tool_registry = ToolRegistry()
    with pytest.raises(ValueError, match="ghost_tool"):
        runtime.activate("heavy", {}, [], tool_registry)


def test_multiple_skills_loaded(tmp_path):
    for name, line in [("alpha", "Alpha skill"), ("beta", "Beta skill")]:
        d = tmp_path / name
        d.mkdir()
        (d / "skill.yaml").write_text(f"name: {name}\none_line: {line}\n")
        (d / "prompt.md").write_text(f"You are in {name} mode.")
    registry = load_dir(tmp_path)
    assert registry.get("alpha") is not None
    assert registry.get("beta") is not None
    assert len(registry.list_skills()) == 2


def test_triggers_loaded_as_metadata(tmp_path):
    d = tmp_path / "reasoning"
    d.mkdir()
    (d / "skill.yaml").write_text(
        "name: reasoning\none_line: reason\ntriggers:\n  - 推理\n  - 分析\n"
    )
    (d / "prompt.md").write_text("Reason carefully.")
    registry = load_dir(tmp_path)
    skill = registry.get("reasoning")
    assert skill is not None
    assert "推理" in skill.triggers
    assert "分析" in skill.triggers
