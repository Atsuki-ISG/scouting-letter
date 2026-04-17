"""Search query templates for the multi-pass competitor research pipeline.

Kept as a Python module (rather than YAML or Sheets) for now because the
set changes rarely and lives right next to the pipeline that consumes it.
Migrate to Sheets only when non-engineers need to tune queries.

Template placeholders:
  {area}       — geographic area extracted from profile (e.g. "東京都港区")
  {competitor} — competitor facility / company name (Pass 2 only)

Design (validated manually on 2026-04-17 against LCC訪問看護 / 港区):
  - Pass 1 (area-level listup)   returns 6–10 competitor names reliably.
  - Pass 2 per-competitor queries return concrete numbers and reviews.
  - Pass 2 area-wide queries ("訪問看護 港区 給与相場") return only求人サイト
    aggregates with no per-company differentiation — DO NOT USE.

業態 keys:
  visiting_nurse         訪問看護 (ARK, LCC, いちご, an)
  hospital_nurse         病院看護師 (野村病院, 茅ヶ崎徳洲会)
  elderly_care_sales     入居相談員 (ネオ・サミット湯河原)
  default                fallback when業態 unknown

When adding a new業態, copy the default entry and tune the keywords. Keep
queries under ~40 chars each — Google search tolerates long queries but
grounding tends to quote them verbatim and lose intent.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QueryBundle:
    """One set of query templates for a given業態."""
    listup: str                    # Pass 1
    conditions: str                # Pass 2A
    reputation: str                # Pass 2B (評判・口コミ)
    training_culture: str          # Pass 2B (研修・特色)


# Curated domain filters for Pass 2B reputation searches.
# OpenWork / エン / 転職会議 / Indeed are the most load-bearing口コミ sources
# for 看護・介護系 companies in Japan.
REPUTATION_DOMAINS = [
    "openwork.jp",
    "en-hyouban.com",
    "jobtalk.jp",
    "jp.indeed.com",
    "syukatsu-kaigi.jp",
]

CONDITIONS_DOMAINS = [
    "job-medley.com",
    "kango.mynavi.jp",
    "co-medical.com",
    "kango-roo.com",
    "hellowork.careers",
]


QUERIES: dict[str, QueryBundle] = {
    "visiting_nurse": QueryBundle(
        listup="{area} 訪問看護ステーション 一覧 採用",
        conditions="{competitor} 訪問看護 給与 月給 オンコール手当",
        reputation="{competitor} 訪問看護 評判 口コミ 働き方",
        training_culture="{competitor} 訪問看護 研修 教育 特色",
    ),
    "hospital_nurse": QueryBundle(
        listup="{area} 病院 看護師 採用 一覧",
        conditions="{competitor} 看護師 給与 夜勤手当 基本給",
        reputation="{competitor} 看護師 評判 離職 口コミ",
        training_culture="{competitor} 看護師 教育 プリセプター 研修",
    ),
    "elderly_care_sales": QueryBundle(
        listup="{area} 有料老人ホーム 入居相談員 採用",
        conditions="{competitor} 入居相談員 年収 インセンティブ 歩合",
        reputation="{competitor} 入居相談員 評判 働き方 口コミ",
        training_culture="{competitor} 入居相談員 研修 育成 営業スタイル",
    ),
    "default": QueryBundle(
        listup="{area} 採用 一覧",
        conditions="{competitor} 給与 手当 待遇",
        reputation="{competitor} 評判 口コミ 働き方",
        training_culture="{competitor} 研修 教育 特色",
    ),
}


# Company ID → 業態 mapping. Explicit so we don't guess from profile text.
# Update when adding a new company.
COMPANY_BUSINESS_TYPE: dict[str, str] = {
    "ark-visiting-nurse": "visiting_nurse",
    "lcc-visiting-nurse": "visiting_nurse",
    "ichigo-visiting-nurse": "visiting_nurse",
    "an-visiting-nurse": "visiting_nurse",
    "chigasaki-tokushukai": "hospital_nurse",
    "nomura-hospital": "hospital_nurse",
    "daiwa-house-ls": "elderly_care_sales",
}


def business_type_for(company_id: str) -> str:
    return COMPANY_BUSINESS_TYPE.get(company_id, "default")


def queries_for(company_id: str) -> QueryBundle:
    return QUERIES.get(business_type_for(company_id), QUERIES["default"])
