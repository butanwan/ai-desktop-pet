"""bbox_utils.py — 角色范围（包围盒）计算工具。

仅依赖 PIL + numpy，用于导入角色包时**自动识别帧、生成鼠标点击范围**
（bboxes.json 的 human 字段）。与抠像无关，可独立使用。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image
import numpy as np


def compute_bbox(frames_dir) -> list:
    """对所有导出帧求不透明像素的并集包围盒，返回 [x, y, w, h]（基于帧原始尺寸）。

    用于自动生成鼠标点击范围（bboxes.json 的 human 字段）。
    """
    frames_dir = Path(frames_dir)
    pngs = sorted(frames_dir.glob("*.png"))
    if not pngs:
        return [0, 0, 0, 0]
    min_x, min_y, max_x, max_y = None, None, None, None
    for p in pngs:
        img = Image.open(p).convert("RGBA")
        w, h = img.size
        alpha = np.asarray(img.getchannel("A"))
        ys, xs = np.where(alpha > 16)
        if xs.size == 0:
            continue
        min_x = xs.min() if min_x is None else min(min_x, int(xs.min()))
        min_y = ys.min() if min_y is None else min(min_y, int(ys.min()))
        max_x = xs.max() if max_x is None else max(max_x, int(xs.max()))
        max_y = ys.max() if max_y is None else max(max_y, int(ys.max()))
    if min_x is None:
        return [0, 0, w, h]
    return [min_x, min_y, max_x - min_x + 1, max_y - min_y + 1]
