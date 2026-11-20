import { describe, it, expect } from "vitest";
import { parseHash, buildHash, readInitial, writeHash } from "./tabHash";

describe("tabHash", () => {
  it("empty or unknown addresses open Home", () => {
    for (const h of ["", "#", "#/", "#/nope", "#/admin", "#home", "#/../x", undefined, null]) expect(parseHash(h)).toEqual({ tab: "home", league: null });
  });
  it("opens each real tab", () => {
    for (const t of ["home", "table", "fixtures", "results", "tournaments"]) expect(parseHash(`#/${t}`).tab).toBe(t);
  });
  it("keeps a plain league key on the Table tab only", () => {
    expect(parseHash("#/table/premier_league_men")).toEqual({ tab: "table", league: "premier_league_men" });
    expect(parseHash("#/results/premier_league_men").league).toBe(null);
  });
  it("rejects hostile league values", () => {
    for (const bad of ["<script>alert(1)</script>", "a b", "x".repeat(80), "../../etc", "%3Cimg", "javascript:alert(1)"]) expect(parseHash(`#/table/${bad}`).league).toBe(null);
  });
  it("builds clean addresses", () => {
    expect(buildHash("home", null)).toBe("");
    expect(buildHash("results", "premier_league_men")).toBe("#/results");
    expect(buildHash("table", "premier_league_men")).toBe("#/table/premier_league_men");
    expect(buildHash("table", "bad key")).toBe("#/table");
    expect(buildHash("evil", null)).toBe("");
  });
  it("round-trips", () => {
    for (const [t, l] of [["table", "super_league_women"], ["fixtures", null], ["tournaments", null]]) {
      expect(parseHash(buildHash(t, l))).toEqual({ tab: t, league: t === "table" ? l : null });
    }
  });
  it("writeHash replaces (no history spam), keeps path and query, and skips no-op writes", () => {
    const calls = [];
    const win = { location: { hash: "", pathname: "/", search: "?a=1" }, history: { state: null, replaceState: (s, t, url) => { calls.push(url); win.location.hash = url.slice(url.indexOf("#") >= 0 ? url.indexOf("#") : url.length); } } };
    writeHash("results", null, win);
    writeHash("results", null, win);
    writeHash("home", null, win);
    expect(calls).toEqual(["/?a=1#/results", "/?a=1"]);
  });
  it("never throws without a window", () => {
    expect(readInitial(null)).toEqual({ tab: "home", league: null });
    expect(() => writeHash("results", null, null)).not.toThrow();
  });
});
