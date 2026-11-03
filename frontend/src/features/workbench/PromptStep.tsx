import { useMutation, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";

import { apiRequest } from "../../api/client";
import type {
  ProductWorkspace,
  PromptDirection,
  PromptPlan,
  PromptRecipe,
} from "../../types";
import commonStyles from "../../pages/WorkbenchPage.module.css";
import { PromptDirectionEditor } from "./PromptDirectionEditor";
import { PromptSetup } from "./PromptSetup";
import styles from "./PromptStep.module.css";

type Props = {
  workspace: ProductWorkspace;
  onConfirmed: () => void;
};

export function PromptStep({ workspace, onConfirmed }: Props) {
  const queryClient = useQueryClient();
  const [generationType, setGenerationType] = useState<"main" | "detail">("main");
  const [imageCount, setImageCount] = useState(15);
  const [activePlan, setActivePlan] = useState<PromptPlan | null>(
    workspace.latest_prompt_plan,
  );
  const [recipe, setRecipe] = useState<PromptRecipe | null>(
    workspace.latest_prompt_plan?.plan || null,
  );
  const [regenerateInstruction, setRegenerateInstruction] = useState("");

  useEffect(() => {
    setActivePlan(workspace.latest_prompt_plan);
    setRecipe(workspace.latest_prompt_plan?.plan || null);
  }, [workspace.latest_prompt_plan]);

  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ["workspace", workspace.product.id] });
  const create = useMutation({
    mutationFn: () =>
      apiRequest<PromptPlan>("/prompt-plans", {
        method: "POST",
        idempotent: true,
        body: {
          product_id: workspace.product.id,
          generation_type: generationType,
          image_count: imageCount,
        },
      }),
    onSuccess: (plan) => {
      setActivePlan(plan);
      setRecipe(plan.plan);
      void refresh();
    },
  });
  const regenerate = useMutation({
    mutationFn: () =>
      apiRequest<PromptPlan>(`/prompt-plans/${activePlan?.id}/regenerate`, {
        method: "POST",
        idempotent: true,
        body: { instruction: regenerateInstruction },
      }),
    onSuccess: (plan) => {
      setActivePlan(plan);
      setRecipe(plan.plan);
      setRegenerateInstruction("");
      void refresh();
    },
  });
  const confirm = useMutation({
    mutationFn: () =>
      apiRequest<PromptPlan>(`/prompt-plans/${activePlan?.id}/confirm`, {
        method: "POST",
        idempotent: true,
        body: { plan: recipe },
      }),
    onSuccess: (plan) => {
      setActivePlan(plan);
      void refresh();
      onConfirmed();
    },
  });

  const updateDirection = (index: number, patch: Partial<PromptDirection>) => {
    setRecipe((current) =>
      current
        ? {
            ...current,
            directions: current.directions.map((direction, itemIndex) =>
              itemIndex === index ? { ...direction, ...patch } : direction,
            ),
          }
        : current,
    );
  };

  const updateVariant = (directionIndex: number, variantIndex: number, prompt: string) => {
    setRecipe((current) => {
      if (!current) return current;
      return {
        ...current,
        directions: current.directions.map((direction, itemIndex) =>
          itemIndex === directionIndex
            ? {
                ...direction,
                variants: direction.variants.map((variant, rowIndex) =>
                  rowIndex === variantIndex ? { ...variant, prompt } : variant,
                ),
              }
            : direction,
        ),
      };
    });
  };

  const error = create.error || regenerate.error || confirm.error;
  return (
    <section>
      <div className={commonStyles.sectionHeader}>
        <div>
          <h2>策划生图提示词</h2>
          <p>{activePlan ? `方案版本 V${activePlan.active_version}` : "新建视觉方案"}</p>
        </div>
        {activePlan?.state === "confirmed" && (
          <span className="status-pill success">已确认</span>
        )}
      </div>

      {!activePlan && (
        <PromptSetup
          generationType={generationType}
          imageCount={imageCount}
          isPending={create.isPending}
          onGenerationTypeChange={setGenerationType}
          onImageCountChange={setImageCount}
          onCreate={() => create.mutate()}
        />
      )}

      {recipe?.directions.map((direction, directionIndex) => (
        <PromptDirectionEditor
          key={`${direction.index}-${directionIndex}`}
          direction={direction}
          directionIndex={directionIndex}
          onDirectionChange={(patch) => updateDirection(directionIndex, patch)}
          onVariantChange={(variantIndex, prompt) =>
            updateVariant(directionIndex, variantIndex, prompt)
          }
        />
      ))}

      {activePlan && (
        <div className={styles.regenerate}>
          <input
            className="field"
            value={regenerateInstruction}
            onChange={(event) => setRegenerateInstruction(event.target.value)}
            placeholder="例如：更高级、更生活化，减少装饰元素"
          />
          <button
            className="button secondary"
            disabled={regenerate.isPending}
            onClick={() => regenerate.mutate()}
          >
            <RefreshCw size={17} />
            重新生成提示词
          </button>
        </div>
      )}

      {error && (
        <div className={commonStyles.errorBox} role="alert">
          {error.message}
        </div>
      )}
      {activePlan && recipe && (
        <div className={commonStyles.actionBar}>
          <span>
            {recipe.directions.length} 个视觉方向 · {recipe.image_count} 张图片
          </span>
          <button className="button" disabled={confirm.isPending} onClick={() => confirm.mutate()}>
            {confirm.isPending ? "正在确认" : "确认提示词并继续"}
          </button>
        </div>
      )}
    </section>
  );
}
