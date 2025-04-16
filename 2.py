import requests
import cv2
import numpy as np
from PIL import Image
import io
import json
import base64
import sys
from collections import defaultdict
from dotenv import load_dotenv
import os
import tempfile
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# Tải biến môi trường
load_dotenv()

# Khởi tạo FastAPI
app = FastAPI(title="CAPTCHA Analysis API")

# Thêm CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Cho phép tất cả các nguồn gốc
    allow_credentials=True,
    allow_methods=["*"],  # Cho phép tất cả các phương thức
    allow_headers=["*"],  # Cho phép tất cả các header
)

# Cấu hình API Roboflow
PROJECT_ID = "tk-3d-cq49s-1j4v5"  # Project ID từ data.yaml
VERSION = "1"  # Version từ data.yaml  
API_KEY = os.getenv("ROBOFLOW_API_KEY")  
# API endpoint configuration
BASE_URL = "https://detect.roboflow.com"

# Kích thước các khối UI
FULL_BROWSER_WIDTH = 502  # Chiều rộng của toàn bộ khối
FULL_BROWSER_HEIGHT = 606  # Chiều cao của toàn bộ khối
CAPTCHA_CONTAINER_WIDTH = 312  # Chiều rộng của khối chứa CAPTCHA, tiêu đề, xác nhận, reload
CAPTCHA_CONTAINER_HEIGHT = 307  # Chiều cao của khối chứa CAPTCHA, tiêu đề, xác nhận, reload
TITLE_WIDTH = 272  # Chiều rộng của khối tiêu đề
TITLE_HEIGHT = 42  # Chiều cao của khối tiêu đề
CONFIRM_WIDTH = 288  # Chiều rộng của nút xác nhận
CONFIRM_HEIGHT = 40  # Chiều cao của nút xác nhận
RELOAD_WIDTH = 288  # Chiều rộng của nút reload
RELOAD_HEIGHT = 28  # Chiều cao của nút reload
CAPTCHA_IMAGE_WIDTH = 288  # Chiều rộng của ảnh CAPTCHA
CAPTCHA_IMAGE_HEIGHT = 179  # Chiều cao của ảnh CAPTCHA

# Tính vị trí các khối dựa trên kích thước
CAPTCHA_CONTAINER_X = (FULL_BROWSER_WIDTH - CAPTCHA_CONTAINER_WIDTH) // 2  # Vị trí X của khối chứa CAPTCHA
CAPTCHA_CONTAINER_Y = 150  # Ước tính vị trí Y của khối chứa CAPTCHA

TITLE_X = CAPTCHA_CONTAINER_X + (CAPTCHA_CONTAINER_WIDTH - TITLE_WIDTH) // 2  # Vị trí X của tiêu đề
TITLE_Y = CAPTCHA_CONTAINER_Y  # Vị trí Y của tiêu đề

CAPTCHA_IMAGE_X = CAPTCHA_CONTAINER_X + (CAPTCHA_CONTAINER_WIDTH - CAPTCHA_IMAGE_WIDTH) // 2  # Vị trí X của ảnh CAPTCHA
CAPTCHA_IMAGE_Y = TITLE_Y + TITLE_HEIGHT + 5  # Vị trí Y của ảnh CAPTCHA

CONFIRM_X = CAPTCHA_CONTAINER_X + (CAPTCHA_CONTAINER_WIDTH - CONFIRM_WIDTH) // 2  # Vị trí X của nút xác nhận
CONFIRM_Y = CAPTCHA_IMAGE_Y + CAPTCHA_IMAGE_HEIGHT + 5  # Vị trí Y của nút xác nhận

RELOAD_X = CAPTCHA_CONTAINER_X + (CAPTCHA_CONTAINER_WIDTH - RELOAD_WIDTH) // 2  # Vị trí X của nút reload
RELOAD_Y = CONFIRM_Y + CONFIRM_HEIGHT + 5  # Vị trí Y của nút reload

def convert_coordinates(image_coord, image_size, captcha_offset=(CAPTCHA_IMAGE_X, CAPTCHA_IMAGE_Y)):
    """
    Chuyển đổi tọa độ từ ảnh sang tọa độ trình duyệt
    
    :param image_coord: Tuple tọa độ (x, y) trên ảnh gốc
    :param image_size: Tuple kích thước (width, height) ảnh gốc
    :param captcha_offset: Tuple offset (x, y) của khung CAPTCHA so với top-left của khung ngoài
    :return: Tuple tọa độ (x, y) trên trình duyệt
    """
    # Xác định tỷ lệ giữa kích thước ảnh gốc và kích thước khung CAPTCHA
    x_ratio = CAPTCHA_IMAGE_WIDTH / image_size[0]
    y_ratio = CAPTCHA_IMAGE_HEIGHT / image_size[1]
    
    # Chuyển đổi tọa độ dựa trên tỷ lệ của khung CAPTCHA
    captcha_x = round(image_coord[0] * x_ratio)
    captcha_y = round(image_coord[1] * y_ratio)
    
    # Thêm offset của khung CAPTCHA để có tọa độ trên trình duyệt
    browser_x = captcha_offset[0] + captcha_x
    browser_y = captcha_offset[1] + captcha_y
    
    # Giới hạn tọa độ trong phạm vi của khung ngoài
    browser_x = min(max(0, browser_x), FULL_BROWSER_WIDTH)
    browser_y = min(max(0, browser_y), FULL_BROWSER_HEIGHT)
    
    return (browser_x, browser_y)

def load_image(image_path):
    if image_path.startswith(('http://', 'https://')):
        # Xử lý URL
        response = requests.get(image_path)
        if response.status_code == 200:
            return Image.open(io.BytesIO(response.content))
        else:
            raise Exception(f"Không thể tải ảnh từ URL, mã trạng thái: {response.status_code}")
    else:
        # Xử lý đường dẫn cục bộ
        return Image.open(image_path)

def analyze_image_with_roboflow(image_path):
    # URL của API Inference Roboflow
    url = f"{BASE_URL}/{PROJECT_ID}/{VERSION}"
    
    try:
        # Đọc file ảnh và mã hóa base64
        with open(image_path, "rb") as image_file:
            encoded_image = base64.b64encode(image_file.read()).decode('utf-8')
        
        # Chuẩn bị payload
        payload = encoded_image
        
        # Headers
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Authorization': f'Bearer {API_KEY}'
        }
        
        # Gửi request
        try:
            response = requests.post(
                url, 
                params={'api_key': API_KEY},
                data=payload,
                headers=headers
            )
            
            # Kiểm tra phản hồi
            if response.status_code == 200:
                return response.json()
            else:
                raise Exception(f"Lỗi API Roboflow: {response.status_code}, {response.text}")
        
        except requests.exceptions.RequestException as e:
            raise Exception(f"Lỗi kết nối: {e}")
            
    except Exception as e:
        raise Exception(f"Lỗi khi xử lý file ảnh: {e}")

def process_image(image_path, captcha_offset_x=None, captcha_offset_y=None):
    try:
        # Sử dụng giá trị tính toán từ biến toàn cục nếu không có offset được chỉ định
        if captcha_offset_x is None:
            captcha_offset_x = CAPTCHA_IMAGE_X
        if captcha_offset_y is None:
            captcha_offset_y = CAPTCHA_IMAGE_Y
            
        # Tải ảnh
        image = load_image(image_path)
        
        # Phân tích ảnh
        results = analyze_image_with_roboflow(image_path)
        
        # Đảm bảo các trường cơ bản tồn tại
        if "image" not in results:
            results["image"] = {"width": 0, "height": 0}
        if "predictions" not in results:
            results["predictions"] = []
        
        # Sắp xếp các dự đoán theo tin cậy giảm dần
        sorted_predictions = sorted(
            results.get("predictions", []),
            key=lambda x: x.get("confidence", 0),
            reverse=True
        )
        
        # Nhóm các ký tự theo class
        class_groups = defaultdict(list)
        for prediction in sorted_predictions:
            # Đảm bảo các thuộc tính bắt buộc tồn tại trong mỗi prediction
            if "class" not in prediction:
                prediction["class"] = "unknown"
            
            class_name = prediction.get("class", "")
            class_groups[class_name].append(prediction)
        
        # Xác định các class trùng nhau (có nhiều hơn 1 ký tự)
        duplicate_classes = {}
        duplicate_list = []
        
        for class_name, predictions in class_groups.items():
            if len(predictions) > 1:
                # Sắp xếp theo confidence giảm dần
                sorted_class_predictions = sorted(
                    predictions,
                    key=lambda x: x.get("confidence", 0),
                    reverse=True
                )
                
                # Chuyển đổi tọa độ sang số nguyên và sang tọa độ trình duyệt
                standardized_predictions = []
                for pred in sorted_class_predictions:
                    # Tọa độ gốc
                    original_coord = (
                        int(pred.get("x", 0.0)), 
                        int(pred.get("y", 0.0))
                    )
                    
                    # Kích thước ảnh gốc
                    image_size = (
                        int(results.get("image", {}).get("width", 0)),
                        int(results.get("image", {}).get("height", 0))
                    )
                    
                    # Offset của khung CAPTCHA
                    captcha_offset = (captcha_offset_x, captcha_offset_y)
                    
                    # Chuyển đổi tọa độ
                    browser_coord = convert_coordinates(
                        original_coord, 
                        image_size, 
                        captcha_offset
                    )
                    
                    standardized_pred = {
                        "browser_x": browser_coord[0],
                        "browser_y": browser_coord[1],
                        "class": pred.get("class", ""),
                        "class_id": int(pred.get("class_id", 0)),
                        "confidence": float(pred.get("confidence", 0.0)),
                        "detection_id": pred.get("detection_id", ""),
                        "height": int(pred.get("height", 0.0)),
                        "width": int(pred.get("width", 0.0)),
                        "x": int(pred.get("x", 0.0)),
                        "y": int(pred.get("y", 0.0))
                    }
                    standardized_predictions.append(standardized_pred)
                    duplicate_list.append(standardized_pred)
                
                duplicate_classes[class_name] = {
                    "count": len(predictions),
                    "details": standardized_predictions
                }
        
        # Chuẩn bị tất cả dự đoán với tọa độ số nguyên và tọa độ trình duyệt
        all_integer_predictions = []
        for pred in sorted_predictions:
            # Tọa độ gốc
            original_coord = (
                int(pred.get("x", 0.0)), 
                int(pred.get("y", 0.0))
            )
            
            # Kích thước ảnh gốc
            image_size = (
                int(results.get("image", {}).get("width", 0)),
                int(results.get("image", {}).get("height", 0))
            )
            
            # Offset của khung CAPTCHA
            captcha_offset = (captcha_offset_x, captcha_offset_y)
            
            # Chuyển đổi tọa độ
            browser_coord = convert_coordinates(
                original_coord, 
                image_size, 
                captcha_offset
            )
            
            integer_pred = {
                "browser_x": browser_coord[0],
                "browser_y": browser_coord[1],
                "class": pred.get("class", ""),
                "class_id": int(pred.get("class_id", 0)),
                "confidence": float(pred.get("confidence", 0.0)),
                "detection_id": pred.get("detection_id", ""),
                "height": int(pred.get("height", 0.0)),
                "width": int(pred.get("width", 0.0)),
                "x": int(pred.get("x", 0.0)),
                "y": int(pred.get("y", 0.0))
            }
            all_integer_predictions.append(integer_pred)
        
        # Chuẩn bị kết quả JSON
        enhanced_output = {
            "all_predictions": all_integer_predictions,
            "coordinate_transform": {
                "x_ratio": round(CAPTCHA_IMAGE_WIDTH / results.get("image", {}).get("width", 1), 4),
                "y_ratio": round(CAPTCHA_IMAGE_HEIGHT / results.get("image", {}).get("height", 1), 4),
                "offset_x": captcha_offset_x,
                "offset_y": captcha_offset_y
            },
            "duplicate_characters": duplicate_classes,
            "duplicate_count": len(duplicate_classes),
            "duplicates": duplicate_list,
            "image": {
                "captcha_height": CAPTCHA_IMAGE_HEIGHT,
                "captcha_width": CAPTCHA_IMAGE_WIDTH,
                "full_browser_height": FULL_BROWSER_HEIGHT,
                "full_browser_width": FULL_BROWSER_WIDTH,
                "height": int(results.get("image", {}).get("height", 0)),
                "width": int(results.get("image", {}).get("width", 0)),
                "captcha_offset_x": captcha_offset_x,
                "captcha_offset_y": captcha_offset_y
            },
            "ui_layout": {
                "captcha_container": {
                    "width": CAPTCHA_CONTAINER_WIDTH,
                    "height": CAPTCHA_CONTAINER_HEIGHT,
                    "x": CAPTCHA_CONTAINER_X,
                    "y": CAPTCHA_CONTAINER_Y
                },
                "title": {
                    "width": TITLE_WIDTH,
                    "height": TITLE_HEIGHT,
                    "x": TITLE_X,
                    "y": TITLE_Y
                },
                "captcha_image": {
                    "width": CAPTCHA_IMAGE_WIDTH,
                    "height": CAPTCHA_IMAGE_HEIGHT,
                    "x": CAPTCHA_IMAGE_X,
                    "y": CAPTCHA_IMAGE_Y
                },
                "confirm_button": {
                    "width": CONFIRM_WIDTH,
                    "height": CONFIRM_HEIGHT,
                    "x": CONFIRM_X,
                    "y": CONFIRM_Y
                },
                "reload_button": {
                    "width": RELOAD_WIDTH,
                    "height": RELOAD_HEIGHT,
                    "x": RELOAD_X,
                    "y": RELOAD_Y
                }
            },
            "inference_id": results.get("inference_id", ""),
            "time": results.get("time", 0),
            "total_detected": len(results.get("predictions", [])),
            "unique_characters": len(class_groups)
        }
        
        return enhanced_output
    
    except Exception as e:
        # In lỗi dưới dạng JSON
        error_output = {
            "lỗi": str(e),
            "chi_tiết": "Lỗi trong quá trình xử lý ảnh",
            "duplicate_characters": {},
            "duplicates": [],
            "all_predictions": []
        }
        return error_output

# Root endpoint
@app.get("/")
async def root():
    return {"message": "Welcome to CAPTCHA Analysis API", "version": "1.0.0"}

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "ok"}

# API endpoint để xử lý ảnh từ file upload
@app.post("/process")
async def process_image_endpoint(
    file: UploadFile = File(...),
    captcha_offset_x: int = Form(None),
    captcha_offset_y: int = Form(None)
):
    try:
        # Tạo file tạm để lưu file upload
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temp_file:
            temp_file.write(await file.read())
            temp_file_path = temp_file.name
        
        # Xử lý ảnh
        result = process_image(temp_file_path, captcha_offset_x, captcha_offset_y)
        
        # Xóa file tạm sau khi xử lý
        os.unlink(temp_file_path)
        
        return result
    
    except Exception as e:
        # Xử lý lỗi
        return JSONResponse(
            status_code=500,
            content={
                "lỗi": str(e),
                "chi_tiết": "Lỗi trong quá trình xử lý ảnh",
                "duplicate_characters": {},
                "duplicates": [],
                "all_predictions": []
            }
        )

# API endpoint để xử lý ảnh từ URL
@app.post("/process_url")
async def process_image_url(
    image_url: str = Form(...),
    captcha_offset_x: int = Form(None),
    captcha_offset_y: int = Form(None)
):
    try:
        # Tải ảnh từ URL và lưu vào file tạm
        response = requests.get(image_url)
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Không thể tải ảnh từ URL, mã trạng thái: {response.status_code}")
        
        # Tạo file tạm để lưu ảnh
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temp_file:
            temp_file.write(response.content)
            temp_file_path = temp_file.name
        
        # Xử lý ảnh
        result = process_image(temp_file_path, captcha_offset_x, captcha_offset_y)
        
        # Xóa file tạm sau khi xử lý
        os.unlink(temp_file_path)
        
        return result
    
    except Exception as e:
        # Xử lý lỗi
        return JSONResponse(
            status_code=500,
            content={
                "lỗi": str(e),
                "chi_tiết": "Lỗi trong quá trình xử lý ảnh từ URL",
                "duplicate_characters": {},
                "duplicates": [],
                "all_predictions": []
            }
        )