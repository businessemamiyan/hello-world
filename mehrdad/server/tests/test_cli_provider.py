import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.brain import Brain, CLIError, _cli_prompt, parse_cli_output, run_claude_cli
from app.config import Config


def test_parse_cli_output_object_and_event_array():
    assert parse_cli_output(json.dumps({"type": "result", "is_error": False, "result": "سلام"})) == "سلام"
    events = [{"type": "system"}, {"type": "assistant"}, {"type": "result", "is_error": False, "result": "ok"}]
    assert parse_cli_output(json.dumps(events)) == "ok"


@pytest.mark.parametrize("bad", ["not json", json.dumps({"is_error": True, "result": "401 invalid"}),
                                 json.dumps({"type": "result"}), json.dumps([{"type": "system"}]), "5"])
def test_parse_cli_output_errors(bad):
    with pytest.raises(CLIError):
        parse_cli_output(bad)


def test_cli_prompt_includes_history_and_last_message():
    p = _cli_prompt([{"role": "user", "content": "سلام"}, {"role": "assistant", "content": "سلام!"},
                     {"role": "user", "content": "خرجم چقدر شد؟"}])
    assert p.index("کاربر: سلام") < p.index("مهرداد: سلام!") < p.index("خرجم چقدر شد؟")
    assert "JSON" in p
    assert "گفتگوی اخیر" not in _cli_prompt([{"role": "user", "content": "x"}])


@pytest.mark.asyncio
async def test_cli_provider_prefetches_memory_and_parses_reply():
    seen = {}

    async def runner(system, prompt, model):
        seen.update(system=system, prompt=prompt, model=model)
        return '{"reply": "از CLI", "memory": [{"type": "note", "summary": "تست"}]}'

    async def search(q):
        return [{"type": "idea", "summary": "ایده قدیمی قهوه", "detail": None, "amount": None, "ts": 1.0}]

    b = Brain("", provider="cli", cli_model="sonnet", cli_runner=runner, search=search)
    reply, entries = await b.think([("user", "قبلی")], [], "درباره قهوه چی گفتم؟")
    assert reply == "از CLI" and entries[0]["summary"] == "تست"
    assert "ایده قدیمی قهوه" in seen["system"] and seen["model"] == "sonnet"
    assert "درباره قهوه چی گفتم؟" in seen["prompt"]


@pytest.mark.asyncio
async def test_cli_provider_failure_is_graceful():
    async def runner(system, prompt, model):
        raise CLIError("401")

    reply, entries = await Brain("", provider="cli", cli_runner=runner).think([], [], "سلام")
    assert "اتصال" in reply and entries == []


@pytest.mark.asyncio
async def test_run_claude_cli_missing_binary_and_fake_binary(tmp_path):
    with pytest.raises(CLIError):
        await run_claude_cli("s", "p", binary=str(tmp_path / "does-not-exist"))
    # یک «claude» ساختگی: stdin را می‌خواند و JSON استاندارد برمی‌گرداند
    fake = tmp_path / "fake_claude.py"
    fake.write_text(
        "import sys, json\nprompt = sys.stdin.buffer.read().decode('utf-8')\n"
        "assert '--tools' in sys.argv and '-p' in sys.argv\n"
        "print(json.dumps({'type': 'result', 'is_error': False, 'result': 'echo:' + prompt}))\n",
        encoding="utf-8",
    )
    wrapper = tmp_path / ("w.cmd" if os.name == "nt" else "w.sh")
    wrapper.write_text(
        (f'@"{sys.executable}" "{fake}" %*\r\n' if os.name == "nt" else f'#!/bin/sh\nexec "{sys.executable}" "{fake}" "$@"\n'),
        encoding="utf-8",
    )
    if os.name != "nt":
        wrapper.chmod(0o755)
    assert await run_claude_cli("sys", "پیام", binary=str(wrapper)) == "echo:پیام"


def test_config_provider_selection_and_problems():
    base = dict(bot_token="x", setup_code="c")
    assert Config(**base, anthropic_api_key="k").provider() == "api"
    assert Config(**base, claude_oauth_token="t").provider() == "cli"
    assert Config(**base).provider() == "cli"
    assert Config(**base).problems() == []  # cli بدون توکن: لاگین ذخیره‌شدهٔ `claude auth login` هم کافی است
    assert Config(**base, claude_oauth_token="t").problems() == []
    assert Config(**base, anthropic_api_key="k").problems() == []
    assert any("ANTHROPIC_API_KEY" in p for p in Config(**base, brain_provider="api").problems())
