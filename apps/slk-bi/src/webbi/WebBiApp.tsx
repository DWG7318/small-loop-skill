import {
  IconArrowLeft,
  IconBell,
  IconChevronRight,
  IconSearch,
} from "@tabler/icons-react";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import type { ProjectSummary, RoleProjection } from "../contracts";
import { catalogKey } from "../messages/catalog";
import type { MessageCatalogEntry } from "../messages/messageFeed";
import {
  acknowledgeDisplayedMessages,
  bootstrapReadMarker,
  hasUnreadMessages,
  mergeReadMarker,
  parseReadMarker,
  type ReadMarker,
} from "../messages/readMarkers";
import { buildRunStripView, type RunStripView } from "../runPresentation";
import { BI_VERSION } from "../version";
import type { NotificationSettingsInput } from "./contracts";
import type { PublicNotificationSettings } from "./notifications";
import type { WebBiArchiveRecord } from "./worker";
import { webBiApi, type WebBiApi } from "./webApi";
import "./webbi.css";

type Route = { kind: "list" } | { kind: "run"; deviceId: string; runId: string } | { kind: "settings" };

function routeFromHash(): Route {
  const parts = window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (parts[0] === "runs" && parts.length === 3) {
    return { kind: "run", deviceId: decodeURIComponent(parts[1]!), runId: decodeURIComponent(parts[2]!) };
  }
  if (parts[0] === "settings") return { kind: "settings" };
  return { kind: "list" };
}

function runHref(record: WebBiArchiveRecord) {
  return `#/runs/${encodeURIComponent(record.device.device_id)}/${encodeURIComponent(record.run.run_id)}`;
}

function recordKey(record: WebBiArchiveRecord) {
  return `${record.device.device_id}:${record.run.run_id}`;
}

function readKey(record: WebBiArchiveRecord) {
  return `le-webbi:1.1:read:${record.device.device_id}:${record.run.run_id}`;
}

function projectFor(record: WebBiArchiveRecord): ProjectSummary {
  return {
    project_id: record.run.summary.project_id,
    name: record.run.summary.source_project_name?.trim() || record.run.summary.project_id,
    repository_url: null,
    last_known_path: "",
    run_count: 1,
  };
}

function display(record: WebBiArchiveRecord): RunStripView {
  return buildRunStripView(projectFor(record), record.run, new Date());
}

function roleLabel(role: RoleProjection["role"]) {
  return role === "supervisor" ? "Supervisor"
    : role === "checker" ? "Checker"
      : role === "worker" ? "Worker" : "Overwatcher";
}

function WebHeader() {
  return (
    <header className="webbi-header">
      <a className="webbi-brand" href="#/" aria-label="LE BI Run 一览">LE BI</a>
      <code>{BI_VERSION}</code>
      <span>Run 一览</span>
      <a className="webbi-settings-link" href="#/settings"><IconBell size={17} />手机通知</a>
    </header>
  );
}

function UnreadBadge() {
  return <span className="webbi-unread"><span aria-hidden="true" />有更新</span>;
}

function RunList({ api }: { api: WebBiApi }) {
  const [archived, setArchived] = useState(false);
  const [records, setRecords] = useState<WebBiArchiveRecord[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [markers, setMarkers] = useState<Record<string, ReadMarker>>({});

  const refresh = useCallback(async () => {
    try {
      const next = await api.listRuns(archived);
      setRecords(next);
      setError(undefined);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  }, [api, archived]);

  useEffect(() => {
    setLoading(true);
    void refresh();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, 30_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    setMarkers((current) => {
      const next = { ...current };
      for (const record of records) {
        const key = recordKey(record);
        const ids = record.messages.map(({ message_id }) => message_id);
        const stored = next[key] ?? parseReadMarker(window.localStorage.getItem(readKey(record)));
        next[key] = stored ? mergeReadMarker(stored, ids) : bootstrapReadMarker(ids);
        window.localStorage.setItem(readKey(record), JSON.stringify(next[key]));
      }
      return next;
    });
  }, [records]);

  function unread(record: WebBiArchiveRecord) {
    const marker = markers[recordKey(record)];
    return marker ? hasUnreadMessages(marker, record.messages.map(({ message_id }) => message_id)) : false;
  }

  function acknowledge(record: WebBiArchiveRecord) {
    const key = recordKey(record);
    const marker = acknowledgeDisplayedMessages(
      markers[key] ?? bootstrapReadMarker([]),
      record.messages.map(({ message_id }) => message_id),
    );
    window.localStorage.setItem(readKey(record), JSON.stringify(marker));
    setMarkers((current) => ({ ...current, [key]: marker }));
  }

  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) return records;
    return records.filter((record) => {
      const run = record.run.summary;
      return [run.run_name, run.run_description, run.project_id, record.device.device_id, record.device.device_name]
        .some((value) => value.toLocaleLowerCase().includes(needle));
    });
  }, [query, records]);

  return (
    <main className="webbi-page">
      <section className="webbi-page-intro">
        <h1>Run 一览</h1>
        <p>{archived ? "已归档的 Run 永久保留，只读查看。" : "来自各台已登记电脑的进行中 Run；每个 Run 独立保存。"}</p>
      </section>
      <label className="webbi-search">
        <span className="sr-only">搜索 Run</span><IconSearch size={18} aria-hidden="true" />
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索项目、Run 或电脑 ID" />
      </label>
      <div className="webbi-list-controls">
        <div className="webbi-segmented" aria-label="Run 状态">
          <button type="button" aria-pressed={!archived} onClick={() => setArchived(false)}>进行中</button>
          <button type="button" aria-pressed={archived} onClick={() => setArchived(true)}>已归档</button>
        </div>
        <span>{filtered.length} 个 Run</span>
      </div>
      {error ? <p className="webbi-error">读取失败：{error}</p> : null}
      {loading && !records.length ? <p className="webbi-empty">正在读取…</p> : null}
      {!loading && !filtered.length ? <p className="webbi-empty">没有匹配的 Run</p> : null}
      <ol className="webbi-run-list">
        {filtered.map((record) => {
          const view = display(record);
          return (
            <li key={recordKey(record)}>
              <a href={runHref(record)} onClick={() => acknowledge(record)} aria-label={`${view.runName}，查看详情`}>
                <span className="webbi-run-main">
                  <small>{view.projectName}</small>
                  <strong>{view.runName}</strong>
                  <span>{view.description}</span>
                </span>
                <span className="webbi-run-signals">
                  {unread(record) ? <UnreadBadge /> : null}
                  <span className={`webbi-status tone-${view.statusTone}`}>{view.status}</span>
                </span>
                <span className="webbi-run-meta">
                  <b>{view.progress.passed}/{view.progress.total} CELL</b>
                  <span>{view.totalWorkMs ? `${Math.floor(view.totalWorkMs / 60_000)}m` : "0m"}</span>
                  <span>SLK {view.slkVersion}</span>
                </span>
                <code className="webbi-device">电脑 {record.device.device_name} · {record.device.device_id}</code>
                <IconChevronRight className="webbi-open" size={21} aria-hidden="true" />
              </a>
            </li>
          );
        })}
      </ol>
    </main>
  );
}

function RunDetail({ api, deviceId, runId }: { api: WebBiApi; deviceId: string; runId: string }) {
  const [record, setRecord] = useState<WebBiArchiveRecord>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const next = await api.getRun(deviceId, runId);
        if (active) { setRecord(next); setError(undefined); }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : String(reason));
      }
    };
    void refresh();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, 30_000);
    return () => { active = false; window.clearInterval(timer); };
  }, [api, deviceId, runId]);

  if (error) return <main className="webbi-page"><a className="webbi-back" href="#/"><IconArrowLeft size={18} />返回</a><p className="webbi-error">读取失败：{error}</p></main>;
  if (!record) return <main className="webbi-page"><p className="webbi-empty">正在读取…</p></main>;
  const view = display(record);
  return (
    <main className="webbi-page">
      <a className="webbi-back" href="#/"><IconArrowLeft size={18} />返回 Run 一览</a>
      <section className="webbi-detail-head">
        <div><small>{view.projectName}</small><h1>{view.runName}</h1><p>{view.description}</p></div>
        <span className={`webbi-status tone-${view.statusTone}`}>{view.status}</span>
      </section>
      <dl className="webbi-detail-meta">
        <div><dt>电脑</dt><dd>{record.device.device_name} · {record.device.device_id}</dd></div>
        <div><dt>Run ID</dt><dd><code>{record.run.run_id}</code></dd></div>
        <div><dt>SLK</dt><dd>{view.slkVersion}</dd></div>
        <div><dt>D1 验收</dt><dd>{view.progress.passed}/{view.progress.total} CELL</dd></div>
      </dl>
      <div className="webbi-detail-grid">
        <section>
          <header className="webbi-section-head"><h2>CELL 记录</h2><small>来自电脑端 BI 同一投影</small></header>
          <ol className="webbi-cell-list">
            {view.cells.map((cell) => (
              <li key={cell.id}>
                <code>{cell.id}</code><div><strong>{cell.name}</strong><p>{cell.note}</p><small>{cell.meta}</small></div>
              </li>
            ))}
          </ol>
        </section>
        <section>
          <header className="webbi-section-head"><h2>团队登记</h2><small>{record.run.roles.length} 个角色</small></header>
          <ol className="webbi-role-list">
            {record.run.roles.map((role) => (
              <li key={role.role_instance_id}>
                <div><span>{roleLabel(role.role)}</span><strong>{role.agent_runtime}</strong></div>
                <code>{role.model}{role.reasoning ? ` · ${role.reasoning}` : ""}</code>
                <details><summary>身份信息</summary><dl>
                  <dt>实例</dt><dd>{role.role_instance_id}</dd><dt>平台</dt><dd>{role.provider}</dd><dt>Session</dt><dd>{role.session_id}</dd>
                </dl></details>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </main>
  );
}

function SettingsPage({ api }: { api: WebBiApi }) {
  const [catalog, setCatalog] = useState<readonly MessageCatalogEntry[]>([]);
  const [stored, setStored] = useState<PublicNotificationSettings>();
  const [draft, setDraft] = useState<NotificationSettingsInput>();
  const [notice, setNotice] = useState<string>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    void Promise.all([api.catalog(), api.getNotificationSettings()]).then(([entries, settings]) => {
      setCatalog(entries.filter(({ notification_eligible }) => notification_eligible));
      setStored(settings);
      setDraft({
        enabled: settings.enabled,
        server_url: settings.server_url,
        topic: settings.topic,
        auth_mode: settings.auth_mode,
        username: settings.username,
        selection_mode: settings.selection_mode,
        selected_message_types: settings.selected_message_types,
      });
    }).catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)));
  }, [api]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!draft) return;
    try {
      const saved = await api.saveNotificationSettings(draft);
      setStored(saved);
      setDraft((current) => current ? { ...current, secret: undefined } : current);
      setNotice("设置已保存");
      setError(undefined);
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
  }

  async function sendTest() {
    try {
      await api.testNotification();
      setNotice("测试消息已发送");
      setError(undefined);
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
  }

  function toggleType(key: string) {
    if (!draft) return;
    const selected = new Set(draft.selected_message_types);
    if (selected.has(key)) selected.delete(key); else selected.add(key);
    setDraft({ ...draft, selected_message_types: [...selected].sort() });
  }

  if (!draft || !stored) return <main className="webbi-page"><a className="webbi-back" href="#/"><IconArrowLeft size={18} />返回</a>{error ? <p className="webbi-error">读取失败：{error}</p> : <p className="webbi-empty">正在读取…</p>}</main>;
  return (
    <main className="webbi-page webbi-settings-page">
      <a className="webbi-back" href="#/"><IconArrowLeft size={18} />返回 Run 一览</a>
      <section className="webbi-page-intro"><h1>手机通知</h1><p>WebBI 只从 Agent 已标注的正式消息类型中筛选，再通过你的 ntfy 服务器发送。</p></section>
      <form className="webbi-settings" onSubmit={(event) => void submit(event)}>
        <label className="webbi-toggle"><input type="checkbox" checked={draft.enabled} onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })} /><span>启用 ntfy 通知</span></label>
        <div className="webbi-form-grid">
          <label>服务器地址<input aria-label="服务器地址" value={draft.server_url} onChange={(event) => setDraft({ ...draft, server_url: event.target.value })} /></label>
          <label>Topic 名称<input aria-label="Topic 名称" value={draft.topic} onChange={(event) => setDraft({ ...draft, topic: event.target.value })} /></label>
          <label>认证方式<select value={draft.auth_mode} onChange={(event) => setDraft({ ...draft, auth_mode: event.target.value as NotificationSettingsInput["auth_mode"] })}><option value="none">无</option><option value="token">Token</option><option value="password">账号密码</option></select></label>
          {draft.auth_mode === "password" ? <label>用户名<input aria-label="用户名" value={draft.username ?? ""} onChange={(event) => setDraft({ ...draft, username: event.target.value })} /></label> : null}
          {draft.auth_mode !== "none" ? <label>{draft.auth_mode === "password" ? "密码" : "Token"}<input aria-label={draft.auth_mode === "password" ? "密码" : "Token"} type="password" value={draft.secret ?? ""} onChange={(event) => setDraft({ ...draft, secret: event.target.value || undefined })} placeholder={stored.has_secret ? "同一服务器与账号留空保留" : draft.auth_mode === "password" ? "请输入密码" : "请输入 Token"} /><small>{stored.has_secret ? "已保存凭据；更换服务器、认证方式或账号需重新填写" : "尚未保存凭据"}</small></label> : null}
        </div>
        <fieldset>
          <legend>发送范围</legend>
          <label><input type="radio" name="selection" checked={draft.selection_mode === "all"} onChange={() => setDraft({ ...draft, selection_mode: "all" })} />全部正式新消息</label>
          <label><input type="radio" name="selection" checked={draft.selection_mode === "selected"} onChange={() => setDraft({ ...draft, selection_mode: "selected" })} />只发送勾选类型</label>
        </fieldset>
        {draft.selection_mode === "selected" ? <div className="webbi-message-types">
          {catalog.map((entry) => {
            const key = catalogKey(entry.source_kind, entry.message_type);
            return <label key={key}><input type="checkbox" checked={draft.selected_message_types.includes(key)} onChange={() => toggleType(key)} /><span><b>{entry.label_zh}</b><code>{key}</code></span></label>;
          })}
        </div> : null}
        {error ? <p className="webbi-error">操作失败：{error}</p> : null}{notice ? <p className="webbi-success">{notice}</p> : null}
        <div className="webbi-form-actions"><button type="submit">保存设置</button><button type="button" className="secondary" onClick={() => void sendTest()}>发送测试消息</button></div>
      </form>
    </main>
  );
}

export function WebBiApp({ api = webBiApi }: { api?: WebBiApi }) {
  const [route, setRoute] = useState<Route>(() => routeFromHash());
  useEffect(() => {
    const changed = () => setRoute(routeFromHash());
    window.addEventListener("hashchange", changed);
    return () => window.removeEventListener("hashchange", changed);
  }, []);
  return <div className="webbi-shell"><WebHeader />{route.kind === "settings" ? <SettingsPage api={api} /> : route.kind === "run" ? <RunDetail api={api} deviceId={route.deviceId} runId={route.runId} /> : <RunList api={api} />}<footer className="webbi-footer"><strong>slk.lcsp.work</strong><span>WebBI 只读在线存档 · 每个 Run 独立保留</span></footer></div>;
}
