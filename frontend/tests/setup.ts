import "@testing-library/jest-dom/vitest";

// WSとAudioはjsdomに無いのでスタブする(接続の中身はテスト対象外)
class FakeWebSocket {
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  static last: FakeWebSocket | null = null;
  constructor() {
    FakeWebSocket.last = this;
    setTimeout(() => this.onopen?.(), 0);
  }
  close() {}
  /** テストからサーバー送信を模す */
  static push(ev: unknown) {
    FakeWebSocket.last?.onmessage?.({ data: JSON.stringify(ev) });
  }
}
(globalThis as Record<string, unknown>).WebSocket = FakeWebSocket;
(globalThis as Record<string, unknown>).FakeWebSocket = FakeWebSocket;

class FakeAudio {
  play() {
    return Promise.resolve();
  }
  pause() {}
}
(globalThis as Record<string, unknown>).Audio = FakeAudio;

// scrollToはjsdom未実装
Element.prototype.scrollTo = () => {};
