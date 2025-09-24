import pyautogui
import cv2
from cvzone.HandTrackingModule import HandDetector
import numpy as np
import time
import os
import pygetwindow as gw



def gestureControl():
    
    
    
    ppt_folder = os.path.join("D:", "airglide", "packages", "pptfile")
    script_dir = os.path.dirname(os.path.realpath(__file__))
    ppt_folder = os.path.join(script_dir, "pptfile")

    # Find the .pptx file dynamically
    ppt_files = [f for f in os.listdir(ppt_folder) if f.endswith(".pptx")]

    if ppt_files:
        ppt_file_path = os.path.join(ppt_folder, ppt_files[0])  # Get the first .pptx file
    else:
        print("Error: No .pptx file found in the 'pptfile' directory.")
        exit()

    # Open the PowerPoint file
    if os.path.exists(ppt_file_path):
        print(f"Opening PowerPoint file: {ppt_file_path}")
        os.startfile(ppt_file_path)
    else:
        print(f"Error: PowerPoint file not found at {ppt_file_path}")
        exit()

    # Wait for PowerPoint to open
    time.sleep(5)

    pyautogui.press('f5')


    time.sleep(2)

  
    width, height = 1280, 720
    folderPath = os.path.join(script_dir, "slides")

    imgNumber = 0
    gestureThreshhold = 300
    buttonDelay = 30
    buttonPress = False
    buttonCounter = 0
    heightSS, widthSS = int(120 * 1.2), int(213 * 1)

    cap = cv2.VideoCapture(0)
    cap.set(3, width)
    cap.set(4, height)

    pathImages = sorted(os.listdir(folderPath), key=len)
    print(pathImages)

    detector = HandDetector(detectionCon=0.8, maxHands=1)

    while True:
        if buttonPress:
            buttonCounter += 1
            if buttonCounter > buttonDelay:
                buttonCounter = 0
                buttonPress = False
        
        success, img = cap.read()
        img = cv2.flip(img, 1)
        pathFullImage = os.path.join(folderPath, pathImages[imgNumber])
        imgCurrent = cv2.imread(pathFullImage)

        hands, img = detector.findHands(img, flipType=False)

        if hands and not buttonPress:
            hand = hands[0]
            fingers = detector.fingersUp(hand)
            
            cx, cy = hand['center']
            lmList = hand["lmList"]
            minY, maxY = 100, 550

            if lmList and len(lmList) > 8:
                ix, iy = lmList[8][:2]
                lastX, lastY = ix, iy
                screenw, screenh = pyautogui.size()
                mappedX = int((ix / width) * screenw)
                mappedY = int(((iy - minY) / (maxY - minY)) * screenh)
                indexFinger = (mappedX, mappedY)
            else:
                ix, iy = lastX, lastY
                indexFinger = None

            if indexFinger is not None:
                cv2.circle(imgCurrent, indexFinger, 10, (83, 189, 235), cv2.FILLED)

            # Gesture - Left Swipe (Previous Slide)
            if fingers == [0,0,0,0,0]:
                print("Left Swipe - Previous Slide")
                if imgNumber > 0:
                    buttonPress = True
                    imgNumber -= 1
                    pyautogui.press('left')

            # Gesture - Right Swipe (Next Slide)
            if fingers == [1, 0,0,0,1]:
                print(f"Right Swipe - Next Slide {fingers}")
                if imgNumber < len(pathImages) - 1:
                    buttonPress = True
                    imgNumber += 1
                    pyautogui.press('right')
            
            # Gesture - pen 4 finger up
            if fingers == [1, 1, 1,1,1]:
                print("pen activatedcloses")
                windows = gw.getWindowsWithTitle("PowerPoint")
                for window in windows:
                    if window.isMaximized:  # If the PowerPoint window is maximized
                        buttonPress=True
                        print("PowerPoint is in slideshow mode. Activating Pen Tool.")
                        pyautogui.hotkey('ctrl', 'p')
                        break
            
            #escape- close fist     
     
            if fingers == [1, 0, 0,0,0]:
                
                buttonPress = True
                pyautogui.press("esc")
              
            
            # gesture= open fist   start from begining
           
            if fingers == [0,1,1,1,1]:
                
                buttonPress = True
                pyautogui.press("f5")  
               
            
            if fingers == [0, 1, 0, 0, 0]:
                
                buttonPress = True
                for i in range(0,9):
                    pyautogui.press("volumeup")
                pyautogui.press("volumeup")    
            
            if fingers == [0, 1, 1, 0, 0]:
                
                buttonPress = True
                for i in range(0,9):
                    pyautogui.press("volumedown")
                pyautogui.press("volumedown")        
                    
                    
                      


        
        imgSmall = cv2.resize(img, (widthSS, heightSS))
        h, w, _ = imgCurrent.shape
        imgCurrent[0:heightSS, w - widthSS:w] = imgSmall
        
        key = cv2.waitKey(1)
        if key == ord('q'):
            break
