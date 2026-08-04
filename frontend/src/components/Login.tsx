import { useState, type FormEvent } from "react";
import { completeNewPassword, login, type LoginResult } from "../auth";

/** ログイン画面。招待の一時パスワード直後は本パスワード設定に切り替わる。 */
export function Login({ onLoggedIn }: { onLoggedIn: () => void }) {
  const [phase, setPhase] = useState<"login" | "new_password">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const handle = (r: LoginResult) => {
    setBusy(false);
    if (r.kind === "ok") onLoggedIn();
    else if (r.kind === "new_password_required") {
      setPhase("new_password");
      setError("");
    } else setError(r.message);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    handle(
      phase === "login"
        ? await login(email.trim(), password)
        : await completeNewPassword(newPassword),
    );
  };

  return (
    <div className="login-bg d-flex align-items-center justify-content-center vh-100 px-3">
      <div className="login-card card border-0 shadow-lg" style={{ maxWidth: 400, width: "100%" }}>
        <div className="card-body p-4 p-md-5">
          <div className="text-center mb-4">
            <div className="login-mark mx-auto mb-3">☎</div>
            <h1 className="fs-4 fw-bold mb-1">crossbar_telepath</h1>
            <div className="text-secondary small">通話モニタ — 電話網の監視卓</div>
          </div>

          {phase === "new_password" && (
            <div className="alert alert-info py-2 small">
              初回ログインです。新しいパスワードを設定してください。
            </div>
          )}
          {error && (
            <div className="alert alert-danger py-2 small" data-testid="login-error">
              {error}
            </div>
          )}

          <form onSubmit={submit}>
            {phase === "login" ? (
              <>
                <div className="form-floating mb-2">
                  <input
                    id="email"
                    type="email"
                    className="form-control"
                    placeholder="you@example.com"
                    autoComplete="username"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    autoFocus
                  />
                  <label htmlFor="email">メールアドレス</label>
                </div>
                <div className="form-floating mb-3">
                  <input
                    id="password"
                    type="password"
                    className="form-control"
                    placeholder="password"
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                  />
                  <label htmlFor="password">パスワード</label>
                </div>
              </>
            ) : (
              <div className="form-floating mb-3">
                <input
                  id="new-password"
                  type="password"
                  className="form-control"
                  placeholder="new password"
                  autoComplete="new-password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  required
                  autoFocus
                />
                <label htmlFor="new-password">新しいパスワード</label>
              </div>
            )}
            <button className="btn btn-primary w-100 py-2" disabled={busy} type="submit">
              {busy ? "確認中…" : phase === "login" ? "ログイン" : "パスワードを設定"}
            </button>
          </form>

          <div className="text-center text-secondary mt-4" style={{ fontSize: 11 }}>
            アカウントは管理者が発行します(セルフ登録なし)
          </div>
        </div>
      </div>
    </div>
  );
}
