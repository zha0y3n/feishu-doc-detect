#!/usr/bin/env python3
"""
把 Markdown 文件中标题的最高级别调整为指定数字，其余标题等距平移。

例: 原文有 1/2/3/4 级标题，指定 2 → 变为 2/3/4/5 级。

只识别真正的 ATX 标题（行首 0~3 个空格 + 1~6 个 # + 空格或行尾），
会跳过以下内容中的 #：
  - ``` / ~~~ 围栏代码块（含代码里的 # 注释）
  - 4 空格/Tab 缩进的代码块
  - YAML front matter（文件开头的 --- ... ---）
  - HTML 注释 <!-- ... -->
  - 行内的 #（如 #tag、C#、`#include`）
  - 转义的 \\#

可选 -b：整理空行（不检查代码块、front matter、HTML 注释内部）
  - 单独 1 个空行 → 删除
  - 连续 3 个空行 → 变为 1 个空行
  - 出现其它数量的连续空行 → 报告行号并终止，不修改任何文件

用法:
  fsdd input.md 2              # 直接修改原文件，并生成 input.md.bak 备份
  fsdd input.md 2 -o out.md    # 写到新文件，原文件不动
  fsdd input.md 2 -b           # 同时整理空行
"""
import argparse
import re
import shutil
import sys

from . import clipboard

HEADING_RE = re.compile(r'^( {0,3})(#{1,6})(?=[ \t]|$)(.*)$')
FENCE_RE = re.compile(r'^ {0,3}(`{3,}|~{3,})(.*)$')


def scan(lines):
    """
    返回 (headings, protected)
      headings : 标题行的 [(行号, 级别, 匹配对象)]
      protected: 属于代码块 / front matter / HTML 注释的行号集合（含边界行）
    """
    headings = []
    protected = set()
    fence = None          # 当前所在围栏的 (字符, 长度)
    in_comment = False
    start = 0

    # YAML front matter
    if lines and lines[0].rstrip('\r\n') == '---':
        for j in range(1, len(lines)):
            if lines[j].rstrip('\r\n') in ('---', '...'):
                protected.update(range(0, j + 1))
                start = j + 1
                break

    for n in range(start, len(lines)):
        line = lines[n].rstrip('\r\n')

        if fence:
            protected.add(n)
            m = FENCE_RE.match(line)
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= fence[1] \
                    and not m.group(2).strip():
                fence = None
            continue

        if in_comment:
            protected.add(n)
            if '-->' in line:
                in_comment = False
            continue

        m = FENCE_RE.match(line)
        if m:
            marker, info = m.group(1), m.group(2)
            # 反引号围栏的 info 字符串里不能含反引号
            if not (marker[0] == '`' and '`' in info):
                fence = (marker[0], len(marker))
                protected.add(n)
                continue

        stripped = line.lstrip()
        if stripped.startswith('<!--') and '-->' not in stripped[4:]:
            in_comment = True
            protected.add(n)
            continue

        m = HEADING_RE.match(line)
        if m:
            headings.append((n, len(m.group(2)), m))
    return headings, protected


def shift_headings(lines, headings, target):
    """原地修改 lines 中的标题行，返回 (偏移量, 被截断到 6 级的标题列表)。"""
    if not headings:
        return 0, []
    offset = target - min(h[1] for h in headings)
    clamped = []
    for n, level, m in headings:
        new_level = level + offset
        if new_level > 6:
            clamped.append((n + 1, level, new_level))
            new_level = 6
        eol = lines[n][len(lines[n].rstrip('\r\n')):]
        lines[n] = f"{m.group(1)}{'#' * new_level}{m.group(3)}{eol}"
    return offset, clamped


def blank_runs(lines, protected):
    """找出代码块等区域之外的连续空行，返回 [(起始行号, 数量)]（行号从 0 开始）。"""
    runs = []
    n = 0
    while n < len(lines):
        if n not in protected and not lines[n].strip():
            s = n
            while n < len(lines) and n not in protected and not lines[n].strip():
                n += 1
            runs.append((s, n - s))
        else:
            n += 1
    return runs


def squeeze_blank_lines(lines, runs):
    """1 个空行删除，3 个空行保留 1 个。调用前需确保 runs 只含 1 和 3。"""
    drop = set()
    for s, count in runs:
        drop.update(range(s, s + count) if count == 1 else range(s + 1, s + count))
    return [l for i, l in enumerate(lines) if i not in drop]


def main():
    # Windows 控制台可能不是 UTF-8，提示信息遇到无法编码的字符时替换而不是崩溃
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors='replace')
        except (AttributeError, ValueError):
            pass

    p = argparse.ArgumentParser(prog='feishu-doc-detect', description='调整 Markdown 标题的最高级别')
    p.add_argument('input', help='输入的 Markdown 文件')
    p.add_argument('level', type=int, help='目标最高级别 (1-6)')
    p.add_argument('-o', '--output', help='写到新文件（默认直接修改原文件并保留 .bak 备份）')
    p.add_argument('-b', '--blank-lines', action='store_true',
                   help='整理空行：单独 1 个空行删除，连续 3 个空行变为 1 个；'
                        '出现其它数量时报告行号并终止（不检查代码块内部）')
    p.add_argument('--no-copy', action='store_true', help='不把转换后的内容复制到剪切板')
    p.add_argument('--encoding', default='utf-8', help='文件编码，默认 utf-8')
    args = p.parse_args()

    if not 1 <= args.level <= 6:
        p.error('level 必须在 1~6 之间')

    with open(args.input, encoding=args.encoding, newline='') as f:
        lines = f.read().splitlines(keepends=True)

    headings, protected = scan(lines)

    runs = []
    if args.blank_lines:
        runs = blank_runs(lines, protected)
        bad = [(s, c) for s, c in runs if c not in (1, 3)]
        if bad:
            print(f'错误: 发现 {len(bad)} 处连续空行数量不是 1 或 3，未修改任何文件：', file=sys.stderr)
            for s, c in bad:
                where = f'第 {s + 1} 行' if c == 1 else f'第 {s + 1}-{s + c} 行'
                print(f'  {where}: 连续 {c} 个空行', file=sys.stderr)
            sys.exit(1)

    offset, clamped = shift_headings(lines, headings, args.level)
    for line_no, old, new in clamped:
        print(f'警告: 第 {line_no} 行 {old} 级标题需变为 {new} 级，超过 6 级上限，已设为 6 级',
              file=sys.stderr)

    if args.blank_lines:
        lines = squeeze_blank_lines(lines, runs)

    if args.output:
        out_path = args.output
    else:
        shutil.copyfile(args.input, args.input + '.bak')
        out_path = args.input

    result = ''.join(lines)
    with open(out_path, 'w', encoding=args.encoding, newline='') as f:
        f.write(result)
    msg = f'完成: 标题级别偏移 {offset:+d}，已写入 {out_path}'
    if args.blank_lines:
        msg += f'，删除 {sum(1 for _, c in runs if c == 1)} 处单独空行，' \
               f'合并 {sum(1 for _, c in runs if c == 3)} 处三连空行'
    if not args.output:
        msg += f'（备份: {args.input}.bak）'
    print(msg, file=sys.stderr)

    if not args.no_copy:
        try:
            clipboard.copy(result)
            print('已复制转换后的内容到剪切板', file=sys.stderr)
        except clipboard.ClipboardError as e:
            print(f'警告: 复制到剪切板失败（文件已正常写入）: {e}', file=sys.stderr)


if __name__ == '__main__':
    main()
