/** Tell the Release Graph (and anything listening) to re-fetch from the API. */
export const GRAPH_REFRESH_EVENT = "rg:graph-refresh";

export type GraphRefreshDetail = {
  projectId?: number;
  reason?: string;
};

export function notifyGraphRefresh(detail?: GraphRefreshDetail) {
  window.dispatchEvent(new CustomEvent<GraphRefreshDetail>(GRAPH_REFRESH_EVENT, { detail: detail ?? {} }));
}
