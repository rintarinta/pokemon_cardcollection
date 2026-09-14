#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TCGdexにカードはあるが画像が1枚も無いセット（メガ弾のM1S〜M5等）へ、
pokecahack.com の画像だけを継ぎ足す。

fetch_cardrush.py / fetch_official.py との違い:
    - fetch_cardrush.py  … TCGdexにカードが0枚のセットを、名前・レア度・画像ごと補完
    - fetch_official.py  … TCGdexのセット一覧にすら無い発売直後セットを丸ごと生成
    - このスクリプト     … カードと名前・レア度はTCGdexにあるので「画像だけ」補完

そのためレア度は空で書き出す。アプリの表示レア度は事前集計（data/rarities.json、
中身はTCGdex由来）が使われるため、こちらで推測を混ぜると逆に精度が落ちる。
名前はTCGdexから取って書き込む（同梱データ単体でも中身が読めるようにするだけで、
アプリ側はTCGdexの名前を優先する）。

使い方:
    python tools/fetch_images.py            # 画像が無いセットと補完可否を一覧表示
    python tools/fetch_images.py M1S        # 指定セット（スラッグは既定でセットIDの小文字）
    python tools/fetch_images.py M2a m2a    # スラッグを明示指定
    python tools/fetch_images.py --all      # SLUGS の対応表を全部生成

生成物:
    data/sets/<セットID>.json（fetch_cardrush.pyと同じスキーマ。レア度列は空）
    data/index.json / data/rarities.json も更新する
    ※ extra_sets.json は触らない（TCGdexにあるセットなので一覧への追加表示は不要）
"""
import json, os, re, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_cardrush import DATA, ROOT, TCGDEX, UA, get_json, write_index, build_rarities

HACK = 'https://pokecahack.com'
IMG_TEMPLATE = HACK + '/wp-content/uploads/{id}'

# セットID -> pokecahackのスラッグ。既定はセットIDの小文字なので、一致しないものだけ書く。
# 画像が無いセットを見つけたら `python tools/fetch_images.py` の一覧で当たりを確認して追加する。
SLUGS = {
    'M1S': 'm1s',   # メガシンフォニア
    'M1L': 'm1l',   # メガブレイブ
    'M2': 'm2',     # インフェルノX
    'M2a': 'm2a',   # MEGAドリームex
    'M3': 'm3',     # ムニキスゼロ
    'M4': 'm4',     # ニンジャスピナー
    'M5': 'm5',     # アビスアイ
}


def get_text(url):
    req = urllib.request.Request(url, headers=UA)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode('utf-8', errors='replace')
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)


def tcgdex_set(set_id):
    return get_json(TCGDEX + '/sets/' + urllib.parse.quote(set_id))


def hack_images(slug):
    """番号 -> 画像ID（uploads/以下のパス）。

    `m2a_154_1.png` のような連番サフィックス付きも拾うが、素の `m2a_154.png` があれば
    そちらを優先する（サフィックス版は別イラスト・差し替え版のことがある）。
    `-300x419` のようなサムネイルは原寸だけ残るよう正規表現で弾いている。
    """
    html = get_text('%s/%s/' % (HACK, slug))
    pat = re.compile(r'src="%s/wp-content/uploads/([^"]*?%s_(\d+)([_-]\d+)?\.(?:png|jpg))"'
                     % (re.escape(HACK), re.escape(slug)), re.I)
    out = {}
    for m in pat.finditer(html):
        num, plain = int(m.group(2)), not m.group(3)
        if num not in out or (plain and not out[num][1]):
            out[num] = (m.group(1), plain)
    return {n: v[0] for n, v in out.items()}


def imageless_sets():
    """TCGdexにカードはあるが、画像が1枚も無いセット。"""
    def detail(s):
        try:
            d = tcgdex_set(s['id'])
        except Exception:
            return None
        cards = d.get('cards') or []
        if not cards or any(c.get('image') for c in cards):
            return None
        return {'id': d['id'], 'name': d.get('name'), 'cards': len(cards)}

    with ThreadPoolExecutor(8) as ex:
        return [r for r in ex.map(detail, get_json(TCGDEX + '/sets')) if r]


def build(set_id, slug):
    d = tcgdex_set(set_id)
    imgs = hack_images(slug)
    cards = []
    for c in d.get('cards') or []:
        num = c.get('localId') or ''
        n = int(num) if num.isdigit() else None
        cards.append([num, c.get('name') or '', '', imgs.get(n, '')])
    return {'set': set_id, 'name': d.get('name') or '', 'source': 'pokecahack.com (画像のみ) + TCGdex (名前)',
            'img': IMG_TEMPLATE, 'cards': cards}, len(imgs)


def write_set(doc):
    os.makedirs(os.path.join(DATA, 'sets'), exist_ok=True)
    p = os.path.join(DATA, 'sets', doc['set'] + '.json')
    with open(p, 'w', encoding='utf-8', newline='\n') as f:
        f.write('{"set":%s,"name":%s,"source":%s,"img":%s,"cards":[\n' % (
            json.dumps(doc['set'], ensure_ascii=False), json.dumps(doc['name'], ensure_ascii=False),
            json.dumps(doc['source'], ensure_ascii=False), json.dumps(doc['img'])))
        f.write(',\n'.join(json.dumps(c, ensure_ascii=False) for c in doc['cards']))
        f.write('\n]}\n')
    return p


def main():
    args = sys.argv[1:]

    if not args:
        rows = imageless_sets()
        print('TCGdexに画像が無いセット: %d件 / %d枚' % (len(rows), sum(r['cards'] for r in rows)))
        for r in sorted(rows, key=lambda r: r['id']):
            slug = SLUGS.get(r['id'])
            mark = 'pokecahack: %s' % slug if slug else '対応表(SLUGS)に未登録'
            print('   %-6s %-24s %4d枚  %s' % (r['id'], r['name'], r['cards'], mark))
        return

    if args[0] == '--all':
        targets = [(sid, slug) for sid, slug in sorted(SLUGS.items())]
    elif len(args) >= 2:
        targets = [(args[0], args[1])]
    else:
        targets = [(args[0], SLUGS.get(args[0], args[0].lower()))]

    for set_id, slug in targets:
        try:
            doc, found = build(set_id, slug)
        except Exception as e:
            print('skip %-6s %s' % (set_id, e))
            continue
        p = write_set(doc)
        noimg = [c[0] for c in doc['cards'] if not c[3]]
        print('%-6s %4d枚  pokecahackに%d枚  画像なし%d %s  %s' % (
            set_id, len(doc['cards']), found, len(noimg),
            ('(%s)' % ','.join(noimg[:8])) if noimg else '', os.path.relpath(p, ROOT)))
        time.sleep(0.3)

    idx = write_index()
    print('\ndata/index.json 更新: %d セット / %d枚' % (len(idx), sum(idx.values())))
    build_rarities()


if __name__ == '__main__':
    main()
