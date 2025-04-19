#!/bin/bash
# Script triển khai API CAPTCHA Analysis cho Google Cloud VPS
# Cách sử dụng: bash deploy.sh

# Màu sắc để hiển thị tốt hơn
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # Không màu

echo -e "${BLUE}Bắt đầu quy trình triển khai API CAPTCHA Analysis trên Google Cloud...${NC}"

# Kiểm tra nếu đang chạy với quyền root
if [[ $EUID -ne 0 ]]; then
   echo -e "${YELLOW}Script này không chạy với quyền root. Một số thao tác có thể thất bại.${NC}"
   echo -e "${YELLOW}Hãy cân nhắc chạy với sudo nếu bạn gặp lỗi về quyền.${NC}"
fi

# Tạo thư mục cho ứng dụng nếu chưa tồn tại
APP_DIR="/opt/captcha-api"
echo -e "${BLUE}Thiết lập thư mục ứng dụng tại ${APP_DIR}...${NC}"
sudo mkdir -p ${APP_DIR}
sudo chown $USER:$USER ${APP_DIR}

# Clone hoặc cập nhật repository (nếu bạn đang sử dụng Git)
if [ -d "${APP_DIR}/.git" ]; then
    echo -e "${BLUE}Đang cập nhật repository hiện có...${NC}"
    cd ${APP_DIR}
    git pull
else
    echo -e "${BLUE}Thiết lập ứng dụng mới...${NC}"
    # Sao chép các file ứng dụng của bạn vào APP_DIR
    # Nếu bạn không sử dụng Git, bạn sẽ sao chép file ở đây
    cd ${APP_DIR}
fi

# Tạo môi trường ảo Python
echo -e "${BLUE}Thiết lập môi trường ảo Python...${NC}"
python3 -m venv venv
source venv/bin/activate

# Cài đặt các dependencies
echo -e "${BLUE}Cài đặt các dependencies...${NC}"
pip install --upgrade pip
pip install -r requirements.txt

# Tạo file .env nếu chưa tồn tại
if [ ! -f "${APP_DIR}/.env" ]; then
    echo -e "${BLUE}Tạo file .env...${NC}"
    cat > ${APP_DIR}/.env << EOF
ROBOFLOW_API_KEY=D0z8HBtVSIXIYX0bKrUR
ADMIN_API_KEY=$(openssl rand -hex 16)
EOF
    echo -e "${GREEN}File .env đã được tạo với ADMIN_API_KEY ngẫu nhiên${NC}"
else
    echo -e "${YELLOW}File .env đã tồn tại. Bỏ qua việc tạo.${NC}"
fi

# Tạo file service systemd
echo -e "${BLUE}Tạo file service systemd...${NC}"
sudo tee /etc/systemd/system/captcha-api.service > /dev/null << EOF
[Unit]
Description=CAPTCHA Analysis API Service
After=network.target

[Service]
User=$USER
Group=$USER
WorkingDirectory=${APP_DIR}
Environment="PATH=${APP_DIR}/venv/bin"
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/venv/bin/gunicorn -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000 2:app

[Install]
WantedBy=multi-user.target
EOF

# Thiết lập tường lửa (nếu cần)
echo -e "${BLUE}Thiết lập tường lửa...${NC}"
sudo ufw allow 8000/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Kích hoạt và khởi động service
echo -e "${BLUE}Kích hoạt và khởi động service...${NC}"
sudo systemctl daemon-reload
sudo systemctl enable captcha-api.service
sudo systemctl start captcha-api.service

# Kiểm tra trạng thái của service
echo -e "${BLUE}Kiểm tra trạng thái service...${NC}"
sudo systemctl status captcha-api.service

# Hiển thị admin key từ file .env
ADMIN_KEY=$(grep ADMIN_API_KEY ${APP_DIR}/.env | cut -d= -f2)
echo -e "${GREEN}=====================================${NC}"
echo -e "${GREEN}Triển khai hoàn tất thành công!${NC}"
echo -e "${GREEN}=====================================${NC}"
echo -e "${YELLOW}ADMIN_API_KEY của bạn là: ${ADMIN_KEY}${NC}"
echo -e "${YELLOW}Truy cập API tại: http://IP_SERVER_CỦA_BẠN:8000${NC}"
echo -e "${YELLOW}Truy cập bảng quản trị tại: http://IP_SERVER_CỦA_BẠN:8000/admin/keys${NC}"
echo -e "${GREEN}=====================================${NC}"