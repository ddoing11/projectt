import cv2

def test_motion_detection():
    cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("🚫 웹캠을 열 수 없습니다.")
        return

    subtractor = cv2.createBackgroundSubtractorMOG2()

    while True:
        ret, frame = cap.read()
        if not ret:
            print("❌ 프레임을 읽지 못했습니다.")
            break

        fgmask = subtractor.apply(frame)
        contours, _ = cv2.findContours(fgmask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for contour in contours:
            area = cv2.contourArea(contour)
            if area > 300:
                print(f"👤 감지된 움직임 (면적: {area})")
                x, y, w, h = cv2.boundingRect(contour)
                cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)

        cv2.imshow("움직임 감지 테스트", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    test_motion_detection()
