import type { CallMeta } from "../types";
import { angerColor, clock, day, shortId } from "../anger";

/** 監視卓(SVビュー)。全呼を「担当・状態ゲージ・状況の読み」の行で一覧する。
    通話中は**怒り順**——荒れている呼を探す作業を人に残さない。 */
export function Dashboard(props: {
  calls: CallMeta[];
  myEmail?: string;
  onOpen: (id: string) => void;
  onClaim: (id: string) => void;
}) {
  const live = props.calls
    .filter((c) => c.live)
    .sort((a, b) => (b.anger_now ?? b.max_anger ?? 0) - (a.anger_now ?? a.max_anger ?? 0));
  const ended = props.calls
    .filter((c) => !c.live)
    .sort((a, b) => (b.started_at || 0) - (a.started_at || 0));

  return (
    <div className="feed px-4 py-3">
      <Section title={`通話中 (${live.length})`} empty="いまは通話がありません。">
        {live.map((c) => (
          <Row key={c.contact_id} c={c} {...props} />
        ))}
      </Section>
      <Section title={`終了した呼 (${ended.length})`} empty="まだ記録がありません。">
        {ended.map((c) => (
          <Row key={c.contact_id} c={c} {...props} />
        ))}
      </Section>
    </div>
  );
}

function Section({ title, empty, children }: {
  title: string; empty: string; children: React.ReactNode[];
}) {
  return (
    <div className="mb-4">
      <div className="text-secondary small fw-semibold mb-2">{title}</div>
      {children.length === 0 ? (
        <div className="text-secondary small py-2">{empty}</div>
      ) : (
        <div className="d-flex flex-column gap-2">{children}</div>
      )}
    </div>
  );
}

function Row({ c, myEmail, onOpen, onClaim }: {
  c: CallMeta;
  myEmail?: string;
  onOpen: (id: string) => void;
  onClaim: (id: string) => void;
}) {
  const score = c.live ? (c.anger_now ?? null) : (c.max_anger ?? null);
  return (
    <div
      className="dash-row d-flex align-items-center gap-3 border rounded bg-body px-3 py-2"
      data-testid={`call-${c.contact_id}`}
      onClick={() => onOpen(c.contact_id)}
      role="button"
    >
      <span className={`dot ${c.live ? "live" : ""}`} />
      <div style={{ width: 110 }} className="flex-shrink-0">
        <div className="fw-semibold small font-monospace">{shortId(c.contact_id)}</div>
        <div className="text-secondary" style={{ fontSize: 11 }}>
          {day(c.started_at)} {clock(c.started_at)} · {c.message_count ?? 0}件
        </div>
      </div>
      <div style={{ width: 150 }} className="flex-shrink-0" onClick={(e) => e.stopPropagation()}>
        {c.owner_email ? (
          <span
            className={`badge rounded-pill ${c.owner_email === myEmail ? "text-bg-primary" : "text-bg-secondary"}`}
            title={c.owner_email}
          >
            {c.owner_email === myEmail ? "自分が担当" : c.owner_email.split("@")[0]}
          </span>
        ) : c.live ? (
          <button
            className="btn btn-sm btn-outline-primary py-0"
            style={{ fontSize: 12 }}
            onClick={() => onClaim(c.contact_id)}
          >
            取る
          </button>
        ) : (
          <span className="text-secondary small">—</span>
        )}
      </div>
      <div className="flex-shrink-0 d-flex align-items-center gap-2" style={{ width: 170 }}>
        <div className="gauge flex-grow-1">
          <div
            className="gauge-bar"
            style={{ width: `${score ?? 0}%`, background: angerColor(score ?? 0) }}
          />
        </div>
        <span
          className="fw-bold font-monospace"
          style={{ width: 28, color: score == null ? undefined : angerColor(score) }}
        >
          {score ?? "—"}
        </span>
      </div>
      <div className="text-truncate small text-secondary flex-grow-1">
        {c.live ? c.reason_now || "" : c.summary || ""}
      </div>
      {!c.live && c.max_anger != null && c.max_anger >= 70 && (
        <span className="badge rounded-pill text-danger border border-danger bg-danger-subtle flex-shrink-0">
          怒り {c.max_anger}
        </span>
      )}
    </div>
  );
}
