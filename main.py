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
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Depends
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from io import BytesIO
from typing import Optional
from pydantic import BaseModel
import logging
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("api.log")
    ]
)
logger = logging.getLogger("captcha-api")

# Import API key management at the top
from apikey_manager import setup_api_key_management, add_admin_page, get_api_key

# Tải biến môi trường
load_dotenv()

# Pydantic model for JSON input
class ImageBase64Request(BaseModel):
    image_base64: str
    captcha_offset_x: Optional[int] = None
    captcha_offset_y: Optional[int] = None

# Khởi tạo FastAPI - chỉ một lần duy nhất
app = FastAPI(
    title="CAPTCHA Analysis API",
    description="API for analyzing CAPTCHA images and detecting duplicate characters",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Thêm CORS middleware with more restrictive settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("ALLOWED_ORIGINS", "*").split(","),  # Ideally, specify exact domains
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],  # Restrict to necessary methods
    allow_headers=["*"],  # You might want to restrict this in production
)

# Set up API key management
setup_api_key_management(app)

# Add admin page
add_admin_page(app)

# Cấu hình API Roboflow
PROJECT_ID = os.environ.get("PROJECT_ID", "tk-3d-cq49s-1j4v5")  # Project ID from environment or default
VERSION = os.environ.get("VERSION", "1")  # Version from environment or default
# Get API key from environment or default
API_KEY = os.environ.get("ROBOFLOW_API_KEY", "D0z8HBtVSIXIYX0bKrUR")

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
            # Chuyển ảnh sang RGB và nén JPEG để giảm kích thước
            img = Image.open(image_file)
            buffered = io.BytesIO()
            img.convert('RGB').save(buffered, format="JPEG", quality=85)
            encoded_image = base64.b64encode(buffered.getvalue()).decode('utf-8')
        
        # Gửi request với timeout và retry logic
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                response = requests.post(
                    url, 
                    data=encoded_image,
                    params={
                        'api_key': API_KEY
                    },
                    headers={
                        'Content-Type': 'application/x-www-form-urlencoded'
                    },
                    timeout=15  # Increased timeout to 15 seconds
                )
                
                # Kiểm tra phản hồi
                if response.status_code == 200:
                    return response.json()
                else:
                    logger.error(f"Roboflow API Error: {response.status_code}, {response.text}")
                    raise Exception(f"Lỗi API Roboflow: {response.status_code}, {response.text}")
            
            except requests.exceptions.Timeout:
                retry_count += 1
                logger.warning(f"Timeout connecting to Roboflow API. Retry {retry_count}/{max_retries}")
                if retry_count >= max_retries:
                    raise Exception("Không thể kết nối đến Roboflow API sau nhiều lần thử")
            
            except requests.exceptions.RequestException as e:
                logger.error(f"Request error: {str(e)}")
                raise Exception(f"Lỗi kết nối: {e}")
            
    except Exception as e:
        logger.error(f"Error processing image: {str(e)}")
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
        # Log the error
        logger.error(f"Error processing image: {str(e)}")
        
        # Return the error as JSON
        error_output = {
            "error": str(e),
            "details": "Lỗi trong quá trình xử lý ảnh",
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
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

# API endpoint để xử lý ảnh từ file upload
@app.post("/process")
async def process_image_endpoint(
    file: UploadFile = File(...),
    captcha_offset_x: int = Form(None),
    captcha_offset_y: int = Form(None)
):
    try:
        # Log the request
        logger.info(f"Processing image: {file.filename}, offsets: ({captcha_offset_x}, {captcha_offset_y})")
        
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
        # Log the error
        logger.error(f"Error in process_image_endpoint: {str(e)}")
        
        # Xử lý lỗi
        return JSONResponse(
            status_code=500,
            content={
                "error": str(e),
                "details": "Lỗi trong quá trình xử lý ảnh",
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
        # Log the request
        logger.info(f"Processing image from URL: {image_url}")
        
        # Tải ảnh từ URL và lưu vào file tạm
        response = requests.get(image_url, timeout=10)
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
        # Log the error
        logger.error(f"Error in process_image_url: {str(e)}")
        
        # Xử lý lỗi
        return JSONResponse(
            status_code=500,
            content={
                "error": str(e),
                "details": "Lỗi trong quá trình xử lý ảnh từ URL",
                "duplicate_characters": {},
                "duplicates": [],
                "all_predictions": []
            }
        )

# Cải tiến: API endpoint để xử lý ảnh từ base64
@app.post("/process_base64")
async def process_image_base64(request: Request):
    try:
        # Kiểm tra xem request có phải là JSON hay không
        content_type = request.headers.get("content-type", "").lower()
        
        # Xử lý request dạng JSON
        if "application/json" in content_type:
            try:
                json_data = await request.json()
                image_base64 = json_data.get("image_base64")
                captcha_offset_x = json_data.get("captcha_offset_x")
                captcha_offset_y = json_data.get("captcha_offset_y")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Lỗi khi đọc dữ liệu JSON: {str(e)}")
        # Xử lý request dạng Form
        else:
            form_data = await request.form()
            image_base64 = form_data.get("image_base64")
            
            # Chuyển đổi offset sang số nguyên nếu có
            captcha_offset_x = form_data.get("captcha_offset_x")
            if captcha_offset_x is not None:
                try:
                    captcha_offset_x = int(captcha_offset_x)
                except ValueError:
                    captcha_offset_x = None
                    
            captcha_offset_y = form_data.get("captcha_offset_y")
            if captcha_offset_y is not None:
                try:
                    captcha_offset_y = int(captcha_offset_y)
                except ValueError:
                    captcha_offset_y = None
        
        # Kiểm tra xem có dữ liệu base64 hay không
        if not image_base64:
            raise HTTPException(status_code=422, detail="Missing required field: image_base64")
        
        # Log the request (truncated for privacy)
        logger.info(f"Processing base64 image, length: {len(image_base64) if image_base64 else 0}")
        
        # Giải mã base64 thành dữ liệu nhị phân
        try:
            # Xử lý trường hợp có tiền tố "data:image/..."
            if "base64," in image_base64:
                image_base64 = image_base64.split("base64,")[1]
            
            image_data = base64.b64decode(image_base64)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Không thể giải mã base64: {str(e)}")
        
        # Tạo file tạm để lưu ảnh
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temp_file:
            temp_file.write(image_data)
            temp_file_path = temp_file.name
        
        # Xử lý ảnh
        result = process_image(temp_file_path, captcha_offset_x, captcha_offset_y)
        
        # Xóa file tạm sau khi xử lý
        os.unlink(temp_file_path)
        
        return result
    
    except HTTPException as e:
        # Log the error
        logger.error(f"HTTP Exception in process_image_base64: {e.detail}")
        
        # Chuyển tiếp lỗi HTTP
        return JSONResponse(
            status_code=e.status_code,
            content={
                "error": e.detail,
                "details": "Lỗi trong quá trình xử lý request",
                "duplicate_characters": {},
                "duplicates": [],
                "all_predictions": []
            }
        )
    except Exception as e:
        # Log the error
        logger.error(f"Error in process_image_base64: {str(e)}")
        
        # Xử lý lỗi khác
        return JSONResponse(
            status_code=500,
            content={
                "error": str(e),
                "details": "Lỗi trong quá trình xử lý ảnh từ base64",
                "duplicate_characters": {},
                "duplicates": [],
                "all_predictions": []
            }
        )

# Alternative JSON-specific endpoint for base64 processing
@app.post("/process_base64_json")
async def process_image_base64_json(request_data: ImageBase64Request):
    try:
        # Lấy thông tin từ request JSON
        image_base64 = request_data.image_base64
        captcha_offset_x = request_data.captcha_offset_x
        captcha_offset_y = request_data.captcha_offset_y
        
        # Log the request (truncated for privacy)
        logger.info(f"Processing base64 JSON image, length: {len(image_base64) if image_base64 else 0}")
        
        # Giải mã base64 thành dữ liệu nhị phân
        try:
            # Xử lý trường hợp có tiền tố "data:image/..."
            if "base64," in image_base64:
                image_base64 = image_base64.split("base64,")[1]
            
            image_data = base64.b64decode(image_base64)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Không thể giải mã base64: {str(e)}")
        
        # Tạo file tạm để lưu ảnh
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temp_file:
            temp_file.write(image_data)
            temp_file_path = temp_file.name
        
        # Xử lý ảnh
        result = process_image(temp_file_path, captcha_offset_x, captcha_offset_y)
        
        # Xóa file tạm sau khi xử lý
        os.unlink(temp_file_path)
        
        return result
    
    except Exception as e:
        # Log the error
        logger.error(f"Error in process_image_base64_json: {str(e)}")
        
        # Xử lý lỗi
        return JSONResponse(
            status_code=500,
            content={
                "error": str(e),
                "details": "Lỗi trong quá trình xử lý ảnh từ base64",
                "duplicate_characters": {},
                "duplicates": [],
                "all_predictions": []
            }
        )

# Đặt các route bảo mật với API key
@app.post("/secure/process", dependencies=[Depends(get_api_key)])
async def secure_process_image_endpoint(
    file: UploadFile = File(...),
    captcha_offset_x: int = Form(None),
    captcha_offset_y: int = Form(None)
):
    """Route giống /process nhưng yêu cầu API key hợp lệ"""
    return await process_image_endpoint(file, captcha_offset_x, captcha_offset_y)

@app.post("/secure/process_url", dependencies=[Depends(get_api_key)])
async def secure_process_image_url(
    image_url: str = Form(...),
    captcha_offset_x: int = Form(None),
    captcha_offset_y: int = Form(None)
):
    """Route giống /process_url nhưng yêu cầu API key hợp lệ"""
    return await process_image_url(image_url, captcha_offset_x, captcha_offset_y)

@app.post("/secure/process_base64", dependencies=[Depends(get_api_key)])
async def secure_process_image_base64(request: Request):
    """Route giống /process_base64 nhưng yêu cầu API key hợp lệ"""
    return await process_image_base64(request)

@app.post("/secure/process_base64_json", dependencies=[Depends(get_api_key)])
async def secure_process_image_base64_json(request_data: ImageBase64Request):
    """Route giống /process_base64_json nhưng yêu cầu API key hợp lệ"""
    return await process_image_base64_json(request_data)

@app.get("/health")
async def health_check():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

# MỚI: HTML helper endpoint với hướng dẫn
@app.get("/helper")
async def helper_page():
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>CAPTCHA Analysis API Helper</title>
        <style>
            body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
            pre { background: #f4f4f4; padding: 10px; border-radius: 5px; overflow: auto; }
            h2 { margin-top: 30px; }
        </style>
    </head>
    <body>
        <h1>CAPTCHA Analysis API Helper</h1>
        
        <h2>Xử lý Blob URL</h2>
        <p>Để xử lý blob URL từ trình duyệt, bạn cần thực hiện các bước sau:</p>
        
        <pre>
// JavaScript để xử lý Blob URL
async function processCaptcha(blobUrl) {
    // Tải blob URL
    const response = await fetch(blobUrl);
    const blob = await response.blob();
    
    // Chuyển đổi blob thành base64
    const reader = new FileReader();
    reader.readAsDataURL(blob);
    
    return new Promise((resolve, reject) => {
        reader.onloadend = async () => {
            try {
                const base64Data = reader.result;
                
                // Gửi đến API
                const formData = new FormData();
                formData.append('image_base64', base64Data);
                
                const apiResponse = await fetch('/process_base64', {
                    method: 'POST',
                    body: formData
                });
                
                const result = await apiResponse.json();
                resolve(result);
            } catch (error) {
                reject(error);
            }
        };
        
        reader.onerror = reject;
    });
}

// Sử dụng
processCaptcha("blob:https://www.example.com/41031d94-2563-4609-bdd2-a2af28663add")
    .then(result => console.log(result))
    .catch(error => console.error(error));
        </pre>
        
        <h2>Sử dụng JSON format</h2>
        <p>Bạn cũng có thể sử dụng JSON để gửi dữ liệu base64:</p>
        
        <pre>
// JavaScript để gửi dữ liệu base64 qua JSON
async function processCaptchaWithJSON(base64Data) {
    const apiResponse = await fetch('/process_base64', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            'image_base64': base64Data,
            'captcha_offset_x': 107, // tùy chọn
            'captcha_offset_y': 192  // tùy chọn
        })
    });
    
    const result = await apiResponse.json();
    return result;
}
        </pre>
        
        <h2>Sử dụng API key để truy cập các endpoint bảo mật</h2>
        <p>Để sử dụng các endpoint bảo mật, bạn cần thêm API key vào header hoặc query parameter:</p>
        
        <pre>
// Thêm API key vào header
fetch('/secure/process_base64', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        'X-API-Key': 'YOUR_API_KEY_HERE'
    },
    body: JSON.stringify({
        'image_base64': base64Data
    })
});

// Hoặc thêm API key vào query parameter
fetch('/secure/process_base64?X-API-Key=YOUR_API_KEY_HERE', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json'
    },
    body: JSON.stringify({
        'image_base64': base64Data
    })
});
        </pre>
        
        <h2>Các endpoints có sẵn</h2>
        <ul>
            <li><code>/</code> - Trang chào mừng</li>
            <li><code>/health</code> - Kiểm tra trạng thái API</li>
            <li><code>/process</code> - Xử lý ảnh từ file upload</li>
            <li><code>/process_url</code> - Xử lý ảnh từ URL công khai</li>
            <li><code>/process_base64</code> - Xử lý ảnh từ chuỗi base64 (hỗ trợ cả form và JSON)</li>
            <li><code>/process_base64_json</code> - Xử lý ảnh từ chuỗi base64 (chỉ hỗ trợ JSON)</li>
            <li><code>/secure/process</code> - Phiên bản bảo mật của /process (yêu cầu API key)</li>
            <li><code>/secure/process_url</code> - Phiên bản bảo mật của /process_url (yêu cầu API key)</li>
            <li><code>/secure/process_base64</code> - Phiên bản bảo mật của /process_base64 (yêu cầu API key)</li>
            <li><code>/secure/process_base64_json</code> - Phiên bản bảo mật của /process_base64_json (yêu cầu API key)</li>
            <li><code>/docs</code> - API documentation tự động</li>
            <li><code>/redoc</code> - API documentation tự động (định dạng ReDoc)</li>
            <li><code>/admin/keys</code> - Trang quản lý API key (yêu cầu admin key)</li>
            <li><code>/helper</code> - Trang hướng dẫn này</li>
        </ul>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html_content, status_code=200)

# Khi chạy server
if __name__ == "__main__":
    import uvicorn
    
    # Tự động tạo ADMIN_API_KEY nếu chưa có trong biến môi trường
    if "ADMIN_API_KEY" not in os.environ:
        import secrets
        admin_key = secrets.token_hex(16)
        os.environ["ADMIN_API_KEY"] = admin_key
        print(f"\n[INFO] Generated new ADMIN_API_KEY: {admin_key}\n")
    
    # Log server startup
    logger.info("Starting CAPTCHA Analysis API server")
    
    # Run server with enhanced settings for production
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        workers=int(os.environ.get("WORKERS", 4)),
        log_level="info",
        proxy_headers=True,
        forwarded_allow_ips="*"  # Adjust for production
    )