import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BackgroundTransparency } from "./BackgroundTransparency";

const key = "le-bi:background-transparency:v1";
beforeEach(() => localStorage.clear());
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe.each(["desktop", "web"] as const)("%s background-only transparency", (surface) => {
  it("uses a standard 0–100 slider with one-percent steps and an opaque current value", () => {
    render(<BackgroundTransparency surface={surface} />);
    const slider = screen.getByRole("slider", { name: "背景透明度" });
    expect(slider).toHaveAttribute("type", "range");
    expect(slider).toHaveAttribute("min", "0");
    expect(slider).toHaveAttribute("max", "100");
    expect(slider).toHaveAttribute("step", "1");
    expect(slider).toHaveValue("20");
    expect(slider.closest("label")).not.toHaveAttribute("title");
    for (const level of [0, 1, 37, 99, 100]) {
      fireEvent.change(slider, { target: { value: String(level) } });
      expect(slider).toHaveValue(String(level));
      expect(slider).toHaveAttribute("aria-valuetext", `${level}%`);
      expect(screen.getByText(`${level}%`)).toBeVisible();
      expect(document.documentElement.style.getPropertyValue("--bi-surface-opacity")).toBe(`${100 - level}%`);
      expect(document.documentElement.style.opacity).toBe("");
      expect(slider.closest("label")!.style.opacity).toBe("");
      expect(slider).toBeEnabled();
      expect(localStorage.getItem(key)).toBe(String(level));
    }
    expect(document.documentElement.dataset.biSurface).toBe(surface);
  });

  it.each([0, 1, 20, 37, 40, 60, 80, 99, 100])("restores saved %i percent and the opaque fallback on unmount", (level) => {
    localStorage.setItem(key, String(level));
    const mounted = render(<BackgroundTransparency surface={surface} />);
    expect(screen.getByRole("slider", { name: "背景透明度" })).toHaveValue(String(level));
    expect(document.documentElement.style.getPropertyValue("--bi-surface-opacity")).toBe(`${100 - level}%`);
    mounted.unmount();
    expect(document.documentElement.dataset.biSurface).toBeUndefined();
    expect(document.documentElement.style.getPropertyValue("--bi-surface-opacity")).toBe("");
  });

  it.each([null, "", " ", "invalid", "NaN", "Infinity", "-1", "101", "37.5"])("defaults to 20 percent for missing or invalid storage %s", (stored) => {
    if (stored !== null) localStorage.setItem(key, stored);
    render(<BackgroundTransparency surface={surface} />);
    expect(screen.getByRole("slider", { name: "背景透明度" })).toHaveValue("20");
    expect(localStorage.getItem(key)).toBe("20");
  });

  it("remains usable when storage cannot be read or written", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    render(<BackgroundTransparency surface={surface} />);
    const slider = screen.getByRole("slider", { name: "背景透明度" });
    expect(slider).toHaveValue("20");
    fireEvent.change(slider, { target: { value: "100" } });
    expect(slider).toHaveValue("100");
    expect(document.documentElement.style.getPropertyValue("--bi-surface-opacity")).toBe("0%");
    fireEvent.change(slider, { target: { value: "37" } });
    expect(slider).toHaveValue("37");
  });
});
