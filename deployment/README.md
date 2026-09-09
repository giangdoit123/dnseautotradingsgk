# Triển khai production riêng tư

Đây là gói triển khai Docker cho **một chủ tài khoản**. UI giữ API key, API
secret và Trading Token trong cùng tiến trình; vì vậy không được đưa cổng này
ra Internet công khai hoặc dùng chung giữa nhiều người.

Compose chỉ bind `127.0.0.1:8787`. Nếu máy chủ ở xa, truy cập qua VPN riêng như
Tailscale hoặc SSH tunnel. Không mở cổng 8787 trên firewall/router.

## 1. Chuẩn bị máy chủ

- Docker Engine và Docker Compose v2.
- Đồng hồ máy chủ đồng bộ NTP: DNSE yêu cầu thời gian request sát với giờ của
  họ.
- Một máy chủ/VPS cá nhân đã được bảo vệ bằng tài khoản hệ điều hành và VPN.

## 2. Cấu hình bí mật

Tạo tệp bí mật (tệp này bị `.dockerignore` loại khỏi image):

```bash
cp deployment/.env.production.example deployment/.env
chmod 600 deployment/.env
```

Điền `DNSE_API_KEY` và `DNSE_API_SECRET`. Không đặt OTP hoặc Trading Token vào
tệp này. UAT và Production phải dùng đúng cặp key/secret cùng endpoint tương
ứng. Giữ `PLACE_ORDER=0` trong giai đoạn kiểm thử.

## 3. Chạy dịch vụ

Từ thư mục gốc dự án:

```bash
docker compose -f deployment/docker-compose.prod.yml up -d --build
docker compose -f deployment/docker-compose.prod.yml ps
```

Để chỉ kiểm tra cú pháp Compose mà không dùng tệp bí mật thật:

```bash
DNSE_ENV_FILE=.env.production.example docker compose -f deployment/docker-compose.prod.yml config
```

Mở `http://127.0.0.1:8787` trên máy chủ hoặc qua VPN/tunnel, sau đó nhấn **Dùng
.env**. Với image production, việc nhập API key/secret trực tiếp từ trình duyệt
được tắt có chủ đích. Lấy Trading Token bằng OTP trong UI mỗi khi cần; token
không được lưu trong `.env` và mất khi container khởi động lại.

## 4. Xác minh trước khi giao dịch

1. Dùng key UAT và chọn **UAT** trong UI.
2. Kiểm tra UI nhận đúng tiểu khoản và số dư.
3. Lấy Trading Token với OTP UAT.
4. Chạy backtest, sau đó gửi một lệnh UAT khối lượng nhỏ nhất.
5. Chỉ sau đó mới thay **đồng thời** key/secret và hai URL DNSE sang Production.

`PLACE_ORDER=1` chỉ áp dụng cho auto-trader CLI, không phải nút đặt lệnh thủ
công trong UI. Không đổi giá trị này trước khi đã xác minh UAT.

## Vận hành

```bash
# Xem nhật ký, không bao gồm API secret
docker compose -f deployment/docker-compose.prod.yml logs -f dnse-ui

# Cập nhật code rồi build lại
docker compose -f deployment/docker-compose.prod.yml up -d --build

# Dừng dịch vụ
docker compose -f deployment/docker-compose.prod.yml down
```

Không dùng `down -v`: thao tác đó không cần thiết cho UI và có thể xoá dữ liệu
Docker không liên quan nếu cấu hình được mở rộng trong tương lai.
