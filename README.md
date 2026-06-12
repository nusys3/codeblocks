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

## 경제·투자 이벤트 타임라인 로컬 웹페이지

KDI 경제정책 시계열서비스의 `주제별 보기 → 시계열 화면 → 상세 화면` 흐름을 참고해 만든 정적 웹페이지입니다.

### 실행

Node.js/npm이 없어도 실행되도록 Python 실행 스크립트를 기본 실행 방법으로 제공합니다.

```bash
python3 serve_timeline.py
```

브라우저가 자동으로 열리지 않으면 <http://127.0.0.1:8000> 을 열면 됩니다. macOS에서는 `serve_economic_timeline.command` 파일을 더블클릭해도 실행할 수 있습니다.

npm을 사용하는 경우에는 아래 명령도 가능합니다.

```bash
npm run serve:timeline
```

> `npm error code ENOENT` 또는 `Could not read package.json`가 나오면 현재 터미널 위치에 `package.json`이 없다는 뜻입니다. 저장소 최신 변경사항을 받은 뒤 저장소 루트에서 실행하거나, npm 대신 `python3 serve_timeline.py`를 사용하세요.

### 주요 기능

- 주제별 1·2·3단계 필터: 거시경제/통화, 파생·만기, IPO·상장, 주식 발행·기업 이벤트
- 연도, 검색어, 확정도(확정/조건부/관찰) 필터
- 이벤트 상세 모달: 투자자 체크포인트, 설명, 출처 링크 표시
- JSON 내보내기/불러오기: 향후 IPO 공모가, 발행 주식 수, 확정 일정이 바뀔 때 로컬 데이터 교체 가능

### 데이터 기준

초기 데이터의 기준일은 2026-06-11입니다. FOMC, 한국은행, 일본은행, KRX/CME 파생 만기 규칙, SpaceX/OpenAI/Anthropic의 IPO 관련 공개 자료를 바탕으로 시드 데이터를 구성했습니다. IPO나 주식 발행 일정은 최종 투자설명서 및 거래소/SEC 공시로 변동될 수 있습니다.
