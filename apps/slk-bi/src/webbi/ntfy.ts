import type { IngestedMessage, NtfyDeliveryTarget, WebBiNotifier } from "./worker";

function endpoint(target: NtfyDeliveryTarget) {
  return `${target.settings.server_url.replace(/\/$/, "")}/${encodeURIComponent(target.settings.topic)}`;
}

function authorization(target: NtfyDeliveryTarget) {
  if (target.settings.auth_mode === "token" && target.secret) {
    return `Bearer ${target.secret}`;
  }
  if (target.settings.auth_mode === "password" && target.settings.username && target.secret) {
    return `Basic ${btoa(`${target.settings.username}:${target.secret}`)}`;
  }
  return undefined;
}

async function publish(
  target: NtfyDeliveryTarget,
  body: string,
  title: string,
) {
  const headers = new Headers({
    "content-type": "text/plain; charset=utf-8",
    title,
    tags: "information_source",
  });
  const auth = authorization(target);
  if (auth) headers.set("authorization", auth);
  const response = await fetch(endpoint(target), { method: "POST", headers, body });
  if (!response.ok) throw new Error(`SLK_WEBBI_NTFY_REJECTED:${response.status}`);
}

export class NtfyNotifier implements WebBiNotifier {
  async send(target: NtfyDeliveryTarget, record: IngestedMessage) {
    const scope = [record.message.go_id, record.message.cell_id]
      .filter(Boolean)
      .join(" · ");
    await publish(
      target,
      [
        `${record.run.summary.run_name} · ${record.message.label_zh}`,
        `${record.message.author_role}${scope ? ` · ${scope}` : ""}`,
        `设备：${record.device.device_name} (${record.device.device_id})`,
      ].join("\n"),
      `SLK · ${record.run.summary.run_name}`,
    );
  }

  async test(target: NtfyDeliveryTarget) {
    await publish(target, "WebBI 1.1.0 的 ntfy 配置测试成功。", "SLK WebBI 测试");
  }
}
