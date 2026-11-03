import { RefreshCw } from "lucide-react";

import type { GenerationBatch } from "../../types";
import styles from "./GenerationStep.module.css";

type Props = {
  batch: GenerationBatch;
  isRetrying: boolean;
  onRetry: () => void;
};

function stageIndex(batch: GenerationBatch): number {
  if (batch.progress === 100) return 3;
  if (batch.progress >= 20) return 2;
  if (batch.progress > 0 || batch.state === "generating") return 1;
  return 0;
}

export function GenerationProgress({ batch, isRetrying, onRetry }: Props) {
  const currentStage = stageIndex(batch);
  return (
    <div className={styles.progressBand}>
      <div className={styles.progressHeader}>
        <strong>任务进度</strong>
        <span>{batch.progress}%</span>
      </div>
      <div className={styles.progressTrack} role="progressbar" aria-valuenow={batch.progress}>
        <div className={styles.progressValue} style={{ width: `${batch.progress}%` }} />
      </div>
      <p>已完成 {batch.items.filter((item) => item.kind === "initial" && item.state === "completed").length} · 失败 {batch.items.filter((item) => item.kind === "initial" && item.state === "failed").length} · 共 {batch.image_count} 张</p>
      <div className={styles.stages}>
        {["任务已排队", "读取参考素材", "逐张生成", "本轮执行结束"].map(
          (stage, index) => (
            <div
              className={`${styles.stage} ${index <= currentStage ? styles.stageActive : ""}`}
              key={stage}
            >
              <span className={styles.stageDot} />
              {stage}
            </div>
          ),
        )}
      </div>
      {(batch.state === "partial" || batch.state === "failed") && (
        <button className="button secondary" disabled={isRetrying} onClick={onRetry}>
          <RefreshCw size={17} />
          仅补生成失败图片
        </button>
      )}
    </div>
  );
}
