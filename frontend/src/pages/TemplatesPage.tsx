import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, LayoutTemplate, Pencil, Play, Trash2, X } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiRequest } from "../api/client";
import { listProducts } from "../features/workbench/api";
import type { PromptRecipe, Template } from "../types";
import styles from "./LibraryPages.module.css";

export function TemplatesPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const templates = useQuery({
    queryKey: ["templates"],
    queryFn: () => apiRequest<Template[]>("/templates"),
  });
  const products = useQuery({ queryKey: ["products"], queryFn: listProducts });
  const [editing, setEditing] = useState<Template | null>(null);
  const [applyProduct, setApplyProduct] = useState<Record<string, string>>({});
  const copy = useMutation({
    mutationFn: (id: string) =>
      apiRequest(`/templates/${id}/copy`, { method: "POST", idempotent: true }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["templates"] }),
  });
  const remove = useMutation({
    mutationFn: (id: string) =>
      apiRequest(`/templates/${id}`, { method: "DELETE", idempotent: true }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["templates"] }),
  });
  const update = useMutation({
    mutationFn: (template: Template) =>
      apiRequest(`/templates/${template.id}`, {
        method: "PATCH",
        idempotent: true,
        body: { name: template.name, recipe: template.recipe },
      }),
    onSuccess: () => {
      setEditing(null);
      void queryClient.invalidateQueries({ queryKey: ["templates"] });
    },
  });
  const apply = useMutation({
    mutationFn: ({ templateId, productId }: { templateId: string; productId: string }) =>
      apiRequest(`/templates/${templateId}/apply`, {
        method: "POST",
        idempotent: true,
        body: { product_id: productId },
      }),
    onSuccess: (_, variables) => {
      void queryClient.invalidateQueries({ queryKey: ["workspace", variables.productId] });
      navigate(`/?product=${variables.productId}`);
    },
  });

  return (
    <>
      <header className="page-header">
        <div>
          <h1>模板库</h1>
          <p>复用已验证的生成配方</p>
        </div>
      </header>

      {!templates.data?.length ? (
        <div className="empty-state">
          <LayoutTemplate size={34} />
          <h2>暂无模板</h2>
        </div>
      ) : (
        <div className={styles.templateGrid}>
          {templates.data.map((template) => {
            const selectedProduct = applyProduct[template.id] || "";
            return (
              <article className={styles.templateCard} key={template.id}>
                <div className={styles.templateAccent} />
                <div className={styles.templateBody}>
                  <span className="status-pill">
                    {template.generation_type === "main" ? "商品主图" : "商品详情图"}
                  </span>
                  <h2>{template.name}</h2>
                  <p>{template.recipe.image_count} 张 · {template.recipe.directions.length} 个方向</p>
                  <select
                    className="field"
                    style={{ marginTop: 14 }}
                    value={selectedProduct}
                    onChange={(event) =>
                      setApplyProduct((current) => ({
                        ...current,
                        [template.id]: event.target.value,
                      }))
                    }
                  >
                    <option value="">选择已确认商品</option>
                    {products.data
                      ?.filter((product) => product.status === "product_confirmed")
                      .map((product) => (
                        <option key={product.id} value={product.id}>
                          {product.name}
                        </option>
                      ))}
                  </select>
                  <div className={styles.templateActions}>
                    <button
                      className="icon-button"
                      title="应用模板"
                      disabled={!selectedProduct}
                      onClick={() =>
                        apply.mutate({ templateId: template.id, productId: selectedProduct })
                      }
                    >
                      <Play size={16} />
                    </button>
                    <button className="icon-button" title="编辑" onClick={() => setEditing(template)}>
                      <Pencil size={16} />
                    </button>
                    <button className="icon-button" title="复制" onClick={() => copy.mutate(template.id)}>
                      <Copy size={16} />
                    </button>
                    <button
                      className="icon-button"
                      title="删除"
                      disabled={template.is_protected}
                      onClick={() => remove.mutate(template.id)}
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}

      {editing && (
        <TemplateDrawer
          template={editing}
          onClose={() => setEditing(null)}
          onSave={(template) => update.mutate(template)}
        />
      )}
    </>
  );
}

function TemplateDrawer({
  template,
  onClose,
  onSave,
}: {
  template: Template;
  onClose: () => void;
  onSave: (template: Template) => void;
}) {
  const [name, setName] = useState(template.name);
  const [recipeText, setRecipeText] = useState(JSON.stringify(template.recipe, null, 2));
  const [parseError, setParseError] = useState("");
  const save = () => {
    try {
      const recipe = JSON.parse(recipeText) as PromptRecipe;
      onSave({ ...template, name, recipe });
    } catch {
      setParseError("配方 JSON 格式不正确");
    }
  };

  return (
    <div className={styles.drawerBackdrop} onMouseDown={onClose}>
      <aside className={styles.drawer} onMouseDown={(event) => event.stopPropagation()}>
        <div className={styles.drawerHeader}>
          <h2>编辑模板</h2>
          <button className="icon-button" title="关闭" onClick={onClose}>
            <X size={19} />
          </button>
        </div>
        <div className={styles.drawerForm}>
          <label className="field-label">
            模板名称
            <input className="field" value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <label className="field-label">
            完整生成配方
            <textarea
              className="field"
              rows={24}
              value={recipeText}
              onChange={(event) => {
                setRecipeText(event.target.value);
                setParseError("");
              }}
            />
          </label>
          {parseError && <p style={{ color: "var(--red)" }}>{parseError}</p>}
          <div className={styles.drawerActions}>
            <button className="button secondary" onClick={onClose}>取消</button>
            <button className="button" onClick={save}>保存模板</button>
          </div>
        </div>
      </aside>
    </div>
  );
}
