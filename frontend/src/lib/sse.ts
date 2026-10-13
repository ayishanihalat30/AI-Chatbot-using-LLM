export interface SSEEvent {
  event: string;
  data: unknown;
}

/** Incremental Server-Sent-Events parser. Feed it text chunks; it returns completed events. */
export function createSSEParser() {
  let buffer = "";
  return (chunk: string): SSEEvent[] => {
    buffer += chunk.replace(/\r\n/g, "\n");
    const out: SSEEvent[] = [];
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      let event = "message";
      const dataLines: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
      }
      if (!dataLines.length) continue;
      const raw = dataLines.join("\n");
      try {
        out.push({ event, data: JSON.parse(raw) });
      } catch {
        out.push({ event, data: raw });
      }
    }
    return out;
  };
}
