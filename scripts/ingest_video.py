#!/usr/bin/env python3
"""Download a direct video URL, identify bytes, name it, extract actual endpoint frames."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def run(args):
    return subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout


def extension(path, probe):
    with path.open('rb') as f:
        head = f.read(4096)
    formats = set(probe['format']['format_name'].split(','))
    if head[4:8] == b'ftyp':
        brand = head[8:12]
        if brand == b'qt  ':
            return 'mov'
        if brand.startswith(b'3g2'):
            return '3g2'
        if brand.startswith(b'3gp'):
            return '3gp'
        return 'mp4'
    if head.startswith(b'\x1aE\xdf\xa3'):
        return 'webm' if b'webm' in head else 'mkv'
    if head.startswith(b'RIFF') and head[8:12] == b'AVI ':
        return 'avi'
    mapping = {'mpegts': 'ts', 'mpeg': 'mpg', 'flv': 'flv', 'ogg': 'ogv',
               'asf': 'asf', 'avi': 'avi', 'gif': 'gif'}
    for fmt, ext in mapping.items():
        if fmt in formats:
            return ext
    raise ValueError('无法可靠确定容器后缀，ffprobe格式为：' + ','.join(sorted(formats)))


def ingest(url, prompt, workspace):
    if urlsplit(url).scheme not in ('http', 'https'):
        raise ValueError('仅接受 HTTP/HTTPS 视频直链')
    for tool in ('ffmpeg', 'ffprobe'):
        if not shutil.which(tool):
            raise ValueError('缺少依赖：' + tool)
    folder = workspace.resolve() / 'assets' / datetime.now().strftime('%Y-%m-%d')
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.ingest-', dir=folder) as temp:
        temp = Path(temp)
        download = temp / 'download.part'
        req = Request(url, headers={'User-Agent': 'ingest-video/1.0', 'Accept-Encoding': 'identity'})
        with urlopen(req, timeout=60) as response, download.open('wb') as target:
            if urlsplit(response.url).scheme not in ('http', 'https'):
                raise ValueError('重定向后的地址不是 HTTP/HTTPS')
            shutil.copyfileobj(response, target, length=1024 * 1024)
            declared = response.headers.get('Content-Length')
        if not download.stat().st_size:
            raise ValueError('下载文件为空')
        if declared and download.stat().st_size != int(declared):
            raise ValueError('下载不完整，文件长度与 Content-Length 不符')
        digest = hashlib.md5()
        with download.open('rb') as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(block)
        probe = json.loads(run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(download)]))
        videos = [s for s in probe['streams'] if s['codec_type'] == 'video' and not s.get('disposition', {}).get('attached_pic')]
        if not videos:
            raise ValueError('下载内容没有有效视频轨道')
        ext = extension(download, probe)
        # Reserve the prefix to avoid concurrent runs overwriting each other.
        while True:
            stamp = time.time_ns() // 1_000_000
            prefix = '{}_{}'.format(stamp, digest.hexdigest())
            lock = folder / (prefix + '.lock')
            try:
                lock.touch(exist_ok=False)
                break
            except FileExistsError:
                continue
        video = folder / (prefix + '.' + ext)
        try:
            if video.exists():
                raise ValueError('目标文件已存在，请重试')
            download.rename(video)
            first = folder / (prefix + '_first.png')
            last = folder / (prefix + '_last.png')
            prompt_path = folder / (prefix + '_prompt.txt')
            prompt_path.write_text(prompt, encoding='utf-8')
            common = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-xerror', '-i', str(video), '-map', '0:{}'.format(videos[0]['index']), '-an', '-sn', '-dn']
            run(common + ['-frames:v', '1', '-threads', '1', '-y', str(temp / 'first.png')])
            # Decode all frames; overwrite one temporary PNG on every frame.
            # This remains correct with VFR, a one-frame clip, and imprecise duration metadata.
            run(common + ['-vsync', '0', '-threads', '1', '-update', '1', '-y', str(temp / 'last.png')])
            for name in ('first', 'last'):
                if not (temp / (name + '.png')).is_file():
                    raise ValueError('未能解码出' + name + '帧')
            (temp / 'first.png').rename(first)
            (temp / 'last.png').rename(last)
            result = dict(video=str(video), md5=digest.hexdigest(), extension=ext,
                          timestamp_ms=stamp, first_frame=str(first), last_frame=str(last),
                          prompt_file=str(prompt_path), prompt=prompt)
            manifest = folder / (prefix + '_metadata.json')
            result['metadata_file'] = str(manifest)
            manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            return result
        finally:
            lock.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prompt')
    group.add_argument('--prompt-file', type=Path)
    parser.add_argument('--workspace', type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        prompt = args.prompt_file.read_text(encoding='utf-8') if args.prompt_file else args.prompt
        print(json.dumps(ingest(args.url, prompt, args.workspace), ensure_ascii=False, indent=2))
    except Exception as exc:
        detail = exc.stderr if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        print('处理失败：' + detail, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
