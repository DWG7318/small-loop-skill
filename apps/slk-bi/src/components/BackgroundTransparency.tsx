import { useLayoutEffect, useState } from "react";

const LEVELS = [20, 40, 60, 80] as const;
const STORAGE_KEY = "le-bi:background-transparency:v1";

function savedLevel() {
  try {
    const value = Number(window.localStorage.getItem(STORAGE_KEY));
    if (LEVELS.some((level) => level === value)) return value;
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

  return <label className="background-transparency" title={surface === "desktop"
    ? "仅框体和背景透明，文字与图标保持不透明"
    : "仅框体和背景透出页面底色，文字与图标保持不透明"}>
    <span>背景透明度</span>
    <select aria-label="背景透明度" value={level} onChange={(event) => {
      const next = Number(event.target.value);
      if (LEVELS.some((item) => item === next)) setLevel(next);
    }}>
      {LEVELS.map((item) => <option key={item} value={item}>{item}%</option>)}
    </select>
  </label>;
}
