"""Folds the long tail of album tags (MusicBrainz / Last.fm hand out hundreds: 'Post-Punk revival', 'Nwobhm', 'Van Gogh'...)
into a short list of genres worth filtering by. This only changes what is shown and filtered: the raw tags stay in meta.json,
and search still looks through them.

Rules are tried in order and the first match wins, so put the specific ones first. Tags that match nothing (countries,
cities, 'Female Vocalists', 'Under 50 Listeners'...) are dropped."""
import re
from functools import lru_cache

R = re.compile
# (pattern, [genres]) - matched against the lower-cased tag
RULES = [
    # --- things that are not genres at all
    (R(r"^(female vocalists?|male vocalists?|under \d+ listeners|seen live|soft visual|van gogh|pigfuck|usa|us|uk|american|british|"
       r"canadian|canada|australian|german|russian|ukrainian|icelandic|welsh|winnipeg|new zealand|serb\w*|croat\w*|bosnian|"
       r"montenegrin|ex-yu|nova srpska scena)$"), []),
    (R(r"^(steampunk|progressive house)$"), []),
    (R(r"^instrumental$"), ["Instrumental"]),
    # --- metal
    (R(r"metalcore|deathcore|electronicore"), ["Metalcore"]),
    (R(r"progressive metal|prog metal"), ["Progressive", "Heavy Metal"]),
    (R(r"stoner|sludge"), ["Psychedelic & Stoner"]),
    (R(r"folk metal|pagan metal|celtic metal|viking"), ["Folk Metal"]),
    (R(r"symphonic|gothic metal|female.fronted"), ["Symphonic Metal"]),
    (R(r"nu.metal|alternative metal|groove metal|industrial metal|rap metal|funk metal|neue deutsche h|rapcore|djent|avant-garde metal"), ["Alternative Metal"]),
    (R(r"thrash|death(?!rock|core)|black metal|doom|grind|brutal|blackened"), ["Extreme Metal"]),
    (R(r"metal|nwobhm"), ["Heavy Metal"]),
    # --- country, americana and blues (they sit closer to each other than to classic rock)
    (R(r"country rock"), ["Country & Americana", "Rock"]),
    (R(r"country blues"), ["Country & Americana", "Blues"]),
    (R(r"country|americana|bluegrass|southern rock|heartland|roots rock|swamp rock"), ["Country & Americana"]),
    (R(r"blues"), ["Blues"]),
    # --- punk and what grew out of it
    (R(r"ska.punk"), ["Punk", "Reggae & Ska"]),
    (R(r"pop.punk"), ["Pop Punk"]),
    (R(r"folk.punk|celtic.punk"), ["Folk Punk"]),
    (R(r"post-?hardcore|screamo|emo|midwest|melodic hardcore|^hardcore$|easycore|pop screamo"), ["Emo & Hardcore"]),
    (R(r"post.?punk|new wave|cold ?wave|dark ?wave|minimal wave|ethereal|death ?rock|goth|neue deutsche welle|novi val"), ["Post-Punk & Goth"]),
    (R(r"punk"), ["Punk"]),
    (R(r"cabaret"), ["Cabaret"]),
    (R(r"comedy"), ["Comedy"]),
    # --- rock
    (R(r"rap rock"), ["Rock", "Hip Hop"]),
    (R(r"funk rock"), ["Rock", "Soul & Funk"]),
    (R(r"shoegaze|acid rock|heavy psych|psychedel|neo-psych|space rock"), ["Psychedelic & Stoner"]),
    (R(r"hard rock|glam rock|occult rock|aor|arena rock"), ["Hard Rock"]),
    (R(r"indie|jangle|lo-fi|bedroom pop|dream pop|slowcore|noise pop|chamber pop"), ["Indie"]),
    (R(r"alternative rock|^alternative$|grunge|britpop|modern rock|art rock"), ["Alternative Rock"]),
    (R(r"progressive|post-rock|experimental rock|math rock|krautrock|^experimental$"), ["Progressive"]),
    (R(r"folk rock"), ["Folk", "Rock"]),
    (R(r"industrial rock|electronic rock"), ["Rock", "Electronic"]),
    (R(r"celtic rock"), ["Celtic", "Rock"]),
    (R(r"classic rock|rock.and.roll|rockabilly|soft rock|light rock|beat music|^mod$|surf"), ["Classic Rock"]),
    (R(r"rock"), ["Rock"]),
    # --- the rest
    (R(r"hip.?hop|\brap\b|trap"), ["Hip Hop"]),
    (R(r"reggae|\bska\b|^dub$"), ["Reggae & Ska"]),
    (R(r"synth.?pop|electropop"), ["Pop", "Electronic"]),
    (R(r"celtic|irish"), ["Celtic"]),
    (R(r"folk|singer-songwriter|medieval|acoustic|polka|throat singing"), ["Folk"]),
    (R(r"soul|funk|r&b"), ["Soul & Funk"]),
    (R(r"jazz"), ["Jazz"]),
    (R(r"classical|soundtrack|opera|baroque(?! pop)"), ["Classical & Soundtrack"]),
    (R(r"electro|industrial|ebm|synthwave|dubstep|house|techno|gabber|edm|downtempo|trip hop|ambient|drone|chiptune|dance|hi-nrg|"
       r"minimal synth|noise|trance|disco|italo|boogie|drum and bass|\bidm\b|glitch|future bass|complextro|vocaloid"), ["Electronic"]),
    (R(r"pop"), ["Pop"]),
]


@lru_cache(maxsize=None)
def broad_tag(tag: str) -> tuple:
    t = tag.strip().casefold()
    for pattern, genres in RULES:
        if pattern.search(t):
            return tuple(genres)
    return ()


def broad(tags, limit=3) -> list:
    """['Gothic Rock', 'Post-Punk', 'Indie Rock'] -> ['Post-Punk & Goth', 'Indie']  (same order, no repeats)."""
    out = []
    for tag in tags or []:
        for g in broad_tag(tag):
            if g not in out:
                out.append(g)
    return out[:limit]
