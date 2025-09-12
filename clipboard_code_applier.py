import os
import re
import sys
import threading
import configparser
import time
import ctypes
import tkinter as tk
from tkinter import messagebox, simpledialog
from queue import Queue, Empty # 导入 Queue 和 Empty 异常

import win32clipboard
import win32con
import win32gui
import pywintypes

# MessageBoxW Constants
MB_YESNO = 0x00000004
MB_ICONQUESTION = 0x00000020
MB_FOREGROUND = 0x00010000 # Places the message box in the foreground
IDYES = 6
IDNO = 7

def win32_askyesno(title, message):
    """
    使用 Windows 原生 MessageBoxW 显示一个“是/否”确认框。
    """
    result = ctypes.windll.user32.MessageBoxW(
        0, # hWnd
        message, # lpText
        title, # lpCaption
        MB_YESNO | MB_ICONQUESTION | MB_FOREGROUND # uType
    )
    return result == IDYES


class ConfigManager:
    """
    管理配置文件 (config.ini) 的读取和写入。
    用于存储根目录等配置信息。
    """
    def __init__(self, config_file='config.ini'):
        self.config_file = config_file
        self.config = configparser.ConfigParser()
        self._load_config()

    def _load_config(self):
        """加载配置文件，如果不存在则创建。"""
        if os.path.exists(self.config_file):
            self.config.read(self.config_file, encoding='utf-8')
        else:
            self._create_default_config()

    def _create_default_config(self):
        """创建默认配置文件。"""
        self.config['Settings'] = {'root_folder': ''}
        self._save_config()

    def _save_config(self):
        """保存配置文件。"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                self.config.write(f)
        except IOError as e:
            messagebox.showerror("配置错误", f"无法保存配置文件 '{self.config_file}': {e}")

    def get_root_folder(self):
        """获取配置的根目录。"""
        return self.config.get('Settings', 'root_folder', fallback='').strip()

    def set_root_folder(self, path):
        """设置根目录并保存。"""
        self.config['Settings']['root_folder'] = path
        self._save_config()

class ClipboardMonitor:
    """
    使用 Win32 API 监听剪贴板变化的类。
    当剪贴板内容变化时，将内容放入队列。
    """
    WM_CLIPBOARDUPDATE = 0x031D

    def __init__(self, clipboard_queue):
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
            0,
            class_atom,
            "ClipboardMonitor",
            0,
            0, 0, 0, 0,
            0,
            0,
            wc.hInstance,
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
            print(f"[ERROR] pywintypes.error when accessing clipboard: {e}")
        except Exception as e:
            print(f"[ERROR] General error accessing clipboard: {e}")
        finally:
            if opened:
                try:
                    win32clipboard.CloseClipboard()
                except Exception as e:
                    print(f"[ERROR] Error closing clipboard in finally: {e}")


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


class AutoCodeApplier:
    """
    主应用程序逻辑，处理剪贴板内容，模式匹配，用户交互和文件写入。
    """
    CLIPBOARD_PATTERN = re.compile(
        r"---FILE:\s*(?P<filename>[^ \n]+?)---\s*\n"
        r"```(?P<language>\w*)?\s*\n"
        r"(?P<content>.*?)\n"
        r"```",
        re.DOTALL
    )

    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw() # 隐藏主窗口
        
        self.config_manager = ConfigManager()
        self.root_folder = self._get_or_set_root_folder()
        
        self.clipboard_queue = Queue()
        self.monitor = ClipboardMonitor(self.clipboard_queue)

        self.root.after(100, self._check_clipboard_queue)

    def _get_or_set_root_folder(self):
        """
        获取根目录，如果未设置则提示用户输入。
        """
        root_folder = self.config_manager.get_root_folder()
        while not root_folder or not os.path.isdir(root_folder):
            root_folder = simpledialog.askstring(
                "配置根目录",
                "请设置您的项目根目录路径：",
                initialvalue=root_folder if root_folder else os.getcwd()
            )
            if root_folder:
                root_folder = os.path.abspath(root_folder)
                if not os.path.isdir(root_folder):
                    messagebox.showwarning("路径无效", f"'{root_folder}' 不是一个有效的目录。请重新输入。")
                    root_folder = None
                else:
                    self.config_manager.set_root_folder(root_folder)
            else:
                messagebox.showerror("根目录未设置", "未设置项目根目录，程序将退出。")
                sys.exit(1)
        return root_folder

    def _check_clipboard_queue(self):
        """
        定时检查剪贴板队列，处理其中的内容。
        """
        try:
            clipboard_content = self.clipboard_queue.get_nowait()
            self._handle_clipboard_change(clipboard_content)
        except Empty: # 明确捕获并忽略 queue.Empty 异常
            pass
        except Exception as e:
            # 仅打印非 Empty 且非 Tkinter TclError 的异常
            if not isinstance(e, tk.TclError):
                 print(f"[ERROR] Error in _check_clipboard_queue: {type(e).__name__}: {e}")
        finally:
            self.root.after(100, self._check_clipboard_queue)

    def _handle_clipboard_change(self, clipboard_content):
        """
        处理剪贴板内容变化的逻辑，现在支持一次性确认多个文件块的写入，
        并在写入前检查内容是否与现有文件一致。
        """
        if not clipboard_content:
            return

        matches = list(self.CLIPBOARD_PATTERN.finditer(clipboard_content))

        if not matches:
            return

        files_to_write = []
        prompt_details = []

        for match in matches:
            filename = match.group('filename')
            code_content = match.group('content').strip()
            # 标准化剪贴板内容的换行符
            code_content = code_content.replace('\r\n', '\n').replace('\r', '\n')
            
            target_path = os.path.join(self.root_folder, filename)
            target_dir = os.path.dirname(target_path)

            existing_content = None
            if os.path.exists(target_path) and os.path.isfile(target_path):
                try:
                    with open(target_path, 'r', encoding='utf-8') as f:
                        existing_content = f.read()
                    # 标准化现有文件内容的换行符
                    existing_content = existing_content.replace('\r\n', '\n').replace('\r', '\n')
                except Exception as e:
                    print(f"[WARNING] 无法读取文件 '{target_path}' 进行比较: {e}. 将视为新内容。")
                    existing_content = None # 无法读取则视为不一致，强制写入
            
            if code_content == existing_content:
                print(f"文件 '{filename}' 内容与现有文件一致，跳过写入。")
                continue # 内容一致，跳过此文件
            
            files_to_write.append({
                'filename': filename,
                'code_content': code_content,
                'target_path': target_path,
                'target_dir': target_dir
            })
            # 如果是新文件或内容不一致，才加入提示列表
            status = "更新" if existing_content is not None else "创建"
            prompt_details.append(f"- '{filename}' ({status}, 将写入到: '{target_path}')")
        
        # 如果没有文件需要写入，则不弹出提示框
        if not files_to_write:
            print("剪贴板中检测到的所有代码块内容均与现有文件一致，无需写入。")
            return

        prompt_message = (
            f"在剪贴板中检测到 {len(files_to_write)} 个代码块，其中部分内容与现有文件不一致或为新文件。\n"
            f"是否将它们写入到您的项目根目录 '{self.root_folder}' 下？\n\n"
            f"以下文件将被处理：\n"
            f"{' \n'.join(prompt_details)}\n\n"
            f"注意：这将覆盖现有文件内容（如果文件已存在）。"
        )
        
        response = win32_askyesno("检测到代码块", prompt_message)

        if response:
            for file_info in files_to_write:
                try:
                    os.makedirs(file_info['target_dir'], exist_ok=True)
                    with open(file_info['target_path'], 'w', encoding='utf-8') as f:
                        f.write(file_info['code_content'])
                    print(f"代码已成功写入到: {file_info['target_path']}")
                except Exception as e:
                    messagebox.showerror("写入失败", f"无法将代码写入文件 '{file_info['target_path']}': {e}")
        else:
            print("用户取消了所有写入操作。")


    def run(self):
        """启动应用程序。"""
        print(f"当前项目根目录: {self.root_folder}")
        print("剪贴板监控已启动，请复制包含 `---FILE: <filename>---` 模式的代码。")
        self.monitor.start()
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            print("程序即将退出...")
        finally:
            self.monitor.stop()

if __name__ == '__main__':
    try:
        import win32clipboard
        import win32gui
        import pywintypes
    except ImportError:
        messagebox.showerror(
            "缺少依赖",
            "需要安装 'pywin32' 库。请运行 'pip install pywin32' 后再启动程序。"
        )
        sys.exit(1)

    app = AutoCodeApplier()
    app.run()