# AUTOFOX EDIT — نسخة أولية

محرك محلي أولي لتحليل تغيّر المشاهد وتقدير الحركة واختيار مقاطع قصيرة ثم تركيبها في MP4 باستخدام FFmpeg. لا يتضمن حالياً فهماً دلالياً كاملاً للمحتوى أو مؤثرات CapCut المتقدمة.

## متطلبات Termux
```bash
pkg update
pkg install python ffmpeg
python -m pip install --upgrade pip
pip install -r requirements.txt
termux-setup-storage
```

## التشغيل
```bash
python autofox.py "/sdcard/Download/video.mp4"
```
أو:
```bash
python autofox.py "/sdcard/Download/video.mp4" --output "/sdcard/Download/AUTOFOX_FINAL.mp4"
```

يحفظ الفيديو الأصلي دون تعديل، وينشئ تقرير JSON بجانب ملف الإخراج. الاختيار الحالي يعتمد على تغيّر المشاهد وتقدير الحركة، وليس التعرف الذكي على أحداث مثل Headshot أو فهم الكلام. التصدير الافتراضي حتى 1080p/30fps؛ الأداء والجودة يعتمدان على الهاتف والملف.

## الخصوصية والتكلفة
لا يوجد API أو مفتاح سري في هذا المشروع. المعالجة محلية بعد تثبيت المتطلبات. لا تضع مفاتيح API في ملفات GitHub.