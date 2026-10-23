// The small bridge between Kotlin (WhisperModel) and whisper.cpp.
#include <jni.h>
#include <string>
#include <android/log.h>
#include "whisper.h"

#define TAG "ScreenTranslator"

extern "C" JNIEXPORT jlong JNICALL
Java_io_github_milkteatw1_screentranslator_WhisperModel_nativeLoad(JNIEnv *env, jobject, jstring path) {
    const char *p = env->GetStringUTFChars(path, nullptr);
    whisper_context_params cparams = whisper_context_default_params();
    cparams.use_gpu = false;
    whisper_context *ctx = whisper_init_from_file_with_params(p, cparams);
    env->ReleaseStringUTFChars(path, p);
    if (!ctx) __android_log_print(ANDROID_LOG_WARN, TAG, "whisper: could not load the model");
    return reinterpret_cast<jlong>(ctx);
}

extern "C" JNIEXPORT void JNICALL
Java_io_github_milkteatw1_screentranslator_WhisperModel_nativeFree(JNIEnv *, jobject, jlong handle) {
    if (handle) whisper_free(reinterpret_cast<whisper_context *>(handle));
}

// Transcribes 16 kHz mono float audio. [language] is a code ("en", "ja"...) or "auto".
// Returns the UTF-8 bytes of "<detected language code>\t<text>" (bytes, not a Java string: JNI's own string
// encoding cannot carry characters such as emoji, which Whisper sometimes writes). Empty when it failed.
extern "C" JNIEXPORT jbyteArray JNICALL
Java_io_github_milkteatw1_screentranslator_WhisperModel_nativeTranscribe(
        JNIEnv *env, jobject, jlong handle, jfloatArray audio, jint threads, jstring language) {
    auto *ctx = reinterpret_cast<whisper_context *>(handle);
    if (!ctx) return env->NewByteArray(0);
    const char *lang = env->GetStringUTFChars(language, nullptr);
    std::string langCopy(lang);
    env->ReleaseStringUTFChars(language, lang);

    whisper_full_params params = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
    params.language = langCopy.c_str();
    params.translate = false;
    params.n_threads = threads;
    params.no_context = true;
    params.no_timestamps = true;
    params.single_segment = false;
    params.suppress_nst = true;
    params.print_progress = false;
    params.print_realtime = false;
    params.print_special = false;
    params.print_timestamps = false;
    params.temperature_inc = 0.0f;  // no slow retries at higher temperatures: a late caption is worse than a rough one

    jsize n = env->GetArrayLength(audio);
    // The encoder normally looks at a fixed 30 s window however short the speech is. Shrinking it to the length of the
    // audio (plus some room) makes short clips several times faster, which is what live captions need. 50 = frames per second.
    int frames = (int) (n / 16000.0 * 50.0) + 200;
    params.audio_ctx = frames < 750 ? 750 : (frames > 1500 ? 1500 : frames);
    jfloat *samples = env->GetFloatArrayElements(audio, nullptr);
    int rc = whisper_full(ctx, params, samples, n);
    env->ReleaseFloatArrayElements(audio, samples, JNI_ABORT);
    if (rc != 0) return env->NewByteArray(0);

    std::string text;
    int segments = whisper_full_n_segments(ctx);
    for (int i = 0; i < segments; i++) {
        if (whisper_full_get_segment_no_speech_prob(ctx, i) > 0.6f) continue;  // music, noise: not speech
        text += whisper_full_get_segment_text(ctx, i);
    }
    int id = whisper_full_lang_id(ctx);
    const char *code = id >= 0 ? whisper_lang_str(id) : "";
    std::string out = std::string(code ? code : "") + "\t" + text;
    jbyteArray bytes = env->NewByteArray((jsize) out.size());
    env->SetByteArrayRegion(bytes, 0, (jsize) out.size(), reinterpret_cast<const jbyte *>(out.data()));
    return bytes;
}
