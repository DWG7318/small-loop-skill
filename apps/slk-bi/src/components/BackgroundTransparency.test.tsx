import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BackgroundTransparency } from "./BackgroundTransparency";

const key = "le-bi:background-transparency:v1";
beforeEach(() => localStorage.clear());
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("background-only transparency", () => {
  it.each(["desktop", "web"] as const)("offers the same four steps on %s without fading content", (surface) => {
    render(<BackgroundTransparency surface={surface} />);
    const select = screen.getByRole("combobox", { name: "背景透明度" });
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual(["20%", "40%", "60%", "80%"]);
    expect(select).toHaveValue("20");
    for (const level of [20, 40, 60, 80]) {
      fireEvent.change(select, { target: { value: String(level) } });
      expect(document.documentElement.style.getPropertyValue("--bi-surface-opacity")).toBe(`${100 - level}%`);
      expect(document.documentElement.style.opacity).toBe("");
      expect(localStorage.getItem(key)).toBe(String(level));
    }
    expect(document.documentElement.dataset.biSurface).toBe(surface);
  });

  it("restores the last choice and restores the opaque fallback when unmounted", () => {
    localStorage.setItem(key, "60");
    const mounted = render(<BackgroundTransparency surface="desktop" />);
    expect(screen.getByRole("combobox", { name: "背景透明度" })).toHaveValue("60");
    mounted.unmount();
    expect(document.documentElement.dataset.biSurface).toBeUndefined();
    expect(document.documentElement.style.getPropertyValue("--bi-surface-opacity")).toBe("");
  });

  it("ignores invalid stored values and remains usable when storage is unavailable", () => {
    localStorage.setItem(key, "100");
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    render(<BackgroundTransparency surface="desktop" />);
    const select = screen.getByRole("combobox", { name: "背景透明度" });
    expect(select).toHaveValue("20");
    fireEvent.change(select, { target: { value: "80" } });
    expect(select).toHaveValue("80");
  });
});
