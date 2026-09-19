import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

function BootShell() {
  return <main aria-label="SLK BI">SLK BI</main>;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BootShell />
  </StrictMode>,
);
