import { useEffect, useState } from "react";
import App from "./App";
import { setAuthEnabled } from "./api";
import { currentToken, fetchAuthConfig, logout, readIdentity } from "./auth";
import { Login } from "./components/Login";

type Phase = "loading" | "login" | "ready";

/** 認証の門番。認証無効(開発・CI)なら素通しでAppを出す。 */
export function AuthGate() {
  const [phase, setPhase] = useState<Phase>("loading");
  const [devTools, setDevTools] = useState(false);
  const [who, setWho] = useState<{ email: string; role: "sv" | "operator" } | null>(null);

  const enter = async () => {
    const token = await currentToken();
    if (token) {
      setWho(readIdentity(token));
      setPhase("ready");
    } else {
      setPhase("login");
    }
  };

  useEffect(() => {
    void (async () => {
      try {
        const cfg = await fetchAuthConfig();
        setAuthEnabled(cfg.enabled);
        setDevTools(cfg.dev_tools ?? !cfg.enabled);
        if (!cfg.enabled) setPhase("ready");
        else await enter();
      } catch {
        // 設定が取れない=バックエンド停止。素のAppを出しても同じ表示になる
        setPhase("ready");
      }
    })();
  }, []);

  if (phase === "loading") {
    return (
      <div className="d-flex align-items-center justify-content-center vh-100 text-secondary">
        <div className="spinner-border spinner-border-sm me-2" role="status" />
        接続中…
      </div>
    );
  }
  if (phase === "login") return <Login onLoggedIn={() => void enter()} />;
  return (
    <App
      devTools={devTools}
      identity={who}
      onLogout={() => {
        logout();
        location.reload();
      }}
    />
  );
}
