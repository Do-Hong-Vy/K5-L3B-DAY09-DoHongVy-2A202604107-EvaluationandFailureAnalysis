# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (backend REPLAY, verdict của judge lưu sẵn trong CSV). Lớp dương = `FAIL`, vì việc của judge là tìm lỗi.

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | **Đạt** · confusion tp=24 fp=4 fn=6 tn=66 | **dùng**, chỉ để theo dõi, không chặn tiền/approval |
| helpful | 100 | 0.375 | 1.000 | 0.300 | **Không đạt** (κ và R dưới sàn) · tp=9 fp=0 fn=21 tn=70 | **loại** |

Tỉ lệ lỗi sau hiệu chỉnh Rogan-Gladen:
- tone: quan sát 0.28 → hiệu chỉnh **0.30** (sens 0.8, spec 66/70 = 0.943).
- helpful: quan sát 0.09 → hiệu chỉnh **0.30** (sens 0.3, spec 1.0). Judge helpful báo ít hơn tỉ lệ lỗi thật hơn 3 lần.

## Audit thủ công 10 bất đồng của tone_ok (đọc toàn bộ, không chỉ 5)
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | Người | Xưng "em" + "nha" quá suồng sã. Rubric thêm: "xưng hô LogiX/anh-chị; cấm em/bạn/nha/nhé với khách khiếu nại". |
| 2 | H-017 "Dạ, bạn ơi LogiX đã hoàn 25.000đ…" | PASS | FAIL | Người | Cùng lỗi xưng hô ("bạn ơi"), dùng cùng điều khoản ở #1. Thêm ví dụ âm vào few-shot. |
| 3 | H-029 "Dạ, vui lòng chờ… không cần nhắn thêm." | PASS | FAIL | Người | Judge bị đánh lừa bởi từ lịch sự bề mặt. Rubric: "câu mệnh lệnh / chặn khách liên hệ = FAIL dù có 'Dạ', 'vui lòng'". |
| 4 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Judge phạt vì thiếu xin lỗi. Rubric: "xin lỗi không bắt buộc khi yêu cầu đã được giải quyết; ngắn mà đủ ý = PASS". |
| 5 | H-051 "LogiX đã refund 90.000đ…" | FAIL | PASS | Người | Style guide CS LogiX cho phép từ "refund". Đưa danh sách từ tiếng Anh được phép vào rubric. |
| 6 | H-063 "…đã hoàn 20.000đ và sẽ hoàn thêm…" | PASS | FAIL | Người | Hứa ngoài kết quả hệ thống. Đây là **lỗi nội dung** chứ không phải giọng điệu: chuyển sang grader code (so số tiền và cam kết với ledger, như FM-08), bỏ khỏi phạm vi tone. |
| 7 | H-070 "…đã hoàn 90.000đ… 😂😂" | PASS | FAIL | Người | Rubric: "emoji cười trong ngữ cảnh khiếu nại = FAIL". Cũng kiểm được bằng regex. |
| 8 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn…" | FAIL | PASS | **Judge** | Người gán nhãn đọc nhầm ticket. **Sửa nhãn người** thành FAIL trong bản CSV tiếp theo, không sửa rubric. |
| 9 | H-088 "Dạ, dạ, LogiX đã hoàn 40.000đ…" | FAIL | PASS | Người (tranh cãi) | Lặp "Dạ" do gõ nhầm, không phải giọng điệu xấu. Rubric: "lỗi chính tả/lặp từ nhỏ không làm FAIL tone". Gắn cờ để 2 người gán nhãn thống nhất. |
| 10 | H-094 "Da, LogiX da hoan 40.000đ… (mất dấu)" | PASS | FAIL | Người | Rubric: "tiếng Việt không dấu / dịch máy = FAIL". Thêm kiểm tra tỉ lệ ký tự có dấu bằng code. |

Tổng hợp: người đúng 8/10, judge đúng 1/10 (H-081), 1 ca tranh cãi (H-088). Lỗi hệ thống của judge: (a) **chấm theo từ khoá lịch sự bề mặt** (#1–3, #10), (b) **phạt theo luật không có trong style guide** (#4, #5). Sửa rubric: thêm danh sách xưng hô bị cấm, mục "câu mệnh lệnh", whitelist từ tiếng Anh, bỏ yêu cầu xin lỗi bắt buộc, kèm 4 ví dụ âm/dương lấy từ chính các case này.

## Vì sao không dùng judge `helpful` làm gate (dẫn ma trận nhầm lẫn)
- fn = 21 trên 30 ca người chấm FAIL: judge **bỏ sót 70% lỗi** (R = 0.3). 18/21 ca bỏ sót có `human_failure = "sai tiền"`, ví dụ HL-015 "đã hoàn 55.000đ", ledger ghi 40.000đ. Judge chỉ đọc reply, **không thấy ledger**, và còn bị câu xin lỗi dài làm "trông hữu ích" (HL-016, HL-028, HL-043…). 3 ca còn lại sai xưng hô ("Ok bạn…", HL-047/091/097).
- P = 1.0 chỉ vì judge gần như không bao giờ nói FAIL (9/100). Nhìn P mà không nhìn R sẽ tưởng judge rất tốt. κ = 0.375 cho thấy mức đồng thuận vượt ngẫu nhiên thấp.
- Dùng judge này làm gate thì một PR làm reply sai tiền vẫn xanh. Vì vậy phần "sai tiền" được chấm bằng **code**: `reply_amount_matches_ledger` (FM-08, blocking, min 1.0). Phần xưng hô chuyển sang tiêu chí tone (đã đạt FLOORS) hoặc regex.

## Kết luận
- **Bị loại:** `helpful` (κ 0.375 < 0.6, R 0.30 < 0.7). Nó hỏng chính ở nhóm lỗi quan trọng nhất (tiền).
- **Dùng có điều kiện:** `tone_ok`, chỉ làm metric theo dõi (non-blocking) cho chất lượng giọng điệu. Tiền và approval luôn chấm bằng code.
- **Rủi ro còn lại:** judge chỉ được kiểm trên 100 dòng replay đã công khai, và chính các dòng này được dùng để sửa rubric. Sau khi sửa rubric phải đo lại trên **bộ nhãn người mới (held-out)**, nếu không thì κ đang bị overfit. Nhãn người cũng có lỗi (H-081), nên cần 2 người gán nhãn độc lập và đo κ giữa người với người làm trần.
