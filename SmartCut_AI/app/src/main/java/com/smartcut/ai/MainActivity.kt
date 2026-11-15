package com.smartcut.ai

import android.content.ContentValues
import android.net.Uri
import android.os.Bundle
import android.provider.MediaStore
import android.widget.*
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.media3.common.MediaItem
import androidx.media3.transformer.EditedMediaItem
import androidx.media3.transformer.ExportException
import androidx.media3.transformer.ExportResult
import androidx.media3.transformer.Transformer
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream

class MainActivity : ComponentActivity() {
    private lateinit var preview: VideoView
    private lateinit var status: TextView
    private lateinit var pickButton: Button
    private lateinit var exportButton: Button
    private lateinit var startInput: EditText
    private lateinit var endInput: EditText
    private var source: File? = null

    private val picker = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) loadVideo(uri)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(24, 30, 24, 24)
            setBackgroundColor(0xFF10131A.toInt())
        }
        fun label(value: String, size: Float, color: Int = -1) = TextView(this).apply {
            text = value; textSize = size; setTextColor(color)
        }
        root.addView(label("SMARTCUT AI", 28f, 0xFFFF8A32.toInt()))
        root.addView(label("مونتاج الفيديو على هاتفك", 17f).apply { setPadding(0, 8, 0, 20) })
        preview = VideoView(this)
        root.addView(preview, LinearLayout.LayoutParams(-1, 220).apply { bottomMargin = 16 })
        pickButton = Button(this).apply {
            text = "اختيار فيديو"
            setOnClickListener { picker.launch(arrayOf("video/*")) }
        }
        root.addView(pickButton)
        root.addView(label("قص الفيديو — الوقت بالثواني", 17f).apply { setPadding(0, 20, 0, 8) })
        val fields = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        startInput = EditText(this).apply { hint = "من 0"; setText("0"); inputType = 8194; setTextColor(-1) }
        endInput = EditText(this).apply { hint = "إلى"; inputType = 8194; setTextColor(-1) }
        fields.addView(startInput, LinearLayout.LayoutParams(0, -2, 1f))
        fields.addView(endInput, LinearLayout.LayoutParams(0, -2, 1f))
        root.addView(fields)
        exportButton = Button(this).apply {
            text = "قص وتصدير MP4"
            isEnabled = false
            setOnClickListener { exportVideo() }
        }
        root.addView(exportButton, LinearLayout.LayoutParams(-1, -2).apply { topMargin = 14 })
        status = label("الإصدار الأول: اختيار الفيديو ومعاينته وقصه.", 14f, 0xFFB7C0CC.toInt())
        status.setPadding(0, 18, 0, 0)
        root.addView(status)
        root.addView(label("ميزات الذكاء الاصطناعي قيد التطوير ولم تُدمج بعد.", 12f, 0xFF8993A2.toInt()).apply { setPadding(0, 14, 0, 0) })
        setContentView(ScrollView(this).apply { addView(root) })
    }

    private fun loadVideo(uri: Uri) {
        try {
            val file = File(cacheDir, "smartcut_source_video")
            contentResolver.openInputStream(uri).use { input ->
                requireNotNull(input).copyTo(FileOutputStream(file))
            }
            source = file
            preview.setVideoURI(Uri.fromFile(file))
            preview.setOnPreparedListener { player ->
                player.isLooping = true
                preview.start()
                endInput.setText((player.duration / 1000).toString())
                status.text = "تم تحميل الفيديو — " + (player.duration / 1000) + " ثانية"
                exportButton.isEnabled = true
            }
        } catch (e: Exception) {
            status.text = "تعذر تحميل الفيديو: " + e.message
        }
    }

    private fun exportVideo() {
        val input = source ?: return
        val from = ((startInput.text.toString().toDoubleOrNull() ?: 0.0) * 1000).toLong()
        val to = ((endInput.text.toString().toDoubleOrNull() ?: 0.0) * 1000).toLong()
        if (from < 0 || to <= from) {
            status.text = "أدخل وقت بداية ونهاية صحيحين."
            return
        }
        val output = File(cacheDir, "smartcut_output.mp4")
        output.delete()
        exportButton.isEnabled = false
        pickButton.isEnabled = false
        status.text = "جارٍ تنفيذ القص..."
        val mediaItem = MediaItem.Builder().setUri(Uri.fromFile(input))
            .setClippingConfiguration(MediaItem.ClippingConfiguration.Builder()
                .setStartPositionMs(from).setEndPositionMs(to).build()).build()
        val edited = EditedMediaItem.Builder(mediaItem).build()
        val listener = object : Transformer.Listener {
            override fun onCompleted(composition: androidx.media3.transformer.Composition, exportResult: ExportResult) {
                try {
                    val values = ContentValues().apply {
                        put(MediaStore.Video.Media.DISPLAY_NAME, "SmartCut_" + System.currentTimeMillis() + ".mp4")
                        put(MediaStore.Video.Media.MIME_TYPE, "video/mp4")
                        put(MediaStore.Video.Media.RELATIVE_PATH, "Movies/SmartCutAI")
                    }
                    val saved = contentResolver.insert(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, values)
                        ?: error("تعذر إنشاء الملف")
                    contentResolver.openOutputStream(saved).use { out ->
                        requireNotNull(out)
                        FileInputStream(output).use { it.copyTo(out) }
                    }
                    status.text = "نجح التصدير! تحقق من Movies/SmartCutAI."
                } catch (e: Exception) {
                    status.text = "اكتمل القص وتعذر الحفظ: " + e.message
                }
                exportButton.isEnabled = true
                pickButton.isEnabled = true
            }
            override fun onError(composition: androidx.media3.transformer.Composition, exportResult: ExportResult, exportException: ExportException) {
                status.text = "فشل القص: " + exportException.message
                exportButton.isEnabled = true
                pickButton.isEnabled = true
            }
        }
        Transformer.Builder(this).addListener(listener).build().start(edited, output.absolutePath)
    }
}
