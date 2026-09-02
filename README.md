# DNSE OpenAPI Trading Toolkit

Bộ công cụ này giúp bạn kết nối DNSE OpenAPI, xem dữ liệu thị trường, quản lý
tài khoản, chạy backtest và thử chiến lược giao dịch trước khi dùng tiền thật.

> Cảnh báo: đây là công cụ kỹ thuật, không phải khuyến nghị đầu tư. Backtest và
> UAT không đảm bảo kết quả khi giao dịch thật. Luôn dùng UAT và giới hạn rủi ro
> trước khi bật lệnh production.

## Chức năng chính

- **DNSE Control Center:** giao diện cục bộ để xem tài khoản, thị trường, OTP,
  Trading Token và các thao tác giao dịch.
- **Market data:** giá trần/sàn/tham chiếu, OHLC, chào giá, khớp lệnh, phiên và
  dữ liệu khối ngoại.
- **Auto-trader:** theo dõi nến đóng WebSocket, tạo tín hiệu và đóng lệnh theo
  giao cắt Base129 khi được cho phép rõ ràng.
- **Backtest:** mô phỏng chiến lược `ichimoku_volume_mtf` trên dữ liệu OHLC lịch
  sử của DNSE, có tính phí và trượt giá giả định.

## 1. Cài đặt lần đầu

Yêu cầu: Python 3.8 trở lên và quyền truy cập DNSE OpenAPI.

Mở PowerShell tại thư mục dự án và chạy:

```powershell
cd python
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Thư viện cần thiết được liệt kê trong [python/requirements.txt](python/requirements.txt).

## 2. Chọn cách kết nối

### Cách dễ nhất: dùng giao diện

Chạy:

```powershell
cd python
.\.venv\Scripts\python.exe -X utf8 ui/server.py
```

Mở [http://127.0.0.1:8787](http://127.0.0.1:8787), sau đó:

1. Nhập **API key** và **API secret**.
2. Chọn `Production` hoặc `UAT`.
3. Bấm **Kết nối**.

UI tự tạo chữ ký HMAC, `Date`, nonce, version, query, request body và header.
API secret chỉ được giữ trong bộ nhớ tiến trình đang chạy, không được lưu bởi UI.

Mục **Backtest trực quan** cho phép chọn mã, khung 1/3 phút và số ngày để xem
nguồn OHLC từ DNSE, nến, Base Line 129, mây Kumo, điểm vào/thoát và bảng lãi/lỗ
của từng lệnh mô phỏng. Chức năng này chỉ đọc dữ liệu thị trường.

### Chạy các ví dụ Python

Sao chép mẫu cấu hình:

```powershell
cd python
Copy-Item examples\.env.example examples\.env
```

Mở `python/examples/.env` và điền:

```ini
DNSE_API_KEY=your-api-key
DNSE_API_SECRET=your-api-secret
DNSE_API_VERSION=2026-07-23
DNSE_BASE_URL=https://openapi.dnse.com.vn
DNSE_WS_URL=wss://ws-openapi.dnse.com.vn
```

Tệp `.env` đã được Git bỏ qua. Không gửi, không commit và không chụp màn hình
API secret.

## 3. Các thao tác thường dùng

Tất cả các lệnh sau được chạy từ thư mục `python`.

### Kiểm tra tài khoản và tiểu khoản

```powershell
.\.venv\Scripts\python.exe -X utf8 examples/use-cases/portfolio-check.py
```

Lệnh này chỉ đọc. Sau khi có kết quả, dùng tiểu khoản có `dealAccount=true` cho
các thao tác giao dịch và đặt vào `DNSE_ACCOUNT_NO` trong `.env`.

### Xem dữ liệu thị trường

```powershell
.\.venv\Scripts\python.exe -X utf8 examples/use-cases/market-data.py
```

Để đổi mã, sửa danh sách `SYMBOLS` trong
[python/examples/use-cases/market-data.py](python/examples/use-cases/market-data.py).

### Lấy Trading Token để giao dịch

Trong UI, thực hiện theo thứ tự:

1. Chọn **Gửi Email OTP**.
2. Lấy mã OTP từ email hoặc Smart OTP.
3. Chọn **Lấy Trading Token**, chọn đúng loại OTP và nhập mã.

Token có hiệu lực khoảng 8 giờ theo hướng dẫn DNSE. UI tự giữ token trong bộ
nhớ cho các thao tác giao dịch; bạn không cần tự điền header `trading-token`.

> Các thao tác đặt, sửa, hủy lệnh và đóng vị thế yêu cầu tích xác nhận giao dịch
> thật trong UI.

## 4. Chiến lược Ichimoku + volume: hai luồng độc lập

Chiến lược `ichimoku_volume_mtf` chạy độc lập trên cả nến 1 phút và nến 3 phút.
Mỗi luồng áp dụng cùng bộ điều kiện và không dùng tín hiệu của khung kia để xác
nhận, chặn hay đóng lệnh.

| Tình huống | Điều kiện |
|---|---|
| Long | Base Line Ichimoku 129 kỳ đang hướng lên và nằm **trên mây Kumo** (cao hơn cả Leading Span A/B), volume hiện tại ≥ 2 × MA20 volume và RSI ngày ≤ 60. |
| Short | Base Line Ichimoku 129 kỳ đang hướng xuống và nằm **dưới mây Kumo** (thấp hơn cả Leading Span A/B), volume hiện tại ≥ 2 × MA20 volume. |
| Thoát long | Giá đóng nến của chính khung đó cắt xuống Base Line 129. |
| Thoát short | Giá đóng nến của chính khung đó cắt lên Base Line 129. |

Mây Kumo được lấy đúng tại vị trí đang hiển thị: Leading Span A dùng Conversion
Line 9 kỳ với Base Line 129 kỳ, Leading Span B dùng 52 kỳ, cùng độ dịch chuyển
26 nến. Chiến lược **không dùng TP hoặc SL cố định**. Thoát lệnh chỉ được xác
nhận khi nến đóng có giao cắt Base129 ngược chiều. Vào lệnh có hai chế độ:
`confirmed` đợi nến đóng, còn `intrabar` dùng snapshot OHLC realtime (giá hiện
tại, high/low đang hình thành và volume lũy kế) để vào ngay trong nến N.

Để chạy ở chế độ mô phỏng, thêm vào `python/examples/.env`:

```ini
STRATEGY=ichimoku_volume_mtf
TIMEFRAMES=1,3
ENTRY_MODE=intrabar
PLACE_ORDER=0
```

Sau đó chạy:

```powershell
.\.venv\Scripts\python.exe -X utf8 examples/use-cases/auto-trader-multi-timeframe.py
```

`PLACE_ORDER=0` là mô phỏng: mỗi luồng chỉ in kế hoạch vào/thoát lệnh, không gửi
lệnh tới DNSE. Hai luồng ghi trạng thái khôi phục riêng ở
`examples/.position_1m.json` và `examples/.position_3m.json`. Chỉ đổi thành
`PLACE_ORDER=1` sau khi đã hoàn tất backtest và UAT.

## 5. Backtest trước khi giao dịch

Backtest chỉ gọi dữ liệu OHLC lịch sử; không lấy OTP, Trading Token và không thể
đặt lệnh. Có hai mô hình vào lệnh:

- `next_open`: tín hiệu nến đóng được khớp ở **giá mở nến kế tiếp**.
- `intrabar_close`: lệnh được gắn vào **nến N** tại giá đóng N. Đây là proxy
  lịch sử vì OHLC không lưu mọi snapshot nội nến; chỉ dữ liệu realtime được ghi
  lại mới phát lại được đúng từng thời điểm khớp trong nến.
- Không có take profit hoặc stop loss cố định; lệnh chỉ thoát ở Base129 cross.
- Có thể điều chỉnh phí và trượt giá theo basis point cho mỗi chiều.

Chạy 30 ngày gần nhất:

```powershell
.\.venv\Scripts\python.exe -X utf8 examples/backtest_ichimoku_volume_mtf.py --resolution 1 --days 30
```

Ví dụ điều chỉnh giả định chi phí:

```powershell
.\.venv\Scripts\python.exe -X utf8 examples/backtest_ichimoku_volume_mtf.py --resolution 1 --days 90 --commission-bps 2 --slippage-bps 1
```

Backtest proxy cho chế độ vào nội nến:

```powershell
.\.venv\Scripts\python.exe -X utf8 examples/backtest_ichimoku_volume_mtf.py --resolution 1 --days 30 --entry-mode intrabar_close
```

Lặp lại cùng lệnh với `--resolution 3` để đánh giá độc lập luồng 3 phút; không
gộp hai báo cáo thành một kết quả chiến lược.

Lưu báo cáo đầy đủ:

```powershell
.\.venv\Scripts\python.exe -X utf8 examples/backtest_ichimoku_volume_mtf.py --resolution 1 --days 90 --output report.json
```

Khi đọc kết quả, đừng chỉ nhìn lợi nhuận ròng. Hãy đánh giá tối thiểu:

- số lệnh và độ dài giai đoạn;
- profit factor;
- drawdown lớn nhất;
- lợi nhuận sau phí/trượt giá;
- kết quả ở nhiều giai đoạn tăng, giảm và đi ngang.

## 6. Thử giao dịch bằng UAT/demo

UAT có dữ liệu thị trường và cặp API key/secret riêng; key UAT không dùng được
trên production và ngược lại. Dùng UI để thử an toàn:

1. Mở `http://127.0.0.1:8787`.
2. Chọn **UAT**.
3. Nhập API key và API secret UAT.
4. Kiểm tra tài khoản và số dư trước.
5. Lấy Trading Token bằng OTP UAT.
6. Đặt lệnh với khối lượng nhỏ nhất được UAT hỗ trợ, rồi kiểm tra trạng thái và
   hủy/đóng lệnh.

Không thay URL production trong `.env` bằng URL UAT trừ khi bạn đồng thời thay
cả API key và API secret sang bộ key UAT.

## 7. An toàn và xử lý lỗi

- Không chia sẻ API secret, OTP hoặc Trading Token.
- Máy tính cần đúng giờ; DNSE yêu cầu `Date` gần với giờ hệ thống của họ.
- Dùng `Production` chỉ khi đã hoàn tất UAT. Lệnh trên production có thể dùng
  tiền thật.
- Nếu gặp lỗi xác thực, kiểm tra API key/secret thuộc đúng môi trường và không
  dùng lại Trading Token đã hết hạn.
- Nếu UI không mở được, chạy lại `ui/server.py` và vào đúng địa chỉ
  `http://127.0.0.1:8787`.
- Nếu thiếu thư viện, chạy lại lệnh cài đặt trong phần 1.

## Tài liệu liên quan

- [Triển khai Vercel chỉ đọc / backtest](deployment/VERCEL.md)
- [Xác thực DNSE OpenAPI](https://developers.dnse.com.vn/docs/guide/intro/authentication/)
- [Dữ liệu thị trường DNSE](https://developers.dnse.com.vn/docs/dnse/market-data/)
- [Hướng dẫn UI chi tiết](python/ui/README.md)
- [Ví dụ Python](python/examples/README.md)
