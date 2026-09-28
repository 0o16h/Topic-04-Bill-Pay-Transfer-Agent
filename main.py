import os
import sys
import json
from dotenv import load_dotenv
from groq import Groq
import arabic_reshaper
from bidi.algorithm import get_display

import mock_wallet as wallet
import confirmation_layer as conf

load_dotenv()

MODEL_NAME = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
TEMPERATURE = float(os.getenv("GROQ_TEMPERATURE", "0.4"))
MAX_TOKENS = int(os.getenv("GROQ_MAX_TOKENS", "1024"))
MAX_TOOL_ROUNDS = 5  # أقصى عدد جولات أدوات بالطلب الواحد

SYSTEM_PROMPT = (
    "أنت مساعد ذكي لمحفظة إلكترونية عراقية (زين كاش). "
    "تحچي بلهجة عراقية سلسة ومباشرة. "
    "\n\n"
    "قاعدة صارمة بخصوص التحويل ودفع الفواتير: لا تنفذ أي عملية تحويل أو دفع فاتورة "
    "مباشرة أبداً. أول شي استخدم prepare_transfer أو prepare_pay_bill حتى تتحقق من "
    "الجهة والرصيد وتجهز العملية بدون تنفيذها. بعدين اعرض على المستخدم بالضبط نص "
    "'message' اللي رجعته الأداة (فيه المبلغ والجهة والرصيد المتوقع بعد العملية) "
    "واسأله يأكد. "
    "لا تستدعي confirm_pending_action بنفس الرد اللي جهزت بيه العملية أبداً؛ لازم تعرض سؤال التأكيد وتنتظر رسالة المستخدم الجاية. ولا تستدعيها إلا بعد ما المستخدم يوافق صراحة بكلمة زي "
    "(اي، أكد، تمام، اوكي، نعم، امشي بيها)، واستخدم نفس pending_id اللي رجعته أداة "
    "prepare_* بالضبط، من غير ما تغيره أو تخترع وحدة جديدة. "
    "إذا المستخدم تراجع أو رفض أو غيّر رايه، استدعي cancel_pending_action بنفس الـ "
    "pending_id بدل ما تسكت أو تتجاهل الطلب. "
    "\n\n"
    "إذا المستخدم يريد يستفسر عن رصيده أو آخر عملياته، استخدم get_balance أو "
    "get_transaction_history. "
    "إذا ناقصك معلومة (متل اسم الشخص أو المبلغ)، اسأل المستخدم قبل ما تستدعي أي أداة. "
    "إذا رجعت لك أداة رسالة تكول في أكثر من جهة اتصال بنفس الاسم، لا تخمن وحدة منهن أبداً — "
    "اذكر الأسماء الكاملة اللي بالرسالة واسأل المستخدم يحدد وحدة منهن. "
    "بعد ما توصلك نتيجة أي أداة، لخصها للمستخدم بأسلوب طبيعي وواضح، وما تخترع أرقام أو "
    "تفاصيل مو موجودة بنتيجة الأداة."
)

# تعريف الأدوات بصيغة JSON schema المتوافقة مع Groq / OpenAI
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_balance",
            "description": "يرجع الرصيد الحالي لمحفظة المستخدم بالدينار العراقي.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "prepare_transfer",
            "description": (
                "يتحقق من جهة الاتصال والرصيد ويجهز عملية تحويل بدون تنفيذها. "
                "يرجع رسالة تأكيد لازم تعرضها على المستخدم قبل أي تنفيذ فعلي."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "contact_name": {
                        "type": "string",
                        "description": "اسم الشخص المراد التحويل له، كما ذكره المستخدم.",
                    },
                    "amount": {
                        "type": "number",
                        "description": "المبلغ المطلوب تحويله بالدينار العراقي.",
                    },
                },
                "required": ["contact_name", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "prepare_pay_bill",
            "description": (
                "يتحقق من الجهة والرصيد ويجهز عملية دفع فاتورة بدون تنفيذها. "
                "يرجع رسالة تأكيد لازم تعرضها على المستخدم قبل أي تنفيذ فعلي."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "biller_name": {
                        "type": "string",
                        "enum": list(wallet.BILLERS.keys()),
                        "description": "اسم الجهة المراد الدفع لها، لازم واحد من القيم المتاحة بالضبط (بالعربي).",
                    },
                    "amount": {
                        "type": "number",
                        "description": "المبلغ المطلوب دفعه بالدينار العراقي.",
                    },
                },
                "required": ["biller_name", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_pending_action",
            "description": (
                "ينفذ فعلياً عملية تحويل أو دفع فاتورة جهزتها prepare_transfer أو "
                "prepare_pay_bill، وذلك فقط بعد موافقة المستخدم الصريحة."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pending_id": {
                        "type": "string",
                        "description": "المعرف اللي رجعته أداة prepare_transfer أو prepare_pay_bill.",
                    },
                },
                "required": ["pending_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_pending_action",
            "description": "يلغي عملية تحويل أو دفع فاتورة كانت جاهزة ولم تنفذ بعد، بناءً على طلب المستخدم.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pending_id": {
                        "type": "string",
                        "description": "المعرف اللي رجعته أداة prepare_transfer أو prepare_pay_bill.",
                    },
                },
                "required": ["pending_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_transaction_history",
            "description": "يرجع آخر عمليات المستخدم (تحويلات ودفع فواتير).",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "عدد آخر العمليات المطلوب عرضها (افتراضياً 5).",
                    }
                },
                "required": [],
            },
        },
    },
]

# ربط اسم الأداة بالدالة الفعلية.
# ملاحظة مهمة: wallet.transfer_money و wallet.pay_bill (التنفيذ الفعلي) غير
# معروضين هنا نهائياً - الموديل ما يكدر يستدعيهم مباشرة. الطريق الوحيد للتنفيذ
# هو confirm_pending_action، اللي يستدعيهم داخلياً بس بعد التأكيد.
AVAILABLE_FUNCTIONS = {
    "get_balance": wallet.get_balance,
    "prepare_transfer": conf.prepare_transfer,
    "prepare_pay_bill": conf.prepare_pay_bill,
    "confirm_pending_action": conf.confirm_pending_action,
    "cancel_pending_action": conf.cancel_pending_action,
    "get_transaction_history": wallet.get_transaction_history,
}


def print_ar(text: str = "") -> None:
    """
    يطبع نص عربي (أو مختلط عربي/انكليزي/أرقام) بالشكل الصحيح على الطرفيات
    اللي ما تدعم عرض النص ثنائي الاتجاه (RTL) بشكل صحيح، متل بعض إصدارات
    Windows Console. يعيد تشكيل الحروف العربية (reshape) ويرتبها بصرياً
    (bidi) قبل الطباعة، فتطلع مرتبة صح بغض النظر عن الطرفية.
    """
    reshaped = arabic_reshaper.reshape(text)
    print(get_display(reshaped, base_dir="R"))


class WalletAgent:
    """وكيل محادثة يربط Groq بوظائف المحفظة الفعلية عبر tool calling."""

    def __init__(self, api_key: str | None = None, model: str = MODEL_NAME):
        api_key = api_key or os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError(
                "ما كو GROQ_API_KEY! تأكد أنك مضيفه بملف .env أو متغير بيئي."
            )
        self.client = Groq(api_key=api_key)
        self.model = model
        self.history: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    def _run_tool(self, call) -> dict:
        """ينفذ أداة وحدة طلبها الموديل، ويرجع نتيجة دايماً (حتى لو صار خطأ)."""
        func_name = call.function.name
        func = AVAILABLE_FUNCTIONS.get(func_name)
        if not func:
            return {"success": False, "message": f"أداة غير معروفة: {func_name}"}

        try:
            args = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            return {"success": False, "message": "صيغة المعاملات غلط، أعد الاستدعاء بمعاملات صحيحة."}

        try:
            return func(**args)
        except TypeError as e:
            # الموديل استخدم أسماء معاملات غلط -> نخبره حتى يصحح ويعيد
            return {
                "success": False,
                "message": f"معاملات غلط للأداة {func_name}: {e}. استخدم أسماء المعاملات من تعريف الأداة بالضبط.",
            }
        except Exception as e:
            return {"success": False, "message": f"خطأ بتنفيذ الأداة: {e}"}

    def ask(self, user_prompt: str) -> str:
        """
        يرسل رسالة المستخدم ويشغل حلقة أدوات: الموديل يستدعي أدوات (ممكن أكثر من جولة)
        لحد ما يرجع رد نصي نهائي. الأدوات تبقى متاحة بكل جولة، وعدد الجولات محدود.
        """
        conf.begin_turn()  # دور جديد: يمنع تأكيد عملية بنفس الدور اللي انجهزت بيه
        self.history.append({"role": "user", "content": user_prompt})

        for round_idx in range(MAX_TOOL_ROUNDS):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=self.history,
                    tools=TOOLS,
                    tool_choice="auto",
                    temperature=TEMPERATURE,
                    max_tokens=MAX_TOKENS,
                )
            except Exception as e:
                if round_idx == 0:
                    self.history.pop()  # ما صار أي شي، نشيل رسالة المستخدم من السجل
                return f"⚠️ صار خطأ بالاتصال: {e}"

            message = response.choices[0].message

            # ما طلب أدوات -> هذا الرد النهائي
            if not message.tool_calls:
                reply = message.content or "ما كدرت أصيغ رد، جرب تعيد الطلب."
                self.history.append({"role": "assistant", "content": reply})
                return reply

            self.history.append(
                {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.function.name,
                                "arguments": call.function.arguments,
                            },
                        }
                        for call in message.tool_calls
                    ],
                }
            )

            for call in message.tool_calls:
                result = self._run_tool(call)
                self.history.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.function.name,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

        return "⚠️ ما كدرت أكمل الطلب بعدد محاولات معقول. جرب تعيد صياغته بشكل أبسط."

    def reset(self):
        """يصفر سجل المحادثة ويرجعه لبرومبت النظام بس."""
        self.history = [{"role": "system", "content": SYSTEM_PROMPT}]


def main():
    try:
        agent = WalletAgent()
    except ValueError as e:
        print(e)
        sys.exit(1)

    print_ar("مرحباً بكم في مشروع زين هاكاثون العراق!")
    print_ar("== مساعد المحفظة الإلكترونية (مع تنفيذ فعلي للعمليات) ==")
    print_ar("(اكتب 'خروج' للإنهاء، أو 'مسح' لتصفير المحادثة)\n")

    while True:
        user_input = input(get_display(arabic_reshaper.reshape("أنت: "), base_dir="R")).strip()
        if not user_input:
            continue
        if user_input.lower() in ("خروج", "exit", "quit"):
            print_ar("مع السلامة!")
            break
        if user_input.lower() in ("مسح", "reset"):
            agent.reset()
            print_ar("[تم تصفير المحادثة]\n")
            continue

        reply = agent.ask(user_input)
        print_ar(f"المساعد: {reply}\n")


if __name__ == "__main__":
    main()