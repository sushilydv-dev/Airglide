import cv2
import pyautogui
import numpy as np
import mediapipe as mp

mouse_running = False  


def is_ipcam_available(url, timeout=3):
    cap = cv2.VideoCapture(url)
    if not cap.isOpened():
        return False

    for _ in range(timeout * 10):  
        ret, frame = cap.read()
        if ret:
            cap.release()
            return True
        cv2.waitKey(100)
    cap.release()
    return False

def get_camera_source():
    phone_url = "http://192.168.131.52:8080/video"
    print("Checking avalable IP cam...")
    if is_ipcam_available(phone_url):
        print("IP cam available for usage")
        return phone_url
    else:
        print("[⚠️] IP cam not available. Falling back to laptop cam.")
        return 0  

def virtual_mouse_loop(cam_choice='lapcam'):
    if cam_choice == 'phonecam':
        cam_url = phonecam()
    else:
        cam_url = lapcam()
    
    global mouse_running
    
    cap = cv2.VideoCapture(cam_url)
    wScr, hScr = pyautogui.size()
    frameR = 100
    smoothening = 7
    plocX, plocY = 0, 0
    clocX, clocY = 0, 0

    mpHands = mp.solutions.hands
    hands = mpHands.Hands(max_num_hands=1)
    mpDraw = mp.solutions.drawing_utils

    def fingers_up(lmList):
        tipIds = [4, 8, 12, 16, 20]
        fingers = []
        fingers.append(1 if lmList[tipIds[0]][1] > lmList[tipIds[0] - 1][1] else 0)
        for id in range(1, 5):
            fingers.append(1 if lmList[tipIds[id]][2] < lmList[tipIds[id] - 2][2] else 0)
        return fingers

    

    while mouse_running:   # Run only when mouse_running is True
        success, img = cap.read()
        if not success:
            break
        img = cv2.flip(img, 1)

        hCam, wCam, _ = img.shape

        imgRGB = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        imgRGB = np.array(imgRGB, dtype=np.uint8)
        results = hands.process(imgRGB)

        lmList = []
        if results.multi_hand_landmarks:
            for handLms in results.multi_hand_landmarks:
                mpDraw.draw_landmarks(img, handLms, mpHands.HAND_CONNECTIONS)
                for id, lm in enumerate(handLms.landmark):
                    px, py = int(lm.x * wCam), int(lm.y * hCam)
                    lmList.append([id, px, py])

        if len(lmList) >= 13:
            x1, y1 = lmList[8][1:]
            x2, y2 = lmList[12][1:]
            fingers = fingers_up(lmList)

            if fingers[1] == 1 and fingers[2] == 0:
                x3 = np.interp(x1, (frameR, wCam - frameR), (wScr, 0))
                y3 = np.interp(y1, (frameR, hCam - frameR), (0, hScr))
                clocX = plocX + (x3 - plocX) / smoothening
                clocY = plocY + (y3 - plocY) / smoothening
                pyautogui.moveTo(wScr - clocX, clocY)  
                plocX, plocY = clocX, clocY
                cv2.circle(img, (x1, y1), 15, (255, 0, 255), cv2.FILLED)

            if fingers[1] == 1 and fingers[2] == 1:
                length = np.hypot(x2 - x1, y2 - y1)
                if length < 40:
                    cv2.circle(img, ((x1 + x2) // 2, (y1 + y2) // 2), 15, (0, 255, 0), cv2.FILLED)
                    pyautogui.click()

        cv2.rectangle(img, (frameR, frameR), (wCam - frameR, hCam - frameR), (255, 0, 255), 2)
    
        if cv2.waitKey(1) == ord('q'):
            mouse_running = False
    
    cap.release()
    cv2.destroyAllWindows()


def start_virtual_mouse():
    global mouse_running
    if not mouse_running:
        mouse_running = True
        import threading
        threading.Thread(target=virtual_mouse_loop, daemon=True).start()

def stopVmouse():
    global mouse_running
    mouse_running = False

def lapcam():
    return 0
def phonecam():
    return  "http://192.168.131.52:8080/video"
