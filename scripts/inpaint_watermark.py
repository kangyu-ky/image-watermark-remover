#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inpaint_watermark.py — 依据水印框/掩码,用图像修复(inpainting)去除水印并补全内容。

用法:
  python inpaint_watermark.py <image> --box x,y,w,h [--box x2,y2,w2,h2 ...]
  python inpaint_watermark.py <image> --mask mask.png
  python inpaint_watermark.py <image> --box 1200,80,260,40 --mode both --out ./result_dir

参数:
  --box     水印矩形(原图坐标),可重复传入多个
  --mask    水印掩码 PNG(白色=待修复),与 --box 二选一
  --mode    rect | adaptive | both
              rect      : 整块矩形修复(彻底,小水印效果好)
              adaptive  : 只修复与背景差异大的文字/Logo 笔画(更保真,半透明白字效果好)
              both      : 同时输出两种,供执行 Agent 看图择优(默认)
  --engine  telea | ns(默认 telea)
              ns        : Navier-Stokes 流体修复,配合"拆簇小框"时结构保持明显更好
              实战建议:修复框横跨人物轮廓线时,把长水印拆成多个小框 + --engine ns --radius 6
  --radius  修复半径(默认按水印宽度自动计算 3~20;小框+ns 建议 4~6)
  --out     输出目录(默认:输入图片所在目录)
  --suffix  输出文件名后缀(默认 _clean)

输出:
  <stem><suffix>.png                 (--mode rect / adaptive 时)
  <stem><suffix>_rect.png 与 ..._adaptive.png   (--mode both 时)
  <stem><suffix>_compare.jpg         原图 | 结果 并排对比图
"""
import argparse
import os
import sys

import numpy as np

try:
    import cv2
except ImportError:
    sys.exit("缺少依赖 opencv-python-headless,请先执行: pip install opencv-python-headless numpy")


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


def clip_box(x, y, w, h, W, H):
    x, y = max(0, int(x)), max(0, int(y))
    x2, y2 = min(W, int(x + w)), min(H, int(y + h))
    if x2 <= x or y2 <= y:
        raise ValueError(f"水印框超出图像范围或无面积: ({x},{y},{w},{h})")
    return x, y, x2 - x, y2 - y


def build_mask(img, boxes, mode):
    """boxes: list of (x,y,w,h) 已裁剪. 返回 uint8 掩码(255=待修复)"""
    H, W = img.shape[:2]
    mask = np.zeros((H, W), np.uint8)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    for (x, y, w, h) in boxes:
        pad = max(3, int(0.04 * max(w, h)))
        if mode == "rect":
            x0, y0 = max(0, x - pad), max(0, y - pad)
            x1, y1 = min(W, x + w + pad), min(H, y + h + pad)
            mask[y0:y1, x0:x1] = 255
        else:  # adaptive:仅对水印笔画(与局部背景差异大的像素)做修复
            sub = gray[y:y + h, x:x + w]
            if sub.size < 9:
                continue
            ks = int(min(h, w) / 6) | 1  # 奇数且不要太大
            ks = max(3, min(ks, 25))
            bg = cv2.medianBlur(sub, ks)
            d = cv2.absdiff(sub, bg)
            # Otsu 自适应切出"水印结构"像素
            _, m = cv2.threshold(d, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
            m = cv2.dilate(m, np.ones((pad, pad), np.uint8))
            mask[y:y + h, x:x + w] = np.maximum(mask[y:y + h, x:x + w], m)
    return mask


def inpaint(img, boxes, mode, radius=None, engine="telea"):
    """执行修复,返回 (结果图, mask)"""
    H, W = img.shape[:2]
    boxes = [clip_box(*b, W, H) for b in boxes]
    if radius is None:
        mw = max((w for _, _, w, _ in boxes), default=40)
        radius = int(np.clip(0.025 * mw, 3, 20))
    mask = build_mask(img, boxes, mode)
    if mask.sum() == 0:
        raise RuntimeError("掩码为空:请检查 --box 坐标是否正确,或改用 --mode rect")
    algo = cv2.INPAINT_TELEA if engine == "telea" else cv2.INPAINT_NS
    res = cv2.inpaint(img, mask, radius, algo)
    return res, mask


def main():
    ap = argparse.ArgumentParser(description="去除图片水印并补全")
    ap.add_argument("image")
    ap.add_argument("--box", action="append", default=None,
                    help="水印矩形 x,y,w,h(可多次传入)")
    ap.add_argument("--mask", default=None, help="水印掩码 PNG(与 --box 二选一)")
    ap.add_argument("--mode", default="both", choices=["rect", "adaptive", "both"])
    ap.add_argument("--engine", default="telea", choices=["telea", "ns"],
                    help="修复算法:telea(默认)或 ns(拆簇小框时结构更好)")
    ap.add_argument("--radius", type=int, default=None,
                    help="修复半径(默认按水印宽度自动计算)")
    ap.add_argument("--out", default="", help="输出目录")
    ap.add_argument("--suffix", default="_clean")
    args = ap.parse_args()

    if not args.box and not args.mask:
        sys.exit("必须提供 --box 或 --mask")
    if args.box and args.mask:
        sys.exit("--box 与 --mask 只能二选一")

    img = imread_unicode(args.image)
    H, W = img.shape[:2]
    stem = os.path.splitext(os.path.basename(args.image))[0]
    out_dir = args.out or os.path.dirname(os.path.abspath(args.image))
    os.makedirs(out_dir, exist_ok=True)

    def out_path(suf):
        return os.path.join(out_dir, f"{stem}{args.suffix}{suf}.png")

    results = {}
    if args.mask:
        msk = imread_unicode(args.mask)
        msk = cv2.cvtColor(msk, cv2.COLOR_BGR2GRAY)
        msk = cv2.resize(msk, (W, H), interpolation=cv2.INTER_NEAREST)
        msk = (msk > 127).astype(np.uint8) * 255
        algo = cv2.INPAINT_TELEA if args.engine == "telea" else cv2.INPAINT_NS
        res = cv2.inpaint(img, msk, args.radius or 5, algo)
        p = out_path("")
        imwrite_unicode(p, res)
        results["mask"] = p
    else:
        boxes = []
        for s in args.box:
            try:
                x, y, w, h = (int(v) for v in s.split(","))
            except ValueError:
                sys.exit(f"--box 格式应为 x,y,w,h,收到: {s}")
            boxes.append(clip_box(x, y, w, h, W, H))

        modes = ["rect", "adaptive"] if args.mode == "both" else [args.mode]
        for md in modes:
            try:
                res, _ = inpaint(img, boxes, md, radius=args.radius, engine=args.engine)
            except RuntimeError as e:
                print(f"[warn] mode={md} 失败: {e}", file=sys.stderr)
                continue
            suf = "" if len(modes) == 1 else f"_{md}"
            p = out_path(suf)
            imwrite_unicode(p, res)
            results[md] = p
            print(f"[ok] mode={md} -> {p}")

    if not results:
        sys.exit("全部修复模式失败,请检查水印框/掩码后重试")

    # 并排对比图(便于执行 Agent / 用户快速查看)
    if args.mask:
        best_path = results["mask"]
        res = imread_unicode(best_path)
    else:
        # both 时默认取 rect 做对比;Agent 看图后若 adaptive 更好,可直接选用对应文件
        key = "rect" if "rect" in results else list(results)[0]
        res = imread_unicode(results[key])
    Hc = min(H, 720)
    Wc = int(W * Hc / H)
    small_org = cv2.resize(img, (Wc, Hc), interpolation=cv2.INTER_AREA)
    small_res = cv2.resize(res, (Wc, Hc), interpolation=cv2.INTER_AREA)
    canvas = np.hstack([small_org, small_res])
    cv2.putText(canvas, "original", (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2, cv2.LINE_AA)
    cv2.putText(canvas, "cleaned", (Wc + 8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2, cv2.LINE_AA)
    cmp_path = os.path.join(out_dir, f"{stem}{args.suffix}_compare.jpg")
    imwrite_unicode(cmp_path, canvas, [cv2.IMWRITE_JPEG_QUALITY, 92])
    print(f"[ok] 对比图 -> {cmp_path}")


if __name__ == "__main__":
    main()
