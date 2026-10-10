# 抖音点赞视频增量下载器

这是一个面向 Windows 的个人工具：每天凌晨 5:00 打开抖音网页，读取登录账号的“喜欢”列表，下载尚未下载过的视频。

运行逻辑如下：

1. 第一次成功运行时，扫描当前账号能够看到的全部点赞视频并下载。
2. 工具把视频 ID 和本地文件路径保存到 `data/state.json`。
3. 后续运行仍会扫描点赞列表，但只处理未出现在成功下载状态中的视频。
4. 下载失败的视频不会被标记为完成，下一次会自动重试。

抖音页面和播放地址会变化，因此工具使用 Playwright 驱动浏览器，不保存账号密码，也不自动处理验证码。首次登录由用户在浏览器窗口中手动完成；登录态保存在本机 `data/browser-profile`，请不要把这个目录分享或提交到 Git。

## 安装

需要 Python 3.10 或更高版本。

在 PowerShell 中进入项目目录：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
Copy-Item config.example.json config.json
```

默认优先使用本机 Microsoft Edge（`browser_channel` 为 `msedge`）。如果机器没有 Edge，把 `config.json` 中的值改为 `null`，工具会使用 Playwright Chromium。

如抖音返回的是 HLS（`.m3u8`）播放地址，还需要把 `ffmpeg.exe` 加入系统 `PATH`；普通 MP4 地址不需要额外安装 ffmpeg。

## 首次使用

也可以直接双击项目目录中的 `一键启动.bat`。脚本会自动准备虚拟环境和 Playwright、创建配置文件、安装或更新每天 05:00 的任务；第一次运行时打开登录窗口，登录成功后才会保存登录标记，之后直接扫描并下载。

先手动登录并保存登录态：

```powershell
python app.py login
```

浏览器打开后，在窗口中扫码或完成登录；确认已经能看到账号内容后，回到 PowerShell 按 Enter。

先手动试跑一次：

```powershell
python app.py run
```

视频默认保存到 `H:\Movie\Douyin`，运行日志在 `data/run.log`，启动错误输出在 `data/startup.log`。建议先检查首次全量下载结果，再安装定时任务。

## 安装每天 5:00 任务

```powershell
python app.py install-task
```

任务名和时间来自 `config.json` 的 `task_name`、`schedule_time`。删除任务：

```powershell
python app.py uninstall-task
```

任务计划程序按当前 Windows 用户创建，电脑需要在 5:00 开机并允许该用户运行任务。若需要“用户未登录时也运行”或“唤醒计算机运行”，可以在 Windows 的任务计划程序中打开该任务的属性进一步调整；浏览器登录态仍必须先在同一用户下完成。

## 配置说明

实际运行配置只有 `config.json` 一份，字段含义如下：

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `likes_url` | `https://www.douyin.com/user/self?showTab=like` | 点赞列表入口，页面改版时可调整 |
| `output_dir` | `H:\Movie\Douyin` | 视频保存目录 |
| `data_dir` | `data` | 登录态、状态和日志目录 |
| `headless` | `true` | 定时任务建议保持无头模式，调试时可改为 `false` |
| `browser_channel` | `msedge` | 使用本机 Microsoft Edge；设为 `null` 使用 Playwright Chromium |
| `max_scroll_rounds` | `300` | 点赞列表最多滚动次数，点赞很多时可增大 |
| `scroll_pause_seconds` | `1.5` | 每次滚动后的等待时间 |
| `detail_wait_seconds` | `4.0` | 打开详情页等待媒体地址的时间 |
| `page_timeout_seconds` | `60` | 页面操作超时秒数 |
| `download_timeout_seconds` | `180` | 单个视频下载或 ffmpeg 超时秒数 |
| `minimum_video_duration_seconds` | `3.0` | 缺少页面时长信息时，低于该时长的 MP4 会按不完整文件处理；若详情接口提供了准确时长，则按该时长校验 |
| `max_items` | `0` | 每次最多处理数量；`0` 表示不限制 |
| `schedule_time` | `05:00` | Windows 任务每日执行时间 |
| `task_name` | `DouyinLikedVideosDownloader` | 任务计划程序名称 |
| `feishu_webhook_url` | `""` | 飞书自定义机器人 Webhook 地址；为空则不发送 |
| `feishu_webhook_secret` | `""` | 飞书机器人签名密钥；启用签名校验时填写 |

配置飞书运行结果通知：在 `config.json` 中填写 `feishu_webhook_url`；如果机器人启用了签名校验，同时填写 `feishu_webhook_secret`。每次 `run` 完成或发生异常时都会发送一条富文本报告，按运行概览、新下载、已跳过、失败分组，并列出视频标题、ID、保存路径或失败原因；通知发送失败不会影响视频下载。

## 常用排查

- `登录态已失效`：运行 `python app.py login` 重新登录；若使用一键脚本，失败后窗口会保持打开，错误也会写入 `data/startup.log`。
- `点赞列表中没有采集到视频链接`：确认账号确实有“喜欢”内容；如果抖音页面结构改版，检查 `likes_url` 并查看 `data/run.log`。
- 视频只有约 2 秒：程序会将其识别为不完整文件并自动重试其他媒体地址；旧短片不会被覆盖。检查 `data/run.log` 中的候选地址校验信息。
- 找到视频但下载失败：先检查登录是否有效，再检查 `data/run.log`；如果是 `.m3u8`，确认 `ffmpeg` 在 `PATH` 中。
- 想先限制首次下载数量：临时把 `max_items` 设置为一个小数值，确认工具正常后再改回 `0`。

请仅下载自己有权保存的内容，并遵守抖音的服务条款、版权和隐私要求。高频自动化访问可能触发平台风控，建议保持合理的滚动和下载间隔。
