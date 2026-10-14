# -*- coding: utf-8 -*-
"""把本地目录发布/更新到 GitHub 仓库（走 Git Data API，支持二进制文件）

适用：`git push` 连不上 github.com，但 api.github.com 通。

用法：
    1. 改下面 CONFIG 五个常量
    2. python push_files.py

首次提交与后续更新都能用：
    首次会先用 Contents API 建初始提交（空仓库用不了 blobs API）
    更新时会自动读当前分支 HEAD 作为 parents
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

# ============================== CONFIG ==============================
OWNER = 'chuiziyao'
REPO = 'wushuang-download-skill'
BRANCH = 'main'
ROOT = r'C:\Users\chuiz\WorkBuddy\2026-10-02-14-59-47\wushuang-download-skill'          # 要发布的本地目录
TOKEN_FILE = os.path.join(os.path.expanduser('~'), '.workbuddy', 'github-token.json')
COMMIT_MSG = 'chore: 更新'
# ====================================================================

API = 'https://api.github.com'
SKIP_DIRS = {'.git', '__pycache__', 'build', 'dist', 'node_modules', '.venv', 'venv'}
SKIP_FILES = {'.DS_Store', 'Thumbs.db'}


def load_token():
    with open(TOKEN_FILE, encoding='utf-8') as f:
        return json.load(f)['github_token']


HDR = {
    'Authorization': 'token ' + load_token(),
    'Accept': 'application/vnd.github+json',
    'Content-Type': 'application/json',
    'User-Agent': 'gh-publish-fallback',
    'X-GitHub-Api-Version': '2022-11-28',
}


def call(method, url, payload=None, tries=4):
    body = json.dumps(payload).encode('utf-8') if payload is not None else None
    last = None
    for n in range(tries):
        try:
            req = urllib.request.Request(url, data=body, headers=HDR, method=method)
            with urllib.request.urlopen(req, timeout=180) as r:
                raw = r.read().decode('utf-8', 'ignore')
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode('utf-8', 'ignore')[:300]
            last = f'HTTP {e.code}: {detail}'
            if e.code in (401, 403, 404, 422):      # 不可重试
                break
        except Exception as e:
            last = repr(e)
        time.sleep(1.5 * (n + 1))
    raise RuntimeError(f'{method} {url} 失败 → {last}')


def walk():
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn in SKIP_FILES:
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, ROOT).replace('\\', '/')
            out.append((rel, full))
    return sorted(out)


def ensure_branch():
    """返回当前分支 HEAD 的 sha；空仓库则先用 Contents API 建初始提交。

    坑：空仓库查 ref 返回的是 **409「Git Repository is empty」**，
    而有分支但分支名不对时返回 404。两个都要当「需要 bootstrap」处理。
    """
    try:
        ref = call('GET', f'{API}/repos/{OWNER}/{REPO}/git/ref/heads/{BRANCH}')
        return ref['object']['sha'], False
    except RuntimeError as e:
        if not ('HTTP 404' in str(e) or 'HTTP 409' in str(e)):
            raise
    # 空仓库 → 先 bootstrap
    boot = call('PUT', f'{API}/repos/{OWNER}/{REPO}/contents/README.md',
                {'message': 'chore: 初始化仓库',
                 'content': base64.b64encode(b'# ' + REPO.encode() + b'\n').decode('ascii'),
                 'branch': BRANCH})
    return boot['commit']['sha'], True


def main():
    files = walk()
    print(f'目录 {ROOT}\n待提交 {len(files)} 个文件\n')

    base_sha, booted = ensure_branch()
    print(f'基线提交 {base_sha[:8]}' + ('（本仓库之前为空，已自动 bootstrap）' if booted else '') + '\n')

    entries = []
    for i, (rel, full) in enumerate(files, 1):
        raw = open(full, 'rb').read()
        r = call('POST', f'{API}/repos/{OWNER}/{REPO}/git/blobs',
                 {'content': base64.b64encode(raw).decode('ascii'), 'encoding': 'base64'})
        entries.append({'path': rel, 'mode': '100644', 'type': 'blob', 'sha': r['sha']})
        print(f'  [{i:>3}/{len(files)}] {rel:<46} {len(raw):>10,} B')

    tree = call('POST', f'{API}/repos/{OWNER}/{REPO}/git/trees', {'tree': entries})
    print(f'\ntree   = {tree["sha"]}')

    commit = call('POST', f'{API}/repos/{OWNER}/{REPO}/git/commits',
                  {'message': COMMIT_MSG, 'tree': tree['sha'], 'parents': [base_sha]})
    print(f'commit = {commit["sha"]}')

    if booted:
        call('PATCH', f'{API}/repos/{OWNER}/{REPO}/git/refs/heads/{BRANCH}',
             {'sha': commit['sha'], 'force': True})
    else:
        call('PATCH', f'{API}/repos/{OWNER}/{REPO}/git/refs/heads/{BRANCH}',
             {'sha': commit['sha']})
    print(f'refs/heads/{BRANCH} 已更新 ✅')
    print(f'\nhttps://github.com/{OWNER}/{REPO}')


if __name__ == '__main__':
    sys.exit(main())
