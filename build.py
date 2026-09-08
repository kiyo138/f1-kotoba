#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build.py -- 「F1のことば、あいうえお」静的サイト生成

python build.py を引数なしで実行すると、docs/ 以下に索引ページ・各回の
記事ページ・画像一式を生成する。標準ライブラリのみを使用する。

詳細仕様は _specs/build-spec.md を参照。
"""

from __future__ import annotations

import html
import struct
import sys
from pathlib import Path

# ============================================================
# 0. 定数
# ============================================================

BASE_URL = "https://kiyo138.github.io/f1-kotoba"  # 末尾スラッシュなし。この1箇所のみに書く
SITE_TITLE = "F1のことば、あいうえお"

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"

# ------------------------------------------------------------
# COLUMNS: 回・画像対応表（週に1エントリ追記するだけで新しい回が公開される）
#
#   "NN": (
#       "フォルダ名",
#       [
#           ("画像サフィックス", アンカー見出し文字列 or None, "altテキスト" or None),
#           ...
#       ],
#   )
#
# アンカー: None は冒頭（hero）、文字列はその ■ 見出しの節末に挿入する。
# alt: サフィックスが "hero" のときのみ None を許す（自動生成される）。
# ------------------------------------------------------------

COLUMNS: dict[str, tuple[str, list[tuple[str, str | None, str | None]]]] = {
    "01": (
        "アンダーステア",
        [
            ("hero", None, None),
            (
                "diagram",
                "曲がりたいのに、曲がってくれない",
                "カーブでハンドルを切ってもマシンが外側へ流れていくアンダーステアの図解",
            ),
            (
                "parts",
                "どう直すのか",
                "アンダーステアの調整箇所（ブレーキ配分ダイヤル、フロントウイング角度、タイヤ空気圧）を示した図",
            ),
        ],
    ),
    "02": (
        "インターミディエイト",
        [
            ("hero", None, None),
            (
                "tyres",
                "雨と晴れの、あいだ",
                "スリック・インターミディエイト・フルウェットの3種類のタイヤの溝と色の比較図",
            ),
            (
                "range",
                "履き替えるタイミングが勝負",
                "路面の乾き具合に応じたタイヤの使い分け範囲と、履き替えの目安を示した図",
            ),
        ],
    ),
    "03": (
        "ウイング",
        [
            ("hero", None, None),
            (
                "wing",
                "飛行機の翼を、さかさまにする",
                "飛行機の翼を上下さかさまにするとダウンフォースが生まれることを示した図",
            ),
            (
                "mode",
                "2026年、ウイングが動きはじめた",
                "コーナーモードとストレートモードでフラップの開閉が切り替わるアクティブエアロの図",
            ),
        ],
    ),
}

BUN_FILENAME_TMPL = "f1-{nn}-本文.txt"
IMG_FILENAME_TMPL = "f1-{nn}-{suffix}.png"

CAP_HINT_TEXT = "画像をタップすると大きく表示できます"  # 本文中図版（hero以外）の案内文。固定文言

RULE_HEAVY = "\u2501"  # ━ ヘッダの罫線
RULE_LIGHT = "\u2500"  # ─ フッタの罫線
FULLWIDTH_SPACE = "\u3000"

HEADER_LINE_RE = None  # 後で re.compile する

# 五十音「行」対応表（索引の行見出し用。濁音・半濁音は清音の行にまとめる）
GOJUON_ROWS: list[tuple[str, str]] = [
    ("あ行", "あいうえお"),
    ("か行", "かきくけこがぎぐげご"),
    ("さ行", "さしすせそざじずぜぞ"),
    ("た行", "たちつてとだぢづでど"),
    ("な行", "なにぬねの"),
    ("は行", "はひふへほばびぶべぼぱぴぷぺぽ"),
    ("ま行", "まみむめも"),
    ("や行", "やゆよ"),
    ("ら行", "らりるれろ"),
    ("わ行", "わをん"),
]


def kana_row(kana: str) -> str:
    """かな1文字から「あ行」等の行見出しを返す。表に無ければ「{かな}行」を返す。"""
    for row_name, members in GOJUON_ROWS:
        if kana in members:
            return row_name
    return f"{kana}行"


# ============================================================
# 1. エラー収集
# ============================================================


class BuildError(Exception):
    pass


def esc(s: str) -> str:
    """HTML属性・本文向けのエスケープ（quote=True で常に統一）。"""
    return html.escape(s, quote=True)


# ============================================================
# 2. PNG ヘッダの読み取り（PIL不使用）
# ============================================================

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def read_png_size(path: Path) -> tuple[int, int]:
    with open(path, "rb") as f:
        head = f.read(24)
    if len(head) < 24 or head[:8] != PNG_SIGNATURE:
        raise BuildError(f"PNGシグネチャまたはIHDRが読み取れません: {path}")
    width, height = struct.unpack(">II", head[16:24])
    return width, height


# ============================================================
# 3. 本文txt → 中間表現
# ============================================================


def is_rule_line(line: str, ch: str) -> bool:
    return len(line) > 0 and set(line) == {ch}


def read_text_lines(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8-sig")  # BOMがあれば除去
    lines = raw.split("\n")
    # 行末の \r と空白を除去
    return [ln.rstrip("\r\n \t\u3000") if False else ln.rstrip() for ln in lines]


def extract_header(lines: list[str], nn: str) -> tuple[int, str, str, str]:
    """ヘッダブロックを読み、(本文開始行index, 回数文字列, かな, 語) を返す。"""
    import re

    header_re = re.compile(r"^第(\d+)回「(.)」" + FULLWIDTH_SPACE + r"(.+)$")

    start = None
    for i, ln in enumerate(lines):
        if is_rule_line(ln, RULE_HEAVY):
            start = i
            break
    if start is None:
        raise BuildError("ヘッダ開始の罫線（━のみの行）が見つかりません")

    end = None
    for i in range(start + 1, len(lines)):
        if is_rule_line(lines[i], RULE_HEAVY):
            end = i
            break
    if end is None:
        raise BuildError("ヘッダ終端の罫線（━のみの行）が見つかりません")

    header_block = lines[start : end + 1]
    match = None
    for ln in header_block:
        m = header_re.match(ln)
        if m:
            match = m
            break
    if match is None:
        raise BuildError(
            "ヘッダから「第N回「か」　語」の行を抽出できません。ヘッダ: "
            + " / ".join(header_block)
        )

    round_str, kana, word = match.group(1), match.group(2), match.group(3).strip()
    if int(round_str) != int(nn):
        raise BuildError(
            f"ヘッダの回数がCOLUMNSのキーと一致しません（期待: {int(nn)} / 実際: {round_str}）"
        )
    return end + 1, round_str, kana, word


Node = tuple  # ("h2", text) | ("p", text) | ("ul", [items]) | ("img", suffix, alt)


def parse_body(lines: list[str]) -> tuple[list[str], list[Node]]:
    """本文行（ヘッダ後・フッタ前）を (lead段落のリスト, flowノードのリスト) に変換する。"""
    lead: list[str] = []
    flow: list[Node] = []
    para_buf: list[str] = []
    list_buf: list[str] = []
    seen_heading = False

    def flush_para() -> None:
        nonlocal para_buf
        if para_buf:
            text = "".join(para_buf)
            if seen_heading:
                flow.append(("p", text))
            else:
                lead.append(text)
            para_buf = []

    def flush_list() -> None:
        nonlocal list_buf
        if list_buf:
            flow.append(("ul", list(list_buf)))
            list_buf = []

    for raw in lines:
        line = raw.strip()
        if line == "":
            flush_para()
            flush_list()
            continue
        if line.startswith("■"):
            flush_para()
            flush_list()
            heading = line[1:].strip()
            flow.append(("h2", heading))
            seen_heading = True
            continue
        if line.startswith("・"):
            flush_para()
            list_buf.append(line[1:].strip())
            continue
        # 通常の本文行
        flush_list()
        para_buf.append(line)

    flush_para()
    flush_list()
    return lead, flow


def split_footer(lines: list[str]) -> tuple[list[str], list[str], bool]:
    """本文行から (本文行, フッタ行, フッタ罫線が見つかったか) を返す。"""
    idx = None
    for i, ln in enumerate(lines):
        if is_rule_line(ln, RULE_LIGHT):
            idx = i
            break
    if idx is None:
        return lines, [], False

    content_lines = lines[:idx]
    footer_raw = lines[idx + 1 :]
    footer_lines = [
        ln.strip()
        for ln in footer_raw
        if ln.strip() != "" and not is_rule_line(ln.strip(), RULE_LIGHT)
    ]
    return content_lines, footer_lines, True


# ============================================================
# 4. 回ごとの処理（検証 + 中間表現の構築）
# ============================================================


def section_end_index(flow: list[Node], heading_index: int) -> int:
    for k in range(heading_index + 1, len(flow)):
        if flow[k][0] == "h2":
            return k
    return len(flow)


def build_description(first_paragraph: str) -> str:
    text = "".join(ch if ch not in "\t\r\n" else " " for ch in first_paragraph)
    text = text.strip()
    if len(text) > 100:
        text = text[:100] + "\u2026"
    return text


def process_round(
    nn: str, folder_name: str, images: list[tuple[str, str | None, str | None]]
) -> tuple[dict | None, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    folder = ROOT / folder_name
    if not folder.is_dir():
        errors.append(f"第{nn}回: フォルダが存在しません（{folder}）")
        return None, errors, warnings

    txt_name = BUN_FILENAME_TMPL.format(nn=nn)
    txt_path = folder / txt_name
    candidates = sorted(folder.glob(f"f1-{nn}-本文*.txt"))
    if txt_path not in candidates or len(candidates) != 1:
        errors.append(
            f"第{nn}回: {txt_name} が見つからないか複数あります（探索パス: {folder}）"
        )
        return None, errors, warnings

    try:
        lines = read_text_lines(txt_path)
        body_start, round_str, kana, word = extract_header(lines, nn)
    except BuildError as e:
        errors.append(f"第{nn}回: {e}")
        return None, errors, warnings

    body_lines = lines[body_start:]
    content_lines, footer_lines, footer_found = split_footer(body_lines)
    if not footer_found:
        warnings.append(f"第{nn}回: フッタ罫線（─のみの行）が見つかりません。次回予告なしで生成します")

    lead, flow = parse_body(content_lines)
    headings = [text for (t, text) in flow if t == "h2"]

    # --- 画像の突き合わせ ---------------------------------------
    declared_names = {IMG_FILENAME_TMPL.format(nn=nn, suffix=suf) for suf, _, _ in images}
    actual_names = {p.name for p in folder.glob(f"f1-{nn}-*.png")}
    missing = declared_names - actual_names
    for name in sorted(missing):
        errors.append(f"第{nn}回: COLUMNSが指すPNGがフォルダにありません（期待パス: {folder / name}）")
    extra = actual_names - declared_names
    if extra:
        errors.append(
            f"第{nn}回: フォルダ内にCOLUMNSに載っていないPNGがあります: {', '.join(sorted(extra))}"
        )

    for suf, anchor, alt in images:
        if suf != "hero" and (alt is None or alt.strip() == ""):
            errors.append(
                f"第{nn}回: {IMG_FILENAME_TMPL.format(nn=nn, suffix=suf)} のaltが空です"
            )
        if anchor is not None:
            count = headings.count(anchor)
            if count != 1:
                heading_list = " / ".join(headings) if headings else "(見出しなし)"
                errors.append(
                    f"第{nn}回: アンカー見出し「{anchor}」が本文中に{count}回出現しました"
                    f"（1回である必要があります）。実際の見出し一覧: {heading_list}"
                )

    # PNGサイズの読み取り（存在するものだけ）
    dims: dict[str, tuple[int, int]] = {}
    for suf, _, _ in images:
        name = IMG_FILENAME_TMPL.format(nn=nn, suffix=suf)
        path = folder / name
        if not path.exists():
            continue
        try:
            dims[suf] = read_png_size(path)
        except BuildError as e:
            errors.append(f"第{nn}回: {e}")

    if errors:
        return None, errors, warnings

    title_full = f"第{int(round_str)}回「{kana}」{word}"

    # --- 画像ノードの挿入 -----------------------------------------
    insertions: dict[int, list[Node]] = {}
    hero_alt = None
    hero_dims = dims.get("hero")
    for suf, anchor, alt in images:
        if suf == "hero":
            hero_alt = alt if alt else f"{title_full} のアイキャッチ画像"
            continue
        heading_index = headings_index_of(flow, anchor)
        pos = section_end_index(flow, heading_index)
        insertions.setdefault(pos, []).append(("img", suf, alt))

    final_flow: list[Node] = []
    for i, node in enumerate(flow):
        final_flow.extend(insertions.get(i, []))
        final_flow.append(node)
    final_flow.extend(insertions.get(len(flow), []))

    # --- og:description の元になる最初の段落 ----------------------
    if lead:
        first_paragraph = lead[0]
    else:
        first_paragraph = next((text for (t, text) in flow if t == "p"), "")
    description = build_description(first_paragraph)

    first_h2 = headings[0] if headings else ""

    footer_text = "".join(footer_lines) if footer_lines else None

    data = {
        "nn": nn,
        "folder": folder,
        "round_str": round_str,
        "kana": kana,
        "word": word,
        "title_full": title_full,
        "lead": lead,
        "final_flow": final_flow,
        "footer_text": footer_text,
        "description": description,
        "first_h2": first_h2,
        "images": images,
        "dims": dims,
        "hero_alt": hero_alt,
        "hero_dims": hero_dims,
    }
    return data, errors, warnings


def headings_index_of(flow: list[Node], anchor: str) -> int:
    for i, (t, text) in enumerate(flow):
        if t == "h2" and text == anchor:
            return i
    # ここに来るのは通常あり得ない（事前にcount==1を検証しているため）
    raise BuildError(f"アンカー見出し「{anchor}」が見つかりません")


# ============================================================
# 5. CSS（意匠見本の <style> をそのまま1箇所で管理する）
# ============================================================

COMMON_CSS = """/* --- 1. カラートークン ------------------------------------ */
:root{
  color-scheme: light dark;

  --bg:          #F6F5F2;  /* 連載の地色。図版PNGの地と同一 */
  --ink:         #191B1F;  /* 本文 */
  --sub:         #5A5D64;  /* 補助文字。地色に対し 6.05:1 */
  --accent:      #D4342A;  /* 強調。罫・マーク・大きな文字専用（地色に対し 4.46:1） */
  --accent-text: #B32A21;  /* 小さい文字用に暗くした強調色（5.89:1）*/

  /* 基調4色から起こした中間色 */
  --rule:        #DDDAD3;  /* 細罫・画像の縁 */
  --rule-strong: #C6C2B9;  /* 押せる要素の縁 */
  --panel:       #EDEBE5;  /* 箇条書きなどの面 */
  --card:        #FCFBF9;  /* カード・ボタンの面 */
  --plate-rim:   #DDDAD3;  /* 画像の縁（暗色時に差し替える） */
  --img-filter:  none;

  /* 寸法 */
  --measure: 41.5rem;      /* 本文1行の最大幅 = 664px */
  --wide:    57.5rem;      /* 図版の最大幅   = 920px */
  --pad:     1rem;         /* 画面左右の余白（狭い画面） */
}

@media (prefers-color-scheme: dark){
  :root{
    --bg:          #15171A;
    --ink:         #E9E7E2;
    --sub:         #A8ABB1;  /* 8.0:1 */
    --accent:      #F2564A;  /* 5.3:1 …暗色時は小さい文字にも使える */
    --accent-text: #F2564A;
    --rule:        #2E3238;
    --rule-strong: #3D424A;
    --panel:       #1D2126;
    --card:        #1B1E23;
    --plate-rim:   #4A5058;  /* 明るい図版を暗い地から縁取る */
    --img-filter:  brightness(.90);
  }
}

/* --- 2. 下地 ---------------------------------------------- */
*, *::before, *::after{ box-sizing:border-box; }
html{ -webkit-text-size-adjust:100%; }
body{
  margin:0;
  background:var(--bg);
  color:var(--ink);
  /* OS標準のみ。Latinはsystem-ui、和文は各OSの標準ゴシックに落ちる */
  font-family:
    system-ui, -apple-system,
    "Hiragino Sans", "Hiragino Kaku Gothic ProN",
    "Noto Sans JP",
    "Yu Gothic Medium", "游ゴシック Medium", "Yu Gothic", YuGothic,
    "Meiryo", sans-serif;
  font-size:1.0625rem;      /* 17px */
  line-height:1.9;
  letter-spacing:.03em;
  line-break:strict;        /* 和文の禁則を厳密に */
  text-rendering:optimizeLegibility;
}
@media (min-width:600px){
  body{ font-size:1.125rem; }   /* 18px */
  :root{ --pad:1.5rem; }
}
img{ max-width:100%; height:auto; display:block; }
a{ color:inherit; }
a:focus-visible, summary:focus-visible{
  outline:3px solid var(--ink);
  outline-offset:3px;
  border-radius:4px;
}
.skip{
  position:absolute; left:-9999px; top:0;
  background:var(--card); color:var(--ink);
  padding:12px 16px; border:2px solid var(--ink); z-index:10;
}
.skip:focus{ left:8px; top:8px; }

/* --- 3. 桁組み -------------------------------------------- */
.wrap{ max-width:var(--wide); margin-inline:auto; padding-inline:var(--pad); }
.col { max-width:var(--measure); margin-inline:auto; }
.prose > *      { max-width:var(--measure); margin-inline:auto; }
.prose > figure { max-width:var(--wide); }

/* --- 4. ヘッダ／フッタ ------------------------------------ */
.topbar{ border-bottom:1px solid var(--rule); background:var(--bg); }
.topbar-inner{ max-width:var(--measure); margin-inline:auto; padding-inline:var(--pad); }
.series{
  display:inline-block;
  padding:14px 0;
  font-size:.9375rem;          /* 15px */
  letter-spacing:.16em;
  color:var(--sub);
  text-decoration:none;
  min-height:44px;             /* 押せる高さを確保 */
}
.series:hover{ color:var(--ink); }

.site-footer{
  margin:56px auto 40px;
  padding-top:20px;
  border-top:1px solid var(--rule);
  font-size:.9375rem;
  letter-spacing:.14em;
  color:var(--sub);
}

/* --- 5. 記事タイトル -------------------------------------- */
.title-block{ margin:36px auto 24px; }
.eyebrow{
  margin:0 0 10px;
  font-size:.9375rem;          /* 15px */
  letter-spacing:.14em;
  color:var(--sub);
  line-height:1.4;
}
.title{
  margin:0;
  display:flex; align-items:center; gap:.5rem;
  font-size:1.875rem;          /* 30px */
  line-height:1.3;
  font-weight:700;
  letter-spacing:.04em;
  font-feature-settings:"palt" 1;   /* 見出しの約物アキを詰める */
}
@media (min-width:600px){
  .title{ font-size:2.375rem; gap:.625rem; }   /* 38px */
}

/* かなタイル ── 五十音順という連載の背骨を、記事・索引で同じ形に */
.tile{
  flex:none;
  display:inline-flex; align-items:center; justify-content:center;
  width:1.75em; height:1.75em;
  border:2px solid var(--accent);
  border-radius:7px;
  color:var(--accent);
  font-weight:700;
  letter-spacing:0;
  line-height:1;
  font-feature-settings:normal;
}

/* --- 6. 本文 ---------------------------------------------- */
.prose{ margin-top:8px; }
.prose p{ margin:0 0 1.55em; }
.prose p:last-child{ margin-bottom:0; }

.lede{
  color:var(--sub);
  font-size:1.0625em;
  margin-bottom:2em !important;
}

.prose h2{
  margin:48px 0 18px;
  font-size:1.3125rem;         /* 21px */
  line-height:1.55;
  font-weight:700;
  letter-spacing:.03em;
  font-feature-settings:"palt" 1;
}
.prose h2::after{             /* 図版PNGの「見出し＋赤い下線」に揃える */
  content:"";
  display:block;
  width:72px; height:3px;
  margin-top:10px;
  background:var(--accent);
}
@media (min-width:600px){
  .prose h2{ font-size:1.4375rem; margin-top:64px; }  /* 23px */
}

/* 箇条書き ── 本文の流れから拾い読みできるよう、面で区切る */
.prose ul{
  list-style:none;
  margin:0 0 1.8em;
  padding:18px 20px 18px 22px;
  background:var(--panel);
  border-radius:8px;
}
.prose li{
  position:relative;
  padding-left:1.15em;
  margin:0 0 .55em;
  line-height:1.8;
}
.prose li:last-child{ margin-bottom:0; }
.prose li::before{            /* 原稿の「・」に相当する印 */
  content:"";
  position:absolute;
  left:0; top:.72em;
  width:7px; height:7px;
  border-radius:50%;
  background:var(--accent);
}

/* --- 7. 図版 ---------------------------------------------- */
.fig{ margin:36px auto; }
@media (min-width:600px){ .fig{ margin:44px auto; } }

.plate{                       /* 画像を包む枠。地色が図版の地と同じなので細罫だけで足りる */
  display:block;
  border:1px solid var(--plate-rim);
  border-radius:10px;
  overflow:hidden;
  background:#F6F5F2;
  filter:var(--img-filter);
}
a.plate{ text-decoration:none; }
a.plate:hover{ border-color:var(--rule-strong); }
.fig-hero{ margin-top:8px; }

figcaption{
  margin-top:12px;
  font-size:1rem;             /* 16px */
  line-height:1.75;
  color:var(--sub);
}
.cap-hint{
  display:block;
  margin-top:4px;
  font-size:.9375rem;
  color:var(--sub);
}
.cap-hint::before{ content:"⤢ "; }

/* --- 8. 次回予告（控えめに） ------------------------------ */
.next-up{
  margin:48px auto 0;
  padding-top:20px;
  border-top:1px solid var(--rule);
  color:var(--sub);
  font-size:1rem;
  line-height:1.85;
}
.next-up .label{
  display:block;
  margin-bottom:2px;
  font-size:.875rem;
  letter-spacing:.18em;
  color:var(--accent-text);
  font-weight:700;
}

/* --- 9. 記事末ナビ ---------------------------------------- */
.pager{ margin:40px auto 0; }
.pager-index{
  display:flex; align-items:center; justify-content:center;
  min-height:56px;
  padding:12px 16px;
  border:1px solid var(--rule-strong);
  border-radius:8px;
  background:var(--card);
  text-decoration:none;
  font-weight:700;
  letter-spacing:.06em;
}
.pager-index:hover{ background:var(--panel); }

.pager-sides{
  display:grid; gap:12px;
  grid-template-columns:1fr;
  margin-top:12px;
}
@media (min-width:600px){
  .pager-sides{ grid-template-columns:1fr 1fr; gap:16px; }
}

.pager-link, .pager-empty{
  margin:0;
  min-height:76px;
  padding:14px 16px;
  border-radius:8px;
  display:flex; flex-direction:column; justify-content:center; gap:6px;
}
.pager-link{                          /* 行ける側：面と枠を強く、矢印つき */
  border:1px solid var(--rule-strong);
  background:var(--card);
  text-decoration:none;
  color:var(--ink);
}
.pager-link:hover{ background:var(--panel); }
.pager-empty{                         /* 欠けている側：面なし・枠は細罫・押せない見た目 */
  border:1px dashed var(--rule);
  background:transparent;
  color:var(--sub);
}
.pager-dir{
  font-size:.9375rem;
  letter-spacing:.1em;
  color:var(--sub);
  line-height:1.4;
}
.pager-link .pager-dir{ color:var(--accent-text); font-weight:700; }
.pager-title{
  display:flex; align-items:center; gap:.45rem;
  font-size:1.0625rem; font-weight:700; line-height:1.4;
}
.pager-msg{ font-size:1rem; line-height:1.6; }
.tile-sm{
  font-size:.9375rem;
  width:1.9em; height:1.9em;
  border-width:1.5px; border-radius:5px;
}
.next .pager-dir{ text-align:right; }
.next .pager-title{ justify-content:flex-end; }
.pager-empty.next{ align-items:flex-end; text-align:right; }
@media (max-width:599px){             /* 狭い画面では左揃えに戻す（行頭が揃うほうが読みやすい） */
  .next .pager-dir, .pager-empty.next{ text-align:left; }
  .next .pager-title{ justify-content:flex-start; }
  .pager-empty.next{ align-items:flex-start; }
}"""

INDEX_EXTRA_CSS = """/* ============================================================
   ここから索引ページ固有
   ============================================================ */
:root{ --badge-fg:#FFFFFF; }
@media (prefers-color-scheme: dark){ :root{ --badge-fg:#15171A; } }

/* 索引の見出し
   ── 文字は本文桁（664px）に揃える。カード格子だけが920pxへ広がる。
      記事ページで「文字は664、図版は920」としているのと同じ関係。 */
.index-head{ margin:36px auto 8px; }
.index-title{
  margin:0 0 12px;
  font-size:1.625rem;          /* 26px */
  line-height:1.4;
  font-weight:700;
  letter-spacing:.05em;
  font-feature-settings:"palt" 1;
}
.index-title::after{
  content:"";
  display:block;
  width:72px; height:3px;
  margin-top:12px;
  background:var(--accent);
}
.index-lead{
  margin:0;
  color:var(--sub);
  font-size:1rem;
  line-height:1.85;
}
@media (min-width:600px){ .index-title{ font-size:2rem; } }

/* 行（あ行・か行…）の見出し ── 20回を超えても迷子にならないための区切り */
.row-label{
  display:flex; align-items:center; gap:14px;
  margin:44px auto 18px;
  font-size:1rem;
  font-weight:700;
  letter-spacing:.2em;
  color:var(--sub);
}
.row-label::after{
  content:""; flex:1 1 auto; height:1px; background:var(--rule);
}

/* カード一覧 */
.cards{
  list-style:none;
  margin:0; padding:0;
  display:grid;
  gap:20px;
  grid-template-columns:1fr;        /* スマホは1カラム */
}
@media (min-width:600px){ .cards{ grid-template-columns:repeat(2,1fr); gap:22px; } }
@media (min-width:960px){ .cards{ grid-template-columns:repeat(3,1fr); } }

.card-link{
  display:block;
  height:100%;
  border:1px solid var(--rule);
  border-radius:12px;
  background:var(--card);
  text-decoration:none;
  color:var(--ink);
  overflow:hidden;
  transition:border-color .12s linear, background-color .12s linear;
}
.card-link:hover{ border-color:var(--rule-strong); background:var(--panel); }

.card-thumb{
  display:block;
  border-bottom:1px solid var(--rule);
  background:#F6F5F2;              /* 図版の地と同色。画像との継ぎ目が出ない */
  filter:var(--img-filter);
}
.card-thumb img{ width:100%; aspect-ratio:16/9; object-fit:cover; }

.card-body{ display:block; padding:16px 18px 20px; }

.card-no{
  display:flex; align-items:center; gap:10px;
  font-size:.9375rem;              /* 15px */
  letter-spacing:.12em;
  color:var(--sub);
  line-height:1.4;
  margin-bottom:8px;
}
.badge{
  flex:none;
  padding:3px 8px;
  border-radius:4px;
  background:var(--accent);
  color:var(--badge-fg);
  font-size:.8125rem;              /* 13px。色だけに頼らず「最新」と書く */
  font-weight:700;
  letter-spacing:.08em;
  line-height:1.5;
}
.card-title{
  display:flex; align-items:center; gap:.5rem;
  font-size:1.1875rem;             /* 19px */
  font-weight:700;
  line-height:1.35;
  letter-spacing:.02em;
}
.card-note{
  display:block;
  margin-top:10px;
  color:var(--sub);
  font-size:1rem;                  /* 16px */
  line-height:1.7;
}
.card-note::before{ content:"「"; }
.card-note::after { content:"」"; }"""


# ============================================================
# 6. HTML断片の組み立て
# ============================================================


def render_flow_node(node: Node, nn: str, dims: dict[str, tuple[int, int]]) -> str:
    kind = node[0]
    if kind == "h2":
        return f"      <h2>{esc(node[1])}</h2>\n"
    if kind == "p":
        return f"      <p>{esc(node[1])}</p>\n"
    if kind == "ul":
        items = "".join(f"        <li>{esc(item)}</li>\n" for item in node[1])
        return f"      <ul>\n{items}      </ul>\n"
    if kind == "img":
        _, suffix, alt = node
        w, h = dims[suffix]
        filename = IMG_FILENAME_TMPL.format(nn=nn, suffix=suffix)
        return (
            "      <figure class=\"fig\">\n"
            f"        <a class=\"plate\" href=\"{filename}\">\n"
            f"          <img src=\"{filename}\" width=\"{w}\" height=\"{h}\" loading=\"lazy\" alt=\"{esc(alt)}\">\n"
            "        </a>\n"
            "        <figcaption><span class=\"cap-hint\">"
            f"{esc(CAP_HINT_TEXT)}</span></figcaption>\n"
            "      </figure>\n"
        )
    raise BuildError(f"未知のノード種別: {kind}")


def render_pager_side(data: dict | None, is_prev: bool) -> str:
    if data is None:
        if is_prev:
            return (
                '        <p class="pager-empty prev">\n'
                '          <span class="pager-dir">前の回</span>\n'
                '          <span class="pager-msg">ここが連載のはじまりです。</span>\n'
                "        </p>\n"
            )
        return (
            '        <p class="pager-empty next">\n'
            '          <span class="pager-dir">次の回</span>\n'
            '          <span class="pager-msg">これが最新回です。毎週ひとつ増えます。</span>\n'
            "        </p>\n"
        )
    href = f"../{data['nn']}/"
    dir_label = "← 前の回" if is_prev else "次の回 →"
    side_class = "prev" if is_prev else "next"
    return (
        f'        <a class="pager-link {side_class}" href="{href}">\n'
        f'          <span class="pager-dir">{dir_label}</span>\n'
        f'          <span class="pager-title"><span class="tile tile-sm">{esc(data["kana"])}</span>{esc(data["word"])}</span>\n'
        "        </a>\n"
    )


def render_meta(
    title_pipe: str,
    description: str,
    canonical: str,
    og_url: str,
    og_type: str,
    image_url: str | None,
    image_wh: tuple[int, int] | None,
) -> str:
    lines = [
        f"<title>{esc(title_pipe)}</title>",
        f'<meta name="description" content="{esc(description)}">',
        f'<link rel="canonical" href="{esc(canonical)}">',
        f'<meta property="og:title" content="{esc(title_pipe)}">',
        f'<meta property="og:description" content="{esc(description)}">',
    ]
    if image_url:
        lines.append(f'<meta property="og:image" content="{esc(image_url)}">')
        if image_wh:
            lines.append(f'<meta property="og:image:width" content="{image_wh[0]}">')
            lines.append(f'<meta property="og:image:height" content="{image_wh[1]}">')
    lines.append(f'<meta property="og:type" content="{og_type}">')
    lines.append(f'<meta property="og:url" content="{esc(og_url)}">')
    lines.append(f'<meta property="og:site_name" content="{esc(SITE_TITLE)}">')
    lines.append('<meta property="og:locale" content="ja_JP">')
    if image_url:
        lines.append('<meta name="twitter:card" content="summary_large_image">')
    return "\n".join(lines)


def render_article(data: dict, prev_data: dict | None, next_data: dict | None) -> str:
    nn = data["nn"]
    title_pipe = f"{data['title_full']}｜{SITE_TITLE}"
    canonical = f"{BASE_URL}/{nn}/"
    hero_w, hero_h = data["hero_dims"]
    hero_url = f"{BASE_URL}/{nn}/{IMG_FILENAME_TMPL.format(nn=nn, suffix='hero')}"

    meta_block = render_meta(
        title_pipe=title_pipe,
        description=data["description"],
        canonical=canonical,
        og_url=canonical,
        og_type="article",
        image_url=hero_url,
        image_wh=(hero_w, hero_h),
    )

    lede_html = "".join(f'      <p class="lede">{esc(t)}</p>\n' for t in data["lead"])
    body_html = "".join(render_flow_node(n, nn, data["dims"]) for n in data["final_flow"])

    if data["footer_text"]:
        footer_html = (
            '    <div class="col next-up">\n'
            '      <span class="label">次回</span>\n'
            f"      {esc(data['footer_text'])}\n"
            "    </div>\n\n"
        )
    else:
        footer_html = ""

    prev_html = render_pager_side(prev_data, is_prev=True)
    next_html = render_pager_side(next_data, is_prev=False)

    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{meta_block}
<style>
{COMMON_CSS}
</style>
</head>

<body>
<a class="skip" href="#main">本文へ</a>

<div class="topbar">
  <div class="topbar-inner">
    <a class="series" href="../">{esc(SITE_TITLE)}</a>
  </div>
</div>

<div class="wrap">

  <div class="col title-block">
    <p class="eyebrow">第{int(data['round_str'])}回</p>
    <h1 class="title"><span class="tile">{esc(data['kana'])}</span><span class="word">{esc(data['word'])}</span></h1>
  </div>

  <main id="main">

    <figure class="fig fig-hero">
      <span class="plate">
        <img src="{IMG_FILENAME_TMPL.format(nn=nn, suffix='hero')}" width="{hero_w}" height="{hero_h}" alt="{esc(data['hero_alt'])}">
      </span>
    </figure>

    <div class="prose">
{lede_html}{body_html}    </div><!-- /.prose -->

{footer_html}    <nav class="col pager" aria-label="記事の移動">
      <a class="pager-index" href="../">← 索引へ</a>
      <div class="pager-sides">
{prev_html}{next_html}      </div>
    </nav>

  </main>

  <footer class="col site-footer">{esc(SITE_TITLE)}</footer>
</div>

</body>
</html>
"""


def render_index(rounds: list[dict]) -> str:
    title = SITE_TITLE
    latest = rounds[-1]
    description = (
        f"F1中継で聞こえてくる言葉を、五十音順にひとつずつ。最新は{latest['title_full']}。"
    )
    canonical = f"{BASE_URL}/"
    hero_url = (
        f"{BASE_URL}/{latest['nn']}/{IMG_FILENAME_TMPL.format(nn=latest['nn'], suffix='hero')}"
    )
    hero_w, hero_h = latest["hero_dims"]

    meta_block = render_meta(
        title_pipe=title,
        description=description,
        canonical=canonical,
        og_url=canonical,
        og_type="website",
        image_url=hero_url,
        image_wh=(hero_w, hero_h),
    )

    # 行（あ行・か行…）ごとにグルーピングする
    rows: dict[str, list[dict]] = {}
    for d in rounds:
        row_name = kana_row(d["kana"])
        rows.setdefault(row_name, []).append(d)

    ordered_row_names = [name for name, _ in GOJUON_ROWS if name in rows]
    for name in rows:
        if name not in ordered_row_names:
            ordered_row_names.append(name)

    sections_html_parts = []
    for row_name in ordered_row_names:
        cards = []
        for d in rows[row_name]:
            nn = d["nn"]
            hw, hh = d["hero_dims"]
            is_latest = d is latest
            badge = '<span class="badge">最新</span>' if is_latest else ""
            cards.append(
                "      <li>\n"
                f'        <a class="card-link" href="{nn}/">\n'
                '          <span class="card-thumb">\n'
                f'            <img src="{nn}/{IMG_FILENAME_TMPL.format(nn=nn, suffix="hero")}" width="{hw}" height="{hh}" loading="lazy" alt="{esc(d["hero_alt"])}">\n'
                "          </span>\n"
                '          <span class="card-body">\n'
                f'            <span class="card-no">第{int(d["round_str"])}回{badge}</span>\n'
                f'            <span class="card-title"><span class="tile tile-sm">{esc(d["kana"])}</span>{esc(d["word"])}</span>\n'
                f'            <span class="card-note">{esc(d["first_h2"])}</span>\n'
                "          </span>\n"
                "        </a>\n"
                "      </li>\n"
            )
        sections_html_parts.append(
            f'    <h2 class="row-label">{esc(row_name)}</h2>\n\n'
            '    <ul class="cards">\n\n' + "\n".join(cards) + "    </ul>\n\n"
        )
    sections_html = "".join(sections_html_parts)

    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{meta_block}
<style>
{COMMON_CSS}

{INDEX_EXTRA_CSS}
</style>
</head>

<body>
<a class="skip" href="#main">記事一覧へ</a>

<div class="topbar">
  <div class="topbar-inner">
    <span class="series">{esc(SITE_TITLE)}</span>
  </div>
</div>

<div class="wrap">

  <header class="col index-head">
    <h1 class="index-title">{esc(SITE_TITLE)}</h1>
    <p class="index-lead">
      F1中継を見ていると、聞き慣れない言葉が次々と出てきます。<br>
      毎週ひとつずつ、五十音順に紹介していきます。
    </p>
  </header>

  <main id="main">

{sections_html}  </main>

  <footer class="col site-footer">{esc(SITE_TITLE)}</footer>
</div>

</body>
</html>
"""


# ============================================================
# 7. 書き出し（削除は行わない。差分が無ければ書かない＝冪等性）
# ============================================================


def write_if_changed_text(path: Path, content: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8")
    if path.exists() and path.read_bytes() == data:
        return False
    with open(path, "wb") as f:
        f.write(data)
    return True


def write_if_changed_bytes(path: Path, data: bytes) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() == data:
        return False
    with open(path, "wb") as f:
        f.write(data)
    return True


def write_site(rounds_data: dict[str, dict]) -> None:
    nns = sorted(rounds_data.keys())
    rounds = [rounds_data[nn] for nn in nns]

    pages_written = 0
    images_copied = 0

    DOCS.mkdir(parents=True, exist_ok=True)
    if write_if_changed_bytes(DOCS / ".nojekyll", b""):
        pass

    for i, nn in enumerate(nns):
        data = rounds_data[nn]
        prev_data = rounds_data[nns[i - 1]] if i > 0 else None
        next_data = rounds_data[nns[i + 1]] if i < len(nns) - 1 else None

        out_dir = DOCS / nn
        out_dir.mkdir(parents=True, exist_ok=True)

        for suf, _, _ in data["images"]:
            filename = IMG_FILENAME_TMPL.format(nn=nn, suffix=suf)
            src = data["folder"] / filename
            dst = out_dir / filename
            if write_if_changed_bytes(dst, src.read_bytes()):
                pass
            images_copied += 1

        article_html = render_article(data, prev_data, next_data)
        if write_if_changed_text(out_dir / "index.html", article_html):
            pass
        pages_written += 1

    index_html = render_index(rounds)
    if write_if_changed_text(DOCS / "index.html", index_html):
        pass
    pages_written += 1

    print(f"生成: {len(rounds)}回分 / ページ {pages_written}本 / 画像 {images_copied}枚")


# ============================================================
# 8. エントリポイント
# ============================================================


def main() -> int:
    all_errors: list[str] = []
    all_warnings: list[str] = []
    rounds_data: dict[str, dict] = {}

    for nn in sorted(COLUMNS.keys()):
        folder_name, images = COLUMNS[nn]
        data, errors, warnings = process_round(nn, folder_name, images)
        all_errors.extend(errors)
        all_warnings.extend(warnings)
        if data is not None:
            rounds_data[nn] = data

    if all_errors:
        print("build.py: 致命的なエラーが見つかりました。docs/ は変更していません。", file=sys.stderr)
        for e in all_errors:
            print(f"- {e}", file=sys.stderr)
        return 1

    for w in all_warnings:
        print(f"警告: {w}", file=sys.stderr)

    write_site(rounds_data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
