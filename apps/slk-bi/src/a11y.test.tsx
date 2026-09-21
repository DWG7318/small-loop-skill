import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./App";
import { fixtureApi } from "./test/fixtures";

describe("SLK BI accessibility boundaries", () => {
  it("has a named main status surface and native window controls", async () => {
    render(<App api={fixtureApi} />);
    expect(await screen.findByRole("main", { name: "SLK Runs" })).toBeVisible();
    expect(screen.getByRole("list", { name: "进行中的 SLK Runs" })).toBeVisible();
    for (const name of ["归档箱", "置顶", "最小化", "关闭"]) {
      expect(screen.getByRole("button", { name })).toBeVisible();
    }
  });
});
