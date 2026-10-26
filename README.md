# IR RAG Assistant

기업 IR 자료와 DART 사업보고서를 검색하고, 같은 질문에 대한 답변을 자료 종류별로 비교하는 학습용 프로젝트입니다.

## 주요 기능

- 회사별 PDF 등록 및 IR·사업보고서 분류
- OpenAI 임베딩을 이용한 의미 검색과 키 없이 가능한 단어 검색
- 검색 근거에 기반한 요약, 원문 인용문 일치 검사
- IR 자료와 사업보고서를 각각 검색·요약하여 비교
- PDF 근거 페이지 팝업과 인용문 하이라이트
- OpenDART에서 최신 대상 사업기간의 최종 연간 사업보고서 가져오기
- 단계별 설명과 한글 주석을 포함한 Jupyter 노트북

## 앱 실행

Python 3.10 이상이 필요합니다.

```sh
git clone https://github.com/chie3333/ir-rag-assistant.git
cd ir-rag-assistant
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-app.txt
.venv/bin/python app.py
```

Mac에서는 `IR검색_실행.command`를 더블클릭해 실행할 수도 있습니다. 실행한 터미널에서 `Control+C`를 누르면 종료됩니다.

처음에는 등록된 자료가 없습니다. 왼쪽에서 회사명과 PDF를 등록하세요. 원본 자료나 개인 캐시는 저장소에 포함하지 않습니다.

## 사용 방법

1. **PDF 추가하기**에서 회사명, 자료 종류, PDF를 등록합니다.
2. **검색에 사용할 자료**에서 `IR + 사업보고서`, `IR 자료만`, `사업보고서만`을 선택합니다.
3. **OpenAI API 키**를 입력하고 질문합니다. 의미 검색은 임베딩을 만든 뒤 관련 근거로 요약합니다.
4. IR과 사업보고서를 둘 다 선택하면 각 자료만을 근거로 한 별도 답변을 비교할 수 있습니다.
5. 답변 아래 근거를 펼치고 **원문 팝업으로 보기**로 원문을 확인합니다.

OpenAI 키 없이 **원문만 미리보기**로 단어 검색과 PDF 페이지 보기를 확인할 수 있습니다. 이 기능은 AI 요약을 만들지 않습니다.

### 최신 사업보고서

별도의 OpenDART 인증키가 필요합니다.

1. **최신 사업보고서 가져오기**에서 OpenDART 키를 입력합니다.
2. 회사명 또는 종목코드를 검색하고 정확한 회사를 선택합니다.
3. **최신 사업보고서 등록**을 누릅니다.

최근 5년의 최종 연간 사업보고서 목록에서 가장 최근 대상 사업기간을 선택하고, 같은 기간이면 최근 정정본을 선택합니다. 분기·반기보고서는 제외합니다. XML 원본에서 항목별 텍스트를 추출하며, PDF 쪽수 대신 공시 항목명과 DART 원문 링크를 표시합니다. 다시 등록해야 최신 여부를 재확인합니다.

## 학습용 노트북

```sh
.venv/bin/python -m pip install -r requirements-rag.txt
.venv/bin/jupyter lab pipeline/ir_rag.ipynb
```

- `pipeline/ir_rag.ipynb`: PDF 추출 → 임베딩 → 검색 → 자료별 요약 → 원문 팝업
- `pipeline/compare_ir.ipynb`: 이전·이후 PDF 페이지 매칭 실험

노트북 실행 결과와 위젯 상태는 저장소에서 제거했습니다. 위에서 아래로 셀을 실행하세요.

이전·이후 비교 실험을 하려면 `data/manifest.example.json`을 `data/manifest.json`으로 복사하고, 본인 PDF의 경로와 날짜를 수정하세요. 예제에 적힌 PDF는 직접 준비해야 합니다. 앱의 **넥스틴 예제 불러오기**도 이 로컬 목록과 PDF가 있을 때만 사용할 수 있습니다.

## 구조

```text
app.py                       # Streamlit 화면 및 실행 진입점
rag_core.py                  # PDF 처리, 임베딩, 검색, 요약, 인용 검증
dart_client.py               # OpenDART 연결 및 XML 파싱
IR검색_실행.command           # Mac 실행 도우미
pipeline/                    # 학습용 노트북
data/manifest.example.json   # 로컬 자료 목록 예시
.streamlit/config.toml       # 이메일 안내 생략 및 로컬 접속 설정
```

등록 문서·공시 원본·추출 텍스트·임베딩 캐시는 로컬 `data/rag/`에 저장되며 Git에서 제외합니다. API 키는 앱의 숨김 입력 또는 `OPENAI_API_KEY`, `DART_API_KEY` 환경변수로 전달합니다. `.env` 파일을 자동으로 읽는 기능은 없습니다.

## 현재 범위

- 검색 시 관련 근거를 자료 종류별로 최대 24개 고릅니다. 문서 전체의 모든 사실을 수집하는 것은 아닙니다.
- 하이라이트는 원문 페이지 이미지 위에 표시하며 원본 PDF를 수정하지 않습니다.
- 이미지 기반 차트의 의미 분석, 스캔 OCR, 복잡한 표의 완전한 구조 복원은 포함하지 않습니다.
- API 사용 시 문서 텍스트와 질문을 OpenAI로 전송하며 API 비용이 발생할 수 있습니다.
- 대화 이력, 답변 수정 사례의 지속 저장, 자동 주기 갱신은 아직 구현하지 않았습니다.

자세한 안내: [앱 실행 안내](앱_실행안내.md), [노트북 실습 안내](RAG_시작하기.md).
