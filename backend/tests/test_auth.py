"""認証の検証。Cognito本物には出ない(署名はローカルのRSA鍵で作る)。"""

from __future__ import annotations

import time

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

import auth

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUB = KEY.public_key()


def make_token(**overrides) -> str:
    claims = {
        "sub": "user-1",
        "email": "op@example.com",
        "aud": "client-abc",
        "iss": "https://cognito-idp.test/pool",
        "token_use": "id",
        "exp": int(time.time()) + 3600,
        **overrides,
    }
    return pyjwt.encode(claims, KEY, algorithm="RS256")


@pytest.fixture(autouse=True)
def local_keys(monkeypatch):
    """JWKSへ出ずにローカル鍵で検証させる。発行者・クライアントIDも固定。"""
    monkeypatch.setattr(auth, "_signing_key", lambda token: PUB)
    monkeypatch.setattr(auth, "COGNITO_ISSUER", "https://cognito-idp.test/pool")
    monkeypatch.setattr(auth, "COGNITO_CLIENT_ID", "client-abc")


def test_valid_token_passes():
    claims = auth.verify_token(make_token())
    assert claims["sub"] == "user-1"


@pytest.mark.parametrize("bad", [
    {"aud": "other-client"},          # 別アプリ向けのトークン
    {"iss": "https://evil.example"},  # 別プールの発行
    {"exp": int(time.time()) - 10},   # 期限切れ
    {"token_use": "access"},          # IDトークン以外は拒否
])
def test_invalid_tokens_rejected(bad):
    with pytest.raises(Exception):
        auth.verify_token(make_token(**bad))


def test_identity_role_mapping():
    """ロールはsvグループの有無で決まる。未設定はoperator(安全側)。"""
    sv = auth.identity({"sub": "a", "email": "x", "cognito:groups": ["sv"]})
    op = auth.identity({"sub": "b", "email": "y", "cognito:groups": ["operator"]})
    none = auth.identity({"sub": "c", "email": "z"})
    assert sv["role"] == "sv"
    assert op["role"] == "operator"
    assert none["role"] == "operator", "グループ未設定に全呼が見えてはいけない"


def test_ws_token_verification(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    assert auth.verify_ws_token(None) is None            # トークン無し → 拒否
    assert auth.verify_ws_token("garbage") is None       # 壊れたトークン → 拒否
    who = auth.verify_ws_token(make_token(**{"cognito:groups": ["sv"]}))
    assert who and who["role"] == "sv"

    monkeypatch.setattr(auth, "AUTH_ENABLED", False)
    assert auth.verify_ws_token(None) == {}              # 認証無効 → 素通し


# ---- HTTP境界(アプリ全体に掛けた依存が効いているか) ----


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    from fastapi.testclient import TestClient

    import main

    with TestClient(main.app) as c:
        yield c


def test_api_requires_token(client):
    assert client.get("/api/history/no-such-call").status_code == 401


def test_public_paths_stay_open(client):
    assert client.get("/api/health").status_code == 200
    cfg = client.get("/api/auth/config")
    assert cfg.status_code == 200
    assert cfg.json()["enabled"] is True


def test_valid_token_reaches_handler(client):
    r = client.get(
        "/api/history/no-such-call",
        headers={"Authorization": f"Bearer {make_token()}"},
    )
    assert r.status_code == 404  # 認証は通り、呼が無いという業務上の404に到達する


def test_ws_rejects_without_token(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect("/ws"):
            pass
    assert e.value.code == 4401


# ---- 挙手(claim): 担当の割り当て ----


@pytest.fixture()
def live_call():
    """hubに通話中の呼を1本生やす(テスト後に掃除)。"""
    import hub as hub_mod
    from hub import CallRecord
    from main import hub

    rec = CallRecord(contact_id="live-1", label="t")
    hub.active["live-1"] = rec
    yield rec
    hub.active.pop("live-1", None)


def test_claim_sets_owner(client, monkeypatch, live_call):
    token = make_token(**{"cognito:groups": ["operator"], "email": "op@example.com"})
    r = client.post("/api/calls/live-1/claim", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert live_call.owner_email == "op@example.com"

    # 同じ人の再挙手は冪等
    r2 = client.post("/api/calls/live-1/claim", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200

    # 別の人は取れない(奪い合い防止)
    other = make_token(**{"email": "sv@example.com"})
    r3 = client.post("/api/calls/live-1/claim", headers={"Authorization": f"Bearer {other}"})
    assert r3.status_code == 409


def test_claim_rejects_ended_call(client, live_call):
    live_call.ended_at = 123.0
    token = make_token()
    r = client.post("/api/calls/live-1/claim", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404


def test_config_exposes_dev_tools_flag(client, monkeypatch):
    """設定値がそのまま公開設定に出ること(既定値の導出はconfig.pyの責務)。"""
    import config

    monkeypatch.setattr(config, "DEV_TOOLS", False)
    assert client.get("/api/auth/config").json()["dev_tools"] is False
    monkeypatch.setattr(config, "DEV_TOOLS", True)
    assert client.get("/api/auth/config").json()["dev_tools"] is True
