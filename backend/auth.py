"""Cognito認証。IDトークンのJWKS署名検証と、HTTP/WS用の認証依存。

**このモジュールは独立させておく**(消したら困る方針)。SPAやUIの書き直しの
影響を受けない位置に置き、外向きは require_auth / verify_ws_token / identity /
public_config の4つだけにする。

認証(このモジュール)と認可(broadcastの宛先化・API側の絞り込み)は別物。
ここでは「誰か」を確定するだけで、「何を見せるか」は次の段階で入れる。
AUTH_ENABLED=0(既定)なら素通しになり、開発とCIはこれまで通り動く。
"""

from __future__ import annotations

import logging

import jwt as pyjwt
from fastapi import HTTPException
from jwt import PyJWKClient
from starlette.requests import HTTPConnection

from config import AUTH_ENABLED, COGNITO_CLIENT_ID, COGNITO_ISSUER

log = logging.getLogger(__name__)

_jwks_client: PyJWKClient | None = None

# 認証を要求しないパス。ヘルスは監視用、auth/configはログイン画面が
# 認証前に読む必要がある。"/" はSPAの殻(データはAPI側で守る)
PUBLIC_PATHS = {"/", "/api/health", "/api/auth/config"}


def _signing_key(token: str):
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(f"{COGNITO_ISSUER}/.well-known/jwks.json")
    return _jwks_client.get_signing_key_from_jwt(token).key


def verify_token(token: str) -> dict:
    """Cognito発行のIDトークンを検証してクレームを返す。失敗時は例外。"""
    claims = pyjwt.decode(
        token,
        _signing_key(token),
        algorithms=["RS256"],
        audience=COGNITO_CLIENT_ID,
        issuer=COGNITO_ISSUER,
    )
    if claims.get("token_use") != "id":
        raise ValueError("IDトークンではありません")
    return claims


def identity(claims: dict) -> dict:
    """クレームから席の情報を取り出す。

    ロールは cognito:groups から。svが入っていればsv、無ければoperator
    (安全側: グループ未設定のユーザーに全呼が見える事故を防ぐ)。
    """
    groups = claims.get("cognito:groups") or []
    return {
        "sub": claims.get("sub", ""),
        "email": claims.get("email", ""),
        "role": "sv" if "sv" in groups else "operator",
    }


async def require_auth(conn: HTTPConnection) -> dict:
    """HTTP API用の認証依存(アプリ全体に掛ける)。認証無効時は素通し。

    HTTPConnectionで受けるのはWSルートにも同じ依存が注入されるため。
    WSの認証は ws_endpoint が自前でやる(トークンはクエリで来る)ので、
    ここではWSを素通しにする。
    """
    if conn.scope.get("type") == "websocket":
        return {}
    if not AUTH_ENABLED or conn.url.path in PUBLIC_PATHS:
        return {}
    token = conn.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="認証が必要です")
    try:
        return identity(verify_token(token))
    except HTTPException:
        raise
    except Exception:
        log.warning("トークン検証に失敗", exc_info=True)
        raise HTTPException(status_code=401, detail="トークンが無効です")


def verify_ws_token(token: str | None) -> dict | None:
    """WebSocket用。認証無効なら空の席、無効トークンならNone(=接続拒否)。"""
    if not AUTH_ENABLED:
        return {}
    if not token:
        return None
    try:
        return identity(verify_token(token))
    except Exception:
        log.warning("WSトークン検証に失敗", exc_info=True)
        return None


def public_config() -> dict:
    """ログイン画面が使う公開設定(シークレットは含まない)。"""
    from config import COGNITO_REGION, COGNITO_USER_POOL_ID, DEV_TOOLS

    return {
        "enabled": AUTH_ENABLED,
        "region": COGNITO_REGION,
        "user_pool_id": COGNITO_USER_POOL_ID,
        "client_id": COGNITO_CLIENT_ID,
        "dev_tools": DEV_TOOLS,
    }
