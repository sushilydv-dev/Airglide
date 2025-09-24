import cv2

# Make sure this is your correct IP from the IP Webcam app
ipcam_url = "http://192.168.131.52:8080/video"

# Start the video stream
cap = cv2.VideoCapture(ipcam_url)

if not cap.isOpened():
    print("[ERROR] Cannot open video stream. Check the URL or Wi-Fi connection.")
    exit()

while True:
    ret, frame = cap.read()
    if not ret:
        print("[ERROR] Failed to grab frame")
        break

    frame = cv2.resize(frame, (1200,720))  # Resize to reduce load
    cv2.imshow("Phone Cam Feed", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
