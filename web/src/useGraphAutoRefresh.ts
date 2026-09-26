import { useEffect } from "react";
import { GRAPH_REFRESH_EVENT, type GraphRefreshDetail } from "./graphRefresh";

const POLL_MS = 20_000;

/** Re-run callback on app actions, tab focus, visibility, and while the graph page is open. */
export function useGraphAutoRefresh(projectId: number, onRefresh: () => void) {
  useEffect(() => {
    const handler = (e: Event) => {
      const d = (e as CustomEvent<GraphRefreshDetail>).detail;
      if (d?.projectId != null && d.projectId !== projectId) return;
      onRefresh();
    };
    window.addEventListener(GRAPH_REFRESH_EVENT, handler);
    return () => window.removeEventListener(GRAPH_REFRESH_EVENT, handler);
  }, [projectId, onRefresh]);

  useEffect(() => {
    const onFocus = () => onRefresh();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [onRefresh]);

  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState === "visible") onRefresh();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [onRefresh]);

  useEffect(() => {
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") onRefresh();
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [onRefresh]);
}
