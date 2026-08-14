"""MAX_TOKENS 到達で本文が途切れた場合の再試行・切り詰め処理のテスト。

再現した実事象: thinking トークンが max_output_tokens を消費し尽くし、
パーソナライズ文が「…離職中の現在のペース」のような文の途中で
切れたままスカウトに挿入されていた。

対策は3段構え:
1. _build_generation_config が思考予算を本文枠に上乗せ（別テスト）
2. finish_reason=MAX_TOKENS を検知したら枠を倍にして1回再試行
3. 再試行でも切れたら最後の完結文まで切り詰める（断片を出荷しない）
"""
from __future__ import annotations

import sys
import types

import pytest

from pipeline import ai_generator


# ---------------------------------------------------------------------------
# Fake Gemini (genai SDK) plumbing
# ---------------------------------------------------------------------------


class _FakeFinishReason:
    def __init__(self, name: str):
        self.name = name


class _FakePart:
    def __init__(self, text: str):
        self.text = text


class _FakeContent:
    def __init__(self, text: str):
        self.parts = [_FakePart(text)]


class _FakeCandidate:
    def __init__(self, text: str, finish: str):
        self.content = _FakeContent(text)
        self.finish_reason = _FakeFinishReason(finish)
        self.safety_ratings = []


class _FakeResponse:
    def __init__(self, text: str, finish: str = "STOP"):
        self.candidates = [_FakeCandidate(text, finish)]
        self._text = text
        self.usage_metadata = None

    @property
    def text(self):
        return self._text


class _FakeModel:
    """generate_content が事前に積んだレスポンスを順に返すフェイク。"""

    queue: list[_FakeResponse] = []
    calls: list[dict] = []

    def __init__(self, model_name=None, system_instruction=None):
        self.model_name = model_name

    def generate_content(self, user_prompt, generation_config=None, **kwargs):
        _FakeModel.calls.append({
            "model": self.model_name,
            "generation_config": dict(generation_config or {}),
        })
        if not _FakeModel.queue:
            raise AssertionError("fake response queue is empty")
        return _FakeModel.queue.pop(0)


def _install_fake_genai(monkeypatch):
    """sys.modules に google.generativeai のフェイクを差し込む。"""
    fake = types.ModuleType("google.generativeai")
    fake.GenerativeModel = _FakeModel

    class _HarmCategory:
        HARM_CATEGORY_HARASSMENT = "h1"
        HARM_CATEGORY_HATE_SPEECH = "h2"
        HARM_CATEGORY_SEXUALLY_EXPLICIT = "h3"
        HARM_CATEGORY_DANGEROUS_CONTENT = "h4"

    class _HarmBlockThreshold:
        BLOCK_NONE = "none"

    fake.types = types.SimpleNamespace(
        HarmCategory=_HarmCategory, HarmBlockThreshold=_HarmBlockThreshold,
    )

    import google
    monkeypatch.setitem(sys.modules, "google.generativeai", fake)
    monkeypatch.setattr(google, "generativeai", fake, raising=False)


@pytest.fixture()
def fake_genai(monkeypatch):
    _install_fake_genai(monkeypatch)
    monkeypatch.setattr(ai_generator, "MOCK_AI", False)
    monkeypatch.setattr(ai_generator, "_initialized", True)
    monkeypatch.setattr(ai_generator, "_use_vertex", False)
    monkeypatch.setattr(ai_generator, "GEMINI_FALLBACK_MODELS", "", raising=False)
    monkeypatch.setattr(ai_generator, "GEMINI_THINKING_BUDGET", 1000)
    ai_generator._tripped_models.clear()
    _FakeModel.queue = []
    _FakeModel.calls = []
    yield _FakeModel


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


class TestTrimToLastSentence:
    def test_complete_text_unchanged(self):
        assert ai_generator._trim_to_last_sentence("一文目。二文目です。") == "一文目。二文目です。"

    def test_trailing_fragment_dropped(self):
        text = "確かな実践力が馴染むと思います。離職中の現在のペース"
        assert ai_generator._trim_to_last_sentence(text) == "確かな実践力が馴染むと思います。"

    def test_exclamation_and_question_count_as_boundaries(self):
        assert ai_generator._trim_to_last_sentence("ぜひ！途中の文") == "ぜひ！"
        assert ai_generator._trim_to_last_sentence("いかがですか？切れた") == "いかがですか？"

    def test_no_boundary_returns_empty(self):
        assert ai_generator._trim_to_last_sentence("句点のない断片") == ""

    def test_trailing_whitespace_stripped(self):
        assert ai_generator._trim_to_last_sentence("完結します。  \n") == "完結します。"


class TestIsTruncated:
    def test_max_tokens_detected(self):
        assert ai_generator._is_truncated(_FakeResponse("t", finish="MAX_TOKENS")) is True

    def test_stop_not_truncated(self):
        assert ai_generator._is_truncated(_FakeResponse("t", finish="STOP")) is False

    def test_missing_candidates_safe(self):
        assert ai_generator._is_truncated(object()) is False


# ---------------------------------------------------------------------------
# generate_personalized_text truncation flow
# ---------------------------------------------------------------------------


COMPLETE = "経験に注目しました。当ステーションで活きると思います。"
TRUNCATED = "経験に注目しました。当ステーションで活きると思います。杉並区から通いやすく、離職中の現在のペース"


class TestTruncationRetry:
    @pytest.mark.asyncio
    async def test_no_truncation_single_call(self, fake_genai):
        fake_genai.queue = [_FakeResponse(COMPLETE, finish="STOP")]
        result = await ai_generator.generate_personalized_text("sys", "user")
        assert result.text == COMPLETE
        assert len(fake_genai.calls) == 1

    @pytest.mark.asyncio
    async def test_truncated_then_retry_succeeds(self, fake_genai):
        fake_genai.queue = [
            _FakeResponse(TRUNCATED, finish="MAX_TOKENS"),
            _FakeResponse(COMPLETE, finish="STOP"),
        ]
        result = await ai_generator.generate_personalized_text("sys", "user")
        assert result.text == COMPLETE
        assert len(fake_genai.calls) == 2
        # 再試行では本文枠が倍（2048→4096）+ 思考予算1000の上乗せ
        assert fake_genai.calls[0]["generation_config"]["max_output_tokens"] == 2048 + 1000
        assert fake_genai.calls[1]["generation_config"]["max_output_tokens"] == 4096 + 1000

    @pytest.mark.asyncio
    async def test_truncated_twice_trims_to_sentence(self, fake_genai):
        fake_genai.queue = [
            _FakeResponse(TRUNCATED, finish="MAX_TOKENS"),
            _FakeResponse(TRUNCATED, finish="MAX_TOKENS"),
        ]
        result = await ai_generator.generate_personalized_text("sys", "user")
        # 3回目は呼ばず、文末で切り詰めた本文を返す
        assert len(fake_genai.calls) == 2
        assert result.text == "経験に注目しました。当ステーションで活きると思います。"

    @pytest.mark.asyncio
    async def test_truncated_twice_without_boundary_raises(self, fake_genai):
        fake_genai.queue = [
            _FakeResponse("句点のない断片", finish="MAX_TOKENS"),
            _FakeResponse("句点のない断片", finish="MAX_TOKENS"),
        ]
        with pytest.raises(ValueError, match="途切れ"):
            await ai_generator.generate_personalized_text("sys", "user")
        assert len(fake_genai.calls) == 2

    @pytest.mark.asyncio
    async def test_retry_disabled_trims_immediately(self, fake_genai):
        fake_genai.queue = [_FakeResponse(TRUNCATED, finish="MAX_TOKENS")]
        result = await ai_generator.generate_personalized_text(
            "sys", "user", retry_on_truncation=False,
        )
        assert len(fake_genai.calls) == 1
        assert result.text.endswith("。")
