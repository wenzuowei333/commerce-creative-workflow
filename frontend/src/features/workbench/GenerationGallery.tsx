import { appUrl } from "../../api/client";
import type { GenerationBatch, GenerationItem } from "../../types";
import styles from "./GenerationStep.module.css";

type Props = {
  batch: GenerationBatch;
  completedItems: GenerationItem[];
  selected: Set<string>;
  allowFinalize: boolean;
  onToggle: (imageId: string) => void;
  onFinalize: (imageId: string) => void;
};

function resultLabel(item: GenerationItem): string {
  if (item.kind === "initial") return `构图 ${item.index + 1}`;
  if (item.kind === "edit") return "调整版本";
  return "高清定稿";
}

export function GenerationGallery({
  batch,
  completedItems,
  selected,
  allowFinalize,
  onToggle,
  onFinalize,
}: Props) {
  return batch.directions.map((direction) => {
    const items = completedItems.filter((item) => item.direction_id === direction.id);
    if (!items.length) return null;
    return (
      <div className={styles.resultSection} key={direction.id}>
        <h3>{direction.title}</h3>
        <p>{direction.rationale}</p>
        <div className={styles.resultGrid}>
          {items.map((item) => {
            const image = item.image!;
            const isSelected = selected.has(image.id);
            return (
              <article
                className={`${styles.resultCard} ${isSelected ? styles.resultCardSelected : ""}`}
                key={item.id}
              >
                <input
                  className={styles.resultCheck}
                  type="checkbox"
                  checked={isSelected}
                  onChange={() => onToggle(image.id)}
                  aria-label={`选择结果 ${item.index + 1}`}
                />
                <img
                  className={styles.resultImage}
                  style={{ aspectRatio: batch.generation_type === "detail" ? "3 / 4" : "1" }}
                  src={appUrl(image.preview_url)}
                  alt={`${direction.title} 结果 ${item.index + 1}`}
                />
                <div className={styles.resultMeta}>
                  <span>{resultLabel(item)}</span>
                  <div className={styles.resultActions}>
                    <button onClick={() => window.open(appUrl(image.preview_url), "_blank")}>
                      查看
                    </button>
                    {allowFinalize && image.quality !== "high" && (
                      <button onClick={() => onFinalize(image.id)}>高清</button>
                    )}
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      </div>
    );
  });
}
