# 抖音点赞视频增量下载器

一个面向 Windows 的个人工具：使用 Playwright 打开抖音点赞列表，增量下载尚未保存的视频，并在每次运行结束后通过飞书机器人发送运行报告。

## 功能

- 手动完成一次登录，后续复用本机登录态；不保存账号密码，也不自动处理验证码。
- 扫描登录账号可见的“喜欢”列表，按视频 ID 去重并增量下载。
- 自动滚动点赞列表，兼容常见的动态卡片和异步加载场景。
- 对失效媒体地址、短片段、HTTP 错误和临时网络中断尝试其他候选地址。
- 将成功下载状态保存到 `data/state.json`，失败视频下次自动重试。
- 每次 `run` 完成或发生异常后发送飞书富文本报告，列出新下载、已跳过和失败视频的明细。
- 支持 Windows 任务计划程序按固定时间运行。

## 工作流程

1. 打开 `likes_url` 指定的点赞列表。
2. 读取视频 ID、标题和作者，并继续滚动加载列表。
3. 查询每个未完成视频的媒体地址，按候选地址下载并校验文件。
4. 成功下载后写入 `data/state.json`；已存在的有效文件跳过，失败项保留到本次报告并等待下次重试。
5. 生成运行汇总和视频明细，通过飞书 Webhook 发送报告。

## 环境要求

- Windows 10/11
- Python 3.10 或更高版本
- Microsoft Edge，或 Playwright Chromium
- 下载 HLS（`.m3u8`）地址时，需要将 `ffmpeg.exe` 加入系统 `PATH`

## 安装

在 PowerShell 中进入项目目录后执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
Copy-Item config.example.json config.json
```

默认使用本机 Microsoft Edge（`browser_channel` 为 `msedge`）。如果机器没有 Edge，将 `config.json` 中的 `browser_channel` 改为 `null`，程序会改用 Playwright Chromium。

也可以直接双击项目目录中的 `一键启动.bat`，由脚本自动准备虚拟环境、Playwright、配置文件和定时任务。

## 首次登录与手动运行

先打开可见浏览器完成登录并保存登录态：

```powershell
python app.py login
```

在浏览器中扫码或完成登录。确认已经能看到账号内容后，回到 PowerShell 按一次 Enter。

随后手动运行一次：

```powershell
python app.py run
```

默认视频保存到 `H:\Movie\Douyin`。建议先确认手动运行正常，再安装定时任务。

## 飞书通知

### 配置机器人

1. 在目标飞书群中添加一个自定义机器人。
2. 复制机器人 Webhook 地址，填写到 `config.json` 的 `feishu_webhook_url`。
3. 如果机器人启用了签名校验，将安全设置中的密钥填写到 `feishu_webhook_secret`。
4. 不需要签名校验时，将 `feishu_webhook_secret` 保持为空。

示例：

```json
{
  "feishu_webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/你的机器人地址",
  "feishu_webhook_secret": "你的签名密钥"
}
```

Webhook 地址和签名密钥属于敏感配置，仅保存在本机 `config.json`，不要提交到 Git 或发送到公开渠道。项目模板中的两个字段默认为空。

### 报告内容

运行报告采用飞书富文本消息，按以下层级排列：

```text
📊 运行概览
  完成时间、运行结果、发现/下载/跳过/失败数量

📥 新下载（数量）
  标题、视频 ID、作者、保存路径

⏭️ 已跳过（数量）
  标题、视频 ID、保存路径

❌ 失败（数量）
  标题、视频 ID、作者、失败原因
```

如果运行异常，也会发送异常类型和错误信息。通知发送失败只记录到运行日志，不会让视频下载任务回滚或失败。

## 安装每日任务

任务名称和运行时间来自 `config.json` 的 `task_name` 与 `schedule_time`：

```powershell
python app.py install-task
```

删除任务：

```powershell
python app.py uninstall-task
```

任务计划程序按当前 Windows 用户创建。若需要“用户未登录时运行”或“唤醒计算机运行”，可在 Windows 任务计划程序中打开任务属性进一步设置；浏览器登录态仍必须先在同一用户环境下完成。

## 配置说明

实际运行配置以 `config.json` 为准。`config.example.json` 只提供可复制的模板。

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `likes_url` | `https://www.douyin.com/user/self?showTab=like` | 点赞列表入口，页面改版时可调整 |
| `output_dir` | `H:\Movie\Douyin` | 视频保存目录 |
| `data_dir` | `data` | 登录态、状态和日志目录 |
| `headless` | `true` | 定时任务建议保持无头模式；调试时可改为 `false` |
| `browser_channel` | `msedge` | 使用本机 Edge；设为 `null` 使用 Playwright Chromium |
| `max_scroll_rounds` | `300` | 点赞列表最多滚动次数 |
| `scroll_pause_seconds` | `1.5` | 每次滚动后的等待时间 |
| `detail_wait_seconds` | `4.0` | 打开详情页等待媒体地址的时间 |
| `page_timeout_seconds` | `60` | 页面操作超时秒数 |
| `download_timeout_seconds` | `180` | 单个视频下载或 ffmpeg 超时秒数 |
| `minimum_video_duration_seconds` | `3.0` | 低于该时长的媒体按不完整文件处理 |
| `max_items` | `0` | 每次最多处理数量；`0` 表示不限制 |
| `schedule_time` | `05:00` | Windows 任务每日执行时间 |
| `task_name` | `DouyinLikedVideosDownloader` | 任务计划程序名称 |
| `feishu_webhook_url` | `""` | 飞书自定义机器人 Webhook 地址；为空则不发送 |
| `feishu_webhook_secret` | `""` | 飞书机器人签名密钥；启用签名校验时填写 |

## 文件与隐私

| 路径 | 用途 | 是否提交 Git |
| --- | --- | --- |
| `config.json` | 本机运行配置，可能包含 Webhook 密钥 | 否 |
| `data/browser-profile` | 浏览器登录态 | 否 |
| `data/storage_state.json` | 登录态快照 | 否 |
| `data/login.success` | 登录成功标记 | 否 |
| `data/state.json` | 已下载状态和本地路径 | 否 |
| `data/run.log` | 运行日志 | 否 |
| `data/startup.log` | 启动错误输出 | 否 |
| `downloads/` | 项目内下载目录（如使用） | 否 |
| `config.example.json` | 不含密钥的配置模板 | 是 |

以上运行数据已由 `.gitignore` 排除。请不要分享 `data/browser-profile`、`data/storage_state.json`、`config.json` 或包含 Webhook 密钥的文件。

## 常用排查

### 登录态失效

重新运行：

```powershell
python app.py login
```

若使用一键脚本，失败后窗口会保持打开；启动错误会写入 `data/startup.log`。

### 点赞列表没有视频链接

先确认账号确实有可见的“喜欢”内容，再检查 `data/run.log`。如果抖音页面结构发生变化，确认 `likes_url` 仍指向点赞列表，并重新运行登录流程。

### 视频下载失败或只有几秒

程序会校验媒体文件；短片段会自动尝试其他媒体地址。对于 `.m3u8` 地址，确认 `ffmpeg` 已加入 `PATH`。具体候选地址和失败原因见 `data/run.log`，飞书报告也会列出最终失败原因。

### 飞书没有收到报告

依次检查：

1. `config.json` 中 `feishu_webhook_url` 是否填写正确。
2. 如果启用了签名校验，`feishu_webhook_secret` 是否正确。
3. 查看 `data/run.log` 中的“飞书运行结果通知”记录。
4. 先执行 `python app.py run` 手动验证网络和机器人配置。

通知失败不会影响视频下载；修复 Webhook 后，下次运行会继续发送报告。

## 开发与测试

运行语法检查和测试：

```powershell
python -X utf8 -m compileall douyin_likes_downloader
python -m unittest discover -s tests -v
```

测试不会读取真实登录态，也不会向飞书发送消息。

## 退出码

| 退出码 | 含义 |
| --- | --- |
| `0` | 运行完成且没有下载失败 |
| `1` | 运行完成但存在视频下载失败，或发生未处理运行异常 |
| `2` | 配置、浏览器或任务计划程序错误 |
| `130` | 用户中断运行 |

请仅下载自己有权保存的内容，并遵守抖音服务条款、版权和隐私要求。高频自动化访问可能触发平台风控，建议保持合理的滚动和下载间隔。
