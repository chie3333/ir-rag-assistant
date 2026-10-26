"""OpenDART에서 회사와 최신 연간 사업보고서를 찾는 연결 모듈.

API 키는 메모리에서만 사용하며 요청 URL이나 키를 파일에 기록하지 않습니다.
"""
import io
import json
import re
import time
import zipfile
import warnings
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning


class DartError(ValueError):
    pass


def company_name_key(name):
    return re.sub(r"주식회사|\(주\)|㈜|\s+", "", name).lower()


def zip_members(content):
    """압축을 디스크에 풀지 않고 내부 XML 파일만 읽습니다."""
    if not zipfile.is_zipfile(io.BytesIO(content)):
        soup = BeautifulSoup(content, "html.parser")
        status = soup.find("status")
        code = status.get_text(strip=True) if status else "unknown"
        messages = {"010": "DART API 키가 유효하지 않습니다.", "011": "사용할 수 없는 DART 키입니다.",
                    "012": "DART 키의 허용 IP 설정을 확인해주세요.", "020": "DART 요청 한도에 도달했습니다.",
                    "014": "공시 원본 파일이 없습니다."}
        raise DartError(messages.get(code, f"DART 원본 파일을 받지 못했습니다. 상태 코드: {code}"))
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        files = [entry for entry in archive.infolist() if entry.filename.lower().endswith('.xml')]
        if not files or sum(entry.file_size for entry in files) > 100_000_000:
            raise DartError("원본 XML의 크기 또는 형식을 확인할 수 없습니다.")
        return [(entry.filename, archive.read(entry)) for entry in files]


class OpenDart:
    def __init__(self, api_key, cache_dir, transport=None):
        if not api_key or not api_key.strip():
            raise DartError("OpenDART API 키를 입력해주세요.")
        self.api_key = api_key.strip()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.transport = transport

    def request(self, endpoint, **params):
        query = {"crtfc_key": self.api_key, **params}
        if self.transport:
            return self.transport(endpoint, query)
        url = "https://opendart.fss.or.kr/api/" + endpoint + "?" + urlencode(query)
        try:
            with urlopen(Request(url, headers={"User-Agent": "IR-Learning-App/1.0"}), timeout=60) as response:
                return response.read()
        except Exception:
            # 원래 예외의 URL에는 API 키가 있어 화면에 그대로 노출하지 않습니다.
            raise DartError("DART에 연결하지 못했습니다. 네트워크 연결을 확인해주세요.") from None

    def json_request(self, endpoint, **params):
        try:
            payload = json.loads(self.request(endpoint, **params))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise DartError("DART 응답을 읽지 못했습니다.") from None
        code = payload.get("status")
        if code == "013":
            return {"list": [], "total_page": 0}
        if code != "000":
            messages = {"010": "DART API 키가 유효하지 않습니다.", "011": "사용할 수 없는 DART 키입니다.",
                        "012": "DART 키의 IP 제한을 확인해주세요.", "020": "DART 요청 한도에 도달했습니다."}
            raise DartError(messages.get(code, f"DART 조회에 실패했습니다. 상태 코드: {code}"))
        return payload

    def search_companies(self, keyword):
        if not keyword.strip():
            raise DartError("회사명 또는 종목코드를 입력해주세요.")
        path = self.cache_dir / 'companies.json'
        if path.exists() and time.time() - path.stat().st_mtime < 86400:
            companies = json.loads(path.read_text(encoding='utf-8'))
        else:
            files = zip_members(self.request('corpCode.xml'))
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', XMLParsedAsHTMLWarning)
                soup = BeautifulSoup(files[0][1], 'html.parser')
            companies = []
            for item in soup.find_all('list'):
                def field(name):
                    element = item.find(name)
                    return element.get_text(strip=True) if element else ''
                companies.append({name: field(name) for name in ['corp_code', 'corp_name', 'stock_code']})
            path.write_text(json.dumps(companies, ensure_ascii=False), encoding='utf-8')
        query = company_name_key(keyword)
        matches = [item for item in companies if query in company_name_key(item['corp_name']) or keyword == item['stock_code']]
        return sorted(matches, key=lambda item: (company_name_key(item['corp_name']) != query, not bool(item['stock_code']), item['corp_name']))[:50]

    def latest_annual_report(self, corp_code, as_of=None):
        if not re.fullmatch(r'\d{8}', corp_code):
            raise DartError("DART 회사 고유번호를 확인해주세요.")
        day = as_of or datetime.now(ZoneInfo('Asia/Seoul')).date()
        reports, page = [], 1
        while True:
            data = self.json_request('list.json', corp_code=corp_code, bgn_de=f'{day.year-5}0101',
                                     end_de=day.strftime('%Y%m%d'), last_reprt_at='Y',
                                     pblntf_detail_ty='A001', sort='date', sort_mth='desc',
                                     page_no=page, page_count=100)
            reports.extend(data.get('list', []))
            if page >= int(data.get('total_page', 0)):
                break
            page += 1
        candidates = []
        for report in reports:
            # 최근 접수된 과거 연도 정정을 최신 사업연도로 잘못 고르지 않습니다.
            match = re.search(r'사업보고서\s*\((\d{4})\.(\d{2})\)', report.get('report_nm', ''))
            if not match or '철' in report.get('rm', ''):
                continue
            if report.get('corp_code') != corp_code or report.get('rcept_dt', '') > day.strftime('%Y%m%d'):
                continue
            candidates.append(((int(match[1]), int(match[2])), report.get('rcept_dt', ''), report['rcept_no'], report))
        if not candidates:
            raise DartError("최근 5년 접수 내역에서 연간 사업보고서를 찾지 못했습니다.")
        period, _, _, selected = max(candidates, key=lambda row: row[:3])
        return {**selected, 'report_period': f'{period[0]}.{period[1]:02d}', 'checked_at': day.isoformat(),
                'source_url': f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={selected['rcept_no']}"}

    def fetch_report(self, report):
        receipt = report['rcept_no']
        if not re.fullmatch(r'\d{14}', receipt):
            raise DartError("공시 접수번호를 확인해주세요.")
        content = self.request('document.xml', rcept_no=receipt)
        zip_members(content)
        return content


def parse_report(content, receipt):
    """XML을 항목·문단·표의 행 단위로 읽습니다. PDF 쪽수를 만들어내지 않습니다."""
    parsed = []
    for filename, raw in zip_members(content):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', XMLParsedAsHTMLWarning)
            soup = BeautifulSoup(raw, 'html.parser')
        blocks, title = [], '표지 및 개요'
        for element in soup.find_all(['title', 'subtitle', 'p', 'tr']):
            if element.find_parent('tr') and element.name != 'tr':
                continue
            if element.name in ('title', 'subtitle'):
                title = element.get_text(' ', strip=True) or title
                text = title
            elif element.name == 'tr':
                cells = element.find_all(['td', 'te', 'th'], recursive=False)
                text = ' | '.join(cell.get_text(' ', strip=True) for cell in cells)
            else:
                if element.find('table'):
                    continue
                text = element.get_text(' ', strip=True)
            if text:
                blocks.append({'section': title, 'text': text})
        complete = '사업의내용' in re.sub(r'\s+', '', soup.get_text())
        parsed.append((complete, len(soup.get_text()), filename, blocks))
    # 첨부 문서보다 실제 사업의 내용이 들어 있는 본문을 우선 선택합니다.
    complete, _, filename, blocks = max(parsed, key=lambda row: row[:2])
    if not complete:
        raise DartError("사업의 내용 본문을 확인하지 못했습니다. 정정 내역만 있는 문서일 수 있어 DART 원문 확인이 필요합니다.")
    return filename, blocks
