import webview
import os
import pygame
import threading
from packages.ppt_presentation import fetch_and_store_pptx
import cv2
import base64
import time
from packages.gesture import gestureControl
from packages.virtual_mouse import start_virtual_mouse
from packages.virtual_mouse import stopVmouse

pygame.init()
pygame.mixer.init()


def btn_click_sound():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    sound_path = os.path.join(current_dir, '..', 'Assets', 'button_click.wav')

    # Play the startup sound asynchronously
    try:
        pygame.mixer.music.load(sound_path)
        pygame.mixer.music.play()
            
    except Exception as e:
        print(f"Error playing sound: {e}")

class Api:
    
    def minimize(self):
        
        webview.windows[0].minimize()

    def close(self):
        webview.windows[0].destroy()

    def move_window(self, x, y):
        window = webview.windows[0]
        window.move(window.x + x, window.y + y)

    class APIbot:
        def minimizebot(self):
            webview.windows[1].minimize()

        def closebot(self):
            webview.windows[1].destroy()

        def move_windowbot(self, x, y):
            window = webview.windows[1]
            window.move(window.x + x, window.y + y)

    def fetch_pptx(self):
        btn_click_sound()
        fetch_and_store_pptx()
        
        

    def presentor(self):
        btn_click_sound()
        gestureControl()

    def virtual_mouse(self):
        btn_click_sound()
        start_virtual_mouse()

    def stop_virtual_mouse(self):
        btn_click_sound()
        stopVmouse()

    def destroycam(self):
        destroyCam()

    def startcamera(self):
        startcam()
    
   
               

    def openChatBotWindow(self):
        btn_click_sound()
        htmlPath = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "views", "chatbot.html"))
        api = Api.APIbot()
        window = webview.create_window(
            "Airglide chatbot",
            url=f"file:///{htmlPath}",
            js_api=api,
            frameless=False,
            width=370,
            height=500,
            resizable=False
        )
    def notification_bar():
        htmlPath = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "views", "feedback.html"))
        api = Api.APIbot()
        window = webview.create_window(
            "Airglide chatbot",
            url=f"file:///{htmlPath}",
            js_api=api,
            frameless=False,
            width=40,
            height=40,
            resizable=False
        )
        




camera_running = False
cap = None

def camera_stream():
    global cap, camera_running
    
    cap = cv2.VideoCapture(0)
    cap.set(3, 640)
    cap.set(4, 480)

    camera_running = True
    while camera_running:
        success, frame = cap.read()
        if not success:
            continue
        frame = cv2.flip(frame, 1)
        _, buffer = cv2.imencode('.jpg', frame)
        frame_base64 = base64.b64encode(buffer).decode('utf-8')

        try:
            webview.windows[0].evaluate_js(f"cameraFrame('{frame_base64}')")
        except Exception as e:
            print(f"Camera Update Error: {e}")

        time.sleep(0.03)  # FPS is 30
    if cap is not None:
        cap.release()
        cap = None
    print("u stopped the cam")

def destroyCam():
    global camera_running
    camera_running = False

def startcam():
    global camera_running
    if not camera_running:
        camera_stream()


def startGui():
    # Get the absolute path to the startup_sound.mp3 file
    current_dir = os.path.dirname(os.path.abspath(__file__))
    sound_path = os.path.join(current_dir, '..', 'Assets', 'startup_sound.wav')

    # Play the startup sound asynchronously
    try:
        pygame.mixer.music.load(sound_path)
        pygame.mixer.music.play()
    except Exception as e:
        print(f"Error playing sound: {e}")

    htmlPath = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "views", "index.html"))
    api = Api()
    window = webview.create_window(
        "Airglide",
        url=f"file:///{htmlPath}",
        js_api=api,
        frameless=True,
        width=370,
        height=300,
        resizable=False
    )

    webview.start()
    

startGui()
