import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ImageUp, Star, Trash2 } from "lucide-react";
import { ChangeEvent, useRef } from "react";

import { apiRequest, appUrl } from "../../api/client";
import type { ProductAsset, ProductWorkspace } from "../../types";
import styles from "../../pages/WorkbenchPage.module.css";
import { uploadProductFiles } from "./api";

type Props = {
  workspace: ProductWorkspace;
  onAnalysisReady: () => void;
};

const angles = [
  ["front", "正面"],
  ["back", "背面"],
  ["left", "左侧"],
  ["right", "右侧"],
  ["top", "顶部"],
  ["detail", "细节"],
  ["package", "包装"],
  ["scene", "场景"],
  ["other", "其他"],
];

export function AssetStep({ workspace, onAnalysisReady }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["workspace", workspace.product.id] });
    void queryClient.invalidateQueries({ queryKey: ["products"] });
  };
  const upload = useMutation({
    mutationFn: (files: File[]) => uploadProductFiles(workspace.product.id, files),
    onSuccess: invalidate,
  });
  const updateAsset = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<ProductAsset> }) =>
      apiRequest(`/assets/${id}`, { method: "PATCH", body: patch }),
    onSuccess: invalidate,
  });
  const deleteAsset = useMutation({
    mutationFn: (id: string) => apiRequest(`/assets/${id}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
  const analyze = useMutation({
    mutationFn: () =>
      apiRequest(`/products/${workspace.product.id}/analysis`, {
        method: "POST",
        idempotent: true,
      }),
    onSuccess: () => {
      invalidate();
      onAnalysisReady();
    },
  });

  const chooseFiles = (event: ChangeEvent<HTMLInputElement>) => {
    const remaining = 8 - workspace.assets.length;
    const files = Array.from(event.target.files || []).slice(0, remaining);
    if (files.length) upload.mutate(files);
    event.target.value = "";
  };

  return (
    <section>
      <div className={styles.sectionHeader}>
        <div>
          <h2>商品参考图</h2>
          <p>{workspace.assets.length} / 8 张</p>
        </div>
        <button
          className="button secondary"
          onClick={() => inputRef.current?.click()}
          disabled={workspace.assets.length >= 8 || upload.isPending}
        >
          <ImageUp size={18} />
          {upload.isPending ? "上传处理中" : "批量上传"}
        </button>
        <input
          ref={inputRef}
          className="sr-only"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          multiple
          onChange={chooseFiles}
        />
      </div>

      <div className={styles.assetGrid}>
        {workspace.assets.map((asset) => (
          <article className={styles.assetCard} key={asset.id}>
            {asset.is_primary && <span className={styles.primaryBadge}>主参考图</span>}
            <img
              className={styles.assetImage}
              src={appUrl(asset.thumbnail_url)}
              alt={`${workspace.product.name} ${asset.angle}`}
            />
            <div className={styles.assetMeta}>
              <strong title={asset.name}>{asset.name}</strong>
              <div className={styles.assetControls}>
                <select
                  className={styles.compactSelect}
                  aria-label="图片角度"
                  value={asset.angle}
                  onChange={(event) =>
                    updateAsset.mutate({ id: asset.id, patch: { angle: event.target.value } })
                  }
                >
                  {angles.map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
                <button
                  className="icon-button"
                  title="设为主参考图"
                  disabled={asset.is_primary}
                  onClick={() => updateAsset.mutate({ id: asset.id, patch: { is_primary: true } })}
                >
                  <Star size={16} fill={asset.is_primary ? "currentColor" : "none"} />
                </button>
                <button
                  className="icon-button"
                  title="移入回收站"
                  onClick={() => deleteAsset.mutate(asset.id)}
                >
                  <Trash2 size={16} />
                </button>
              </div>
            </div>
          </article>
        ))}
        {workspace.assets.length < 8 && (
          <button className={styles.uploadBox} onClick={() => inputRef.current?.click()}>
            <ImageUp size={28} />
            <strong>添加商品图片</strong>
            <span>JPG、PNG、WebP</span>
          </button>
        )}
      </div>

      {(upload.error || updateAsset.error || deleteAsset.error || analyze.error) && (
        <div className={styles.errorBox} role="alert">
          {(upload.error || updateAsset.error || deleteAsset.error || analyze.error)?.message}
        </div>
      )}

      <div className={styles.actionBar}>
        <span>主参考图优先用于保持商品一致性</span>
        <button
          className="button"
          disabled={!workspace.assets.length || analyze.isPending}
          onClick={() => analyze.mutate()}
        >
          {analyze.isPending ? "正在识别商品" : "识别商品信息"}
        </button>
      </div>
    </section>
  );
}
