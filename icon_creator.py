import sys

# --- PIL (Pillow) 相关的导入 ---
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    # 这里的错误处理主要用于直接运行此文件进行测试时，
    # 主程序中已有更全面的启动时检查。
    print(
        "错误: 缺少 'Pillow' 库。请运行 'pip install Pillow'。",
        file=sys.stderr
    )
    sys.exit(1)

def create_default_icon():
    """
    创建一个带有圆角红色背景和白色字母 "AP" 的图标 (PIL Image)。
    这个函数现在是独立的，不依赖于主应用的任何部分。
    """
    width, height = 64, 64
    # 创建一个 RGBA 模式的图像，背景完全透明
    image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # 定义颜色
    # 背景色：一种柔和、不刺眼的红色 (#D9534F)
    background_color = (217, 83, 79, 255)
    # 文本颜色：白色
    text_color = (255, 255, 255, 255)
    
    # 绘制圆角矩形背景
    # 使用 16px 的圆角半径
    draw.rounded_rectangle(
        (0, 0, width, height),
        radius=16,
        fill=background_color
    )
    
    # 尝试加载字体
    try:
        # 字体大小可以适当调整以适应背景
        font = ImageFont.truetype("arialbd.ttf", 38) # 使用 Arial Bold
    except IOError:
        try:
            font = ImageFont.truetype("arial.ttf", 38)
        except IOError:
            font = ImageFont.load_default()

    text = "AP" # AutoApply
    
    # 使用 textbbox 计算文本精确边界框以实现完美居中
    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    
    # 计算文本绘制的起始位置 (x, y)
    x = (width - text_width) / 2
    # textbbox 返回的 y 坐标是基线位置，需要微调
    y = (height - text_height) / 2 - text_bbox[1] 
    
    # 绘制文本
    draw.text((x, y), text, font=font, fill=text_color)
    
    return image

if __name__ == '__main__':
    # 这个简单的测试脚本允许你直接运行 `python icon_creator.py`
    # 来预览生成的图标。
    print("正在生成图标预览 'icon_preview.png'...")
    icon_image = create_default_icon()
    icon_image.save('icon_preview.png')
    print("预览已保存。")