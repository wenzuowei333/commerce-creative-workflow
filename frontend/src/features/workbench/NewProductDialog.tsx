import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";

import { apiRequest } from "../../api/client";
import type { Product } from "../../types";
import styles from "./NewProductDialog.module.css";

type Props = {
  onClose: () => void;
  onCreated: (product: Product) => void;
};

export function NewProductDialog({ onClose, onCreated }: Props) {
  const [name, setName] = useState("");
  const [sku, setSku] = useState("");
  const [brand, setBrand] = useState("");
  const queryClient = useQueryClient();
  const create = useMutation({
    mutationFn: () =>
      apiRequest<Product>("/products", {
        method: "POST",
        idempotent: true,
        body: { name, sku, brand },
      }),
    onSuccess: (product) => {
      void queryClient.invalidateQueries({ queryKey: ["products"] });
      onCreated(product);
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate();
  };

  return (
    <div className={styles.backdrop} role="presentation" onMouseDown={onClose}>
      <div
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="new-product-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <h2 id="new-product-title">新建商品档案</h2>
        <form className={styles.form} onSubmit={submit}>
          <label className="field-label">
            商品名称
            <input
              className="field"
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
            />
          </label>
          <label className="field-label">
            SKU
            <input
              className="field"
              value={sku}
              onChange={(event) => setSku(event.target.value)}
              required
            />
          </label>
          <label className="field-label">
            品牌
            <input
              className="field"
              value={brand}
              onChange={(event) => setBrand(event.target.value)}
            />
          </label>
          {create.error && (
            <div className={styles.error} role="alert">
              {create.error.message}
            </div>
          )}
          <div className={styles.actions}>
            <button className="button secondary" type="button" onClick={onClose}>
              取消
            </button>
            <button className="button" type="submit" disabled={create.isPending}>
              {create.isPending ? "正在创建" : "创建商品"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
