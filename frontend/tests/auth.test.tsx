// 認証の門番(AuthGate)とログイン画面の振る舞い。
// Cognito SDKはモックする(本物のSRPはE2Eで確認する)。

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const authMock = vi.hoisted(() => ({
  fetchAuthConfig: vi.fn(),
  currentToken: vi.fn(),
  login: vi.fn(),
  completeNewPassword: vi.fn(),
  logout: vi.fn(),
  readIdentity: vi.fn(),
}));
vi.mock("../src/auth", () => authMock);

import { AuthGate } from "../src/AuthGate";

function mockApi() {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => ({
    ok: true,
    json: async () => (String(url).includes("recording-files") ? [] : []),
  })));
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  mockApi();
});

describe("AuthGate", () => {
  it("認証無効なら素通しでアプリが出る(開発・CIの既定)", async () => {
    authMock.fetchAuthConfig.mockResolvedValue({ enabled: false });
    render(<AuthGate />);
    expect(await screen.findByText("リアルタイム識字")).toBeInTheDocument();
    expect(screen.queryByLabelText("メールアドレス")).not.toBeInTheDocument();
  });

  it("認証有効でセッションが無ければログイン画面", async () => {
    authMock.fetchAuthConfig.mockResolvedValue({ enabled: true });
    authMock.currentToken.mockResolvedValue(null);
    render(<AuthGate />);
    expect(await screen.findByLabelText("メールアドレス")).toBeInTheDocument();
    expect(screen.getByLabelText("パスワード")).toBeInTheDocument();
    expect(screen.getByText("crossbar_telepath")).toBeInTheDocument();
  });

  it("ログイン失敗はメッセージを出し、成功でアプリ+ロールバッジが出る", async () => {
    authMock.fetchAuthConfig.mockResolvedValue({ enabled: true });
    authMock.currentToken.mockResolvedValue(null);
    authMock.login.mockResolvedValueOnce({ kind: "error", message: "メールアドレスまたはパスワードが違います" });
    render(<AuthGate />);

    await userEvent.type(await screen.findByLabelText("メールアドレス"), "sv@example.com");
    await userEvent.type(screen.getByLabelText("パスワード"), "wrong-pass");
    await userEvent.click(screen.getByRole("button", { name: "ログイン" }));
    expect(await screen.findByTestId("login-error")).toHaveTextContent("違います");

    // 2回目は成功 → セッションが生えてアプリへ
    authMock.login.mockResolvedValueOnce({ kind: "ok" });
    authMock.currentToken.mockResolvedValue("token-x");
    authMock.readIdentity.mockReturnValue({ email: "sv@example.com", role: "sv" });
    await userEvent.click(screen.getByRole("button", { name: "ログイン" }));
    expect(await screen.findByText("SV(監視卓)")).toBeInTheDocument();
    expect(screen.getByText("ログアウト")).toBeInTheDocument();
  });

  it("招待の一時パスワード後は本パスワード設定に切り替わる", async () => {
    authMock.fetchAuthConfig.mockResolvedValue({ enabled: true });
    authMock.currentToken.mockResolvedValue(null);
    authMock.login.mockResolvedValue({ kind: "new_password_required" });
    render(<AuthGate />);

    await userEvent.type(await screen.findByLabelText("メールアドレス"), "new@example.com");
    await userEvent.type(screen.getByLabelText("パスワード"), "Temp-pass1!");
    await userEvent.click(screen.getByRole("button", { name: "ログイン" }));

    expect(await screen.findByLabelText("新しいパスワード")).toBeInTheDocument();
    authMock.completeNewPassword.mockResolvedValue({ kind: "ok" });
    authMock.currentToken.mockResolvedValue("token-y");
    authMock.readIdentity.mockReturnValue({ email: "new@example.com", role: "operator" });
    await userEvent.type(screen.getByLabelText("新しいパスワード"), "RealPass1!");
    await userEvent.click(screen.getByRole("button", { name: "パスワードを設定" }));
    await waitFor(() => expect(screen.getByText("応対者")).toBeInTheDocument());
  });
});
