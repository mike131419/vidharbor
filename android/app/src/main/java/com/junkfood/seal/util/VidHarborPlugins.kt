package com.junkfood.seal.util

import android.content.Context
import android.util.Log
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLRequest
import java.io.File

/**
 * VidHarbor: yt-dlp plugins shipped in assets/ytdlp-plugins (Douyin without cookies, short links
 * from Chinese apps, Kuaishou). They are copied to app storage at start-up and passed to every
 * yt-dlp run with --plugin-dirs.
 */
object VidHarborPlugins {
    private const val TAG = "VidHarborPlugins"
    private const val ASSET_ROOT = "ytdlp-plugins"

    /** First yt-dlp release with --plugin-dirs. Older engines simply run without the plugins. */
    private const val MIN_YTDLP = "2025.02.19"

    @Volatile private var pluginDir: File? = null
    @Volatile private var ytdlpVersion: String? = null

    fun install(context: Context) {
        runCatching {
                val target = File(context.filesDir, ASSET_ROOT)
                target.deleteRecursively() // always use the plugins from this app version
                copyAssets(context, ASSET_ROOT, target)
                pluginDir = target
            }
            .onFailure { Log.e(TAG, "Could not install yt-dlp plugins", it) }
        refreshVersion(context)
    }

    /** Call after yt-dlp has been updated. */
    fun refreshVersion(context: Context) {
        ytdlpVersion = runCatching { YoutubeDL.getInstance().version(context) }.getOrNull()
    }

    private fun copyAssets(context: Context, path: String, target: File) {
        val children = context.assets.list(path) ?: emptyArray()
        if (children.isEmpty()) {
            target.parentFile?.mkdirs()
            context.assets.open(path).use { input ->
                target.outputStream().use { output -> input.copyTo(output) }
            }
            return
        }
        target.mkdirs()
        children.forEach { copyAssets(context, "$path/$it", File(target, it)) }
    }

    fun applyTo(request: YoutubeDLRequest): YoutubeDLRequest {
        val dir = pluginDir ?: return request
        val version = ytdlpVersion ?: return request
        if (version >= MIN_YTDLP) request.addOption("--plugin-dirs", dir.absolutePath)
        return request
    }
}

fun YoutubeDLRequest.withVidHarborPlugins(): YoutubeDLRequest = VidHarborPlugins.applyTo(this)
