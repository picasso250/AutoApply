import tkinter as tk
from tkinter import ttk, messagebox
import os
import sys
from PIL import Image, ImageTk

# 尝试导入 icoextract 库
try:
    import icoextract
except ImportError:
    messagebox.showerror(
        "缺少依赖",
        "请安装 'icoextract' 和 'Pillow' 库: pip install icoextract Pillow"
    )
    sys.exit(1)

# --- 辅助函数：创建可滚动框架 (保持不变) ---
def create_scrollable_frame(parent):
    canvas = tk.Canvas(parent)
    scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
    scrollable_frame = ttk.Frame(canvas)

    scrollable_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")
        )
    )

    canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)

    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    return scrollable_frame

# --- 主应用程序类 ---
class IconViewerApp:
    def __init__(self, master):
        self.master = master
        master.title("Windows 系统图标查看器")

        # 定义需要加载的系统文件列表
        self.available_files = [
            "shell32.dll",
            "imageres.dll",
            "pifmgr.dll",
            "moricons.dll",
            "compstui.dll",
            "explorer.exe",
            "ddores.dll",
            "setupapi.dll",
            "pnidui.dll",
            "mstscax.dll",
            # 您可以在此处添加更多您想查看的文件
        ]

        # 用于存储 PhotoImage 引用，防止被垃圾回收
        self.displayed_icons_references = [] 

        self.setup_ui()

    def setup_ui(self):
        # --- 控制面板框架 ---
        control_frame = ttk.Frame(self.master, padding="10")
        control_frame.pack(side="top", fill="x")

        ttk.Label(control_frame, text="选择文件:").pack(side="left", padx=5)

        self.file_selection_var = tk.StringVar(self.master)
        # 尝试选择第一个可用文件作为默认值
        if self.available_files:
            self.file_selection_var.set(self.available_files[0]) 

        self.file_combobox = ttk.Combobox(
            control_frame,
            textvariable=self.file_selection_var,
            values=self.available_files,
            state="readonly" # 设置为只读，用户只能从列表中选择
        )
        self.file_combobox.pack(side="left", padx=5, expand=True, fill="x")
        self.file_combobox.bind("<<ComboboxSelected>>", self.on_selection_change) # 绑定选择事件

        load_button = ttk.Button(control_frame, text="加载图标", command=self.on_load_icons)
        load_button.pack(side="left", padx=5)

        # --- 显示文件路径的 Label ---
        self.path_label = ttk.Label(self.master, text="当前文件: 未选择文件", anchor="w", wraplength=500)
        self.path_label.pack(side="top", fill="x", padx=10, pady=5)

        # --- 可滚动区域用于显示图标 ---
        self.icon_scroll_frame = create_scrollable_frame(self.master)
        self.icon_scroll_frame.pack(side="top", fill="both", expand=True)

        # 初始加载第一个文件的图标
        if self.available_files:
            self.on_load_icons()
        else:
            ttk.Label(self.icon_scroll_frame, text="没有可供加载的文件。").grid(row=0, column=0, padx=10, pady=10)
            self.path_label.config(text="当前文件: 没有可供加载的文件。")


    def get_file_path(self, filename):
        """
        尝试获取指定文件（可能是 .dll 或 .exe）的路径。
        优先查找 .mun 文件，然后是 System32，最后是 SystemRoot。
        """
        system_root = os.environ.get("SystemRoot", "C:\\Windows")
        
        # 1. 检查 .mun 文件 (主要针对 DLLs 在 Win10+)
        if filename.endswith(".dll"):
            mun_filename = filename + ".mun"
            mun_path = os.path.join(system_root, "SystemResources", mun_filename)
            if os.path.exists(mun_path):
                return mun_path

        # 2. 检查 System32 目录
        system32_path = os.path.join(system_root, "System32", filename)
        if os.path.exists(system32_path):
            return system32_path
            
        # 3. 检查 SystemRoot 目录 (例如 explorer.exe)
        system_root_path = os.path.join(system_root, filename)
        if os.path.exists(system_root_path):
            return system_root_path

        return None

    def on_selection_change(self, event=None):
        """
        当下拉菜单选择改变时触发，自动加载图标。
        """
        self.on_load_icons()

    def on_load_icons(self):
        """
        根据下拉菜单中选择的文件加载并显示图标。
        """
        selected_filename = self.file_selection_var.get()
        full_path = self.get_file_path(selected_filename)
        
        # 清除之前显示的图标
        for widget in self.icon_scroll_frame.winfo_children():
            widget.destroy()
        self.displayed_icons_references.clear() # 清除旧的 PhotoImage 引用

        if not full_path:
            messagebox.showerror("文件未找到", f"无法找到文件: {selected_filename}")
            self.path_label.config(text=f"当前文件: {selected_filename} (未找到)")
            ttk.Label(self.icon_scroll_frame, text="未找到指定文件或无法加载。").grid(row=0, column=0, padx=10, pady=10)
            return

        # 更新路径显示 Label
        self.path_label.config(text=f"当前文件: {full_path}")
        
        # 调用图标加载和显示逻辑
        self._load_and_display_icons_from_path(full_path, self.icon_scroll_frame, self.displayed_icons_references)

    def _load_and_display_icons_from_path(self, file_path, icon_display_frame, displayed_icons_list):
        """
        从指定文件路径提取并显示图标。
        """
        extractor = None
        try:
            extractor = icoextract.IconExtractor(file_path)
        except Exception as e:
            messagebox.showerror("图标提取错误", f"初始化图标提取器时发生错误: {e}\n文件: {os.path.basename(file_path)}")
            ttk.Label(icon_display_frame, text=f"无法从 {os.path.basename(file_path)} 提取图标。").grid(row=0, column=0, padx=10, pady=10)
            return

        icons_per_row = 10
        current_row = 0
        current_col = 0
        max_icons_to_try = 500 # 限制尝试的图标数量，以防文件过大或无限循环
        found_any_icon = False

        for idx in range(max_icons_to_try):
            try:
                icon_data_stream = extractor.get_icon(idx) 
                pil_image = Image.open(icon_data_stream)

                # 如果图片尺寸大于 64x64，则按比例缩小到 64x64
                if pil_image.width > 64 or pil_image.height > 64:
                    pil_image.thumbnail((64, 64), Image.Resampling.LANCZOS) # 使用高质量缩放

                found_any_icon = True
                tk_image = ImageTk.PhotoImage(pil_image)
                displayed_icons_list.append(tk_image) # 保持引用，防止被垃圾回收

                # 创建 Label 来显示图标和序号
                label = ttk.Label(icon_display_frame, image=tk_image, text=str(idx), compound="top")
                label.grid(row=current_row, column=current_col, padx=5, pady=5)

                current_col += 1
                if current_col >= icons_per_row:
                    current_col = 0
                    current_row += 1

            except IndexError:
                # get_icon 会在索引超出范围时抛出 IndexError，说明所有图标已遍历完
                break # 退出循环
            except Exception as e:
                # 捕获其他可能的异常，例如文件损坏、无法解析、Image.open失败等
                # print(f"处理图标 {idx} 时发生未知错误: {e}") # 可用于调试
                if not found_any_icon and idx == 0:
                    # 如果在处理第一个图标时就出错，则显示警告并退出
                    messagebox.showwarning("图标处理警告", f"在索引 {idx} 处处理图标时发生错误: {e}\n文件: {os.path.basename(file_path)}\n可能无法继续提取图标。")
                    break
                else:
                    # 否则，只是跳过当前图标，继续尝试下一个
                    continue

        if not found_any_icon:
            ttk.Label(icon_display_frame, text="未找到任何图标。请确保文件存在且包含可识别的图标。").grid(row=0, column=0, padx=10, pady=10)

# --- 脚本入口点 ---
if __name__ == "__main__":
    root = tk.Tk()
    app = IconViewerApp(root)
    root.mainloop()