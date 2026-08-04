"""認可(宛先化と絞り込み)。認証(test_auth)とは別物:
「誰か」が分かった後に「何を見せるか」を絞る層の検証。"""

from __future__ import annotations

import json

import pytest

from hub import CallRecord, Hub

@pytest.fixture(autouse=True)
def local_keys(monkeypatch):
    """JWKSへ出ずにローカル鍵で検証させる(test_authと同じ固定)。"""
    import auth
    from tests.test_auth import PUB

    monkeypatch.setattr(auth, "_signing_key", lambda token: PUB)
    monkeypatch.setattr(auth, "COGNITO_ISSUER", "https://cognito-idp.test/pool")
    monkeypatch.setattr(auth, "COGNITO_CLIENT_ID", "client-abc")


SV = {"sub": "s1", "email": "sv@example.com", "role": "sv"}
OP_A = {"sub": "a1", "email": "a@example.com", "role": "operator"}
OP_B = {"sub": "b1", "email": "b@example.com", "role": "operator"}


class FakeWs:
    def __init__(self):
        self.got: list[dict] = []

    async def accept(self):
        pass

    async def send_text(self, payload: str):
        self.got.append(json.loads(payload))


@pytest.fixture()
def wired_hub():
    """SV1席+応対者2席が繋がったhub。呼はAの担当1本と未割り当て1本。"""
    h = Hub()
    owned = CallRecord(contact_id="owned-by-a", label="t")
    owned.owner_email = "a@example.com"
    unowned = CallRecord(contact_id="unowned", label="t")
    h.active = {"owned-by-a": owned, "unowned": unowned}
    clients = {"sv": FakeWs(), "a": FakeWs(), "b": FakeWs()}
    h._clients = {clients["sv"]: SV, clients["a"]: OP_A, clients["b"]: OP_B}  # type: ignore[dict-item]
    return h, clients


def types(ws: FakeWs) -> list[str]:
    return [m["type"] for m in ws.got]


@pytest.mark.asyncio
async def test_content_goes_only_to_owner_and_sv(wired_hub):
    """文字起こし・判定の中身は、担当とSVにしか届かない。"""
    h, c = wired_hub
    await h.broadcast({"type": "transcript", "contact_id": "owned-by-a",
                       "speaker": "customer", "text": "秘密の内容", "final": True})
    await h.broadcast({"type": "emotion", "contact_id": "owned-by-a", "score": 80})

    assert types(c["sv"]) == ["transcript", "emotion"]
    assert types(c["a"]) == ["transcript", "emotion"]
    assert types(c["b"]) == [], "他人の呼の中身が応対者Bに漏れている"


@pytest.mark.asyncio
async def test_unowned_live_call_meta_is_visible_for_claiming(wired_hub):
    """未割り当てのライブ呼は、メタだけ全応対者に見える(取るため)。中身は見えない。"""
    h, c = wired_hub
    await h.broadcast({"type": "call_started", "contact_id": "unowned"})
    await h.broadcast({"type": "transcript", "contact_id": "unowned",
                       "speaker": "customer", "text": "まだ誰のものでもない", "final": True})

    assert types(c["b"]) == ["call_started"], "メタは見えるが中身は見えないこと"
    assert types(c["sv"]) == ["call_started", "transcript"]


@pytest.mark.asyncio
async def test_call_updated_reaches_everyone(wired_hub):
    """担当の変化は全員へ(他の応対者の一覧から「取る」を消すため)。"""
    h, c = wired_hub
    await h.broadcast({"type": "call_updated", "contact_id": "owned-by-a",
                       "owner_email": "a@example.com"})
    for name in ("sv", "a", "b"):
        assert types(c[name]) == ["call_updated"], name


# ---- HTTP API側の絞り込み ----


@pytest.fixture()
def client(monkeypatch):
    import auth
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app) as cli:
        yield cli


@pytest.fixture()
def two_calls(monkeypatch):
    from main import hub
    owned = CallRecord(contact_id="mine", label="t")
    owned.owner_email = "a@example.com"
    other = CallRecord(contact_id="theirs", label="t")
    other.owner_email = "b@example.com"
    unowned = CallRecord(contact_id="free", label="t")
    hub.active.update({"mine": owned, "theirs": other, "free": unowned})
    yield
    for cid in ("mine", "theirs", "free"):
        hub.active.pop(cid, None)


def _token(email: str, groups: list[str]):
    from tests.test_auth import make_token
    return make_token(**{"email": email, "cognito:groups": groups})


def test_operator_list_shows_own_and_unowned_only(client, two_calls):
    r = client.get("/api/history",
                   headers={"Authorization": f"Bearer {_token('a@example.com', ['operator'])}"})
    ids = [c["contact_id"] for c in r.json()]
    assert "mine" in ids and "free" in ids
    assert "theirs" not in ids, "他人の担当呼が一覧に出ている"


def test_operator_detail_forbidden_for_others(client, two_calls):
    h = {"Authorization": f"Bearer {_token('a@example.com', ['operator'])}"}
    assert client.get("/api/history/mine", headers=h).status_code == 200
    assert client.get("/api/history/theirs", headers=h).status_code == 403


def test_sv_sees_everything(client, two_calls):
    h = {"Authorization": f"Bearer {_token('sv@example.com', ['sv'])}"}
    ids = [c["contact_id"] for c in client.get("/api/history", headers=h).json()]
    assert {"mine", "theirs", "free"} <= set(ids)
    assert client.get("/api/history/theirs", headers=h).status_code == 200


def test_reprocess_is_sv_only(client, two_calls):
    op = {"Authorization": f"Bearer {_token('a@example.com', ['operator'])}"}
    assert client.post("/api/reprocess/mine", headers=op).status_code == 403


def test_dev_endpoints_are_sv_only(client):
    """リプレイと録音一覧はUIで隠すだけでなくAPIでも塞ぐ(直叩き対策)。"""
    op = {"Authorization": f"Bearer {_token('a@example.com', ['operator'])}"}
    assert client.post("/api/replay?file=call.mkv", headers=op).status_code == 403
    assert client.get("/api/recording-files", headers=op).status_code == 403
