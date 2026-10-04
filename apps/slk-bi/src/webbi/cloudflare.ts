import { MESSAGE_CATALOG } from "../messages/catalog";
import { D1WebBiStore, type D1Database } from "./d1Store";
import { NtfyNotifier } from "./ntfy";
import { createWebBiHandler } from "./worker";

interface AssetBinding {
  fetch(request: Request): Promise<Response>;
}

interface Environment {
  DB: D1Database;
  ASSETS: AssetBinding;
  WEBBI_INGEST_TOKEN: string;
  WEBBI_SETTINGS_ENCRYPTION_KEY: string;
}

export default {
  async fetch(request: Request, environment: Environment) {
    const url = new URL(request.url);
    if (!url.pathname.startsWith("/api/")) return environment.ASSETS.fetch(request);
    const handler = createWebBiHandler({
      store: new D1WebBiStore(environment.DB, environment.WEBBI_SETTINGS_ENCRYPTION_KEY),
      notifier: new NtfyNotifier(),
      catalog: MESSAGE_CATALOG,
      ingest_token: environment.WEBBI_INGEST_TOKEN,
    });
    return handler(request);
  },
};
