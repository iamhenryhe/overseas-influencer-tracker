# 海外大V追踪器（全免费原型）

这个项目追踪两个公开账号：

- `@jukan05`
- `@aleabitoreddit`（Serenity）

`aichainmap` 是第三方的 AI 产业链地图/知识库网站。它的 [Serenity 页面](https://aichainmap.com/serenity/) 会抓取公开 X 内容、整理成时间线，并为部分内容提供中英对照和主题标签。它不是 X 官方接口，也不是 Serenity 本人运营的账号；因此它是交叉来源，不是绝对权威。

当前实现不购买 X API、不使用登录 Cookie、不需要梯子或 VPS。采集顺序是：

1. 两个账号优先读取公开 X 主页 HTML；X HTML 只给预览时尝试免费公开详情中转源。
2. 只有 Serenity 的 X 页面被屏蔽、读取失败或完全无法解析时，才使用 `aichainmap` 的公开 feed/页面作为备用，不把两边的重复内容同时合并。
3. 中文：aichainmap 备用数据有中文时直接使用；X 英文内容没有中文时，使用智谱 GLM 翻译。随后对真正要推送的帖子调用 GLM 生成 1–3 句中文总结。翻译或总结失败仍保留可用内容。
4. 本地状态：用 `state.json` 保存发布时间水位、已见 ID 和发送记录。
5. 推送：可选 PushPlus 微信渠道。没有 token 时可用 `--dry-run`，只抓取和打印，不发送。当前脚本每日最多 200 个逻辑推送，与实名微信渠道额度对齐。

## 本地测试

```bash
python3 -m unittest discover -s tests -v
python3 -m src.main --dry-run --limit 5
```

第一次正式运行默认是 `latest` 基线模式：记录当前已经存在的帖子，不把历史内容一次性轰炸到微信。之后只处理时间水位之后的新帖子。

如果想在第一次测试时打印当前最新内容，可以使用：

```bash
python3 -m src.main --dry-run --bootstrap-mode push_latest --limit 2
```

## PushPlus 配置

PushPlus 的 token 只放环境变量，不写进仓库：

```bash
export PUSHPLUS_TOKENS="你的token1,你的token2"
# 或使用一个 token + 一个 PushPlus 群组
export PUSHPLUS_TOPIC="你的群组编码"
python3 -m src.main
```

`PUSHPLUS_TOKENS` 支持多个接收人；`PUSHPLUS_TOPIC` 可把多个接收者放在一个群组里，减少请求次数。每条消息都保留原文链接，并标记 `NFA`。

接收微信消息：在微信中关注 `pushplus 推送加` 服务号，消息会通过这个服务号发给你。默认是微信渠道；如果想直接在消息里看到正文，可以在服务号里发送“激活消息”，否则通常点击通知进入详情页查看。Token 只放在本机环境变量或 GitHub Actions Secret 中，不要写进代码、README 或 `state.json`。

## 智谱翻译配置

GitHub Actions 使用加密 Secret `ZHIPU_API_KEY` 调用智谱 GLM Coding Plan；端点为 `https://open.bigmodel.cn/api/coding/paas/v4/chat/completions`，默认模型为 `glm-5.2`。Coding Plan 必须使用专用端点，不能使用普通的 `/api/paas/v4/` 端点。智谱官方要求使用 Bearer 认证并建议通过环境变量保存 API Key，不能把 Key 提交到仓库。[Coding Plan 端点说明](https://docs.bigmodel.cn/cn/coding-plan/quick-start)

只翻译和总结最终要推送的帖子，不处理整个历史 feed。aichainmap 已经提供中文的帖子不会重复翻译，但仍会调用一次 GLM 生成总结。工作流通过 `SUMMARIZE_X=true` 开启总结。

## GitHub Actions

把整个目录放入一个 GitHub 仓库，建议使用 public repository。标准 GitHub-hosted runner 对 public repository 免费。然后在仓库的 Settings → Secrets and variables → Actions 中添加：

- `PUSHPLUS_TOKENS`：一个或多个 PushPlus token，逗号分隔；
- `ZHIPU_API_KEY`：智谱 API Key，用于 X 英文内容翻译；
- 可选 `PUSHPLUS_TOPIC`：PushPlus 群组编码。

工作流启动后会在 GitHub Runner 上持续监控约 5 小时，每 60 秒抓取一次；窗口结束时自动接力启动下一轮。另有每小时一次的 `schedule` 作为异常恢复兜底。这样不依赖每 5 分钟创建一个短任务，但 GitHub 高负载或平台故障时仍可能影响任务启动。工作流会把 `state.json` 回写到仓库，每日最多 200 个逻辑推送。

正式工作流开启 `REQUIRE_AI_ENRICHMENT=true`：智谱翻译或总结失败时，本轮不发送、不写入已发送状态，下一分钟自动重试；智谱接口错误会在 Actions 日志中记录 HTTP 状态和 API 错误信息。

`Tracker watchdog` 工作流每 5 分钟检查一次 `monitor_heartbeat.json`：超过 15 分钟没有心跳、某次检查报错或跟踪任务停止时，通过 PushPlus 发送报警；恢复后发送一条恢复通知。同一故障只报警一次，避免重复打扰。

手动运行时可以选择 `push_latest` 做端到端测试，并把 `limit` 设为 `2`；日常定时运行默认使用 `latest`，只建立首次基线并等待新帖子。

## 重要边界

这是零成本、公开页面读取版，能工作不代表永久稳定：X 可能改变公开 HTML、限制匿名页面、对订阅内容只返回预览，或调整页面结构；aichainmap 的 feed 和免费详情中转源也属于第三方公开服务。代码不会绕过登录、验证码、付费订阅、限流或安全控制。

去重逻辑采用“先 claim、后发送”：这样优先避免同一条帖子被重复推送，但如果 PushPlus 在发送后发生网络中断，系统可能选择漏掉这一条，而不是下次重复发送。跨 GitHub 任务的绝对 exactly-once 仍然无法由免费文件状态保证。

原文不再按 420 字符截断；如果上游返回的是截断预览，消息会明确标记正文状态并给出 X 原文链接。`published_at` 表示帖子发布时间，`last_published_at` 是每个账号的发布时间水位，不是抓取时间。股票代码只对 `$TICKER` 和括号中的四位市场代码做保守提取，不把所有大写英文词都当成股票。
