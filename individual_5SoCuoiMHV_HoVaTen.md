# Member Role Report — Day 9: Multi-Agent A2A

> Điền họ tên, MSSV và lớp trước khi nộp. Các nội dung kỹ thuật dưới đây phản
> ánh pipeline hiện có trong repository.

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
| --- | --- |
| Họ và tên | [Họ và tên] |
| MSSV | [MSSV] |
| Khóa/Lớp | K4 |
| Vai trò chính | Thiết kế và tích hợp pipeline multi-agent |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

| Module/deliverable | File phụ trách | Input | Output | Trạng thái |
| --- | --- | --- | --- | --- |
| Điều phối và xuất kết quả | `src/main.py` | 50 JSON case, các handoff | 50 JSON theo schema | Hoàn thành |
| Agent nghiệp vụ | `src/agents.py`, `src/policy.py` | Olist CSV | Evidence, quyết định policy | Hoàn thành |
| Kiểm tra và audit | `src/verifier.py`, `logging/` | Kết quả đã tổng hợp | Validation, trace, metadata | Hoàn thành |

## 3. Kết quả theo vai trò

Pipeline xử lý toàn bộ 50 case từ `input/` và tạo kết quả trong `output/`.
Lần chạy gần nhất sinh 50 dòng trace, mỗi dòng thể hiện chuỗi handoff:
CustomerAgent → OrderProductAgent → PaymentAgent → DeliveryAgent → PolicyAgent
→ VerifierAgent.

Xác minh:

```powershell
.\.venv\Scripts\python.exe -m src.main
```

Kết quả mong đợi: có 50 file `EC_001.json` đến `EC_050.json`, 50 dòng trong
`logging/trace.jsonl`, và `cases_processed: 50` trong `logging/metadata.json`.

## 4. Giải thích kỹ thuật

### Vấn đề giải quyết

Mỗi khiếu nại cần kết hợp nhiều bảng Olist thay vì suy luận chỉ từ lời nhắn
khách hàng. Pipeline xác định trách nhiệm, hoàn tiền và bằng chứng có thể dựng
lại từ CSV.

### Cách triển khai

`OlistRepository` đọc và lập chỉ mục các CSV theo các khóa join. Các agent
domain chỉ trả về dữ kiện của domain mình. `PolicyAgent` áp dụng thứ tự ưu tiên
`EC_POLICY_V2`; mỗi specialist đồng thời gọi OpenRouter bằng Llama 3.1 8B và
handoff JSON review sang PolicyAgent. `VerifierAgent` kiểm tra giới hạn mảng,
confidence, prefix evidence và sự nhất quán giữa refund với case status trước khi ghi file.

| Thành phần | Mô tả |
| --- | --- |
| Input | Một `EC_xxx.json` chứa `claimed_order_id` |
| Output | Một JSON đúng output schema của README |
| Phụ thuộc | 9 CSV Olist trong `data/` |
| Bên dùng output | `output/` để nén nộp; `logging/` để audit |
| Điều kiện lỗi | Order không tồn tại, schema thiếu trường, output vượt giới hạn hoặc evidence sai prefix |

## 5. Quyết định kỹ thuật quan trọng

- **Bối cảnh:** cần phân tích có thể kiểm chứng cho tất cả case.
- **Phương án cân nhắc:** dùng LLM để suy luận tự do; hoặc dùng agent chuyên
  biệt áp dụng quy tắc deterministic trên CSV.
- **Phương án chọn:** agent deterministic theo `EC_POLICY_V2`.
- **Lý do:** công thức hoàn tiền, timestamp, evidence ID và thứ tự ưu tiên đều
  đã được xác định trong đề; cách này tránh tạo ra sự kiện không có trong dữ liệu.
- **Bằng chứng:** mỗi output có evidence ID, đồng thời trace ghi nhận chuỗi
  handoff và verifier hoàn tất trước khi file được ghi.

## 6. Lỗi hoặc blocker đã xử lý

- **Triệu chứng:** đọc bảng `product_category_name_translation.csv` gây lỗi
  không tìm thấy cột `product_category_name`.
- **Nguyên nhân gốc:** file có UTF-8 BOM ở header.
- **Cách xử lý:** CSV loader sử dụng encoding `utf-8-sig`, tương thích cả UTF-8
  thường lẫn UTF-8 có BOM.
- **Xác minh:** chạy `python -m src.main` thành công và sinh đủ 50 output.

## 7. Luồng end-to-end

1. Coordinator đọc case và xác nhận `claimed_order_id` trong `orders`.
2. Customer, order/product, payment và delivery agent tra cứu các bảng liên
   quan, sau đó handoff facts có cấu trúc.
3. PolicyAgent xác định primary issue theo ưu tiên, rồi thêm secondary issues,
   bên chịu trách nhiệm, refund và actions.
4. VerifierAgent chặn output không hợp lệ; kết quả hợp lệ được ghi vào
   `output/`, trace mới nhất thay thế trace cũ và metadata ghi runtime.

## 8. Cam kết

- [ ] Tôi đã thay phần thông tin cá nhân ở mục 1 trước khi nộp.
- [x] Tôi có thể giải thích luồng dữ liệu Olist từ input đến output.
- [x] Các kết quả chạy đã được xác minh bằng lệnh trong mục 3.
- [x] Repository không đưa API key hoặc secret vào source/log.

**Họ và tên:** [Họ và tên]
**Ngày xác nhận:** [YYYY-MM-DD]
