# 烧 Token 的人写作 Playbook

## 信息源规则

1. `reference_accounts` 只用于风格坐标，不作为素材采集源。
2. 选题入口可以来自国内热点平台，因为公众号读者的注意力在国内语境里；但国内热点只负责发现问题，不负责证明事实。
3. 写 AI 最新消息、模型、产品、Agent、产业链时，优先使用海外一手来源、开发者社区和英文主流媒体补证。
4. 每篇文章的核心事实素材优先级：官方公告/文档/GitHub/论文/财报 > Reuters/Bloomberg/FT/WSJ/The Information 等主流媒体 > X/Reddit/Hacker News/YouTube 的讨论线索 > 中文二次转述。
5. X、Reddit、YouTube 可以提供问题意识、争议点和真实用户反馈，但不能作为重大事实的唯一证据。
6. 中文平台只在发现国内热点、解释国内语境、中文社区反应或补充传播背景时使用；不要把量子位、机器之心、少数派、晚点、硅星人、虎嗅当作默认事实源。
7. 涉及投资和产业链，只写产业逻辑、产品进展、供需关系、成本结构和竞争格局，不写荐股、买卖点或确定性收益判断。

## 图片系统规则

1. 默认图片系统是“画面优先 + 少量标签 + 信息结构”，不是文字卡片。图片要用场景、流程、结构、对比或成本图谱帮读者理解文章，而不是把正文摘成大字贴在背景上。
2. 每篇自动产稿必须生成 `generated/visual-plan.json` 和 `generated/image-prompts.md`。`visual-plan.json` 里的每张图必须有 `visual_role`、`scene`、`composition`、`labels`、`text_density`；`labels` 最多 4 个短标签。
3. 稳定槽位为 `assets/cover-wide.jpg`、`assets/cover-square.jpg`、`assets/img-01.jpg`、`assets/img-02.jpg`、`assets/img-03.jpg`……后续生图只覆盖同名文件，不改正文路径。
4. 本地降级图也必须是结构化视觉预览：使用 `scripts/make_placeholder_image.py --visual-spec generated/<slot>-visual-spec.json`，让预览能看到流程、节点、对比或成本结构；没有 `--visual-spec` 时才退回旧文字占位图。
5. 禁止默认交付“单调背景 + 居中大字 + 几个装饰图标”的 PPT/字卡式配图；如果需要文字，最多 2-4 个短标签，且文字服务画面结构。

## 微信渲染边距规则

1. 公众号正文默认按手机端阅读优化，不做“网页大卡片套正文”。外层 shell 用白底、`padding:0 16px`、`max-width:677px`、无阴影、无厚卡片内边距。
2. 正文段落保持 16px 字号、约 1.74 行距、段后约 14px；不要为了“高级感”拉到 2.0 行距，也不要首行缩进导致手机端密度不稳。
3. 正文图片在安全区内 `width:100%` / `max-width:100%`，上下间距紧凑；图片不能因为 `margin:auto` 或内层桌面卡片而显得过窄。
4. 引用、代码、callout 等卡片只做轻量信息块：14-15px 内边距、10-12px 圆角、手机屏内不溢出；避免多层边框、厚阴影和大面积灰底。
5. 每次改模板或主题后，至少跑 `tests/test_mobile_render_spacing.py`，确认 shell、段落、图片、卡片四类边距没有回退。

## 发布前编辑质量门禁

1. 发布正文必须面向读者，不能泄漏内部工作流词：`official_docs`、`github_or_paper`、`internal/evidence ledger`、`source gate`、`evidence gate`、`需要在后续深读`、`阻塞发布`、`本选题的 X 证据` 等出现即阻塞。
2. “证据链”如果放在正文里，必须读者化表达；不要写“这是某类证据”“后续补摘录”“URL 留在 ledger”这种给 agent/编辑看的话。
3. 标题必须和正文持续展开的主题一致。标题有“芯片/算力/模型/Agent/token/Claude/ChatGPT/MCP”等强锚点时，正文必须持续展开对应对象；不能用泛 Agent/token 模板套任意热点。
4. `scripts/editorial_gate.py --article-dir <dir> --json` 会生成 `generated/editorial-report.json`。`toolkit/cli.py check` 会把 `editorial_readiness` 写入 `quality-gates.json`，`publish-ready` 会读取该报告并 fail closed。
5. P15 发现的“机器门禁通过但人工不能发”的样稿类型，P16 后必须被挡在 publish-ready 前。

## 默认素材采集口径

- 先把中文选题翻译成英文关键词，再检索海外来源。
- 每篇至少采集 5-8 条真实素材，并保证每个 H2 至少有 1 条可核验素材锚点。
- 优先检索 `x.com`、`reddit.com`、`github.com`、`youtube.com`、`news.ycombinator.com`、官方博客、论文站和英文主流媒体。
- 引用 X、Reddit、YouTube 时只概括观点，不复制长段原文；重要事实必须用第二来源验证。
