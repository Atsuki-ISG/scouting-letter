"""_strip_thinking のテスト — 2026-04-14 に報告された Draft 漏洩ケースをカバー。"""
from pipeline.ai_generator import _strip_thinking


def test_removes_draft_with_japanese_body():
    """Draft N: で始まるパラグラフ（日本語本文でも）除去"""
    leaked = (
        "Draft 1: 保育補助として3年にわたりお子様一人ひとりに寄り添ってこられた経験や、"
        "現在の生活支援員としての歩みに注目しました。 (119 characters) - A bit long.\n\n"
        "Draft 2: 3年にわたる保育補助や現在の生活支援員として、一人ひとりに寄り添い援助されてきた"
        "経験に注目しました。 (116 characters)\n\n"
        '"3年にわたる保育補助や現在の生活支援員として、一人ひとりに寄り添い援助されてきた'
        '経験に注目しました。相手の状況を汲み取る傾聴力や支援の姿勢は、入居を検討される'
        'お客様の不安を解消する当施設の相談業務で大きく活かせると考えております。"'
    )
    result = _strip_thinking(leaked)
    assert "Draft" not in result
    assert "characters" not in result
    assert result.startswith("3年にわたる保育補助")
    assert result.endswith("と考えております。")


def test_removes_character_counting_block():
    """Characters: で始まる文字数カウントブロック除去"""
    leaked = (
        "これは本文です。\n\n"
        "Characters:\n"
        "    3(1)年(2)に(3)わ(4)た(5)る(6)保(7)育(8)補(9)助(10)や(11)現(12)在(13)の(14)\n"
        "    Total: 115 characters. Perfect."
    )
    result = _strip_thinking(leaked)
    assert "Characters" not in result
    assert "Total" not in result
    assert "(1)" not in result
    assert result == "これは本文です。"


def test_removes_meta_commentary():
    """Wait, / One more check: / My draft などのメタコメント除去"""
    leaked = (
        "これが最終版です。\n\n"
        "Wait, the prompt mentions the candidate's self-PR:\n\n"
        "My draft incorporates this: 一人ひとりに寄り添い。\n\n"
        "One more check: 書き出し: テンプレート冒頭に"
    )
    result = _strip_thinking(leaked)
    assert "Wait" not in result
    assert "My draft" not in result
    assert "One more check" not in result
    assert "これが最終版です。" in result


def test_strips_outer_quotes():
    """最終出力が \"...\" に囲まれていたら剥がす"""
    assert _strip_thinking('"本文です。"') == "本文です。"
    assert _strip_thinking("「本文です。」") == "本文です。"


def test_preserves_clean_output():
    """クリーンな日本語本文はそのまま通す"""
    clean = (
        "3年にわたる保育補助や現在の生活支援員として、一人ひとりに寄り添い援助されてきた"
        "経験に注目しました。相手の状況を汲み取る傾聴力は当施設で活かせます。"
    )
    assert _strip_thinking(clean) == clean


def test_removes_ascii_heavy_english_reasoning():
    """英語の推論ブロック除去（既存挙動）"""
    leaked = (
        "Let me think about this carefully. The candidate has 3 years of experience in childcare "
        "and is currently working as a life support worker.\n\n"
        "本文: 3年にわたる保育補助の経験に注目しました。"
    )
    result = _strip_thinking(leaked)
    assert "Let me" not in result
    assert "candidate" not in result
    assert "本文: 3年にわたる保育補助の経験に注目しました。" == result


def test_counted_chars_pattern_heavy():
    """X(N)パターンが大量に並ぶ段落を除去"""
    leaked = "あ(1)い(2)う(3)え(4)お(5)か(6)き(7)く(8)け(9)こ(10)さ(11)し(12)"
    assert _strip_thinking(leaked) == ""
