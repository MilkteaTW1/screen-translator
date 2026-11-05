"""macOS text recognition with Apple's Vision framework (offline, built in, no language packs to install)."""
import objc
import Quartz
import Vision
from Foundation import NSData

# Languages worth trying when the screen language is "auto" (reading with all ~30 would be slow).
AUTO_PREFERRED = ["en-US", "zh-Hant", "zh-Hans", "ja-JP", "ko-KR", "fr-FR", "de-DE", "es-ES", "ru-RU", "it-IT", "pt-BR"]


def _request():
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    return req


def languages():
    """[(tag, name)] of the languages Vision can read, like ('ja-JP', 'Japanese')."""
    from Foundation import NSLocale
    langs, _err = _request().supportedRecognitionLanguagesAndReturnError_(None)
    loc = NSLocale.localeWithLocaleIdentifier_("en")
    return [(str(l), str(loc.displayNameForKey_value_("kCFLocaleIdentifierKey", str(l)) or l)) for l in (langs or [])]


def _cg_image(bgra, w, h):
    data = NSData.dataWithBytes_length_(bgra, len(bgra))
    provider = Quartz.CGDataProviderCreateWithCFData(data)
    return Quartz.CGImageCreate(
        w, h, 8, 32, w * 4, Quartz.CGColorSpaceCreateDeviceRGB(),
        Quartz.kCGBitmapByteOrder32Little | Quartz.kCGImageAlphaNoneSkipFirst,
        provider, None, False, Quartz.kCGRenderingIntentDefault)


def read(bgra, w, h, tag):
    """[(text, x, y, width, height)] in pixels of the picture, one entry per text line, top to bottom."""
    with objc.autorelease_pool():
        req = _request()
        req.setRecognitionLanguages_([tag])
        req.setUsesLanguageCorrection_(True)
        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(_cg_image(bgra, w, h), None)
        ok, err = handler.performRequests_error_([req], None)
        if not ok:
            raise RuntimeError(f"Vision failed: {err}")
        out = []
        for obs in req.results() or []:
            cands = obs.topCandidates_(1)
            if not cands:
                continue
            box = obs.boundingBox()  # 0..1, origin at the bottom left
            out.append((str(cands[0].string()), box.origin.x * w, (1 - box.origin.y - box.size.height) * h,
                        box.size.width * w, box.size.height * h))
        return sorted(out, key=lambda r: (round(r[2] / 4), r[1]))
