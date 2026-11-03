import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Image, ImageUp, RotateCcw, X } from "lucide-react";
import { ChangeEvent, useEffect, useRef, useState } from "react";

import { apiRequest, appUrl } from "../api/client";
import { getWorkspace, listProducts, uploadProductFiles } from "../features/workbench/api";
import type { ProductAsset } from "../types";
import styles from "./LibraryPages.module.css";

type RecycleEntry = {
  id: string;
  object_id: string;
  name: string;
  deleted_at: string;
  purge_after: string;
};

export function AssetsPage() {
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const products = useQuery({ queryKey: ["products"], queryFn: listProducts });
  const [productId, setProductId] = useState<string | null>(null);
  const [editing, setEditing] = useState<ProductAsset | null>(null);
  useEffect(() => {
    if (!productId && products.data?.length) setProductId(products.data[0].id);
  }, [productId, products.data]);
  const workspace = useQuery({
    queryKey: ["workspace", productId],
    queryFn: () => getWorkspace(productId!),
    enabled: Boolean(productId),
  });
  const recycle = useQuery({
    queryKey: ["recycle-bin"],
    queryFn: () => apiRequest<RecycleEntry[]>("/recycle-bin"),
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["workspace", productId] });
    void queryClient.invalidateQueries({ queryKey: ["products"] });
    void queryClient.invalidateQueries({ queryKey: ["recycle-bin"] });
  };
  const upload = useMutation({
    mutationFn: (files: File[]) => uploadProductFiles(productId!, files),
    onSuccess: refresh,
  });
  const update = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<ProductAsset> }) =>
      apiRequest(`/assets/${id}`, { method: "PATCH", body: patch }),
    onSuccess: () => {
      setEditing(null);
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => apiRequest(`/assets/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      setEditing(null);
      refresh();
    },
  });
  const restore = useMutation({
    mutationFn: (id: string) =>
      apiRequest(`/recycle-bin/${id}/restore`, { method: "POST", idempotent: true }),
    onSuccess: refresh,
  });
  const chooseFiles = (event: ChangeEvent<HTMLInputElement>) => {
    const remaining = 8 - (workspace.data?.assets.length || 0);
    const files = Array.from(event.target.files || []).slice(0, remaining);
    if (files.length) upload.mutate(files);
    event.target.value = "";
  };

  return (
    <>
      <header className="page-header">
        <div>
          <h1>素材库</h1>
          <p>按 SKU 管理商品参考图</p>
        </div>
        <button
          className="button"
          disabled={!productId || upload.isPending || (workspace.data?.assets.length || 0) >= 8}
          onClick={() => inputRef.current?.click()}
        >
          <ImageUp size={18} />
          {upload.isPending ? "上传处理中" : "上传图片"}
        </button>
        <input
          ref={inputRef}
          className="sr-only"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          multiple
          onChange={chooseFiles}
        />
      </header>

      {!products.data?.length ? (
        <div className="empty-state">
          <Image size={32} />
          <h2>暂无商品素材</h2>
        </div>
      ) : (
        <div className={styles.split}>
          <aside className={styles.productList}>
            {products.data.map((product) => (
              <button
                className={`${styles.productButton} ${productId === product.id ? styles.productActive : ""}`}
                key={product.id}
                onClick={() => setProductId(product.id)}
              >
                <div className={styles.productPlaceholder}>
                  <Image size={18} />
                </div>
                <div className={styles.productText}>
                  <strong>{product.name}</strong>
                  <span>{product.sku}</span>
                </div>
              </button>
            ))}
          </aside>
          <section>
            <div className={styles.libraryHeader}>
              <h2>{workspace.data?.product.name || "商品素材"}</h2>
              <span className="status-pill">{workspace.data?.assets.length || 0} / 8 张</span>
            </div>
            <div className={styles.assetGrid}>
              {workspace.data?.assets.map((asset) => (
                <button className={styles.assetCard} key={asset.id} onClick={() => setEditing(asset)}>
                  <img src={appUrl(asset.thumbnail_url)} alt={asset.name} />
                  <div className={styles.assetInfo}>
                    <strong>{asset.name}</strong>
                    <span>{asset.is_primary ? "主参考图" : asset.angle}</span>
                  </div>
                </button>
              ))}
            </div>
          </section>
        </div>
      )}

      {(recycle.data?.length || 0) > 0 && (
        <section className={styles.recycle}>
          <h2>回收站</h2>
          {recycle.data?.map((entry) => (
            <div className={styles.recycleRow} key={entry.id}>
              <span>{entry.name}</span>
              <button className="button secondary" onClick={() => restore.mutate(entry.id)}>
                <RotateCcw size={16} />
                恢复
              </button>
            </div>
          ))}
        </section>
      )}

      {editing && (
        <div className={styles.drawerBackdrop} onMouseDown={() => setEditing(null)}>
          <aside className={styles.drawer} onMouseDown={(event) => event.stopPropagation()}>
            <div className={styles.drawerHeader}>
              <h2>编辑素材</h2>
              <button className="icon-button" title="关闭" onClick={() => setEditing(null)}>
                <X size={19} />
              </button>
            </div>
            <img className={styles.drawerImage} src={appUrl(editing.preview_url)} alt={editing.name} />
            <div className={styles.drawerForm}>
              <label className="field-label">
                图片角度
                <select
                  className="field"
                  value={editing.angle}
                  onChange={(event) => setEditing({ ...editing, angle: event.target.value })}
                >
                  <option value="front">正面</option>
                  <option value="back">背面</option>
                  <option value="left">左侧</option>
                  <option value="right">右侧</option>
                  <option value="detail">细节</option>
                  <option value="package">包装</option>
                  <option value="scene">场景</option>
                  <option value="other">其他</option>
                </select>
              </label>
              <label className="field-label">
                <span>主参考图</span>
                <input
                  type="checkbox"
                  checked={editing.is_primary}
                  onChange={(event) => setEditing({ ...editing, is_primary: event.target.checked })}
                />
              </label>
              <div className={styles.drawerActions}>
                <button className="button danger" onClick={() => remove.mutate(editing.id)}>
                  移入回收站
                </button>
                <button
                  className="button"
                  onClick={() =>
                    update.mutate({
                      id: editing.id,
                      patch: { angle: editing.angle, is_primary: editing.is_primary },
                    })
                  }
                >
                  保存修改
                </button>
              </div>
            </div>
          </aside>
        </div>
      )}
    </>
  );
}
