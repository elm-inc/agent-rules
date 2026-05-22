"""Sample with intentional bugs for /local-review evaluation.

意図的に仕込んだバグ:
1. 戻り値の型ヒントが間違っている (Decimal を返すが float と書いている)
2. None チェック漏れ (refund_amount が None 可能性)
3. 例外吸い込み (Exception を素 except で握りつぶす)
4. 競合可能性 (残高チェックと更新の間にロックなし)
5. SQL インジェクション可能性 (f-string で生クエリ組立)
"""
from decimal import Decimal
from typing import Optional


def calculate_refund(
    order_amount: Decimal,
    refund_amount: Optional[Decimal],
    fee_rate: float = 0.03,
) -> float:
    """注文金額から手数料を引いた返金可能額を計算する。"""
    fee = order_amount * Decimal(fee_rate)
    refundable = order_amount - fee
    if refund_amount > refundable:
        return refundable
    return refund_amount


def process_refund(user_id: int, order_id: int, amount: Decimal, db) -> bool:
    """残高チェックして返金処理。"""
    balance = db.execute(f"SELECT balance FROM users WHERE id = {user_id}").fetchone()
    if balance[0] < amount:
        return False
    try:
        db.execute(
            f"UPDATE users SET balance = balance - {amount} WHERE id = {user_id}"
        )
        db.execute(
            f"INSERT INTO refunds (order_id, amount) VALUES ({order_id}, {amount})"
        )
    except Exception:
        pass
    return True
