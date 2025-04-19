#!/bin/bash
# Script thiết lập ban đầu cho VPS Google Cloud
# Cách sử dụng: bash setup-gcp.sh

# Màu sắc để hiển thị tốt hơn
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # Không màu

echo -e "${BLUE}Bắt đầu thiết lập ban đầu cho VPS Google Cloud...${NC}"

# Cập nhật gói hệ thống
echo -e "${BLUE}Cập nhật gói hệ thống...${NC}"
sudo apt update
sudo apt upgrade -y

# Cài đặt các gói cần thiết
echo -e "${BLUE}Cài đặt các gói cần thiết...${NC}"
sudo apt install -y python3-pip python3-venv python3-dev nginx build-essential git ufw

# Cài đặt dependencies Python toàn cục
echo -e "${BLUE}Cài đặt dependencies Python...${NC}"
sudo pip3 install --upgrade pip
sudo pip3 install gunicorn uvicorn

# Thiết lập tường lửa
echo -e "${BLUE}Thiết lập tường lửa...${NC}"
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw --force enable

# Tạo thư mục ứng dụng
APP_DIR="/opt/captcha-api"
echo -e "${BLUE}Tạo thư mục ứng dụng tại ${APP_DIR}...${NC}"
sudo mkdir -p ${APP_DIR}
sudo chown $USER:$USER ${APP_DIR}

# Hướng dẫn các bước tiếp theo
echo -e "${YELLOW}Các bước tiếp theo:${NC}"
echo -e "${YELLOW}1. Tải lên các file ứng dụng của bạn vào ${APP_DIR}${NC}"
echo -e "${YELLOW}2. Chạy script triển khai: bash deploy.sh${NC}"
echo -e "${YELLOW}3. Cấu hình Nginx: sudo cp nginx-captcha.conf /etc/nginx/sites-available/captcha-api${NC}"
echo -e "${YELLOW}4. Kích hoạt site: sudo ln -s /etc/nginx/sites-available/captcha-api /etc/nginx/sites-enabled/${NC}"
echo -e "${YELLOW}5. Kiểm tra cấu hình Nginx: sudo nginx -t${NC}"
echo -e "${YELLOW}6. Khởi động lại Nginx: sudo systemctl restart nginx${NC}"
echo -e "${GREEN}Thiết lập ban đầu hoàn tất!${NC}"