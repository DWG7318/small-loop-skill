import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

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
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      {screen}
    </StrictMode>,
  );
}

void bootstrap();
