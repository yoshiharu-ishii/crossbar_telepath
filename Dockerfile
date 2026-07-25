# uv入りのPython 3.12スリムイメージ。uv.lockどおりに依存を再現する
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# 1) 依存だけ先に入れてレイヤーキャッシュを効かせる
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 2) アプリ本体。コンテナ内のパス関係はリポジトリと同じにする
#    (config.py が backend/ の親を frontend/ と recordings/ の起点として参照するため)
#    .env は .dockerignore で除外。秘密はイメージに焼かない
COPY backend/ ./
COPY frontend/ /app/frontend/

EXPOSE 8000
# uvicornが出す 0.0.0.0:8000 はコンテナ内部の待ち受け表示で、ブラウザで開く場所ではない
CMD ["/bin/sh", "-c", "echo '================================================================' && echo ' ブラウザで開くURL: http://localhost:<ホスト側ポート>' && echo '   docker compose up なら -> http://localhost:8000' && echo '================================================================' && exec /app/backend/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000"]
