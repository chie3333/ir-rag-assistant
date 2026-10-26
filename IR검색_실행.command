#!/bin/zsh
# Finder에서 이 파일을 더블클릭하면 검색 화면이 브라우저에 열립니다.
set -eu
cd -- "$(dirname -- "$0")"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import streamlit, openai, pdfplumber, numpy, bs4' >/dev/null 2>&1; then
  echo '처음 실행에 필요한 패키지를 설치합니다.'
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python .venv/bin/python -r requirements-app.txt
  else
    .venv/bin/python -m ensurepip --upgrade
    .venv/bin/python -m pip install -r requirements-app.txt
  fi
fi
echo 'IR 검색 앱을 엽니다. 종료하려면 이 창에서 Control+C를 누르세요.'
exec .venv/bin/python app.py
