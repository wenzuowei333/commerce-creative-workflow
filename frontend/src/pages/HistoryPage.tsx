import { useMutation, useQuery } from "@tanstack/react-query";
import { Clock3, Download, Filter, RefreshCw, X } from "lucide-react";
import { FormEvent, useState } from "react";

import { apiRequest, appUrl } from "../api/client";
import { listProducts } from "../features/workbench/api";
import type { GenerationBatch, HistoryResponse } from "../types";
import styles from "./LibraryPages.module.css";

type HistoryDetail = GenerationBatch & {
  product: { id: string; name: string; sku: string };
  timeline: Array<{
    id: string;
    type: string;
    state: string;
    details: Record<string, unknown>;
    created_at: string;
  }>;
};

const eventLabels: Record<string, string> = {
  batch_queued: "任务已排队",
  item_generating: "开始生成图片",
  item_completed: "图片生成完成",
  item_failed: "图片生成失败",
  item_recovered: "中断任务已恢复",
  batch_progress: "批次进度更新",
};

export function HistoryPage() {
  const products = useQuery({ queryKey: ["products"], queryFn: listProducts });
  const [filters, setFilters] = useState({
    product_id: "",
    generation_type: "",
    state: "",
    date_from: "",
    date_to: "",
  });
  const [appliedFilters, setAppliedFilters] = useState(filters);
  const [detailId, setDetailId] = useState<string | null>(null);
  const history = useQuery({
    queryKey: ["history", appliedFilters],
    queryFn: () => {
      const params = new URLSearchParams({ limit: "50", offset: "0" });
      Object.entries(appliedFilters).forEach(([key, value]) => {
        if (value) params.set(key, value);
      });
      return apiRequest<HistoryResponse>(`/history?${params}`);
    },
  });
  const detail = useQuery({
    queryKey: ["history", "detail", detailId],
    queryFn: () => apiRequest<HistoryDetail>(`/history/${detailId}`),
    enabled: Boolean(detailId),
  });
  const download = useMutation({
    mutationFn: (imageIds: string[]) =>
      apiRequest<{ download_url: string }>("/downloads", {
        method: "POST",
        idempotent: true,
        body: { image_ids: imageIds },
      }),
    onSuccess: (bundle) => window.location.assign(appUrl(bundle.download_url)),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setAppliedFilters(filters);
  };

  return (
    <>
      <header className="page-header">
        <div>
          <h1>生成历史</h1>
          <p>查看批次结果与任务时间线</p>
        </div>
        <button className="button secondary" onClick={() => history.refetch()}>
          <RefreshCw size={17} />
          刷新
        </button>
      </header>

      <form className={styles.filters} onSubmit={submit}>
        <select
          className="field"
          value={filters.product_id}
          onChange={(event) => setFilters({ ...filters, product_id: event.target.value })}
        >
          <option value="">全部商品</option>
          {products.data?.map((product) => (
            <option key={product.id} value={product.id}>{product.name}</option>
          ))}
        </select>
        <select
          className="field"
          value={filters.generation_type}
          onChange={(event) => setFilters({ ...filters, generation_type: event.target.value })}
        >
          <option value="">全部类型</option>
          <option value="main">商品主图</option>
          <option value="detail">商品详情图</option>
        </select>
        <select
          className="field"
          value={filters.state}
          onChange={(event) => setFilters({ ...filters, state: event.target.value })}
        >
          <option value="">全部状态</option>
          <option value="queued">排队中</option>
          <option value="generating">生成中</option>
          <option value="completed">已完成</option>
          <option value="partial">部分完成</option>
          <option value="failed">失败</option>
          <option value="cancelled">已取消</option>
        </select>
        <input
          className="field"
          type="date"
          aria-label="开始日期"
          value={filters.date_from}
          onChange={(event) => setFilters({ ...filters, date_from: event.target.value })}
        />
        <input
          className="field"
          type="date"
          aria-label="结束日期"
          value={filters.date_to}
          onChange={(event) => setFilters({ ...filters, date_to: event.target.value })}
        />
        <button className="button" type="submit">
          <Filter size={17} />
          筛选
        </button>
      </form>

      {!history.data?.items.length ? (
        <div className="empty-state">
          <Clock3 size={34} />
          <h2>暂无生成记录</h2>
        </div>
      ) : (
        <div className={styles.historyTable}>
          {history.data.items.map((batch) => (
            <div className={styles.historyRow} key={batch.id}>
              <div className={styles.historyProduct}>
                <strong>{batch.product.name}</strong>
                <span>{batch.product.sku} · {batch.id.slice(0, 8)}</span>
              </div>
              <div className={styles.historyCell}>
                {batch.generation_type === "main" ? "商品主图" : "商品详情图"}
              </div>
              <span
                className={`status-pill ${batch.state === "completed" ? "success" : batch.state === "failed" ? "failed" : "warning"}`}
              >
                {batch.state}
              </span>
              <div className={styles.historyCell}>{batch.progress}%</div>
              <div className={styles.historyCell}>
                {new Date(batch.created_at).toLocaleString("zh-CN")}
              </div>
              <button className="button secondary" onClick={() => setDetailId(batch.id)}>
                查看
              </button>
            </div>
          ))}
        </div>
      )}

      {detailId && (
        <div className={styles.drawerBackdrop} onMouseDown={() => setDetailId(null)}>
          <aside className={styles.drawer} onMouseDown={(event) => event.stopPropagation()}>
            <div className={styles.drawerHeader}>
              <h2>任务详情</h2>
              <button className="icon-button" title="关闭" onClick={() => setDetailId(null)}>
                <X size={19} />
              </button>
            </div>
            {detail.data && (
              <>
                <div className={styles.historyProduct}>
                  <strong>{detail.data.product.name}</strong>
                  <span>{detail.data.product.sku} · {detail.data.id}</span>
                </div>
                <div className={styles.timeline}>
                  {detail.data.timeline.map((event) => (
                    <div className={styles.timelineItem} key={event.id}>
                      <span className={styles.timelineDot} />
                      <div className={styles.timelineText}>
                        <strong>{eventLabels[event.type] || event.type}</strong>
                        <span>{new Date(event.created_at).toLocaleString("zh-CN")}</span>
                      </div>
                    </div>
                  ))}
                </div>
                <div className={styles.drawerActions}>
                  <button
                    className="button"
                    disabled={!detail.data.items.some((item) => item.image)}
                    onClick={() =>
                      download.mutate(
                        detail.data!.items
                          .filter((item) => item.image)
                          .map((item) => item.image!.id),
                      )
                    }
                  >
                    <Download size={17} />
                    下载全部结果
                  </button>
                </div>
              </>
            )}
          </aside>
        </div>
      )}
    </>
  );
}
