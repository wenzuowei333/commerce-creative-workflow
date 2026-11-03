import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { apiRequest, appUrl } from "../../api/client";
import type { GenerationBatch, HistoryResponse } from "../../types";

export const terminalBatchStates = new Set([
  "completed",
  "partial",
  "failed",
  "cancelled",
]);

export function useGenerationBatch(productId: string, promptPlanId?: string) {
  const queryClient = useQueryClient();
  const [batchId, setBatchId] = useState<string | null>(null);
  const latestHistory = useQuery({
    queryKey: ["history", "latest", productId],
    queryFn: () =>
      apiRequest<HistoryResponse>(`/history?product_id=${productId}&limit=1&offset=0`),
  });

  useEffect(() => {
    const latest = latestHistory.data?.items[0];
    if (!batchId && latest && latest.prompt_plan_id === promptPlanId) {
      setBatchId(latest.id);
    }
  }, [batchId, latestHistory.data?.items, promptPlanId]);

  const batch = useQuery({
    queryKey: ["generation-batch", batchId],
    queryFn: () => apiRequest<GenerationBatch>(`/generation-batches/${batchId}`),
    enabled: Boolean(batchId),
    refetchInterval: (query) => {
      const state = (query.state.data as GenerationBatch | undefined)?.state;
      return state && !terminalBatchStates.has(state) ? 3000 : false;
    },
  });

  useEffect(() => {
    if (!batchId || terminalBatchStates.has(batch.data?.state || "")) return;
    const stream = new EventSource(
      appUrl(`/api/v1/generation-batches/${batchId}/events`),
      { withCredentials: true },
    );
    const refresh = () => {
      void queryClient.invalidateQueries({ queryKey: ["generation-batch", batchId] });
      void queryClient.invalidateQueries({ queryKey: ["usage", "daily"] });
    };
    stream.addEventListener("batch_progress", refresh);
    stream.addEventListener("item_completed", refresh);
    stream.addEventListener("item_failed", refresh);
    // Keep native EventSource reconnection; polling also reads persisted state.
    stream.onerror = refresh;
    return () => stream.close();
  }, [batch.data?.state, batchId, queryClient]);

  return { batch, batchId, setBatchId };
}
