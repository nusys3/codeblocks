import unittest

import pandas as pd

from dart_per_share_report import (
    ExtractedTable,
    build_key_metrics_summary_dataframe,
    convert_table_to_per_share,
    extract_key_metrics,
    infer_statement_type,
    infer_convertible_columns,
    parse_numeric,
)


class PerShareConversionTests(unittest.TestCase):
    def test_infer_statement_type_accepts_spaced_korean_pdf_titles(self):
        self.assertEqual(infer_statement_type(pd.DataFrame([["연 결 재 무 상 태 표"]])), "재무상태표")
        self.assertEqual(infer_statement_type(pd.DataFrame([["연 결 자 본 변 동 표"]])), "자본변동표")
        self.assertEqual(infer_statement_type(pd.DataFrame([["연 결 현 금 흐 름 표"]])), "현금흐름표")
        self.assertEqual(infer_statement_type(pd.DataFrame([["자본총계", "1,000", "900"]])), "재무상태표")
        self.assertEqual(infer_statement_type(pd.DataFrame([["2024.01.01 (기초자본)", "당기순이익", "1,000"]])), "자본변동표")
        self.assertEqual(infer_statement_type(pd.DataFrame([["영업활동현금흐름", "당기순이익", "1,000"]])), "현금흐름표")

    def test_parse_numeric_accepts_common_korean_accounting_markers(self):
        self.assertEqual(parse_numeric("△1,000원"), -1000.0)
        self.assertEqual(parse_numeric("−500"), -500.0)
        self.assertEqual(parse_numeric("(250)"), -250.0)
        self.assertIsNone(parse_numeric("5,6,7"))

    def test_conversion_skips_descriptor_note_and_year_metadata(self):
        df = pd.DataFrame(
            {
                "항목": ["단위: 백만원", "자산총계", "부채총계", "연도"],
                "주석": ["1", "2", "3", "4"],
                "2025": ["2025", "1,234,000", "(500)", "2025"],
                "2024": ["2024", "△1,000", "2,000원", "2024"],
            }
        )

        self.assertEqual(infer_convertible_columns(df), {"2025", "2024"})

        converted = convert_table_to_per_share(df, shares_outstanding=1000, decimals=2)
        self.assertEqual(converted.loc[0, "2025"], "2025")
        self.assertEqual(converted.loc[0, "2024"], "2024")
        self.assertEqual(converted.loc[1, "2025"], "1,234.00")
        self.assertEqual(converted.loc[1, "2024"], "-1.00")
        self.assertEqual(converted.loc[2, "2025"], "-0.50")
        self.assertEqual(converted.loc[2, "2024"], "2.00")
        self.assertEqual(converted.loc[1, "주석"], "2")

    def test_conversion_skips_extracted_note_column_when_headers_are_rows(self):
        df = pd.DataFrame(
            [
                ["과 목", "주석", "제 11(당)기말", "제 10(전)기말"],
                ["현금및현금성자산", "5,6,7", "12,999,036,704", "2,813,114,310"],
                ["자산총계", "", "52,872,801,503", "24,936,401,276"],
            ]
        )

        converted = convert_table_to_per_share(df, shares_outstanding=596978255, decimals=4)

        self.assertEqual(converted.loc[1, 1], "5,6,7")
        self.assertEqual(converted.loc[1, 2], "21.7747")
        self.assertEqual(converted.loc[1, 3], "4.7123")

    def test_conversion_skips_note_column_on_continued_tables_without_header(self):
        df = pd.DataFrame(
            [
                ["기타비유동부채", "17", "17,224,508", "215,885,101"],
                ["비유동충당부채", "23", "72,116,095", "97,511,947"],
                ["이연법인세부채", "22", "7,668,603", "24,335,524"],
            ]
        )

        converted = convert_table_to_per_share(df, shares_outstanding=596978255, decimals=4)

        self.assertEqual(converted.loc[0, 1], "17")
        self.assertEqual(converted.loc[0, 2], "0.0289")

    def test_extract_key_metrics_derives_free_cash_flow_from_cash_flow_rows(self):
        income_statement = ExtractedTable(
            statement_type="손익계산서",
            page=3,
            df=pd.DataFrame(
                {
                    "과목": ["매출액", "영업이익", "당기순이익"],
                    "주석": ["1", "2", "3"],
                    "2025": ["1,000", "150", "120"],
                    "2024": ["900", "100", "80"],
                }
            ),
        )
        balance_sheet = ExtractedTable(
            statement_type="재무상태표",
            page=2,
            df=pd.DataFrame(
                {
                    "과목": ["자산총계", "부채총계", "자본총계"],
                    "2025": ["2,000", "800", "1,200"],
                    "2024": ["1,900", "750", "1,150"],
                }
            ),
        )
        cash_flow_statement = ExtractedTable(
            statement_type="현금흐름표",
            page=4,
            df=pd.DataFrame(
                {
                    "과목": ["영업활동으로 인한 현금흐름", "유형자산의 취득", "무형자산의 취득"],
                    "2025": ["500", "(120)", "(30)"],
                    "2024": ["380", "(90)", "(15)"],
                }
            ),
        )

        metrics = extract_key_metrics([income_statement, balance_sheet, cash_flow_statement])

        self.assertEqual(metrics["revenue"].values, {"2025": 1000.0, "2024": 900.0})
        self.assertEqual(metrics["operating_cash_flow"].values, {"2025": 500.0, "2024": 380.0})
        self.assertEqual(metrics["total_capex"].values, {"2025": 150.0, "2024": 105.0})
        self.assertEqual(metrics["free_cash_flow"].values, {"2025": 350.0, "2024": 275.0})

        summary = build_key_metrics_summary_dataframe(
            [income_statement, balance_sheet, cash_flow_statement],
            shares_outstanding=100,
            decimals=2,
        )
        free_cash_flow_rows = summary[summary["지표"] == "잉여현금흐름(FCF)"]

        self.assertEqual(free_cash_flow_rows.iloc[0]["당기"], "3.50")
        self.assertEqual(free_cash_flow_rows.iloc[0]["전기"], "2.75")
        self.assertEqual(free_cash_flow_rows.iloc[0]["기준"], "별도")
        self.assertIn("원본 단위: 원", free_cash_flow_rows.iloc[0]["비고"])
        self.assertIn("현금흐름표 p.4", free_cash_flow_rows.iloc[0]["비고"])

    def test_extract_key_metrics_skips_ratio_like_labels(self):
        income_statement = ExtractedTable(
            statement_type="손익계산서",
            page=7,
            df=pd.DataFrame(
                {
                    "과목": ["매출액", "영업이익률", "영업이익", "당기순이익"],
                    "2025": ["2,400", "15.2", "360", "300"],
                    "2024": ["2,100", "12.0", "252", "220"],
                }
            ),
        )

        metrics = extract_key_metrics([income_statement])

        self.assertEqual(metrics["operating_profit"].values, {"2025": 360.0, "2024": 252.0})
        self.assertEqual(metrics["revenue"].values, {"2025": 2400.0, "2024": 2100.0})

    def test_summary_uses_header_rows_for_periods_and_normalizes_unit_to_won_per_share(self):
        income_statement = ExtractedTable(
            statement_type="손익계산서",
            page=9,
            df=pd.DataFrame(
                [
                    ["연 결 포 괄 손 익 계 산 서", "", "", ""],
                    ["주식회사 테스트", "", "", "(단위: 백만원)"],
                    ["과 목", "주석", "제 11(당) 기", "제 10(전) 기"],
                    ["매출액", "28", "1,000", "900"],
                    ["영업이익", "29", "150", "100"],
                    ["당기순이익", "", "120", "80"],
                ]
            ),
        )

        summary = build_key_metrics_summary_dataframe([income_statement], shares_outstanding=100, decimals=2)
        revenue_row = summary[summary["지표"] == "매출액"].iloc[0]

        self.assertEqual(revenue_row["기준"], "연결")
        self.assertEqual(revenue_row["당기"], "10,000,000.00")
        self.assertEqual(revenue_row["전기"], "9,000,000.00")
        self.assertEqual(revenue_row["원본 라벨"], "매출액")
        self.assertIn("원본 단위: 백만원", revenue_row["비고"])

    def test_unit_detection_stops_at_closing_parenthesis(self):
        table = ExtractedTable(
            statement_type="손익계산서",
            page=1,
            df=pd.DataFrame([["(단위 : 원) 제 52 기"], ["매출액", "1,000"]]),
        )

        summary = build_key_metrics_summary_dataframe([table], shares_outstanding=100, decimals=2)
        revenue_row = summary[summary["지표"] == "매출액"].iloc[0]

        self.assertIn("원본 단위: 원", revenue_row["비고"])
        self.assertNotIn("원) 제", revenue_row["비고"])


if __name__ == "__main__":
    unittest.main()
