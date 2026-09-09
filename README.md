# image-watermark-remover
去除图片上由 AI 生成平台或社交平台添加的水印(角落半透明 Logo / 文字),并用图像修复(inpainting)补全被水印遮挡的内容,输出无水印图片与前后对比图。本 Skill 采用 本地确定性修复为默认路径,AI 生成补全为升级路径 的分级策略:  Level 1(默认):脚本自动检测水印 → 执行 Agent 看图复核 → OpenCV inpaint 修复 → 看图择优。快速、可复现、无网络依赖。 Level 2(升级):Level 1 效果不达标(涂抹痕迹明显 / 水印盖住人脸文字等关键结构)时,改用 ImageGen 图生图做高保真补全。
