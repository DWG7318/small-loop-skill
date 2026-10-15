import { useLayoutEffect, useState } from "react";

const STORAGE_KEY = "le-bi:background-transparency:v1";

function isLevel(value: number) {
  return Number.isInteger(value) && value >= 0 && value <= 100;
}

function savedLevel() {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored !== null && stored.trim() !== "") {
      const value = Number(stored);
      if (isLevel(value)) return value;
    }
  } catch { /* A local display preference must not block BI. */ }
  return 20;
}

export function BackgroundTransparency({ surface }: { surface: "desktop" | "web" }) {
  const [level, setLevel] = useState(savedLevel);
  useLayoutEffect(() => {
    const root = document.documentElement;
    root.dataset.biSurface = surface;
    // Only background colors consume this alpha; never apply opacity to content.
    root.style.setProperty("--bi-surface-opacity", `${100 - level}%`);
    try { window.localStorage.setItem(STORAGE_KEY, String(level)); } catch { /* Keep the live selection usable. */ }
    return () => {
      delete root.dataset.biSurface;
      root.style.removeProperty("--bi-surface-opacity");
    };
  }, [level, surface]);

  return <label className="background-transparency">
    <span>背景透明度</span>
    <input type="range" aria-label="背景透明度" aria-valuetext={`${level}%`}
      min={0} max={100} step={1} value={level} onChange={(event) => {
      const next = Number(event.target.value);
      if (isLevel(next)) setLevel(next);
    }} />
    <span className="background-transparency-value">{level}%</span>
  </label>;
}
