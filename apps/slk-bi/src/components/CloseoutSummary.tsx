import type { RunView } from "../contracts";
import { deviceSignatureLabel } from "../closeout";

export function CloseoutSummary({ run, savedAt }: { run: RunView; savedAt?: string }) {
  const summary = run.closeout_summary;
  return <section className="closeout-summary" aria-label="结项总结">
    <p className="device-signature">{deviceSignatureLabel(run.device_signature)}</p>
    <h2>结项总结</h2>
    {summary ? <>
      <p className="closeout-provenance">{summary.authored_by} · <time dateTime={summary.recorded_at}>{summary.recorded_at}</time> · 修订 {summary.source_revision}</p>
      <div className="closeout-body" data-testid="closeout-body">{summary.body}</div>
    </> : <p>未提供</p>}
    {savedAt ? <p className="closeout-provenance">最后保存 <time dateTime={savedAt}>{savedAt}</time></p> : null}
  </section>;
}
