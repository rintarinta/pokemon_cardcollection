#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TCGdexにもcardrushにも未登録の発売直後セットを、公式サイト＋pokecahackから生成する。

データソース:
    - 名前・通常枠レア度: pokemon-card.com カード検索（resultAPI + 詳細ページ）
      ※公式検索は同名カードをまとめるため通常枠(001〜)のみ取れる
    - シークレット枠の番号・レア度: pokecahack.com の収録リスト見出し（AR（…）12種 等）
    - シークレット枠の名前: Bulbapedia の英名リストで「同名の通常枠」に対応付けて和名を引き継ぐ
    - 画像: pokecahack.com の全カード画像

使い方:
    python tools/fetch_official.py M6 955 m6 ストームエメラルダ
        引数: セットID / 公式検索の収録商品ID(pg) / pokecahackのスラッグ / セット名
        pgは https://www.pokemon-card.com/card-search/ の商品絞り込みのvalue。

生成物:
    data/sets/<セットID>.json（fetch_cardrush.pyと同じスキーマ＋name）
    data/extra_sets.json（TCGdexに無いセットの一覧。アプリがセット一覧に追加表示する）
    ※ data/index.json と data/rarities.json の更新は fetch_cardrush.py の関数を使う

TCGdex/cardrushにセットが入ったら、data/extra_sets.json から該当行を消すだけでよい
（アプリはTCGdex側を優先するため、同梱データは自動でフォールバックに回る）。
"""
import json, os, re, sys, time, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_cardrush import write_index, build_rarities, DATA

OFFICIAL = 'https://www.pokemon-card.com'
UA = {'User-Agent': 'Mozilla/5.0 (pokecard-manager data builder)'}


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


def official_cards(pg):
    """公式検索: cardID -> 和名。同名まとめのため通常枠のみ。"""
    out, page = {}, 1
    while True:
        d = json.loads(get_text(f'{OFFICIAL}/card-search/resultAPI.php?keyword=&pg={pg}&page={page}'))
        for c in d.get('cardList') or []:
            out[c['cardID']] = c.get('cardNameAltText') or c.get('cardNameViewText') or ''
        if page >= int(d.get('maxPage') or 1):
            break
        page += 1
        time.sleep(0.3)
    return out


def official_detail(card_id):
    """詳細ページから (番号, 型番の分母, レア度アイコン名) を取る。"""
    html = get_text(f'{OFFICIAL}/card-search/details.php/card/{card_id}/regu/all')
    num = re.search(r'(\d{3})\s*/\s*(\d{3})', html.replace('&nbsp;', ' '))
    ic = re.search(r'ic_rare_([a-z0-9_]+)\.gif', html)
    return (num.group(1) if num else None), (num.group(2) if num else None), (ic.group(1) if ic else '')


# 公式レア度アイコン（ic_rare_<コード>_c.gif 等）-> 表示コード。見つかった分だけ随時追加
ICON_RARITY = {'c_c': 'C', 'u_c': 'U', 'r_c': 'R', 'rr_c': 'RR', 'ace_c': 'ACE',
               'c': 'C', 'u': 'U', 'r': 'R', 'rr': 'RR', 'ace': 'ACE',
               'ar': 'AR', 'sr': 'SR', 'sar': 'SAR', 'ur': 'UR', 'mur': 'MUR', 'chr': 'CHR'}

# 収録セット内に同名の通常枠が無いカード（他セット由来のSR再録等）の英名 -> 和名。
# ツール実行後に「名前なし」と出た番号をBulbapediaで確認して随時追加する。
EN_JA_FALLBACK = {
    'Pokémon Catcher': 'ポケモンキャッチャー',
    'Growing Energy': 'グロウ草エネルギー',
    'Nitro Energy': 'ニトロ炎エネルギー',
    'Bubbly Energy': 'バブル水エネルギー',
}


def pokecahack_page(slug):
    return get_text(f'https://pokecahack.com/{slug}/')


def pokecahack_images(html, slug):
    """番号 -> 画像URL（同番号は最初の1枚）。"""
    pat = re.compile(r'src="(https://pokecahack\.com/wp-content/uploads/([^"]*?%s_(\d+)(?:-\d+)?\.(?:png|jpg)))"' % re.escape(slug), re.I)
    out = {}
    for m in pat.finditer(html):
        num = int(m.group(3))
        out.setdefault(num, (m.group(1), m.group(2)))  # (フルURL, uploads以下)
    return out


def pokecahack_secret_ranges(html, slug):
    """カードリスト見出し（AR（アートレア）12種 等）から 番号 -> レア度コード。"""
    events = []
    for m in re.finditer(r'<h([234])[^>]*>(.*?)</h\1>', html, re.S):
        txt = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        events.append((m.start(), 'H', txt))
    for m in re.finditer(r'%s_(\d+)(?:-\d+)?\.(?:png|jpg)"' % re.escape(slug), html, re.I):
        events.append((m.start(), 'IMG', m.group(1)))
    events.sort()
    cur, out = None, {}
    for _pos, kind, val in events:
        if kind == 'H':
            m = re.match(r'(AR|SR|SAR|UR|MUR|CHR)（', val)
            cur = m.group(1) if m else None
        elif cur:
            out[int(val)] = cur
    return out


def parse_bulbapedia(html, denom):
    out = {}
    for r in re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.S):
        m = re.search(r'(\d{3})/%s' % denom, r)
        if not m:
            continue
        cells = [re.sub(r'<[^>]+>', '', c).replace('&#160;', ' ').strip()
                 for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, re.S)]
        name = next((c for c in cells[1:] if re.search(r'[A-Za-z]', c)), '')
        out[int(m.group(1))] = re.sub(r'\s+', ' ', name)
    return out


def main():
    if len(sys.argv) < 5:
        print(__doc__)
        return
    set_id, pg, slug, set_name = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    bulba_url = sys.argv[5] if len(sys.argv) > 5 else None

    print('公式検索から名前を取得中...')
    names_by_cardid = official_cards(pg)
    print('  %d件（同名まとめ後）' % len(names_by_cardid))

    print('公式詳細ページから番号・レア度を取得中...')
    ja_by_num, rarity_by_num, unknown_icons, denom = {}, {}, set(), None
    for cid, name in names_by_cardid.items():
        num, den, icon = official_detail(cid)
        if num:
            n = int(num)
            ja_by_num[n] = name
            denom = denom or den
            code = ICON_RARITY.get(icon)
            if code:
                rarity_by_num[n] = code
            elif icon:
                unknown_icons.add(icon)
        time.sleep(0.25)
    if unknown_icons:
        print('  未対応のレア度アイコン:', sorted(unknown_icons), '（ICON_RARITYに追加してください）')
    print('  番号判明 %d件（型番分母 %s）' % (len(ja_by_num), denom))

    print('pokecahackから画像とシークレットレア度を取得中...')
    hack = pokecahack_page(slug)
    imgs = pokecahack_images(hack, slug)
    secrets = pokecahack_secret_ranges(hack, slug)
    total = max(imgs) if imgs else max(ja_by_num)
    print('  画像 %d枚（1〜%d）・シークレットレア度 %d件' % (len(imgs), total, len(secrets)))
    rarity_by_num.update(secrets)
    if bulba_url:
        print('Bulbapediaから同名カードの対応を取得中...')
        en_by_num = parse_bulbapedia(get_text(bulba_url), denom)
        ja_by_en = {}
        for n in sorted(en_by_num):
            if n <= int(denom) and n in ja_by_num and en_by_num[n] not in ja_by_en:
                ja_by_en[en_by_num[n]] = ja_by_num[n]
        filled = 0
        for n in range(1, total + 1):
            en = en_by_num.get(n, '')
            if n not in ja_by_num:
                # シークレット枠や別イラスト版は、同名の通常枠から和名を引き継ぐ
                ja = ja_by_en.get(en) or EN_JA_FALLBACK.get(en)
                if ja:
                    ja_by_num[n] = ja
                    filled += 1
            if n not in rarity_by_num and n <= int(denom) and en:
                # 同名まとめで公式検索に出ない別イラスト版は、同名カードのレア度を引き継ぐ
                sib = next((m for m in rarity_by_num if m <= int(denom) and en_by_num.get(m) == en), None)
                if sib:
                    rarity_by_num[n] = rarity_by_num[sib]
        print('  同名対応で名前 %d件を補完' % filled)

    cards = []
    for n in range(1, total + 1):
        num = '%03d' % n
        img_id = imgs.get(n, (None, ''))[1]
        cards.append([num, ja_by_num.get(n, ''), rarity_by_num.get(n, ''), img_id])
    doc = {'set': set_id, 'name': set_name, 'source': 'pokemon-card.com + pokecahack.com',
           'img': 'https://pokecahack.com/wp-content/uploads/{id}', 'cards': cards}
    p = write_set_with_name(doc)
    noname = sum(1 for c in cards if not c[1])
    norar = sum(1 for c in cards if not c[2])
    noimg = sum(1 for c in cards if not c[3])
    print('%s %d枚  名前なし%d レア度なし%d 画像なし%d  %s' % (set_id, len(cards), noname, norar, noimg, p))

    update_extra_sets(set_id, set_name, total)
    write_index()
    build_rarities()


def write_set_with_name(doc):
    """write_set と同じ整形＋nameフィールド付きで書き出す。"""
    os.makedirs(os.path.join(DATA, 'sets'), exist_ok=True)
    p = os.path.join(DATA, 'sets', doc['set'] + '.json')
    with open(p, 'w', encoding='utf-8', newline='\n') as f:
        f.write('{"set":%s,"name":%s,"source":%s,"img":%s,"cards":[\n' % (
            json.dumps(doc['set'], ensure_ascii=False), json.dumps(doc['name'], ensure_ascii=False),
            json.dumps(doc['source']), json.dumps(doc['img'])))
        f.write(',\n'.join(json.dumps(c, ensure_ascii=False) for c in doc['cards']))
        f.write('\n]}\n')
    return p


def update_extra_sets(set_id, set_name, total):
    """data/extra_sets.json … TCGdexのセット一覧に無いセット。アプリが一覧へ追加表示する。"""
    p = os.path.join(DATA, 'extra_sets.json')
    rows = []
    if os.path.exists(p):
        rows = json.load(open(p, encoding='utf-8'))
    rows = [r for r in rows if r['id'] != set_id]
    rows.append({'id': set_id, 'name': set_name, 'total': total})
    with open(p, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
        f.write('\n')
    print('data/extra_sets.json 更新: %d件' % len(rows))


if __name__ == '__main__':
    main()
