import { describe, expect, it } from "vitest";
import { createSSEParser } from "@/lib/sse";

describe("SSE parser", () => {
  it("parses complete events", () => {
    const p = createSSEParser();
    expect(p('event: token\ndata: "Hel"\n\nevent: token\ndata: "lo"\n\n')).toEqual([
      { event: "token", data: "Hel" },
      { event: "token", data: "lo" },
    ]);
  });

  it("handles events split across chunks and CRLF", () => {
    const p = createSSEParser();
    expect(p('event: done\r\ndata: {"a"')).toEqual([]);
    expect(p(":1}\r\n\r\n")).toEqual([{ event: "done", data: { a: 1 } }]);
  });

  it("preserves unicode and falls back to raw text for non-JSON", () => {
    const p = createSSEParser();
    expect(p('event: token\ndata: "നമസ്കാരം"\n\nevent: x\ndata: plain\n\n')).toEqual([
      { event: "token", data: "നമസ്കാരം" },
      { event: "x", data: "plain" },
    ]);
  });
});
