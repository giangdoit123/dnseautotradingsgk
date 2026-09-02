# Triển khai Vercel (chỉ đọc / backtest)

Vercel phù hợp để xem dữ liệu DNSE, WebSocket ngắn và chạy backtest. Không dùng
nó để gửi lệnh thật: Function có thể khởi động lại bất kỳ lúc nào nên không giữ
được Trading Token một cách tin cậy; đồng thời endpoint web không nên là nơi
thực thi giao dịch có tiền thật. Dùng gói Docker riêng tư trong thư mục này cho
phần giao dịch, qua VPN hoặc SSH tunnel.

## Biến môi trường bắt buộc

Trong **Vercel → Project → Settings → Environment Variables**, thêm các biến
sau cho Production (và Preview nếu muốn thử Preview):

| Tên | Giá trị |
| --- | --- |
| `DNSE_UI_ACCESS_TOKEN` | Một mật khẩu dài, ngẫu nhiên, chỉ bạn biết. |
| `DNSE_API_KEY` | API key DNSE, không đưa vào mã nguồn. |
| `DNSE_API_SECRET` | API secret DNSE, không đưa vào mã nguồn. |
| `DNSE_BASE_URL` | `https://openapi-uat.dnse.com.vn` khi thử UAT, hoặc URL production DNSE. |
| `DNSE_WS_URL` | `wss://ws-openapi-uat.dnse.com.vn` khi thử UAT, hoặc URL WebSocket production DNSE. |
| `DNSE_API_VERSION` | Phiên bản API DNSE, hiện dùng `2026-07-23`. |

Mở trang Vercel, nhập `DNSE_UI_ACCESS_TOKEN` tại **Mã truy cập** rồi nhấn
**Enter** để nạp dashboard. Mã truy cập không được lưu trong mã nguồn hay trình
duyệt.

## Thiết lập lần đầu

1. Trên Vercel, chọn **Add New → Project** và import repository GitHub này.
2. Giữ **Root Directory** là thư mục gốc repository; không đặt thành `python`.
3. Vercel tự nhận các Python Functions trong `api/`; không cần Build Command.
4. Thêm toàn bộ biến môi trường ở trên, triển khai và mở domain. Nếu domain cũ
   vẫn trả `404`, vào **Settings → Domains** để gán nó cho đúng project, rồi
   Redeploy bản mới nhất.

## Cập nhật sau này

Mỗi lần push commit vào nhánh `main`, Vercel tự tạo Production Deployment mới.
Vào tab **Deployments** để xem log; khi trạng thái là **Ready**, mở domain và
kiểm tra lại trang. Thay đổi Environment Variables cần một lần **Redeploy** để
áp dụng.
