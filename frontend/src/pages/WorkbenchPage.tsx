import { useQuery } from "@tanstack/react-query";
import { Check, PackagePlus, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { AnalysisStep } from "../features/workbench/AnalysisStep";
import { AssetStep } from "../features/workbench/AssetStep";
import { GenerationStep } from "../features/workbench/GenerationStep";
import { NewProductDialog } from "../features/workbench/NewProductDialog";
import { getWorkspace, listProducts } from "../features/workbench/api";
import { PromptStep } from "../features/workbench/PromptStep";
import { deriveWorkspaceStep } from "../features/workbench/steps";
import styles from "./WorkbenchPage.module.css";

const steps = ["商品素材", "商品信息", "提示词", "生成结果"];

export function WorkbenchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedId = searchParams.get("product");
  const [activeStep, setActiveStep] = useState(1);
  const [showNewProduct, setShowNewProduct] = useState(false);
  const products = useQuery({ queryKey: ["products"], queryFn: listProducts });
  const workspace = useQuery({
    queryKey: ["workspace", selectedId],
    queryFn: () => getWorkspace(selectedId!),
    enabled: Boolean(selectedId),
  });

  useEffect(() => {
    if (!selectedId && products.data?.length) {
      setSearchParams({ product: products.data[0].id }, { replace: true });
    }
  }, [products.data, selectedId, setSearchParams]);

  useEffect(() => {
    setActiveStep(deriveWorkspaceStep(workspace.data));
  }, [workspace.data]);

  const maxStep = deriveWorkspaceStep(workspace.data);
  const selectProduct = (productId: string) => {
    setSearchParams({ product: productId });
    setActiveStep(1);
  };

  return (
    <>
      <header className="page-header">
        <div>
          <h1>创作工作台</h1>
          <p>从商品素材到批量结果</p>
        </div>
        <div className={styles.toolbar}>
          <select
            className={`field ${styles.productSelect}`}
            aria-label="当前商品"
            value={selectedId || ""}
            onChange={(event) => selectProduct(event.target.value)}
          >
            {!products.data?.length && <option value="">暂无商品</option>}
            {products.data?.map((product) => (
              <option value={product.id} key={product.id}>
                {product.name} · {product.sku}
              </option>
            ))}
          </select>
          <button className="button" onClick={() => setShowNewProduct(true)}>
            <Plus size={18} />
            新建商品
          </button>
        </div>
      </header>

      {workspace.data ? (
        <>
          <nav className={styles.stepper} aria-label="生图流程">
            {steps.map((label, index) => {
              const step = index + 1;
              const complete = step < maxStep;
              return (
                <button
                  key={label}
                  className={`${styles.step} ${activeStep === step ? styles.stepActive : ""} ${complete ? styles.stepComplete : ""}`}
                  disabled={step > maxStep}
                  onClick={() => setActiveStep(step)}
                >
                  <span className={styles.stepNumber}>
                    {complete ? <Check size={14} /> : step}
                  </span>
                  {label}
                </button>
              );
            })}
          </nav>

          {activeStep === 1 && (
            <AssetStep workspace={workspace.data} onAnalysisReady={() => setActiveStep(2)} />
          )}
          {activeStep === 2 && (
            <AnalysisStep workspace={workspace.data} onConfirmed={() => setActiveStep(3)} />
          )}
          {activeStep === 3 && (
            <PromptStep workspace={workspace.data} onConfirmed={() => setActiveStep(4)} />
          )}
          {activeStep === 4 && <GenerationStep key={`${workspace.data.product.id}:${workspace.data.latest_prompt_plan?.id}`} workspace={workspace.data} />}
        </>
      ) : workspace.isLoading || products.isLoading ? (
        <div className="empty-state">
          <p>正在载入商品档案</p>
        </div>
      ) : (
        <div className="empty-state">
          <PackagePlus size={36} />
          <h2>新建第一个商品档案</h2>
          <button className="button" onClick={() => setShowNewProduct(true)}>
            <Plus size={18} />
            新建商品
          </button>
        </div>
      )}

      {showNewProduct && (
        <NewProductDialog
          onClose={() => setShowNewProduct(false)}
          onCreated={(product) => {
            setShowNewProduct(false);
            selectProduct(product.id);
          }}
        />
      )}
    </>
  );
}
