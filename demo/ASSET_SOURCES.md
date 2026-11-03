# 素材来源

`references/` 的 8 张 PNG 是本候选版 `demo/seed.py` 用 Pillow 绘制的几何测试示意图。商品和 DEMO LAB 品牌均为虚构；不是产品摄影，不含原始企业素材，可随本展示版复用。

`mock-outputs/` 的 5 张 PNG 来自所选源版本已有的 `MockAIProvider`，通过固定提示词生成。它们是程序化预览占位图，不是真实模型产出，也没有写入数据库充当成功任务。

`frontend/public/demo-studio.svg` 是新编写的几何登录插图，替代来源许可未核实的原 PNG。

所有 PNG 以 RGB 画布新建，不复制元数据；验证时检查 EXIF、文本块和文件哈希。生成器固定输入，文件可逐字节重建。每个文件的来源、用途、Mock 标记、尺寸和 SHA-256 见 `fixtures/assets-manifest.json`。
