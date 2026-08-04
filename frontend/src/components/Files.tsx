import type { RecordingFile } from "../types";

/** 録音ファイル(開発用リプレイ)。クリックでリプレイが始まりライブ追従になる。 */
export function Files({ files, onReplay }: {
  files: RecordingFile[];
  onReplay: (file: string) => void;
}) {
  return (
    <div className="feed px-4 py-3">
      <div className="text-secondary small fw-semibold mb-2">録音ファイル(開発用リプレイ)</div>
      {files.length === 0 && <div className="text-secondary small">ファイルがありません。</div>}
      <div className="d-flex flex-column gap-2" style={{ maxWidth: 480 }}>
        {files.map((f) => (
          <button
            key={f.file}
            className="btn text-start border rounded bg-body px-3 py-2"
            onClick={() => onReplay(f.file)}
          >
            <div className="fw-semibold small font-monospace">{f.file}</div>
            <div className="text-secondary" style={{ fontSize: 11 }}>
              {Math.round(f.size / 1024)} KB · クリックでリプレイ
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
