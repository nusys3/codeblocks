# codeblocks

DART 공시 사업보고서 PDF에서 **주요 재무제표 숫자**를 **주당(per-share)** 값으로 환산해,
원본 뒤에 환산 결과를 붙인 새 PDF를 만드는 스크립트입니다.

## 파일
- `dart_per_share_report.py`

## 설치
```bash
pip install pandas pypdf reportlab camelot-py tabula-py
```

> 참고:
> - `camelot-py`는 시스템에 따라 Ghostscript가 필요할 수 있습니다.
> - `tabula-py`는 Java 런타임이 필요합니다.

## 사용법
```bash
python dart_per_share_report.py \
  ./input_report.pdf \
  ./output_report_per_share.pdf \
  --shares-outstanding 596978255 \
  --pages "1-200" \
  --decimals 4
```

## 동작 방식
1. PDF 표 추출 (Camelot 우선, 실패 시 Tabula)
2. 재무상태표/손익계산서/현금흐름표 키워드 기반 선별
3. 숫자 셀을 발행주식수로 나눠 주당 값으로 변환
4. 원본 PDF + 환산 결과 PDF 병합

## 주의
- 스캔 품질이나 표 구조가 복잡한 PDF에서는 표 추출 정확도가 떨어질 수 있습니다.
- 본 스크립트는 원문 본문을 직접 다시 조판하는 방식이 아니라,
  **원본 PDF는 그대로 유지하고 환산 페이지를 뒤에 추가**합니다.
