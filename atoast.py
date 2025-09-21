from win11toast import toast
import time

def send_win11_toast_notification():
    """
    发送一个Windows 11原生Toast通知。
    通知将显示在屏幕右下角。
    """
    title = "来自 Python 的通知！"
    message = "这是一个在 Windows 11 上显示的 Toast 通知。"
    
    print(f"尝试发送通知：标题='{title}', 消息='{message}'")
    
    # 发送Toast通知
    # duration='long' 可以让通知显示更长时间，但通常仍会进入通知中心
    toast(title, message, duration='long') #cite: 1, 3
    
    print("通知已发送。请检查您的屏幕右下角或通知中心。")

if __name__ == "__main__":
    send_win11_toast_notification()
    
    # 等待几秒钟，确保用户有机会看到通知（如果通知没有立即进入通知中心）
    time.sleep(5) 