"""
Geetest v3 slide (slide3) image de-scramble + gap distance — reversed from slide.7.9.3.js.

The bg/fullbg the server serves are column-scrambled (312px). slide.js reassembles them into a
260px image on a canvas via a fixed permutation Ut, then the user drags the slice into the gap.
Ut generator + the 52-slice draw loop are reproduced here byte-for-byte from the JS (lines 258-276,
4700-4707). Gap distance = template-match the slice piece against the de-scrambled bg.
"""
from __future__ import annotations
import numpy as np
try:
    import cv2
except Exception:
    cv2 = None

# Ut permutation (slide.js 4700): from '6_11_7_10_4_12_3_1_0_5_2_9_8'
_E = [6, 11, 7, 10, 4, 12, 3, 1, 0, 5, 2, 9, 8]
def _build_ut():
    ut = []
    for r in range(52):
        t = 2 * _E[(r % 26) // 2] + r % 2
        if (r // 2) % 2 == 0:
            t += -1 if (r % 2) else 1
        t += 26 if r < 26 else 0
        ut.append(t)
    return ut
UT = _build_ut()   # [39,38,48,49,41,40,...] the canonical Geetest slide permutation


def descramble(img: np.ndarray) -> np.ndarray:
    """312xH scrambled -> 260xH. slice i (10px wide, half-height) drawn from source Ut[i]."""
    a = img.shape[0] // 2
    out = np.zeros((img.shape[0], 260, img.shape[2]), img.dtype)
    for i in range(52):
        sx = UT[i] % 26 * 12 + 1
        sy = a if UT[i] > 25 else 0
        dx = (i % 26) * 10
        dy = a if i > 25 else 0
        out[dy:dy + a, dx:dx + 10] = img[sy:sy + a, sx:sx + 10]
    return out


def _decode(b: bytes) -> np.ndarray:
    return cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_UNCHANGED)


def gap_distance(bg_bytes: bytes, slice_bytes: bytes, xpos: int = 0) -> int:
    """distance the slider must travel = gap_left - piece_left_in_slice - xpos.
    bg/slice are the raw image bytes from the slide get.php URLs. Verified: the correct distance
    passes the server's answer check (wrong -> 'fail', right -> risk-checked)."""
    if cv2 is None:
        raise RuntimeError("pip install opencv-python numpy")
    bg = descramble(_decode(bg_bytes))[:, :, :3]
    sl = _decode(slice_bytes)
    ys, xs = np.where(sl[:, :, 3] > 40)          # non-transparent piece bbox
    tmpl = sl[ys.min():ys.max() + 1, xs.min():xs.max() + 1, :3]
    piece_left = int(xs.min())
    res = cv2.matchTemplate(cv2.Canny(bg, 100, 200), cv2.Canny(tmpl, 100, 200), cv2.TM_CCOEFF_NORMED)
    _, _, _, loc = cv2.minMaxLoc(res)
    return int(loc[0]) - piece_left - xpos
