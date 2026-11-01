# feishu-doc-detect

把 Markdown 标题的最高级别调整为指定数字，其余标题等距平移。
例：原文有 1/2/3/4 级标题，指定 2 → 变为 2/3/4/5 级。

代码块（``` / ~~~ / 缩进）、YAML front matter、HTML 注释、行内 `#` 都不会被改动。

## 安装

```bash
uv tool install .
```

## 用法

```bash
fsdd input.md 2              # 直接修改原文件，并生成 input.md.bak 备份
fsdd input.md 2 -o out.md    # 写到新文件，原文件不动
fsdd input.md 2 -b           # 同时整理空行
fsdd input.md 2 --no-copy    # 不复制到剪切板
```

`fsdd` 是 `feishu-doc-detect` 的简写，两者等价。

## 整理空行（-b）

加上 `-b` / `--blank-lines` 后，在调整标题的同时整理空行：

- 单独 1 个空行 → 删除
- 连续 3 个空行 → 变为 1 个空行
- 出现其它数量（2 个、4 个及以上）→ 列出所有出问题的行号并终止，不修改任何文件

代码块、YAML front matter、HTML 注释内部的空行不检查也不修改。只含空格/Tab 的行也算空行。

## 复制到剪切板

转换成功后，转换后的完整内容会自动复制到剪切板，可直接粘贴。加 `--no-copy` 可关闭。
复制失败只会给出警告，不影响文件写入。

- Windows：直接调用系统接口，无需额外安装
- macOS：pbcopy（系统自带）
- WSL：clip.exe（复制到 Windows 剪切板）
- Linux：需安装 `wl-clipboard`（Wayland）或 `xclip` / `xsel`（X11）
