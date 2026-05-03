import cv2
import mediapipe as mp
from mediapipe.tasks import python
import pyautogui,time
import keyboard
from mediapipe.tasks.python import vision
from utils import get_angle,get_distance


# ── Path to your downloaded task file ──────────────────────────────────────
MODEL_PATH = r"D:\My Future\Project\Gen_AI\02_K.U.R.A.M.A\Version_4\Extra_tools_file\Youtube_vision_control\hand_landmarker.task"
# ── Put at top of file ──────────────────────────
pyautogui.FAILSAFE = False
pyautogui.PAUSE    = 0

last_mute_time    = 0
last_volup_time   = 0
COOLDOWN          = 1.0   # 1 second between actions
# If not in same folder, use full path:
# MODEL_PATH = r"D:\Learning\Opencv Project\Hand_gesture_control\hand_landmarker.task"

# ── Build the HandLandmarker ────────────────────────────────────────────────
base_options = python.BaseOptions(model_asset_path=MODEL_PATH)

options = vision.HandLandmarkerOptions(
    base_options=base_options,
    running_mode=vision.RunningMode.VIDEO,
    num_hands=1,
    min_hand_detection_confidence=0.5,
    min_hand_presence_confidence=0.5,
    min_tracking_confidence=0.5     
)   

detector = vision.HandLandmarker.create_from_options(options)

# ── Draw landmarks manually (no landmark_pb2 needed) ───────────────────────
HAND_CONNECTIONS = [
    (0,1),(1,2),(2,3),(3,4),         # Thumb
    (0,5),(5,6),(6,7),(7,8),         # Index
    (0,9),(9,10),(10,11),(11,12),    # Middle
    (0,13),(13,14),(14,15),(15,16),  # Ring
    (0,17),(17,18),(18,19),(19,20),  # Pinky
    (5,9),(9,13),(13,17)             # Palm
]

def draw_landmarks_on_frame(frame, detection_result):
    h, w, _ = frame.shape

    for hand_landmarks in detection_result.hand_landmarks:
        # Get pixel coordinates for all 21 points
        points = []
        for lm in hand_landmarks:
            cx, cy = int(lm.x * w), int(lm.y * h)
            points.append((cx, cy))

        # Draw connections (bones)
        for start, end in HAND_CONNECTIONS:
            cv2.line(frame, points[start], points[end], (7, 148, 230), 2)

        # Draw landmark dots
        for i, (cx, cy) in enumerate(points):
            # Fingertips are bigger (indices 4,8,12,16,20)
            radius = 8 if i in [4, 8, 12, 16, 20] else 5
            cv2.circle(frame, (cx, cy), radius, (153, 158, 153), -1)
            cv2.circle(frame, (cx, cy), radius, (255, 255, 255), 1)

    return frame

# ── Finger state detection ──────────────────────────────────────────────────
def get_finger_states(hand_landmarks):
    """Returns [thumb, index, middle, ring, pinky] True=up False=down"""
    tips = [4, 8, 12, 16, 20]
    pips = [3, 6, 10, 14, 18]

    fingers = []

    # Thumb: compare x-axis
    fingers.append(hand_landmarks[4].x < hand_landmarks[3].x)

    # Other fingers: tip y < pip y means finger is up
    for tip, pip in zip(tips[1:], pips[1:]):
        fingers.append(hand_landmarks[tip].y < hand_landmarks[pip].y)

    return fingers

# ── Sign classifier ─────────────────────────────────────────────────────────
def classify_sign(detection_result,fingers):
    thumb, index, middle, ring, pinky = fingers
    global last_mute_time, last_volup_time

    current_time = time.time()
    if detection_result.hand_landmarks:
        lm = detection_result.hand_landmarks[0]
        lm = detection_result.hand_landmarks[0]  # first hand

        # ── Wrist ───────────────────────────────────────────
        wrist           = (lm[0].x,  lm[0].y)

        # ── Thumb ───────────────────────────────────────────
        thumb_cmc       = (lm[1].x,  lm[1].y)   # thumb base
        thumb_mcp       = (lm[2].x,  lm[2].y)   # thumb knuckle
        thumb_ip        = (lm[3].x,  lm[3].y)   # thumb middle joint
        thumb_tip       = (lm[4].x,  lm[4].y)   # thumb tip

        # ── Index Finger ────────────────────────────────────
        index_mcp       = (lm[5].x,  lm[5].y)   # index base knuckle
        index_pip       = (lm[6].x,  lm[6].y)   # index first joint
        index_dip       = (lm[7].x,  lm[7].y)   # index second joint
        index_tip       = (lm[8].x,  lm[8].y)   # index tip

        # ── Middle Finger ───────────────────────────────────
        middle_mcp      = (lm[9].x,  lm[9].y)   # middle base knuckle
        middle_pip      = (lm[10].x, lm[10].y)  # middle first joint
        middle_dip      = (lm[11].x, lm[11].y)  # middle second joint
        middle_tip      = (lm[12].x, lm[12].y)  # middle tip

        # ── Ring Finger ─────────────────────────────────────
        ring_mcp        = (lm[13].x, lm[13].y)  # ring base knuckle
        ring_pip        = (lm[14].x, lm[14].y)  # ring first joint
        ring_dip        = (lm[15].x, lm[15].y)  # ring second joint
        ring_tip        = (lm[16].x, lm[16].y)  # ring tip

        # ── Pinky Finger ────────────────────────────────────
        pinky_mcp       = (lm[17].x, lm[17].y)  # pinky base knuckle
        pinky_pip       = (lm[18].x, lm[18].y)  # pinky first joint
        pinky_dip       = (lm[19].x, lm[19].y)  # pinky second joint
        pinky_tip       = (lm[20].x, lm[20].y)  # pinky tip
        
        volume_angle = get_angle(index_tip, index_pip, index_mcp)
        volume_angle2 = get_angle(thumb_tip, thumb_mcp, thumb_cmc)
        volume_length = get_distance([index_tip,thumb_tip])

        cv2.putText(frame, f"Idx Angle : {volume_angle:.1f}",  (10, h-80),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,0), 2)
        cv2.putText(frame, f"Thb Angle : {volume_angle2:.1f}", (10, h-55),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,0), 2)
        cv2.putText(frame, f"Distance  : {volume_length:.1f}", (10, h-30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,0), 2)

        if index and thumb and not middle and not ring and not pinky:
            if volume_angle>150 and volume_length > 130 and volume_angle2 > 180 :
                keyboard.press_and_release('volume up') 
                return "Volume Up"
            
            elif volume_angle>130 and volume_length < 90 and volume_length>40 :
                keyboard.press_and_release('volume down')  
                return "Volume Down"
            
            elif volume_angle>130 and volume_length < 40:
                if (current_time - last_mute_time) > COOLDOWN:
                    keyboard.press_and_release('f11')  # fast ✅
                    last_mute_time = current_time
                return "Full Screen"
            
        elif index and not thumb and not middle and not ring and not pinky: 
                if (current_time - last_mute_time) > COOLDOWN:
                        keyboard.press_and_release('volume mute')  # fast ✅
                        last_mute_time = current_time
                return "Mute"    
               
        elif index and not thumb and not middle and not ring and pinky: 
                if (current_time - last_mute_time) > COOLDOWN:
                        keyboard.press_and_release('play/pause media')  # fast ✅
                        last_mute_time = current_time
                return "play/pause media"     
              
        elif not index and not thumb and not middle and not ring and pinky: 
                if (current_time - last_mute_time) > COOLDOWN:
                        pyautogui.hotkey('shift', 'n')
                        last_mute_time = current_time
                return "Next Track"     
        
        elif index and not thumb and middle and not ring and not pinky: 
                if (current_time - last_mute_time) > COOLDOWN:
                        pyautogui.hotkey('f')
                        last_mute_time = current_time
                return "Youtube Full screen"  
           
        elif not index and thumb and not middle and not ring and not pinky: 
                if (current_time - last_mute_time) > COOLDOWN:
                        pyautogui.hotkey('left')
                        last_mute_time = current_time
                return "Backward"     


        


# ── Main loop ───────────────────────────────────────────────────────────────
# ── Main loop ───────────────────────────────────────────────────────────────
cap = cv2.VideoCapture(0)

# ── Define your own width and height ───────────────
w, h = 1280, 720
cap.set(cv2.CAP_PROP_FRAME_WIDTH,  w)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)

timestamp = 0
print("Hand Sign Detection Running — press 'q' to quit")

while True:
    ret, frame = cap.read()
    if not ret:
        print("❌ Camera not accessible!")
        break

    frame     = cv2.flip(frame, 1)
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image  = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

    timestamp        += 33
    detection_result  = detector.detect_for_video(mp_image, timestamp)

    # Draw landmarks
    if detection_result.hand_landmarks:
        frame = draw_landmarks_on_frame(frame, detection_result)

        for i, hand_landmarks in enumerate(detection_result.hand_landmarks):
            handedness = detection_result.handedness[i][0].display_name
            if handedness != "Left":    # change to "Left" if needed
                continue
            fingers    = get_finger_states(hand_landmarks)
            sign       = classify_sign(detection_result,fingers)
            handedness = detection_result.handedness[i][0].display_name

            # Background box for text
            label = f"{handedness}: {sign}"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 1, 2)
            y_pos = 45 + i * 55
            cv2.rectangle(frame, (8, y_pos - th - 8), (8 + tw + 8, y_pos + 5), (0, 0, 0), -1)
            cv2.putText(frame, label, (12, y_pos),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2, cv2.LINE_AA)
    else:
        cv2.putText(frame, "No hand detected", (10, 45),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2, cv2.LINE_AA)

    # FPS display
    cv2.putText(frame, "Press Q to quit", (10, frame.shape[0] - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)

    cv2.imshow("Hand Sign Detection", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
detector.close()
print("Done!")