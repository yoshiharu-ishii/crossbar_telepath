// Cognito認証(SRP)。**このモジュールは独立させておく**(消したら困る方針)。
// UIの書き直しの影響を受けない位置に置き、外向きは AuthApi の形だけにする。
//
// Hosted UIではなく自前ログイン画面+SRPにしたのは、画面のデザインを
// 完全に握るため。SRPなのでパスワードは平文でネットワークに乗らない。

import {
  AuthenticationDetails,
  CognitoUser,
  CognitoUserPool,
  type CognitoUserSession,
} from "amazon-cognito-identity-js";

export interface AuthConfig {
  enabled: boolean;
  region: string;
  user_pool_id: string;
  client_id: string;
}

export type LoginResult =
  | { kind: "ok" }
  | { kind: "new_password_required" } // 招待の一時パスワードでログインした直後
  | { kind: "error"; message: string };

let pool: CognitoUserPool | null = null;
let pendingUser: CognitoUser | null = null; // 新パスワード設定チャレンジの継続用

export async function fetchAuthConfig(): Promise<AuthConfig> {
  const res = await fetch("/api/auth/config");
  const cfg: AuthConfig = await res.json();
  if (cfg.enabled) {
    pool = new CognitoUserPool({ UserPoolId: cfg.user_pool_id, ClientId: cfg.client_id });
  }
  return cfg;
}

/** 現在の有効なIDトークン。SDKがリフレッシュトークンで自動更新する。 */
export function currentToken(): Promise<string | null> {
  const user = pool?.getCurrentUser();
  if (!user) return Promise.resolve(null);
  return new Promise((resolve) => {
    user.getSession((err: Error | null, session: CognitoUserSession | null) => {
      if (err || !session || !session.isValid()) resolve(null);
      else resolve(session.getIdToken().getJwtToken());
    });
  });
}

export function login(email: string, password: string): Promise<LoginResult> {
  if (!pool) return Promise.resolve({ kind: "error", message: "認証設定が未取得です" });
  const user = new CognitoUser({ Username: email, Pool: pool });
  return new Promise((resolve) => {
    user.authenticateUser(
      new AuthenticationDetails({ Username: email, Password: password }),
      {
        onSuccess: () => resolve({ kind: "ok" }),
        onFailure: (err) => resolve({ kind: "error", message: friendly(err) }),
        newPasswordRequired: () => {
          pendingUser = user;
          resolve({ kind: "new_password_required" });
        },
      },
    );
  });
}

/** 招待の一時パスワード後の、本パスワード設定。 */
export function completeNewPassword(newPassword: string): Promise<LoginResult> {
  const user = pendingUser;
  if (!user) return Promise.resolve({ kind: "error", message: "ログインからやり直してください" });
  return new Promise((resolve) => {
    user.completeNewPasswordChallenge(newPassword, {}, {
      onSuccess: () => {
        pendingUser = null;
        resolve({ kind: "ok" });
      },
      onFailure: (err) => resolve({ kind: "error", message: friendly(err) }),
    });
  });
}

export function logout(): void {
  pool?.getCurrentUser()?.signOut();
}

/** 表示用: トークンのペイロードから席の情報を取り出す(検証はサーバーの仕事)。 */
export function readIdentity(token: string): { email: string; role: "sv" | "operator" } {
  try {
    const p = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    const groups: string[] = p["cognito:groups"] || [];
    return { email: p.email || "", role: groups.includes("sv") ? "sv" : "operator" };
  } catch {
    return { email: "", role: "operator" };
  }
}

function friendly(err: unknown): string {
  const code = (err as { code?: string; message?: string })?.code;
  switch (code) {
    case "NotAuthorizedException":
      return "メールアドレスまたはパスワードが違います";
    case "UserNotFoundException":
      return "メールアドレスまたはパスワードが違います"; // ユーザーの存在は明かさない
    case "PasswordResetRequiredException":
      return "パスワードのリセットが必要です。管理者に連絡してください";
    case "LimitExceededException":
    case "TooManyRequestsException":
      return "試行が多すぎます。しばらく待ってからやり直してください";
    case "InvalidPasswordException":
      return "パスワードの要件を満たしていません(8文字以上・大小英字・数字・記号)";
    default:
      return (err as { message?: string })?.message || "ログインに失敗しました";
  }
}
