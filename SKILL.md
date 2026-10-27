---
name: sk-happy
description: 输入视频URL及提示词，下载归档、计算MD5、识别真实容器格式并提取首尾帧；也可按用户要求将本地图片、视频等文件上传到云并返回资源URL。用于视频素材预处理、归档及本地文件上传；不执行视频生成。
---

# 视频素材预处理

## 输入与约定

- 获取用户提供的视频 HTTP/HTTPS 直链和提示词；缺失时询问，不编造。
- 将当前任务工作目录作为工作空间，不使用 Skill 自身目录作为输出目录。
- 使用运行机器的本地日期 `YYYY-MM-DD`、Unix 毫秒时间戳、32位小写MD5。
- 将提示词原样保存，用于后续任务；本 Skill 不据此修改视频或调用生成模型。
- 仅处理可直接下载的视频文件。不将网页、HLS/DASH清单当作视频，不绕过登录或DRM；遇到这种输入时请用户提供视频直链。

## 执行

1. 检查 `python3`、`ffmpeg`、`ffprobe`；缺失时说明依赖，不假报成功。
2. 将提示词写入工作空间内的临时 UTF-8 文件，避免多行、引号或特殊字符被 shell 解释。
3. 解析本 Skill 的绝对目录，调用随附脚本。使用结构化进程参数或可靠的 shell 引号，不拼接执行用户输入。

```bash
python3 /绝对路径/sk-happy/scripts/ingest_video.py \
  --url 'https://example.com/video.mp4' \
  --prompt-file '/工作空间/prompt.txt' \
  --workspace '/工作空间'
```

4. 让脚本顺序完成下载、Python分块计算MD5、根据文件字节及ffprobe识别真实容器后缀、重命名、FFmpeg提取首尾帧。不要使用URL后缀或HTTP Content-Type判断真实类型。
5. 读取成功退出后的JSON，核实视频、两张PNG、提示词文件及元数据文件存在，再报告路径。必要时查看两张PNG。
6. 失败时报告具体阶段与错误。已归档的视频和提示词会保留用于排查，不声称已有完整结果，不删除用户原文件。

## 输出

在 `assets/YYYY-MM-DD/` 下保存：

- `<毫秒时间戳>_<MD5>.<真实容器后缀>`
- `<毫秒时间戳>_<MD5>_first.png`
- `<毫秒时间戳>_<MD5>_last.png`
- `<毫秒时间戳>_<MD5>_prompt.txt`
- `<毫秒时间戳>_<MD5>_metadata.json`

首帧是首个非封面视频轨的第一张解码帧，尾帧是同一轨最后一张解码帧。单帧视频允许两张图相同。为保证尾帧准确，脚本顺序解码全片并持续覆盖临时尾帧图片，处理长视频可能较慢。文件类型指容器格式，不是H.264/H.265等视频编码。MD5基于原始下载字节，重命名不转码。支持MP4、MOV、3GP、3G2、WebM、MKV、AVI、TS、MPEG、FLV、Ogg及ASF；无法可靠识别时拒绝猜测后缀。

## 本地文件上传到云

当用户要求上传本地图片、视频或其他文件并获取资源 URL 时，使用以下接口。单独上传不要求视频 URL 或提示词，也不必执行前面的下载预处理。预处理完成后仅在用户要求上传时上传指定产物。

- 工具依赖：`curl`（也可使用支持 multipart/form-data 的 HTTP 客户端）。
- 请求方法：`POST`。
- Host：从当前工程根目录 `.env` 的 `SK_HAPPY_UPLOAD_HOST` 读取，值包含协议和可选端口。按键解析配置，不执行 `.env` 内容；缺失或不是 HTTP/HTTPS 地址时报告配置错误，不使用硬编码回退值。
- 接口：`${SK_HAPPY_UPLOAD_HOST%/}/pubbiz/common/upload-test`。
- 无需额外请求头。
- 请求体：`multipart/form-data`，文件字段名为 `file`。让客户端自动设置含 boundary 的 Content-Type。

先确认目标本地文件存在，并将 `.env` 中读取的 host 赋给进程变量 `SK_HAPPY_UPLOAD_HOST`，再执行请求。将示例中的路径替换为用户指定文件的绝对路径，保留可靠的引号；不要把 Markdown 链接语法或终端续行提示符 `>` 带入命令。

```bash
curl --fail-with-body --silent --show-error --location \
  "${SK_HAPPY_UPLOAD_HOST%/}/pubbiz/common/upload-test" \
  --form 'file=@"/Users/jv/Desktop/图片/22.png"'
```

成功响应示例：

```json
{"code":2000,"msg":"成功","data":"https://d1so8k724hha4.cloudfront.net/jv-test/hypit-test/2026-10-27/1793090503187_22.png"}
```

解析 JSON，仅在 HTTP 请求成功、`code` 为 `2000` 且 `data` 为非空 HTTP/HTTPS URL 时报告上传成功。`data` 就是资源 URL，向用户返回可点击链接及对应本地文件路径。失败时报告 HTTP 状态或业务 `code`、`msg`，不要编造 URL。上传不删除或覆盖本地原文件。接口的文件大小、类型限制未给出，遇到服务端拒绝时以实际响应为准。
