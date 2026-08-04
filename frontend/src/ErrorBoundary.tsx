import { Component, type ReactNode } from "react";

/** 想定外の描画エラーで画面を真っ白にしない最後の受け皿。

    SPA化直後に「未知のWSイベントで状態破壊→真っ白」を、認可導入後に
    「403のエラーJSONをfilesに代入→files.mapで死亡→真っ白」を踏んだ。
    根本原因はそれぞれ潰したが、このクラスの事故は今後も起こり得るので、
    起きたときに「何かが壊れた」ことが見える形にしておく。 */
export class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div className="d-flex flex-column align-items-center justify-content-center vh-100 gap-3 px-4">
          <div className="fs-5">⚠ 画面の描画に失敗しました</div>
          <code className="text-danger small">{String(this.state.error)}</code>
          <button className="btn btn-outline-secondary btn-sm" onClick={() => location.reload()}>
            再読み込み
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
