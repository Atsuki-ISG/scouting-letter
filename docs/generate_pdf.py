#!/usr/bin/env python3
"""Convert admin-setup-guide.md to a well-formatted Japanese PDF."""

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether, ListFlowable, ListItem,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Register Japanese fonts
FONT_REG = "BIZUDPGothic"
FONT_BOLD = "BIZUDPGothic-Bold"
pdfmetrics.registerFont(TTFont(FONT_REG, "/Users/aki/Library/Fonts/BIZUDPGothic-Regular.ttf"))
pdfmetrics.registerFont(TTFont(FONT_BOLD, "/Users/aki/Library/Fonts/BIZUDPGothic-Bold.ttf"))

# Colors
C_PRIMARY = HexColor("#1a56db")
C_HEADING = HexColor("#111827")
C_BODY = HexColor("#374151")
C_MUTED = HexColor("#6b7280")
C_BG_QUOTE = HexColor("#f0f5ff")
C_BG_TABLE_H = HexColor("#e8edf5")
C_BORDER = HexColor("#d1d5db")
C_CODE_BG = HexColor("#f3f4f6")
C_LINK = HexColor("#1a56db")

# Styles
s_title = ParagraphStyle("Title", fontName=FONT_BOLD, fontSize=18, leading=26,
                          textColor=C_PRIMARY, spaceAfter=4)
s_subtitle = ParagraphStyle("Subtitle", fontName=FONT_REG, fontSize=10, leading=14,
                             textColor=C_MUTED, spaceAfter=12)
s_h2 = ParagraphStyle("H2", fontName=FONT_BOLD, fontSize=14, leading=20,
                        textColor=C_HEADING, spaceBefore=18, spaceAfter=8)
s_h3 = ParagraphStyle("H3", fontName=FONT_BOLD, fontSize=11, leading=16,
                        textColor=C_HEADING, spaceBefore=12, spaceAfter=6)
s_body = ParagraphStyle("Body", fontName=FONT_REG, fontSize=9.5, leading=15,
                          textColor=C_BODY)
s_body_bold = ParagraphStyle("BodyBold", fontName=FONT_BOLD, fontSize=9.5, leading=15,
                               textColor=C_BODY)
s_quote = ParagraphStyle("Quote", fontName=FONT_REG, fontSize=8.5, leading=13,
                           textColor=C_MUTED, leftIndent=8, rightIndent=8)
s_code = ParagraphStyle("Code", fontName="Courier", fontSize=8.5, leading=12,
                          textColor=C_BODY, leftIndent=12)
s_list_item = ParagraphStyle("ListItem", fontName=FONT_REG, fontSize=9.5, leading=15,
                               textColor=C_BODY, leftIndent=6)
s_table_header = ParagraphStyle("TableH", fontName=FONT_BOLD, fontSize=8.5, leading=12,
                                  textColor=C_HEADING)
s_table_cell = ParagraphStyle("TableC", fontName=FONT_REG, fontSize=8.5, leading=12,
                                textColor=C_BODY)


def build_pdf(output_path: str):
    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        leftMargin=25*mm, rightMargin=25*mm,
        topMargin=20*mm, bottomMargin=20*mm,
    )
    story = []
    W = doc.width

    def hr():
        story.append(Spacer(1, 6))
        story.append(HRFlowable(width="100%", thickness=0.5, color=C_BORDER))
        story.append(Spacer(1, 6))

    def quote_block(lines):
        text = "<br/>".join(lines)
        t = Table([[Paragraph(text, s_quote)]], colWidths=[W - 4*mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), C_BG_QUOTE),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("ROUNDEDCORNERS", [3, 3, 3, 3]),
        ]))
        story.append(t)
        story.append(Spacer(1, 6))

    def md_table(headers, rows):
        col_count = len(headers)
        col_w = W / col_count
        data = [[Paragraph(h, s_table_header) for h in headers]]
        for row in rows:
            data.append([Paragraph(c, s_table_cell) for c in row])
        t = Table(data, colWidths=[col_w] * col_count)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), C_BG_TABLE_H),
            ("GRID", (0, 0), (-1, -1), 0.5, C_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]
        t.setStyle(TableStyle(style))
        story.append(t)
        story.append(Spacer(1, 8))

    def fmt(text):
        """Convert markdown inline formatting to reportlab XML."""
        import re
        # Bold
        text = re.sub(r'\*\*(.+?)\*\*', rf'<font name="{FONT_BOLD}">\1</font>', text)
        # Inline code
        text = re.sub(r'`(.+?)`', r'<font name="Courier" color="#dc2626">\1</font>', text)
        # Links
        text = re.sub(r'\[(.+?)\]\((.+?)\)', r'<font color="#1a56db"><u>\1</u></font>', text)
        return text

    # === Title ===
    story.append(Paragraph("管理者向け", s_title))
    story.append(Paragraph("GCPアカウント＆Gemini APIキー発行手順", s_title))
    story.append(Spacer(1, 4))
    story.append(Paragraph("スカウト文生成AIを動かすために必要な初期セットアップです。所要時間: 約15分", s_subtitle))
    hr()

    # === やること ===
    story.append(Paragraph("やること", s_h2))
    items = [
        ListItem(Paragraph(fmt("**GCPプロジェクト作成 + 課金有効化**（サーバー設置先）"), s_list_item)),
        ListItem(Paragraph(fmt("**Gemini APIキー発行 + 支払い設定**（AI呼び出し用）"), s_list_item)),
    ]
    story.append(ListFlowable(items, bulletType='1', bulletFontName=FONT_BOLD,
                               bulletFontSize=9.5, bulletColor=C_PRIMARY, leftIndent=16))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "この2つが完了したら、APIキーとプロジェクトIDを開発担当に共有してください。",
        s_body))
    story.append(Paragraph(
        "API有効化・サービスアカウント作成・スプレッドシート準備・デプロイ等は開発担当が行います。",
        s_body))
    hr()

    # === ① GCPプロジェクト作成 ===
    story.append(Paragraph("① GCPプロジェクト作成", s_h2))

    story.append(Paragraph("1. Google Cloud Consoleにアクセス", s_h3))
    story.append(Paragraph(fmt(
        '<font color="#1a56db"><u>https://console.cloud.google.com/</u></font> にGoogleアカウントでログイン'
    ), s_body))
    story.append(Spacer(1, 8))

    story.append(Paragraph("2. プロジェクト作成", s_h3))
    steps = [
        "画面上部のプロジェクト選択ドロップダウンをクリック",
        "「新しいプロジェクト」をクリック",
        fmt('**プロジェクト名**: `scout-generation`'),
        "「作成」をクリック",
        fmt("画面上部に `scout-generation` と表示されればOK"),
    ]
    items = [ListItem(Paragraph(s, s_list_item)) for s in steps]
    story.append(ListFlowable(items, bulletType='1', bulletFontName=FONT_REG,
                               bulletFontSize=9, start=1, leftIndent=16))
    story.append(Spacer(1, 8))

    story.append(Paragraph("3. 課金の有効化", s_h3))
    steps = [
        "左メニュー → 「お支払い」",
        "請求先アカウントをリンク",
    ]
    items = [ListItem(Paragraph(s, s_list_item)) for s in steps]
    story.append(ListFlowable(items, bulletType='1', bulletFontName=FONT_REG,
                               bulletFontSize=9, start=1, leftIndent=16))
    sub_items = [
        ListItem(Paragraph(fmt("初回は**無料トライアル（$300クレジット）**が使える"), s_list_item)),
        ListItem(Paragraph("クレジットカード登録が必要だが、無料枠内なら課金されない", s_list_item)),
    ]
    story.append(ListFlowable(sub_items, bulletType='bullet', bulletFontSize=6, leftIndent=32))
    story.append(Spacer(1, 6))

    quote_block([
        fmt("**コスト目安**: 月3,000件のAI生成で約 $0.5〜$1/月（ほぼ無料枠内）"),
        "※これはAPIの使用ではなくサーバ（webアプリ）を提供することのコスト",
    ])
    hr()

    # === ② Gemini APIキー発行 ===
    story.append(Paragraph("② Gemini APIキー発行", s_h2))

    story.append(Paragraph("1. Google AI Studio にアクセス", s_h3))
    story.append(Paragraph(fmt(
        '<font color="#1a56db"><u>https://aistudio.google.com/apikey</u></font> にログイン（①と同じGoogleアカウント）'
    ), s_body))
    story.append(Spacer(1, 8))

    story.append(Paragraph("2. APIキー作成", s_h3))
    steps = [
        "「APIキーを作成」をクリック",
        fmt("プロジェクトを選択: `scout-generation`"),
        "「APIキーを作成」で確定",
        fmt("表示されたAPIキー（`AIza...` で始まる文字列）を**安全な場所にコピー**"),
    ]
    items = [ListItem(Paragraph(s, s_list_item)) for s in steps]
    story.append(ListFlowable(items, bulletType='1', bulletFontName=FONT_REG,
                               bulletFontSize=9, start=1, leftIndent=16))
    story.append(Spacer(1, 6))
    quote_block([
        "このAPIキー1つで全Geminiモデル（Flash〜Pro）を呼び出せます。",
        "モデルの選択はサーバー側で設定するので、ここでは不要です。",
    ])

    story.append(Paragraph("3. 支払い設定（従量課金の有効化）", s_h3))
    story.append(Paragraph(
        "APIキーには無料枠がありますが、上限を超えると停止します。", s_body))
    story.append(Paragraph(
        "今回はAPI利用コストが無料枠では収まらないので、従量課金を有効にします。", s_body))
    story.append(Spacer(1, 6))
    steps = [
        fmt('<font color="#1a56db"><u>https://aistudio.google.com/apikey</u></font> にアクセス'),
        fmt('発行したAPIキーの横にある「課金プロジェクト」が `scout-generation` になっていることを確認'),
        fmt("①-3で課金を有効化済みであれば、**自動的に従量課金が適用**される"),
    ]
    items = [ListItem(Paragraph(s, s_list_item)) for s in steps]
    story.append(ListFlowable(items, bulletType='1', bulletFontName=FONT_REG,
                               bulletFontSize=9, start=1, leftIndent=16))
    hr()

    # === 補足: コスト管理 ===
    story.append(Paragraph("補足: コスト管理", s_h2))

    story.append(Paragraph("GCPサーバー費用（Cloud Run等）", s_h3))
    story.append(Paragraph(
        "①の課金設定に含まれます。月$1以下の見込み。", s_body))
    story.append(Paragraph(fmt(
        "GCP Console → 「お支払い」→「予算とアラート」で月額上限の通知設定が可能です。"
    ), s_body))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Gemini API費用", s_h3))
    story.append(Paragraph(fmt(
        "GCPの予算アラートとは**別管理**です。"
    ), s_body))
    story.append(Paragraph(fmt(
        "サーバー側でリクエスト数・推定コストを集計し、**Google Chatへ定期通知する仕組みを実装予定**です。"
    ), s_body))
    hr()

    # === 開発担当への共有 ===
    story.append(Paragraph("開発担当への共有", s_h2))
    story.append(Paragraph("以下の2つを開発担当に渡してください:", s_body))
    story.append(Spacer(1, 6))
    md_table(
        ["項目", "例"],
        [
            [fmt("**GCPプロジェクトID**"), fmt("`scout-generation`")],
            [fmt("**Gemini APIキー**"), fmt("`AIzaSy...`")],
        ],
    )
    quote_block([
        "【注意】APIキーは機密情報です。パスワードマネージャーや対面で共有してください。",
    ])

    doc.build(story)
    print(f"PDF generated: {output_path}")


if __name__ == "__main__":
    build_pdf("/Users/aki/scouting-letter/docs/admin-setup-guide.pdf")
