import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./styles/tokens.css";
import "./styles/app.css";

async function bootstrap() {
  const acceptanceApi =
    import.meta.env.DEV && new URLSearchParams(window.location.search).has("acceptance")
      ? (await import("./test/fixtures")).fixtureApi
      : undefined;
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App api={acceptanceApi} />
    </StrictMode>,
  );
}

void bootstrap();
