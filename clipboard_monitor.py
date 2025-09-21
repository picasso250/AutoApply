import threading
import time
import sys
import ctypes
import win32clipboard
import win32con
import win32gui
import pywintypes
from queue import Queue # 虽然 ClipboardMonitor 接收 Queue 实例，但它内部不需要直接导入 Queue 类，不过为了模块的独立性，如果将来它需要创建或操作队列，保留在这里是合理的。

class ClipboardMonitor:
    """
    使用 Win32 API 监听剪贴板变化的类。
    当剪贴板内容变化时，将内容放入队列。
    """
    WM_CLIPBOARDUPDATE = 0x031D

    def __init__(self, clipboard_queue: Queue):
        self.clipboard_queue = clipboard_queue
        self.hwnd = None
        self.last_clipboard_data = None
        self._stop_event = threading.Event()

    def _create_window(self):
        """创建一个隐藏窗口用于接收 Windows 消息。"""
        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = self._wnd_proc
        wc.lpszClassName = "ClipboardMonitorClass"
        wc.hInstance = win32gui.GetModuleHandle(None)
        class_atom = win32gui.RegisterClass(wc)
        
        self.hwnd = win32gui.CreateWindowEx(
            0, # dwExStyle
            class_atom, # lpClassName
            "ClipboardMonitor", # lpWindowName
            0, # dwStyle (WS_POPUP is often 0, suitable for a message-only window)
            0, 0, 0, 0, # x, y, nWidth, nHeight
            win32con.HWND_MESSAGE, # hWndParent - **修正: 使用 HWND_MESSAGE 创建消息窗口**
            0, # hMenu
            wc.hInstance, # hInstance
            None
        )
        win32gui.UpdateWindow(self.hwnd)

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        """窗口过程函数，处理 Windows 消息。"""
        if msg == self.WM_CLIPBOARDUPDATE:
            self._on_clipboard_update()
        elif msg == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _on_clipboard_update(self):
        """剪贴板内容更新时的回调。"""
        clipboard_data = None
        opened = False
        try:
            win32clipboard.OpenClipboard(self.hwnd) 
            opened = True
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                clipboard_data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                if clipboard_data:
                    self.clipboard_queue.put(clipboard_data)
                self.last_clipboard_data = clipboard_data
        except pywintypes.error as e:
            print(f"[ERROR] pywintypes.error when accessing clipboard: {e}", file=sys.stderr)
        except Exception as e:
            print(f"[ERROR] General error accessing clipboard: {e}", file=sys.stderr)
        finally:
            if opened:
                try:
                    win32clipboard.CloseClipboard()
                except Exception as e:
                    print(f"[ERROR] Error closing clipboard in finally: {e}", file=sys.stderr)

    def start(self):
        """启动剪贴板监听线程。"""
        monitor_thread = threading.Thread(target=self._run_monitor)
        monitor_thread.daemon = True
        monitor_thread.start()

    def _run_monitor(self):
        """在独立线程中运行消息循环。"""
        self._create_window()
        ctypes.windll.user32.AddClipboardFormatListener(self.hwnd)
        while not self._stop_event.is_set():
            win32gui.PumpWaitingMessages()
            time.sleep(0.01)

        ctypes.windll.user32.RemoveClipboardFormatListener(self.hwnd)
        win32gui.DestroyWindow(self.hwnd)
        win32gui.UnregisterClass("ClipboardMonitorClass", win32gui.GetModuleHandle(None))

    def stop(self):
        """停止剪贴板监听。"""
        self._stop_event.set()
        if self.hwnd:
            win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)