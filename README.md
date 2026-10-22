# Nền tảng đặt bàn + gợi ý món (React/TypeScript + FastAPI)

Một nhà hàng, 4 vai trò (khách, quản lý, phục vụ, bếp). Bám theo tài liệu phân tích 10 tuần.

## Chạy nhanh
```bash
docker compose up --build        # PostgreSQL + API :8000 + web :5173
```
Tài khoản demo (seed): `manager@demo.vn`, `waiter@demo.vn`, `kitchen@demo.vn` / mật khẩu `demo1234`. Khách tự đăng ký.

Không dùng Docker:
```bash
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
python -m app.seed && uvicorn app.main:app --reload          # mặc định SQLite dev.db
cd frontend && npm install && npm run dev
pytest                                                       # trong backend/
```
Tài liệu API tự sinh: http://localhost:8000/docs

## Luồng demo trọn vòng
1. Khách đăng ký -> Profile (onboarding 5 câu + đồng ý) -> Đặt bàn -> quét QR cọc.
2. Dev không có tiền thật: gửi webhook giả (xem dưới) -> đặt bàn thành "Đã cọc".
3. Phục vụ: Check-in (tự mở phiên bàn). Quản lý: Bàn & QR -> in mã QR bàn.
4. Khách quét `/t/<token>` -> menu, giỏ chung, gợi ý -> Gửi bếp. Bếp nhận ngay (WebSocket), bấm Bắt đầu/Xong; phục vụ bấm Đã bưng.

```bash
curl -X POST localhost:8000/api/webhooks/sepay -H 'Authorization: Apikey dev-sepay-key' \
  -H 'Content-Type: application/json' \
  -d '{"id": 12345, "transferType": "in", "transferAmount": 100000, "content": "DB1A2B3C4D"}'
```
(`content` = mã thanh toán hiện trên trang cọc, `transferAmount` >= số tiền cọc.)

## Cấu hình thanh toán thật (SePay)
Đặt `SEPAY_API_KEY`, `BANK_CODE`, `BANK_ACCOUNT` trong `.env`; trong SePay trỏ webhook tới `https://<domain>/api/webhooks/sepay`
kiểu xác thực API Key. URL phải truy cập được từ internet (dev: ngrok). Chạy thật nên chuyển sang HMAC-SHA256
(sửa `verify_webhook_auth` trong `services/payment.py`).

## Cấu trúc & điểm chính
| Yêu cầu | Nơi cài đặt |
| --- | --- |
| FR-14/15, NFR-01 chống đặt trùng | `services/booking.py` (khóa dòng bàn + kiểm tra chồng lấn) và ràng buộc `EXCLUDE USING gist` trên PostgreSQL (`main.py`) |
| FR-20..24 cọc VietQR | `services/payment.py`: `transaction_id` UNIQUE, UPDATE có điều kiện trạng thái + số tiền, hàng đợi giao dịch chưa khớp, đối soát `/api/payments/reconcile` |
| FR-26..31 QR + realtime | `routers/ordering.py`, `realtime.py` (phòng `kitchen`, `staff`, `session:<id>`) |
| FR-32..35 gợi ý | `services/recommend.py`: mức 0 phổ biến theo khung giờ có suy giảm, mức 1 content-based, `reason_code`, lọc cứng dị ứng/ăn kiêng |
| FR-05/06, NFR-10 dữ liệu cá nhân | đồng ý riêng, dị ứng mã hóa Fernet, xuất/xóa dữ liệu trong `routers/auth.py` |
| FR-37 dashboard | `routers/insights.py` |

## Việc còn lại / lưu ý
- Chưa có Alembic: `create_all` chỉ dành cho dev; production nên tạo migration (gồm ràng buộc EXCLUDE và unique index phiên bàn).
- Thời gian lưu dạng naive theo giờ Hà Nội (một nhà hàng); mở rộng đa nhà hàng/đa múi giờ cần đổi sang timestamptz.
- Rate limit trong bộ nhớ (một tiến trình); nhiều worker cần Redis.
- Đối soát tự động qua API giao dịch của SePay chưa gọi mạng: endpoint `/api/payments/reconcile` nhận danh sách giao dịch.
- Mức 2 (LightFM) chưa làm, đúng với phương án A trong tài liệu; thêm sau như `level2()` trong `recommend.py`.
- Chưa có refresh token; JWT người dùng hết hạn sau 8 giờ.

## CI/CD (Jenkins + GitHub + IIS)
`Jenkinsfile` + thư mục `deploy/` tự động hóa GitHub -> Jenkins -> Restore -> Build -> Test -> Publish -> Deploy -> Verify
lên `http://localhost/booking` (IIS làm reverse proxy sang FastAPI chạy như dịch vụ Windows). Thiết lập một lần: `deploy\setup-iis.ps1`.
