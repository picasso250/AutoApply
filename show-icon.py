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

def get_shell32_path():
    """
    尝试获取 shell32.dll 或 shell32.dll.mun 的路径。
    优先查找 Windows 10+ 上的 .mun 文件。
    """
    system_root = os.environ.get("SystemRoot")
    if not system_root:
        system_root = "C:\\Windows"

    # Windows 10 及更高版本可能将图标存储在 .mun 文件中
    mun_path = os.path.join(system_root, "SystemResources", "shell32.dll.mun")
    if os.path.exists(mun_path):
        return mun_path

    # 传统位置
    dll_path = os.path.join(system_root, "System32", "shell32.dll")
    if os.path.exists(dll_path):
        return dll_path

    return None

def create_scrollable_frame(parent):
    """
    创建一个可滚动的框架。
    """
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

def display_icons():
    """
    从 shell32.dll (或 .mun) 中提取并显示图标。
    """
    file_path = get_shell32_path()

    if not file_path:
        messagebox.showerror("文件未找到", "无法找到 shell32.dll 或 shell32.dll.mun 文件。")
        return

    root = tk.Tk()
    root.title(f"显示 {os.path.basename(file_path)} 中的图标 (从 0 开始)")

    # 创建可滚动区域
    scroll_frame = create_scrollable_frame(root)

    extractor = None
    try:
        extractor = icoextract.IconExtractor(file_path)
    except Exception as e:
        messagebox.showerror("图标提取错误", f"初始化图标提取器时发生错误: {e}\n请确保 'icoextract' 库已正确安装且版本兼容。")
        return

    # 设置每行显示的图标数量
    icons_per_row = 10
    current_row = 0
    current_col = 0
    displayed_icons = [] # 存储 PhotoImage 引用以防止被垃圾回收

    max_icons_to_try = 200 # 限制尝试的图标数量
    found_any_icon = False

    for idx in range(max_icons_to_try):
        try:
            # 尝试通过递增的索引获取图标
            # icoextract 0.2.0 的 get_icon(idx) 方法返回的是一个 BytesIO 对象
            icon_data_stream = extractor.get_icon(idx) 
            
            # 关键修正：将 BytesIO 流加载为 PIL Image 对象
            pil_image = Image.open(icon_data_stream)

            found_any_icon = True

            # 将 PIL Image 转换为 Tkinter PhotoImage
            tk_image = ImageTk.PhotoImage(pil_image)
            displayed_icons.append(tk_image) # 保持引用

            # 创建 Label 来显示图标和序号
            label = ttk.Label(scroll_frame, image=tk_image, text=str(idx), compound="top")
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
            print(f"处理图标 {idx} 时发生未知错误: {e}")
            if not found_any_icon:
                messagebox.showwarning("图标处理警告", f"在索引 {idx} 处处理图标时发生错误: {e}\n可能无法继续提取图标。")
                break
            else:
                continue

    if not found_any_icon:
        ttk.Label(scroll_frame, text="未找到任何图标。请确保DLL文件存在且包含可识别的图标。").grid(row=0, column=0, padx=10, pady=10)

    root.mainloop()

if __name__ == "__main__":
    display_icons()