import { useEffect, useState } from "react";

/** Current unix time in seconds, updated every `everyMs` (for "x seconds ago" labels). */
export function useNow(everyMs = 5000): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now() / 1000), everyMs);
    return () => window.clearInterval(id);
  }, [everyMs]);
  return now;
}
