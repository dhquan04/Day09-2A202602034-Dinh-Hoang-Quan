# BÁO CÁO CÁ NHÂN — DAY 09 MULTI-AGENT A2A

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
| --- | --- |
| Họ và tên | Đinh Hoàng Quân |
| MSSV | 2A202602034 |
| Lớp | K4-E402 |
| Vai trò | Thiết kế, triển khai và kiểm thử pipeline multi-agent |
| Ngày hoàn thành | 05/08/2026 |

## 2. Mục tiêu bài làm

Hệ thống điều tra 50 yêu cầu hỗ trợ thương mại điện tử trên dữ liệu Olist. Kết
luận không được sao chép hoặc tin trực tiếp nội dung người dùng cung cấp. Mỗi
case phải được truy xuất lại từ CSV, đối chiếu order, customer, item, seller,
product, giao vận và payment trước khi áp dụng `EC_POLICY_V2`.

Kết quả của mỗi case gồm issue chính, các issue liên quan, entity bị ảnh hưởng,
ngữ cảnh khách hàng/sản phẩm, phân tích giao vận, đối soát thanh toán, nguyên
nhân, bằng chứng, bên chịu trách nhiệm, tiền hoàn và action xử lý.

## 3. Kiến trúc multi-agent

Pipeline sử dụng các agent chuyên biệt và gọi API OpenRouter bằng model
`meta-llama/llama-3.1-8b-instruct` (8B tham số, không vượt giới hạn 10B):

1. `CustomerAgent`: xác minh `customer_unique_id` và các order khác của khách.
2. `OrderProductAgent`: lấy toàn bộ item, seller, product và category liên quan.
3. `PaymentAgent`: đối soát tất cả payment row với item và freight.
4. `DeliveryAgent`: tính độ trễ giao hàng và độ trễ bàn giao của từng seller.
5. `CanceledOrderIssueAgent`: chỉ kiểm tra đơn canceled đã thanh toán.
6. `UnavailableOrderIssueAgent`: chỉ kiểm tra đơn unavailable đã thanh toán.
7. `LateDeliverySellerIssueAgent`: chỉ kiểm tra giao trễ do seller bàn giao muộn.
8. `LateDeliveryLogisticsIssueAgent`: chỉ kiểm tra giao trễ do logistics.
9. `ValidSplitPaymentIssueAgent`: chỉ kiểm tra split payment đã đối soát đúng.
10. `UnsupportedLateClaimIssueAgent`: chỉ kiểm tra claim giao trễ bị dữ liệu bác bỏ.
11. `PolicyCoordinatorAgent`: dừng tại issue agent đầu tiên khớp theo priority,
    sau đó tính cause, responsibility, refund và actions.
12. `VerifierAgent`: tính lại kết quả từ CSV, từ chối dữ liệu sai hoặc không có
   bằng chứng trước khi Coordinator ghi file.

Model được sử dụng để review evidence và handoff giữa các agent. Các phép tính
số học và luật quyết định được viết bằng hàm Python rõ ràng để tránh LLM tính
sai, tự tạo dữ liệu hoặc thay đổi thứ tự nghiệp vụ.

## 4. Các hàm tính toán

Các hàm thuần trong `src/calculations.py`:

- `calculate_hours_between(later, earlier)`:
  tính chênh lệch timestamp theo giờ và làm tròn hai chữ số.
- `calculate_payment_reconciliation(items, payments)`:
  tính `item_total_brl`, `freight_total_brl`, `expected_total_brl`,
  `payment_total_brl`, `difference_brl` và `reconciled`.
- `calculate_seller_handoff_analysis(order, items)`:
  so sánh thời điểm carrier nhận hàng với `shipping_limit_date` sớm nhất của
  từng seller.
- `calculate_delivery_analysis(order, items)`:
  tổng hợp timestamp, delivery variance, seller handoff và seller bàn giao muộn.

Các công thức chính:

```text
delivery_variance_hours
  = order_delivered_customer_date - order_estimated_delivery_date

handoff_variance_hours
  = order_delivered_carrier_date - shipping_limit_date sớm nhất của seller

expected_total_brl
  = sum(order_items.price) + sum(order_items.freight_value)

difference_brl
  = sum(order_payments.payment_value) - expected_total_brl

reconciled
  = abs(difference_brl) <= 0.10 BRL
```

Khi order không có item, tổng item và freight bằng `0.0`; expected total,
difference và reconciled giữ `null` vì không có item ledger để đối soát. Timestamp
không tồn tại và variance không đủ timestamp cũng giữ `null`, tránh biến dữ liệu
không xác định thành một sự kiện có giá trị bằng zero.

## 5. Thứ tự nghiệp vụ EC_POLICY_V2

Hàm `classify_primary_issue()` trong `src/issue_rules.py` sử dụng first-match:

1. `canceled_order_paid`
2. `unavailable_order_paid`
3. `late_delivery_seller`
4. `late_delivery_logistics`
5. `valid_split_payment`
6. `unsupported_late_claim`

Thứ tự này là bắt buộc. Ví dụ, một order đã bị hủy và đã thanh toán phải được
xử lý hoàn toàn bộ payment trước khi xét giao vận hoặc split payment. Với order
giao trễ, hệ thống phải kiểm tra seller có bàn giao sau hạn hay không trước khi
quy trách nhiệm cho logistics. Đổi thứ tự có thể làm sai primary issue, bên chịu
trách nhiệm và số tiền hoàn.

Hàm `evaluate_issue_rules()` tính độc lập điều kiện kiểm chứng của cả sáu rule.
Mỗi issue agent chỉ nhận các fact cần cho đúng một nghiệp vụ và trả về `matches`.
`PolicyCoordinatorAgent` gọi các agent theo priority, dừng ở agent đầu tiên khớp
và đối chiếu với `classify_primary_issue()` trước khi tính khoản hoàn tiền.

Sau primary issue, hàm `calculate_secondary_issues()` thêm các issue liên quan
theo thứ tự: multi-item, multi-seller, split payment, repeat customer và multiple
categories. Hàm `calculate_resolution_actions()` tạo action chính trước, sau đó
mới thêm các action bổ sung theo policy.

## 6. Kiểm chứng đầu ra

`VerifierAgent.verify()` kiểm tra schema, giới hạn mảng, confidence, evidence ID
và quan hệ giữa refund với case status.

`VerifierAgent.verify_against_source_data()` độc lập tính lại từ CSV:

- Primary issue và secondary issues.
- Order, item, seller và payment ID.
- Customer history qua `customer_unique_id`.
- Product ID và category gốc, không dịch dữ liệu.
- Delivery variance và seller handoff variance.
- Tất cả tham số đối soát thanh toán.
- Root cause, responsible party và evidence.
- Recommended refund và resolution actions.

Nếu bất kỳ trường nào khác dữ liệu nguồn hoặc sai thứ tự policy, verifier ném
`VerificationError` và case không được ghi ra `output/`.

## 7. Handoff và trace

Luồng xử lý một case:

```text
Coordinator
  → CustomerAgent
  → OrderProductAgent
  → PaymentAgent
  → DeliveryAgent
  → CanceledOrderIssueAgent
  → UnavailableOrderIssueAgent (nếu rule trước không khớp)
  → LateDeliverySellerIssueAgent (nếu chưa khớp)
  → LateDeliveryLogisticsIssueAgent (nếu chưa khớp)
  → ValidSplitPaymentIssueAgent (nếu chưa khớp)
  → UnsupportedLateClaimIssueAgent (nếu chưa khớp)
  → PolicyCoordinatorAgent
  → VerifierAgent
  → output/EC_xxx.json
```

Mỗi specialist gửi evidence có cấu trúc cho agent tiếp theo và gọi OpenRouter để
review domain của mình. Lượt chạy mới ghi đè `logging/trace.jsonl`, không append
trace cũ. `logging/metadata.json` ghi model, kích thước 8B, framework, runtime và
số case đã xử lý.

## 8. Kết quả kiểm thử

- Xử lý đủ 50 input từ `EC_001.json` đến `EC_050.json`.
- Kiểm tra source với toàn bộ output bằng verifier dữ liệu nguồn.
- Thử cố tình sửa `difference_brl` của một case và verifier đã từ chối.
- Model được khai báo trực tiếp trong source và có guard `8B <= 10B`.
- API key chỉ nằm trong `.env`, không được ghi vào source, trace hoặc output ZIP.
- File nộp chỉ chứa thư mục `output/` với đúng 50 JSON.

## 9. Công việc cá nhân đã thực hiện

- Xây dựng repository loader và các index phục vụ join dữ liệu Olist.
- Thiết kế các specialist agent và cấu trúc handoff.
- Tích hợp OpenRouter Chat Completions API với Llama 3.1 8B.
- Viết các hàm tính toán giao vận, thanh toán và phân loại policy.
- Viết verifier đối chiếu trực tiếp JSON đầu ra với CSV.
- Xử lý UTF-8 BOM bằng `utf-8-sig` và giữ nguyên category tiếng Bồ Đào Nha.
- Xử lý đúng order không có item và các trường không đủ dữ liệu để tính.
- Tạo trace, metadata, 50 output JSON và file ZIP nộp bài.

## 10. Cam kết

- [x] Tôi có thể giải thích luồng dữ liệu từ input đến output.
- [x] Kết luận được kiểm chứng từ CSV, không tin trực tiếp lời người dùng.
- [x] Các phép tính và thứ tự nghiệp vụ được thể hiện bằng hàm trong source.
- [x] Model sử dụng có 8B tham số, không vượt giới hạn 10B.
- [x] Không đưa API key hoặc secret vào source, log hay output ZIP.

**Họ và tên:** Đinh Hoàng Quân

**MSSV:** 2A202602034

**Ngày xác nhận:** 05/08/2026
