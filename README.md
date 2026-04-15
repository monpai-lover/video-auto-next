# video-auto-next

退役军人课程视频站专用自动化脚本（双层自动播放增强版）。

## 新增：自动切到“视频”标签页

很多集合详情页默认先落在 **“详情”** 标签，不会直接显示视频列表。现在脚本在进入集合详情页后会：

1. 检查当前激活的 tab 是否为 `视频`
2. 如果不是，就自动点击 `视频`
3. 等待 `.video_list` 出现
4. 再开始自动播放逻辑

如果成功切换，会打印：

```text
[fix] 已自动切换到“视频”标签页
```

## 登录态持久化

现在脚本会在 `--profile-dir` 目录下自动保存登录态：

- 浏览器 profile：`browser-profile/`
- 额外状态文件：`browser-profile/auth_state.json`

保存内容包括：

- cookies
- 当前站点的 `localStorage`
- 当前站点的 `sessionStorage`

## 运行方式

### 第一次登录并保存状态

```bash
cd /Users/goatdie/video-auto-next
python3 main.py \
  --url 'https://zxsp.tyjr.sh.gov.cn/#/onlineTrain' \
  --profile-dir /Users/goatdie/video-auto-next/browser-profile \
  --safe-seek 2 \
  --login-wait
```

### 后续直接复用登录态

```bash
cd /Users/goatdie/video-auto-next
python3 main.py \
  --url 'https://zxsp.tyjr.sh.gov.cn/#/onlineTrain' \
  --profile-dir /Users/goatdie/video-auto-next/browser-profile \
  --safe-seek 2
```
