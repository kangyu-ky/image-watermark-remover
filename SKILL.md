---
name: image-watermark-remover
description: Remove watermark logos / text overlays from images (especially AI image platform watermarks like 即梦 Jimeng, 可灵 Kling, Midjourney, 通义万相, 豆包/Seedream corner semi-transparent marks) and inpaint the covered region to reconstruct natural content, returning a clean watermark-free image plus a before/after comparison. Use whenever a user asks to 去水印 / 去除水印 / 消除AI水印 / remove watermark / clean watermark / 得到无水印原图, or hands over an image with a corner logo/text mark they want removed and the covered content restored.
agent_created: true
---

# Image Watermark Remover(图片去水印与内容补全)

## Overview

去除图片上由 AI 生成平台或社交平台添加的水印(角落半透明 Logo / 文字),并用图像修复(inpainting)补全被水印遮挡的内容,输出无水印图片与前后对比图。本 Skill 采用 **本地确定性修复为默认路径,AI 生成补全为升级路径** 的分级策略:

- **Level 1(默认)**:脚本自动检测水印 → 执行 Agent 看图复核 → OpenCV inpaint 修复 → 看图择优。快速、可复现、无网络依赖。
- **Level 2(升级)**:Level 1 效果不达标(涂抹痕迹明显 / 水印盖住人脸文字等关键结构)时,改用 ImageGen 图生图做高保真补全。

## 前置环境

脚本依赖 `opencv-python-headless` 与 `numpy`。首次使用先确认,缺失则安装:

```bash
python -c "import cv2, numpy" 2>/dev/null || pip install opencv-python-headless numpy
```

脚本所在目录:本 Skill 的 `scripts/`。执行时用绝对路径调用,例如:

```bash
python "<skill_dir>/scripts/detect_watermark.py" --help
```

## 工作流

### Step 1 检测水印位置

```bash
python "<skill_dir>/scripts/detect_watermark.py" "<图片路径>" \
  --visual "<输出目录>/<文件名>_wm_boxes.jpg" \
  --json "<输出目录>/<文件名>_wm.json"
```

脚本输出候选框 JSON,并生成绿色框标注预览图。检测为启发式,**必须人工(Agent 视觉)复核**:

1. 用 Read 打开 `<文件名>_wm_boxes.jpg`,逐框核对是否准确框住水印。
2. 框准确 → 记录候选框坐标,进入 Step 2。
3. 漏检 / 框偏 → 直接用 Read 查看**原图**,目测水印位置,按 `x,y,w,h` 记录(从左上角起算的像素坐标,水印框应比水印略大、留 3~8 像素余量)。
4. 检测框包含角部真实内容(误报)→ 忽略该框,只保留真正的水印框。

参考:常见平台水印特征表与检测原理见 `references/watermarks.md`。

### Step 2 本地修复(Level 1)

```bash
python "<skill_dir>/scripts/inpaint_watermark.py" "<图片路径>" \
  --box x,y,w,h \
  --mode both \
  --out "<输出目录>"
```

- `--box` 可重复传入多个水印框(一张图多处水印时)。
- `--mode both` 默认同时产出 `rect`(整块修复)与 `adaptive`(笔画级修复)两个结果及一张 `*_compare.jpg` 原图|修复并排对比图。
- 若已确定哪种模式更好,可指定 `--mode rect` 或 `--mode adaptive`。

### Step 3 质量门禁与择优

用 Read 打开对比图与两个修复结果,检查:

- 水印是否完全消失(无残影、无半透明"鬼影")。
- 修复区是否自然(无模糊块、无接缝、纹理与周边连续)。
- 画面其余部分未被改动。

两者取更自然的一张作为交付结果;若两个结果都有可见涂抹,先做 **Level 1.5 参数迭代**(见下),仍不行才进入 Step 4。

### Step 3.5 Level 1.5 参数迭代(实测有效的进阶技巧)

修复框横跨强边缘(人物轮廓线、建筑边)时,整条带修复必然涂抹。按序尝试:

1. **拆簇小框**:把长水印(如"小红书号:123456"这类文字行)按字符簇拆成多个小框,刻意**保留中间的轮廓线段作为锚点**,小孔锚点近、涂抹大幅减轻。框间只留 2~6px 缝隙,漏缝会残字,宁可轻微重叠也不要留缝。直接用脚本 CLI 的 NS 引擎:
   ```bash
   python inpaint_watermark.py <img> --box <簇1> --box <簇2> --box <簇3> --engine ns --radius 6 --mode rect
   ```
   文字与关键结构(如手指皮肤)重叠、整框会糊掉结构时,进一步用"笔画级薄掩码":只把灰度超过阈值的文字像素计入掩码(阈值 ~200,dilate 5x5),保留字缝间像素作锚点,再 `--engine ns --radius 3`(此时建议构造 mask.png 后用 `--mask` 传入)。
2. **FSR 重建**(需 opencv-contrib-python-headless):对结构保持好、确定性,但很慢(大图可达 20 分钟+),仅在小图或用户可等待时用:
   ```python
   cv2.xphoto.inpaint(img, mask, dst, cv2.xphoto.INPAINT_FSR_BEST)
   ```
3. **禁用 SHIFTMAP**(`cv2.xphoto.INPAINT_SHIFTMAP`):它从全图拷贝纹理块,**会把水印自身复制到修复区**,实测不可用。
4. **半透明白字水印 → 反解校正(优先于一切修补!)**:若水印是白色半透明叠加(`obs = bg·(1-α) + 255α`),可以数学还原而非修补。步骤:
   - 估计 α:在水印带内取中值背景 `med = medianBlur(gray, 51)`,`diff = gray - med`;只在**强水印像素(diff>12)且中低亮度背景(med<235)**上取 `α = median(diff/(255-med))`(典型值 0.3~0.5);
   - 校正:`out = obs - α·(255-med)`,只作用于掩码 `diff>阈值` 处(羽化过渡)。对非水印像素校正值≈0,安全,近白背景也不会爆炸;
   - **禁止**用除法反解 `(obs-255α)/(1-α)` 作用到大掩码上——掩码误伤的非水印像素会被整体压暗产生黑块;近白背景(med>250)处该式数值不稳定;
   - **禁止**在密集粗笔画文字区内做"向中值收敛"的平整——中值核会被笔画本身污染,产生灰块;
   - 若白衣等亮背景上有残底,再用细掩码 NS 收尾(掩码限 `med>236` 的亮区,`|diff|>2.2`,Sobel>80 的强轮廓除外),最后可对平滑区做低频高斯混合抛光。
   - 实测:压在"白衣+皮肤+蓝渐变"三种背景上的豆包水印(α≈0.43)用此法+NS 收尾+抛光基本清零。
5. **文字密集的海报禁走 ImageGen**:海报上有大量标题/文案时,图生图必然破坏文字,Level 2 不可用,只能在 Level 1.5 内迭代到最优并诚实告知残留。

### Step 4 AI 高保真补全(Level 2,仅当 Level 1 不达标)

保留 Step 3 中较好结果作为"修复基线"图片,然后:

1. 调用 ImageGen 工具,使用**图生图(image-to-image)**能力,输入修复基线图片,提示词明确:
   - 位置:水印原来所在的区域(用图中相对位置描述,如"右下角区域 / bottom-right area");
   - 动作:"去除残留水印/伪影,重建被覆盖的内容";
   - 约束:"保持其余画面、构图、光影、风格、人物身份完全不变;输出与周边像素无缝融合的自然结果"。
2. 用 Read 查看生成结果与原图对比;若模型改动了整体画面或生成内容不真实,可迭代 1~2 次。

**ImageGen 实测注意事项(重要)**:
- 生成模型**几乎必然重新取景**(改变构图/比例/加入裁剪外的内容),即使提示词强调"保持构图"。生成图与原图**无法通过 SIFT 特征配准对齐**(卡通平色图匹配点过少),不要浪费时间做生成图贴回。
- 生成模型**可能自带新的 AI 角标**,交付前必须检查生成图四角。
- 因此 Level 2 的现实定位:整张重新生成的图作为**独立交付候选**(告知用户整体会有细微重绘差异),而不是"局部补丁源"。局部保真需求靠 Level 1/1.5 满足。
3. 诚实告知用户:通用图生图会重绘全图(背景色调、细节与原图存在细微差异),无法保证逐像素一致。

> 已知局限:Level 2 依赖 ImageGen 工具的局部一致性表现,结果需每次人工目检。生成式模型无法做到 OpenCV inpaint 那样的"仅改水印区域"硬约束。

### Step 5 交付

- 把最优结果复制为清晰命名(如 `<原名>_无水印.png`),保存为 PNG 无损格式。
- 保留原图不动;删除中间产物(检测框图、候选 json、较差的结果)或移入 `_intermediate/` 子目录。
- 用 Read 打开最终图做最后一次目检,再用 present_files 将**最终无水印图 + 前后对比图**一起呈现给用户。

## 命令速查

| 目的 | 命令 |
|---|---|
| 检测 | `python detect_watermark.py <img> --visual box.jpg --json box.json` |
| 手动指定修复 | `python inpaint_watermark.py <img> --box x,y,w,h --mode both --out dir` |
| 跨轮廓水印 | 多个 `--box` 拆簇 + `--engine ns --radius 6 --mode rect` |
| 笔画级薄掩码 | 构造 mask.png 后 `--mask mask.png --engine ns --radius 3` |
| 多水印 | 追加多个 `--box x,y,w,h` |
| 已知掩码 | `python inpaint_watermark.py <img> --mask mask.png --out dir` |
| 只看一种模式 | `--mode rect` / `--mode adaptive` |

## 关键要点

- **复核不可省**:检测脚本是启发式的,一切以 Agent 看图判断为准;宁可多传一个 `--box` 也不要漏掉水印。
- **坐标统一**:所有 `--box` 均为原图坐标系像素值,由 `detect_watermark.py` JSON 输出直接可得。
- **半透明水印**:多数平台水印半透明,`adaptive` 模式通常更保真;若背景纹理复杂导致残影,改用 `rect`。
- **多水印顺序**:先修大框再修小框一般效果更稳;复杂场景可拆开逐次修复。
- 详细调参与效果边界参见 `references/watermarks.md`。

## 合规

仅处理用户有权修改的图片(自有版权、已获授权、或平台明确允许去除自身角标的内容)。不为规避他人版权标识提供帮助。
