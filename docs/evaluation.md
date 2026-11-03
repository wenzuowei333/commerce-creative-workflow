# 功能验证与评测边界

这是软件功能与恢复机制验证，不是模型效果评测。以下数据来自 **2026-11-03 阶段五** 的干净检出运行；原时间戳保存在 [脱敏摘要](assets/acceptance-summary.json)。阶段六新增文档、截图、视频，没有重新标记旧测试的执行时间。

| 报告 | passed | failed / error / skipped | JUnit 用时 |
|---|---:|---|---|
| source-validation.xml | 42 | 0 / 0 / 0 | 11.983 秒 |
| postgres-validation.xml | 21 | 0 / 0 / 0 | 42.281 秒 |
| frontend-validation.xml | 7 | 0 / 0 / 0 | 0.007 秒 |

另有 3 组 Chrome 用例，20.804 秒，0 意外失败/跳过/flaky；覆盖 4+1、刷新、重试、第二商品、账号隔离和 390px 布局。前端 7 项 JUnit 时间仅约 0.007 秒，npm 测试步骤总计 2.136 秒，二者口径不同。

**阶段六新增验证：** 录屏实际点击、数据库状态和结果断言通过；业务源码/测试/依赖锁与阶段五最终候选一致，检查媒体哈希、视频时长、元数据、相对链接和代码锚点。未把录屏断言重复计入以上测试数量。

## 运行测试

需要 Docker、Python 3.12、uv、Node 24，测试库端口未被其他实例使用。测试会重建专用测试库，不指向演示数据库或生产库：

```sh
uv venv --python 3.12
uv pip install -r backend/requirements-dev.lock
.venv/bin/python demo/run_checks.py
```

前端命令：`cd frontend` 后执行 `npm ci`、`npm test`、`npm run typecheck`；实际页面已启动后执行 `npm run test:e2e`。完整命令与浏览器安装见 [运行手册](runbook.md)。

空卷复现与隔离运行使用 `ci/run.py --fresh-data-check`，完整依赖/浏览器安装、独立项目名和端口前提见 [阶段五入口](runbook.md#阶段五验收入口)。它要求专用项目尚不存在；会检查种子重复和新卷重建摘要一致，再运行全部测试。依赖安装需要软件源网络；运行期使用 Mock 和本地服务。

实测环境：macOS 26.6.2 arm64、Python 3.12.12（主机）/3.12.16（容器）、PostgreSQL 16.15、Docker 29.2.0、Compose 5.0.2、Chrome 156.0.8078.80、Node 24.13.0、Redis Server 7.4.12、Playwright JS 1.61.1。构建允许利用镜像层缓存；没有对首次无缓存安装计时。

## 没有做出的结论

未运行真实模型质量评测、生产容量或长时间稳定性测试，没有统计代码覆盖率；功能测试数量和 Mock 状态不能转换为业务成功率。真实外部请求和收费的严格一次语义未验证。GitHub 托管 Actions 未运行，不能以本地入口通过替代远程 CI 结论。

如需继续模型评测，应另行固定模型、样本来源、任务定义和重复次数，分别统计结构合规、证据覆盖、语义正确及业务目标满足度。本仓库不填未经运行的指标。
