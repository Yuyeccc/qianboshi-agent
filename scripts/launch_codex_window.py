#!/usr/bin/env python3
"""开可见终端窗口跑 codex —— 飞书触发链路的执行端（dadafastrun 工作流落地）

用法:
  python launch_codex_window.py "任务prompt"
  python launch_codex_window.py "任务prompt" --model gpt-5.5 --yolo --title "钱博士-回测"
  python launch_codex_window.py --check          # 检测当前是否有codex窗口在跑

原理: cmd /c start 打开一个新的可见 cmd 窗口, 窗口内 cd 到项目目录并跑 codex。
窗口保持打开 (/k), codex 跑完/报错都不会闪退, 用户可以盯着窗口看实时输出。
"""
import subprocess, sys, datetime, os

PROJECT = r'E:\qianboshi-agent'
LOG = os.path.join(PROJECT, 'data', 'tmp', 'codex_window_launches.log')

def log(msg):
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(f'[{datetime.datetime.now().isoformat()}] {msg}\n')

def sanitize(s: str) -> str:
    """cmd 引号嵌套太脆, 去掉 prompt 里的双引号, 用单引号代替"""
    return s.replace('"', "'").replace('&', '^&')

def check():
    """检测当前 codex 窗口进程"""
    r = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq codex.exe'],
                       capture_output=True, timeout=30)
    out = r.stdout.decode('gbk', errors='replace')
    lines = [l for l in out.splitlines() if 'codex' in l.lower()]
    if lines:
        print(f'检测到 codex 进程 {len(lines)} 个:')
        for l in lines[:10]:
            print(' ', l.strip())
    else:
        print('当前没有 codex 进程在跑')
    return 0

def launch(prompt: str, model: str = 'gpt-5.5', yolo: bool = False, title: str = None, logfile: str = None):
    ts = datetime.datetime.now().strftime('%m%d-%H%M%S')
    win_title = title or f'codex-{ts}'
    flag = '--dangerously-bypass-approvals-and-sandbox'
    # 窗口标题用ASCII, 避免 cmd 标题中文乱码
    inner = f'cd /d {PROJECT} && codex -m {model} exec {flag} "{sanitize(prompt)}"'
    if logfile:
        inner += f' > "{logfile}" 2>&1'
    # /c start 开新窗口并立即返回; /k 保持窗口不闪退
    full_cmd = f'cmd /c start "{win_title}" cmd /k {inner}'
    log(f'launch title={win_title} model={model} flag={flag} prompt={prompt[:120]} logfile={logfile}')
    subprocess.Popen(full_cmd, shell=True)
    print(f'已开窗口: [{win_title}]  (模型={model}, 模式={flag})')
    print(f'命令: {inner}')
    print(f'窗口会保持打开, 跑完直接看窗口内输出即可')
    if logfile:
        print(f'输出重定向: {logfile}')
    print(f'启动日志: {LOG}')
    return 0

if __name__ == '__main__':
    args = sys.argv[1:]
    if args and args[0] == '--check':
        sys.exit(check())
    if not args:
        print(__doc__)
        sys.exit(1)
    prompt = args[0]
    model = 'gpt-5.5'
    yolo = False
    title = None
    logfile = None
    i = 1
    while i < len(args):
        if args[i] == '--model' and i + 1 < len(args):
            model = args[i + 1]; i += 2
        elif args[i] == '--yolo':
            yolo = True; i += 1
        elif args[i] == '--title' and i + 1 < len(args):
            title = args[i + 1]; i += 2
        elif args[i] == '--log' and i + 1 < len(args):
            logfile = args[i + 1]; i += 2
        else:
            i += 1
    sys.exit(launch(prompt, model, yolo, title, logfile))
