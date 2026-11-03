import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, ShieldAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { apiRequest } from "../../api/client";
import type { AnalysisAttribute, ProductWorkspace } from "../../types";
import styles from "../../pages/WorkbenchPage.module.css";

type Props = {
  workspace: ProductWorkspace;
  onConfirmed: () => void;
};

const profileFields = [
  ["name", "商品名称"],
  ["category", "商品品类"],
  ["brand", "品牌"],
  ["sku", "SKU"],
  ["colors", "颜色"],
  ["materials", "材质"],
  ["packaging", "包装"],
  ["structure", "结构特征"],
  ["selling_points", "商品卖点"],
  ["audience", "适用人群"],
  ["scenes", "适用场景"],
  ["forbidden_content", "禁用内容"],
];

function displayValue(value: unknown): string {
  if (Array.isArray(value)) return value.join("，");
  if (value === null || value === undefined) return "";
  return String(value);
}

export function AnalysisStep({ workspace, onConfirmed }: Props) {
  const analysis = workspace.latest_analysis;
  const [profile, setProfile] = useState<Record<string, unknown>>({});
  const [attributes, setAttributes] = useState<AnalysisAttribute[]>([]);
  const queryClient = useQueryClient();

  useEffect(() => {
    setProfile(analysis?.result.profile || {});
    setAttributes(analysis?.result.attributes || []);
  }, [analysis?.id, analysis?.result.attributes, analysis?.result.profile]);

  const unconfirmedRisk = useMemo(
    () => attributes.filter((attribute) => attribute.high_risk && !attribute.user_confirmed),
    [attributes],
  );
  const confirm = useMutation({
    mutationFn: () =>
      apiRequest(`/analysis/${analysis?.id}/confirm`, {
        method: "POST",
        idempotent: true,
        body: { profile, attributes },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["workspace", workspace.product.id] });
      void queryClient.invalidateQueries({ queryKey: ["products"] });
      onConfirmed();
    },
  });

  if (!analysis) {
    return (
      <div className="empty-state">
        <ShieldAlert size={30} />
        <h2>尚未识别商品</h2>
        <p>返回商品参考图步骤开始识别。</p>
      </div>
    );
  }

  const updateAttribute = (index: number, patch: Partial<AnalysisAttribute>) => {
    setAttributes((current) =>
      current.map((attribute, itemIndex) =>
        itemIndex === index ? { ...attribute, ...patch } : attribute,
      ),
    );
  };

  return (
    <section>
      <div className={styles.sectionHeader}>
        <div>
          <h2>确认商品信息</h2>
          <p>识别版本 V{analysis.version}</p>
        </div>
        <span className="status-pill warning">AI 推测内容需确认</span>
      </div>

      <div className={styles.profileGrid}>
        {profileFields.map(([key, label]) => (
          <label
            className={`field-label ${["structure", "selling_points", "forbidden_content"].includes(key) ? styles.profileWide : ""}`}
            key={key}
          >
            {label}
            <input
              className="field"
              value={displayValue(profile[key])}
              onChange={(event) =>
                setProfile((current) => ({ ...current, [key]: event.target.value }))
              }
            />
          </label>
        ))}
      </div>

      <div className={styles.attributeTable}>
        {attributes.map((attribute, index) => (
          <div className={styles.attributeRow} key={`${attribute.key}-${index}`}>
            <div className={styles.attributeKey}>
              {attribute.key}
              {attribute.high_risk && <ShieldAlert size={14} color="var(--orange)" />}
            </div>
            <input
              className="field"
              value={displayValue(attribute.value)}
              onChange={(event) => updateAttribute(index, { value: event.target.value })}
            />
            <div className={styles.confidence}>
              <div className={styles.confidenceTrack} aria-hidden="true">
                <span style={{ width: `${attribute.confidence * 100}%` }} />
              </div>
              {Math.round(attribute.confidence * 100)}%
            </div>
            <label className={styles.confirmCheck}>
              <input
                type="checkbox"
                checked={attribute.user_confirmed}
                onChange={(event) =>
                  updateAttribute(index, { user_confirmed: event.target.checked })
                }
              />
              人工确认
            </label>
          </div>
        ))}
        <button
          className="button secondary"
          style={{ marginTop: 14 }}
          onClick={() =>
            setAttributes((current) => [
              ...current,
              {
                key: `custom_${current.length + 1}`,
                value: "",
                confidence: 1,
                inference_kind: "user",
                source_asset_ids: [],
                user_confirmed: true,
                high_risk: false,
              },
            ])
          }
        >
          <Plus size={16} />
          添加属性
        </button>
      </div>

      {confirm.error && (
        <div className={styles.errorBox} role="alert">
          {confirm.error.message}
        </div>
      )}
      <div className={styles.actionBar}>
        <span>
          {unconfirmedRisk.length
            ? `${unconfirmedRisk.length} 个高风险字段尚未确认`
            : "商品信息可提交"}
        </span>
        <button
          className="button"
          disabled={Boolean(unconfirmedRisk.length) || confirm.isPending}
          onClick={() => confirm.mutate()}
        >
          {confirm.isPending ? "正在保存" : "确认商品信息"}
        </button>
      </div>
    </section>
  );
}
