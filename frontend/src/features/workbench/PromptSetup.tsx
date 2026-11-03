import { WandSparkles } from "lucide-react";

import styles from "./PromptStep.module.css";

type Props = {
  generationType: "main" | "detail";
  imageCount: number;
  isPending: boolean;
  onGenerationTypeChange: (value: "main" | "detail") => void;
  onImageCountChange: (value: number) => void;
  onCreate: () => void;
};

export function PromptSetup({
  generationType,
  imageCount,
  isPending,
  onGenerationTypeChange,
  onImageCountChange,
  onCreate,
}: Props) {
  return (
    <div className={styles.promptSetup}>
      <div className={styles.choiceGroup}>
        <span>图片类型</span>
        <div className={styles.segmented}>
          <button
            className={generationType === "main" ? styles.selected : ""}
            onClick={() => onGenerationTypeChange("main")}
          >
            商品主图
          </button>
          <button
            className={generationType === "detail" ? styles.selected : ""}
            onClick={() => onGenerationTypeChange("detail")}
          >
            商品详情图
          </button>
        </div>
      </div>
      <div className={styles.choiceGroup}>
        <span>生成数量</span>
        <div className={styles.segmented}>
          {[5, 10, 15].map((count) => (
            <button
              key={count}
              className={imageCount === count ? styles.selected : ""}
              onClick={() => onImageCountChange(count)}
            >
              {count} 张
            </button>
          ))}
        </div>
      </div>
      <button className="button" disabled={isPending} onClick={onCreate}>
        <WandSparkles size={18} />
        {isPending ? "正在策划" : "生成提示词"}
      </button>
    </div>
  );
}
