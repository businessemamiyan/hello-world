import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.brain import _build_context_block, _build_habits_block, _extract_json


def test_extract_json_plain():
    text = '{"reply": "سلام", "memory": []}'
    assert _extract_json(text) == {"reply": "سلام", "memory": []}


def test_extract_json_with_fences():
    text = '```json\n{"reply": "سلام", "memory": []}\n```'
    assert _extract_json(text) == {"reply": "سلام", "memory": []}


def test_extract_json_with_surrounding_text():
    text = 'یه توضیح قبلش\n{"reply": "باشه", "memory": [{"type": "note", "summary": "تست"}]}\nو بعدش'
    parsed = _extract_json(text)
    assert parsed["reply"] == "باشه"
    assert parsed["memory"][0]["type"] == "note"


def test_extract_json_invalid_returns_none():
    assert _extract_json("این اصلا JSON نیست") is None


def test_build_context_block_empty():
    assert "هیچ خاطره" in _build_context_block([])


def test_build_context_block_with_amount():
    mem = [{"type": "expense", "summary": "ناهار", "amount": 250000}]
    block = _build_context_block(mem)
    assert "ناهار" in block
    assert "250,000" in block or "250000" in block


def test_build_context_block_without_amount():
    mem = [{"type": "idea", "summary": "یه ایده", "amount": None}]
    block = _build_context_block(mem)
    assert "یه ایده" in block
    assert "تومان" not in block


def test_build_habits_block_empty():
    assert "/habit" in _build_habits_block([])


def test_build_habits_block_simple():
    habits = [{"id": 1, "good": "مطالعه", "bad": None, "streak": 3, "best_streak": 5}]
    block = _build_habits_block(habits)
    assert "مطالعه" in block
    assert "3" in block
    assert "به‌جای" not in block


def test_build_habits_block_with_replacement():
    habits = [{"id": 2, "good": "نفس عمیق", "bad": "سیگار", "streak": 0, "best_streak": 2}]
    block = _build_habits_block(habits)
    assert "به‌جای سیگار" in block
