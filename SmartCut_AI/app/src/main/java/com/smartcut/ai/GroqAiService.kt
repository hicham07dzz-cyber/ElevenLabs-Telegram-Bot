package com.smartcut.ai

import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.File
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL

data class TranscriptSegment(
    val start: Double,
    val end: Double,
    val text: String,
    val noSpeechProbability: Double = 0.0
)

data class TranscriptionResult(val text: String, val segments: List<TranscriptSegment>)
data class ClipRange(val startSeconds: Double, val endSeconds: Double)

object GroqAiService {
    private const val BASE = "https://api.groq.com/openai/v1"

    fun transcribeVideo(video: File, apiKey: String): TranscriptionResult {
        require(apiKey.isNotBlank()) { "أدخل مفتاح API داخل التطبيق أولاً." }
        require(video.exists() && video.length() > 0) { "ملف الفيديو غير موجود." }
        require(video.length() <= 25L * 1024L * 1024L) {
            "حجم الملف أكبر من 25MB. قلّل حجم الفيديو ثم أعد المحاولة."
        }
        val boundary = "SmartCutBoundary" + System.currentTimeMillis()
        val connection = (URL("$BASE/audio/transcriptions").openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 30000
            readTimeout = 180000
            doOutput = true
            setRequestProperty("Authorization", "Bearer $apiKey")
            setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
        }
        connection.outputStream.use { output ->
            fun field(name: String, value: String) {
                output.write("--$boundary\r\n".toByteArray())
                output.write("Content-Disposition: form-data; name=\"$name\"\r\n\r\n".toByteArray())
                output.write(value.toByteArray(Charsets.UTF_8))
                output.write("\r\n".toByteArray())
            }
            field("model", "whisper-large-v3-turbo")
            field("response_format", "verbose_json")
            field("timestamp_granularities[]", "segment")
            field("temperature", "0")
            output.write("--$boundary\r\n".toByteArray())
            output.write("Content-Disposition: form-data; name=\"file\"; filename=\"smartcut_video.mp4\"\r\n".toByteArray())
            output.write("Content-Type: video/mp4\r\n\r\n".toByteArray())
            video.inputStream().use { it.copyTo(output) }
            output.write("\r\n--$boundary--\r\n".toByteArray())
        }
        val code = connection.responseCode
        val stream = if (code in 200..299) connection.inputStream else connection.errorStream
        val body = BufferedReader(InputStreamReader(stream)).use { it.readText() }
        connection.disconnect()
        if (code !in 200..299) {
            val message = try { JSONObject(body).optString("error", body) } catch (_: Exception) { body }
            throw IllegalStateException("Whisper API ($code): $message")
        }
        val json = JSONObject(body)
        val segmentsJson = json.optJSONArray("segments") ?: JSONArray()
        val segments = (0 until segmentsJson.length()).mapNotNull { i ->
            val item = segmentsJson.optJSONObject(i) ?: return@mapNotNull null
            val start = item.optDouble("start", Double.NaN)
            val end = item.optDouble("end", Double.NaN)
            val text = item.optString("text", "").trim()
            if (!start.isFinite() || !end.isFinite() || end <= start || text.isBlank()) null
            else TranscriptSegment(start, end, text, item.optDouble("no_speech_prob", 0.0))
        }
        return TranscriptionResult(json.optString("text", ""), segments)
    }

    fun chat(
        apiKey: String,
        transcript: String,
        userRequest: String,
        history: List<Pair<String, String>> = emptyList()
    ): String {
        require(apiKey.isNotBlank()) { "أدخل مفتاح API داخل التطبيق أولاً." }
        val connection = (URL("$BASE/chat/completions").openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 30000
            readTimeout = 120000
            doOutput = true
            setRequestProperty("Authorization", "Bearer $apiKey")
            setRequestProperty("Content-Type", "application/json")
        }
        val messages = JSONArray()
        messages.put(JSONObject().put("role", "system").put(
            "content",
            "أنت مساعد مونتاج فيديو. أجب بالعربية. افهم طلب المستخدم واقترح خطوات تحرير قابلة للتطبيق. " +
                "في أول طلب، أعط ثلاث نسخ تحرير مختلفة بعنوان: نسخة سريعة، نسخة متوازنة، نسخة سينمائية. " +
                "في الرسائل التالية تابع سياق المحادثة. لا تدّع أنك نفذت التصدير ولا تخترع أوقاتاً."
        ))
        history.takeLast(8).forEach { item ->
            messages.put(JSONObject().put("role", item.first).put("content", item.second))
        }
        messages.put(JSONObject().put("role", "user").put(
            "content",
            "طلب التحرير: ${userRequest}\n\nتفريغ Whisper المتاح:\n${transcript.take(12000)}"
        ))
        val payload = JSONObject()
            .put("model", "openai/gpt-oss-120b")
            .put("temperature", 0.4)
            .put("messages", messages)
        connection.outputStream.use { it.write(payload.toString().toByteArray(Charsets.UTF_8)) }
        val code = connection.responseCode
        val stream = if (code in 200..299) connection.inputStream else connection.errorStream
        val body = BufferedReader(InputStreamReader(stream)).use { it.readText() }
        connection.disconnect()
        if (code !in 200..299) {
            val message = try { JSONObject(body).optJSONObject("error")?.optString("message") ?: body }
                catch (_: Exception) { body }
            throw IllegalStateException("AI API ($code): $message")
        }
        return JSONObject(body).getJSONArray("choices").getJSONObject(0)
            .getJSONObject("message").optString("content").ifBlank { "لم يصل رد من نموذج AI." }
    }
}

object SmartCutPlanner {
    fun fromSpeech(segments: List<TranscriptSegment>, durationSeconds: Double): List<ClipRange> {
        if (segments.isEmpty() || durationSeconds <= 0.0) return emptyList()
        val speech = segments
            .filter { it.noSpeechProbability < 0.70 && it.text.isNotBlank() }
            .sortedBy { it.start }
            .map {
                ClipRange((it.start - 0.22).coerceAtLeast(0.0), (it.end + 0.28).coerceAtMost(durationSeconds))
            }
            .filter { it.endSeconds - it.startSeconds >= 0.25 }
        if (speech.isEmpty()) return emptyList()
        val merged = mutableListOf<ClipRange>()
        for (range in speech) {
            val last = merged.lastOrNull()
            if (last != null && range.startSeconds - last.endSeconds <= 1.15) {
                merged[merged.lastIndex] = ClipRange(last.startSeconds, maxOf(last.endSeconds, range.endSeconds))
            } else merged.add(range)
        }
        return merged.filter { it.endSeconds - it.startSeconds >= 0.45 }
    }
}


data class CaptionCue(val startMs: Long, val endMs: Long, val text: String)

@androidx.media3.common.util.UnstableApi
class SmartCutCaptionOverlay(private val cues: List<CaptionCue>) : androidx.media3.effect.TextOverlay() {
    override fun getText(presentationTimeUs: Long): android.text.SpannableString {
        val timeMs = presentationTimeUs / 1000L
        val caption = cues.firstOrNull { timeMs >= it.startMs && timeMs <= it.endMs }?.text.orEmpty()
        val styled = android.text.SpannableString(caption)
        if (caption.isNotEmpty()) {
            styled.setSpan(android.text.style.ForegroundColorSpan(android.graphics.Color.WHITE), 0, caption.length, android.text.Spannable.SPAN_EXCLUSIVE_EXCLUSIVE)
            styled.setSpan(android.text.style.BackgroundColorSpan(0x99000000.toInt()), 0, caption.length, android.text.Spannable.SPAN_EXCLUSIVE_EXCLUSIVE)
            styled.setSpan(android.text.style.StyleSpan(android.graphics.Typeface.BOLD), 0, caption.length, android.text.Spannable.SPAN_EXCLUSIVE_EXCLUSIVE)
        }
        return styled
    }
}


@androidx.media3.common.util.UnstableApi
class SpeechDuckingGainProvider(private val speechRanges: List<ClipRange>) :
    androidx.media3.common.audio.GainProcessor.GainProvider {
    override fun getGainFactorAtSamplePosition(samplePosition: Long, sampleRate: Int): Float {
        if (sampleRate <= 0) return 0.35f
        val seconds = samplePosition.toDouble() / sampleRate.toDouble()
        return if (speechRanges.any { seconds >= it.startSeconds && seconds <= it.endSeconds }) 0.16f else 0.42f
    }

    override fun isUnityUntil(samplePosition: Long, sampleRate: Int): Long =
        androidx.media3.common.C.TIME_UNSET
}
