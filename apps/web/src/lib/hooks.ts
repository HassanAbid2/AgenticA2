import { useCallback, useEffect, useRef, useState } from "react";

/** Loads data with explicit loading / error states and a reload function. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const reload = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      setData(await fnRef.current());
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { data, error, loading, reload, setData };
}

/** Server-Sent Events subscription (auto-reconnects; resumes from Last-Event-ID). */
export function useSSE(url: string | null, onEvent: (type: string, data: unknown) => void, types: string[] = ["message"]) {
  const cb = useRef(onEvent);
  cb.current = onEvent;
  useEffect(() => {
    if (!url) return;
    const es = new EventSource(url, { withCredentials: true });
    const handler = (ev: MessageEvent) => {
      try {
        cb.current(ev.type, JSON.parse(ev.data));
      } catch {
        cb.current(ev.type, ev.data);
      }
    };
    types.forEach((t) => es.addEventListener(t, handler as EventListener));
    es.addEventListener("end", () => es.close());
    return () => es.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);
}

export const money = (n?: number | null, unit?: string | null) =>
  n == null ? "-" : `$${n.toLocaleString(undefined, { maximumFractionDigits: unit === "hourly" ? 2 : 0 })}${unit === "hourly" ? "/h" : ""}`;

export const pct = (n?: number | null) => (n == null ? "-" : `${Math.round(n * 100)}%`);
