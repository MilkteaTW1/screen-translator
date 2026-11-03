"""Renders the evaluation pictures with headless Chrome, and takes the right answers from the page itself.

Every page below is made up for this purpose. A script in the page lists each line of text with its exact box, so the
answers need no hand labelling. Pictures and answers are committed: running the evaluation needs no browser.
Run it again only to change the set:  python eval/make_fixtures.py
"""
import html
import json
import re
import subprocess
import tempfile
from pathlib import Path

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
OUT = Path(__file__).parent / "fixtures"
W, H = 1280, 720

EN = [
    "The new release moves speech recognition to its own worker, so a slow network no longer holds up the microphone.",
    "We measured the start time on three laptops and the median dropped from four seconds to just under one.",
    "If the installer warns you about an unknown publisher, open the details and choose to run it anyway.",
    "Each monster keeps its affection between sessions, and feeding it a favorite treat counts for twice as much.",
    "Does anyone know why the second monitor stays black after waking the machine from sleep overnight?",
    "I replaced the cable, updated the driver and reinstalled the dock firmware, but nothing has changed so far.",
    "Our library opens on Saturday mornings from nine until noon, and volunteers are always welcome at the desk.",
    "A small political science reading group meets every other Tuesday to discuss one short book or essay.",
    "Please back up your configuration folder first, because the upgrade rewrites two of the older settings files.",
    "The river trail is closed north of the old bridge until the repairs finish sometime late next spring.",
    "Add the flour slowly while stirring, then let the dough rest under a damp towel for about half an hour.",
    "Short answer: the cache was never cleared, so every request after the first one returned the stale copy.",
    "Tickets for the evening concert go on sale on Friday, and members of the choir may reserve two seats each.",
    "The experiment was repeated with a larger sample, and the difference between both groups largely disappeared.",
    "When the battery falls below ten percent the screen dims itself and background downloads pause until charging.",
    "She moved to the coast after graduating and spent the next six years restoring wooden fishing boats by hand.",
]
SHORT = ["Home", "Settings", "Share", "Reply", "Download", "Sign in", "Popular", "Recent posts", "Join", "Save draft",
         "Release notes", "Getting started", "Open an issue", "Older versions"]
ZH = ["這個版本把語音辨識移到獨立的執行緒,網路再慢也不會卡住麥克風。", "如果安裝程式顯示未知的發行者,請打開詳細資訊後選擇仍要執行。",
      "圖書館週六早上九點開到中午,櫃檯隨時歡迎志工加入。", "請先備份設定資料夾,因為升級會覆寫其中兩個舊的設定檔。",
      "河濱步道在舊橋以北封閉,預計明年春天修復完成後才會重新開放。", "麵粉要慢慢加入並持續攪拌,然後蓋上濕布讓麵團靜置半小時。"]
JA = ["新しいバージョンでは音声認識を別のスレッドに移したので、回線が遅くてもマイクは止まりません。",
      "インストーラーに警告が出た場合は、詳細を開いてそのまま実行を選んでください。",
      "図書館は土曜日の朝九時から正午まで開いていて、ボランティアはいつでも歓迎しています。",
      "アップグレードの前に、設定フォルダーのバックアップを必ず取っておいてください。"]

THEMES = {
    "light": ("#ffffff", "#1f2328", "#59636e", "#f6f8fa", "#d1d9e0"),
    "dark": ("#0e1113", "#d7dadc", "#8ba2ad", "#1a1a1b", "#343536"),
    "sepia": ("#f4ecd8", "#433422", "#7a6a53", "#eadfc4", "#cdbf9f"),
    "lowcontrast": ("#3a3f44", "#9aa3aa", "#868f96", "#42484d", "#50565b"),
}

SCRIPT = r"""<script>
function lines() {
  const out = [], walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    const p = n.parentElement;
    if (!n.textContent.trim() || p.closest('script,style,#gt') || getComputedStyle(p).visibility === 'hidden') continue;
    let cur = null;
    for (let i = 0; i < n.length; i++) {
      const r = document.createRange(); r.setStart(n, i); r.setEnd(n, i + 1);
      const c = r.getClientRects()[0];
      if (!c || !c.width) { if (cur) cur.text += n.textContent[i]; continue; }
      if (!cur || Math.abs(c.top - cur.top) > c.height / 2) { cur = {text: '', x: c.left, top: c.top, right: c.right, bottom: c.bottom}; out.push(cur); }
      cur.text += n.textContent[i]; cur.right = Math.max(cur.right, c.right); cur.bottom = Math.max(cur.bottom, c.bottom);
    }
  }
  return out.map(l => ({text: l.text.trim(), x: l.x + scrollX, y: l.top + scrollY, w: l.right - l.x, h: l.bottom - l.top}));
}
window.addEventListener('load', () => document.fonts.ready.then(() => setTimeout(() => {
  const gt = document.createElement('pre'); gt.id = 'gt'; gt.style.display = 'none';
  gt.textContent = JSON.stringify(lines()); document.body.appendChild(gt);
}, 300)));
</script>"""


def css(theme, size, font="'Segoe UI', Arial, sans-serif"):
    bg, fg, dim, panel, line = THEMES[theme]
    return f"""<style>*{{box-sizing:border-box}}html,body{{margin:0;width:{W}px;overflow:hidden;background:{bg};color:{fg};font:{size}px/1.5 {font}}}
.top{{height:56px;padding:0 24px;background:{panel};border-bottom:1px solid {line};display:flex;gap:28px;align-items:center;font-weight:600}}
.wrap{{display:flex;gap:28px;padding:20px 28px}}.side{{width:210px;flex:none;color:{dim}}}.side div{{padding:6px 0}}
.main{{flex:1;min-width:0}}.post{{background:{panel};border:1px solid {line};border-radius:10px;padding:12px 16px;margin-bottom:14px}}
h1{{font-size:{size * 2}px;margin:0 0 12px}}h2{{font-size:{int(size * 1.4)}px;margin:18px 0 8px}}p{{margin:0 0 10px}}
.dim{{color:{dim};font-size:{max(10, size - 2)}px}}.btn{{display:inline-block;margin:6px 10px 0 0;padding:3px 12px;border:1px solid {line};border-radius:14px;color:{dim}}}
pre{{background:{panel};border:1px solid {line};padding:10px 14px;font:{size - 1}px/1.45 Consolas,monospace;margin:0 0 12px}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid {line};padding:6px 10px;text-align:left}}
.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}.card{{background:{panel};border:1px solid {line};border-radius:12px;padding:14px}}
.dots{{display:grid;grid-template-columns:repeat(20,1fr);gap:7px;width:480px;margin:18px 0}}.dots i{{width:16px;height:16px;border-radius:50%;background:#c8e64a;border:3px solid #111}}
.hero{{height:300px;padding:70px 56px;color:#fff;background:linear-gradient(120deg,#1b2a6b,#8a2f8f 60%,#e0653f)}}.hero h1{{font-size:{size * 3}px}}
</style>"""


def nav(items=SHORT[:5]):
    return '<div class="top">' + "".join(f"<span>{i}</span>" for i in items) + "</div>"


def forum(texts):
    posts = "".join(f'<div class="post"><div class="dim">r/{"example" if i % 2 else "homelab"} · {i + 2} hours ago</div>'
                    f'<p>{t}</p><span class="btn">{i * 3 + 4} votes</span><span class="btn">Share</span></div>'
                    for i, t in enumerate(texts))
    side = "".join(f"<div>{s}</div>" for s in SHORT[6:12])
    return nav() + f'<div class="wrap"><div class="side">{side}</div><div class="main">{posts}</div></div>'


def article(texts):
    body = "".join(f"<h2>{SHORT[(i + 10) % len(SHORT)]}</h2><p>{t}</p>" if i % 3 == 0 else f"<p>{t}</p>" for i, t in enumerate(texts))
    return nav() + f'<div class="wrap"><div class="main"><h1>Notes from the workshop</h1>{body}</div></div>'


def docs(texts):
    code = "npm install --save-dev example-tool\nexport STORE_PATH=./data/settings.json\nnode scripts/migrate.js --dry-run"
    return nav() + f'<div class="wrap"><div class="side"><div>Overview</div><div>Install</div><div>Reference</div></div><div class="main">' \
        f'<h1>Installation</h1><p>{texts[0]}</p><pre>{code}</pre><p>{texts[1]}</p><p>{texts[2]}</p></div></div>'


def table(texts):
    rows = "".join(f"<tr><td>{SHORT[i]}</td><td>{t}</td><td>{i * 37 + 12} MB</td></tr>" for i, t in enumerate(texts))
    return nav() + f'<div class="wrap"><div class="main"><h1>Downloads</h1><table><tr><th>Name</th><th>Description</th><th>Size</th></tr>{rows}</table></div></div>'


def cards(texts):
    c = "".join(f'<div class="card"><h2>{SHORT[i + 2]}</h2><p>{t}</p><span class="btn">Join</span></div>' for i, t in enumerate(texts))
    return nav() + f'<div class="wrap"><div class="main"><div class="cards">{c}</div></div></div>'


def hero(texts):
    return nav() + f'<div class="hero"><h1>Build something small</h1><p>{texts[0]}</p></div><div class="wrap"><div class="main"><p>{texts[1]}</p><p>{texts[2]}</p></div></div>'


def slide(title, sub, dots=True):
    grid = '<div class="dots">' + "<i></i>" * 200 + "</div>" if dots else ""
    return f'<div style="padding:40px 56px"><h1>{title}</h1>{grid}<h2>{sub}</h2></div>'


LAYOUTS = {"forum": (forum, 4), "article": (article, 6), "docs": (docs, 3), "table": (table, 5), "cards": (cards, 6), "hero": (hero, 3)}


def stills():
    n = 0
    for name, (fn, count) in LAYOUTS.items():
        for theme, size in (("light", 16), ("dark", 16), ("dark", 12), ("sepia", 14), ("lowcontrast", 15)):
            texts = [EN[(n + i) % len(EN)] for i in range(count)]
            n += count
            yield f"{name}-{theme}-{size}", "en-US", css(theme, size) + fn(texts)
    for theme in ("light", "dark"):
        yield f"zh-article-{theme}", "zh-Hant-TW", css(theme, 18, "'Microsoft JhengHei', sans-serif") + "".join(f"<p style='margin:24px'>{t}</p>" for t in ZH)
        yield f"ja-article-{theme}", "ja", css(theme, 18, "'Yu Gothic', 'Meiryo', sans-serif") + "".join(f"<p style='margin:24px'>{t}</p>" for t in JA)


def render(name, page, chrome_dir, height=H):
    doc = f"<!doctype html><html><head><meta charset='utf-8'></head><body>{page}{SCRIPT}</body></html>"
    src = Path(chrome_dir) / "page.html"
    src.write_text(doc, encoding="utf-8")
    url = src.as_uri()
    base = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
            "--font-render-hinting=none", f"--user-data-dir={chrome_dir}\\p", f"--window-size={W},{height}"]
    subprocess.run([*base, f"--screenshot={OUT / (name + '.png')}", url], check=True, capture_output=True, timeout=120)
    dom = subprocess.run([*base, "--virtual-time-budget=4000", "--dump-dom", url], check=True, capture_output=True, timeout=120).stdout.decode("utf-8")
    lines = json.loads(html.unescape(re.search(r'<pre id="gt"[^>]*>(.*?)</pre>', dom, re.S).group(1)))
    for l in lines:  # measured before the layout settled, the boxes come out as slivers: never keep such an answer
        if l["w"] < 2.5 * len(l["text"]) or l["h"] < 8:
            raise RuntimeError(f"{name}: box does not fit its text: {l}")
    return lines


def main():
    OUT.mkdir(exist_ok=True)
    index = []
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        for name, lang, page in stills():
            index.append({"name": name, "kind": "still", "lang": lang, "lines": render(name, page, tmp)})
        # long pages, read through a moving window: a scroll sequence
        for name, fn, theme, size in (("scroll-forum-dark", forum, "dark", 15), ("scroll-article-light", article, "light", 16)):
            texts = [f"{t} (note {i + 1})" for i, t in enumerate(EN * 2)]
            index.append({"name": name, "kind": "tall", "lang": "en-US", "lines": render(name, css(theme, size) + fn(texts), tmp, height=2600)})
        # an animated page: the text of the first picture is gone in the second
        pairs = [("Claude Opus and Claude Sonnet", "Two hundred rounds played", "The second room", "Four rooms in total"),
                 ("What happened before", "A language of their own", "Saying goodbye", "The last conversation")]
        for k, (t1, s1, t2, s2) in enumerate(pairs):
            for side, (t, s) in (("a", (t1, s1)), ("b", (t2, s2))):
                name = f"vanish{k}-{side}"
                index.append({"name": name, "kind": "vanish", "lang": "en-US", "lines": render(name, css("sepia", 20) + slide(t, s), tmp)})
    (OUT / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=0), encoding="utf-8")
    print(len(index), "pictures")


if __name__ == "__main__":
    main()
