"""실행: .venv/bin/python -m streamlit run app.py

화면은 이 파일, PDF 처리·검색·OpenAI 연결은 rag_core.py에 있습니다.
"""
from pathlib import Path
import json
import os
import sys

import streamlit as st
from openai import OpenAI, AuthenticationError, RateLimitError, APIConnectionError, APIStatusError
from rag_core import RAGLibrary, PROJECT_DIR, category_label, document_category, paragraph_categories, answer_provenance, clean_summary_text
from dart_client import OpenDart, DartError, company_name_key

# python app.py로 실행해도 Streamlit 화면이 열리도록 실행 방식을 연결합니다.
if __name__ == "__main__":
    from streamlit.runtime.scriptrunner import get_script_run_ctx
    if get_script_run_ctx(suppress_warning=True) is None:
        import socket
        # 이미 앱이 실행 중이면 다른 빈 번호로 열어 충돌을 피합니다.
        port = None
        for candidate in range(8501, 8521):
            with socket.socket() as probe:
                try:
                    probe.bind(("127.0.0.1", candidate))
                except OSError:
                    continue
                port = candidate
                break
        if port is None:
            raise SystemExit("사용할 실행 포트가 없습니다. 기존 IR 앱을 종료한 뒤 다시 실행해주세요.")
        os.execv(sys.executable, [sys.executable, "-m", "streamlit", "run", str(Path(__file__).resolve()),
                                 "--server.address=127.0.0.1", f"--server.port={port}",
                                 "--server.headless=false", "--server.showEmailPrompt=false",
                                 "--browser.gatherUsageStats=false"])

st.set_page_config(page_title="IR 자료에게 물어보기", page_icon="📄", layout="wide")

# 화면을 다시 그릴 때 자료는 디스크에서 읽고, 질문 결과와 키 입력은 현재 세션에만 둡니다.
library = RAGLibrary()
st.title("IR 자료에게 물어보기")
st.caption("질문과 관련된 자료를 찾아 요약하고, 실제 원문과 근거 페이지를 함께 보여드려요.")

with st.sidebar:
    st.header("내 IR 자료")
    with st.expander("PDF 추가하기", expanded=not library.registry):
        with st.form("upload_form", clear_on_submit=True):
            upload_company = st.text_input("회사명", placeholder="예: 넥스틴")
            upload_kind = st.selectbox("PDF 자료 종류", ["IR 자료", "사업보고서"])
            uploaded = st.file_uploader("IR PDF 선택", type=["pdf"], accept_multiple_files=True)
            add = st.form_submit_button("자료 등록", width="stretch")
        if add:
            if not upload_company.strip() or not uploaded:
                st.warning("회사명과 PDF를 함께 입력해주세요.")
            else:
                with st.spinner("PDF를 읽는 중…"):
                    success = 0
                    for file in uploaded:
                        try:
                            doc = library.register_pdf(file.getvalue(), file.name, upload_company, document_kind="annual_report" if upload_kind == "사업보고서" else "ir")
                            success += 1
                            if doc["image_only_pages"]:
                                st.warning(f"{doc['name']}: 글자가 없는 {len(doc['image_only_pages'])}쪽은 텍스트 검색에서 제외돼요.")
                        except (ValueError, OSError) as error:
                            st.warning(f"{file.name}: {error}")
                        except Exception:
                            st.warning(f"{file.name}: 읽을 수 없는 PDF입니다. 암호 또는 파일 손상을 확인해주세요.")
                if success:
                    st.success(f"{success}개 자료를 등록했어요. 같은 파일은 중복 저장하지 않아요.")

    if st.button("넥스틴 예제 불러오기", width="stretch"):
        manifest_path = PROJECT_DIR / "data/manifest.json"
        if not manifest_path.exists():
            st.warning("예제 목록이 없습니다. PDF를 직접 등록해주세요.")
        else:
            with st.spinner("예제 자료를 등록하는 중…"):
                failed = 0
                for item in json.loads(manifest_path.read_text())["documents"]:
                    path = Path(item["path"])
                    try:
                        library.register_pdf(path.read_bytes(), path.name, "넥스틴")
                    except Exception:
                        failed += 1
                if failed:
                    st.warning(f"{failed}개 파일을 읽지 못했습니다. 다운로드 폴더의 원본 경로를 확인해주세요.")
                else:
                    st.success("넥스틴 예제 6개가 준비됐어요.")

    with st.expander("최신 사업보고서 가져오기"):
        st.caption("DART에서 최신 연간 사업보고서를 찾아 IR 자료와 함께 등록해요. 분기·반기보고서는 제외해요.")
        dart_key_input = st.text_input("OpenDART API 키", type="password", key="dart_api_key_input")
        dart_key = dart_key_input.strip() or os.getenv("DART_API_KEY", "")
        st.caption("OpenAI 키와 다른 인증키예요. 파일에 저장하지 않아요.")
        st.link_button("DART 인증키 발급 안내", "https://opendart.fss.or.kr/")
        dart_query = st.text_input("DART 회사명 또는 종목코드", value=st.session_state.get("company_select") or "넥스틴")
        if st.button("DART 회사 찾기", disabled=not dart_key):
            try:
                with st.spinner("DART 회사 목록을 확인하는 중…"):
                    connector = OpenDart(dart_key, library.data_dir / "dart_cache")
                    st.session_state["dart_candidates"] = connector.search_companies(dart_query)
                if not st.session_state["dart_candidates"]:
                    st.info("일치하는 회사를 찾지 못했어요.")
            except DartError as error:
                st.warning(str(error))
        candidates = st.session_state.get("dart_candidates", [])
        if candidates:
            chosen = st.selectbox("DART에서 확인한 회사", candidates,
                                  format_func=lambda row: f"{row['corp_name']} ({row['stock_code'] or row['corp_code']})")
            if st.button("최신 사업보고서 등록", disabled=not dart_key, type="primary"):
                try:
                    with st.spinner("최신 사업연도·정정 내역을 확인하고 본문을 읽는 중…"):
                        connector = OpenDart(dart_key, library.data_dir / "dart_cache")
                        report = connector.latest_annual_report(chosen["corp_code"])
                        # 기존 회사의 이름 표기가 같으면 동일한 자료함에 합칩니다.
                        target = next((doc["company"] for doc in library.registry
                                       if company_name_key(doc["company"]) == company_name_key(chosen["corp_name"])),
                                      chosen["corp_name"])
                        content = connector.fetch_report(report)
                        doc = library.register_dart(report, content, target)
                    st.session_state["dart_status"] = f"{doc['name']} 등록 완료 · 접수 {doc['filing_date']} · 확인 {doc['checked_at']}"
                    st.session_state["company_select"] = target
                    st.session_state.pop("search_result", None)
                    st.rerun()
                except DartError as error:
                    st.warning(str(error))
                except Exception:
                    st.warning("사업보고서를 등록하지 못했어요. 공시 원문과 네트워크를 확인해주세요.")
        if st.session_state.get("dart_status"):
            st.success(st.session_state["dart_status"])

    companies = sorted({doc["company"] for doc in library.registry})
    company = st.selectbox("검색할 회사", companies, index=0 if companies else None, placeholder="자료를 등록해주세요", key="company_select")
    documents = [doc for doc in library.registry if doc["company"] == company and doc.get("active", True)]
    pdf_documents = [doc for doc in documents if doc.get("source_type") != "dart"]
    st.caption(f"IR 자료 {sum(document_category(doc) == 'ir' for doc in documents)}개 · 사업보고서 {sum(document_category(doc) == 'annual_report' for doc in documents)}개")
    with st.expander("등록된 파일 보기"):
        for doc in documents:
            st.write(f"[{category_label(doc)}] {doc['name']}")
            if doc.get("source_type") == "dart":
                st.caption(f"대상 {doc['report_period']} · 접수 {doc['filing_date']} · 최신 확인 {doc['checked_at']}")
                st.link_button("DART 원문", doc["source_url"], key=f"dart_original_{doc['id']}")
            else:
                st.caption(f"PDF {doc['pages']}쪽")

    st.divider()
    st.subheader("OpenAI 연결")
    api_key_input = st.text_input("OpenAI API 키", type="password", key="api_key_input", placeholder="키는 이 입력창에만 넣어주세요")
    key = api_key_input.strip() or os.getenv("OPENAI_API_KEY", "")
    st.caption("키는 파일에 저장하지 않아요. 키 입력만으로 API를 호출하지 않아요.")
    with st.expander("모델 설정"):
        embedding_model = st.text_input("검색 모델", value="text-embedding-3-small")
        answer_model = st.text_input("답변 모델", value="gpt-4.1-mini")
    st.caption("AI 사용 시 자료 텍스트·질문·검색 발췌문을 OpenAI로 전송하며 API 비용이 발생해요.")

library.EMBED_MODEL = embedding_model.strip()
library.ANSWER_MODEL = answer_model.strip()

# 회사를 바꾸면 앞 회사의 결과를 비워 혼동을 방지합니다.
if st.session_state.get("result_company") != company:
    st.session_state.pop("search_result", None)
    st.session_state["result_company"] = company

if not company:
    st.info("왼쪽에서 PDF를 등록하거나 ‘넥스틴 예제 불러오기’를 눌러 시작하세요.")
    st.stop()

source_scope_label = st.radio("검색에 사용할 자료", ["IR + 사업보고서", "IR 자료만", "사업보고서만"], horizontal=True)
source_scope = {"IR + 사업보고서": "all", "IR 자료만": "ir", "사업보고서만": "annual_report"}[source_scope_label]
if st.session_state.get("result_scope") != source_scope:
    st.session_state.pop("search_result", None)
    st.session_state["result_scope"] = source_scope
if not library.company_chunks(company, source_scope):
    st.info("선택한 종류의 자료가 아직 없어요. IR PDF 또는 최신 사업보고서를 먼저 등록해주세요.")

# 검색 방법은 근거를 찾는 방법입니다. 어떤 방법을 선택해도 기본 결과는 AI 요약입니다.
strategy = st.radio("자료를 찾는 방식", ["의미 검색", "단어 검색"], horizontal=True)
st.caption("의미 검색은 비슷한 뜻의 자료를, 단어 검색은 입력한 표현이 있는 자료를 찾아요. 두 방식 모두 검색된 근거로 AI가 요약해요.")
if not key:
    st.info("검색 기반 요약을 보려면 왼쪽에 OpenAI API 키를 입력해주세요. 키 없이도 원문만 미리 볼 수 있어요.")

# 이전 버전의 원문 전용 검색 결과와 새 요약 결과가 섞이지 않게 한 번만 비웁니다.
if st.session_state.get("summary_flow_version") != 5:
    st.session_state.pop("search_result", None)
    st.session_state["summary_flow_version"] = 5

with st.form("question_form"):
    question = st.text_area("무엇을 알고 싶나요?", placeholder="예: 이 기업이 무엇을 만드는지 쉽게 요약해줘 / IRIS의 특징을 정리해줘", height=90)
    submitted = st.form_submit_button("검색하고 요약하기", type="primary", disabled=not key)
    preview = st.form_submit_button("원문만 미리보기", help="API를 호출하지 않고 단어 검색으로 원문을 확인해요.")

if submitted or preview:
    st.session_state.pop("search_result", None)
    if not question.strip():
        st.warning("질문이나 검색어를 입력해주세요.")
    else:
        try:
            if not preview:
                library.client = OpenAI(api_key=key, timeout=60.0, max_retries=2)
            with st.spinner("자료 종류별로 근거를 모아 각각 요약하는 중…" if not preview else "자료 종류별 원문을 찾는 중…"):
                groups = library.collect_source_results(question, company, strategy, source_scope, preview)
            st.session_state["search_result"] = {
                "question": question, "company": company, "groups": groups,
                "strategy": "단어 검색" if preview else strategy, "preview": preview, "source_scope": source_scope_label,
            }
        except AuthenticationError:
            st.error("API 키를 확인해주세요. OpenAI 인증에 실패했어요.")
        except RateLimitError:
            st.error("OpenAI 사용 한도 또는 요청 한도에 도달했어요. API 계정의 결제·사용 한도를 확인해주세요.")
        except APIConnectionError:
            st.error("OpenAI에 연결하지 못했어요. 인터넷 연결을 확인해주세요.")
        except APIStatusError:
            st.error("OpenAI 요청을 처리하지 못했어요. 모델 이름과 계정의 모델 접근 권한을 확인해주세요.")
        except Exception:
            st.error("요약을 완료하지 못했어요. 모델 설정과 등록 자료를 확인한 뒤 다시 시도해주세요.")
        finally:
            if library.client is not None:
                library.client.close()
                library.client = None

result = st.session_state.get("search_result")
if not result:
    st.markdown("#### 이렇게 시작해보세요")
    st.write("기업 소개, 제품의 역할, 고객사, 특정 분기의 실적 등을 질문할 수 있어요.")
    st.caption("먼저 질문을 입력하고 ‘검색하고 요약하기’를 눌러주세요. 원문 미리보기는 IRIS · HBM · 매출액 같은 단어로 연습할 수 있어요.")
    st.stop()

# 요약을 읽는 영역과 근거 확인을 분리합니다. 원문은 요청할 때만 팝업으로 엽니다.
st.markdown("""
<style>
[data-testid="stMain"] [data-testid="stMarkdownContainer"] p,
[data-testid="stMain"] [data-testid="stMarkdownContainer"] li {
    font-size: 20px; line-height: 1.85;
}
[data-testid="stMain"] button p {font-size: 16px;}
</style>
""", unsafe_allow_html=True)

@st.dialog("근거 원문", width="large")
def show_evidence(hit, quote_text=""):
    doc = library.document_for(hit["chunk"])
    if doc.get("source_type") == "dart":
        st.markdown(f"**[{category_label(doc)}] {doc['name']}**")
        st.caption(f"{library.source_label(hit['chunk'])} · 접수 {doc['filing_date']}")
        st.html(library.excerpt_html(hit, quote_text))
        st.link_button("DART 공시 원문 열기", doc["source_url"])
        original = library.data_dir / "dart" / f"{doc['id']}.zip"
        st.download_button("공시 XML 원본 다운로드", original.read_bytes(), file_name=f"{doc['rcept_no']}.zip",
                           mime="application/zip", on_click="ignore")
        return
    st.markdown(f"**[{category_label(doc)}] {doc['name']} · PDF {hit['chunk']['page']}쪽**")
    if quote_text:
        st.caption("노란색은 이 답변의 근거로 인용한 줄이에요.")
    st.image(library.render_evidence(hit, quote_text), width="stretch")
    if quote_text:
        with st.expander("인용문 텍스트"):
            st.text(quote_text)
    original = library.PDF_DIR / f"{doc['id']}.pdf"
    st.download_button("원본 PDF 다운로드", original.read_bytes(), file_name=doc["name"],
                       mime="application/pdf", on_click="ignore")

st.subheader("자료별 답변 비교" if len(result["groups"]) == 2 else "답변")
st.caption(result["question"])
# 둘 다 선택했을 때만 두 칸을 만듭니다. 한 종류면 제목 하나와 답변 하나만 표시합니다.
panels = st.columns(2, gap="large") if len(result["groups"]) == 2 else [st.container()]
for panel, group in zip(panels, result["groups"]):
    with panel:
        title = "IR 자료" if group["kind"] == "ir" else "사업보고서"
        st.subheader(title)
        hits, answer = group["hits"], group["answer"]
        if group["status"] == "missing":
            st.info("등록된 자료가 없어요.")
            continue
        if group["status"] == "error":
            st.warning("이 자료의 검색·요약을 완료하지 못했어요. API 키·사용 한도·연결 상태를 확인해주세요.")
            continue
        if group["status"] == "no_hits":
            st.info("이 질문에 관련된 근거를 찾지 못했어요.")
            continue
        if answer is None:
            st.caption("원문 미리보기예요. 요약하려면 API 키를 입력하고 ‘검색하고 요약하기’를 눌러주세요.")
        elif answer["statements"]:
            # 자료 종류를 제목에 한 번만 쓰고 문단에는 반복하지 않습니다.
            st.markdown("\n\n".join(clean_summary_text(item["text"]) for item in answer["statements"]))
            counts = answer_provenance(answer, hits, library.registry)
            st.caption(f"실제 인용 문서 {counts[group['kind']]}개")
        else:
            st.info("검색된 자료에서 답변을 뒷받침할 근거를 확인하지 못했어요.")
        if answer and answer["limitations"]:
            st.caption(f"확인 범위: {answer['limitations']}")
        if answer and answer["rejected"]:
            st.caption(f"인용을 확인하지 못한 문단 {answer['rejected']}개를 제외했어요.")
        references, seen = [], set()
        for paragraph in (answer or {}).get("statements", []):
            for citation in paragraph["evidence"]:
                signature = (citation["source"], citation["quote"])
                if signature not in seen:
                    seen.add(signature)
                    references.append(citation)
        if references:
            with st.expander(f"답변 근거 확인 · {len(references)}개"):
                for number, reference in enumerate(references, 1):
                    hit = hits[reference["source"] - 1]
                    doc = library.document_for(hit["chunk"])
                    st.caption(f"[{number}] {doc['name']} · {library.source_label(hit['chunk'])}")
                    st.text(reference["quote"])
                    if st.button("원문 팝업으로 보기", key=f"citation_{group['kind']}_{number}"):
                        show_evidence(hit, reference["quote"])
        with st.expander(f"검색된 원문 데이터 · {len(hits)}개", expanded=False):
            for number, hit in enumerate(hits, 1):
                doc = library.document_for(hit["chunk"])
                with st.expander(f"[{number}] {doc['name']} · {library.source_label(hit['chunk'])}"):
                    st.text(hit["chunk"]["text"])
                    if st.button("원문 팝업으로 보기", key=f"raw_{group['kind']}_{number}"):
                        show_evidence(hit)

st.divider()
st.caption("같은 질문으로 자료 종류별 근거를 따로 검색하고 각각 요약해요. 한쪽 자료에 없는 정보는 다른 쪽에서 가져와 채우지 않아요.")
