#!/usr/bin/env python3
"""
Script để kiểm tra Admin UI và các endpoint liên quan
"""

import requests
import webbrowser
import time

# Configuration
PROXY_URL = "http://localhost:4000"
MASTER_KEY = "sk-1234"
UI_USERNAME = "admin"
UI_PASSWORD = "sk-1234"

def check_proxy_health():
    """Kiểm tra proxy server có đang chạy không"""
    try:
        response = requests.get(f"{PROXY_URL}/health", timeout=5)
        if response.status_code == 200:
            print("✅ Proxy server đang chạy")
            return True
        else:
            print(f"❌ Proxy server trả về status: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Không thể kết nối tới proxy server: {e}")
        return False

def check_ui_accessibility():
    """Kiểm tra UI có accessible không"""
    try:
        response = requests.get(f"{PROXY_URL}/ui", timeout=5)
        if response.status_code == 200:
            print("✅ Admin UI accessible")
            return True
        else:
            print(f"❌ Admin UI trả về status: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Không thể truy cập Admin UI: {e}")
        return False

def check_swagger_ui():
    """Kiểm tra Swagger UI"""
    try:
        response = requests.get(f"{PROXY_URL}/", timeout=5)
        if response.status_code == 200:
            print("✅ Swagger UI accessible")
            return True
        else:
            print(f"❌ Swagger UI trả về status: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Không thể truy cập Swagger UI: {e}")
        return False

def test_login():
    """Test login endpoint"""
    try:
        # Prepare login data
        login_data = {
            "username": UI_USERNAME,
            "password": UI_PASSWORD
        }
        
        response = requests.post(
            f"{PROXY_URL}/login",
            data=login_data,
            timeout=5
        )
        
        if response.status_code == 200:
            print("✅ Login endpoint hoạt động")
            return True
        else:
            print(f"❌ Login failed: {response.status_code} - {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Lỗi khi test login: {e}")
        return False

def check_models_endpoint():
    """Kiểm tra models endpoint"""
    try:
        headers = {
            "Authorization": f"Bearer {MASTER_KEY}"
        }
        
        response = requests.get(
            f"{PROXY_URL}/v1/models",
            headers=headers,
            timeout=5
        )
        
        if response.status_code == 200:
            models = response.json()
            print(f"✅ Models endpoint hoạt động - tìm thấy {len(models.get('data', []))} models")
            return True
        else:
            print(f"❌ Models endpoint failed: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Lỗi khi kiểm tra models: {e}")
        return False

def open_admin_ui():
    """Mở Admin UI trong browser"""
    try:
        print(f"🌐 Đang mở Admin UI tại: {PROXY_URL}/ui")
        print(f"📝 Username: {UI_USERNAME}")
        print(f"📝 Password: {UI_PASSWORD}")
        webbrowser.open(f"{PROXY_URL}/ui")
        return True
    except Exception as e:
        print(f"❌ Không thể mở browser: {e}")
        return False

def open_swagger_ui():
    """Mở Swagger UI trong browser"""
    try:
        print(f"📚 Đang mở Swagger UI tại: {PROXY_URL}/")
        webbrowser.open(f"{PROXY_URL}/")
        return True
    except Exception as e:
        print(f"❌ Không thể mở Swagger UI: {e}")
        return False

def main():
    """Main function"""
    print("🚀 Kiểm tra Admin UI và các endpoint...")
    print("=" * 50)
    
    # 1. Kiểm tra proxy server
    print("1. Kiểm tra proxy server...")
    if not check_proxy_health():
        print("❌ Proxy server không chạy. Hãy chạy docker-compose up trước.")
        return
    
    # 2. Kiểm tra models endpoint
    print("\n2. Kiểm tra models endpoint...")
    check_models_endpoint()
    
    # 3. Kiểm tra Swagger UI
    print("\n3. Kiểm tra Swagger UI...")
    check_swagger_ui()
    
    # 4. Kiểm tra Admin UI
    print("\n4. Kiểm tra Admin UI...")
    check_ui_accessibility()
    
    # 5. Test login endpoint
    print("\n5. Test login endpoint...")
    test_login()
    
    # 6. Mở browser
    print("\n6. Mở Admin UI trong browser...")
    open_admin_ui()
    
    print("\n7. Mở Swagger UI trong browser...")
    open_swagger_ui()
    
    print("\n" + "=" * 50)
    print("✅ Hoàn thành kiểm tra!")
    print("\n📋 Hướng dẫn sử dụng Admin UI:")
    print("1. Truy cập: http://localhost:4000/ui")
    print(f"2. Đăng nhập với Username: {UI_USERNAME}, Password: {UI_PASSWORD}")
    print("3. Vào mục 'Spend Analytics' để debug spend tracking")
    print("4. Tạo API keys và test spend tracking")
    print("\n📚 Swagger UI: http://localhost:4000/")
    print("   - Xem tất cả API endpoints")
    print("   - Test API trực tiếp từ browser")

if __name__ == "__main__":
    main()
