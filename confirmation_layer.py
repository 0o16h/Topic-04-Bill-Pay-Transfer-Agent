"""
confirmation_layer.py
======================
طبقة التأكيد الصريح + منع الدفع المزدوج (Idempotency).

الشرطين من البريف:
1) "Nothing executes without an explicit confirmation step"
2) "Retries never cause a double payment"

التصميم:
--------
prepare_*  : يتحقق ويجهز العملية بدون تنفيذ. نفس العملية (نوع + جهة + مبلغ)
             تنطي نفس pending_id حتى لو انطلب التحضير مرتين.
confirm_*  : التنفيذ الفعلي. كل pending_id ينفذ مرة وحدة بس، وأي تأكيد مكرر
             يرجع النتيجة الأصلية بدون ما ينخصم شي إضافي.
_LOCK      : يمنع تنفيذ نفس العملية مرتين إذا وصلت طلبات متزامنة.

طبقات الحماية من الدفع المزدوج:
  1. تأكيد مكرر لنفس pending_id   -> يرجع النتيجة المحفوظة (EXECUTED_ACTIONS)
  2. تحضير مكرر لنفس العملية      -> يرجع نفس pending_id (fingerprint)
  3. عملية مشابهة نفذت قبل شوي    -> تنبيه بسؤال التأكيد (بدون منع)
  4. طلبات متزامنة                -> قفل threading.RLock
"""

import threading
import time
import uuid

import mock_wallet as wallet

PENDING_TTL_SECONDS = 120        # صلاحية العملية المعلقة
DUPLICATE_WINDOW_SECONDS = 300   # نافذة تنبيه العملية المشابهة (5 دقايق)

PENDING_ACTIONS: dict = {}       # {pending_id: {...}}
EXECUTED_ACTIONS: dict = {}      # {pending_id: {"result", "fingerprint", "executed_at"}}
_LOCK = threading.RLock()

# عداد أدوار المحادثة: كل رسالة من المستخدم = دور جديد.
# يستخدم لمنع تأكيد العملية بنفس الدور اللي انجهزت بيه (بدون رد المستخدم).
_CURRENT_TURN = 0


def begin_turn() -> None:
    """يستدعيه main.py مع كل رسالة جديدة من المستخدم."""
    global _CURRENT_TURN
    with _LOCK:
        _CURRENT_TURN += 1


# ---------------------------------------------------------------------------
# أدوات مساعدة
# ---------------------------------------------------------------------------

def _new_pending_id() -> str:
    return uuid.uuid4().hex[:8]


def _fingerprint(action_type: str, target: str, amount: float) -> tuple:
    return (action_type, target, float(amount))


def _cleanup_expired() -> None:
    now = time.time()
    expired = [
        pid for pid, a in PENDING_ACTIONS.items()
        if now - a["created_at"] > PENDING_TTL_SECONDS
    ]
    for pid in expired:
        del PENDING_ACTIONS[pid]


def _register_pending(action: dict) -> str:
    """ينشئ عملية معلقة، أو يرجع الموجودة إذا نفس العملية معلقة أصلاً."""
    fp = action["fingerprint"]
    for pid, existing in PENDING_ACTIONS.items():
        if existing["fingerprint"] == fp:
            existing["created_at"] = time.time()  # نجدد الصلاحية
            existing["turn"] = _CURRENT_TURN      # المستخدم يشوف التأكيد بهذا الدور
            return pid
    pid = _new_pending_id()
    action["created_at"] = time.time()
    action["turn"] = _CURRENT_TURN
    PENDING_ACTIONS[pid] = action
    return pid


def _recent_duplicate_note(fp: tuple) -> str:
    """إذا نفذت عملية مطابقة بالـ5 دقايق الأخيرة، يرجع تنبيه بالعامية."""
    now = time.time()
    for done in EXECUTED_ACTIONS.values():
        if (
            done["fingerprint"] == fp
            and done["result"].get("success")
            and now - done["executed_at"] <= DUPLICATE_WINDOW_SECONDS
        ):
            return " ⚠️ انتبه: نفذت عملية مطابقة قبل شوي. تأكد ما تريد تكررها بالغلط."
    return ""


# ---------------------------------------------------------------------------
# خطوة 1: التحضير (بدون تنفيذ)
# ---------------------------------------------------------------------------

def prepare_transfer(contact_name: str, amount: float) -> dict:
    with _LOCK:
        _cleanup_expired()

        if amount <= 0:
            return {"status": "invalid_amount", "message": "المبلغ لازم يكون أكبر من صفر."}

        contact = wallet.find_contact(contact_name)

        if contact is None:
            return {
                "status": "not_found",
                "message": f"ما لكيت جهة اتصال بهذا الاسم: {contact_name}",
            }

        if contact.get("ambiguous"):
            options = "، ".join(contact["matches"])
            return {
                "status": "ambiguous",
                "message": f"في أكثر من جهة اتصال بهذا الاسم: {options}. حدد الاسم الكامل حتى أكمل التحويل.",
                "matches": contact["matches"],
            }

        if amount > wallet.USER_BALANCE:
            return {
                "status": "insufficient_funds",
                "message": f"الرصيد غير كافي. رصيدك الحالي {wallet.USER_BALANCE:,} دينار.",
            }

        fp = _fingerprint("transfer", contact["name"], amount)
        pending_id = _register_pending(
            {
                "type": "transfer",
                "contact_name": contact["name"],
                "amount": amount,
                "fingerprint": fp,
            }
        )

        return {
            "status": "awaiting_confirmation",
            "pending_id": pending_id,
            "message": (
                f"راح تحول {amount:,} دينار لـ {contact['name']}. "
                f"رصيدك بعد التحويل يصير {wallet.USER_BALANCE - amount:,} دينار. "
                f"تأكد التحويل؟" + _recent_duplicate_note(fp)
            ),
        }


def prepare_pay_bill(biller_name: str, amount: float) -> dict:
    with _LOCK:
        _cleanup_expired()

        if amount <= 0:
            return {"status": "invalid_amount", "message": "المبلغ لازم يكون أكبر من صفر."}

        biller_name = biller_name.strip()
        if not wallet.BILLERS.get(biller_name):
            available = "، ".join(wallet.BILLERS.keys())
            return {
                "status": "not_found",
                "message": f"ما أعرف هذي الجهة. الجهات المتوفرة: {available}",
            }

        if amount > wallet.USER_BALANCE:
            return {
                "status": "insufficient_funds",
                "message": f"الرصيد غير كافي. رصيدك الحالي {wallet.USER_BALANCE:,} دينار.",
            }

        fp = _fingerprint("bill", biller_name, amount)
        pending_id = _register_pending(
            {
                "type": "bill",
                "biller_name": biller_name,
                "amount": amount,
                "fingerprint": fp,
            }
        )

        return {
            "status": "awaiting_confirmation",
            "pending_id": pending_id,
            "message": (
                f"راح تدفع {amount:,} دينار لفاتورة {biller_name}. "
                f"رصيدك بعد الدفع يصير {wallet.USER_BALANCE - amount:,} دينار. "
                f"تأكد الدفع؟" + _recent_duplicate_note(fp)
            ),
        }


# ---------------------------------------------------------------------------
# خطوة 2: التأكيد (التنفيذ الفعلي، مرة وحدة بس) أو الإلغاء
# ---------------------------------------------------------------------------

def confirm_pending_action(pending_id: str) -> dict:
    with _LOCK:
        _cleanup_expired()

        # حماية 1: هذي العملية نفذت من قبل -> نرجع نتيجتها بدون تنفيذ جديد
        done = EXECUTED_ACTIONS.get(pending_id)
        if done:
            return {
                "status": "already_processed",
                "message": "هذي العملية انعالجت من قبل، وما راح تتكرر ولا ينخصم شي إضافي.",
                "original_result": done["result"],
            }

        action = PENDING_ACTIONS.get(pending_id)
        if not action:
            return {
                "status": "expired_or_invalid",
                "message": "ما أكو عملية بهذا الرقم أو خلص وقتها، أعد الطلب من جديد لو سمحت.",
            }

        # حماية التأكيد الصريح: ممنوع التنفيذ بنفس الدور اللي انجهزت بيه العملية.
        # لازم المستخدم يشوف سؤال التأكيد ويرد برسالة جديدة.
        if action["turn"] >= _CURRENT_TURN:
            return {
                "status": "needs_user_confirmation",
                "message": (
                    "ما تكدر تنفذ العملية قبل ما المستخدم يوافق. اعرض عليه سؤال "
                    "التأكيد وانتظر رده بالرسالة الجاية."
                ),
            }

        del PENDING_ACTIONS[pending_id]

        try:
            if action["type"] == "transfer":
                result = wallet.transfer_money(action["contact_name"], action["amount"])
            else:
                result = wallet.pay_bill(action["biller_name"], action["amount"])
        except Exception as e:
            result = {"success": False, "message": f"صار خطأ أثناء التنفيذ: {e}"}

        EXECUTED_ACTIONS[pending_id] = {
            "result": result,
            "fingerprint": action["fingerprint"],
            "executed_at": time.time(),
        }
        return {"status": "executed", **result}


def cancel_pending_action(pending_id: str) -> dict:
    with _LOCK:
        if PENDING_ACTIONS.pop(pending_id, None) is not None:
            return {"status": "cancelled", "message": "زين، ألغيت العملية."}
        return {"status": "not_found", "message": "ما أكو عملية معلقة بهذا الرقم."}