# -*- coding: utf-8 -*-
"""静态门禁：所有以文本模式读子进程输出的调用都必须显式指定 encoding

中文 Windows 上 locale 默认编码是 cp936。子进程（ffmpeg / pip / python）写的是
UTF-8，用 text=True 而不给 encoding 时，Python 的读取线程会在遇到非法 GBK 字节处
抛 UnicodeDecodeError —— 而 subprocess.run **不会**把这个异常抛给调用方，它只是把
stdout/stderr 变成 None。于是 ffmpeg 真的失败时，错误信息退化成"未知错误"，
`does not contain any stream` 这类按内容的特判也永远命中不了（2026-10-30 实测）。

这类问题只在路径含中文时出现，而开发期的测试文件名往往是 ASCII，所以行为测试
盖不住它，改用静态扫描兜底：新写一个调用点也逃不掉。
"""
import ast
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = ROOT
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

SKIP_DIRS = {"runtime", "build", "dist", "TEMP", ".git", "__pycache__", ".venv"}
SUBPROCESS_FUNCS = {"run", "Popen", "check_output", "call", "check_call"}

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def python_files():
    for path in sorted(ROOT.rglob("*.py")):
        parts = set(path.relative_to(ROOT).parts)
        if parts & SKIP_DIRS:
            continue
        yield path


def flag_value(node):
    """关键字的值是不是字面量 True（变量传参按需要 encoding 处理，保守算违规）"""
    if isinstance(node, ast.Constant):
        return node.value is True
    return False


def scan(path):
    """返回该文件里所有『文本模式但没写 encoding』的调用行号"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError) as e:
        return [(-1, f"解析失败: {e}")]
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in SUBPROCESS_FUNCS:
            continue
        keywords = {kw.arg for kw in node.keywords if kw.arg}
        text_on = any(
            flag_value(kw.value) for kw in node.keywords
            if kw.arg in ("text", "universal_newlines")
        )
        if text_on and "encoding" not in keywords:
            bad.append((node.lineno, "文本模式未指定 encoding"))
        elif text_on and "errors" not in keywords:
            bad.append((node.lineno, "指定了 encoding 但没有 errors=replace"))
    return bad


offenders = []
for f in python_files():
    for line, why in scan(f):
        offenders.append((f.relative_to(ROOT).as_posix(), line, why))

total = sum(1 for _ in python_files())
check("扫描覆盖到源码文件", total > 10, f"{total} 个 .py 文件")
check("没有『文本模式未指定 encoding』的子进程调用", not offenders,
      "; ".join(f"{p}:{ln} {why}" for p, ln, why in offenders[:6]))

# 门禁自身也要能抓到反例，否则它是空转的
sample = 'import subprocess\nsubprocess.run(["x"], capture_output=True, text=True)\n'
path = ROOT / "TEMP" / "_encoding_canary.py"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(sample, encoding="utf-8")
found = scan(path)
path.unlink(missing_ok=True)
check("门禁能抓到漏写 encoding 的调用", found and found[0][0] == 2, str(found))

sample2 = ('import subprocess\n'
           'subprocess.run(["x"], text=True, encoding="utf-8", errors="replace")\n'
           'subprocess.run(["y"], capture_output=True)\n'
           'subprocess.Popen(["z"], text=True, encoding="utf-8", errors="replace")\n')
path.write_text(sample2, encoding="utf-8")
found2 = [row for row in scan(path) if "encoding" in row[1]]
path.unlink(missing_ok=True)
check("写法合规时不误报", not found2, str(found2))

sample3 = ('import subprocess\n'
           'subprocess.run(["x"], universal_newlines=True, encoding="utf-8", errors="replace")\n')
path.write_text(sample3, encoding="utf-8")
found3 = scan(path)
path.unlink(missing_ok=True)
check("universal_newlines 同样纳入检查且不误报", not found3, str(found3))

# 只写 encoding 不写 errors 也要抓到：ffmpeg 极端情况下会吐出非法字节，
# 缺 errors=replace 时同样会打死解码线程
sample4 = ('import subprocess\n'
           'subprocess.run(["x"], text=True, encoding="utf-8")\n')
path.write_text(sample4, encoding="utf-8")
found4 = scan(path)
path.unlink(missing_ok=True)
check("缺 errors=replace 也会被抓到", found4 and "errors" in found4[0][1], str(found4))

print(f"\n===== {len(PASS)} passed, {len(FAIL)} failed =====")
sys.stdout.flush()
os._exit(0 if not FAIL else 1)
