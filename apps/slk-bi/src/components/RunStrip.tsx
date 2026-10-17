import { formatDuration, formatCellProgress, type RunStripCell, type RunStripView } from "../runPresentation";
import type { RunView } from "../contracts";
import { CloseoutSummary } from "./CloseoutSummary";

interface RunStripProps {
  view: RunStripView;
  archived?: boolean;
  unread?: boolean;
  open?: boolean;
  onToggle?: () => void;
  run?: RunView;
  syncLabel?: string;
  savedAt?: string;
}

const MARK = {
  done: "✓",
  active: "●",
  wait: "○",
  exempt: "—",
  rework: "↺",
  blocked: "×",
} as const;

export function groupTone(groupKey: string) {
  let hash = 0;
  for (const character of groupKey) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  return (hash % 8) + 1;
}

function SegmentedProgress({ passed, total, tone, available = true }: { passed: number; total: number; tone: string; available?: boolean }) {
  const segments = Math.min(total, 30);
  const columns = Math.min(segments, 10);
  const filled = !available ? 0 : total <= 30
    ? Math.min(passed, segments)
    : passed >= total ? segments : Math.min(segments - 1, Math.floor((passed / total) * segments));
  return (
    <span
      className="segmented-progress"
      style={columns < 10 ? {
        gridTemplateColumns: columns ? `repeat(${columns}, minmax(0, 1fr))` : "none",
        // Keep the full-row 62 px / 2 px-gap geometry without empty tracks.
        width: Math.max(0, (64 * columns - 20) / 10),
      } : undefined}
      role={available ? "progressbar" : "img"}
      aria-label={available ? `CELL 进度 ${passed}/${total}` : `${total} CELL，D1 进度未提供`}
      aria-valuemin={available ? 0 : undefined}
      aria-valuemax={available ? total : undefined}
      aria-valuenow={available ? passed : undefined}
      title={!available ? `${total} CELL，D1 进度未提供` : total > 30
        ? `CELL 进度比例概览 ${passed}/${total}，30 格按比例显示，不对应具体 CELL`
        : `CELL 进度 ${passed}/${total}，每格代表 1 个 CELL 的完成数量`}
    >
      {Array.from({ length: segments }, (_, index) => (
        <span key={index} className={index < filled ? `segment segment-${tone}` : "segment"} />
      ))}
    </span>
  );
}

function CellRow({ cell }: { cell: RunStripCell }) {
  return (
    <li className={`cell-row cell-${cell.tone}`}>
      <span className="cell-mark" aria-hidden="true">{MARK[cell.tone]}</span>
      <code>{cell.id}</code>
      <span className="cell-copy">
        <strong>{cell.name}</strong>
        <span>{cell.note}</span>
      </span>
      <span className="cell-meta">{cell.meta}</span>
    </li>
  );
}

export function RunStrip({ view, archived = false, unread = false, open = false, onToggle, run, syncLabel, savedAt }: RunStripProps) {
  const progressTone = view.statusTone === "done" ? "done" : view.statusTone === "active" ? "active" : "wait";
  const tone = groupTone(view.sourceGroupKey);

  return (
    <li className={`slk-block group-${tone}${open ? " is-open" : ""}${archived ? " is-archived" : ""}`}>
      <button
        className="slk-row"
        type="button"
        aria-expanded={open}
        aria-label={`${open ? "收起" : "展开"} ${view.runName}`}
        onClick={onToggle}
      >
        <time dateTime={view.startDate}>{view.startDate}</time>
        <span className={`source source-${view.source.kind}`}>{view.source.label}</span>
        <span className="run-copy">
          <strong><span>{view.projectName}</span> · <span className="run-name">{view.runName}</span></strong>
          <span>{view.description}</span>
        </span>
        <code className="work-time" title={view.timingAvailable === false ? "来源未提供工作耗时" : undefined}>{view.timingAvailable === false ? "—" : formatDuration(view.totalWorkMs)}</code>
        <SegmentedProgress passed={view.progress.passed} total={view.progress.total} tone={progressTone} available={view.progressAvailable} />
        <code className="cell-progress">
          {formatCellProgress(view)}
          {view.currentCellWorkMs ? ` · ${formatDuration(view.currentCellWorkMs)}` : ""}
        </code>
        <span className={`run-status status-${view.statusTone}`} title={view.status}>
          <span aria-hidden="true">{MARK[view.statusTone]}</span> {view.status}
        </span>
        <code className="slk-version">SLK {view.slkVersion}</code>
        {unread ? <span className="unread-dot" aria-label="有新消息" title="有新消息" /> : <span className="unread-dot-slot" />}
        <span className={`chevron${open ? " is-open" : ""}`} aria-hidden="true">▾</span>
      </button>

      {open ? (
        <div className="run-details">
          <dl className="role-strip" data-role-count={view.roles.length} aria-label="参与角色">
            {view.roles.map((role) => (
              <div key={role.role}>
                <dt>{role.role.toUpperCase()}</dt>
                <dd>
                  <strong>{role.agent}</strong>
                  <code><span className="role-model">{role.model}</span>{role.reasoning ? ` · ${role.reasoning}` : ""}</code>
                </dd>
              </div>
            ))}
          </dl>
          {view.overwatcher ? (
            <div className={`overwatch-status status-${view.overwatcher.tone}`} aria-label="Overwatcher 运行保障状态">
              <strong>OVERWATCHER · {view.overwatcher.label}</strong>
              <code>{view.overwatcher.detail}</code>
            </div>
          ) : null}
          <ol className="cell-list" tabIndex={0} aria-label={`${view.runName} CELL 记录`}>
            {view.cells.map((cell) => <CellRow key={cell.cellId} cell={cell} />)}
          </ol>
          {!view.cells.length ? <p className="quiet-empty">尚无施工记录</p> : null}
          {syncLabel ? <p className="run-upload-status">{syncLabel}</p> : null}
          {run ? <CloseoutSummary run={run} savedAt={savedAt} /> : null}
        </div>
      ) : null}
    </li>
  );
}
