#!/usr/bin/env python3
"""
DART 사업보고서 PDF에서 주요 재무제표 테이블 숫자를 주당(per-share) 기준으로 변환해
새 PDF를 생성하는 스크립트.

핵심 동작
1) PDF에서 표 추출 (camelot 우선, 실패 시 tabula-py 시도)
2) 주요 재무제표(재무상태표/손익계산서/현금흐름표)로 보이는 표 선별
3) 숫자 컬럼을 발행주식수로 나눠 주당 값으로 변환
4) 원본 PDF 뒤에 "주당 환산 재무제표" 페이지를 붙여 출력

주의
- PDF 품질(스캔본/복잡한 레이아웃)에 따라 표 추출 정확도는 달라질 수 있습니다.
- 본 스크립트는 원문 텍스트/레이아웃을 완전 보존 편집하는 방식이 아니라,
  원본 + 환산 결과 페이지를 결합하는 방식입니다.
"""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, NamedTuple, Optional
from xml.sax.saxutils import escape

import pandas as pd
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import LongTable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, TableStyle


STATEMENT_KEYWORDS = {
    "재무상태표": ["재무상태표", "재무 상태표", "balance sheet"],
    "손익계산서": ["손익계산서", "포괄손익계산서", "income statement"],
    "자본변동표": ["자본변동표", "자본 변동표", "statement of changes in equity"],
    "현금흐름표": ["현금흐름표", "cash flow"],
}
DESCRIPTOR_KEYWORDS = {"항목", "과목", "계정", "구분", "내역", "주석", "note", "notes"}
UNIT_PATTERN = re.compile(r"단위\s*[:：]?\s*([가-힣A-Za-z/$ ]+)")

KOREAN_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    "/System/Library/Fonts/Supplemental/NotoSansGothic-Regular.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/Library/Fonts/NanumGothic.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "C:/Windows/Fonts/malgun.ttf",
]

PAGE_SIZE = landscape(A4)
PAGE_MARGIN = 24
AVAILABLE_TABLE_WIDTH = PAGE_SIZE[0] - (PAGE_MARGIN * 2)
SUMMARY_COLUMN_ORDER = ["지표", "기준", "당기", "전기", "원본 라벨", "비고"]
RATIO_LABEL_KEYWORDS = ("%", "율", "비율", "margin", "ratio", "eps", "bps", "주당", "pershare")


@dataclass
class ExtractedTable:
    statement_type: str
    page: Optional[int]
    df: pd.DataFrame
    basis: Optional[str] = None


class ReportFonts(NamedTuple):
    regular: str
    bold: str


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    display_name: str
    statement_types: tuple[str, ...]
    aliases: tuple[str, ...]


@dataclass
class SummaryMetric:
    key: str
    display_name: str
    statement_type: str
    page: Optional[int]
    unit_label: Optional[str]
    basis: str
    source_label: str
    values: dict[str, float]


KEY_METRIC_DEFINITIONS = (
    MetricDefinition("revenue", "매출액", ("손익계산서",), ("매출액", "영업수익", "수익매출액", "revenue", "sales")),
    MetricDefinition(
        "operating_profit",
        "영업이익",
        ("손익계산서",),
        ("영업이익", "영업손실", "영업이익손실", "operatingincome", "operatingprofit"),
    ),
    MetricDefinition(
        "net_income",
        "당기순이익",
        ("손익계산서",),
        ("당기순이익", "당기순손실", "당기순이익손실", "연결당기순이익", "netincome", "profitfortheyear"),
    ),
    MetricDefinition("total_assets", "자산총계", ("재무상태표",), ("자산총계", "총자산", "totalassets")),
    MetricDefinition("total_liabilities", "부채총계", ("재무상태표",), ("부채총계", "총부채", "totalliabilities")),
    MetricDefinition("total_equity", "자본총계", ("재무상태표",), ("자본총계", "총자본", "totalequity")),
    MetricDefinition(
        "operating_cash_flow",
        "영업활동현금흐름",
        ("현금흐름표",),
        (
            "영업활동으로인한현금흐름",
            "영업활동으로인한순현금흐름",
            "영업활동현금흐름",
            "cashflowsfromoperatingactivities",
            "netcashprovidedbyusedinoperatingactivities",
        ),
    ),
    MetricDefinition(
        "capex_tangible",
        "CAPEX(유형자산)",
        ("현금흐름표",),
        (
            "유형자산의취득",
            "유형자산취득",
            "acquisitionofpropertyplantandequipment",
            "purchaseofpropertyplantandequipment",
        ),
    ),
    MetricDefinition(
        "capex_intangible",
        "CAPEX(무형자산)",
        ("현금흐름표",),
        ("무형자산의취득", "무형자산취득", "acquisitionofintangibleassets", "purchaseofintangibleassets"),
    ),
)
KEY_METRIC_DISPLAY_ORDER = [
    "revenue",
    "operating_profit",
    "net_income",
    "total_assets",
    "total_liabilities",
    "total_equity",
    "operating_cash_flow",
    "capex_tangible",
    "capex_intangible",
    "total_capex",
    "free_cash_flow",
]
REQUIRED_SUMMARY_METRIC_KEYS = {"revenue", "operating_profit", "net_income", "total_equity", "operating_cash_flow", "free_cash_flow"}
METRIC_DISPLAY_NAMES = {definition.key: definition.display_name for definition in KEY_METRIC_DEFINITIONS}
METRIC_DISPLAY_NAMES.update({"total_capex": "총 CAPEX", "free_cash_flow": "잉여현금흐름(FCF)"})


def find_korean_font_path() -> Optional[Path]:
    env_path = os.environ.get("DART_REPORT_FONT_PATH")
    candidates = [env_path] if env_path else []
    candidates.extend(KOREAN_FONT_CANDIDATES)

    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.exists():
            return path
    return None


def register_report_fonts() -> ReportFonts:
    font_path = find_korean_font_path()
    if font_path is None:
        return ReportFonts("Helvetica", "Helvetica-Bold")

    try:
        pdfmetrics.registerFont(TTFont("KoreanRegular", str(font_path)))
    except Exception:
        return ReportFonts("Helvetica", "Helvetica-Bold")

    # A regular Korean font is preferable to Helvetica-Bold, which cannot render Hangul.
    return ReportFonts("KoreanRegular", "KoreanRegular")


def build_report_styles(fonts: ReportFonts) -> dict[str, ParagraphStyle]:
    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName = fonts.regular

    styles["Title"].fontName = fonts.bold
    styles["Title"].fontSize = 18
    styles["Title"].leading = 22
    styles["Heading2"].fontName = fonts.bold
    styles["Heading2"].fontSize = 12
    styles["Heading2"].leading = 15
    styles["Normal"].fontName = fonts.regular
    styles["Normal"].fontSize = 9
    styles["Normal"].leading = 12

    styles.add(
        ParagraphStyle(
            name="TableHeader",
            parent=styles["Normal"],
            fontName=fonts.bold,
            fontSize=7.2,
            leading=8.5,
            wordWrap="CJK",
        )
    )
    styles.add(
        ParagraphStyle(
            name="TableCell",
            parent=styles["Normal"],
            fontName=fonts.regular,
            fontSize=7,
            leading=8.5,
            wordWrap="CJK",
        )
    )
    return styles


def normalize_number_text(text: str) -> str:
    t = str(text).strip()
    if t in {"", "-", "--", "N/A", "nan", "None"}:
        return ""
    t = t.replace(",", "").replace("−", "-")
    t = re.sub(r"^[△▲]", "-", t)
    t = re.sub(r"[원주$₩\s]", "", t)
    # 회계 표기: (1234) -> -1234
    if re.fullmatch(r"\(\s*[-+]?\d+(?:\.\d+)?\s*\)", t):
        t = "-" + t.replace("(", "").replace(")", "").strip()
    return t


def parse_numeric(text: str) -> Optional[float]:
    raw = str(text).strip().replace("−", "-")
    comma_check = re.sub(r"[원주$₩\s]", "", raw)
    comma_check = re.sub(r"^[△▲]", "-", comma_check)
    if "," in comma_check and not re.fullmatch(r"[-+]?\(?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?", comma_check):
        return None
    t = normalize_number_text(text)
    if t == "":
        return None
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", t):
        return float(t)
    return None


def infer_statement_type(df: pd.DataFrame) -> Optional[str]:
    return infer_statement_type_from_text(" ".join(df.fillna("").astype(str).values.flatten()))


def infer_statement_type_from_text(text: str) -> Optional[str]:
    blob = text.lower()
    compact_blob = re.sub(r"\s+", "", blob)
    for stype, keywords in STATEMENT_KEYWORDS.items():
        if any(k.lower() in blob or re.sub(r"\s+", "", k.lower()) in compact_blob for k in keywords):
            return stype
    if any(keyword in compact_blob for keyword in ("기초자본", "기말자본", "자본합계")):
        return "자본변동표"
    if any(keyword in compact_blob for keyword in ("자산총계", "부채총계", "자본총계", "자본과부채총계")):
        return "재무상태표"
    if any(keyword in compact_blob for keyword in ("영업활동현금흐름", "영업활동으로인한현금흐름")):
        return "현금흐름표"
    if any(keyword in compact_blob for keyword in ("매출액", "영업이익", "영업손실", "당기순이익")):
        return "손익계산서"
    return None


def is_financial_statement_continuation(df: pd.DataFrame) -> bool:
    return bool(infer_convertible_columns(df)) and df.shape[0] >= 3 and df.shape[1] >= 3


def detect_unit_label(df: pd.DataFrame) -> Optional[str]:
    blob = " ".join(df.head(5).fillna("").astype(str).values.flatten())
    match = UNIT_PATTERN.search(blob)
    if match:
        return match.group(1).strip()
    return None


def unit_multiplier(unit_label: Optional[str]) -> Optional[float]:
    if unit_label is None:
        return 1.0

    compact = re.sub(r"\s+", "", unit_label)
    if "백만원" in compact or "백만" in compact:
        return 1_000_000.0
    if "천원" in compact:
        return 1_000.0
    if "억원" in compact:
        return 100_000_000.0
    if "원" in compact:
        return 1.0
    return None


def infer_statement_basis(table: ExtractedTable) -> str:
    if table.basis:
        return table.basis
    return infer_statement_basis_from_text(" ".join(table.df.head(5).fillna("").astype(str).values.flatten())) or "별도"


def infer_statement_basis_from_text(text: str) -> Optional[str]:
    compact = re.sub(r"\s+", "", text)
    if "연결" in compact:
        return "연결"
    if "별도" in compact:
        return "별도"
    return None


def table_signature(table: ExtractedTable) -> tuple[str, Optional[int], tuple[int, int], str]:
    first_cells = " ".join(table.df.head(3).fillna("").astype(str).values.flatten()[:12])
    return (table.statement_type, table.page, table.df.shape, first_cells[:120])


def add_extracted_table(
    tables: list[ExtractedTable],
    seen: set[tuple[str, Optional[int], tuple[int, int], str]],
    table: ExtractedTable,
) -> None:
    signature = table_signature(table)
    if signature not in seen:
        seen.add(signature)
        tables.append(table)


def extract_tables(input_pdf: Path, pages: str = "all") -> List[ExtractedTable]:
    tables: List[ExtractedTable] = []
    seen: set[tuple[str, Optional[int], tuple[int, int], str]] = set()
    errors = []
    page_statement_types = {
        page_number: infer_statement_type_from_text(page.extract_text() or "")
        for page_number, page in enumerate(PdfReader(str(input_pdf)).pages, start=1)
    }
    page_statement_bases = {
        page_number: infer_statement_basis_from_text(page.extract_text() or "")
        for page_number, page in enumerate(PdfReader(str(input_pdf)).pages, start=1)
    }

    for flavor in ("stream", "lattice"):
        try:
            import camelot  # type: ignore

            c_tables = camelot.read_pdf(str(input_pdf), pages=pages, flavor=flavor)
            last_page = None
            last_stype = None
            last_basis = None
            for t in c_tables:
                df = t.df
                page = None
                try:
                    page = int(getattr(t, "page", None) or 0)
                except Exception:
                    page = None

                stype = infer_statement_type(df) or page_statement_types.get(page)
                if (
                    stype is None
                    and last_stype is not None
                    and page is not None
                    and last_page is not None
                    and page == last_page + 1
                    and is_financial_statement_continuation(df)
                ):
                    stype = last_stype

                if stype:
                    basis = page_statement_bases.get(page)
                    if (
                        basis is None
                        and last_basis is not None
                        and page is not None
                        and last_page is not None
                        and page == last_page + 1
                        and stype == last_stype
                    ):
                        basis = last_basis
                    add_extracted_table(tables, seen, ExtractedTable(stype, page, df, basis))
                    last_stype = stype
                    last_page = page
                    last_basis = basis
        except Exception as e:  # pragma: no cover
            errors.append(f"camelot({flavor}) error={e}")

    if tables:
        return tables

    try:
        import tabula  # type: ignore

        dfs = tabula.read_pdf(str(input_pdf), pages=pages, multiple_tables=True, lattice=False)
        for df in dfs:
            stype = infer_statement_type(df)
            if stype:
                add_extracted_table(tables, seen, ExtractedTable(stype, None, df))
    except Exception as e:  # pragma: no cover
        errors.append(f"tabula error={e}")

    if not tables and errors:
        raise RuntimeError("표 추출 실패: " + " / ".join(errors))

    return tables


def convert_table_to_per_share(df: pd.DataFrame, shares_outstanding: float, decimals: int = 4) -> pd.DataFrame:
    converted = df.copy()
    convertible_columns = infer_convertible_columns(converted)

    for c in converted.columns:
        new_col = []
        for v in converted[c].tolist():
            n = parse_numeric(str(v))
            if n is None or c not in convertible_columns or is_likely_metadata_number(str(v), n):
                new_col.append(v)
            else:
                per_share = n / shares_outstanding
                new_col.append(f"{per_share:,.{decimals}f}")
        converted[c] = new_col

    return converted


def is_likely_metadata_number(text: str, value: float) -> bool:
    raw = str(text).strip()
    normalized = normalize_number_text(text)
    if raw == normalized and re.fullmatch(r"\d{4}", normalized) and 1900 <= value <= 2100:
        return True
    return False


def infer_convertible_columns(df: pd.DataFrame) -> set[object]:
    convertible = set()

    for idx, col in enumerate(df.columns):
        column_label = clean_cell_text(col).lower()
        values = [clean_cell_text(value) for value in df[col].tolist()]
        value_blob = " ".join(values[:8]).lower()
        if (
            idx == 0
            or any(keyword in column_label for keyword in DESCRIPTOR_KEYWORDS)
            or any(keyword in value_blob for keyword in DESCRIPTOR_KEYWORDS)
            or is_likely_note_column(idx, values)
        ):
            continue

        nonblank = [value for value in values if value]
        numeric_values = [
            parse_numeric(value)
            for value in nonblank
            if parse_numeric(value) is not None and not is_likely_metadata_number(value, parse_numeric(value) or 0)
        ]

        if not nonblank:
            continue

        numeric_density = len(numeric_values) / len(nonblank)
        if len(numeric_values) >= 2 or numeric_density >= 0.45:
            convertible.add(col)

    return convertible


def is_likely_note_column(column_index: int, values: list[str]) -> bool:
    if column_index != 1:
        return False

    nonblank = [value for value in values if value and value != "-"]
    if len(nonblank) < 2:
        return False

    note_like_count = 0
    for value in nonblank:
        if re.fullmatch(r"\d+(?:,\d+)*", value):
            parts = [int(part) for part in value.split(",")]
            if all(0 < part <= 200 for part in parts):
                note_like_count += 1

    return note_like_count / len(nonblank) >= 0.6


def clean_cell_text(value: object) -> str:
    text = str(value if value is not None else "").strip()
    return re.sub(r"\s+", " ", text)


def normalize_metric_label(text: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", clean_cell_text(text).lower())


def is_ratio_like_label(text: str) -> bool:
    normalized = normalize_metric_label(text)
    raw = clean_cell_text(text).lower()
    return any(keyword in raw or keyword in normalized for keyword in RATIO_LABEL_KEYWORDS)


def ordered_convertible_columns(df: pd.DataFrame) -> list[object]:
    convertible = infer_convertible_columns(df)
    return [col for col in df.columns if col in convertible]


def ordered_label_columns(df: pd.DataFrame, value_columns: list[object]) -> list[object]:
    label_columns = []
    for idx, col in enumerate(df.columns):
        if col in value_columns:
            continue
        values = [clean_cell_text(value) for value in df[col].tolist()]
        if is_likely_note_column(idx, values):
            continue
        label_columns.append(col)
    if not label_columns and len(df.columns) > 0:
        label_columns.append(df.columns[0])
    return label_columns


def extract_row_label(row: pd.Series, label_columns: list[object]) -> str:
    for col in label_columns:
        value = clean_cell_text(row.get(col, ""))
        if value and value.lower() not in {keyword.lower() for keyword in DESCRIPTOR_KEYWORDS}:
            return value
    return ""


def period_label_for_column(df: pd.DataFrame, col: object) -> str:
    column_label = clean_cell_text(col)
    if column_label and not column_label.isdigit():
        return column_label

    for value in df[col].head(8).tolist():
        text = clean_cell_text(value)
        compact = re.sub(r"\s+", "", text)
        if not text:
            continue
        if any(token in compact for token in ("당기", "전기", "당기말", "전기말")):
            return text
        if re.fullmatch(r"\d{4}", compact):
            return text

    return column_label or str(col)


def period_bucket(period_label: str) -> Optional[str]:
    compact = re.sub(r"\s+", "", period_label)
    if "당기" in compact or "당기말" in compact:
        return "당기"
    if "전기" in compact or "전기말" in compact:
        return "전기"
    return None


def score_metric_match(label: str, definition: MetricDefinition) -> Optional[int]:
    if is_ratio_like_label(label):
        return None

    normalized_label = normalize_metric_label(label)
    if not normalized_label:
        return None

    best_score = None
    for alias in definition.aliases:
        normalized_alias = normalize_metric_label(alias)
        if normalized_label == normalized_alias:
            score = 300 + len(normalized_alias)
        elif normalized_label.startswith(normalized_alias):
            score = 240 + len(normalized_alias)
        elif normalized_alias in normalized_label:
            score = 200 + len(normalized_alias)
        else:
            continue
        if best_score is None or score > best_score:
            best_score = score
    return best_score


def extract_metric_values(df: pd.DataFrame, row: pd.Series, value_columns: list[object]) -> dict[str, float]:
    values: dict[str, float] = {}
    for col in value_columns:
        raw_value = row.get(col, "")
        parsed = parse_numeric(str(raw_value))
        if parsed is None or is_likely_metadata_number(str(raw_value), parsed):
            continue
        values[period_label_for_column(df, col)] = parsed
    return values


def format_per_share(value: float, decimals: int) -> str:
    return f"{value:,.{decimals}f}"


def format_amount(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def format_metric_source(metric: SummaryMetric) -> str:
    page = f" p.{metric.page}" if metric.page else ""
    return f"{metric.statement_type}{page} / {metric.source_label}"


def metric_period_values(metric: SummaryMetric, shares_outstanding: float, decimals: int) -> tuple[str, str, str]:
    multiplier = unit_multiplier(metric.unit_label)
    if multiplier is None:
        return "", "", f"단위 판별 불가: {metric.unit_label}"

    values_by_bucket: dict[str, float] = {}
    for period, amount in metric.values.items():
        bucket = period_bucket(period)
        if bucket and bucket not in values_by_bucket:
            values_by_bucket[bucket] = amount

    if not values_by_bucket:
        labels = list(metric.values)
        if labels:
            values_by_bucket["당기"] = metric.values[labels[0]]
        if len(labels) > 1:
            values_by_bucket["전기"] = metric.values[labels[1]]

    note = f"원본 단위: {metric.unit_label or '원'}"
    current = values_by_bucket.get("당기")
    prior = values_by_bucket.get("전기")
    current_text = format_per_share(current * multiplier / shares_outstanding, decimals) if current is not None else ""
    prior_text = format_per_share(prior * multiplier / shares_outstanding, decimals) if prior is not None else ""
    return current_text, prior_text, note


def build_summary_metric(
    definition: MetricDefinition,
    table: ExtractedTable,
    label: str,
    values: dict[str, float],
) -> SummaryMetric:
    return SummaryMetric(
        key=definition.key,
        display_name=definition.display_name,
        statement_type=table.statement_type,
        page=table.page,
        unit_label=detect_unit_label(table.df),
        basis=infer_statement_basis(table),
        source_label=label,
        values=values,
    )


def should_replace_metric(existing: SummaryMetric, existing_score: int, candidate: SummaryMetric, candidate_score: int) -> bool:
    existing_rank = (existing_score, len(existing.values), 1 if existing.page is not None else 0)
    candidate_rank = (candidate_score, len(candidate.values), 1 if candidate.page is not None else 0)
    return candidate_rank > existing_rank


def derive_composite_metrics(metrics: dict[str, SummaryMetric]) -> dict[str, SummaryMetric]:
    derived = dict(metrics)
    capex_sources = [metrics.get("capex_tangible"), metrics.get("capex_intangible")]
    present_capex_sources = [metric for metric in capex_sources if metric is not None]

    if present_capex_sources:
        total_capex_values: dict[str, float] = {}
        ordered_periods = []
        for metric in present_capex_sources:
            for period in metric.values:
                if period not in ordered_periods:
                    ordered_periods.append(period)

        for period in ordered_periods:
            total = 0.0
            found = False
            for metric in present_capex_sources:
                if period in metric.values:
                    total += abs(metric.values[period])
                    found = True
            if found:
                total_capex_values[period] = total

        first_source = present_capex_sources[0]
        if total_capex_values:
            derived["total_capex"] = SummaryMetric(
                key="total_capex",
                display_name="총 CAPEX",
                statement_type="현금흐름표",
                page=first_source.page,
                unit_label=first_source.unit_label,
                basis=first_source.basis,
                source_label="유형자산의 취득 + 무형자산의 취득",
                values=total_capex_values,
            )

    operating_cash_flow = metrics.get("operating_cash_flow")
    total_capex = derived.get("total_capex")
    if operating_cash_flow and total_capex:
        free_cash_flow_values = {
            period: amount - total_capex.values[period]
            for period, amount in operating_cash_flow.values.items()
            if period in total_capex.values
        }
        if free_cash_flow_values:
            derived["free_cash_flow"] = SummaryMetric(
                key="free_cash_flow",
                display_name="잉여현금흐름(FCF)",
                statement_type="현금흐름표",
                page=operating_cash_flow.page,
                unit_label=operating_cash_flow.unit_label or total_capex.unit_label,
                basis=operating_cash_flow.basis,
                source_label="영업활동현금흐름 - 총 CAPEX",
                values=free_cash_flow_values,
            )

    return derived


def extract_key_metrics(tables: Iterable[ExtractedTable]) -> dict[str, SummaryMetric]:
    metrics: dict[str, SummaryMetric] = {}
    scores: dict[str, int] = {}

    for table in tables:
        value_columns = ordered_convertible_columns(table.df)
        if not value_columns:
            continue

        label_columns = ordered_label_columns(table.df, value_columns)
        for _, row in table.df.iterrows():
            label = extract_row_label(row, label_columns)
            if not label:
                continue

            values = extract_metric_values(table.df, row, value_columns)
            if not values:
                continue

            for definition in KEY_METRIC_DEFINITIONS:
                if table.statement_type not in definition.statement_types:
                    continue

                score = score_metric_match(label, definition)
                if score is None:
                    continue

                candidate = build_summary_metric(definition, table, label, values)
                existing = metrics.get(definition.key)
                existing_score = scores.get(definition.key)
                if existing is None or existing_score is None or should_replace_metric(existing, existing_score, candidate, score):
                    metrics[definition.key] = candidate
                    scores[definition.key] = score

    return derive_composite_metrics(metrics)


def build_key_metrics_summary_dataframe(
    tables: Iterable[ExtractedTable],
    shares_outstanding: float,
    decimals: int = 4,
) -> pd.DataFrame:
    metrics = extract_key_metrics(tables)
    rows = []

    for metric_key in KEY_METRIC_DISPLAY_ORDER:
        metric = metrics.get(metric_key)
        if metric is None:
            if metric_key in REQUIRED_SUMMARY_METRIC_KEYS:
                rows.append(
                    {
                        "지표": METRIC_DISPLAY_NAMES.get(metric_key, metric_key),
                        "기준": "-",
                        "당기": "",
                        "전기": "",
                        "원본 라벨": "",
                        "비고": "지표 미식별",
                    }
                )
            continue

        current_text, prior_text, note = metric_period_values(metric, shares_outstanding, decimals)
        rows.append(
            {
                "지표": metric.display_name,
                "기준": metric.basis,
                "당기": current_text,
                "전기": prior_text,
                "원본 라벨": metric.source_label,
                "비고": f"{note}; {format_metric_source(metric)}",
            }
        )

    return pd.DataFrame(rows, columns=SUMMARY_COLUMN_ORDER)


def paragraph_cell(value: object, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(clean_cell_text(value)), style)


def calculate_column_widths(df: pd.DataFrame, available_width: float = AVAILABLE_TABLE_WIDTH) -> list[float]:
    if df.empty:
        return [available_width]

    sample = df.head(30).fillna("").astype(str)
    weights = []
    for col in df.columns:
        values = [str(col), *sample[col].tolist()]
        longest = max((len(clean_cell_text(v)) for v in values), default=1)
        weights.append(min(max(longest, 6), 28))

    if weights:
        weights[0] = min(weights[0] * 1.4, 34)

    total = sum(weights) or 1
    return [available_width * (weight / total) for weight in weights]


def dataframe_to_reportlab_table(
    df: pd.DataFrame,
    styles: dict[str, ParagraphStyle],
    fonts: ReportFonts,
) -> LongTable:
    header = [paragraph_cell(col, styles["TableHeader"]) for col in df.columns]
    body = [
        [paragraph_cell(value, styles["TableCell"]) for value in row]
        for row in df.fillna("").astype(str).values.tolist()
    ]
    data = [header] + body

    tbl = LongTable(data, colWidths=calculate_column_widths(df), repeatRows=1, splitByRow=True)
    style = TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF7")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#B8C2CC")),
            ("FONTNAME", (0, 0), (-1, 0), fonts.bold),
            ("FONTNAME", (0, 1), (-1, -1), fonts.regular),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ]
    )
    tbl.setStyle(style)
    return tbl


def build_converted_pdf(tables: Iterable[ExtractedTable], output_pdf: Path, shares_outstanding: float, decimals: int) -> None:
    table_list = list(tables)
    fonts = register_report_fonts()
    styles = build_report_styles(fonts)
    story = []

    story.append(Paragraph("주당 환산 재무제표", styles["Title"]))
    story.append(Spacer(1, 12))
    story.append(
        Paragraph(
            f"환산 기준 발행주식수: {shares_outstanding:,.0f}주 / 소수점 {decimals}자리",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 16))

    for idx, t in enumerate(table_list, start=1):
        heading = f"{idx}. {t.statement_type}" + (f" (원본 page: {t.page})" if t.page else "")
        unit_label = detect_unit_label(t.df)
        if unit_label:
            heading += f" / 원본 단위: {unit_label}"
        story.append(Paragraph(heading, styles["Heading2"]))
        converted = convert_table_to_per_share(t.df, shares_outstanding, decimals=decimals)
        story.append(dataframe_to_reportlab_table(converted, styles, fonts))
        story.append(Spacer(1, 18))

    story.append(PageBreak())
    story.append(Paragraph("주당 핵심 지표 요약", styles["Title"]))
    story.append(Spacer(1, 12))
    story.append(
        Paragraph(
            "원본 값은 추출된 DART 표의 공시 단위를 유지하며, FCF는 영업활동현금흐름에서 CAPEX를 차감해 계산합니다.",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 12))

    summary_df = build_key_metrics_summary_dataframe(table_list, shares_outstanding, decimals=decimals)
    if summary_df.empty:
        story.append(Paragraph("핵심 지표 요약에 사용할 행을 식별하지 못했습니다.", styles["Normal"]))
    else:
        story.append(dataframe_to_reportlab_table(summary_df, styles, fonts))

    doc = SimpleDocTemplate(
        str(output_pdf),
        pagesize=PAGE_SIZE,
        leftMargin=PAGE_MARGIN,
        rightMargin=PAGE_MARGIN,
        topMargin=PAGE_MARGIN,
        bottomMargin=PAGE_MARGIN,
    )
    doc.build(story)


def merge_original_and_converted(original_pdf: Path, converted_pdf: Path, final_output_pdf: Path) -> None:
    writer = PdfWriter()

    for p in PdfReader(str(original_pdf)).pages:
        writer.add_page(p)
    for p in PdfReader(str(converted_pdf)).pages:
        writer.add_page(p)

    with final_output_pdf.open("wb") as f:
        writer.write(f)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DART 사업보고서 PDF의 주요 재무제표 숫자를 주당 값으로 환산한 새 PDF 생성"
    )
    parser.add_argument("input_pdf", type=Path, help="입력 사업보고서 PDF 경로")
    parser.add_argument("output_pdf", type=Path, help="출력 PDF 경로")
    parser.add_argument(
        "--shares-outstanding",
        type=float,
        required=True,
        help="환산에 사용할 발행주식수 (예: 596978255)",
    )
    parser.add_argument("--pages", default="all", help='표 추출 대상 페이지 (예: "1-120" 또는 "all")')
    parser.add_argument("--decimals", type=int, default=4, help="주당 값 소수점 자리수 (기본 4)")
    args = parser.parse_args()

    if not args.input_pdf.exists():
        raise FileNotFoundError(f"입력 PDF를 찾을 수 없습니다: {args.input_pdf}")
    if args.shares_outstanding <= 0:
        raise ValueError("--shares-outstanding 값은 0보다 커야 합니다.")

    extracted = extract_tables(args.input_pdf, pages=args.pages)
    if not extracted:
        raise RuntimeError("주요 재무제표 표를 찾지 못했습니다. --pages 범위 또는 PDF 품질을 확인하세요.")

    temp_converted = args.output_pdf.with_suffix(".converted_only.pdf")
    try:
        build_converted_pdf(extracted, temp_converted, args.shares_outstanding, args.decimals)
        merge_original_and_converted(args.input_pdf, temp_converted, args.output_pdf)
    finally:
        temp_converted.unlink(missing_ok=True)

    print(f"완료: {args.output_pdf}")


if __name__ == "__main__":
    main()
