# Image Watermark Remover(图片去水印与内容补全)

一个用于去除 AI 生成平台 / 社交平台水印的 **Agent Skill**:自动检测水印位置(四角半透明 Logo / 文字),用 OpenCV inpainting 做本地确定性修复,效果不足时升级为 ImageGen 图生图高保真补全,输出无水印图片 + 前后对比图。

> 适用于 即梦 Jimeng、可灵 Kling、Midjourney、通义万相、豆包/Seedream 等平台的角落半透明角标。

## ✨ 特性

- **分级修复策略**
  - Level 1(默认):脚本自动检测水印 → Agent 看图复核 → OpenCV inpaint 修复 → 看图择优。快速、可复现、无网络依赖。
  - Level 1.5(进阶):拆簇小框 + NS 引擎、笔画级薄掩码、半透明白字反解校正等实测技巧,处理跨轮廓/半透明水印。
  - Level 2(升级):Level 1 不达标时,改用 ImageGen 图生图做整图高保真补全。
- **启发式检测 + 人工复核**:检测脚本输出候选框 JSON 与可视化标注图,由 Agent 视觉复核,保证不漏检、不误伤。
- **多水印支持**:可同时传入多个水印框,支持整块修复 / 笔画级修复两种模式择优。

## 📦 仓库结构

```
image-watermark-remover/
├── SKILL.md                  # Skill 主文件(frontmatter 的 description 决定触发时机)
├── README.md
├── LICENSE                   # MIT
├── requirements.txt          # 脚本依赖
├── scripts/
│   ├── detect_watermark.py   # 检测水印位置 → JSON + 标注图
│   └── inpaint_watermark.py  # 按框/掩码修复水印 → PNG + 对比图
└── references/
    └── watermarks.md         # 各平台水印特征与调参边界
```

## 🚀 安装到 Agent(WorkBuddy / Claude Code / CodeBuddy)

Skill 是"目录即技能":只要把整个目录(含 `SKILL.md`)放进技能的**用户级目录**即可。

| Agent | 用户级技能目录 |
|---|---|
| WorkBuddy | `~/.workbuddy/skills/` |
| Claude Code | `~/.claude/skills/` |
| CodeBuddy | `~/.codebuddy/skills/` |

**方式一:git clone 直接安装(推荐,后续可 `git pull` 更新)**

```bash
# 以 WorkBuddy 为例,Windows 上 ~ 即 C:\Users\<用户名>
git clone https://github.com/<你的用户名>/image-watermark-remover.git \
  ~/.workbuddy/skills/image-watermark-remover
```

**方式二:手动拷贝**

下载仓库 zip,把整个 `image-watermark-remover` 目录(内含 `SKILL.md`)拷贝到上表对应目录,重启对话即可。

安装完成后,当用户发来带水印的图片并说"去水印"时,该 Skill 会根据 `SKILL.md` 的 description 自动触发。

## 🔧 脚本依赖

```bash
pip install -r requirements.txt
# opencv-python-headless  numpy
# (可选)Level 1.5 FSR 重建引擎: pip install opencv-contrib-python-headless
```

## 🖥️ CLI 直接使用(不经过 Agent 也可)

```bash
# 1. 检测水印(输出候选框 JSON + 标注图)
python scripts/detect_watermark.py 图片.png \
  --visual 输出目录/标注图.jpg --json 输出目录/候选框.json

# 2. 按框修复(可传多个框,自动输出 rect/adaptive 两种结果与对比图)
python scripts/inpaint_watermark.py 图片.png \
  --box 1200,80,260,40 --mode both --out 输出目录/

# 3. 进阶:跨轮廓水印 → 拆簇小框 + NS 引擎
python scripts/inpaint_watermark.py 图片.png \
  --box 1200,80,260,40 --box 1250,90,60,30 --engine ns --radius 6 --mode rect

# 4. 已知掩码 PNG 直接修复
python scripts/inpaint_watermark.py 图片.png --mask mask.png --out 输出目录/
```

完整参数说明与各平台水印特征见 [SKILL.md](SKILL.md) 与 [references/watermarks.md](references/watermarks.md)。

## ⚠️ 合规说明

仅处理用户**有权修改**的图片(自有版权、已获授权、或平台明确允许去除自身角标的内容)。不为规避他人版权标识提供帮助。

## 📄 协议

[MIT](LICENSE) © 2026 image-watermark-remover contributors

> 发布前可把 LICENSE 版权行改成你自己的名字/邮箱。
