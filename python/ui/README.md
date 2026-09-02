# DNSE Control Center

Giao diện cục bộ dùng API key và API secret nhập trực tiếp trên màn hình. Hai giá trị này chỉ nằm trong bộ nhớ của tiến trình Python hiện tại, không ghi vào tệp `.env` hay gửi tới bất kỳ máy chủ nào ngoài DNSE.

## Chạy

```powershell
cd python
.\.venv\Scripts\python.exe -X utf8 ui/server.py
```

Mở `http://127.0.0.1:8787`, nhập API key, API secret, chọn Production hoặc UAT, rồi bấm **Kết nối**. UI sẽ tự xác thực và chọn tiểu khoản giao dịch (`dealAccount`) nếu có.

## Sử dụng

- Dùng mục **Backtest trực quan** sau khi kết nối để chọn mã, thị trường, khung
  nến 1/3 phút, khoảng thời gian, phí và trượt giá. UI lấy nến trực tiếp từ
  endpoint OHLC của DNSE; phần Nguồn dữ liệu giải thích chính xác truy vấn nến
  giao dịch, nến ngày dùng cho RSI và quy tắc mô phỏng khớp lệnh.
- Biểu đồ hiển thị nến, Base Line 129, mây Kumo, tam giác điểm vào và vòng tròn
  điểm thoát. Bảng bên dưới biểu đồ liệt kê toàn bộ lệnh cùng lý do thoát và
  lãi/lỗ. Khi có quá nhiều nến, UI gộp chúng chỉ để vẽ nhanh, còn điểm vào/thoát
  vẫn được đặt theo thời gian dữ liệu gốc.
- Chọn chức năng ở cột trái và điền các trường nghiệp vụ hiển thị sẵn.
- UI tự tạo chữ ký, `Date`, nonce, version, query, body, và header cần thiết.
- Chọn **Gửi Email OTP**, sau đó **Lấy Trading Token**. Token được giữ trong bộ nhớ UI và tự dùng cho đặt/sửa/hủy lệnh hoặc đóng vị thế.
- Các thao tác làm thay đổi giao dịch cần tích xác nhận trước khi gửi.

Máy chủ chỉ lắng nghe tại `127.0.0.1`, nên chỉ máy tính đang chạy UI mới truy cập được.
