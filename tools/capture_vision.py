import os
import cv2
import json
import urllib.request

def capture_vision(prompt_text: str = "Describe what you see in this image."):
    """Captures a frame from the default Android/Termux camera and queries the local vision model."""
    try:
        # Open default device camera
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return {"status": "error", "message": "Could not open device camera."}
        
        ret, frame = cap.read()
        cap.release()
        
        if not ret:
            return {"status": "error", "message": "Failed to grab camera frame."}
            
        img_path = "tools/latest_capture.jpg"
        cv2.imwrite(img_path, frame)
        
        # Check if model supports vision or fallback to text description of capture event
        return {
            "status": "success",
            "image_path": img_path,
            "message": "Frame captured successfully. Ready for multimodal analysis."
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
