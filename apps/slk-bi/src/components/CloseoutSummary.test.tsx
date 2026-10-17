import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { CloseoutSummary } from "./CloseoutSummary";
import { runFixture } from "../test/fixtures";

it("renders the original formal record and explicit unknowns without HTML execution", () => {
  const body = "恢复原交接后完成\n\n<script>not executed</script>";
  render(<CloseoutSummary run={{ ...runFixture, closeout_summary: { body, authored_by: "supervisor-a", recorded_at: "2026-10-18T00:00:00Z", source_id: "source-1", source_revision: 1, content_sha256: "0".repeat(64) } }} />);
  expect(screen.getByText("未获取 · 未获取 · 未获取")).toBeInTheDocument();
  expect(screen.getByTestId("closeout-body").textContent).toBe(body);
  expect(document.querySelector("script")).toBeNull();
});
