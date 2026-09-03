import os
from PIL import Image

def process_png_images(input_dir, output_dir):
    # 確保輸出資料夾存在
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # 設定白色判定閾值 (大於此數值的 RGB 會被視為白色)
    # 設定 240 可以順便過濾掉邊緣微小的灰白像素 (抗鋸齒)
    white_threshold = 240 
    
    # 設定目標淺灰色 (這裡選用帶有一點莫蘭迪質感的低飽和淺灰)
    # 若想調整深淺，可以修改這三個數值 (R, G, B)
    target_gray = (190, 195, 198) 

    # 走訪輸入資料夾中的所有檔案
    for filename in os.listdir(input_dir):
        if filename.lower().endswith('.png'):
            input_path = os.path.join(input_dir, filename)
            output_path = os.path.join(output_dir, filename)
            
            try:
                # 打開圖片並強制轉換為帶有透明通道的 RGBA 模式
                img = Image.open(input_path).convert("RGBA")
                
                # 獲取圖片的所有像素資料
                datas = img.getdata()
                new_data = []
                
                for item in datas:
                    r, g, b, a = item
                    
                    # 條件 1：如果該像素是完全透明的，保持不變
                    if a == 0:
                        new_data.append(item)
                        
                    # 條件 2：如果是白色（或接近白色），將其 Alpha 值設為 0 (完全透明)
                    elif r > white_threshold and g > white_threshold and b > white_threshold:
                        new_data.append((255, 255, 255, 0))
                        
                    # 條件 3：其他有顏色的部分，替換成我們設定的淺灰色，並保留原本的透明度(Alpha)
                    else:
                        new_data.append((target_gray[0], target_gray[1], target_gray[2], a))
                
                # 將新像素資料寫回圖片並存檔
                img.putdata(new_data)
                img.save(output_path, "PNG")
                print(f"✅ 成功處理: {filename}")
                
            except Exception as e:
                print(f"❌ 處理 {filename} 時發生錯誤: {e}")

# ================= 使用方式 =================
# 請將這裡的路徑替換成您電腦中的實際資料夾路徑
input_folder = "."   # 原始圖片資料夾
output_folder = "./output_icons" # 處理後的圖片要存放的資料夾

print("開始處理圖片...")
process_png_images(input_folder, output_folder)
print("處理完成！")
