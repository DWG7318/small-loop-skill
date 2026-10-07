import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { InterfaceFailure, InterfaceLoading, UiFailureBoundary } from "./components/AppState";
import "./styles/tokens.css";
import "./styles/app.css";

const rootElement = document.getElementById("root");
if (!rootElement) throw new Error("SLK_BI_ROOT_MISSING");
const root = createRoot(rootElement);
root.render(<StrictMode><InterfaceLoading /></StrictMode>);

async function bootstrap() {
  const desktop = "__TAURI_INTERNALS__" in window
    || (import.meta.env.DEV && new URLSearchParams(window.location.search).has("acceptance"));
  const acceptanceApi =
    import.meta.env.DEV && new URLSearchParams(window.location.search).has("acceptance")
      ? (await import("./test/fixtures")).fixtureApi
      : undefined;
  let screen;
  if (desktop) {
    const Desktop = (await import("./App")).App;
    screen = <Desktop api={acceptanceApi} />;
  } else {
    const Web = (await import("./webbi/WebBiApp")).WebBiApp;
    const webApi = import.meta.env.DEV && new URLSearchParams(window.location.search).has("webbi-acceptance")
      ? (await import("./webbi/testFixtures")).webBiFixtureApi
      : undefined;
    screen = <Web api={webApi} />;
  }
  root.render(
    <StrictMode>
      <UiFailureBoundary>{screen}</UiFailureBoundary>
    </StrictMode>,
  );
}

void bootstrap().catch((error: unknown) => {
  console.error("SLK_BI_BOOTSTRAP_FAILED", error);
  root.render(
    <StrictMode>
      <InterfaceFailure detail="SLK_BI_BOOTSTRAP_FAILED" />
    </StrictMode>,
  );
});
