"""
mock_wallet.py
بيانات ودوال وهمية تحاكي محفظة إلكترونية عراقية (بأسلوب زين كاش).
هذي الدوال تستخدم كـ "tools" يستدعيها الوكيل الذكي عبر Groq function calling.
"""

from datetime import datetime

# الرصيد الحالي للمستخدم (بالدينار العراقي)
USER_BALANCE = 250_000

# جهات الاتصال المسجلة بالمحفظة
# ملاحظة: تعمّدنا وضع اسمين بنفس الاسم الأول (احمد) لاختبار حالة التشابه بالأسماء
CONTACTS = {
    "احمد كريم": {"phone": "07901234567"},
    "احمد جبار": {"phone": "07711223344"},
    "علي": {"phone": "07709876543"},
    "زهراء": {"phone": "07801112233"},
    "مريم": {"phone": "07501234499"},
}

# الجهات المتاحة لدفع الفواتير
BILLERS = {
    "زين": {"type": "رصيد هاتف"},
    "كهرباء": {"type": "فاتورة كهرباء"},
    "انترنت": {"type": "فاتورة انترنت"},
}

# سجل العمليات (يمتلئ أثناء تشغيل البرنامج)
TRANSACTION_HISTORY = []


def get_balance() -> dict:
    """يرجع الرصيد الحالي للمستخدم."""
    return {"balance": USER_BALANCE, "currency": "IQD"}


def find_contact(name: str) -> dict | None:
    """
    يبحث عن جهة اتصال بالاسم.
    - تطابق تام (الاسم الكامل) -> يرجعها مباشرة.
    - تطابق جزئي وحيد -> يرجعها.
    - تطابق جزئي لأكثر من جهة (مثلاً "احمد" يطابق "احمد كريم" و"احمد جبار")
      -> يرجع {"ambiguous": True, "matches": [...]} بدل ما يخمن وحدة عشوائي.
    - ما كو أي تطابق -> يرجع None.
    """
    name = name.strip()

    # تطابق تام بالاسم الكامل
    if name in CONTACTS:
        return {"name": name, **CONTACTS[name]}

    # تطابق جزئي (يدعم البحث بالاسم الأول بس)
    matches = [
        contact_name
        for contact_name in CONTACTS
        if name in contact_name or contact_name in name
    ]

    if len(matches) == 1:
        return {"name": matches[0], **CONTACTS[matches[0]]}

    if len(matches) > 1:
        return {"ambiguous": True, "matches": matches}

    return None


def transfer_money(contact_name: str, amount: float) -> dict:
    """يحول مبلغ لجهة اتصال، ويتحقق من الرصيد ووجود الجهة أولاً."""
    global USER_BALANCE

    if amount <= 0:
        return {"success": False, "message": "المبلغ لازم يكون أكبر من صفر."}

    contact = find_contact(contact_name)
    if not contact:
        return {
            "success": False,
            "message": f"ما لكيت جهة اتصال بهذا الاسم: {contact_name}",
        }

    if contact.get("ambiguous"):
        options = "، ".join(contact["matches"])
        return {
            "success": False,
            "message": f"في أكثر من جهة اتصال بهذا الاسم: {options}. حدد الاسم الكامل حتى أكمل التحويل.",
        }

    if amount > USER_BALANCE:
        return {
            "success": False,
            "message": f"الرصيد غير كافي. رصيدك الحالي {USER_BALANCE:,} دينار.",
        }

    USER_BALANCE -= amount
    TRANSACTION_HISTORY.append(
        {
            "type": "تحويل",
            "to": contact["name"],
            "amount": amount,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
    )

    return {
        "success": True,
        "message": f"تم تحويل {amount:,} دينار إلى {contact['name']} بنجاح.",
        "new_balance": USER_BALANCE,
    }


def pay_bill(biller_name: str, amount: float) -> dict:
    """يدفع فاتورة لجهة معينة (زين، كهرباء، انترنت...)."""
    global USER_BALANCE

    if amount <= 0:
        return {"success": False, "message": "المبلغ لازم يكون أكبر من صفر."}

    biller_name = biller_name.strip()
    biller = BILLERS.get(biller_name)
    if not biller:
        available = "، ".join(BILLERS.keys())
        return {
            "success": False,
            "message": f"ما أعرف هذي الجهة. الجهات المتوفرة: {available}",
        }

    if amount > USER_BALANCE:
        return {
            "success": False,
            "message": f"الرصيد غير كافي. رصيدك الحالي {USER_BALANCE:,} دينار.",
        }

    USER_BALANCE -= amount
    TRANSACTION_HISTORY.append(
        {
            "type": "دفع فاتورة",
            "biller": biller_name,
            "amount": amount,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
    )

    return {
        "success": True,
        "message": f"تم دفع {amount:,} دينار لـ {biller_name} بنجاح.",
        "new_balance": USER_BALANCE,
    }


def get_transaction_history(limit: int = 5) -> dict:
    """يرجع آخر العمليات (افتراضياً آخر 5)، الأحدث أولاً."""
    return {"transactions": TRANSACTION_HISTORY[-limit:][::-1]}