"""跨平台复制文本到剪切板，不依赖第三方库。

- Windows: 直接调用 Win32 API（ctypes）
- WSL:     clip.exe（复制到 Windows 剪切板）
- macOS:   pbcopy
- Linux:   wl-copy（Wayland）/ xclip / xsel（X11）
"""
import os
import shutil
import subprocess
import sys


class ClipboardError(Exception):
    pass


def _windows_copy(text):
    import ctypes
    from ctypes import wintypes

    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.restype = wintypes.BOOL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]

    data = (text + '\0').encode('utf-16-le')
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not handle:
        raise ClipboardError('GlobalAlloc 失败')
    ptr = kernel32.GlobalLock(handle)
    if not ptr:
        kernel32.GlobalFree(handle)
        raise ClipboardError('GlobalLock 失败')
    ctypes.memmove(ptr, data, len(data))
    kernel32.GlobalUnlock(handle)

    if not user32.OpenClipboard(None):
        kernel32.GlobalFree(handle)
        raise ClipboardError('无法打开剪切板（可能被其它程序占用）')
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            raise ClipboardError('SetClipboardData 失败')
        # 成功后内存归剪切板所有，不能再释放
    finally:
        user32.CloseClipboard()


def _is_wsl():
    try:
        with open('/proc/version') as f:
            return 'microsoft' in f.read().lower()
    except OSError:
        return False


def _run(cmd, data):
    try:
        subprocess.run(cmd, input=data, check=True, timeout=10,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except (OSError, subprocess.SubprocessError) as e:
        raise ClipboardError(f'{cmd[0]} 执行失败: {e}')


def copy(text):
    """把 text 复制到系统剪切板，失败时抛出 ClipboardError。"""
    if sys.platform == 'win32':
        _windows_copy(text.replace('\r\n', '\n').replace('\n', '\r\n'))
        return

    if sys.platform == 'darwin':
        _run(['pbcopy'], text.encode('utf-8'))
        return

    if _is_wsl() and shutil.which('clip.exe'):
        # clip.exe 能识别 UTF-16LE（不要加 BOM，否则 BOM 会作为字符留在剪切板里）
        win_text = text.replace('\r\n', '\n').replace('\n', '\r\n')
        _run(['clip.exe'], win_text.encode('utf-16-le'))
        return

    candidates = []
    if os.environ.get('WAYLAND_DISPLAY'):
        candidates.append(['wl-copy'])
    if os.environ.get('DISPLAY'):
        candidates += [['xclip', '-selection', 'clipboard'],
                       ['xsel', '--clipboard', '--input']]
    for cmd in candidates:
        if shutil.which(cmd[0]):
            _run(cmd, text.encode('utf-8'))
            return
    raise ClipboardError('未找到可用的剪切板工具，请安装 wl-clipboard、xclip 或 xsel')
