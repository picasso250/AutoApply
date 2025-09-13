#Requires AutoHotkey v2.0
#SingleInstance Force

Gui := Gui("可调整大小", "Shell32.dll 图标展示")
Gui.SetFont("s10")

; 定义每行显示多少个图标
IconsPerRow := 10
IconSize := 32 ; 图标大小，例如 32x32

; 用于加载 shell32.dll
; shell32_path := A_WinDir "\System32\shell32.dll"
; For Windows 10+, prefer .mun file if it exists
shell32_path := A_WinDir "\SystemResources\shell32.dll.mun"
If !FileExist(shell32_path)
    shell32_path := A_WinDir "\System32\shell32.dll"

If !FileExist(shell32_path) {
    MsgBox "无法找到 shell32.dll 或 shell32.dll.mun 文件。", "错误", "IconError"
    ExitApp
}

; 假设 shell32.dll 中有足够多的图标，这里我们尝试一个范围
; 实际的图标数量可能非常大，根据需要调整上限
MaxIconsToDisplay := 500

current_row := 0
current_col := 0

For i := 0 UpTo MaxIconsToDisplay - 1
{
    Try {
        ; AHK Gui Add Picture 支持 *icon 来从文件中提取图标
        ; *%IconSize% 是指定图标尺寸，紧跟在 * 后面
        ; %shell32_path% 是DLL路径，%i% 是图标索引
        Gui.Add("Picture", "x+" (current_col > 0 ? 5 : 0) " y" (current_col = 0 ? "+5" : "Same") " w" IconSize " h" IconSize, "*" IconSize " " shell32_path " " i)
        ; 添加图标编号
        Gui.Add("Text", "x" (A_ScreenWidth / 2 - 20) " y+0", i) ; (这行需要调整位置，使其在图标下方)
        ; 上面的 Text 位置有问题，需要重新计算。更简单的方式是先画图标，再画文本

        ; 调整位置以便显示编号
        ; 创建一个垂直布局，图标和文本上下排列
        Gui.Add("Text", "x" (current_col * (IconSize + 20) + 10) " y" (current_row * (IconSize + 30) + 5) , i)
        Gui.Add("Picture", "x" (current_col * (IconSize + 20) + 10) " y" (current_row * (IconSize + 30) + 20) " w" IconSize " h" IconSize, "*" IconSize " " shell32_path " " i)


        current_col += 1
        If (current_col >= IconsPerRow) {
            current_col := 0
            current_row += 1
        }
    } Catch As err {
        ; 如果图标索引无效，Gui.Add 会抛出错误，我们捕获并停止
        ; MsgBox "在索引 " i " 处停止： " err.Message
        Break
    }
}

Gui.Show("w" (IconsPerRow * (IconSize + 20) + 50)) ; 调整窗口宽度以适应图标数量
return

Gui_Escape:
Gui_Close:
ExitApp