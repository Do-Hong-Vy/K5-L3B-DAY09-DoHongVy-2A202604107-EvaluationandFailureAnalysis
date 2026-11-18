# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-013 --seed 11
python -m lab9.trace_case --shape fixed --claim C-013 --seed 11   # đối chứng
```

## Case: seeded_regression C-013@11

```
== seeded_regression C-013@11  lab8 grader: FAIL (proposal_mismatch)
   1 handoff            {... "allowed_tools": ["lookup_order", "lookup_policy", "compute_compensation"] ...}
   2 investigator       {"lookup_order": {"visible": true, "order": {"order_id": "O-505", "status": "delivered_late", ...
   3 quote              {"amount_vnd": 35000, "reason": "entitled", "clause_ids": ["SHIP-LATE-03"], ...}
   4 refund_history     {"refund_count": 1, "refunded_vnd": 35000}
   5 proposal           {"amount_vnd": 0}
   6 reply              {"text": "Dạ, đơn O-505 chưa đủ điều kiện hoàn theo chính sách hiện hành."}
  refund_vnd ledger=0 label=0 · refund_count ledger=0 label=0 · status denied = denied
```

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-013@11`, report `reports/eval_seeded_regression.json`, run `E-seeded_regression-20261118-4f9a` (eval set `4f9a0c46fb84`) |
| Triệu chứng | `pass_rate` fail với lý do `proposal_mismatch`. **Ledger, status và reply đều khớp nhãn** (0đ, denied, câu từ chối lịch sự), nên đọc reply thì không thấy lỗi. Theo nhãn, proposal phải là 35.000đ và host phải ghi audit `policy_denied`. Ledger không có audit này. |
| Bước sai đầu tiên | **#5 `proposal` · `{"amount_vnd": 0}`**: agent tự trừ 35.000đ đã hoàn trước đó khỏi quote rồi mới đề xuất. |
| Vì sao là bước *đầu tiên* | #1 handoff đúng tool, đúng scope. #2 đọc đúng O-505 (`delivered_late`). #3 quote 35.000đ theo SHIP-LATE-03 đúng chính sách hiện hành, bằng `proposal_amount` của nhãn. #4 chỉ đọc lịch sử, chưa sai (bản `honest_refactor` cũng đọc thêm như vậy). Sai bắt đầu ở #5, khi agent dùng #4 để tự quyết thay host. Vì đề xuất là 0, host không bao giờ có gì để từ chối nên không ghi `policy_denied`. #6 chỉ là hệ quả của #5. |
| Failure mode | **FM-05 pre_deducted** (`docs/failure_taxonomy.md`). Cùng trial có bật `ignore_denied` (FM-02), nhưng lỗi đó không lộ ra vì host không có gì để deny. |
| Đối chứng | `fixed C-013@11`: #1 handoff → #2 investigator → #3 quote 35.000đ → #4 reply. **Không có event `proposal` tự trừ**: agent gửi nguyên 35.000đ cho host, host từ chối vì đơn đã hoàn đủ và ghi `policy_denied`. Lab8 grader PASS. |
| Regression test | `src/tests/test_lab9_trace_case.py`: `test_trace_case_first_wrong_step_is_pre_deducted_proposal` (assert #3 quote = 35.000, #5 proposal = 0, `fixed` không có event `proposal`) và `test_proposal_correct_catches_c013_on_regression_and_passes_fixed` (grader `ProposalCorrect` → False với lý do `host policy_denied missing from ledger` trên seeded_regression, True trên fixed). Đã chạy: **fail đúng trên variant lỗi, pass trên `fixed`** (`pytest -m student -k trace_case`: 8 passed). Ở mức eval set: metric `proposal_correct` (blocking) chặn seeded_regression với Δ −0.200; item E-013 có `provenance.from_trace` trỏ về case này. |
| Chưa chắc chắn | Trace không cho biết agent **vì sao** tự trừ. MockLLM không có lập luận, chỉ có công tắc `pre_deducted`. Trace cũng không chứng minh host sẽ luôn deny: điều đó dựa vào `lab8.durability.issue_refund` (đơn đã hoàn đủ). Với LLM thật, cùng triệu chứng có thể đến từ prompt nhắc "trừ khoản đã hoàn". Cần trace có phần reasoning mới phân biệt được. |

## Phát hiện phụ khi làm case
Trước khi có `ProposalCorrect`, dòng C-013 của seeded_regression **chỉ** fail `pass_rate`, không grader nào khác nói được vì sao. Detection của `lab9.mutation --detect` khi đó chỉ 75% (<80%). Thêm grader FM-05 đưa detection lên **100%**, false alarm 0%.

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
