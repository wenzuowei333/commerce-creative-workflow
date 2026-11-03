import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, ImageDown, Save, SlidersHorizontal } from "lucide-react";
import { useMemo, useState } from "react";

import { apiRequest, appUrl } from "../../api/client";
import { useSystemInfo } from "../system/api";
import type { GeneratedImage, GenerationBatch, ProductWorkspace } from "../../types";
import commonStyles from "../../pages/WorkbenchPage.module.css";
import { GenerationGallery } from "./GenerationGallery";
import { GenerationProgress } from "./GenerationProgress";
import styles from "./GenerationStep.module.css";
import { useGenerationBatch } from "./useGenerationBatch";

type Props = {
  workspace: ProductWorkspace;
};

type RevisionResult = {
  id: string;
  parent_image_id: string;
  child_image: GeneratedImage;
};

function statusLabel(state: string): string {
  if (state === "completed") return "已完成";
  if (state === "partial") return "部分完成";
  if (state === "failed") return "生成失败";
  return "生成中";
}

export function GenerationStep({ workspace }: Props) {
  const plan = workspace.latest_prompt_plan;
  const system = useSystemInfo();
  const queryClient = useQueryClient();
  const { batch, batchId, setBatchId } = useGenerationBatch(
    workspace.product.id,
    plan?.id,
  );
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [revisionInstruction, setRevisionInstruction] = useState("");
  const [templateName, setTemplateName] = useState("");

  const refreshBatch = () =>
    queryClient.invalidateQueries({ queryKey: ["generation-batch", batchId] });
  const refreshUsage = () =>
    queryClient.invalidateQueries({ queryKey: ["usage", "daily"] });
  const start = useMutation({
    mutationFn: () =>
      apiRequest<GenerationBatch>("/generation-batches", {
        method: "POST",
        idempotent: true,
        body: { prompt_plan_id: plan?.id },
      }),
    onSuccess: (created) => {
      setBatchId(created.id);
      queryClient.setQueryData(["generation-batch", created.id], created);
      void queryClient.invalidateQueries({ queryKey: ["history"] });
      void refreshUsage();
    },
  });
  const retry = useMutation({
    mutationFn: () =>
      apiRequest<GenerationBatch>(`/generation-batches/${batchId}/retry-failed`, {
        method: "POST",
        idempotent: true,
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(["generation-batch", batchId], updated);
      void refreshUsage();
    },
  });
  const revise = useMutation({
    mutationFn: () =>
      apiRequest<RevisionResult[]>("/image-revisions", {
        method: "POST",
        idempotent: true,
        body: { image_ids: Array.from(selected), instruction: revisionInstruction },
      }),
    onSuccess: () => {
      setSelected(new Set());
      setRevisionInstruction("");
      void refreshBatch();
      void refreshUsage();
    },
  });
  const finalize = useMutation({
    mutationFn: (imageId: string) =>
      apiRequest<RevisionResult>(`/images/${imageId}/finalize`, {
        method: "POST",
        idempotent: true,
      }),
    onSuccess: () => {
      void refreshBatch();
      void refreshUsage();
    },
  });
  const saveTemplate = useMutation({
    mutationFn: () =>
      apiRequest("/templates", {
        method: "POST",
        idempotent: true,
        body: {
          name: templateName || `${workspace.product.name}视觉模板`,
          prompt_plan_id: plan?.id,
        },
      }),
    onSuccess: () => {
      setTemplateName("");
      void queryClient.invalidateQueries({ queryKey: ["templates"] });
    },
  });
  const download = useMutation({
    mutationFn: () =>
      apiRequest<{ download_url: string }>("/downloads", {
        method: "POST",
        idempotent: true,
        body: { image_ids: Array.from(selected) },
      }),
    onSuccess: (bundle) => window.location.assign(appUrl(bundle.download_url)),
  });

  const current = batch.data;
  const completedImages = useMemo(
    () => current?.items.filter((item) => item.state === "completed" && item.image) || [],
    [current?.items],
  );
  const error =
    start.error || retry.error || revise.error || finalize.error || saveTemplate.error || download.error;
  const toggleSelected = (imageId: string) => {
    setSelected((previous) => {
      const next = new Set(previous);
      if (next.has(imageId)) next.delete(imageId);
      else next.add(imageId);
      return next;
    });
  };

  if (!plan || plan.state !== "confirmed") {
    return (
      <div className="empty-state">
        <SlidersHorizontal size={30} />
        <h2>提示词尚未确认</h2>
      </div>
    );
  }

  return (
    <section>
      <div className={commonStyles.sectionHeader}>
        <div>
          <h2>生成商品图片</h2>
          <p>
            {plan.generation_type === "main" ? "商品主图" : "商品详情图"} · {plan.image_count} 张
          </p>
        </div>
        {current && (
          <span
            className={`status-pill ${current.state === "completed" ? "success" : current.state === "failed" ? "failed" : "warning"}`}
          >
            {statusLabel(current.state)}
          </span>
        )}
      </div>

      {!current && (
        <div className="empty-state">
          <ImageDown size={34} />
          <h2>提示词已确认</h2>
          <button className="button" disabled={start.isPending} onClick={() => start.mutate()}>
            {start.isPending ? "正在创建任务" : `开始生成 ${plan.image_count} 张`}
          </button>
        </div>
      )}

      {current && (
        <>
          <GenerationProgress
            batch={current}
            isRetrying={retry.isPending}
            onRetry={() => retry.mutate()}
          />
          <GenerationGallery
            batch={current}
            completedItems={completedImages}
            selected={selected}
            allowFinalize={system.features.hd_finalize}
            onToggle={toggleSelected}
            onFinalize={(imageId) => finalize.mutate(imageId)}
          />
          {completedImages.length > 0 && (
            <>
              <div className={styles.batchActions}>
                {system.features.image_revisions ? (
                  <>
                    <input
                      className="field"
                      value={revisionInstruction}
                      onChange={(event) => setRevisionInstruction(event.target.value)}
                      placeholder="输入统一调整意见"
                    />
                    <button
                      className="button secondary"
                      disabled={
                        !selected.size || !revisionInstruction.trim() || revise.isPending
                      }
                      onClick={() => revise.mutate()}
                    >
                      <SlidersHorizontal size={17} />
                      调整 {selected.size || "所选"} 张
                    </button>
                  </>
                ) : (
                  <>
                    <span />
                    <span />
                  </>
                )}
                <button
                  className="button secondary"
                  disabled={!selected.size || download.isPending}
                  onClick={() => download.mutate()}
                >
                  <Download size={17} />
                  下载所选
                </button>
              </div>
              {system.features.templates && (
                <div className={styles.batchActions}>
                  <input
                    className="field"
                    value={templateName}
                    onChange={(event) => setTemplateName(event.target.value)}
                    placeholder="模板名称"
                  />
                  <button className="button secondary" onClick={() => saveTemplate.mutate()}>
                    <Save size={17} />
                    保存为模板
                  </button>
                  <span />
                </div>
              )}
            </>
          )}
        </>
      )}

      {error && (
        <div className={commonStyles.errorBox} role="alert">
          {error.message}
        </div>
      )}
    </section>
  );
}
