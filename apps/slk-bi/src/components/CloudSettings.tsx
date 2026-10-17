import { useEffect, useState, type FormEvent } from "react";
import type { SlkApi, WebBiSettings } from "../api";

export function CloudSettings({ api, onSaved }: { api: SlkApi; onSaved: () => void }) {
  const [settings, setSettings] = useState<WebBiSettings>();
  const [token, setToken] = useState(""); const [error, setError] = useState<string>(); const [saving, setSaving] = useState(false);
  useEffect(() => {
    let active = true;
    void api.webBiSettings?.().then((value) => { if (active) setSettings(value); }).catch(() => { if (active) setError("无法读取云端设置"); });
    return () => { active = false; };
  }, [api]);
  if (!api.webBiSettings) return null;
  async function save(event: FormEvent) {
    event.preventDefault(); if (!settings || !api.saveWebBiSettings) return;
    setSaving(true); setError(undefined);
    try { setSettings(await api.saveWebBiSettings({ url: settings.url, device_id: settings.device_id, ...(token ? { token } : {}) })); setToken(""); onSaved(); }
    catch { setError("保存失败；请检查地址和授权。更换地址需重新填写授权。"); }
    finally { setSaving(false); }
  }
  return <form className="cloud-settings" onSubmit={(event) => void save(event)}>
    <h2>云端上传</h2>
    {settings ? <>
      <label>云端地址<input aria-label="云端地址" type="url" disabled={settings.sources.url === "environment"} value={settings.url} onChange={(event) => setSettings({ ...settings, url: event.target.value })} /></label>
      <label>上传授权<input aria-label="上传授权" type="password" autoComplete="off" disabled={settings.sources.token === "environment"} value={token} onChange={(event) => setToken(event.target.value)} placeholder={settings.has_token ? "留空保留已保存授权" : "尚未配置"} /></label>
      <label>稳定设备 ID<input aria-label="稳定设备 ID" disabled={settings.sources.device_id === "environment"} value={settings.device_id} onChange={(event) => setSettings({ ...settings, device_id: event.target.value })} required /></label>
      <p>环境变量优先：地址 {settings.sources.url === "environment" ? "环境变量" : "本机保存"} · 授权 {settings.sources.token === "environment" ? "环境变量" : "系统安全存储"} · ID {settings.sources.device_id === "environment" ? "环境变量" : "本机保存"}。更换 ID 会建立独立云端归属。</p>
      {settings.sources.token === "destination_mismatch" ? <p role="status">保存的授权属于其他云端地址。请为当前地址填写新授权，或设置 SLK_WEBBI_UPLOAD_TOKEN。</p> : null}
      <p>未配置不影响本地查看。BI 打开时约每 30 秒续传；关闭期间不后台上传。</p>
      <button type="submit" disabled={saving}>{saving ? "保存中…" : "保存云端设置"}</button>
    </> : <p>正在读取设置…</p>}
    {error ? <p role="alert">{error}</p> : null}
  </form>;
}
