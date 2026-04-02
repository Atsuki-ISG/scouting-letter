"""Rebuild all 4 company dashboards with _chart_data + addChart (fully automated).

Creates hidden _chart_data sheets with COUNTIF aggregation,
then dashboard sheets with embedded charts via addChart API.
No manual steps required.

Usage:
    cd server && GOOGLE_APPLICATION_CREDENTIALS=sa-key.json python scripts/rebuild_dashboards.py
"""
from __future__ import annotations

import re
import time

import google.auth
from googleapiclient.discovery import build

SPREADSHEET_ID = "1a3XE212nZgsQP-93phk22VlSSZ5aD1ig72M4A6p2awE"

WHITE = {"red": 1, "green": 1, "blue": 1}
BLACK_TEXT = {"red": 0.13, "green": 0.13, "blue": 0.13}

PALETTES = {
    "アーク訪看": {
        "DARK":  {"red": 0.10, "green": 0.27, "blue": 0.53},
        "MAIN":  {"red": 0.26, "green": 0.52, "blue": 0.96},
        "MID":   {"red": 0.55, "green": 0.71, "blue": 0.97},
        "LIGHT": {"red": 0.78, "green": 0.87, "blue": 0.99},
        "PALE":  {"red": 0.91, "green": 0.94, "blue": 0.99},
        "BG":    {"red": 0.96, "green": 0.97, "blue": 0.99},
    },
    "いちご訪看": {
        "DARK":  {"red": 0.05, "green": 0.35, "blue": 0.33},
        "MAIN":  {"red": 0.15, "green": 0.56, "blue": 0.53},
        "MID":   {"red": 0.40, "green": 0.73, "blue": 0.71},
        "LIGHT": {"red": 0.70, "green": 0.87, "blue": 0.86},
        "PALE":  {"red": 0.88, "green": 0.95, "blue": 0.94},
        "BG":    {"red": 0.95, "green": 0.98, "blue": 0.97},
    },
    "LCC訪看": {
        "DARK":  {"red": 0.55, "green": 0.25, "blue": 0.05},
        "MAIN":  {"red": 0.85, "green": 0.45, "blue": 0.15},
        "MID":   {"red": 0.93, "green": 0.65, "blue": 0.40},
        "LIGHT": {"red": 0.97, "green": 0.82, "blue": 0.65},
        "PALE":  {"red": 0.99, "green": 0.93, "blue": 0.85},
        "BG":    {"red": 1.00, "green": 0.97, "blue": 0.93},
    },
    "an訪看": {
        "DARK":  {"red": 0.30, "green": 0.15, "blue": 0.50},
        "MAIN":  {"red": 0.48, "green": 0.32, "blue": 0.75},
        "MID":   {"red": 0.65, "green": 0.52, "blue": 0.85},
        "LIGHT": {"red": 0.82, "green": 0.73, "blue": 0.93},
        "PALE":  {"red": 0.93, "green": 0.90, "blue": 0.97},
        "BG":    {"red": 0.97, "green": 0.96, "blue": 0.99},
    },
}

CONFIGS = [
    {
        "source": "アーク訪看",
        "dashboard": "アーク訪看ダッシュボード",
        "chart_data": "_chart_data_ark",
        "dataStartRow": 8,
        "maxSourceCols": 16,
        "columns": {"name": 1, "status": 2, "job": 10, "media": 9, "app_type": 11,
                     "location": 0, "age_gender": 12, "date": 5},
        "statuses": ["書類選考中", "日程調整中", "日程調整完了", "面談完了", "採用候補者", "採用決定", "不採用", "辞退"],
        "media": ["ジョブメドレー", "Indeed", "コメディカル", "知り合い", "その他"],
        "app_types": ["応募", "スカウト返信", "気になる返信"],
        "locations": [],
        "charts": ["status", "monthly", "job", "media", "age", "gender"],
    },
    {
        "source": "いちご訪看",
        "dashboard": "いちご訪看ダッシュボード",
        "chart_data": "_chart_data_ichigo",
        "dataStartRow": 9,
        "maxSourceCols": 12,
        "columns": {"name": 1, "status": 2, "job": 7, "media": 6, "app_type": 8,
                     "location": 4, "age_gender": 9, "date": 5},
        "statuses": ["01_書類選考中", "02_日程調整中", "03_1次面談終了", "04_面談終了", "05_採用決定", "05_選考辞退"],
        "media": ["ジョブメドレー", "Indeed", "知り合い"],
        "app_types": ["応募", "スカウト返信", "気になる返信"],
        "locations": [],
        "charts": ["status", "monthly", "job", "media", "age", "gender"],
    },
    {
        "source": "LCC訪看",
        "dashboard": "LCC訪看ダッシュボード",
        "chart_data": "_chart_data_lcc",
        "dataStartRow": 8,
        "maxSourceCols": 16,
        "columns": {"name": 1, "status": 2, "job": 11, "media": 9, "app_type": 13,
                     "location": 10, "age_gender": 14, "date": 5},
        "statuses": ["01_書類選考中", "02_日程調整中", "03_1次面談終了", "04_面談終了", "05_採用決定", "05_選考辞退"],
        "media": ["ジョブメドレー", "カイテク", "Indeed", "知り合い"],
        "app_types": ["応募", "スカウト返信", "気になる返信"],
        "locations": ["本社", "北里研究所病院サテライト"],
        "charts": ["status", "monthly", "job", "media", "age", "gender"],
    },
    {
        "source": "an訪看",
        "dashboard": "an訪看ダッシュボード",
        "chart_data": "_chart_data_an",
        "dataStartRow": 8,
        "maxSourceCols": 12,
        "columns": {"name": 1, "status": 2, "job": 8, "media": 0, "app_type": 9,
                     "location": 0, "age_gender": 10, "date": 5},
        "statuses": ["面談終了", "日程調整完了", "お見送り", "採用決定"],
        "media": [],
        "app_types": ["応募", "スカウト返信"],
        "locations": [],
        "charts": ["status", "monthly", "job", "app_type", "age", "gender"],
    },
]

CURRENT_MONTH = 3  # 2026年3月
ALL_AGE_GROUPS = ["〜24歳", "25〜29歳", "30〜34歳", "35〜39歳", "40〜44歳", "45〜49歳", "50歳〜"]


def month_range(start: int, end: int) -> list[int]:
    """Generate month numbers from start to end, wrapping around year boundary."""
    result = []
    m = start
    while True:
        result.append(m)
        if m == end:
            break
        m = m % 12 + 1
    return result


def col_letter(col_1indexed: int) -> str:
    """1-indexed column number to letter (1=A, 26=Z, 27=AA)."""
    result = ""
    n = col_1indexed
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        result = chr(65 + remainder) + result
    return result


def build_chart_data_formulas(config: dict, months: list[int]) -> list[list[str]]:
    """Build formulas for _chart_data sheet.

    Args:
        months: list of month numbers to include (e.g. [10,11,12,1,2,3])
    """
    src = config["source"]
    start = config["dataStartRow"]
    cols = config["columns"]
    max_row = start + 200  # generous range

    def src_range(col_num: int) -> str:
        c = col_letter(col_num)
        return f"'{src}'!{c}{start}:{c}{max_row}"

    def countif(col_num: int, value: str) -> str:
        return f'=COUNTIF({src_range(col_num)},"{value}")'

    rows = []

    # --- Section 1: 選考状況 ---
    rows.append(["選考状況", "人数"])
    for s in config["statuses"]:
        rows.append([s, countif(cols["status"], s)])

    rows.append(["", ""])  # spacer

    # --- Section 2: 月別推移 ---
    rows.append(["月", "人数"])
    date_col = cols["date"]
    if date_col > 0:
        dc = col_letter(date_col)
        rng = f"'{src}'!{dc}{start}:{dc}{max_row}"
        for m_num in months:
            rows.append([
                f"{m_num}月",
                f'=SUMPRODUCT((ISNUMBER({rng})*(TEXT({rng},"M")="{m_num}")+'
                f'(NOT(ISNUMBER({rng}))*(LEFT({rng},LEN("{m_num}/"))="{m_num}/")))*1)'
            ])
    else:
        for m_num in months:
            rows.append([f"{m_num}月", "0"])

    rows.append(["", ""])

    # --- Section 3: 職種別 ---
    rows.append(["職種", "人数"])
    # We'll compute job categories from actual data later
    rows.append(["_placeholder_jobs", ""])

    rows.append(["", ""])

    # --- Section 4: 媒体別 or 応募種別 ---
    if config["media"]:
        rows.append(["媒体", "人数"])
        for m in config["media"]:
            rows.append([m, countif(cols["media"], m)])
    elif config["app_types"]:
        rows.append(["応募種別", "人数"])
        for a in config["app_types"]:
            rows.append([a, countif(cols["app_type"], a)])

    rows.append(["", ""])

    # --- Section 5: 年齢分布 ---
    # Format: "42歳 女性" — extract leading digits, but ONLY for non-empty cells
    # LEN(cell)>0 filters out empties, ISNUMBER(VALUE(LEFT(cell,2))) ensures valid number
    rows.append(["年齢層", "人数"])
    ag_col = cols["age_gender"]
    if ag_col > 0:
        ac = col_letter(ag_col)
        rng = f"'{src}'!{ac}{start}:{ac}{max_row}"
        valid = f'(LEN({rng})>0)*ISNUMBER(VALUE(LEFT({rng},2)))'
        age = f'VALUE(LEFT({rng},2))'
        rows.append(["〜24歳",    f'=SUMPRODUCT(({valid})*({age}<25)*1)'])
        rows.append(["25〜29歳",  f'=SUMPRODUCT(({valid})*({age}>=25)*({age}<30)*1)'])
        rows.append(["30〜34歳",  f'=SUMPRODUCT(({valid})*({age}>=30)*({age}<35)*1)'])
        rows.append(["35〜39歳",  f'=SUMPRODUCT(({valid})*({age}>=35)*({age}<40)*1)'])
        rows.append(["40〜44歳",  f'=SUMPRODUCT(({valid})*({age}>=40)*({age}<45)*1)'])
        rows.append(["45〜49歳",  f'=SUMPRODUCT(({valid})*({age}>=45)*({age}<50)*1)'])
        rows.append(["50歳〜",    f'=SUMPRODUCT(({valid})*({age}>=50)*1)'])
    else:
        for ag in ALL_AGE_GROUPS:
            rows.append([ag, "0"])

    rows.append(["", ""])

    # --- Section 6: 性別 ---
    rows.append(["性別", "人数"])
    if ag_col > 0:
        rows.append(["男性", f'=COUNTIF({src_range(ag_col)},"*男性*")'])
        rows.append(["女性", f'=COUNTIF({src_range(ag_col)},"*女性*")'])
    else:
        rows.append(["男性", "0"])
        rows.append(["女性", "0"])

    return rows


def find_section_ranges(data_sheet_name: str, rows: list[list[str]]) -> dict:
    """Find row ranges for each section in chart_data by scanning headers."""
    sections = {}
    section_names = {
        "選考状況": "status", "月": "monthly", "職種": "job",
        "媒体": "media", "応募種別": "app_type",
        "年齢層": "age", "性別": "gender",
    }
    current_section = None
    section_start = None

    for i, row in enumerate(rows):
        label = row[0] if row else ""
        if label in section_names:
            if current_section and section_start is not None:
                sections[current_section] = (section_start, i)
            current_section = section_names[label]
            section_start = i  # header row
        elif label == "" and current_section:
            sections[current_section] = (section_start, i)
            current_section = None
            section_start = None

    if current_section and section_start is not None:
        sections[current_section] = (section_start, len(rows))

    return sections


def make_chart(sheet_id: int, chart_data_sheet_id: int, chart_data_name: str,
               section_start: int, section_end: int,
               title: str, chart_type: str, palette: dict,
               row_anchor: int, col_anchor: int,
               offset_x: int = 15, offset_y: int = 10,
               width: int = 580, height: int = 340) -> dict:
    """Create an addChart request."""
    # Data: column A = labels (startCol=0), column B = values (startCol=1)
    # section_start is header row (0-indexed), data starts at section_start+1
    domain_range = {
        "sheetId": chart_data_sheet_id,
        "startRowIndex": section_start,
        "endRowIndex": section_end,
        "startColumnIndex": 0,
        "endColumnIndex": 1,
    }
    data_range = {
        "sheetId": chart_data_sheet_id,
        "startRowIndex": section_start,
        "endRowIndex": section_end,
        "startColumnIndex": 1,
        "endColumnIndex": 2,
    }

    if chart_type == "COLUMN":
        spec_key = "basicChart"
        spec = {
            "chartType": "COLUMN",
            "legendPosition": "NO_LEGEND",
            "axis": [
                {"position": "BOTTOM_AXIS", "title": ""},
                {"position": "LEFT_AXIS", "title": "人数",
                 "format": {"fontFamily": "Roboto", "fontSize": 10}},
            ],
            "domains": [{"domain": {"sourceRange": {"sources": [domain_range]}}}],
            "series": [{
                "series": {"sourceRange": {"sources": [data_range]}},
                "colorStyle": {"rgbColor": palette["MAIN"]},
            }],
            "headerCount": 1,
        }
    elif chart_type == "BAR":
        spec_key = "basicChart"
        spec = {
            "chartType": "BAR",
            "legendPosition": "NO_LEGEND",
            "axis": [
                {"position": "BOTTOM_AXIS", "title": "人数",
                 "format": {"fontFamily": "Roboto", "fontSize": 10}},
                {"position": "LEFT_AXIS", "title": ""},
            ],
            "domains": [{"domain": {"sourceRange": {"sources": [domain_range]}}}],
            "series": [{
                "series": {"sourceRange": {"sources": [data_range]}},
                "colorStyle": {"rgbColor": palette["MAIN"]},
            }],
            "headerCount": 1,
        }
    else:
        raise ValueError(f"Unknown chart type: {chart_type}")

    return {
        "addChart": {
            "chart": {
                "spec": {
                    "title": title,
                    "titleTextFormat": {"fontFamily": "Roboto", "fontSize": 14, "bold": True,
                                        "foregroundColor": BLACK_TEXT},
                    "backgroundColor": WHITE,
                    spec_key: spec,
                },
                "position": {
                    "overlayPosition": {
                        "anchorCell": {"sheetId": sheet_id, "rowIndex": row_anchor, "columnIndex": col_anchor},
                        "offsetXPixels": offset_x,
                        "offsetYPixels": offset_y,
                        "widthPixels": width,
                        "heightPixels": height,
                    }
                },
            }
        }
    }


def format_cell(value, fmt: dict):
    cell = {"userEnteredValue": {}}
    if isinstance(value, (int, float)):
        cell["userEnteredValue"]["numberValue"] = value
    elif str(value).startswith("="):
        cell["userEnteredValue"]["formulaValue"] = str(value)
    else:
        cell["userEnteredValue"]["stringValue"] = str(value)
    if fmt:
        cell["userEnteredFormat"] = fmt
    return cell


def build_dashboard_for_company(service, config):
    source_name = config["source"]
    dashboard_name = config["dashboard"]
    chart_data_name = config["chart_data"]
    palette = PALETTES[source_name]
    cols = config["columns"]

    print(f"\n{'='*60}")
    print(f"Building: {dashboard_name}")

    # ── 1. Read source to get unique job categories ──
    src_range = f"'{source_name}'!A{config['dataStartRow']}:P"
    resp = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=src_range
    ).execute()
    source_data = resp.get("values", [])
    print(f"  Source: {len(source_data)} rows")

    # Extract unique job categories
    job_col = cols["job"]
    jobs = set()
    if job_col > 0:
        for row in source_data:
            if len(row) > job_col - 1:
                v = str(row[job_col - 1]).strip()
                if v:
                    jobs.add(v)
    jobs = sorted(jobs)
    print(f"  Jobs: {jobs}")

    # Detect earliest month from date column
    date_col = cols["date"]
    detected_months: set[int] = set()
    if date_col > 0:
        import re as _re
        for row in source_data:
            if len(row) > date_col - 1:
                v = str(row[date_col - 1]).strip()
                if v:
                    m = _re.match(r"^(\d{1,2})/", v)
                    if m:
                        detected_months.add(int(m.group(1)))

    if detected_months:
        start_m = min(detected_months, key=lambda m: (m - 1) % 12 if m <= CURRENT_MONTH else (m - 1))
        # Find the true start considering year wrap: months > CURRENT_MONTH are "earlier" (previous year)
        prev_year = [m for m in detected_months if m > CURRENT_MONTH]
        curr_year = [m for m in detected_months if m <= CURRENT_MONTH]
        if prev_year:
            start_m = min(prev_year)
        elif curr_year:
            start_m = min(curr_year)
        months = month_range(start_m, CURRENT_MONTH)
    else:
        months = month_range(1, CURRENT_MONTH)
    print(f"  Months: {[f'{m}月' for m in months]}")

    # ── 2. Build chart_data formulas ──
    cd_rows = build_chart_data_formulas(config, months)

    # Replace job placeholder with actual jobs
    final_rows = []
    for row in cd_rows:
        if row[0] == "_placeholder_jobs":
            for j in jobs:
                final_rows.append([j, f'=COUNTIF(\'{source_name}\'!{col_letter(job_col)}{config["dataStartRow"]}:{col_letter(job_col)}{config["dataStartRow"]+200},"{j}")'])
        else:
            final_rows.append(row)

    # Find section ranges
    sections = find_section_ranges(chart_data_name, final_rows)
    print(f"  Sections: {sections}")

    # ── 3. Create sheets ──
    create_requests = [
        {"addSheet": {"properties": {"title": chart_data_name, "hidden": True}}},
        {"addSheet": {"properties": {"title": dashboard_name}}},
    ]
    resp = service.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": create_requests},
    ).execute()
    cd_sheet_id = resp["replies"][0]["addSheet"]["properties"]["sheetId"]
    db_sheet_id = resp["replies"][1]["addSheet"]["properties"]["sheetId"]
    print(f"  chart_data id={cd_sheet_id}, dashboard id={db_sheet_id}")

    # ── 4. Write chart_data formulas ──
    values = [[str(c) for c in row] for row in final_rows]
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{chart_data_name}'!A1:B{len(values)}",
        valueInputOption="USER_ENTERED",
        body={"values": values},
    ).execute()
    print(f"  Wrote {len(values)} rows to {chart_data_name}")

    # ── 5. Format dashboard + add charts ──
    requests = []

    # Hide gridlines
    requests.append({
        "updateSheetProperties": {
            "properties": {"sheetId": db_sheet_id,
                           "gridProperties": {"hideGridlines": True}},
            "fields": "gridProperties.hideGridlines",
        }
    })

    # Tab color
    requests.append({
        "updateSheetProperties": {
            "properties": {"sheetId": db_sheet_id,
                           "tabColorStyle": {"rgbColor": palette["MAIN"]}},
            "fields": "tabColorStyle",
        }
    })

    # Column widths — tighter 2-column layout
    # Col 0: left margin, Cols 1-5: left chart area, Col 6: gap,
    # Cols 7-11: right chart area, Col 12: right margin
    for (start, end), width in [
        ((0, 1), 15),     # left margin
        ((1, 6), 120),    # left chart area (5 cols × 120 = 600px)
        ((6, 7), 15),     # gap between charts
        ((7, 12), 120),   # right chart area (5 cols × 120 = 600px)
        ((12, 13), 15),   # right margin
    ]:
        requests.append({
            "updateDimensionProperties": {
                "range": {"sheetId": db_sheet_id, "dimension": "COLUMNS",
                          "startIndex": start, "endIndex": end},
                "properties": {"pixelSize": width},
                "fields": "pixelSize",
            }
        })

    # Row heights
    for (start, end), height in [
        ((0, 1), 50), ((1, 2), 28), ((2, 3), 80), ((3, 4), 21), ((4, 5), 21),
    ]:
        requests.append({
            "updateDimensionProperties": {
                "range": {"sheetId": db_sheet_id, "dimension": "ROWS",
                          "startIndex": start, "endIndex": end},
                "properties": {"pixelSize": height},
                "fields": "pixelSize",
            }
        })

    # Title bar (row 1)
    title_fmt = {
        "backgroundColor": palette["DARK"],
        "textFormat": {"foregroundColor": WHITE, "fontSize": 20, "bold": True, "fontFamily": "Roboto"},
        "verticalAlignment": "MIDDLE",
        "horizontalAlignment": "LEFT",
        "padding": {"left": 16},
    }
    NUM_COLS = 13  # 0-12
    requests.append({
        "updateCells": {
            "rows": [{"values": [format_cell(f"{source_name} ダッシュボード", title_fmt)]
                      + [format_cell("", {"backgroundColor": palette["DARK"]})] * (NUM_COLS - 1)}],
            "start": {"sheetId": db_sheet_id, "rowIndex": 0, "columnIndex": 0},
            "fields": "userEnteredValue,userEnteredFormat",
        }
    })
    requests.append({
        "mergeCells": {
            "range": {"sheetId": db_sheet_id, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": NUM_COLS},
            "mergeType": "MERGE_ALL",
        }
    })

    # KPI (row 2: labels, row 3: values)
    src = source_name
    start = config["dataStartRow"]
    max_row = start + 200
    status_col = col_letter(cols["status"])
    name_col = col_letter(cols["name"])
    status_rng = f"'{src}'!{status_col}{start}:{status_col}{max_row}"
    name_rng = f"'{src}'!{name_col}{start}:{name_col}{max_row}"

    kpi_items = [
        ("合計", f'=SUMPRODUCT((LEN({name_rng})>0)*1)'),
        ("書類選考", f'=COUNTIF({status_rng},"*書類選考*")'),
        ("日程調整", f'=COUNTIF({status_rng},"*日程調整*")'),
        ("面談完了", f'=COUNTIF({status_rng},"*面談*")'),
        ("採用決定", f'=COUNTIF({status_rng},"*採用決定*")'),
    ]

    label_fmt = {
        "backgroundColor": WHITE,
        "textFormat": {"foregroundColor": palette["MAIN"], "fontSize": 11, "fontFamily": "Roboto"},
        "horizontalAlignment": "CENTER",
        "verticalAlignment": "BOTTOM",
    }
    value_fmt = {
        "backgroundColor": WHITE,
        "textFormat": {"foregroundColor": BLACK_TEXT, "fontSize": 42, "bold": True, "fontFamily": "Roboto"},
        "horizontalAlignment": "CENTER",
        "verticalAlignment": "MIDDLE",
        "numberFormat": {"type": "NUMBER", "pattern": "#,##0"},
    }

    # KPI: 5 items across 12 usable columns (1-11), each gets ~2 cols
    kpi_starts = [1, 3, 5, 7, 9]
    kpi_widths = [2, 2, 2, 2, 2]  # each KPI spans 2 columns
    label_cells = [format_cell("", {"backgroundColor": WHITE})] * NUM_COLS
    value_cells = [format_cell("", {"backgroundColor": WHITE})] * NUM_COLS

    for idx, (label, formula) in enumerate(kpi_items):
        col = kpi_starts[idx]
        label_cells[col] = format_cell(label, label_fmt)
        value_cells[col] = format_cell(formula, value_fmt)

    requests.append({
        "updateCells": {
            "rows": [{"values": label_cells}],
            "start": {"sheetId": db_sheet_id, "rowIndex": 1, "columnIndex": 0},
            "fields": "userEnteredValue,userEnteredFormat",
        }
    })
    requests.append({
        "updateCells": {
            "rows": [{"values": value_cells}],
            "start": {"sheetId": db_sheet_id, "rowIndex": 2, "columnIndex": 0},
            "fields": "userEnteredValue,userEnteredFormat",
        }
    })

    # Merge KPI cells
    for idx in range(len(kpi_items)):
        col = kpi_starts[idx]
        w = kpi_widths[idx]
        for row in [1, 2]:
            requests.append({
                "mergeCells": {
                    "range": {"sheetId": db_sheet_id, "startRowIndex": row, "endRowIndex": row + 1,
                              "startColumnIndex": col, "endColumnIndex": col + w},
                    "mergeType": "MERGE_ALL",
                }
            })

    # Spacer rows
    for spacer_row in [3, 4]:
        requests.append({
            "updateCells": {
                "rows": [{"values": [format_cell("", {"backgroundColor": palette["PALE"]})] * NUM_COLS}],
                "start": {"sheetId": db_sheet_id, "rowIndex": spacer_row, "columnIndex": 0},
                "fields": "userEnteredValue,userEnteredFormat",
            }
        })

    # BG for chart area
    for r in range(5, 56):
        requests.append({
            "updateCells": {
                "rows": [{"values": [format_cell("", {"backgroundColor": palette["BG"]})] * NUM_COLS}],
                "start": {"sheetId": db_sheet_id, "rowIndex": r, "columnIndex": 0},
                "fields": "userEnteredValue,userEnteredFormat",
            }
        })

    # ── Charts ──
    # Layout: 3 rows × 2 columns, tighter spacing
    # Left charts: anchor col 1, Right charts: anchor col 7
    # Chart width: 580px, height: 320px
    # Row spacing: 14 rows per chart row
    CHART_W = 580
    CHART_H = 320
    LEFT_COL = 1
    RIGHT_COL = 7
    ROW_SPACING = 17

    chart_layout = [
        # (chart_key, chart_type, title, row_anchor, col_anchor)
        ("status",   "COLUMN", "選考状況",  5, LEFT_COL),
        ("monthly",  "COLUMN", "月別推移",  5, RIGHT_COL),
        ("job",      "BAR",    "職種別",   5 + ROW_SPACING, LEFT_COL),
    ]

    # 4th chart: media or app_type
    if "media" in config["charts"] and "media" in sections:
        chart_layout.append(("media", "BAR", "媒体別", 5 + ROW_SPACING, RIGHT_COL))
    elif "app_type" in config["charts"] and "app_type" in sections:
        chart_layout.append(("app_type", "BAR", "応募種別", 5 + ROW_SPACING, RIGHT_COL))

    chart_layout.append(("age",    "COLUMN", "年齢分布", 5 + ROW_SPACING * 2, LEFT_COL))
    chart_layout.append(("gender", "BAR",    "男女比",   5 + ROW_SPACING * 2, RIGHT_COL))

    for chart_key, chart_type, title, row_anchor, col_anchor in chart_layout:
        if chart_key not in sections:
            print(f"  Warning: section '{chart_key}' not found, skipping chart")
            continue
        sec_start, sec_end = sections[chart_key]
        requests.append(make_chart(
            db_sheet_id, cd_sheet_id, chart_data_name,
            sec_start, sec_end,
            title, chart_type, palette,
            row_anchor, col_anchor,
            offset_x=5, offset_y=5,
            width=CHART_W, height=CHART_H,
        ))

    # Execute
    print(f"  Sending {len(requests)} requests...")
    service.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": requests},
    ).execute()
    print(f"  ✓ {dashboard_name} complete")


def main():
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=credentials)

    for config in CONFIGS:
        try:
            build_dashboard_for_company(service, config)
            time.sleep(2)
        except Exception as e:
            print(f"\n  ✗ Error: {config['dashboard']}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*60}")
    print("All dashboards rebuilt!")
    print("="*60)


if __name__ == "__main__":
    main()
