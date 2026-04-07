# OCR处理和Torch依赖说明

## 为什么需要Torch？

### EasyOCR的工作原理

EasyOCR是一个基于深度学习的OCR（光学字符识别）库，它使用：

1. **PyTorch (torch)**：深度学习框架
2. **预训练模型**：CRAFT（文字检测）+ CRNN（文字识别）
3. **神经网络推理**：对每张图片进行前向传播来识别文字

这是**完全正常**的，EasyOCR依赖torch进行神经网络推理。

---

## 首次运行注意事项

### 1. 模型下载

首次使用EasyOCR时，会自动下载预训练模型（约500MB）：
- CRAFT模型：用于检测文字区域
- CRNN模型：用于识别文字内容

模型会缓存到：`~/.EasyOCR/model/`

### 2. 处理时间

在CPU上处理55张图片：
- **首次运行**：约2-3分钟
- **后续运行**：约1-2分钟（模型已加载）

### 3. 警告信息

以下警告是**正常的**，不影响功能：

```
Using CPU. Note: This module is much faster with a GPU.
```
→ 提示使用CPU，如有GPU会更快

```
'pin_memory' argument is set as true but no accelerator is found
```
→ DataLoader的优化提示，CPU上可忽略

```
Palette images with Transparency expressed in bytes should be converted
```
→ PIL处理PNG图片的警告，不影响OCR

---

## 优化方案

### 方案1：使用GPU加速（推荐）

如果有NVIDIA GPU：

```python
# 修改 image_reader.py
_ocr_reader = easyocr.Reader(['ch_sim', 'en'], gpu=True)
```

速度提升：**5-10倍**

### 方案2：使用更轻量的OCR引擎

如果不需要高精度中文识别，可以使用Tesseract：

```bash
# 安装
sudo apt-get install tesseract-ocr tesseract-ocr-chi-sim
pip install pytesseract
```

```python
# 替代方案
import pytesseract
from PIL import Image

def read_image_tesseract(image_path):
    img = Image.open(image_path)
    text = pytesseract.image_to_string(img, lang='chi_sim+eng')
    return text
```

优点：速度快，内存占用小
缺点：中文识别准确率较低

### 方案3：跳过OCR处理

如果只需要运行Demo测试，可以跳过OCR：

```python
# 在 WorldEngineAgent 中添加选项
world_engine = WorldEngineAgent(
    script_folder="午夜列车",
    config=config,
    skip_ocr=True,  # 跳过OCR处理
)
```

### 方案4：OCR结果缓存

将OCR结果缓存到文件，避免重复处理：

```python
import json
from pathlib import Path

def get_cached_ocr(image_path, cache_dir=".ocr_cache"):
    cache_file = Path(cache_dir) / f"{image_path.stem}.json"
    
    if cache_file.exists():
        with open(cache_file) as f:
            return json.load(f)["text"]
    
    # 执行OCR
    result = reader.readtext(str(image_path))
    text = '\n'.join([item[1] for item in result])
    
    # 缓存结果
    cache_file.parent.mkdir(exist_ok=True)
    with open(cache_file, 'w') as f:
        json.dump({"text": text}, f)
    
    return text
```

---

## 性能对比

| 方案 | 速度 | 中文准确率 | 内存占用 | 依赖 |
|------|------|-----------|---------|------|
| EasyOCR (CPU) | 慢 | 高 (95%+) | 大 (2GB) | PyTorch |
| EasyOCR (GPU) | 快 | 高 (95%+) | 大 (2GB) | PyTorch + CUDA |
| Tesseract | 快 | 中 (70-80%) | 小 (100MB) | Tesseract |
| PaddleOCR | 中 | 高 (95%+) | 中 (500MB) | PaddlePaddle |

---

## 推荐配置

### 开发测试环境
```python
# 使用缓存 + 跳过OCR
skip_ocr = True  # 快速迭代
```

### 生产环境
```python
# 使用GPU + 缓存
gpu = True
use_cache = True
```

### 无GPU环境
```python
# 使用CPU + 缓存 + 后台预处理
gpu = False
use_cache = True
preprocess = True  # 首次运行时预处理所有图片
```

---

## 常见问题

### Q1: 为什么我的项目需要torch？

**A**: EasyOCR依赖torch进行深度学习推理。这是OCR功能的必需依赖，不是bug。

### Q2: 可以移除torch依赖吗？

**A**: 可以，但需要：
1. 移除EasyOCR
2. 使用其他OCR引擎（如Tesseract）
3. 或完全跳过图片文字识别

### Q3: 如何减少内存占用？

**A**: 
1. 延迟加载OCR模型（已实现）
2. 处理完立即释放内存
3. 使用更小的模型

### Q4: 如何加快处理速度？

**A**: 
1. 使用GPU
2. 使用缓存
3. 减小图片分辨率
4. 使用多进程处理

---

## 实现细节

### 当前的优化措施

1. **延迟加载**：OCR模型只在首次使用时加载
2. **警告抑制**：隐藏torch和PIL的警告信息
3. **进度显示**：每处理10张图片显示一次进度
4. **错误处理**：单张图片失败不影响整体流程

### 代码示例

```python
# 抑制警告
import warnings
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    result = reader.readtext(image_path)

# 进度显示
if processed % 10 == 0:
    logger.info(f"OCR progress: {processed}/{total}")
```

---

## 总结

- **Torch依赖是正常的**：EasyOCR使用PyTorch进行深度学习推理
- **首次运行较慢**：需要下载模型和加载到内存
- **可以优化**：使用GPU、缓存、或替代方案
- **警告可忽略**：不影响功能，已通过代码抑制

如有其他问题，请参考文档或提交Issue。
