import { formatDuration, type RunStripCell, type RunStripView } from "../runPresentation";

interface RunStripProps {
  view: RunStripView;
  archived?: boolean;
  unread?: boolean;
  open?: boolean;
  onToggle?: () => void;
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

function SegmentedProgress({ passed, total, tone }: { passed: number; total: number; tone: string }) {
  const segments = total <= 8 ? 8 : total <= 16 ? 16 : 24;
  const filled = total > 0
    ? passed >= total ? segments : Math.min(segments - 1, Math.floor((passed / total) * segments))
    : 0;
  return (
    <span
      className="segmented-progress"
      role="progressbar"
      aria-label={`CELL 进度 ${passed}/${total}`}
      aria-valuemin={0}
      aria-valuemax={total}
      aria-valuenow={passed}
      title={`CELL 进度比例概览 ${passed}/${total}，每格不对应具体 CELL`}
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

export function RunStrip({ view, archived = false, unread = false, open = false, onToggle }: RunStripProps) {
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
        <code className="work-time">{formatDuration(view.totalWorkMs)}</code>
        <SegmentedProgress passed={view.progress.passed} total={view.progress.total} tone={progressTone} />
        <code className="cell-progress">
          {view.progress.passed}/{view.progress.total} CELL
          {view.currentCellWorkMs ? ` · ${formatDuration(view.currentCellWorkMs)}` : ""}
        </code>
        <span className={`run-status status-${view.statusTone}`}>
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
            {[...view.cells].reverse().map((cell) => <CellRow key={cell.cellId} cell={cell} />)}
          </ol>
        </div>
      ) : null}
    </li>
  );
}
