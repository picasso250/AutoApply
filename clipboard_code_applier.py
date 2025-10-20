import os
import re
import sys
import threading
# import json # 用户指示不删除此导入，即使 ConfigManager 已移出。
import time
import ctypes
import tkinter as tk
from tkinter import messagebox, simpledialog
from queue import Queue, Empty # Queue, Empty 仍然需要

# --- pystray 相关的导入 ---
try:
    from pystray import Icon, Menu, MenuItem
except ImportError:
    print(
        "错误: 缺少必要的库。请安装 'pystray'。\n"
        "请运行 'pip install pystray' 后再启动程序。",
        file=sys.stderr
    )
    sys.exit(1)


import win32clipboard # 仍需用于 pywin32 依赖检查
import win32con # 仍需用于 pywin32 依赖检查
import win32gui # 仍需用于 pywin32 依赖检查
import pywintypes # 仍需用于 pywin32 依赖检查

# --- 从本地模块导入 ---
from config_manager import ConfigManager
from clipboard_monitor import ClipboardMonitor
from icon_creator import create_default_icon # 从新文件中导入图标创建函数


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

# create_default_icon 函数已移动到 icon_creator.py 文件中。

# ConfigManager 类已移动到 config_manager.py 文件中。
# ClipboardMonitor 类已移动到 clipboard_monitor.py 文件中。


class AutoCodeApplier:
    """
    主应用程序逻辑，处理剪贴板内容，模式匹配，用户交互和文件写入。
    """
    # --- 正则表达式优化 ---
    # 优化点：
    # 1. 在指令行 `(...)` 和代码块起始符 ` ``` ` 之间使用 `\s*` 匹配任意空白字符（包括零个或多个空格、换行符）。
    # 2. 这使得 `#### file: ...(...)``` ` (在同一行) 和 `#### file: ...(...)\n``` ` (换行) 两种格式都能被正确匹配。
    CLIPBOARD_PATTERN = re.compile(
        # 匹配元数据标题行：#### file: <path/filename.ext> (OVERWRITE|APPEND|DELETE|CREATE|覆盖|追加|删除|创建|修改)
        r"^####\s*file:\s*(?P<filename>.*?)\s*\((?P<operation>[^)]+)\)\s*"
        r"```(?P<language>\w*)?\s*$" # 匹配代码块起始：```<language>
        r"\n(?P<content>.*?)"              # 懒惰匹配实际代码内容
        r"^\s*```\s*$",                    # 匹配代码块结束：```
        re.MULTILINE | re.DOTALL | re.IGNORECASE
    )

    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw() # 隐藏主窗口
        
        # 始终使用固定的 config.json 文件路径
        current_script_dir = os.path.dirname(os.path.abspath(__file__))
        config_file_path = os.path.join(current_script_dir, 'config.json') # 更改为 config.json
        self.config_manager = ConfigManager(config_file=config_file_path)
        
        # 初始获取根目录。如果 config.json 中没有，会提示用户设置。
        self.root_folder = self._get_or_set_root_folder_path()
        self._last_loaded_root_folder = self.root_folder # 用于检测 config.json 中的变化
        
        self.clipboard_queue = Queue()
        self.monitor = ClipboardMonitor(self.clipboard_queue)
        self.icon = None # 初始化托盘图标对象

        self._setup_tray_icon() # 设置系统托盘图标，现在 self.root_folder 已经可用

        # 调度定时任务
        self.root.after(100, self._check_clipboard_queue)
        self.root.after(1000, self._schedule_root_folder_check) # 每秒检查一次根目录配置

    def _setup_tray_icon(self):
        """
        设置系统托盘图标及其菜单。
        """
        icon_image = create_default_icon() # 从导入的模块调用函数

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
                self._last_loaded_root_folder = self.root_folder # 更新最后加载的根目录
        
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
        # 如果 config.json 中的路径无效，或者强制提示，则需要弹窗
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
                "请设置您的项目根目录路径：\n\n您也可以在VS Code扩展'LLM Code Copier'中配置'AutoApplyConfigFile'，使其自动同步。",
                initialvalue=initial_path_for_dialog
            )
            
            if new_root_folder_input:
                new_root_folder_abs = os.path.abspath(new_root_folder_input)
                if not os.path.isdir(new_root_folder_abs):
                    messagebox.showwarning("路径无效", f"'{new_root_folder_abs}' 不是一个有效的目录。请重新输入。")
                    current_root_from_config = new_root_folder_abs # 更新初始值以便下次循环使用
                else:
                    self.config_manager.set_root_folder(new_root_folder_abs)
                    # 移除成功设置时的弹窗
                    # messagebox.showinfo("根目录已设置", f"项目根目录已成功设置为: {new_root_folder_abs}") 
                    return new_root_folder_abs # 返回新的有效路径
            else:
                # 用户取消输入
                if not current_root_from_config: # 如果从未成功设置过根目录，用户取消则退出程序
                    messagebox.showerror("根目录未设置", "未设置项目根目录，程序将退出。")
                    sys.exit(1)
                else: # 如果之前已设置过有效根目录，用户取消则保留旧的设置
                    # 移除取消操作时的弹窗
                    # messagebox.showinfo("取消操作", "未修改项目根目录，将继续使用现有设置。")
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

    def _schedule_root_folder_check(self):
        """
        调度周期性检查根目录配置的任务。
        """
        self._check_and_update_root_folder_from_config()
        self.root.after(1000, self._schedule_root_folder_check) # 每秒再次调度自己

    def _check_and_update_root_folder_from_config(self):
        """
        重新加载 config.json，并检查 root_folder 是否发生变化。
        如果发生变化，则更新当前根目录并刷新托盘图标。
        """
        try:
            self.config_manager._load_config() # 重新从文件加载配置
            new_root_folder = self.config_manager.get_root_folder()
            
            if new_root_folder and os.path.isdir(new_root_folder) and new_root_folder != self._last_loaded_root_folder:
                # 只有当新路径有效且与上次加载的不同时才更新
                self.root_folder = new_root_folder
                self._last_loaded_root_folder = new_root_folder
                self._update_tray_icon_status(self.root_folder)
                print(f"[INFO] 项目根目录已自动更新为: {self.root_folder}")
            elif not new_root_folder or not os.path.isdir(new_root_folder):
                # 如果 config.json 中的路径无效或为空，并且当前程序持有的 root_folder 也无效，
                # 则可以考虑弹窗提示用户，但为了不打扰用户，这里只打印警告。
                # 如果之前有效，现在无效，则保持旧的有效路径不变。
                if self.root_folder and not os.path.isdir(self.root_folder):
                     print(f"[WARNING] config.json 中的根目录 '{new_root_folder}' 无效，或当前 '{self.root_folder}' 已失效。请手动修改或通过VS Code扩展重新设置。", file=sys.stderr)
                     # 此时可以选择让用户重新设置，但为了避免频繁弹窗，目前只警告
                elif not self.root_folder and new_root_folder and os.path.isdir(new_root_folder):
                    # config.json 之前为空或无效，现在有有效值了
                    self.root_folder = new_root_folder
                    self._last_loaded_root_folder = new_root_folder
                    self._update_tray_icon_status(self.root_folder)
                    print(f"[INFO] 项目根目录已从空值自动更新为: {self.root_folder}")

        except Exception as e:
            print(f"[ERROR] 检查并更新根目录时发生错误: {type(e).__name__}: {e}", file=sys.stderr)


    def _handle_clipboard_change(self, clipboard_content):
        """
        处理剪贴板内容变化的逻辑，现在支持一次性确认多个文件块的写入，
        并在写入前检查内容是否与现有文件一致，并增加了追加、删除和创建操作。
        """
        if not clipboard_content:
            return

        matches = list(self.CLIPBOARD_PATTERN.finditer(clipboard_content))

        if not matches:
            return

        files_to_write = []
        files_to_delete = []
        prompt_details = []

        for match in matches:
            filename = match.group('filename').strip()
            operation_raw = match.group('operation').strip() # 获取原始操作指令
            
            # --- 指令标准化 ---
            # 将中文或英文指令统一映射为大写的英文指令，以便后续逻辑处理
            # re.IGNORECASE 标志确保了 'overwrite', 'OVERWRITE' 等都会被正确处理
            operation_type = ""
            if operation_raw.lower() in ['create', '创建']:
                operation_type = "CREATE"
            elif operation_raw.lower() in ['overwrite', '覆盖', '修改']: # 增加“修改”
                operation_type = "OVERWRITE"
            elif operation_raw.lower() in ['append', '追加']:
                operation_type = "APPEND"
            elif operation_raw.lower() in ['delete', '删除']:
                operation_type = "DELETE"
            else:
                # 如果匹配到未知指令（理论上不会，因为正则表达式限制了），则跳过
                print(f"[WARNING] 检测到文件 '{filename}' 的未知操作类型 '{operation_raw}'，跳过此代码块。", file=sys.stderr)
                continue

            code_content_raw = match.group('content').strip()
            # 标准化剪贴板内容的换行符
            code_content_normalized = code_content_raw.replace('\r\n', '\n').replace('\r', '\n')
            
            target_path = os.path.join(self.root_folder, filename)
            target_dir = os.path.dirname(target_path)

            # --- 处理 DELETE 操作 ---
            if operation_type == "DELETE":
                if os.path.exists(target_path):
                    files_to_delete.append(target_path)
                    prompt_details.append(f"- '{filename}' (删除, 路径: '{target_path}')")
                else:
                    print(f"[INFO] 文件 '{filename}' 不存在，跳过删除操作。")
                    prompt_details.append(f"- '{filename}' (删除 - 文件不存在，已跳过)")
                continue # 完成此匹配项的处理，进入下一个匹配

            # --- 处理 CREATE 操作 ---
            elif operation_type == "CREATE":
                existing_content = ""
                file_exists = os.path.exists(target_path) and os.path.isfile(target_path)

                if file_exists:
                    try:
                        with open(target_path, 'r', encoding='utf-8') as f:
                            existing_content = f.read().replace('\r\n', '\n').replace('\r', '\n')
                    except Exception as e:
                        print(f"[WARNING] 无法读取文件 '{target_path}' 进行比较 (CREATE 操作): {e}. 将视为新内容或空内容。", file=sys.stderr)
                        existing_content = ""
                    
                    if code_content_normalized == existing_content.strip():
                        print(f"文件 '{filename}' (CREATE) 内容与现有文件一致，跳过写入。")
                        continue # 如果文件存在且内容一致，跳过
                    else:
                        # 文件存在但内容不同，CREATE 操作应询问是否覆盖
                        confirmation = win32_askyesno(
                            "文件已存在警告", 
                            f"您尝试创建一个文件 '{filename}'，但该文件已存在且内容不同。\n"
                            f"路径: '{target_path}'\n"
                            f"是否要覆盖现有文件？\n"
                            f"（取消将跳过此文件）"
                        )
                        if not confirmation:
                            print(f"用户取消了 '{filename}' (CREATE) 操作，文件已存在且内容不同。")
                            continue # 用户选择不覆盖，跳过此文件
                        
                        # 如果用户确认覆盖，则视为覆盖操作
                        status = "覆盖 (CREATE 请求)"
                        operation_for_log = "OVERWRITE_ON_CREATE"
                else:
                    status = "创建"
                    operation_for_log = "CREATE"

                files_to_write.append({
                    'filename': filename,
                    'code_content': code_content_normalized,
                    'target_path': target_path,
                    'target_dir': target_dir,
                    'operation': operation_for_log # 存储实际执行的操作类型
                })
                prompt_details.append(f"- '{filename}' ({status}, 将写入到: '{target_path}')")
                continue # 完成此匹配项的处理，进入下一个匹配


            # --- 处理 OVERWRITE 和 APPEND 操作 ---
            elif operation_type in ["OVERWRITE", "APPEND"]:
                existing_content = ""
                file_exists = os.path.exists(target_path) and os.path.isfile(target_path)

                if file_exists:
                    try:
                        with open(target_path, 'r', encoding='utf-8') as f:
                            existing_content = f.read().replace('\r\n', '\n').replace('\r', '\n')
                    except Exception as e:
                        print(f"[WARNING] 无法读取文件 '{target_path}' 进行比较/追加: {e}. 将视为新内容或空内容。", file=sys.stderr)
                        existing_content = "" # 无法读取，视为文件不存在或内容为空
                
                content_to_write = code_content_normalized
                status = ""

                if operation_type == "OVERWRITE":
                    # 在比较前，对现有文件内容和剪贴板内容都执行 strip()
                    if file_exists and code_content_normalized == existing_content.strip():
                        print(f"文件 '{filename}' (OVERWRITE) 内容与现有文件一致，跳过写入。")
                        continue # 内容一致，跳过此文件
                    status = "更新" if file_exists else "创建"

                elif operation_type == "APPEND":
                    # 如果文件存在，新内容是现有内容加上要追加的内容
                    if file_exists:
                        # 确保追加的内容前有换行符，除非现有文件为空
                        content_to_write = existing_content + ("\n" if existing_content and not existing_content.endswith('\n') else "") + code_content_normalized
                        # 检查追加后内容是否与现有内容相同（如果追加的是空内容，或者现有文件已经包含该内容）
                        if content_to_write.strip() == existing_content.strip():
                            print(f"文件 '{filename}' (APPEND) 内容追加后与现有文件一致，跳过写入。")
                            continue
                    else: # 文件不存在，APPEND 行为等同于 OVERWRITE (创建)
                        status = "创建并写入"
                    status = "追加" if file_exists else "创建并写入"
                
                files_to_write.append({
                    'filename': filename,
                    'code_content': content_to_write,
                    'target_path': target_path,
                    'target_dir': target_dir,
                    'operation': operation_type # 用于提示和日志
                })
                prompt_details.append(f"- '{filename}' ({status}, 将{operation_type.lower()}到: '{target_path}')")
            
            else:
                # 此处的 else 理论上不会被触发，因为前面已经做了指令标准化和检查
                print(f"[WARNING] 检测到文件 '{filename}' 的未知操作类型 '{operation_type}'，跳过此代码块。", file=sys.stderr)
                continue


        # 如果没有文件需要写入或删除，则不弹出提示框
        if not files_to_write and not files_to_delete:
            print("剪贴板中检测到的所有代码块内容均与现有文件一致，或操作被跳过，无需处理。")
            return

        # 构建提示消息
        prompt_message_parts = [
            f"在剪贴板中检测到 {len(files_to_write) + len(files_to_delete)} 个操作请求。\n"
            f"是否执行这些操作到您的项目根目录 '{self.root_folder}' 下？\n"
        ]
        if prompt_details:
            prompt_message_parts.append(f"\n以下操作将被执行：\n{' \n'.join(prompt_details)}\n")
        
        prompt_message_parts.append("\n注意：")
        if any(f['operation'] == "CREATE" for f in files_to_write):
            prompt_message_parts.append(" - 'CREATE' 操作将创建新文件。")
        if any(f['operation'] == "OVERWRITE" for f in files_to_write) or any(f['operation'] == "OVERWRITE_ON_CREATE" for f in files_to_write):
            prompt_message_parts.append(" - 'OVERWRITE' 或因 'CREATE' 请求导致的覆盖操作将覆盖现有文件内容。")
        if any(f['operation'] == "APPEND" for f in files_to_write):
            prompt_message_parts.append(" - 'APPEND' 操作将追加内容到现有文件末尾。")
        if files_to_delete:
            prompt_message_parts.append(" - 'DELETE' 操作将删除指定文件。")
        
        prompt_message = "".join(prompt_message_parts)
        
        # 使用 win32_askyesno 而不是 Tkinter 的 messagebox
        response = win32_askyesno("检测到文件操作请求", prompt_message)

        if response:
            # 执行写入/追加操作
            for file_info in files_to_write:
                try:
                    os.makedirs(file_info['target_dir'], exist_ok=True)
                    with open(file_info['target_path'], 'w', encoding='utf-8') as f:
                        f.write(file_info['code_content'])
                    # 根据实际操作类型打印日志
                    log_operation_type = file_info['operation'].replace("OVERWRITE_ON_CREATE", "CREATE (已覆盖)").lower()
                    print(f"文件 '{file_info['target_path']}' 已成功 {log_operation_type}。")
                except Exception as e:
                    messagebox.showerror(f"{file_info['operation']}失败", f"无法 {file_info['operation'].lower()} 文件 '{file_info['target_path']}': {e}")
            
            # 执行删除操作
            for file_path in files_to_delete:
                try:
                    if os.path.exists(file_path): # 再次检查文件是否存在，以防并发操作
                        os.remove(file_path)
                        print(f"文件 '{file_path}' 已成功删除。")
                    else:
                        print(f"尝试删除的文件 '{file_path}' 不存在，已跳过。")
                except Exception as e:
                    messagebox.showerror("删除失败", f"无法删除文件 '{file_path}': {e}")
        else:
            print("用户取消了所有操作。")


    def run(self):
        """启动应用程序。"""
        print(f"当前项目根目录: {self.root_folder}")
        print("剪贴板监控已启动，请复制包含 Markdown 格式的指令。")
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