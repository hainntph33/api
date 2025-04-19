import secrets
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import sqlite3
from pydantic import BaseModel, Field
from fastapi import Depends, HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader, APIKeyQuery
from starlette.status import HTTP_403_FORBIDDEN, HTTP_404_NOT_FOUND
# Thêm import cần thiết
import os

# Định nghĩa các models Pydantic cho API Key
class APIKeyCreate(BaseModel):
    user_email: str
    user_name: str
    expires_in_days: Optional[int] = 30
    usage_limit: Optional[int] = -1  # -1 nghĩa là không giới hạn

class APIKeyResponse(BaseModel):
    key: str
    user_email: str
    user_name: str
    created_at: datetime
    expires_at: Optional[datetime] = None
    usage_count: int = 0
    usage_limit: int = -1
    is_active: bool = True

class APIKeyDB(APIKeyResponse):
    id: int

# Quản lý CSDL SQLite cho API Keys
class APIKeyManager:
    def __init__(self, db_path="api_keys.db"):
        self.db_path = db_path
        self._initialize_db()

    def _initialize_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Tạo bảng api_keys nếu chưa tồn tại
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            user_email TEXT NOT NULL,
            user_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            usage_count INTEGER DEFAULT 0,
            usage_limit INTEGER DEFAULT -1,
            is_active BOOLEAN DEFAULT 1
        )
        ''')
        
        conn.commit()
        conn.close()

    def create_api_key(self, key_data: APIKeyCreate) -> APIKeyResponse:
        # Tạo API key mới
        api_key = secrets.token_urlsafe(32)
        created_at = datetime.now()
        
        # Tính ngày hết hạn nếu có
        expires_at = None
        if key_data.expires_in_days > 0:
            expires_at = created_at + timedelta(days=key_data.expires_in_days)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            """
            INSERT INTO api_keys (key, user_email, user_name, created_at, expires_at, usage_limit, is_active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            (
                api_key, 
                key_data.user_email, 
                key_data.user_name, 
                created_at.isoformat(), 
                expires_at.isoformat() if expires_at else None,
                key_data.usage_limit
            )
        )
        
        conn.commit()
        conn.close()
        
        return APIKeyResponse(
            key=api_key,
            user_email=key_data.user_email,
            user_name=key_data.user_name,
            created_at=created_at,
            expires_at=expires_at,
            usage_count=0,
            usage_limit=key_data.usage_limit,
            is_active=True
        )

    def get_api_key(self, key: str) -> Optional[APIKeyDB]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM api_keys WHERE key = ?", (key,))
        row = cursor.fetchone()
        
        conn.close()
        
        if not row:
            return None
        
        # Chuyển đổi từ row thành đối tượng APIKeyDB
        created_at = datetime.fromisoformat(row['created_at'])
        expires_at = datetime.fromisoformat(row['expires_at']) if row['expires_at'] else None
        
        return APIKeyDB(
            id=row['id'],
            key=row['key'],
            user_email=row['user_email'],
            user_name=row['user_name'],
            created_at=created_at,
            expires_at=expires_at,
            usage_count=row['usage_count'],
            usage_limit=row['usage_limit'],
            is_active=bool(row['is_active'])
        )

    def verify_api_key(self, key: str) -> bool:
        api_key = self.get_api_key(key)
        
        if not api_key:
            return False
        
        # Kiểm tra xem key có còn hiệu lực không
        if not api_key.is_active:
            return False
        
        # Kiểm tra hạn sử dụng
        if api_key.expires_at and datetime.now() > api_key.expires_at:
            # Tự động vô hiệu hóa key đã hết hạn
            self.deactivate_api_key(key)
            return False
        
        # Kiểm tra giới hạn sử dụng
        if api_key.usage_limit > 0 and api_key.usage_count >= api_key.usage_limit:
            return False
        
        # Tăng số lần sử dụng
        self.increment_usage(key)
        
        return True

    def increment_usage(self, key: str) -> None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            "UPDATE api_keys SET usage_count = usage_count + 1 WHERE key = ?",
            (key,)
        )
        
        conn.commit()
        conn.close()

    def deactivate_api_key(self, key: str) -> bool:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            "UPDATE api_keys SET is_active = 0 WHERE key = ?",
            (key,)
        )
        
        rows_affected = cursor.rowcount
        conn.commit()
        conn.close()
        
        return rows_affected > 0

    def list_api_keys(self, active_only: bool = False) -> List[APIKeyDB]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if active_only:
            cursor.execute("SELECT * FROM api_keys WHERE is_active = 1")
        else:
            cursor.execute("SELECT * FROM api_keys")
            
        rows = cursor.fetchall()
        conn.close()
        
        api_keys = []
        for row in rows:
            created_at = datetime.fromisoformat(row['created_at'])
            expires_at = datetime.fromisoformat(row['expires_at']) if row['expires_at'] else None
            
            api_key = APIKeyDB(
                id=row['id'],
                key=row['key'],
                user_email=row['user_email'],
                user_name=row['user_name'],
                created_at=created_at,
                expires_at=expires_at,
                usage_count=row['usage_count'],
                usage_limit=row['usage_limit'],
                is_active=bool(row['is_active'])
            )
            api_keys.append(api_key)
        
        return api_keys

# Tạo middleware xác thực API Key
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)
api_key_query = APIKeyQuery(name=API_KEY_NAME, auto_error=False)

# Khởi tạo API Key Manager
api_key_manager = APIKeyManager()

# Hàm xác thực API key
async def get_api_key(
    api_key_header: str = Security(api_key_header),
    api_key_query: str = Security(api_key_query),
):
    # Ưu tiên API key từ header trước
    api_key = api_key_header or api_key_query
    
    if api_key:
        # Kiểm tra API key trong CSDL
        is_valid = api_key_manager.verify_api_key(api_key)
        if is_valid:
            return api_key
    
    # Nếu không có API key hoặc API key không hợp lệ
    raise HTTPException(
        status_code=HTTP_403_FORBIDDEN, 
        detail="API key không hợp lệ hoặc đã hết hạn"
    )

# Các hàm quản lý API key (để thêm vào FastAPI app)
def setup_api_key_management(app):
    @app.post("/api/keys", response_model=APIKeyResponse, tags=["API Keys"])
    async def create_api_key(key_data: APIKeyCreate, admin_key: str):
        # Lấy admin key từ biến môi trường, với giá trị mặc định cho trường hợp local
        ADMIN_KEY = os.environ.get("ADMIN_API_KEY", "admin_secret_key_2024")
        
        if admin_key != ADMIN_KEY:
            raise HTTPException(
                status_code=HTTP_403_FORBIDDEN,
                detail="Admin key không hợp lệ"
            )
        
        return api_key_manager.create_api_key(key_data)
        
    # Bổ sung thêm endpoints để liệt kê và vô hiệu hóa API key
    @app.get("/api/keys", response_model=List[APIKeyResponse], tags=["API Keys"])
    async def list_api_keys(admin_key: str, active_only: bool = False):
        """Liệt kê tất cả API keys (yêu cầu admin key)"""
        ADMIN_KEY = os.environ.get("ADMIN_API_KEY", "admin_secret_key_2024")
        if admin_key != ADMIN_KEY:
            raise HTTPException(
                status_code=HTTP_403_FORBIDDEN,
                detail="Admin key không hợp lệ"
            )
        
        return api_key_manager.list_api_keys(active_only)

    @app.delete("/api/keys/{key}", tags=["API Keys"])
    async def deactivate_api_key(key: str, admin_key: str):
        """Vô hiệu hóa một API key (yêu cầu admin key)"""
        ADMIN_KEY = os.environ.get("ADMIN_API_KEY", "admin_secret_key_2024")
        if admin_key != ADMIN_KEY:
            raise HTTPException(
                status_code=HTTP_403_FORBIDDEN,
                detail="Admin key không hợp lệ"
            )
        
        success = api_key_manager.deactivate_api_key(key)
        if not success:
            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail="API key không tìm thấy"
            )
        
        return {"message": "API key đã được vô hiệu hóa"} 
    
# Tạo HTML cho trang quản trị API Key
def get_admin_page_html():
    return """
    <!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Quản trị API Key</title>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        :root {
            --primary: #4361ee;
            --primary-hover: #3a56d4;
            --danger: #ef476f;
            --danger-hover: #d64263;
            --success: #06d6a0;
            --warning: #ffd166;
            --info: #118ab2;
            --light: #f8f9fa;
            --dark: #212529;
            --gray: #6c757d;
            --border: #dee2e6;
            --shadow: rgba(0, 0, 0, 0.05);
            --transition: all 0.3s ease;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background-color: #f7f9fc;
            color: #2d3748;
            line-height: 1.6;
        }

        .container {
            max-width: 1200px;
            margin: 2rem auto;
            padding: 0 1rem;
        }

        header {
            display: flex;
            align-items: center;
            margin-bottom: 2rem;
        }

        header h1 {
            font-size: 1.8rem;
            font-weight: 700;
            color: var(--primary);
            margin: 0;
        }

        header .logo {
            margin-right: 1rem;
            font-size: 2rem;
            color: var(--primary);
        }

        .card {
            background-color: white;
            border-radius: 12px;
            box-shadow: 0 4px 20px var(--shadow);
            margin-bottom: 2rem;
            overflow: hidden;
        }

        .card-header {
            padding: 1.25rem;
            border-bottom: 1px solid var(--border);
            background-color: white;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .card-header h2 {
            font-size: 1.25rem;
            font-weight: 600;
            margin: 0;
            color: var(--dark);
            display: flex;
            align-items: center;
        }

        .card-header h2 i {
            margin-right: 0.75rem;
            color: var(--primary);
        }

        .card-body {
            padding: 1.5rem;
        }

        .form-group {
            margin-bottom: 1.25rem;
        }

        label {
            display: block;
            margin-bottom: 0.5rem;
            font-weight: 500;
            color: var(--dark);
        }

        input[type="text"],
        input[type="email"],
        input[type="number"],
        input[type="password"] {
            width: 100%;
            padding: 0.75rem 1rem;
            border: 1px solid var(--border);
            border-radius: 8px;
            font-size: 1rem;
            transition: var(--transition);
        }

        input[type="text"]:focus,
        input[type="email"]:focus,
        input[type="number"]:focus,
        input[type="password"]:focus {
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 0 3px rgba(67, 97, 238, 0.15);
        }

        .btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 0.75rem 1.5rem;
            font-size: 1rem;
            font-weight: 500;
            border-radius: 8px;
            cursor: pointer;
            transition: var(--transition);
            border: none;
        }

        .btn i {
            margin-right: 0.5rem;
        }

        .btn-primary {
            background-color: var(--primary);
            color: white;
        }

        .btn-primary:hover {
            background-color: var(--primary-hover);
        }

        .btn-danger {
            background-color: var(--danger);
            color: white;
        }

        .btn-danger:hover {
            background-color: var(--danger-hover);
        }

        .btn-sm {
            padding: 0.4rem 0.75rem;
            font-size: 0.875rem;
        }

        .alert {
            padding: 1rem;
            border-radius: 8px;
            margin-bottom: 1.5rem;
            display: flex;
            align-items: center;
        }

        .alert i {
            margin-right: 0.75rem;
            font-size: 1.25rem;
        }

        .alert-success {
            background-color: rgba(6, 214, 160, 0.1);
            border: 1px solid rgba(6, 214, 160, 0.2);
            color: var(--success);
        }

        .alert-error {
            background-color: rgba(239, 71, 111, 0.1);
            border: 1px solid rgba(239, 71, 111, 0.2);
            color: var(--danger);
        }

        .hidden {
            display: none;
        }

        .badge {
            display: inline-flex;
            align-items: center;
            padding: 0.35rem 0.75rem;
            font-size: 0.75rem;
            font-weight: 600;
            border-radius: 50px;
        }

        .badge-success {
            background-color: rgba(6, 214, 160, 0.1);
            color: var(--success);
        }

        .badge-danger {
            background-color: rgba(239, 71, 111, 0.1);
            color: var(--danger);
        }

        .badge-warning {
            background-color: rgba(255, 209, 102, 0.1);
            color: var(--warning);
        }

        .badge-info {
            background-color: rgba(17, 138, 178, 0.1);
            color: var(--info);
        }

        .table-container {
            overflow-x: auto;
        }

        table {
            width: 100%;
            border-collapse: collapse;
        }

        th, td {
            padding: 1rem;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }

        th {
            font-weight: 600;
            color: var(--gray);
            font-size: 0.875rem;
            text-transform: uppercase;
        }

        tbody tr:hover {
            background-color: rgba(247, 250, 252, 0.8);
        }

        .api-key {
            font-family: 'Courier New', monospace;
            background-color: #f1f5f9;
            padding: 0.35rem 0.75rem;
            border-radius: 6px;
            font-size: 0.875rem;
            letter-spacing: 0.5px;
            font-weight: 500;
        }

        .status-active {
            color: var(--success);
            font-weight: bold;
        }

        .status-inactive {
            color: var(--danger);
            font-weight: bold;
        }

        .actions {
            white-space: nowrap;
        }

        .flex {
            display: flex;
            gap: 1rem;
            align-items: center;
        }

        .filters {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.5rem;
        }

        .custom-control {
            display: flex;
            align-items: center;
            cursor: pointer;
            user-select: none;
        }

        .custom-control input {
            margin-right: 0.5rem;
        }

        @media (max-width: 768px) {
            .filters {
                flex-direction: column;
                align-items: flex-start;
                gap: 1rem;
            }
            
            .table-responsive {
                overflow-x: auto;
            }
        }

        .empty-state {
            text-align: center;
            padding: 3rem 1rem;
            color: var(--gray);
        }

        .empty-state i {
            font-size: 3rem;
            margin-bottom: 1rem;
            color: #e2e8f0;
        }

        .empty-state p {
            font-size: 1.1rem;
            margin-bottom: 1.5rem;
        }

        .copy-btn {
            background: none;
            border: none;
            cursor: pointer;
            color: var(--primary);
            padding: 0.25rem;
            border-radius: 4px;
            transition: var(--transition);
        }

        .copy-btn:hover {
            background-color: rgba(67, 97, 238, 0.1);
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <i class="fas fa-key logo"></i>
            <h1>Quản lý API Key</h1>
        </header>

        <div id="message" class="alert hidden"></div>

        <div class="card">
            <div class="card-header">
                <h2><i class="fas fa-plus-circle"></i> Tạo API Key mới</h2>
            </div>
            <div class="card-body">
                <form id="createKeyForm">
                    <div class="form-group">
                        <label for="user_name">Tên người dùng</label>
                        <input type="text" id="user_name" name="user_name" placeholder="Nhập tên người dùng" required>
                    </div>
                    <div class="form-group">
                        <label for="user_email">Email</label>
                        <input type="email" id="user_email" name="user_email" placeholder="example@domain.com" required>
                    </div>
                    <div class="form-group">
                        <label for="expires_in_days">Thời hạn (ngày)</label>
                        <input type="number" id="expires_in_days" name="expires_in_days" value="30" min="1">
                    </div>
                    <div class="form-group">
                        <label for="usage_limit">Giới hạn sử dụng (-1 là không giới hạn)</label>
                        <input type="number" id="usage_limit" name="usage_limit" value="-1">
                    </div>
                    <div class="form-group">
                        <label for="admin_key">Admin Key</label>
                        <input type="password" id="admin_key" name="admin_key" placeholder="Nhập Admin Key" required>
                    </div>
                    <button type="submit" class="btn btn-primary"><i class="fas fa-key"></i> Tạo API Key</button>
                </form>
            </div>
        </div>

        <div class="card">
            <div class="card-header">
                <h2><i class="fas fa-list"></i> Danh sách API Key</h2>
            </div>
            <div class="card-body">
                <div class="filters">
                    <div class="form-group" style="margin-bottom: 0; flex-grow: 1;">
                        <label for="admin_key_list">Admin Key</label>
                        <input type="password" id="admin_key_list" placeholder="Nhập Admin Key để xem danh sách" required>
                    </div>
                    <div class="flex">
                        <button id="refreshKeys" class="btn btn-primary"><i class="fas fa-sync-alt"></i> Làm mới</button>
                        <label class="custom-control">
                            <input type="checkbox" id="showActiveOnly" checked>
                            <span>Chỉ hiển thị key đang hoạt động</span>
                        </label>
                    </div>
                </div>

                <div class="table-container">
                    <table id="apiKeysTable">
                        <thead>
                            <tr>
                                <th>API Key</th>
                                <th>Người dùng</th>
                                <th>Email</th>
                                <th>Ngày tạo</th>
                                <th>Hết hạn</th>
                                <th>Sử dụng</th>
                                <th>Trạng thái</th>
                                <th>Thao tác</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td colspan="8">
                                    <div class="empty-state">
                                        <i class="fas fa-database"></i>
                                        <p>Nhập Admin Key và nhấn "Làm mới" để xem danh sách API Key</p>
                                    </div>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <script>
        // Hiển thị thông báo
        function showMessage(message, isError = false) {
            const messageEl = document.getElementById('message');
            messageEl.innerHTML = `<i class="fas fa-${isError ? 'exclamation-circle' : 'check-circle'}"></i> ${message}`;
            messageEl.classList.remove('hidden', 'alert-success', 'alert-error');
            messageEl.classList.add(isError ? 'alert-error' : 'alert-success');
            
            // Tự động ẩn sau 5 giây
            setTimeout(() => {
                messageEl.classList.add('hidden');
            }, 5000);
            
            // Cuộn lên đầu trang để xem thông báo
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
        
        // Copy API key
        function copyToClipboard(text) {
            navigator.clipboard.writeText(text).then(() => {
                showMessage('Đã sao chép API key vào clipboard');
            }).catch(err => {
                console.error('Không thể sao chép: ', err);
            });
        }
        
        // Khởi tạo form tạo API key
        document.getElementById('createKeyForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const formData = {
                user_name: document.getElementById('user_name').value,
                user_email: document.getElementById('user_email').value,
                expires_in_days: parseInt(document.getElementById('expires_in_days').value),
                usage_limit: parseInt(document.getElementById('usage_limit').value)
            };
            
            const adminKey = document.getElementById('admin_key').value;
            
            try {
                const response = await fetch(`/api/keys?admin_key=${encodeURIComponent(adminKey)}`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(formData)
                });
                
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.detail || 'Không thể tạo API key');
                }
                
                const data = await response.json();
                showMessage(`API key đã được tạo thành công: ${data.key}`);
                
                // Reset form
                document.getElementById('user_name').value = '';
                document.getElementById('user_email').value = '';
                
                // Làm mới danh sách
                document.getElementById('admin_key_list').value = adminKey;
                fetchApiKeys();
                
            } catch (error) {
                showMessage(error.message, true);
            }
        });
        
        // Tải danh sách API keys
        async function fetchApiKeys() {
            const adminKey = document.getElementById('admin_key_list').value;
            if (!adminKey) {
                showMessage('Vui lòng nhập Admin Key để xem danh sách', true);
                return;
            }
            
            const showActiveOnly = document.getElementById('showActiveOnly').checked;
            
            try {
                const response = await fetch(`/api/keys?admin_key=${encodeURIComponent(adminKey)}&active_only=${showActiveOnly}`);
                
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.detail || 'Không thể tải danh sách API key');
                }
                
                const keys = await response.json();
                renderApiKeysTable(keys, adminKey);
                
            } catch (error) {
                showMessage(error.message, true);
            }
        }
        
        // Hiển thị danh sách API keys trong bảng
        function renderApiKeysTable(keys, adminKey) {
            const tbody = document.querySelector('#apiKeysTable tbody');
            tbody.innerHTML = '';
            
            if (keys.length === 0) {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td colspan="8">
                        <div class="empty-state">
                            <i class="fas fa-search"></i>
                            <p>Không tìm thấy API key nào</p>
                        </div>
                    </td>
                `;
                tbody.appendChild(row);
                return;
            }
            
            keys.forEach(key => {
                const row = document.createElement('tr');
                
                // Định dạng ngày tháng
                const options = { 
                    year: 'numeric', 
                    month: '2-digit', 
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit'
                };
                const createdDate = new Date(key.created_at).toLocaleDateString('vi-VN', options);
                const expiresDate = key.expires_at ? 
                    new Date(key.expires_at).toLocaleDateString('vi-VN', options) : 
                    '<span class="badge badge-info">Không hết hạn</span>';
                
                // Hiển thị giới hạn sử dụng
                let usageText = '';
                if (key.usage_limit > 0) {
                    const usagePercent = (key.usage_count / key.usage_limit) * 100;
                    let badgeClass = 'badge-info';
                    
                    if (usagePercent >= 90) {
                        badgeClass = 'badge-danger';
                    } else if (usagePercent >= 70) {
                        badgeClass = 'badge-warning';
                    }
                    
                    usageText = `${key.usage_count} / ${key.usage_limit} <span class="badge ${badgeClass}">Giới hạn</span>`;
                } else {
                    usageText = `${key.usage_count} <span class="badge badge-success">Không giới hạn</span>`;
                }
                
                // Trạng thái
                const statusClass = key.is_active ? 'status-active' : 'status-inactive';
                const statusText = key.is_active ? 
                    '<span class="badge badge-success">Hoạt động</span>' : 
                    '<span class="badge badge-danger">Vô hiệu</span>';
                
                row.innerHTML = `
                    <td>
                        <div style="display: flex; align-items: center;">
                            <span class="api-key">${key.key}</span>
                            <button class="copy-btn" onclick="copyToClipboard('${key.key}')" title="Sao chép">
                                <i class="fas fa-copy"></i>
                            </button>
                        </div>
                    </td>
                    <td>${key.user_name}</td>
                    <td>${key.user_email}</td>
                    <td>${createdDate}</td>
                    <td>${expiresDate}</td>
                    <td>${usageText}</td>
                    <td class="${statusClass}">${statusText}</td>
                    <td class="actions">
                        ${key.is_active ? 
                            `<button class="btn btn-danger btn-sm deactivate-key" data-key="${key.key}">
                                <i class="fas fa-ban"></i> Vô hiệu hóa
                            </button>` : 
                            ''}
                    </td>
                `;
                
                tbody.appendChild(row);
            });
            
            // Thêm sự kiện cho các nút vô hiệu hóa
            document.querySelectorAll('.deactivate-key').forEach(button => {
                button.addEventListener('click', async () => {
                    const apiKey = button.getAttribute('data-key');
                    if (confirm(`Bạn có chắc chắn muốn vô hiệu hóa API key này: ${apiKey}?`)) {
                        try {
                            const response = await fetch(`/api/keys/${apiKey}?admin_key=${encodeURIComponent(adminKey)}`, {
                                method: 'DELETE'
                            });
                            
                            if (!response.ok) {
                                const errorData = await response.json();
                                throw new Error(errorData.detail || 'Không thể vô hiệu hóa API key');
                            }
                            
                            showMessage('API key đã được vô hiệu hóa thành công');
                            fetchApiKeys();
                            
                        } catch (error) {
                            showMessage(error.message, true);
                        }
                    }
                });
            });
        }
        
        // Hàm để sao chép API key vào clipboard
        window.copyToClipboard = copyToClipboard;
        
        // Sự kiện nút làm mới
        document.getElementById('refreshKeys').addEventListener('click', fetchApiKeys);
        
        // Sự kiện thay đổi checkbox chỉ hiển thị key đang hoạt động
        document.getElementById('showActiveOnly').addEventListener('change', fetchApiKeys);
    </script>
</body>
</html>
    """

# Thêm endpoint cho trang quản trị
def add_admin_page(app):
    from fastapi.responses import HTMLResponse
    
    @app.get("/admin/keys", response_class=HTMLResponse)
    async def admin_keys_page():
        """Trang quản trị API key"""
        return get_admin_page_html()

