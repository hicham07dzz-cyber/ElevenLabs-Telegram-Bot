package com.smartcut.ai

import android.content.ContentValues
import android.graphics.Bitmap
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.os.Bundle
import android.provider.MediaStore
import android.widget.*
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.media3.common.MediaItem
import androidx.media3.common.util.UnstableApi
import androidx.media3.effect.Presentation
import androidx.media3.transformer.Composition
import androidx.media3.transformer.EditedMediaItem
import androidx.media3.transformer.EditedMediaItemSequence
import androidx.media3.transformer.Effects
import androidx.media3.transformer.ExportException
import androidx.media3.transformer.ExportResult
import androidx.media3.transformer.Transformer
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.util.Locale
import kotlin.concurrent.thread

@OptIn(UnstableApi::class)
class MainActivity : ComponentActivity() {
    private lateinit var preview: VideoView
    private lateinit var status: TextView
    private lateinit var pickButton: Button
    private lateinit var exportButton: Button
    private lateinit var startInput: EditText
    private lateinit var endInput: EditText
    private lateinit var ratioSpinner: Spinner
    private lateinit var commandInput: EditText
    private lateinit var transcriptInput: EditText
    private lateinit var analysisView: TextView
    private lateinit var apiKeyInput: EditText
    private lateinit var chatOutput: TextView
    private lateinit var uploadConsent: CheckBox
    private var transcriptSegments: List<TranscriptSegment> = emptyList()
    private var smartCuts: List<ClipRange>? = null
    private var source: File? = null
    private var music: File? = null
    private var durationMs: Long = 0L

    private val videoPicker = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) loadVideo(uri)
    }
    private val musicPicker = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) loadMusic(uri)
    }
    private val subtitleSaver = registerForActivityResult(ActivityResultContracts.CreateDocument("application/x-subrip")) { uri ->
        if (uri != null) saveSubtitles(uri)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(22, 28, 22, 26)
            setBackgroundColor(0xFF10131A.toInt())
        }
        fun label(value: String, size: Float, color: Int = -1) = TextView(this).apply {
            text = value
            textSize = size
            setTextColor(color)
        }
        fun section(value: String) {
            root.addView(label(value, 18f, 0xFFFF9A45.toInt()).apply { setPadding(0, 20, 0, 8) })
        }
        root.addView(label("SMARTCUT AI", 28f, 0xFFFF8A32.toInt()))
        root.addView(label("استوديو مونتاج الفيديو — Android", 15f, 0xFFB7C0CC.toInt()).apply {
            setPadding(0, 6, 0, 18)
        })
        preview = VideoView(this)
        root.addView(preview, LinearLayout.LayoutParams(-1, 210).apply { bottomMargin = 12 })
        pickButton = Button(this).apply {
            text = "＋ اختيار فيديو"
            setOnClickListener { videoPicker.launch(arrayOf("video/*")) }
        }
        root.addView(pickButton)

        section("1. القص والمقاس")
        root.addView(label("بداية ونهاية المقطع بالثواني", 14f, 0xFFCBD2DC.toInt()))
        val times = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        startInput = EditText(this).apply {
            hint = "من 0"
            setText("0")
            inputType = 8194
            setTextColor(-1)
        }
        endInput = EditText(this).apply {
            hint = "إلى"
            inputType = 8194
            setTextColor(-1)
        }
        times.addView(startInput, LinearLayout.LayoutParams(0, -2, 1f))
        times.addView(endInput, LinearLayout.LayoutParams(0, -2, 1f))
        root.addView(times)
        ratioSpinner = Spinner(this)
        ratioSpinner.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item,
            listOf("عمودي 9:16 — Reels / TikTok", "أفقي 16:9 — YouTube", "مربع 1:1"))
        root.addView(ratioSpinner)

        section("2. تحليل الفيديو")
        root.addView(Button(this).apply {
            text = "تحليل الصورة والمدة"
            setOnClickListener { analyzeVideo() }
        })
        analysisView = label("اختر فيديو لعرض معلوماته وتحليل عينات من الإطارات.", 13f, 0xFFB7C0CC.toInt())
        root.addView(analysisView)

        section("3. Whisper والتفريغ الصوتي")
        apiKeyInput = EditText(this).apply {
            hint = "مفتاح Groq API — لا تضعه في GitHub أو ترسله لأحد"
            inputType = 129
            setTextColor(-1)
        }
        root.addView(apiKeyInput)
        uploadConsent = CheckBox(this).apply {
            text = "أوافق على إرسال نسخة الفيديو إلى خدمة Whisper لمعالجة الصوت"
            setTextColor(0xFFCBD2DC.toInt())
        }
        root.addView(uploadConsent)
        root.addView(Button(this).apply {
            text = "تفريغ الفيديو تلقائياً بواسطة Whisper"
            setOnClickListener { transcribeWithWhisper() }
        })
        root.addView(Button(this).apply {
            text = "اكتشاف فترات الكلام وقص الصمت تلقائياً"
            setOnClickListener { applySmartCut() }
        })

        section("3. الموسيقى")
        root.addView(Button(this).apply {
            text = "اختيار ملف موسيقى"
            setOnClickListener { musicPicker.launch(arrayOf("audio/*")) }
        })
        root.addView(label("يمكن دمج مسار موسيقى خلفية مع صوت الفيديو أثناء التصدير.", 12f, 0xFF8993A2.toInt()))

        section("4. مساعد أوامر التحرير")
        commandInput = EditText(this).apply {
            hint = "مثال: جهّز الفيديو لتيك توك أو اجعله مربعاً"
            setTextColor(-1)
        }
        root.addView(commandInput)

        root.addView(Button(this).apply {
            text = "إرسال الأمر إلى محرر AI وإنشاء 3 نسخ"
            setOnClickListener { askAiEditor() }
        })
        chatOutput = label("ردود محرر AI ستظهر هنا.", 13f, 0xFFB7C0CC.toInt())
        root.addView(chatOutput)
        root.addView(Button(this).apply {
            text = "فهم الأمر وتطبيق الإعدادات"
            setOnClickListener { applyLocalCommand() }
        })

        section("5. النص والترجمة")
        root.addView(label("ألصق النص المنطوق هنا ثم أنشئ ملف SRT بتوقيت تقريبي.", 12f, 0xFFB7C0CC.toInt()))
        transcriptInput = EditText(this).apply {
            hint = "النص المنطوق..."
            minLines = 3
            gravity = android.view.Gravity.TOP
            setTextColor(-1)
        }
        root.addView(transcriptInput)
        root.addView(Button(this).apply {
            text = "تصدير النص كملف ترجمة SRT"
            setOnClickListener {
                if (transcriptInput.text.toString().isBlank()) {
                    status.text = "أدخل النص أولاً لإنشاء ملف الترجمة."
                } else subtitleSaver.launch("SmartCut_Captions.srt")
            }
        })

        section("6. التصدير")
        exportButton = Button(this).apply {
            text = "تصدير الفيديو MP4"
            isEnabled = false
            setOnClickListener { exportVideo() }
        }
        root.addView(exportButton)
        status = label("بانتظار اختيار فيديو.", 14f, 0xFFB7C0CC.toInt())
        status.setPadding(0, 18, 0, 0)
        root.addView(status)
        root.addView(label("ملاحظة: تحليل الإطارات والمقاسات ودمج الموسيقى متاح في هذه المرحلة. تفريغ Whisper والقص الذكي الدلالي والترجمة المتزامنة تلقائياً ما زالت قيد الدمج.", 12f, 0xFF8993A2.toInt()).apply {
            setPadding(0, 16, 0, 0)
        })
        setContentView(ScrollView(this).apply { addView(root) })
    }

    private fun copyUriToCache(uri: Uri, name: String): File {
        val file = File(cacheDir, name)
        contentResolver.openInputStream(uri).use { input ->
            requireNotNull(input) { "تعذر فتح الملف المختار" }.use { stream ->
                FileOutputStream(file).use { output -> stream.copyTo(output) }
            }
        }
        return file
    }

    private fun loadVideo(uri: Uri) {
        try {
            val file = copyUriToCache(uri, "smartcut_source_video")
            source = file
            preview.setVideoURI(Uri.fromFile(file))
            preview.setOnPreparedListener { player ->
                player.isLooping = true
                preview.start()
                durationMs = player.duration.toLong()
                endInput.setText(String.format(Locale.US, "%.1f", durationMs / 1000.0))
                status.text = "تم تحميل الفيديو — " + (durationMs / 1000) + " ثانية"
                exportButton.isEnabled = true
            }
        } catch (e: Exception) {
            status.text = "تعذر تحميل الفيديو: " + (e.message ?: "خطأ غير معروف")
        }
    }

    private fun loadMusic(uri: Uri) {
        try {
            music = copyUriToCache(uri, "smartcut_background_music")
            status.text = "تم اختيار الموسيقى. ستتكرر لتغطية مدة الفيديو."
        } catch (e: Exception) {
            status.text = "تعذر تحميل الموسيقى: " + (e.message ?: "خطأ غير معروف")
        }
    }

    private fun analyzeVideo() {
        val file = source
        if (file == null) {
            status.text = "اختر فيديو أولاً."
            return
        }
        analysisView.text = "جارٍ تحليل عينات من الإطارات..."
        thread {
            val retriever = MediaMetadataRetriever()
            try {
                retriever.setDataSource(file.absolutePath)
                val width = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH)?.toIntOrNull() ?: 0
                val height = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT)?.toIntOrNull() ?: 0
                val duration = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)?.toLongOrNull() ?: durationMs
                val samples = mutableListOf<Double>()
                for (i in 0 until 8) {
                    val timeUs = (duration * 1000L * i / 8).coerceAtLeast(0L)
                    val bitmap: Bitmap? = retriever.getFrameAtTime(timeUs, MediaMetadataRetriever.OPTION_CLOSEST_SYNC)
                    if (bitmap != null) {
                        val stepX = (bitmap.width / 32).coerceAtLeast(1)
                        val stepY = (bitmap.height / 32).coerceAtLeast(1)
                        var total = 0L
                        var n = 0
                        var y = 0
                        while (y < bitmap.height) {
                            var x = 0
                            while (x < bitmap.width) {
                                val pixel = bitmap.getPixel(x, y)
                                val luma = (0.2126 * ((pixel shr 16) and 0xFF) +
                                    0.7152 * ((pixel shr 8) and 0xFF) +
                                    0.0722 * (pixel and 0xFF)).toInt()
                                total += luma
                                n++
                                x += stepX
                            }
                            y += stepY
                        }
                        if (n > 0) samples.add(total.toDouble() / n)
                        bitmap.recycle()
                    }
                }
                val average = if (samples.isNotEmpty()) samples.average() else 0.0
                val variation = if (samples.size > 1) samples.maxOrNull()!! - samples.minOrNull()!! else 0.0
                val note = when {
                    samples.isEmpty() -> "لم أتمكن من قراءة الإطارات."
                    average < 65 -> "العينة العامة داكنة؛ راجع الإضاءة."
                    average > 205 -> "العينة شديدة السطوع؛ راجع التعريض."
                    else -> "متوسط الإضاءة ضمن نطاق متوازن تقريبياً."
                }
                val result = "الدقة: " + width + "×" + height + "\nالمدة: " + (duration / 1000) +
                    " ثانية\nمتوسط سطوع العينات: " + average.toInt() + "/255\n" +
                    "تغيّر السطوع بين العينات: " + variation.toInt() + "\n" + note +
                    "\nهذا فحص إطارات أولي، وليس فهماً دلالياً للمشاهد."
                runOnUiThread {
                    analysisView.text = result
                    if (durationMs == 0L) {
                        durationMs = duration
                        endInput.setText(String.format(Locale.US, "%.1f", duration / 1000.0))
                    }
                }
            } catch (e: Exception) {
                runOnUiThread { analysisView.text = "تعذر التحليل: " + e.message }
            } finally {
                retriever.release()
            }
        }
    }


    private fun transcribeWithWhisper() {
        val file = source
        val key = apiKeyInput.text.toString().trim()
        if (file == null) { status.text = "اختر فيديو أولاً."; return }
        if (key.isBlank()) { status.text = "أدخل مفتاح API داخل التطبيق. لا ترسله في المحادثة."; return }
        if (!uploadConsent.isChecked) { status.text = "فعّل الموافقة قبل إرسال الفيديو إلى خدمة Whisper."; return }
        status.text = "جارٍ إرسال الفيديو إلى Whisper..."
        thread {
            try {
                val result = GroqAiService.transcribeVideo(file, key)
                transcriptSegments = result.segments
                smartCuts = null
                runOnUiThread {
                    transcriptInput.setText(result.text)
                    status.text = "اكتمل التفريغ: ${result.segments.size} مقطعاً زمنياً."
                    analysisView.text = "Whisper: ${result.segments.size} مقطعاً زمنياً.\n" +
                        result.segments.take(8).joinToString("\n") {
                            "${"%.1f".format(Locale.US, it.start)}s — ${it.text}"
                        }
                }
            } catch (e: Exception) {
                runOnUiThread { status.text = "تعذر التفريغ: ${e.message}" }
            }
        }
    }

    private fun applySmartCut() {
        if (transcriptSegments.isEmpty()) {
            status.text = "نفّذ تفريغ Whisper أولاً حتى تتوفر التوقيتات."
            return
        }
        val durationSeconds = durationMs / 1000.0
        val ranges = SmartCutPlanner.fromSpeech(transcriptSegments, durationSeconds)
        if (ranges.isEmpty()) {
            status.text = "لم أجد مقاطع كلام موثوقة لاقتراح القص. لم أغيّر الفيديو."
            return
        }
        smartCuts = ranges
        val kept = ranges.sumOf { it.endSeconds - it.startSeconds }
        val removed = (durationSeconds - kept).coerceAtLeast(0.0)
        analysisView.text = "خطة القص الذكي: ${ranges.size} مقطعاً محفوظاً.\n" +
            "المدة الأصلية: ${"%.1f".format(Locale.US, durationSeconds)} ثانية\n" +
            "المدة بعد حذف فترات الصمت الطويلة تقريبياً: ${"%.1f".format(Locale.US, kept)} ثانية\n" +
            "الوقت المحذوف تقريبياً: ${"%.1f".format(Locale.US, removed)} ثانية"
        status.text = "تم إعداد القص الذكي. راجع الخطة قبل التصدير."
    }

    private fun askAiEditor() {
        val key = apiKeyInput.text.toString().trim()
        val request = commandInput.text.toString().trim()
        if (key.isBlank()) { status.text = "أدخل مفتاح API داخل التطبيق أولاً."; return }
        if (request.isBlank()) { status.text = "اكتب ما تريد تعديله أولاً."; return }
        chatOutput.text = "محرر AI يفكر..."
        thread {
            try {
                val response = GroqAiService.chat(key, transcriptInput.text.toString(), request)
                runOnUiThread {
                    chatOutput.text = response
                    status.text = "وصل رد محرر AI. راجع النسخ الثلاث."
                }
            } catch (e: Exception) {
                runOnUiThread { chatOutput.text = "تعذر الاتصال بمحرر AI: ${e.message}" }
            }
        }
    }

    private fun captionCuesFor(ranges: List<ClipRange>): List<CaptionCue> {
        val cues = mutableListOf<CaptionCue>()
        var outputOffsetMs = 0L
        for (range in ranges) {
            for (segment in transcriptSegments) {
                val overlapStart = maxOf(range.startSeconds, segment.start)
                val overlapEnd = minOf(range.endSeconds, segment.end)
                if (overlapEnd > overlapStart) {
                    val start = outputOffsetMs + ((overlapStart - range.startSeconds) * 1000.0).toLong()
                    val end = outputOffsetMs + ((overlapEnd - range.startSeconds) * 1000.0).toLong()
                    cues.add(CaptionCue(start, end.coerceAtLeast(start + 250L), segment.text))
                }
            }
            outputOffsetMs += ((range.endSeconds - range.startSeconds) * 1000.0).toLong()
        }
        return cues
    }

    private fun applyLocalCommand() {
        val command = commandInput.text.toString().lowercase(Locale.ROOT)
        when {
            command.contains("تيك توك") || command.contains("ريلز") || command.contains("reels") ->
                ratioSpinner.setSelection(0)
            command.contains("يوتيوب") || command.contains("youtube") ->
                ratioSpinner.setSelection(1)
            command.contains("مربع") || command.contains("square") ->
                ratioSpinner.setSelection(2)
        }
        val match = Regex("(?:من\\s*)?(\\d+(?:\\.\\d+)?)\\s*(?:إلى|الى|حتى|to)\\s*(\\d+(?:\\.\\d+)?)").find(command)
        if (match != null) {
            startInput.setText(match.groupValues[1])
            endInput.setText(match.groupValues[2])
        } else if (command.contains("أول 30") || command.contains("اول 30")) {
            startInput.setText("0")
            endInput.setText("30")
        }
        status.text = "طبّقت الإعدادات التي فهمها مساعد الأوامر المحلي. راجع المقاس والأوقات قبل التصدير."
    }

    private fun saveSubtitles(uri: Uri) {
        try {
            val fullText = transcriptInput.text.toString().trim()
            val ranges = smartCuts ?: listOf(ClipRange(0.0, durationMs.coerceAtLeast(1000L) / 1000.0))
            val cues = captionCuesFor(ranges)
            val srt = if (cues.isNotEmpty()) {
                cues.mapIndexed { index, cue ->
                    (index + 1).toString() + "\n" + srtTime(cue.startMs) + " --> " +
                        srtTime(cue.endMs) + "\n" + cue.text
                }.joinToString("\n\n")
            } else {
                val lines = fullText.split(Regex("(?<=[.!؟?])\\s+|\\n+")).filter { it.isNotBlank() }
                val totalMs = durationMs.coerceAtLeast(1000L)
                val chunk = (totalMs / lines.size.coerceAtLeast(1)).coerceAtLeast(1000L)
                lines.mapIndexed { index, line ->
                    val startMs = index * chunk
                    val endMs = if (index == lines.lastIndex) totalMs else (startMs + chunk).coerceAtMost(totalMs)
                    (index + 1).toString() + "\n" + srtTime(startMs) + " --> " + srtTime(endMs) + "\n" + line
                }.joinToString("\n\n")
            }
            contentResolver.openOutputStream(uri).use { output ->
                requireNotNull(output).write(srt.toByteArray(Charsets.UTF_8))
            }
            status.text = "تم حفظ ملف SRT بتوقيت تقريبي. راجع التوقيت قبل النشر."
        } catch (e: Exception) {
            status.text = "تعذر حفظ الترجمة: " + e.message
        }
    }

    private fun srtTime(ms: Long): String {
        val safe = ms.coerceAtLeast(0L)
        val hours = safe / 3_600_000
        val minutes = (safe % 3_600_000) / 60_000
        val seconds = (safe % 60_000) / 1000
        val millis = safe % 1000
        return String.format(Locale.US, "%02d:%02d:%02d,%03d", hours, minutes, seconds, millis)
    }

    private fun exportVideo() {
        val input = source ?: return
        val from = ((startInput.text.toString().toDoubleOrNull() ?: 0.0) * 1000).toLong()
        val to = ((endInput.text.toString().toDoubleOrNull() ?: 0.0) * 1000).toLong()
        if (from < 0 || to <= from || (durationMs > 0 && to > durationMs + 500)) {
            status.text = "أدخل وقت بداية ونهاية صحيحين ضمن مدة الفيديو."
            return
        }
        val ratio = when (ratioSpinner.selectedItemPosition) {
            0 -> 9f / 16f
            1 -> 16f / 9f
            else -> 1f
        }
        val output = File(cacheDir, "smartcut_output.mp4")
        output.delete()
        exportButton.isEnabled = false
        pickButton.isEnabled = false
        status.text = if (music == null) "جارٍ القص وتطبيق المقاس..." else "جارٍ القص ودمج الموسيقى..."
        val activeRanges = (smartCuts ?: listOf(ClipRange(from / 1000.0, to / 1000.0)))
            .filter { it.endSeconds > it.startSeconds }
        if (activeRanges.isEmpty()) {
            status.text = "لا توجد مقاطع صالحة للتصدير."
            exportButton.isEnabled = true
            pickButton.isEnabled = true
            return
        }
        val captionCues = captionCuesFor(activeRanges)
        val editedVideos = activeRanges.map { range ->
            val clip = MediaItem.Builder().setUri(Uri.fromFile(input))
                .setClippingConfiguration(MediaItem.ClippingConfiguration.Builder()
                    .setStartPositionMs((range.startSeconds * 1000).toLong())
                    .setEndPositionMs((range.endSeconds * 1000).toLong()).build()).build()
            val presentation = Presentation.createForAspectRatio(
                ratio, Presentation.LAYOUT_SCALE_TO_FIT_WITH_CROP
            )
            val itemCues = captionCuesFor(listOf(range))
            val videoEffects = mutableListOf<androidx.media3.common.Effect>(
                presentation,
                androidx.media3.effect.Brightness(0.015f),
                androidx.media3.effect.Contrast(0.035f)
            )
            if (itemCues.isNotEmpty()) {
                videoEffects.add(androidx.media3.effect.OverlayEffect(
                    listOf(SmartCutCaptionOverlay(itemCues))
                ))
            }
            EditedMediaItem.Builder(clip)
                .setEffects(Effects(emptyList(), videoEffects))
                .build()
        }
        val videoSequence = EditedMediaItemSequence.withAudioAndVideoFrom(editedVideos)
        val transformer = Transformer.Builder(this).addListener(object : Transformer.Listener {
            override fun onCompleted(composition: Composition, exportResult: ExportResult) {
                try {
                    val values = ContentValues().apply {
                        put(MediaStore.Video.Media.DISPLAY_NAME, "SmartCut_" + System.currentTimeMillis() + ".mp4")
                        put(MediaStore.Video.Media.MIME_TYPE, "video/mp4")
                        put(MediaStore.Video.Media.RELATIVE_PATH, "Movies/SmartCutAI")
                    }
                    val saved = contentResolver.insert(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, values)
                        ?: error("تعذر إنشاء ملف الحفظ")
                    contentResolver.openOutputStream(saved).use { out ->
                        requireNotNull(out)
                        FileInputStream(output).use { it.copyTo(out) }
                    }
                    status.text = "اكتمل التصدير. تحقق من مجلد Movies/SmartCutAI."
                } catch (e: Exception) {
                    status.text = "اكتمل التحويل لكن تعذر الحفظ: " + e.message
                }
                exportButton.isEnabled = true
                pickButton.isEnabled = true
            }
            override fun onError(composition: Composition, exportResult: ExportResult, exportException: ExportException) {
                status.text = "فشل التصدير: " + exportException.message
                exportButton.isEnabled = true
                pickButton.isEnabled = true
            }
        }).build()
        try {
            val selectedMusic = music
            val sequences = mutableListOf(videoSequence)
            if (selectedMusic != null) {
                val speechRanges = captionCues.map {
                    ClipRange(it.startMs / 1000.0, it.endMs / 1000.0)
                }
                val duckingProcessor = androidx.media3.common.audio.GainProcessor(
                    SpeechDuckingGainProvider(speechRanges)
                )
                val musicItem = EditedMediaItem.Builder(MediaItem.fromUri(Uri.fromFile(selectedMusic)))
                    .setEffects(Effects(listOf(duckingProcessor), emptyList()))
                    .build()
                val musicSequence = EditedMediaItemSequence.withAudioFrom(listOf(musicItem))
                    .buildUpon().setIsLooping(true).build()
                sequences.add(musicSequence)
            }
            transformer.start(Composition.Builder(sequences).build(), output.absolutePath)
        } catch (e: Exception) {
            status.text = "تعذر بدء التصدير: " + e.message
            exportButton.isEnabled = true
            pickButton.isEnabled = true
        }
    }
}
