#!/usr/bin/env python3
"""
Script để debug spend tracking trong LiteLLM Proxy
"""

import requests
import json
import time
from datetime import datetime, timedelta

# Configuration
PROXY_URL = "http://localhost:4000"
MASTER_KEY = "sk-1234"  # Thay đổi theo master key của bạn
TEST_API_KEY = "sk-test-debug-key"  # API key để test

def create_test_api_key():
    """Tạo một API key test để debug"""
    headers = {
        "Authorization": f"Bearer {MASTER_KEY}",
        "Content-Type": "application/json"
    }
    
    data = {
        "models": ["gpt-3.5-turbo"],
        "max_budget": 100.0,
        "user_id": "debug_user"
    }
    
    try:
        response = requests.post(
            f"{PROXY_URL}/key/generate",
            headers=headers,
            json=data
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Tạo API key thành công: {result.get('key', 'N/A')}")
            return result.get('key')
        else:
            print(f"❌ Lỗi tạo API key: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"❌ Exception khi tạo API key: {e}")
        return None

def make_test_request(api_key, model="gpt-3.5-turbo"):
    """Tạo một request test để generate spend data"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": model,
        "messages": [
            {"role": "user", "content": "Hello, this is a test message for spend tracking debug."}
        ],
        "max_tokens": 50
    }
    
    try:
        print(f"🔄 Gửi request test với model: {model}")
        response = requests.post(
            f"{PROXY_URL}/v1/chat/completions",
            headers=headers,
            json=data
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Request thành công!")
            print(f"   Request ID: {result.get('id', 'N/A')}")
            print(f"   Model: {result.get('model', 'N/A')}")
            print(f"   Usage: {result.get('usage', {})}")
            return result.get('id')
        else:
            print(f"❌ Lỗi request: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"❌ Exception khi gửi request: {e}")
        return None

def check_spend_logs(api_key=None, user_id=None, request_id=None):
    """Kiểm tra spend logs"""
    headers = {
        "Authorization": f"Bearer {MASTER_KEY}",
        "Content-Type": "application/json"
    }
    
    params = {}
    if api_key:
        params['api_key'] = api_key
    if user_id:
        params['user_id'] = user_id
    if request_id:
        params['request_id'] = request_id
    
    try:
        print(f"🔍 Kiểm tra spend logs với params: {params}")
        response = requests.get(
            f"{PROXY_URL}/spend/logs",
            headers=headers,
            params=params
        )
        
        if response.status_code == 200:
            logs = response.json()
            print(f"✅ Tìm thấy {len(logs)} spend logs:")
            
            for i, log in enumerate(logs[:5]):  # Chỉ hiển thị 5 logs đầu
                print(f"   Log {i+1}:")
                print(f"     - API Key: {log.get('api_key', 'N/A')}")
                print(f"     - User: {log.get('user', 'N/A')}")
                print(f"     - Model: {log.get('model', 'N/A')}")
                print(f"     - Spend: {log.get('spend', 'N/A')}")
                print(f"     - Start Time: {log.get('startTime', 'N/A')}")
                print(f"     - Request ID: {log.get('request_id', 'N/A')}")
                print()
            
            return logs
        else:
            print(f"❌ Lỗi khi lấy spend logs: {response.status_code} - {response.text}")
            return []
    except Exception as e:
        print(f"❌ Exception khi lấy spend logs: {e}")
        return []

def check_global_spend_report(api_key=None):
    """Kiểm tra global spend report"""
    headers = {
        "Authorization": f"Bearer {MASTER_KEY}",
        "Content-Type": "application/json"
    }
    
    params = {
        'group_by': 'api_key'
    }
    if api_key:
        params['api_key'] = api_key
    
    try:
        print(f"📊 Kiểm tra global spend report...")
        response = requests.get(
            f"{PROXY_URL}/global/spend/report",
            headers=headers,
            params=params
        )
        
        if response.status_code == 200:
            report = response.json()
            print(f"✅ Global spend report:")
            print(json.dumps(report, indent=2))
            return report
        else:
            print(f"❌ Lỗi khi lấy global spend report: {response.status_code} - {response.text}")
            return []
    except Exception as e:
        print(f"❌ Exception khi lấy global spend report: {e}")
        return []

def main():
    """Main function để chạy debug"""
    print("🚀 Bắt đầu debug spend tracking...")
    print("=" * 50)
    
    # 1. Tạo API key test
    print("1. Tạo API key test...")
    api_key = create_test_api_key()
    if not api_key:
        print("❌ Không thể tạo API key, dừng debug")
        return
    
    # 2. Gửi request test
    print("\n2. Gửi request test...")
    request_id = make_test_request(api_key)
    
    # 3. Đợi một chút để data được ghi vào DB
    print("\n3. Đợi data được ghi vào database...")
    time.sleep(3)
    
    # 4. Kiểm tra spend logs
    print("\n4. Kiểm tra spend logs...")
    logs = check_spend_logs(api_key=api_key)
    
    # 5. Kiểm tra global spend report
    print("\n5. Kiểm tra global spend report...")
    report = check_global_spend_report(api_key=api_key)
    
    # 6. Kiểm tra theo request_id nếu có
    if request_id:
        print(f"\n6. Kiểm tra spend logs theo request_id: {request_id}")
        request_logs = check_spend_logs(request_id=request_id)
    
    print("\n" + "=" * 50)
    print("✅ Hoàn thành debug spend tracking!")
    print(f"📝 API key test: {api_key}")
    if request_id:
        print(f"📝 Request ID: {request_id}")

if __name__ == "__main__":
    main()
