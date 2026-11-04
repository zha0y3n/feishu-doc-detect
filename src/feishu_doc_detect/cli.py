#!/usr/bin/env python3
"""
整理 Markdown 文件的空行，并把结果复制到剪切板；可选调整标题级别。

整理空行（默认开启，--no-break-lines 关闭）：
  - 单独 1 个空行 → 删除
  - 连续 3 个空行 → 变为 1 个空行
  - 出现其它数量的连续空行 → 报告行号并终止，不复制也不写文件
  - 不检查代码块、front matter、HTML 注释内部

调整标题（指定 level 时）：最高级标题变为 level，其余标题等距平移。
只识别真正的 ATX 标题（行首 0~3 个空格 + 1~6 个 # + 空格或行尾），
会跳过以下内容中的 #：
  - ``` / ~~~ 围栏代码块（含代码里的 # 注释）
  - 4 空格/Tab 缩进的代码块
  - YAML front matter（文件开头的 --- ... ---）
  - HTML 注释 <!-- ... -->
  - 行内的 #（如 #tag、C#、`#include`）
  - 转义的 \\#

用法:
  fsdd input.md                # 整理空行，只复制到剪切板，不写任何文件
  fsdd input.md 2              # 同时把最高级标题调整为 2 级
  fsdd input.md 2 -o out.md    # 另外写到 out.md，原文件不动
  fsdd input.md 2 -o           # 覆盖原文件，并备份原文件
  fsdd input.md --no-break-lines
"""
import argparse
import os
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

    p = argparse.ArgumentParser(prog='feishu-doc-detect',
                                description='整理 Markdown 空行并复制到剪切板，可选调整标题级别')
    p.add_argument('input', help='输入的 Markdown 文件（UTF-8）')
    p.add_argument('level', type=int, nargs='?',
                   help='目标最高标题级别 (1-6)，留空则不修改标题')
    p.add_argument('-o', '--output', nargs='?', const='', metavar='FILE',
                   help='写到文件；FILE 留空则覆盖原文件并生成 .bak 备份（默认只复制到剪切板，不写文件）')
    p.add_argument('--no-break-lines', action='store_true',
                   help='不整理空行（默认：单独 1 个空行删除，连续 3 个空行变为 1 个，'
                        '其它数量报告行号并终止；不检查代码块内部）')
    args = p.parse_intermixed_args()

    if args.level is not None and not 1 <= args.level <= 6:
        p.error('level 必须在 1~6 之间')

    try:
        # utf-8-sig: 兼容 Windows 上带 BOM 的 UTF-8 文件，否则首行标题会识别不出来
        with open(args.input, encoding='utf-8-sig', newline='') as f:
            lines = f.read().splitlines(keepends=True)
    except OSError as e:
        print(f'错误: 无法读取 {args.input}: {e.strerror}', file=sys.stderr)
        sys.exit(1)
    except UnicodeDecodeError:
        print(f'错误: {args.input} 不是 UTF-8 编码，请先转换为 UTF-8', file=sys.stderr)
        sys.exit(1)

    headings, protected = scan(lines)

    runs = []
    if not args.no_break_lines:
        runs = blank_runs(lines, protected)
        bad = [(s, c) for s, c in runs if c not in (1, 3)]
        if bad:
            print(f'错误: 发现 {len(bad)} 处连续空行数量不是 1 或 3，未复制也未写入任何内容：',
                  file=sys.stderr)
            for s, c in bad:
                where = f'第 {s + 1} 行' if c == 1 else f'第 {s + 1}-{s + c} 行'
                print(f'  {where}: 连续 {c} 个空行', file=sys.stderr)
            print('修正后重试，或加 --no-break-lines 跳过空行整理', file=sys.stderr)
            sys.exit(1)

    parts = []
    if args.level is not None:
        offset, clamped = shift_headings(lines, headings, args.level)
        for line_no, old, new in clamped:
            print(f'警告: 第 {line_no} 行 {old} 级标题需变为 {new} 级，超过 6 级上限，已设为 6 级',
                  file=sys.stderr)
        parts.append(f'标题级别偏移 {offset:+d}')

    if not args.no_break_lines:
        lines = squeeze_blank_lines(lines, runs)
        parts.append(f'删除 {sum(1 for _, c in runs if c == 1)} 处单独空行，'
                     f'合并 {sum(1 for _, c in runs if c == 3)} 处三连空行')

    if parts:
        print('完成: ' + '，'.join(parts), file=sys.stderr)

    result = ''.join(lines)

    if args.output is not None:
        out_path = args.output or args.input
        msg = f'已写入 {out_path}'
        # 只有覆盖原文件时才备份
        if os.path.exists(out_path) and os.path.samefile(out_path, args.input):
            bak = args.input + '.bak'
            shutil.copyfile(args.input, bak)
            msg += f'（备份: {bak}）'
        with open(out_path, 'w', encoding='utf-8', newline='') as f:
            f.write(result)
        print(msg, file=sys.stderr)

    try:
        clipboard.copy(result)
        print('已复制到剪切板', file=sys.stderr)
    except clipboard.ClipboardError as e:
        if args.output is None:
            # 剪切板是唯一的输出，失败就等于什么都没得到
            print(f'错误: 复制到剪切板失败: {e}', file=sys.stderr)
            print('可加 -o FILE 把结果写到文件', file=sys.stderr)
            sys.exit(1)
        print(f'警告: 复制到剪切板失败（文件已正常写入）: {e}', file=sys.stderr)


if __name__ == '__main__':
    main()
