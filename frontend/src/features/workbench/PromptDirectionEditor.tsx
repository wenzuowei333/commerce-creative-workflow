import type { PromptDirection } from "../../types";
import styles from "./PromptStep.module.css";

type Props = {
  direction: PromptDirection;
  directionIndex: number;
  onDirectionChange: (patch: Partial<PromptDirection>) => void;
  onVariantChange: (variantIndex: number, prompt: string) => void;
};

export function PromptDirectionEditor({
  direction,
  directionIndex,
  onDirectionChange,
  onVariantChange,
}: Props) {
  return (
    <div className={styles.direction}>
      <div className={styles.directionHeader}>
        <div>
          <h3>
            方向 {directionIndex + 1}：{direction.title}
          </h3>
          <p>{direction.rationale}</p>
        </div>
        <input
          className="field"
          aria-label={`方向 ${directionIndex + 1} 名称`}
          value={direction.title}
          onChange={(event) => onDirectionChange({ title: event.target.value })}
        />
      </div>
      <div className={styles.promptFields}>
        <label className="field-label">
          主提示词
          <textarea
            className="field"
            rows={6}
            value={direction.base_prompt}
            onChange={(event) => onDirectionChange({ base_prompt: event.target.value })}
          />
        </label>
        <label className="field-label">
          负面约束
          <textarea
            className="field"
            rows={6}
            value={direction.negative_prompt}
            onChange={(event) => onDirectionChange({ negative_prompt: event.target.value })}
          />
        </label>
      </div>
      <div className={styles.variantList}>
        {direction.variants.map((variant, variantIndex) => (
          <label className={styles.variantRow} key={`${variant.index}-${variantIndex}`}>
            <span>{variant.module ? `模块：${variant.module}` : `构图 ${variantIndex + 1}`}</span>
            <textarea
              className="field"
              rows={3}
              value={variant.prompt}
              onChange={(event) => onVariantChange(variantIndex, event.target.value)}
            />
          </label>
        ))}
      </div>
    </div>
  );
}
