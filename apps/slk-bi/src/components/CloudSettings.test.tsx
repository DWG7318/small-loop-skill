import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { CloudSettings } from "./CloudSettings";
import { fixtureApi } from "../test/fixtures";
afterEach(cleanup);

it("uses native settings, clears secret after save and explains environment priority", async () => {
  const value = { url: "https://cloud.example.test", device_id: "stable-A", has_token: true, sources: { url: "environment", token: "secure_store", device_id: "saved" } };
  const saveWebBiSettings = vi.fn(async () => value); const refresh = vi.fn();
  render(<CloudSettings api={{ ...fixtureApi, webBiSettings: async () => value, saveWebBiSettings }} onSaved={refresh} />);
  const token = await screen.findByLabelText("上传授权"); fireEvent.change(token, { target: { value: "unit-test-token" } });
  fireEvent.click(screen.getByRole("button", { name: "保存云端设置" }));
  await waitFor(() => expect(refresh).toHaveBeenCalledOnce());
  expect(token).toHaveValue(""); expect(JSON.stringify(window.localStorage)).not.toContain("unit-test-token");
  expect(screen.getByText(/环境变量优先/)).toBeInTheDocument();
});

it("explains that a different destination needs its own token", async () => {
  const value = { url: "https://new.example.test", device_id: "stable-A", has_token: false, sources: { url: "environment", token: "destination_mismatch", device_id: "saved" } };
  render(<CloudSettings api={{ ...fixtureApi, webBiSettings: async () => value }} onSaved={() => undefined} />);
  expect(await screen.findByText(/保存的授权属于其他云端地址/)).toBeVisible();
  expect(screen.getByLabelText("上传授权")).toBeEnabled();
});
