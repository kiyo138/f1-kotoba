# SVG → PNG 変換ノート（第3回「う・ウイング」で確立した手順）

## 使えないツール（本環境に未導入。導入せず headless Chrome で代替すること）
- rsvg-convert
- Inkscape
- ImageMagick（convert / magick）
- cairosvg

## 実際に成功した変換コマンド（そのままコピペで動作確認済み）

前提：SVGをそのままHTML本文に埋め込んだラッパーHTMLを作り、Chromeのheadlessスクリーンショットで撮る。
`--window-size` は変換対象SVGの `width`/`height`（viewBox寸法）と完全に一致させること。

ラッパーHTMLの型：
```html
<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;padding:0;overflow:hidden}</style></head><body>（ここにSVGをそのまま貼る）</body></html>
```

コマンド（Bashツール／Git Bash 表記。パスにスペースを含むため引用符必須）：

```bash
"/c/Program Files/Google/Chrome/Application/chrome.exe" --headless --disable-gpu --hide-scrollbars --force-device-scale-factor=1 --window-size=1600,900 --screenshot="/c/Users/ukyoa/Documents/claude-code/F1 Column/ウイング/f1-03-hero.png" "file:///C:/path/to/scratchpad/hero.html"
```

```bash
"/c/Program Files/Google/Chrome/Application/chrome.exe" --headless --disable-gpu --hide-scrollbars --force-device-scale-factor=1 --window-size=1600,780 --screenshot="/c/Users/ukyoa/Documents/claude-code/F1 Column/ウイング/f1-03-wing.png" "file:///C:/path/to/scratchpad/wing.html"
```

```bash
"/c/Program Files/Google/Chrome/Application/chrome.exe" --headless --disable-gpu --hide-scrollbars --force-device-scale-factor=1 --window-size=1600,720 --screenshot="/c/Users/ukyoa/Documents/claude-code/F1 Column/ウイング/f1-03-mode.png" "file:///C:/path/to/scratchpad/mode.html"
```

変換後の寸法確認：
```bash
python -c "from PIL import Image;print(Image.open(r'...png').size)"
```

## 落とし穴（必ず守ること）

- 日本語フォントは `'Yu Gothic','Meiryo',sans-serif` を指定する。
- `<text>` 要素ごとに `font-family` 属性を直接書く。CSSクラスやCSS継承には頼らない（headless Chrome環境によって継承が効かない・別フォントに落ちることがあるため）。
- `--window-size` と SVG の `width`/`height`（viewBox寸法）を完全に一致させる。ずれると余白や拡大縮小が入り込む。
- 影は `filter`（`feGaussianBlur` 等）ではなく `radialGradient` で作る。headless環境でfilterの再現性が不安定なため。
- 変換しただけで完了にしない。**出力PNGを必ず1枚ずつ目視すること**（豆腐化、文字の重なり、要素のはみ出し・見切れ、矢印や引き出し線の先端位置のズレ、明背景での文字の視認性）。

## ヒーローSVGの流用手順（次回以降）

`f1-03-hero.svg` をコピーして次回分を作る場合、差し替えるのは以下のみ。**マシンの造形と座標は動かさない**。

- `text#seriesNo` … 「第N回」
- `text#kana` … かな1文字
- `text#word` … 語のカタカナ（字数が増えたら `font-size` を 95→85 等に下げる）
- 配色（下表のアクセント／インク／背景／車体／タイヤの16進値を全置換）

明るい背景の回はインクを濃く、暗い背景の回は `#FFFFFF` に戻すこと。

## 配色ローテーション表

| かな | 配色 |
|---|---|
| あ | ペトロールグリーン × カッパー |
| い | ガンメタル × ライムイエロー |
| う | オフホワイト × コバルトブルー |
| え | バーガンディ × ゴールド |
| お | マットブラック × シアン |
