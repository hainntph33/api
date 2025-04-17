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
    
# Tạo HTML cho trang quản trị API Key
def get_admin_page_html():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Quản trị API Key</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 20px;
                background-color: #f5f5f5;
            }
            .container {
                max-width: 1000px;
                margin: 0 auto;
                background-color: white;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            h1 {
                color: #333;
                margin-top: 0;
            }
            .form-group {
                margin-bottom: 15px;
            }
            label {
                display: block;
                margin-bottom: 5px;
                font-weight: bold;
            }
            input[type="text"],
            input[type="email"],
            input[type="number"],
            input[type="password"] {
                width: 100%;
                padding: 8px;
                border: 1px solid #ddd;
                border-radius: 4px;
                box-sizing: border-box;
            }
            button {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 10px 15px;
                border-radius: 4px;
                cursor: pointer;
            }
            button:hover {
                background-color: #45a049;
            }
            table {
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
            }
            th, td {
                padding: 12px;
                text-align: left;
                border-bottom: 1px solid #ddd;
            }
            th {
                background-color: #f2f2f2;
            }
            .api-key {
                font-family: monospace;
                background-color: #f8f8f8;
                padding: 2px 4px;
                border-radius: 2px;
                border: 1px solid #ddd;
            }
            .status-active {
                color: green;
                font-weight: bold;
            }
            .status-inactive {
                color: red;
                font-weight: bold;
            }
            .actions {
                white-space: nowrap;
            }
            .section {
                margin-bottom: 30px;
                padding-bottom: 20px;
                border-bottom: 1px solid #eee;
            }
            .alert {
                padding: 10px 15px;
                margin-bottom: 15px;
                border-radius: 4px;
            }
            .alert-success {
                background-color: #dff0d8;
                border: 1px solid #d6e9c6;
                color: #3c763d;
            }
            .alert-error {
                background-color: #f2dede;
                border: 1px solid #ebccd1;
                color: #a94442;
            }
            .hidden {
                display: none;
            }
            .flex {
                display: flex;
                gap: 10px;
            }
            .btn-danger {
                background-color: #d9534f;
            }
            .btn-danger:hover {
                background-color: #c9302c;
            }
            .tag {
                display: inline-block;
                padding: 2px 8px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
            }
            .tag-limit {
                background-color: #f0ad4e;
                color: white;
            }
            .tag-unlimited {
                background-color: #5bc0de;
                color: white;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Quản lý API Key</h1>
            
            <div id="message" class="alert hidden"></div>
            
            <div class="section">
                <h2>Tạo API Key mới</h2>
                <form id="createKeyForm">
                    <div class="form-group">
                        <label for="user_name">Tên người dùng:</label>
                        <input type="text" id="user_name" name="user_name" required>
                    </div>
                    <div class="form-group">
                        <label for="user_email">Email:</label>
                        <input type="email" id="user_email" name="user_email" required>
                    </div>
                    <div class="form-group">
                        <label for="expires_in_days">Thời hạn (ngày):</label>
                        <input type="number" id="expires_in_days" name="expires_in_days" value="30" min="1">
                    </div>
                    <div class="form-group">
                        <label for="usage_limit">Giới hạn sử dụng (-1 là không giới hạn):</label>
                        <input type="number" id="usage_limit" name="usage_limit" value="-1">
                    </div>
                    <div class="form-group">
                        <label for="admin_key">Admin Key:</label>
                        <input type="password" id="admin_key" name="admin_key" required>
                    </div>
                    <button type="submit">Tạo API Key</button>
                </form>
            </div>
            
            <div class="section">
                <h2>Danh sách API Key</h2>
                <div class="flex">
                    <button id="refreshKeys">Làm mới danh sách</button>
                    <div>
                        <input type="checkbox" id="showActiveOnly" checked>
                        <label for="showActiveOnly">Chỉ hiển thị key đang hoạt động</label>
                    </div>
                </div>
                <div class="form-group">
                    <label for="admin_key_list">Admin Key:</label>
                    <input type="password" id="admin_key_list" required>
                </div>
                
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
                        <!-- Sẽ được điền bởi JavaScript -->
                    </tbody>
                </table>
            </div>
        </div>

        <script>
            // Kiểm tra trạng thái message và hiển thị nếu cần
            function showMessage(message, isError = false) {
                const messageEl = document.getElementById('message');
                messageEl.textContent = message;
                messageEl.classList.remove('hidden', 'alert-success', 'alert-error');
                messageEl.classList.add(isError ? 'alert-error' : 'alert-success');
                
                // Tự động ẩn sau 5 giây
                setTimeout(() => {
                    messageEl.classList.add('hidden');
                }, 5000);
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
                    row.innerHTML = '<td colspan="8" style="text-align: center;">Không có API key nào</td>';
                    tbody.appendChild(row);
                    return;
                }
                
                keys.forEach(key => {
                    const row = document.createElement('tr');
                    
                    // Định dạng ngày tháng
                    const createdDate = new Date(key.created_at).toLocaleString();
                    const expiresDate = key.expires_at ? new Date(key.expires_at).toLocaleString() : 'Không hết hạn';
                    
                    // Hiển thị giới hạn sử dụng
                    let usageText = '';
                    if (key.usage_limit > 0) {
                        usageText = `${key.usage_count} / ${key.usage_limit} <span class="tag tag-limit">Giới hạn</span>`;
                    } else {
                        usageText = `${key.usage_count} <span class="tag tag-unlimited">Không giới hạn</span>`;
                    }
                    
                    // Trạng thái
                    const statusClass = key.is_active ? 'status-active' : 'status-inactive';
                    const statusText = key.is_active ? 'Hoạt động' : 'Vô hiệu';
                    
                    row.innerHTML = `
                        <td><span class="api-key">${key.key}</span></td>
                        <td>${key.user_name}</td>
                        <td>${key.user_email}</td>
                        <td>${createdDate}</td>
                        <td>${expiresDate}</td>
                        <td>${usageText}</td>
                        <td class="${statusClass}">${statusText}</td>
                        <td class="actions">
                            ${key.is_active ? 
                                `<button class="btn-danger deactivate-key" data-key="${key.key}">Vô hiệu hóa</button>` : 
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

