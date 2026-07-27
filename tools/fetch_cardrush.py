#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TCGdexにカードが登録されていないセットを、cardrush.mediaの公開APIから補完して
data/sets/<セットID>.json を生成する。

使い方:
    python tools/fetch_cardrush.py            # 対象セットを一覧表示するだけ
    python tools/fetch_cardrush.py SM8b       # 指定セットだけ生成
    python tools/fetch_cardrush.py --all      # TCGdexが空のセットを全部生成

出力（1セット1ファイル。アプリが開いたセットの分だけ遅延ロードする）:
    {"set":"SM8b","cards":[[番号, 名前, レア度, 画像ID], ...]}
    画像URLは IMG_TEMPLATE の {id} を画像IDに差し替えて組み立てる。
"""
import json, os, sys, time, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CACHE = os.path.join(DATA, '.cache')
API = 'https://api.cardrush.media'
TCGDEX = 'https://api.tcgdex.net/v2/ja'
IMG_PREFIX = 'https://files.cardrush.media/pokemon/unique_cards/'
IMG_TEMPLATE = IMG_PREFIX + '{id}.webp'
UA = {'User-Agent': 'Mozilla/5.0 (pokecard-manager data builder)'}


def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)


def api(path):
    return get_json(API + path)['body']


def cached(name, build):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, name)
    if os.path.exists(p):
        return json.load(open(p, encoding='utf-8'))
    v = build()
    json.dump(v, open(p, 'w', encoding='utf-8'), ensure_ascii=False)
    return v


def load_rarities():
    return {str(r['id']): r['name'] for r in api('/pokemon/rarities?limit=200')}


def load_card_names():
    """カードID→名前。12,000件超あるので1000件ずつページング。"""
    out, page = {}, 1
    while True:
        b = api('/pokemon/cards?limit=1000&page=%d' % page)
        for c in b['records']:
            out[str(c['id'])] = c['name']
        if page >= b['last_page']:
            break
        page += 1
        time.sleep(0.5)
    return out


def load_packs():
    return api('/pokemon/packs?limit=1000')['records']


def empty_tcgdex_sets():
    """TCGdexでカードが1枚も登録されていないセット。同名の重複ゴースト(CS系)は除く。"""
    sets = get_json(TCGDEX + '/sets')

    def detail(s):
        try:
            d = get_json(TCGDEX + '/sets/' + urllib.parse.quote(s['id']))
        except Exception:
            return None
        return {'id': d['id'], 'name': d.get('name'), 'cards': len(d.get('cards') or []),
                'total': (d.get('cardCount') or {}).get('total')}

    with ThreadPoolExecutor(8) as ex:
        rows = [r for r in ex.map(detail, sets) if r]
    return [r for r in rows if r['cards'] == 0 and not r['id'].startswith('CS')]


# TCGdexの型番とcardrushの型番が食い違うセット（TCGdex ID -> cardrush code）
ALIASES = {
    'sn10a': 'SM10A',   # ジージーエンド
    'sn11': 'SM11',     # ミラクルツイン
    'PCG10': 'WCP',     # ワールドチャンピオンズパック
}


def find_pack(packs, set_id):
    u = ALIASES.get(set_id, set_id).upper()
    for p in packs:
        if (p.get('uppercase_code') or '').upper() == u or (p.get('code') or '').upper() == u:
            return p
    return None


def build_set(set_id, pack, rarities, names):
    """同じ番号に複数の版（再録・別スキャン）がぶら下がるので1枚に絞る。
    レア度が付いている版 > 画像がある版 > 古いID の順で採用。"""
    rows = api('/pokemon/unique_cards?pokemon_pack_id=%d&limit=1000' % pack['id'])
    best = {}
    for u in rows:
        num = (u.get('model_number') or '').split('/')[0].strip()
        # 型番なし（"-"）は基本エネルギー等。番号で識別できないので取り込まない
        if not num or not any(ch.isalnum() for ch in num):
            continue
        rarity = rarities.get(str(u.get('pokemon_rarity_id')), '')
        if rarity == '-':
            rarity = ''
        key = (u['image_key'] or '')
        img_id = key[len('pokemon/unique_cards/'):].replace('.webp', '') if key.startswith('pokemon/unique_cards/') else ''
        cand = [num, names.get(str(u['pokemon_card_id']), ''), rarity, img_id, u['id']]
        cur = best.get(num)
        if cur is None or (bool(cand[2]), bool(cand[3]), -cand[4]) > (bool(cur[2]), bool(cur[3]), -cur[4]):
            best[num] = cand
    cards = [c[:4] for c in sorted(best.values(),
                                   key=lambda c: (0, int(c[0])) if c[0].isdigit() else (1, c[0]))]
    return {'set': set_id, 'source': 'cardrush.media', 'img': IMG_TEMPLATE, 'cards': cards}


def write_set(doc):
    os.makedirs(os.path.join(DATA, 'sets'), exist_ok=True)
    p = os.path.join(DATA, 'sets', doc['set'] + '.json')
    with open(p, 'w', encoding='utf-8', newline='\n') as f:
        f.write('{"set":%s,"source":%s,"img":%s,"cards":[\n' % (
            json.dumps(doc['set']), json.dumps(doc['source']), json.dumps(doc['img'])))
        f.write(',\n'.join(json.dumps(c, ensure_ascii=False) for c in doc['cards']))
        f.write('\n]}\n')
    return p


def write_index():
    """data/index.json … アプリはこれを見て「補完データがあるセットか」を判断する。"""
    d = os.path.join(DATA, 'sets')
    idx = {}
    for fn in sorted(os.listdir(d)):
        if fn.endswith('.json'):
            doc = json.load(open(os.path.join(d, fn), encoding='utf-8'))
            idx[doc['set']] = len(doc['cards'])
    with open(os.path.join(DATA, 'index.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(idx, f, ensure_ascii=False, indent=0, sort_keys=True)
        f.write('\n')
    return idx


def main():
    args = [a for a in sys.argv[1:]]
    packs = cached('packs.json', load_packs)
    rarities = cached('rarities.json', load_rarities)

    if not args:
        empties = empty_tcgdex_sets()
        hit = [(e, find_pack(packs, e['id'])) for e in empties]
        ok = [(e, p) for e, p in hit if p]
        ng = [e for e, p in hit if not p]
        print('TCGdexが空のセット: %d件 / %d枚' % (len(empties), sum(e['total'] or 0 for e in empties)))
        print('cardrushで補完可能 : %d件 / %d枚' % (len(ok), sum(e['total'] or 0 for e, _ in ok)))
        print('補完できない       : %d件 / %d枚' % (len(ng), sum(e['total'] or 0 for e in ng)))
        for e in ng:
            print('   - %-7s %s' % (e['id'], e['name']))
        return

    names = cached('cardnames.json', load_card_names)
    if args[0] == '--all':
        targets = [e['id'] for e in empty_tcgdex_sets()]
    else:
        targets = args

    for sid in targets:
        pack = find_pack(packs, sid)
        if not pack:
            print('skip %-7s cardrushに該当パック無し' % sid)
            continue
        doc = build_set(sid, pack, rarities, names)
        p = write_set(doc)
        noimg = sum(1 for c in doc['cards'] if not c[3])
        noname = sum(1 for c in doc['cards'] if not c[1])
        print('%-7s %4d枚  名前なし%-3d 画像なし%-3d  %s' % (
            sid, len(doc['cards']), noname, noimg, os.path.relpath(p, ROOT)))
        time.sleep(0.3)

    idx = write_index()
    print('\ndata/index.json 更新: %d セット / %d枚' % (len(idx), sum(idx.values())))


if __name__ == '__main__':
    main()
