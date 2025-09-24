import webview
import pygame
import os

pygame.mixer.init()


current_dir = os.path.dirname(os.path.abspath(__file__))
sound_path = os.path.join(current_dir, '..', 'Assets', 'startup_sound.wav')

try:
    pygame.mixer.music.load(sound_path)
    pygame.mixer.music.play()
except Exception as e:
    print(f"Error playing sound: {e}")


window = webview.create_window('My App', 'https://example.com', width=800, height=600)
webview.start()