import type { CallMeta } from "../types";

/** 通話カード。切断後に1回だけ作られる対応記録で、JSONで持ち出せる。
    ※SVビュー向けの情報。PH4の応対者ビューには出さないこと(docs/roadmap.md 3.3) */
export function CardPanel({ meta }: { meta: CallMeta }) {
  const c = meta.card;
  if (!c) return null;
  const rows: [string, string][] = [];
  if (c.topic) rows.push(["用件", c.topic]);
  if (c.next_action) rows.push(["次アクション", c.next_action]);
  if (c.callback_needed) rows.push(["折り返し", c.callback_reason || "要"]);
  if (c.unresolved?.length) rows.push(["未解決", c.unresolved.join(" / ")]);

  return (
    <div className="border rounded bg-body mb-3 p-3" style={{ fontSize: 13 }} data-testid="card">
      <div className="d-flex align-items-baseline gap-2 mb-2">
        <span className="text-secondary fw-semibold" style={{ fontSize: 12 }}>通話カード</span>
        {c.harassment && (
          <span className="badge rounded-pill text-danger border border-danger bg-danger-subtle">
            カスハラの疑い
          </span>
        )}
        <a className="ms-auto small" href={`/api/history/${meta.contact_id}/card.json`}>
          JSONで保存
        </a>
      </div>
      <div className={rows.length ? "mb-2" : ""}>{c.summary}</div>
      {rows.length > 0 && (
        <dl className="row m-0">
          {rows.map(([k, v]) => (
            <div className="row m-0 p-0" key={k}>
              <dt className="col-auto text-secondary fw-normal" style={{ fontSize: 12, width: 90 }}>{k}</dt>
              <dd className="col m-0">{v}</dd>
            </div>
          ))}
        </dl>
      )}
      {c.harassment && c.harassment_quote && (
        <div className="quote mt-1">{c.harassment_quote}</div>
      )}
    </div>
  );
}
