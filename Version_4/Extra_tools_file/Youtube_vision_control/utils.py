import numpy as np

def get_angle(a, b, c):
    """
    Angle at point b, between lines a→b and b→c
    Input  : 3 tuples of (x, y) raw landmark values
    Returns: angle in degrees (0 - 360)
    """
    radians = np.arctan2(c[1]-b[1], c[0]-b[0]) - np.arctan2(a[1]-b[1], a[0]-b[0])
    angle = np.abs(np.degrees(radians))
    return angle


def get_distance(landmark_list):
    """
    Distance between 2 points mapped to 0-1000 scale
    Input  : list of 2 tuples [(x1,y1), (x2,y2)] raw landmark values
    Returns: distance scaled 0 to 1000
    """
    if len(landmark_list) < 2:
        return 0
    (x1, y1), (x2, y2) = landmark_list[0], landmark_list[1]
    L = np.hypot(x2 - x1, y2 - y1)
    return np.interp(L, [0, 1], [0, 1000])


# ── Usage inside main loop ───────────────────────────────────────
# if detection_result.hand_landmarks:
#     lm = detection_result.hand_landmarks[0]  # first hand

#     # Extract points as tuples (raw values)
#     thumb_tip  = (lm[4].x,  lm[4].y)
#     thumb_mid  = (lm[3].x,  lm[3].y)
#     thumb_base = (lm[2].x,  lm[2].y)
#     index_tip  = (lm[8].x,  lm[8].y)
#     wrist      = (lm[0].x,  lm[0].y)

#     # ── Angle at thumb middle joint ──
#     angle = get_angle(thumb_tip, thumb_mid, thumb_base)
#     print(f"Thumb angle : {angle:.1f}°")

#     # ── Distance thumb to index ──────
#     dist = get_distance([thumb_tip, index_tip])
#     print(f"Pinch dist  : {dist:.1f}")

#     # ── Actions based on values ──────
#     if dist < 50:
#         print("ACTION → Pinch!")

#     if angle < 90:
#         print("ACTION → Thumb bent!")