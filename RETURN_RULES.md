# Return Analytics Rules

The dashboard now applies these rules to Amazon Returns reports:

1. Same **Order ID + ASIN** is treated as one unique return. Duplicate rows do not increase return count.
2. Return requests whose `return_request_status` contains **Closed** are excluded from return analytics.
3. For duplicate Order ID + ASIN rows, a non-zero `refunded_amount` is preferred and counted only once. If all duplicate rows have no refund, the return is still counted once with refund amount 0.
4. Safe-T reimbursement is tracked separately using `safet_claim_reimbursement_amount` and counted once per Order ID + ASIN. Safe-T amounts are not added to customer refunded amount.
5. Safe-T claims are reported by ASIN and amount.
6. Location, state, city, pincode, reason, ASIN and return-rate analytics all use the same duplicate-safe return dataset.

After replacing the files, restart Streamlit and upload the Returns report again if you need the new `return_request_status` column populated in an older database.
