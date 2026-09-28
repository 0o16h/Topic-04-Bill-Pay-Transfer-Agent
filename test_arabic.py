import arabic_reshaper
from bidi.algorithm import get_display

text = "مرحبا بالعالم"
reshaped = arabic_reshaper.reshape(text)
bidi_text = get_display(reshaped)

print("1) بدون أي معالجة:", text)
print("2) reshape بس:", reshaped)
print("3) reshape + bidi:", bidi_text)
