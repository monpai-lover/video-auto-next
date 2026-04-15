# 网络水课自动化 / video-auto-next

退役军人课程视频站专用自动化脚本。

基于 Python + Playwright，实现：

- 自动复用登录态
- 自动切到“视频”标签页
- 自动播放集合内下一节
- 一个播放集完成后返回选择页，继续下一个播放集
- 根据“所看时长”接近总时长自动跳过已接近完成的视频
- 修复误跳到视频末尾的问题
- 回到父页面后自动等待并下拉，尽量加载完整播放集列表

## 功能概览

### 1. 自动切到“视频”标签页

很多集合详情页默认先落在 **“详情”** 标签，不会直接显示视频列表。脚本会主动尝试切到 **“视频”** 标签页，再开始播放。

成功时会打印：

```text
[fix] 已自动切换到“视频”标签页
```

### 2. 登录态持久化

脚本会在 `--profile-dir` 下保存：

- 浏览器 profile
- `auth_state.json`

保存内容包括：

- cookies
- `localStorage`
- `sessionStorage`

### 3. 集合内自动播放

进入集合详情页后会：

- 自动定位当前/下一可播放视频
- 优先顺序播放
- 最后一节完成后退出当前集合

### 4. 播放集之间自动切换

如果从父页面或详情页启动，当前集合完成后都会回到：

```text
https://peixun.tyjr.sh.gov.cn/azqPhoneService/#/onlineTrainList
```

然后重新抓取播放集列表，继续调度后续未完成集合。

### 5. 父页面懒加载处理

父页面播放集列表不是一次性渲染的。脚本现在会：

- 等待播放集列表出现
- 自动向下滚动
- 等到数量稳定后再开始选择集合

### 6. 所看时长自动跳过

如果列表里的：

```text
所看时长
```

与视频总时长只差很少（当前默认 `<= 5 秒`），脚本会把该视频视为已完成，直接跳到下一节。

### 7. 误跳到末尾修复

如果视频刚开始就异常跳到最后几秒，脚本会尝试：

- Video.js API 修复
- 原生 `video.currentTime` 修复
- 进度条点击修复

## 环境要求

- Python 3
- Playwright
- Chromium

安装示例：

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
```

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

### 从详情页直接启动

```bash
python3 main.py \
  --url 'https://peixun.tyjr.sh.gov.cn/azqPhoneService/#/trainDetail?id=xxx&relationId=yyy' \
  --profile-dir ./browser-profile \
  --safe-seek 2
```

## 主要参数

- `--url`：父页面或详情页 URL
- `--profile-dir`：浏览器配置目录
- `--safe-seek`：误跳尾时拉回秒数
- `--poll-interval`：轮询间隔
- `--login-wait`：手动登录后按回车继续
- `--headless`：无头模式

## 测试

```bash
cd /Users/goatdie/video-auto-next
python3 -m py_compile logic.py main.py
python3 -m unittest tests/test_logic.py -v
```
