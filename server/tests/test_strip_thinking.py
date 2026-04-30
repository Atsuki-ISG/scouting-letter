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


# 2026-04-23 追加: 本番で観測された新しい漏洩パターン
# （chigasaki-tokushukai D-CHI-04 / ichigo D-ICH-08 / ichigo D-ICH-03）


def test_removes_drafting_prefix_with_japanese_body_same_paragraph():
    """`Drafting:\\n本文...` のように単一段落内の先頭行メタを剥がす"""
    leaked = (
        "Drafting:\n"
        "有料老人ホームでの5年間に加え、訪問看護でも3年の経験を積まれている点に注目しました。"
        "施設と在宅の両面を知る実践力は、併設施設との連携や幅広い疾患への対応が求められる"
        "当ステーションにおいて、非常に心強い存在になると期待しています。"
        "一度見学にいらっしゃいませんか。"
    )
    result = _strip_thinking(leaked)
    assert "Drafting" not in result
    assert result.startswith("有料老人ホームでの5年間")
    assert result.endswith("一度見学にいらっしゃいませんか。")


def test_removes_its_n_characters_prefix():
    """`It's 126 characters.\\n本文...` の先頭メタ行を剥がす"""
    leaked = (
        "It's 126 characters.\n"
        "8年の看護師経験に加え、ケアマネジャーの資格もお持ちの点に注目しました。"
        "地域包括ケア病棟での6年にわたるご経験は、多職種連携を重視する当院の在宅復帰支援"
        "において大きな力になると確信しています。"
        "その確かな実践力を、ぜひ当院で発揮してください。"
    )
    result = _strip_thinking(leaked)
    assert "characters" not in result.lower()
    assert result.startswith("8年の看護師経験")


def test_removes_trailing_japanese_char_count_meta():
    """本文末尾に `118文字。これが一番事実に基づいている。` のような自己検証メタが付く場合"""
    leaked = (
        "訪問看護で5年、病棟で3年の経験を積まれている確かな実践力に注目しました。"
        "豊富な知見を活かし、看取りを含む幅広いケアにおいて、現場を支えていただけることを"
        "期待しています。ぜひ一度お話しできましたら嬉しく思います。\n"
        "    118文字。これが一番事実に基づいている。"
    )
    result = _strip_thinking(leaked)
    assert "118文字" not in result
    assert "事実に基づいている" not in result
    assert result.endswith("ぜひ一度お話しできましたら嬉しく思います。")


def test_removes_alternative_draft_after_kept_content():
    """本文の後ろに「訪問」のような別ドラフト断片が続くケースを除去"""
    leaked = (
        "訪問看護で5年、病棟で3年の経験を積まれている確かな実践力に注目しました。"
        "ぜひ一度お話しできましたら嬉しく思います。\n"
        "    118文字。これが一番事実に基づいている。\n\n"
        "「訪問看護と病棟での経験は、当ステーションで活きる"
    )
    result = _strip_thinking(leaked)
    assert "118文字" not in result
    assert "これが一番" not in result
    # 2つ目の「訪問〜」は途切れたドラフトなので落ちるべき
    assert result.endswith("ぜひ一度お話しできましたら嬉しく思います。")


def test_removes_dangling_trailing_quote():
    """本文末尾に閉じ鍵括弧だけ残っているケースを剥がす"""
    leaked = "ぜひ一度お話しできましたら嬉しく思います。」"
    result = _strip_thinking(leaked)
    assert result == "ぜひ一度お話しできましたら嬉しく思います。"


def test_removes_chars_abbreviation_annotations():
    """`(39 chars)` のような略形でも文字数アノテーションを検出して除去する。

    sato-hospital で観測されたケース。`characters?` ではなく `chars` の略形で
    出力されると、従来の正規表現が一致せず、Character Count Check ブロック
    内の本文重複が漏洩していた。
    """
    leaked = (
        "Draft 2 (Applying Rules & Specifics):\n"
        "        整形外科での臨床に加え、副主任として管理業務に携わられた8年の歩みに注目しました。"
        "病院での多角的なリハビリ経験や運営視点は、整形外科から在宅復帰支援まで幅広く手掛ける"
        "当院において、質の高いサービス提供を牽引いただく大きな力になると期待しております。\n\n"
        "   Character Count Check (Draft 2):\n"
        "        整形外科での臨床に加え、副主任として管理業務に携わられた8年の歩みに注目しました。(39 chars)\n"
        "        病院での多角的なリハビリ経験や運営視点は、当院において、質の高いサービス提供を牽引いただく"
        "大きな力になると期待しております。(84 chars)\n\n"
        "   Draft 3 (Refining):\n"
        "        整形外科での臨床に加え、副主任として管理業務に携わられた8年の歩みに注目しました。"
        "病院での多角的なリハビリ経験や運営視点は、当院において、質の高いサービス提供をリードいただく"
        "大きな力になると期待しております。"
    )
    result = _strip_thinking(leaked)
    assert "Draft" not in result
    assert "Character Count" not in result
    assert "(39 chars)" not in result
    assert "(84 chars)" not in result
    assert "リードいただく" not in result, "Draft 3 (revision) should be discarded"
    assert result.startswith("整形外科での臨床に加え")
    assert result.endswith("大きな力になると期待しております。")


def test_removes_character_count_check_block_with_inline_quotes():
    """『Draft N:\\n本文...\\n\\nCharacter count check (Draft N):\\n「本文」\\n-> N characters.』
    のように、本文の後ろに自己検証ブロック（カギ括弧で再引用＋文字数カウント）が
    続くケース。Character count check ブロックはメタなので本文とDraft先頭行のみ残す。
    """
    leaked = (
        "Draft 2 (Applying constraints and refining tone):\n"
        "    特別養護老人ホームで12年にわたり生活相談員を務めてこられた確かな実践力に注目しました。"
        "看取りまで向き合ってこられたご経験から培われた傾聴力は、"
        "ご入居を検討されるご家族の不安に寄り添う場面で大きな力になると確信しております。\n\n"
        "Character count check (Draft 2):\n"
        "    「特別養護老人ホームで12年にわたり生活相談員を務めてこられた確かな実践力に注目しました。"
        "看取りまで向き合ってこられたご経験から培われた傾聴力は、"
        "ご入居を検討されるご家族の不安に寄り添う場面で大きな力になると確信しております。」\n"
        "    -> 113 characters. (Good: 80-120 range)"
    )
    result = _strip_thinking(leaked)
    assert "Draft" not in result
    assert "Character count" not in result
    assert "113 characters" not in result
    assert "80-120 range" not in result
    assert result.startswith("特別養護老人ホームで12年にわたり")
    assert result.endswith("大きな力になると確信しております。")
