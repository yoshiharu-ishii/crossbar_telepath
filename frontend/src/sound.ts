// SV向けのアラート音。応対者には鳴らさない(通知はSVロールの属性)。
// WebAudioの発振器で作るので音源ファイルは持たない。

export function alertBeep(): void {
  try {
    const Ctx = window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.frequency.value = 880;
    gain.gain.value = 0.08;
    osc.start();
    osc.frequency.setValueAtTime(660, ctx.currentTime + 0.15);
    osc.stop(ctx.currentTime + 0.3);
    osc.onended = () => void ctx.close();
  } catch {
    /* 自動再生制限などで鳴らせなくても本体は動かす */
  }
}
