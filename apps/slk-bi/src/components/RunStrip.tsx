import { useState } from "react";

import { formatDuration, type RunStripCell, type RunStripView } from "../runPresentation";

interface RunStripProps {
  view: RunStripView;
  archived?: boolean;
}

const MARK = {
  done: "✓",
  active: "●",
  wait: "○",
  exempt: "—",
  rework: "↺",
  blocked: "×",
} as const;

function groupTone(groupKey: string) {
  if (groupKey === "solo") return 0;
  let hash = 0;
  for (const character of groupKey) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  return (hash % 4) + 1;
}

function SegmentedProgress({ passed, total, tone }: { passed: number; total: number; tone: string }) {
  const segments = 8;
  const filled = total ? Math.round((passed / total) * segments) : 0;
  return (
    <span
      className="segmented-progress"
      role="progressbar"
      aria-label={`CELL 进度 ${passed}/${total}`}
      aria-valuemin={0}
      aria-valuemax={total}
      aria-valuenow={passed}
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

export function RunStrip({ view, archived = false }: RunStripProps) {
  const [open, setOpen] = useState(false);
  const progressTone = view.statusTone === "done" ? "done" : view.statusTone === "active" ? "active" : "wait";
  const tone = groupTone(view.sourceGroupKey);

  return (
    <li className={`slk-block group-${tone}${open ? " is-open" : ""}${archived ? " is-archived" : ""}`}>
      <button
        className="slk-row"
        type="button"
        aria-expanded={open}
        aria-label={`${open ? "收起" : "展开"} ${view.runName}`}
        onClick={() => setOpen((value) => !value)}
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
        <span className={`chevron${open ? " is-open" : ""}`} aria-hidden="true">▾</span>
      </button>

      {open ? (
        <div className="run-details">
          <dl className="role-strip" aria-label="参与角色">
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
          <ol className="cell-list" aria-label={`${view.runName} CELL 记录`}>
            {view.cells.map((cell) => <CellRow key={cell.id} cell={cell} />)}
          </ol>
        </div>
      ) : null}
    </li>
  );
}
