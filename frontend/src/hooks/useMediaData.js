import { useCallback, useEffect, useRef, useState } from 'react';

export default function useMediaData() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [snapshot, setSnapshot] = useState(null);
  const active = useRef(null);
  const timeoutRef = useRef(null);

  const fetchData = useCallback(async (refresh = false) => {
    clearTimeout(timeoutRef.current);
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    const timeout = setTimeout(() => controller.abort('timeout'), 300000);
    timeoutRef.current = timeout;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(refresh ? '/api/media?refresh=true' : '/api/media', { signal: controller.signal });
      if (controller.signal.aborted) return;
      const body = await response.json();
      if (active.current !== controller || controller.signal.aborted) return;
      if (!response.ok) throw new Error(body.error || 'Unable to load media. Please try again.');
      if (!Array.isArray(body)) throw new Error('The server returned an invalid media list.');
      setData(body);
      const inProgress = response.headers.get('X-Scan-In-Progress') === 'true';
      setSnapshot({ scannedAt: response.headers.get('X-Scanned-At'), stale: response.headers.get('X-Cache-Stale') === 'true',
        skipped: Number(response.headers.get('X-Skipped-Records') || 0), inProgress });
      setError(response.headers.get('X-Refresh-Error') || (inProgress ? 'A scan is already running. Showing the last snapshot; retry shortly.' : null));
    } catch (failure) {
      if (active.current !== controller) return;
      if (controller.signal.aborted && controller.signal.reason !== 'timeout') return;
      setError(controller.signal.reason === 'timeout' ? 'The request timed out. Please retry.' : failure.message || 'Unable to load media. Please retry.');
    } finally {
      clearTimeout(timeout);
      if (active.current === controller) setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    return () => { clearTimeout(timeoutRef.current); active.current?.abort(); active.current = null; };
  }, [fetchData]);

  return { data, loading, error, snapshot, reload: () => fetchData(true) };
}
