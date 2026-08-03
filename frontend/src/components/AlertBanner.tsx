export function AlertBanner({ alert }: { alert: { score: number; reason: string } }) {
  return (
    <div className="text-white px-3 py-2" style={{ background: "#b3261e" }} data-testid="alert">
      <strong>⚠ 相手が強い怒りを示しています({alert.score})</strong>
      {alert.reason && <div style={{ fontSize: 13, opacity: 0.92 }}>{alert.reason}</div>}
    </div>
  );
}
