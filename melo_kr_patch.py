# melo_kr_patch.py — 안전한 KR용 런타임 패치 (BERT 의존 치환, 미지 토큰 스킵)
import torch
import melo.utils as _utils
import melo.text as _text

_FLAG = "_MELO_KR_PATCHED_V2"
if not getattr(_utils, _FLAG, False):

    def _fallback_id(symmap):
        for k in ("SP","sp","SIL","sil","PAD","pad","_"):
            if k in symmap:
                return int(symmap[k])
        return int(next(iter(symmap.values()))) if symmap else 0

    def cleaned_text_to_sequence(cleaned_text, tones, language, symbol_to_id_map):
        # cleaned_text -> 토큰 리스트
        if isinstance(cleaned_text, str):
            toks = [t for t in cleaned_text.strip().split() if t]
        elif isinstance(cleaned_text, (list, tuple)):
            toks = list(cleaned_text)
        else:
            toks = []

        # 심볼 매핑 (소문자도 시도), 모르면 스킵
        ids = []
        for t in toks:
            if t in symbol_to_id_map:
                ids.append(int(symbol_to_id_map[t]))
            else:
                tl = t.lower() if isinstance(t, str) else t
                if tl in symbol_to_id_map:
                    ids.append(int(symbol_to_id_map[tl]))

        # 모두 스킵되면 최소 한 개는 넣기(무음/패드 우선)
        if not ids:
            ids = [_fallback_id(symbol_to_id_map)]

        # tone 정규화 (길이 맞추기)
        if isinstance(tones, str):
            tone_ids = [int(x) for x in tones.strip().split() if x.isdigit()]
        elif isinstance(tones, (list, tuple)):
            tone_ids = [int(x) for x in tones]
        else:
            tone_ids = []
        if len(tone_ids) != len(ids):
            tone_ids = [0] * len(ids)

        return ids, tone_ids, language

    def get_text_for_tts_infer(text, language, hps, device, symbol_to_id):
        from melo.text.cleaner import clean_text as _base_clean
        language_str = (language or "").upper()

        # 1) 클린 + 시퀀스화
        out = _base_clean(text, language_str)
        if isinstance(out, (list, tuple)) and len(out) >= 4:
            norm_text, phone, tone, word2ph = out[0], out[1], out[2], out[3]
        else:
            norm_text, phone, tone, word2ph = str(text).strip(), "", "", [0]
        phone, tone, language_str = cleaned_text_to_sequence(phone, tone, language_str, symbol_to_id)

        # 2) 텐서 구성
        T = len(phone)
        phones = torch.tensor(phone, dtype=torch.long)          # (T,)
        tones  = torch.tensor(tone,  dtype=torch.long)          # (T,)

        # 3) BERT/JA_BERT 자리채움 (※ 2D로 반환: (C, T))
        bert    = torch.zeros((1024, T), dtype=torch.float32)   # api.py에서 unsqueeze(0)하여 (1,1024,T)
        ja_bert = torch.zeros(( 768, T), dtype=torch.float32)   # -> (1,768,T)

        # 4) language ids
        try:
            langs = getattr(getattr(hps, "data", None), "languages", None) or []
            lid_map = {str(x).upper(): i for i, x in enumerate(langs)}
            lid = int(lid_map.get(language_str, 0))
        except Exception:
            lid = 0
        lang_ids = torch.full((T,), lid, dtype=torch.long)

        return bert, ja_bert, phones, tones, lang_ids

    # 패치 주입
    _text.cleaned_text_to_sequence = cleaned_text_to_sequence
    _utils.get_text_for_tts_infer  = get_text_for_tts_infer
    setattr(_utils, _FLAG, True)
