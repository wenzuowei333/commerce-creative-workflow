# 架构与关键时序

本版把商品事实确认、视觉策划确认和批量生成分开。识图、策划与修订是同步阶段；只有初始逐图生成通过 Redis/Dramatiq。展示部署由 React 同源页面、FastAPI、独立 Worker、恢复进程、PostgreSQL、Redis 与本地媒体卷组成。

```mermaid
flowchart TB
  UI["React 工作台<br/>素材 / 确认 / 策划 / 结果"] --> API["FastAPI<br/>所有权 / 风险确认 / 版本校验"]
  API --> DB[("PostgreSQL<br/>工作流状态 / 逐图任务 / 事件")]
  API --> Q[("Redis<br/>Session / Dramatiq 消息")]
  Q --> W["独立 Worker<br/>CAS / 租约 / 代次复核"]
  W --> P["Mock Provider<br/>程序占位图"]
  W --> S["本地媒体卷"]
  W --> DB
  R["恢复进程<br/>过期项 / queued 项"] --> DB
  R --> Q
  DB --> API
  API --> UI
```

Redis 承载 session 与消息，PostgreSQL 是工作流状态权威；浏览器根据持久化历史恢复当前批次。主参考图优先、随后按 position 排序。批次冻结设置，但执行时仍读取当前商品的 ready 参考素材，不声称完整历史依赖快照。

```mermaid
sequenceDiagram
  participant U as 页面
  participant A as API
  participant D as PostgreSQL
  participant Q as Redis
  participant W as Dramatiq Worker
  participant P as Mock Provider
  U->>A: 确认识图风险与五图方案
  A->>D: 最新识图版本 / 所有权 / 确认状态
  U->>A: 创建批次 + 幂等键
  A->>D: 幂等请求摘要 / 五个子项 / 设置快照
  A->>Q: 提交后投递 queued 子项
  Q->>W: 子项消息（允许重复）
  W->>D: queued 条件领取 + token + attempts
  Note over W,D: 提交短事务，Provider 调用不持锁
  W->>P: 提示词 + 参考图
  P-->>W: 图片或第 3 项故障
  W->>D: 检查 token / 代次 / 状态 / 有效租约
  W->>D: 写成图或失败 + 持久化事件
  D-->>U: SSE / 查询：4 成功、1 失败
  U->>A: 仅重试失败项
  A->>D: failed 子项重排，保留其他四张
  A->>Q: 只投递失败项
  Q->>W: 第 3 项第二次执行
  D-->>U: 5 成功；attempts = 1,1,2,1,1
```

关键入口：[风险确认](../backend/app/api/analysis.py#L105)、[方案版本](../backend/app/services/plan_validation.py#L61)、[幂等提交](../backend/app/api/generation.py#L58)、[领取与写回](../backend/app/services/generation_execution.py#L142)、[恢复](../backend/app/services/generation_recovery.py#L11)。

媒体文件写入与数据库提交不构成跨资源事务；目前没有保证崩溃下零孤立文件。短全局 advisory 锁简化领取/恢复/重试顺序，限制吞吐。外部模型与对象存储接口保留在代码中，本轮仅用 Mock 与本地媒体。

源实现和新增版本关联、设置快照、回写隔离见 [适配说明](phase4-adaptations.md)。

可导出图：[架构 SVG](assets/architecture.svg) · [关键时序 SVG](assets/sequence.svg)。Mermaid 源码保留在本页，便于后续维护。
