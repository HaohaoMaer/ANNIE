"""Tolerant parser tests for Reflector FACTS / RELATIONSHIP_NOTES."""

from __future__ import annotations

from annie.npc.reflector import _parse_list, _parse_rel_notes


def test_parse_list_json_array():
    assert _parse_list('["a", "b", "c"]') == ["a", "b", "c"]


def test_parse_list_bullets():
    raw = "- 李四昨晚在餐车\n- 匕首上有指纹\n* 另一个观察\n1. 编号项\n2) 另一种编号"
    assert _parse_list(raw) == [
        "李四昨晚在餐车",
        "匕首上有指纹",
        "另一个观察",
        "编号项",
        "另一种编号",
    ]


def test_parse_list_mixed_noise_still_captures_lines():
    # Not JSON, not strict bullets — tolerant parser keeps non-empty lines.
    raw = "李四昨晚在餐车\n  - 匕首上有指纹\nsomething"
    out = _parse_list(raw)
    assert "李四昨晚在餐车" in out
    assert "匕首上有指纹" in out
    assert "something" in out


def test_parse_list_empty():
    assert _parse_list("") == []
    assert _parse_list("   \n   ") == []


def test_parse_rel_notes_json_dicts():
    raw = '[{"person": "Bob", "observation": "suspicious"}]'
    out = _parse_rel_notes(raw)
    assert out == [{"person": "Bob", "observation": "suspicious"}]


def test_parse_rel_notes_bullet_fallback_has_empty_person():
    raw = "- Bob seems suspicious\n- Alice is friendly"
    out = _parse_rel_notes(raw)
    assert all(item["person"] == "" for item in out)
    assert {item["observation"] for item in out} == {"Bob seems suspicious", "Alice is friendly"}


def test_parse_rel_notes_empty():
    assert _parse_rel_notes("") == []
