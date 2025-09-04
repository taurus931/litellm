# Debug LiteLLM Proxy từ Source Code

Hướng dẫn này sẽ giúp bạn chạy LiteLLM Proxy từ source code thay vì sử dụng Docker image có sẵn, để có thể debug và chỉnh sửa code.

## 1. Thiết lập môi trường

### Bước 1: Copy file environment
```bash
cp env.dev.example .env
```

Sau đó chỉnh sửa file `.env` với các giá trị thực tế của bạn.

### Bước 2: Build và chạy với Docker Compose
```bash
# Build và chạy development environment
docker-compose -f docker-compose.dev.yml up --build

# Hoặc chạy trong background
docker-compose -f docker-compose.dev.yml up --build -d
```

## 2. Chạy LiteLLM trong Background

### Cách 1: Chạy ngầm (Recommended)
```powershell
# Chạy script PowerShell để start ngầm
.\run_background.ps1
```

### Cách 2: Chạy thủ công
```powershell
# Chạy trong background (detached mode)
docker-compose -f docker-compose.dev.yml up --build -d

# Xem logs
docker-compose -f docker-compose.dev.yml logs -f

# Dừng services
docker-compose -f docker-compose.dev.yml down
```

### Cách 3: Quản lý services
```powershell
# Start services
.\manage_services.ps1 start

# Stop services  
.\manage_services.ps1 stop

# Restart services
.\manage_services.ps1 restart

# Xem logs
.\manage_services.ps1 logs

# Xem status
.\manage_services.ps1 status
```

## 3. Debug Spend Tracking

### Chạy script debug
```bash
# Cài đặt dependencies cho script debug
pip install requests

# Chạy script debug
python debug_spend_tracking.py
```

### Kiểm tra logs
```bash
# Xem logs của LiteLLM container
docker logs litellm_server_dev -f

# Xem logs với timestamps
docker logs litellm_server_dev -f --timestamps
```

## 3. Chỉnh sửa Source Code

### Live Reload
Với setup này, bạn có thể chỉnh sửa code trong thư mục `litellm/` và container sẽ tự động reload (nếu sử dụng development mode).

### Debug specific files
Để debug spend tracking, tập trung vào các file sau:
- `litellm/proxy/db/db_spend_update_writer.py`
- `litellm/proxy/spend_tracking/spend_management_endpoints.py`
- `litellm/proxy/spend_tracking/spend_tracking_utils.py`

## 4. Truy cập Admin UI

### Admin UI Dashboard
LiteLLM có Admin UI tích hợp sẵn, bạn có thể truy cập tại:

```
http://localhost:4000/ui
```

**Thông tin đăng nhập mặc định:**
- Username: `admin`
- Password: `sk-1234` (hoặc giá trị của LITELLM_MASTER_KEY)

### Tính năng của Admin UI:
- 🔑 **Quản lý API Keys**: Tạo, xem, xóa API keys
- 📊 **Spend Tracking**: Xem chi tiết chi phí theo API key, user, team
- 👥 **User Management**: Quản lý users và teams
- 📈 **Analytics**: Biểu đồ usage và spend
- ⚙️ **Model Management**: Thêm/xóa models
- 🔧 **Configuration**: Cập nhật config trực tiếp từ UI

### Screenshots của các tính năng:
1. **Dashboard**: Overview của spend và usage
2. **API Keys**: Danh sách và tạo keys mới
3. **Spend Analytics**: Chi tiết spend tracking (đây là phần bạn cần debug)
4. **Models**: Quản lý model list

## 5. API Endpoints để Debug

### Kiểm tra spend logs
```bash
# Lấy tất cả spend logs
curl -X GET "http://localhost:4000/spend/logs" \
  -H "Authorization: Bearer sk-1234"

# Lấy spend logs theo API key
curl -X GET "http://localhost:4000/spend/logs?api_key=sk-your-test-key" \
  -H "Authorization: Bearer sk-1234"

# Lấy global spend report
curl -X GET "http://localhost:4000/global/spend/report?group_by=api_key" \
  -H "Authorization: Bearer sk-1234"
```

### Tạo API key test
```bash
curl -X POST "http://localhost:4000/key/generate" \
  -H "Authorization: Bearer sk-1234" \
  -H "Content-Type: application/json" \
  -d '{
    "models": ["gpt-3.5-turbo"],
    "max_budget": 100.0,
    "user_id": "debug_user"
  }'
```

### Gửi request test
```bash
curl -X POST "http://localhost:4000/v1/chat/completions" \
  -H "Authorization: Bearer sk-your-test-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [
      {"role": "user", "content": "Hello, this is a test message."}
    ],
    "max_tokens": 50
  }'
```

## 5. Troubleshooting

### Container không start
```bash
# Kiểm tra logs
docker-compose -f docker-compose.dev.yml logs litellm

# Rebuild container
docker-compose -f docker-compose.dev.yml down
docker-compose -f docker-compose.dev.yml up --build
```

### Database connection issues
```bash
# Kiểm tra PostgreSQL
docker exec -it litellm_postgres_dev psql -U postgres -d litellm

# Kiểm tra Redis
docker exec -it litellm_redis_dev redis-cli ping
```

### Permission issues
```bash
# Fix permissions
sudo chown -R $USER:$USER ./litellm
chmod -R 755 ./litellm
```

## 6. Development Tips

1. **Sử dụng debug flags**: Container đã được cấu hình với `--debug` và `--detailed_debug`
2. **Live code editing**: Code trong `./litellm/` được mount vào container
3. **Log monitoring**: Sử dụng `docker logs -f` để theo dõi real-time
4. **Database access**: PostgreSQL và Redis đều accessible từ localhost

## 7. Cấu trúc Files

```
.
├── Dockerfile.dev              # Development Dockerfile
├── docker-compose.dev.yml      # Development docker-compose
├── debug_spend_tracking.py     # Script debug spend tracking
├── env.dev.example            # Environment variables template
└── README_DEBUG.md            # File này
```

## 8. Next Steps

Sau khi setup xong, bạn có thể:
1. Chạy script debug để test spend tracking
2. Chỉnh sửa code trong `litellm/proxy/` để fix issues
3. Test lại với script debug
4. Commit changes và tạo PR
