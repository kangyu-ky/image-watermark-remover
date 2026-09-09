#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
detect_watermark.py — 定位图片角落的 AI 平台水印(半透明 Logo / 文字),输出候选框与可视化。

设计定位:
  本脚本是"辅助检测"工具,给执行 Agent 提供水印位置的起点候选 + 可视化标注图复核。
  启发式算法无法保证 100% 命中:若脚本漏检或框不准,Agent 应直接查看原图,
  用肉眼判断水印大致位置,并在调用 inpaint_watermark.py 时手动 --box 指定。

用法:
  python detect_watermark.py <image> [--json out.json] [--visual out_boxes.jpg] [--max-side 1600] [--min-conf 0.30]

输出(JSON):
  {
    "image_size": [w, h],
    "found": true,
    "candidates": [
      {"x":.., "y":.., "w":.., "h":.., "corner":"bottom-right", "confidence":0.87, "note":"..."}
    ]
  }
  坐标均为原图坐标系。
"""
import argparse
import json
import os
import sys

import numpy as np

try:
    import cv2
except ImportError:
    sys.exit("缺少依赖 opencv-python-headless,请先执行: pip install opencv-python-headless numpy")


# --------------------------------------------------------------------------- #
# IO helpers(支持中文 / 空格路径)
# --------------------------------------------------------------------------- #
def imread_unicode(path):
    data = np.fromfile(path, dtype=np.uint8)
    if data.size == 0:
        raise FileNotFoundError(f"无法读取图片: {path}")
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"图片解码失败(格式不支持?): {path}")
    return img


def imwrite_unicode(path, img, params=None):
    ext = os.path.splitext(path)[1] or ".jpg"
    ok, buf = cv2.imencode(ext, img, params or [])
    if not ok:
        raise RuntimeError(f"编码图片失败: {path}")
    buf.tofile(path)


CORNER_NAMES = {
    "tl": "top-left",
    "tr": "top-right",
    "bl": "bottom-left",
    "br": "bottom-right",
}


# --------------------------------------------------------------------------- #
# 水印候选检测
# --------------------------------------------------------------------------- #
def corner_roi(w, h, corner, frac=0.24):
    """返回 (x0,y0,x1,y1): 从 corner 角向图内扩展 frac 比例的矩形 ROI"""
    sw, sh = max(8, int(w * frac)), max(8, int(h * frac))
    if corner == "tl":
        return 0, 0, sw, sh
    if corner == "tr":
        return w - sw, 0, w, sh
    if corner == "bl":
        return 0, h - sh, sw, h
    if corner == "br":
        return w - sw, h - sh, w, h
    raise ValueError(corner)


def detect_candidates(img, min_side=600):
    """在四角寻找疑似水印的文字/Logo 块。返回候选 dict 列表(降采样坐标)。"""
    h, w = img.shape[:2]
    # 1) 降采样,保证后续运算快且 medianBlur 核尺寸合理
    scale = 1.0
    work = img
    if min(h, w) > 1600:
        scale = 1600.0 / min(h, w)
        work = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        h, w = work.shape[:2]

    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)

    # 2) 背景估计:大核中值滤波抹掉小尺度文字/Logo,保留场景大结构
    k = int(max(15, min(h, w) / 40))
    k = k | 1  # 强制奇数
    bg = cv2.medianBlur(gray, k)
    diff = cv2.absdiff(gray, bg).astype(np.float32)

    cands = []
    for corner in ("tl", "tr", "bl", "br"):
        x0, y0, x1, y1 = corner_roi(w, h, corner)
        roi = diff[y0:y1, x0:x1]
        if roi.size < 40:
            continue
        # 3) 角 ROI 内自适应阈值:结构像素 = 显著偏离背景的像素
        thr = float(roi.mean() + 1.6 * roi.std())
        msk = (roi > max(thr, 12.0)).astype(np.uint8) * 255
        # 膨胀把相邻文字笔画/字母连通成一个块
        msk = cv2.morphologyEx(msk, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
        msk = cv2.dilate(msk, np.ones((9, 9), np.uint8))
        cnts, _ = cv2.findContours(msk, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        roi_w, roi_h = x1 - x0, y1 - y0
        for c in cnts:
            bx, by, bw, bh = cv2.boundingRect(c)
            # 尺寸过滤:太小是噪点,太大通常是角部真实内容而非水印
            if bw < 8 or bh < 6 or bw > roi_w * 0.6 or bh > roi_h * 0.6:
                continue
            area_ratio = (bw * bh) / float(roi_w * roi_h)
            if area_ratio < 0.006:
                continue
            gx, gy = x0 + bx + bw / 2.0, y0 + by + bh / 2.0  # 全局中心
            # 与最近图像角的距离(判定"贴角")
            d = min(gx, w - gx, gy, h - gy)
            d_norm = d / (0.5 * min(w, h))
            # 框内结构强度
            inner = roi[by:by + bh, bx:bx + bw]
            mean_d = float(inner.mean())
            score_c = float(np.clip(1.0 - d_norm / 0.7, 0.0, 1.0))
            score_s = 1.0 if 0.006 <= area_ratio <= 0.30 else max(0.0, 1.0 - abs(area_ratio - 0.12) / 0.3)
            score_d = float(np.clip(mean_d / 60.0, 0.0, 1.0))
            conf = 0.45 * score_c + 0.25 * score_s + 0.30 * score_d
            note = f"corner={CORNER_NAMES[corner]}, area_ratio={area_ratio:.3f}"
            cands.append({
                "x": int((x0 + bx) / scale), "y": int((y0 + by) / scale),
                "w": int(bw / scale), "h": int(bh / scale),
                "corner": CORNER_NAMES[corner], "confidence": round(float(conf), 3),
                "note": note,
            })

    # 4) 按置信度降序 + 简单 NMS 去重叠
    cands.sort(key=lambda c: c["confidence"], reverse=True)
    kept = []
    for c in cands:
        if all(not _iou(c, kk) > 0.5 for kk in kept):
            kept.append(c)
    return kept


def _iou(a, b):
    ax1, ay1, ax2, ay2 = a["x"], a["y"], a["x"] + a["w"], a["y"] + a["h"]
    bx1, by1, bx2, by2 = b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / union if union > 0 else 0.0


def draw_boxes(img, cands):
    out = img.copy()
    for c in cands:
        x, y, w, h = c["x"], c["y"], c["w"], c["h"]
        color = (0, 200, 0) if c["confidence"] >= 0.5 else (0, 200, 255)
        cv2.rectangle(out, (x, y), (x + w, y + h), color, max(2, int(min(out.shape[:2]) / 300)))
        label = f"{c['corner']} {c['confidence']:.2f}"
        cv2.putText(out, label, (x, max(18, y - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)
    return out


def main():
    ap = argparse.ArgumentParser(description="检测图片角落的 AI 平台水印")
    ap.add_argument("image", help="输入图片路径")
    ap.add_argument("--json", default="", help="候选框 JSON 输出路径(默认 stdout)")
    ap.add_argument("--visual", default="", help="标注预览图输出路径,如 xxx_wm_boxes.jpg")
    ap.add_argument("--min-conf", type=float, default=0.30, help="认定为命中水印的最低置信度")
    args = ap.parse_args()

    img = imread_unicode(args.image)
    h, w = img.shape[:2]
    cands = detect_candidates(img)
    for c in cands:
        c["confidence"] = round(c["confidence"], 3)
    hit = [c for c in cands if c["confidence"] >= args.min_conf]
    result = {"image_size": [w, h], "found": bool(hit), "candidates": cands}

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"[ok] JSON -> {args.json}")
    else:
        print(text)

    if args.visual:
        vis = draw_boxes(img, cands)
        imwrite_unicode(args.visual, vis)
        print(f"[ok] 标注图 -> {args.visual}")


if __name__ == "__main__":
    main()
