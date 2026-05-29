# Hermes Agent 交接说明

## 项目定位

本项目已被调整为公众号「烧 Token 的人」的内容生产工作台。

- 账号名：烧 Token 的人
- 简介：用 AI 大模型工程师视角，讲清楚 AI、模型、产品，和那些被烧掉的 token。
- slogan：让每个烧掉的 token，都变成生产力。
- 内容方向：AI 最新消息解读、AI 科普、AI 产品体验、大模型工程实践、AI 工具与工作流、AI 产业链观察。
- 写作视角：AI 大模型工程师写给普通读者，专业但不端着，讲技术但翻译成人话。

## 当前已完成

### 账号配置

- `style.yaml` 已配置账号名称、简介、slogan、主题、信息源偏好和选题策略。
- `personas/token-burner.yaml` 已新增专属写作人格。
- `playbook.md` 已配置账号级信息源和写作底线。

### 内容规则

- `references/writing-guide.md` 已改为「烧 Token 的人」写法。
- `references/layout-playbook.md` 已改为适配 AI 工程师科普、产品体验和产业链分析的排版规则。
- `references/visual-prompts.md` 已改为 token 成本、调用链路、产品界面、工程现场和产业链图谱方向。
- `references/topic-selection.md` 已改为「国内热点发现，海外信息补证」的 AI 工程师号选题评分规则。

### 视觉主题

新增 3 个主题：

- `toolkit/themes/token-clean.yaml`：主主题，冷白、石墨黑、青绿色强调。
- `toolkit/themes/token-mint.yaml`：工程/工具体验轮换主题。
- `toolkit/themes/token-data.yaml`：产业链/商业分析轮换主题。

`scripts/layout_strategy.py` 已加入 token 主题轮换偏好。

## 关键产品决策

### 热点和素材的分工

不要把热点源和事实源混在一起。

- 热点源：保留国内平台，负责发现公众号读者正在关心什么。
- 事实源：优先海外官方、GitHub、论文、财报、英文主流媒体；X/Reddit/Hacker News/YouTube 只作为用户反馈和争议线索。重大事实必须尽量回到一手/primary 来源，社区和媒体不再要求三类硬凑齐。
- 中文公众号或中文媒体：只做风格参考、国内语境和传播背景，不作为重大事实默认来源。

执行时的标准流程：

1. 从国内热点抓取候选话题。
2. 用 `references/topic-selection.md` 打分，筛出有 AI 工程解释价值的选题。
3. 把中文选题翻译成英文关键词。
4. 按 `style.yaml.source_policy.search_queries` 和 `playbook.md` 找海外素材。
5. 只有证据足够时才进入写作。

### 选题评分方向

选题不要再按泛热搜号逻辑打分。核心维度已经改为：

- 国内热度
- AI 相关度
- 工程解释价值
- 海外证据可得
- 大众可读性

每个选题必须输出一句「AI 工程师问题」，例如：

```text
这个热点真正值得写的问题是：它到底省了谁的 token，又把复杂度转移到了哪里？
```

## Hermes 优先任务

### P0：补 macOS/Linux 原生 Python 工作流入口

当前项目默认主链路大量依赖 PowerShell：

- `scripts/new_wechat_article.ps1`
- `scripts/render_wechat_article.ps1`
- `scripts/check_wechat_article.ps1`
- `scripts/publish_wechat_article.ps1`

但当前 macOS 环境没有 `pwsh` / `powershell`。如果 Hermes 要稳定调用这个项目，必须补齐纯 Python 入口。

建议在 `toolkit/cli.py` 或新增 `scripts/wewrite.py` 中实现：

```bash
python3 toolkit/cli.py new --title "标题" --author "烧 Token 的人"
python3 toolkit/cli.py render --article-dir output/xxx
python3 toolkit/cli.py check --article-dir output/xxx
python3 toolkit/cli.py publish-draft --article-dir output/xxx --dry-run
```

#### P0 验收标准

- 不依赖 PowerShell，在 macOS/Linux 上可直接运行。
- 能创建标准文章目录：
  - `article.md`
  - `assets/`
  - `generated/`
  - `draft-metadata.json`
- 能调用现有 converter 生成预览 HTML。
- 能生成或调用以下报告：
  - `generated/humanness-report.json`
  - `generated/diagnose-report.json`
  - `generated/seo-report.json`
  - `generated/quality-gates.json`
- `publish-draft --dry-run` 不上传素材、不创建草稿，只验证配置、文章、图片、质量门禁。
- P13 图片系统已升级为“画面优先 + 少量标签 + 信息结构”：`draft-from-topic` 会产出 `generated/visual-plan.json`、`generated/image-prompts.md`、每图一个 `generated/*-visual-spec.json`，并用 `make_placeholder_image.py --visual-spec` 生成结构化本地预览图，不再默认交付大字文字卡片。
- P14 微信渲染边距已按手机端优化：模板 shell 使用白底、`padding:0 16px`、`max-width:677px`、无桌面阴影卡片；converter 会在主题样式后统一收紧正文段落、让图片在安全区内 `width:100%`、降低图注间距，并把引用/代码卡片改成手机友好的 14-15px 内边距。
- P16 发布前编辑门禁已接入：`scripts/editorial_gate.py` 生成 `generated/editorial-report.json`；`check`/`run-quality-gates.py` 会把 `editorial_readiness` 写入 `quality-gates.json`；`publish-ready` 会读取 `editorial-report.json`，发现内部工作流词泄漏、证据链内部笔记化或标题正文严重错位时 fail closed。
- 保留 Windows PowerShell wrapper，但主逻辑应迁移到 Python，PowerShell 只做薄包装。

### P1：把国内热点抓取升级为 AI 选题源

保留 `scripts/fetch_hotspots.py` 的国内热点入口，但建议新增过滤层，而不是直接推翻国内热点源。

可新增：

```bash
python3 scripts/select_ai_topics.py --hotspots output/hotspots.json --style style.yaml
```

职责：

- 读取国内热点。
- 按 `references/topic-selection.md` 的热点优先评分筛选，提高国内热度与跨平台热度权重。
- 为每个候选生成「AI 工程师问题」。
- 输出 `why_now` 和 `platform_heat`，说明为什么今天值得写、来自哪些平台/榜单。
- 输出海外补证关键词和推荐检索方向。

#### P1 验收标准

- 输出 Top 10 候选，每个候选包含国内热点来源、AI 工程师问题、栏目、五维评分、海外补证方向和风险提醒。
- 国内热度高但 AI 解释价值低的热点能被降权。
- 海外证据可得分低于 5 的选题不能进入自动写作。

### P2：补来源可信度门禁

建议新增 `scripts/source_gate.py`，检查文章或素材清单是否满足最低来源要求。

最低要求：

- 至少 1 个一手/primary 来源：官方文档、GitHub、论文、财报、产品公告、监管文件等。
- 社区讨论来源可来自 X、Reddit、Hacker News、YouTube 官方访谈，用于读者痛点、争议和使用反馈，不作为重大事实单独依据。
- 英文主流媒体或其他强二手验证来源用于产业判断交叉验证，但不再硬性要求每篇齐全。
- 中文媒体和国内二手转述不能单独支撑重大事实。

#### P2 验收标准

- 生成 `generated/source-report.json`。
- 只缺社区/媒体来源时不 fail；缺少一手/primary 来源时 fail closed。
- 证据不足时写入 `quality-gates.json` 的 warning/fail。
- 投资/产业链内容不得出现荐股、买卖点或确定性收益措辞。

## 可后置任务

这些可以等 Hermes 接手后继续完善：

- 初始化 `history.yaml` 并记录每篇文章表现。
- 创建专属 `writing-config.yaml`。
- README 改成「烧 Token 的人内容工作台」版本。
- 添加更多主题预览和视觉回归测试。
- 接入真实微信公众号配置和图片 API。
- 做文章数据复盘和选题反馈闭环。

## 当前已知环境状态

- 已安装 `.venv`，依赖可用。
- `config.yaml` 尚未配置，所以发布和生图会降级。
- `history.yaml` 尚不存在，所以选题去重和风格飞轮还没开始。
- `pwsh` / `powershell` 不存在，这是 Hermes 接手前最重要的工程风险。

## Hermes 开始前建议先跑

```bash
python3 scripts/diagnose.py --json
python3 toolkit/cli.py themes
python3 toolkit/cli.py gallery --no-open -o /tmp/wewrite-gallery.html
```

如果使用本地虚拟环境：

```bash
.venv/bin/python scripts/diagnose.py --json
.venv/bin/python toolkit/cli.py themes
```
