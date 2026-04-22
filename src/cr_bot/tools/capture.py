import cv2
import numpy as np
import subprocess
import os
from cr_bot.config.device_config import DEVICE_ID, adb_command
from cr_bot.paths import TEMPLATES_DIR

def capture_region(device_id=None, x1=528, y1=2236, x2=914, y2=2418, save_path=None):
    """
    获取指定像素区域的截图
    
    Args:
        device_id (str): 设备ID或地址，如 '127.0.0.1:16384'
        x1, y1 (int): 区域左上角坐标
        x2, y2 (int): 区域右下角坐标
        save_path (str): 保存截图的路径，如果为None则不保存
        
    Returns:
        numpy.ndarray: 截取的图像区域，如果失败则返回None
    """
    try:
        # 确定ADB命令
        adb_cmd = adb_command("exec-out", "screencap", "-p", device_id=device_id or DEVICE_ID)
        
        # 执行ADB截图命令
        process = subprocess.Popen(adb_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()
        
        if stderr:
            print(f"ADB截图错误: {stderr.decode()}")
            return None
        
        # 将截图数据转换为numpy数组
        nparr = np.frombuffer(stdout, np.uint8)
        full_screenshot = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if full_screenshot is None:
            print("错误: 无法解码截图")
            return None
        
        # 提取指定区域
        region = full_screenshot[y1:y2, x1:x2]
        
        # 保存截图（如果指定了路径）
        if save_path is not None:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            cv2.imwrite(save_path, region)
            print(f"区域截图已保存: {save_path}")
        
        return region
        
    except Exception as e:
        print(f"截图异常: {e}")
        return None

# 使用示例
if __name__ == "__main__":
    # 获取指定区域截图
    region = capture_region(
        device_id=DEVICE_ID,
        x1=625, y1=2200, x2=800, y2=2300,
        save_path=os.path.join(os.fspath(TEMPLATES_DIR), "screenshot_region.png")
    )
    
    if region is not None:
        print(f"成功获取区域截图，尺寸: {region.shape}")
    else:

        print("获取区域截图失败")
