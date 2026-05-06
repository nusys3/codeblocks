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
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

import pandas as pd
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


STATEMENT_KEYWORDS = {
    "재무상태표": ["재무상태표", "재무 상태표", "balance sheet"],
    "손익계산서": ["손익계산서", "포괄손익계산서", "income statement"],
    "현금흐름표": ["현금흐름표", "cash flow"],
}


@dataclass
class ExtractedTable:
    statement_type: str
    page: Optional[int]
    df: pd.DataFrame


def normalize_number_text(text: str) -> str:
    t = str(text).strip()
    if t in {"", "-", "--", "N/A", "nan", "None"}:
        return ""
    t = t.replace(",", "")
    # 회계 표기: (1234) -> -1234
    if re.fullmatch(r"\(\s*[-+]?\d+(?:\.\d+)?\s*\)", t):
        t = "-" + t.replace("(", "").replace(")", "").strip()
    return t


def parse_numeric(text: str) -> Optional[float]:
    t = normalize_number_text(text)
    if t == "":
        return None
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", t):
        return float(t)
    return None


def infer_statement_type(df: pd.DataFrame) -> Optional[str]:
    blob = " ".join(df.fillna("").astype(str).values.flatten()).lower()
    for stype, keywords in STATEMENT_KEYWORDS.items():
        if any(k.lower() in blob for k in keywords):
            return stype
    return None


def extract_tables(input_pdf: Path, pages: str = "all") -> List[ExtractedTable]:
    tables: List[ExtractedTable] = []

    # 1) camelot 우선
    camelot_err = None
    try:
        import camelot  # type: ignore

        c_tables = camelot.read_pdf(str(input_pdf), pages=pages, flavor="stream")
        for t in c_tables:
            df = t.df
            stype = infer_statement_type(df)
            if stype:
                page = None
                try:
                    page = int(getattr(t, "page", None) or 0)
                except Exception:
                    page = None
                tables.append(ExtractedTable(stype, page, df))
    except Exception as e:  # pragma: no cover
        camelot_err = e

    if tables:
        return tables

    # 2) tabula 백업
    try:
        import tabula  # type: ignore

        dfs = tabula.read_pdf(str(input_pdf), pages=pages, multiple_tables=True, lattice=False)
        for df in dfs:
            stype = infer_statement_type(df)
            if stype:
                tables.append(ExtractedTable(stype, None, df))
    except Exception as e:  # pragma: no cover
        if camelot_err is not None:
            raise RuntimeError(
                "표 추출 실패: camelot/tabula 모두 실패했습니다. "
                f"camelot error={camelot_err}, tabula error={e}"
            ) from e
        raise RuntimeError(f"표 추출 실패: tabula error={e}") from e

    return tables


def convert_table_to_per_share(df: pd.DataFrame, shares_outstanding: float, decimals: int = 4) -> pd.DataFrame:
    converted = df.copy()

    for c in converted.columns:
        new_col = []
        for v in converted[c].tolist():
            n = parse_numeric(str(v))
            if n is None:
                new_col.append(v)
            else:
                per_share = n / shares_outstanding
                new_col.append(f"{per_share:,.{decimals}f}")
        converted[c] = new_col

    return converted


def dataframe_to_reportlab_table(df: pd.DataFrame) -> Table:
    data = [list(df.columns)] + df.fillna("").astype(str).values.tolist()
    tbl = Table(data, repeatRows=1)
    style = TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]
    )
    tbl.setStyle(style)
    return tbl


def build_converted_pdf(tables: Iterable[ExtractedTable], output_pdf: Path, shares_outstanding: float, decimals: int) -> None:
    styles = getSampleStyleSheet()
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

    for idx, t in enumerate(tables, start=1):
        heading = f"{idx}. {t.statement_type}" + (f" (원본 page: {t.page})" if t.page else "")
        story.append(Paragraph(heading, styles["Heading2"]))
        converted = convert_table_to_per_share(t.df, shares_outstanding, decimals=decimals)
        story.append(dataframe_to_reportlab_table(converted))
        story.append(Spacer(1, 18))

    doc = SimpleDocTemplate(
        str(output_pdf),
        pagesize=landscape(A4),
        leftMargin=24,
        rightMargin=24,
        topMargin=24,
        bottomMargin=24,
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
    build_converted_pdf(extracted, temp_converted, args.shares_outstanding, args.decimals)
    merge_original_and_converted(args.input_pdf, temp_converted, args.output_pdf)
    temp_converted.unlink(missing_ok=True)

    print(f"완료: {args.output_pdf}")


if __name__ == "__main__":
    main()
