import os
import re
import sys
import threading
import configparser
import time
import ctypes
import tkinter as tk
from tkinter import messagebox, simpledialog
from queue import Queue, Empty

# --- 新增 pystray, PIL 相关的导入，并使用 print 进行依赖检查 ---
# icoextract 不再需要
try:
    from pystray import Icon, Menu, MenuItem
    from PIL import Image, ImageDraw, ImageFont # Pillow 用于创建或加载图标
except ImportError:
    print(
        "错误: 缺少必要的库。请安装 'pystray' 和 'Pillow'。\n"
        "请运行 'pip install pystray Pillow' 后再启动程序。",
        file=sys.stderr
    )
    sys.exit(1)


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

def create_default_icon():
    """
    创建一个简单的默认图标 (PIL Image)。
    """
    width, height = 64, 64
    image = Image.new('RGBA', (width, height), (255, 255, 255, 0)) # 透明背景
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 36)
    except IOError:
        font = ImageFont.load_default()

    text = "AP" # AutoApply
    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    
    x = (width - text_width) / 2
    y = (height - text_height) / 2
    
    draw.text((x, y), text, font=font, fill=(0, 0, 0, 255)) # 黑色文本
    return image

# get_system_icon 函数已删除

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
        # _get_or_set_root_folder_path 返回路径，然后赋值给 self.root_folder
        self.root_folder = self._get_or_set_root_folder_path() 
        
        self.clipboard_queue = Queue()
        self.monitor = ClipboardMonitor(self.clipboard_queue)
        self.icon = None # 初始化托盘图标对象

        self._setup_tray_icon() # 设置系统托盘图标，现在 self.root_folder 已经可用

        self.root.after(100, self._check_clipboard_queue)

    def _setup_tray_icon(self):
        """
        设置系统托盘图标及其菜单。
        现在始终使用默认图标。
        """
        icon_image = create_default_icon() # 始终使用默认图标

        menu = (
            MenuItem(f"项目根目录: {self.root_folder}", None, enabled=False), # 显示当前根目录，不可点击
            MenuItem("修改根目录", self._modify_root_folder_action),
            Menu.SEPARATOR,
            MenuItem("退出", self._quit_application)
        )
        
        self.icon = Icon(
            'AutoCodeApplier',
            icon_image,
            hover_text=f"AutoCodeApplier - 根目录: {self.root_folder}",
            menu=menu
        )
        self.icon.title = f"AutoCodeApplier - 根目录: {self.root_folder}"

    def _update_tray_icon_status(self, new_root_folder_path):
        """
        更新托盘图标的标题、提示文本和菜单中的根目录显示。
        """
        if self.icon:
            # 需要重新设置菜单以更新只读项的文本
            menu = (
                MenuItem(f"项目根目录: {new_root_folder_path}", None, enabled=False),
                MenuItem("修改根目录", self._modify_root_folder_action),
                Menu.SEPARATOR,
                MenuItem("退出", self._quit_application)
            )
            self.icon.menu = menu
            self.icon.title = f"AutoCodeApplier - 根目录: {new_root_folder_path}"
            self.icon.tooltip = f"AutoCodeApplier - 根目录: {new_root_folder_path}"

    def _modify_root_folder_action(self):
        """
        托盘菜单中“修改根目录”选项的回调函数。
        """
        # 在 Tkinter 主线程中执行对话框和更新逻辑
        def prompt_and_update():
            # _get_or_set_root_folder_path 会返回新的路径或旧路径（如果用户取消）
            new_path = self._get_or_set_root_folder_path(force_prompt=True)
            if new_path and new_path != self.root_folder: # 只有当路径实际改变时才更新
                self.root_folder = new_path
                self._update_tray_icon_status(self.root_folder)
        
        self.root.after(0, prompt_and_update)


    def _quit_application(self, icon=None, item=None):
        """
        托盘菜单中“退出”选项的回调函数。
        优雅地关闭所有组件。
        """
        print("收到退出指令...")
        if self.monitor:
            self.monitor.stop() # 停止剪贴板监听线程
        if self.icon:
            self.icon.stop() # 停止托盘图标线程
        
        # 确保在主线程中调用 Tkinter 的 quit 方法
        self.root.after(0, self.root.quit)
        print("应用程序已关闭。")

    def _get_or_set_root_folder_path(self, force_prompt=False): # 重命名以强调它返回路径
        """
        获取根目录路径。如果未设置、无效或 force_prompt 为 True 则提示用户输入。
        此方法始终返回一个有效的根目录路径（或在用户拒绝设置时退出程序）。
        """
        current_root_from_config = self.config_manager.get_root_folder()
        
        # 判断是否需要弹窗提示用户设置根目录
        should_prompt = force_prompt or not current_root_from_config or not os.path.isdir(current_root_from_config)

        if not should_prompt:
            # 如果不需要弹窗，直接返回配置中已有的有效路径
            return current_root_from_config

        # 如果需要弹窗
        while True:
            # 为对话框提供初始值，优先使用当前配置的路径，否则使用当前工作目录
            initial_path_for_dialog = current_root_from_config if current_root_from_config else os.getcwd()
            
            new_root_folder_input = simpledialog.askstring(
                "配置根目录",
                "请设置您的项目根目录路径：",
                initialvalue=initial_path_for_dialog
            )
            
            if new_root_folder_input:
                new_root_folder_abs = os.path.abspath(new_root_folder_input)
                if not os.path.isdir(new_root_folder_abs):
                    messagebox.showwarning("路径无效", f"'{new_root_folder_abs}' 不是一个有效的目录。请重新输入。")
                    current_root_from_config = new_root_folder_abs # 更新初始值以便下次循环使用
                else:
                    self.config_manager.set_root_folder(new_root_folder_abs)
                    messagebox.showinfo("根目录已设置", f"项目根目录已成功设置为: {new_root_folder_abs}")
                    return new_root_folder_abs # 返回新的有效路径
            else:
                # 用户取消输入
                if not current_root_from_config: # 如果从未成功设置过根目录，用户取消则退出程序
                    messagebox.showerror("根目录未设置", "未设置项目根目录，程序将退出。")
                    sys.exit(1)
                else: # 如果之前已设置过有效根目录，用户取消则保留旧的设置
                    messagebox.showinfo("取消操作", "未修改项目根目录，将继续使用现有设置。")
                    return current_root_from_config # 返回旧的有效路径

    def _check_clipboard_queue(self):
        """
        定时检查剪贴板队列，处理其中的内容。
        """
        try:
            clipboard_content = self.clipboard_queue.get_nowait()
            self._handle_clipboard_change(clipboard_content)
        except Empty:
            pass # 明确捕获并忽略 queue.Empty 异常
        except Exception as e:
            # 仅打印非 Empty 且非 Tkinter TclError 的异常
            if not isinstance(e, tk.TclError):
                 print(f"[ERROR] Error in _check_clipboard_queue: {type(e).__name__}: {e}", file=sys.stderr)
        finally:
            # 在主线程中调度下一次检查
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
                    print(f"[WARNING] 无法读取文件 '{target_path}' 进行比较: {e}. 将视为新内容。", file=sys.stderr)
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
        
        # 使用 win32_askyesno 而不是 Tkinter 的 messagebox，因为 Tkinter 主循环可能专注于其他任务
        response = win32_askyesno("检测到代码块", prompt_message)

        if response:
            for file_info in files_to_write:
                try:
                    os.makedirs(file_info['target_dir'], exist_ok=True)
                    with open(file_info['target_path'], 'w', encoding='utf-8') as f:
                        f.write(file_info['code_content'])
                    print(f"代码已成功写入到: {file_info['target_path']}")
                except Exception as e:
                    # 使用 Tkinter 的 messagebox，因为根目录已设置，Tkinter 循环已运行
                    messagebox.showerror("写入失败", f"无法将代码写入文件 '{file_info['target_path']}': {e}")
        else:
            print("用户取消了所有写入操作。")


    def run(self):
        """启动应用程序。"""
        print(f"当前项目根目录: {self.root_folder}")
        print("剪贴板监控已启动，请复制包含 `---FILE: <filename>---` 模式的代码。")
        self.monitor.start()

        # 在单独的线程中运行 pystray icon，因为它也有自己的阻塞事件循环
        tray_thread = threading.Thread(target=self.icon.run, daemon=True)
        tray_thread.start()

        try:
            self.root.mainloop() # Tkinter 主循环在主线程运行
        except KeyboardInterrupt:
            print("程序即将退出...")
        finally:
            self.monitor.stop()
            if self.icon:
                self.icon.stop() # 确保在退出时停止托盘图标
            print("应用程序已完全关闭。")

if __name__ == '__main__':
    # win32clipboard, win32gui, pywintypes 的检查保留
    try:
        import win32clipboard
        import win32gui
        import pywintypes
    except ImportError:
        print(
            "错误: 缺少 'pywin32' 库。请运行 'pip install pywin32' 后再启动程序。",
            file=sys.stderr
        )
        sys.exit(1)

    app = AutoCodeApplier()
    app.run()