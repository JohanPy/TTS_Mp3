import json
import logging
import os
import re

logger = logging.getLogger(__name__)

_DEFAULT_PRONUNCIATION_DICT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "pronunciation_dict.json"
)
_PRONUNCIATION_CACHE: tuple[str, float, dict[str, str]] | None = None

_CAPS_KEEP_ACRONYMS = {
    'LFI', 'RN', 'PS', 'LR', 'UE', 'ONU', 'OTAN', 'USA', 'CGT', 'CFDT',
    'SNCF', 'EDF', 'DGSE', 'DGSI', 'PFAS', 'BFMTV', 'FNSEA', 'UCL', 'RSA',
    'SMIC', 'TVA', 'PIB', 'PMA', 'GPA', 'IVG', 'OQTF', 'ONG', 'RSF', 'OIP',
    'AFD', 'MEDEF', 'UNESCO', 'OMS', 'FMI', 'BCE', 'INSEE', 'CNIL', 'ARCOM',
}

# --- INCLUSIVE WRITING HANDLER ---

_FEM_SUFFIXES = (
    r'trice|trices|euse|euses|rice|rices|ice|ices|elle|elles|'
    r'ère|ères|ive|ives|ne|nes|le|les|te|tes|se|ses|ve|ves|ce|ces|fe|fes|re|res|es|e'
)

_SINGULAR_OR_CONJ = {'un', 'aucun', 'chacun', 'quelqu\'un', 'quelqu’un'}

_EXPLICIT_SLASH_REPLACEMENTS = [
    (r'\b(il/elle/iel|elle/il/iel|il/elle|elle/il)\b', 'elle ou il'),
    (r'\b(ils/elles/iels|elles/ils/iels|ils/elles|elles/ils)\b', 'elles et ils'),
    (r'\b(celui/celle|celle/celui)\b', 'celle ou celui'),
    (r'\b(ceux/celles|celles/ceux)\b', 'celles et ceux'),
    (r'\b(le/la|la/le)\b', 'la ou le'),
    (r'\b(un/une|une/un)\b', 'une ou un'),
    (r'\b(mon/ma|ma/mon)\b', 'ma ou mon'),
    (r'\b(son/sa|sa/son)\b', 'sa ou son'),
    (r'\b(du/de la|de la/du)\b', 'de la ou du'),
    (r'\b(au/à la|à la/au)\b', 'à la ou au'),
]

_NEOLOGISMES = [
    (r'\bcelleux\b', 'celles et ceux'),
    (r'\bceuxlles\b', 'ceux et celles'),
    (r'\btoustes\b', 'toutes et tous'),
    (r'\biels\b', 'elles et ils'),
    (r'\biel\b', 'elle ou il'),
]


def _preserve_case(template: str, replacement: str) -> str:
    """Préserve la majuscule initiale du mot source sur le remplacement."""
    if not template or not replacement:
        return replacement
    if template[0].isupper():
        return replacement[0].upper() + replacement[1:]
    return replacement


def _sonnent_pareil(masculin: str, feminin: str) -> bool:
    """
    Détermine si le masculin et le féminin sonnent pareil à l'oral en français.
    """
    masc = masculin.lower().strip()
    fem = feminin.lower().strip()

    if masc == fem:
        return True

    masc_base = masc.rstrip('s')
    fem_base = fem.rstrip('s')

    if masc_base == fem_base:
        return True

    if (masc_base, fem_base) in {('fier', 'fière'), ('cher', 'chère')}:
        return True

    # Voyelle finale (é, i, u, o, a, y) ou r/l final + e muet :
    # ami/amie, salarié/salariée, professeur/professeure, auteur/auteure, espagnol/espagnole
    if fem_base == masc_base + 'e' and masc_base:
        if masc_base[-1] in 'éèêëiîïuûüoôaàây':
            return True
        if masc_base[-1] == 'r' and not fem_base.endswith('ère'):
            return True
        if masc_base[-1] == 'l' and not masc_base.endswith('gentil'):
            return True

    # -el / -elle (professionnel/professionnelle, actuel/actuelle)
    if masc_base.endswith('el') and fem_base == masc_base + 'le':
        return True

    return False


def _construire_formes(prefix: str, base: str, fem_suffix: str, is_plural: bool) -> tuple[str, str]:
    """
    Construit les formes (masculin, feminin) complètes à partir du préfixe élidé,
    de la base, du suffixe féminin et du nombre.
    """
    base_low = base.lower()
    fem_low = fem_suffix.lower()

    # Cas particulier : tou·te·s / tous·tes
    if base_low in ('tou', 'tous') and fem_low in ('te', 'tes'):
        masc = 'tous'
        fem = 'toutes'
        return prefix + _preserve_case(base, masc), prefix + _preserve_case(base, fem)

    # Masculin pluriel : éviter le double s (divers -> divers, Taïwanais -> Taïwanais)
    if is_plural and not base_low.endswith(('s', 'x', 'z')):
        masc_core = base + 's'
    else:
        masc_core = base

    # Féminin selon l'alternance morphologique
    plural_s = 's' if is_plural else ''
    if base_low.endswith('teur') and fem_low in ('ice', 'ices', 'rice', 'rices', 'trice', 'trices'):
        fem_core = base[:-3] + 'rice' + plural_s
    elif base_low.endswith('eur') and fem_low in ('euse', 'euses', 'se', 'ses'):
        fem_core = base[:-3] + 'euse' + plural_s
    elif base_low.endswith('f') and fem_low in ('ve', 'ves', 'ive', 'ives'):
        fem_core = base[:-1] + 've' + plural_s
    elif base_low.endswith('x') and fem_low in ('se', 'ses', 'euse', 'euses'):
        fem_core = base[:-1] + 'se' + plural_s
    elif base_low.endswith('er') and fem_low in ('ère', 'ères', 'ere', 'eres'):
        fem_core = base[:-2] + 'ère' + plural_s
    elif base_low in ('fier', 'cher') and fem_low in ('e', 'es', 'ère', 'ères', 'ere', 'eres'):
        fem_core = base[:-2] + 'ère' + plural_s
    elif base_low.endswith('ier') and fem_low in ('e', 'es'):
        fem_core = base[:-2] + 'ère' + plural_s
    else:
        fem_clean = fem_suffix[:-1] if (is_plural and fem_low.endswith('s') and len(fem_suffix) > 1) else fem_suffix
        fem_core = base + fem_clean + plural_s

    return prefix + masc_core, prefix + fem_core


def _generer_forme_parlee(prefix: str, base: str, fem_suffix: str, is_plural: bool) -> str:
    """
    Génère la forme parlée d'un mot en écriture inclusive.
    Retourne soit le masculin seul (si homophone), soit "féminin et/ou masculin".
    """
    masculin, feminin = _construire_formes(prefix, base, fem_suffix, is_plural)

    if _sonnent_pareil(masculin, feminin):
        return masculin

    base_low = base.lower()
    use_ou = (not is_plural) and (base_low in _SINGULAR_OR_CONJ or (prefix.lower() + base_low) in _SINGULAR_OR_CONJ)
    conj = 'ou' if use_ou else 'et'

    # Mettre en minuscule le second terme si le mot de départ avait une majuscule de début de phrase
    # (sauf noms composés avec trait d'union comme Afro-Américains)
    masc_out = masculin
    if not prefix and masculin and masculin[0].isupper() and '-' not in base:
        masc_out = masculin[0].lower() + masculin[1:]

    return f"{feminin} {conj} {masc_out}"


def process_inclusive_writing(text: str) -> str:
    """
    Convertit l'écriture inclusive en forme parlée pour TTS.
    """
    result = text

    # 1. Formes avec barres obliques explicites (avant les néologismes)
    for pattern, replacement in _EXPLICIT_SLASH_REPLACEMENTS:
        result = re.sub(
            pattern,
            lambda m, r=replacement: _preserve_case(m.group(0), r),
            result,
            flags=re.IGNORECASE,
        )

    # 2. Néologismes inclusifs
    for pattern, replacement in _NEOLOGISMES:
        result = re.sub(
            pattern,
            lambda m, r=replacement: _preserve_case(m.group(0), r),
            result,
            flags=re.IGNORECASE,
        )

    prefix_pat = r"(?P<prefix>(?:[A-Za-zÀ-ÿ]+[’'])?)"
    base_pat = r"(?P<base>[A-Za-zÀ-ÿ]+(?:-[A-Za-zÀ-ÿ]+)?)"

    def _replace_match(match, force_plural=False):
        prefix = match.group('prefix') or ''
        base = match.group('base')
        fem = match.group('fem')
        has_pl = force_plural
        if 'pl' in match.groupdict() and match.group('pl'):
            has_pl = True
        if not has_pl and fem.lower().endswith('s'):
            has_pl = True
        return _generer_forme_parlee(prefix, base, fem, has_pl)

    # 3. Motif A : point médian (· ou •), 3 parties puis 2 parties
    pat_median_3 = re.compile(
        rf"\b{prefix_pat}{base_pat}[·•](?P<fem>{_FEM_SUFFIXES})[·•](?P<pl>s)\b",
        flags=re.IGNORECASE,
    )
    result = pat_median_3.sub(lambda m: _replace_match(m, force_plural=True), result)

    pat_median_2 = re.compile(
        rf"\b{prefix_pat}{base_pat}[·•](?P<fem>{_FEM_SUFFIXES})\b",
        flags=re.IGNORECASE,
    )
    result = pat_median_2.sub(lambda m: _replace_match(m), result)

    # 4. Motif B : parenthèses appariées base(fem)(s) ou base(fem)s?
    pat_paren = re.compile(
        rf"\b{prefix_pat}{base_pat}\((?P<fem>{_FEM_SUFFIXES})\)(?:\((?P<pl>s)\)|(?P<pl2>s))?(?![A-Za-zÀ-ÿ])",
        flags=re.IGNORECASE,
    )
    result = pat_paren.sub(
        lambda m: _generer_forme_parlee(
            m.group('prefix') or '',
            m.group('base'),
            m.group('fem'),
            bool(m.group('pl') or m.group('pl2') or m.group('fem').lower().endswith('s')),
        ),
        result,
    )

    # 5. Motif C : point (.), 3 parties puis 2 parties (en évitant les URLs/domaines/emails)
    pat_dot_3 = re.compile(
        rf"\b{prefix_pat}{base_pat}\.(?P<fem>{_FEM_SUFFIXES})\.(?P<pl>s)\b",
        flags=re.IGNORECASE,
    )
    result = pat_dot_3.sub(lambda m: _replace_match(m, force_plural=True), result)

    pat_dot_2 = re.compile(
        rf"\b{prefix_pat}{base_pat}\.(?P<fem>{_FEM_SUFFIXES})\b(?!/)",
        flags=re.IGNORECASE,
    )

    def _replace_dot_2(match):
        start = match.start()
        ctx_before = result[max(0, start - 10):start].lower()
        if any(tok in ctx_before for tok in ('http://', 'https://', 'www.', '@')):
            return match.group(0)
        return _replace_match(match)

    result = pat_dot_2.sub(_replace_dot_2, result)

    # 6. Motif D : trait d'union uniquement en 3 parties explicites (ex: tou-te-s, citoyen-ne-s)
    pat_hyphen_3 = re.compile(
        rf"\b{prefix_pat}(?P<base>[A-Za-zÀ-ÿ]+)-(?P<fem>{_FEM_SUFFIXES})-(?P<pl>s)\b",
        flags=re.IGNORECASE,
    )
    result = pat_hyphen_3.sub(lambda m: _replace_match(m, force_plural=True), result)

    # 7. Nettoyer tout point médian résiduel et normaliser les espaces
    result = re.sub(r'[·•]', ' ', result)
    result = re.sub(r'\s+', ' ', result)
    return result


# --- ROMAN NUMERALS & ORDINALS HANDLER ---

_ROMAN_VALID_RE = re.compile(
    r'^(?:M{0,3})(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})$'
)
_FEM_ORDINAL_NOUNS_RE = re.compile(
    r'^\s*(?:République|guerre|Internationale|partie|section|édition|année|dynastie|croisade|chambre|classe|division|période|étape)\b',
    re.IGNORECASE,
)
_ORDINAL_CONTEXT_AFTER_RE = re.compile(
    r'^\s*(?:siècles?|arrondissements?|République|Reich|Internationale|guerres?|plans?|congrès|éditions?|années?|dynasties?|croisades?|millénaires?|av\.|ap\.|au\b|et\b)',
    re.IGNORECASE,
)
_ORDINAL_CONTEXT_BEFORE_RE = re.compile(
    r'\b(?:du|au|la|le|de|dès|depuis|avant|après|un|une|Paris|Lyon|Marseille)\s*$',
    re.IGNORECASE,
)

_SOUVERAINS = (
    r"Louis|Charles|Henri|Jean-Paul|Jean|Philippe|François|Guillaume|Benoît|Paul|Pie|"
    r"Napoléon|Léopold|Léon|Élisabeth|Elizabeth|Nicolas|Pierre|Catherine|Alexandre|"
    r"Frédéric|Georges|George|Édouard|Edward|Richard|Albert|Urbain|Innocent|Grégoire|"
    r"Clément|Sixte|Victor-Emmanuel|Hassan|Mohammed|Ramsès|Ptolémée|Cyrus|Darius|"
    r"Constantin|Justinien|Alphonse|Ferdinand|Isabelle|Jacques|Baudouin|Gustave|"
    r"Christian|Oscar|Harald|Olav|Margrethe|Juan Carlos|Felipe"
)
_TITRES_SOUVERAINS = r"pape|roi|reine|empereur|impératrice|tsar|tsarine|duc|duchesse|prince|princesse"
_STRUCT_MOTS = r"chapitre|tome|partie|livre|volume|acte|scène|article|annexe|section|épisode|saison|numéro|concile\s+Vatican|Vatican"


def _roman_to_int(s: str) -> int:
    """Convertit un chiffre romain strictement valide (majuscules) en entier."""
    if not s or not _ROMAN_VALID_RE.match(s):
        return 0
    rom_val = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
    int_val = 0
    for i, ch in enumerate(s):
        val = rom_val[ch]
        if i + 1 < len(s) and rom_val[s[i + 1]] > val:
            int_val -= val
        else:
            int_val += val
    return int_val


def _format_ordinal(val: int, suffix: str, context_after: str = '') -> str:
    """Formate un ordinal numérique lisible par VivienneNeural."""
    if val == 1:
        suf = suffix.lower()
        if suf in ('ère', 'ere', 're'):
            return '1re'
        if suf == 'er':
            return '1er'
        if _FEM_ORDINAL_NOUNS_RE.match(context_after):
            return '1re'
        return '1er'
    return f"{val}e"


def convertir_chiffres_romains(texte: str) -> str:
    """
    Convertit les chiffres romains en chiffres arabes (ou ordinaux) dans les contextes
    appropriés (siècles, Républiques, arrondissements, souverains, références structurelles)
    et réattache les suffixes ordinaux détachés par des balises <sup>.
    """
    result = texte

    # 2a. Réattacher les suffixes ordinaux détachés après chiffres arabes (ex: "1 er mai" -> "1er mai")
    result = re.sub(r'\b(\d+)\s+(er|ère|ere|re|ème|eme|e)\b(?![-\w])', r'\1\2', result)

    # 2a-bis. Réattacher et convertir les chiffres romains suivis d'un suffixe ordinal détaché (ex: "XIX e siècle")
    def _replace_detached_roman(match):
        rom = match.group(1)
        suf = match.group(2)
        val = _roman_to_int(rom)
        if not (1 <= val <= 39):
            return match.group(0)
        after = result[match.end():match.end() + 40]
        before = result[max(0, match.start() - 25):match.start()]
        if (
            len(rom) >= 2
            or suf.lower() in ('er', 'ère', 'ere', 're', 'ème', 'eme')
            or _ORDINAL_CONTEXT_AFTER_RE.match(after)
            or _ORDINAL_CONTEXT_BEFORE_RE.search(before)
        ):
            return _format_ordinal(val, suf, after)
        return match.group(0)

    result = re.sub(
        r'\b([IVX]+)\s+(er|ère|ere|re|ème|eme|e)\b(?![-\w’\'])',
        _replace_detached_roman,
        result,
    )

    # 2b. Chiffres romains attachés à un suffixe ordinal (ex: XVIIIe, Vème, VIe, Ier, Ire)
    def _replace_attached_roman(match):
        rom = match.group(1)
        suf = match.group(2)
        val = _roman_to_int(rom)
        if not (1 <= val <= 39):
            return match.group(0)
        after = result[match.end():match.end() + 40]
        return _format_ordinal(val, suf, after)

    result = re.sub(
        r'\b([IVX]+)(er|ère|ere|re|ème|eme|e)\b',
        _replace_attached_roman,
        result,
    )

    # 2c. Arrondissements sans suffixe (Paris IV -> Paris 4e)
    def _replace_ville_arrond(match):
        ville = match.group(1)
        val = _roman_to_int(match.group(2))
        if not (1 <= val <= 20):
            return match.group(0)
        return f"{ville} {_format_ordinal(val, 'e')}"

    result = re.sub(r'\b(Paris|Lyon|Marseille)\s+([IVX]+)\b', _replace_ville_arrond, result)

    # 2d. Souverains, papes et personnages historiques (espace ou trait d'union)
    def _replace_souverain(match):
        nom = match.group(1)
        val = _roman_to_int(match.group(2))
        if not (1 <= val <= 39):
            return match.group(0)
        if val == 1:
            return f"{nom} 1er"
        return f"{nom} {val}"

    result = re.sub(
        rf'\b({_SOUVERAINS})[\s-]+([IVX]+)\b',
        _replace_souverain,
        result,
    )

    def _replace_titre_souverain(match):
        titre = match.group(1)
        nom = match.group(2)
        val = _roman_to_int(match.group(3))
        if not (1 <= val <= 39):
            return match.group(0)
        if val == 1:
            return f"{titre} {nom} 1er"
        return f"{titre} {nom} {val}"

    result = re.sub(
        rf'\b({_TITRES_SOUVERAINS})\s+([A-ZÀ-Ÿ][a-zà-ÿ\-]+)[\s-]+([IVX]+)\b',
        _replace_titre_souverain,
        result,
        flags=re.IGNORECASE,
    )

    # 2e. Références structurelles (chapitre IV, tome II, Vatican II...)
    def _replace_struct(match):
        mot = match.group(1)
        val = _roman_to_int(match.group(2))
        if not (1 <= val <= 39):
            return match.group(0)
        return f"{mot} {val}"

    result = re.sub(
        rf'\b({_STRUCT_MOTS})\s+([IVX]+)\b',
        lambda m: _replace_struct(m) if m.group(1).lower() in (
            'chapitre', 'tome', 'partie', 'livre', 'volume', 'acte', 'scène',
            'article', 'annexe', 'section', 'épisode', 'saison', 'numéro',
            'vatican', 'concile vatican'
        ) or re.match(r'^concile\s+vatican$', m.group(1), re.I) else m.group(0),
        result,
        flags=re.IGNORECASE,
    )

    return result


# --- TEXT CLEANING & NORMALIZATION FOR TTS ---

_TECH_WHITELIST = {
    'base64', 'utf8', 'ipv4', 'ipv6', 'http2', 'html5', 'css3',
    'sqlite3', 'sha1', 'sha256', 'web3', 'llama3', 'python3',
    'gemini4', 'covid19',
}


def _deduplicate_consecutive_sentences(text: str) -> str:
    """Supprime les phrases consécutives identiques (> 40 caractères) issues d'exergues/encarts."""
    segments = re.split(r'(?<=[\.!\?…])\s+', text)
    if len(segments) <= 1:
        return text

    kept = []
    prev_norm = None
    for seg in segments:
        norm = re.sub(r'[\W_]+', ' ', seg.lower()).strip()
        if len(norm) > 40 and norm == prev_norm:
            continue
        kept.append(seg)
        if len(norm) > 40:
            prev_norm = norm
    return " ".join(kept)


def clean_text_for_tts(text: str) -> str:
    """
    Nettoie le texte pour la synthèse vocale en supprimant:
    - Caractères invisibles, tirets conditionnels, puces décoratives
    - URLs, DOI, notes de bas de page, bibliographie
    - Sections interactives, compteurs de vues, boilerplate et collisions de ponctuation
    """
    result = text

    # 0. Supprimer les caractères invisibles / tirets conditionnels (\xad) et normaliser espaces/tirets insécables
    result = re.sub(r'[\u00ad\u200b\u200c\u200d\u2060\ufeff\ufe0e\ufe0f\u21a9\ufffd]', '', result)
    result = result.replace('\u00a0', ' ').replace('\u202f', ' ').replace('\u2011', '-')
    result = re.sub(r'[►▸▪●★☆✓✔✗✘➤➔→⇒◆◇■□]', ' ', result)

    # 1. Supprimer les URLs (http://, https://, www.) et URLs nues avec slash (en préservant la ponctuation finale)
    def _strip_url_keep_punct(match):
        tok = match.group(0)
        return tok[-1] if tok and tok[-1] in '.,;:!?' else ''

    result = re.sub(r'https?://[^\s\)]+', _strip_url_keep_punct, result)
    result = re.sub(r'www\.[^\s\)]+', _strip_url_keep_punct, result)
    result = re.sub(r'\b[A-Za-z0-9-]+\.(?:org|com|fr|net|eu|io)/[^\s\)]*', _strip_url_keep_punct, result)

    # 2. Supprimer les DOI
    result = re.sub(r'doi\.org/[^\s\)]+', '', result)
    result = re.sub(r'https?://doi\.org/[^\s]+', '', result)
    result = re.sub(r'\bdoi\s*:\s*[^\s]+', '', result, flags=re.IGNORECASE)

    # 3. Supprimer les références bibliographiques typiques
    result = re.sub(
        r'\b[A-Z][a-zà-ÿ]+,\s*[A-Z]\.\s*(?:&\s*[A-Z][a-zà-ÿ]+,\s*[A-Z]\.\s*)*\(\d{4}\)\.\s*[^\.]+\.[^\.]*(?:Presses|Éditions|University|Press|Gallimard|Seuil)[^\.]*\.',
        '',
        result,
    )

    # 4. Supprimer les mentions de licence Creative Commons
    result = re.sub(r'(CC\s+BY[-\w]*|Creative\s+Commons|Tous\s+droits\s+réservés)[^\.]*\.?', '', result, flags=re.IGNORECASE)
    result = re.sub(r'Le texte seul est utilisable sous licence[^\.]+\.', '', result, flags=re.IGNORECASE)

    # 5. Supprimer les références électroniques
    result = re.sub(r'Référence électronique[^\.]*\.?', '', result, flags=re.IGNORECASE)
    result = re.sub(r'\[En ligne\][^,]*,', '', result, flags=re.IGNORECASE)
    result = re.sub(r'mis en ligne le[^,\.]+[,\.]', '', result, flags=re.IGNORECASE)
    result = re.sub(r'consulté le \d+[^\.]+\.', '', result, flags=re.IGNORECASE)
    result = re.sub(r'URL\s*:', '', result, flags=re.IGNORECASE)

    # 6. Supprimer les mentions "Paru dans..." "Articles du même auteur" et bruit éditorial résiduel
    result = re.sub(r'Paru dans[^\.]+\.', '', result, flags=re.IGNORECASE)
    result = re.sub(r'Articles? du même auteur\.?', '', result, flags=re.IGNORECASE)
    result = re.sub(r'\b\d+\s*vues?\b\.{0,3}', '', result, flags=re.IGNORECASE)
    result = re.sub(
        r'Inscrivez-vous à\s+[^\.!\?]{0,140}(?:newsletter|lettre|semaine|jours|mercredi)[^\.!\?]*[\.!\?]?',
        '',
        result,
        flags=re.IGNORECASE,
    )
    result = re.sub(r'Ne manquez plus notre newsletter[^\.!\?]*[\.!\?]?', '', result, flags=re.IGNORECASE)
    result = re.sub(r'Découvrir d[\'’]autres articles de[^\.!\?]*[\.!\?]?', '', result, flags=re.IGNORECASE)
    result = re.sub(r'Image à la Une\s*:[^\.!\?]*[\.!\?]?', '', result, flags=re.IGNORECASE)
    result = re.sub(r'Voulez-vous plonger dans les\s+secrets de\s+fabrication[^\.!\?]*[\.!\?]?', '', result, flags=re.IGNORECASE)
    result = re.sub(r'Rejoignez la\s+[«"].*?lettre enquête[^\.!\?]*[\.!\?]?', '', result, flags=re.IGNORECASE)
    result = re.sub(r'Version raccourcie tract\s*:.*$', '', result, flags=re.IGNORECASE | re.DOTALL)

    # 6b. Supprimer les renvois purement visuels / web entre parenthèses
    result = re.sub(
        r'\(\s*(?:lire\s+l[\'’]intégralité[^)]{0,120}|lire\s+aussi[^)]{0,120}|'
        r'voir\s+(?:ci-dessous|ci-dessus|encadré|annexe|plus\s+bas|plus\s+haut)[^)]{0,80}|'
        r'ci-contre)\s*\)',
        '',
        result,
        flags=re.IGNORECASE,
    )

    # 7. Supprimer les sections interactives et boilerplate
    noise_cutoff_patterns = [
        r'"Et vous\s*\?"',
        r'"Et vous aussi"',
        r'"Voir aussi"',
        r'Voir aussi\s*:',
        r'Vous avez lu gratuitement',
        r'Soutenez le club',
        r'en souscrivant un abonnement',
        r'Donnez votre avis',
        r'Réagissez à cet article',
        r'Laisser un commentaire',
    ]
    for pattern in noise_cutoff_patterns:
        m = re.search(pattern, result, flags=re.IGNORECASE)
        if m:
            result = result[:m.start()]

    # 8. Appels de notes numériques entre crochets [1], [ 12 ], [1, 2], [1-3] ou parenthèses isolées ( 9 ).
    result = re.sub(r'\[\s*\d+(?:\s*[-–,]\s*\d+)*\s*\]', '', result)
    result = re.sub(r'(?<=\S)\s*\(\s*\d{1,2}\s*\)(?=\s*[\.,;:!?—–\-])', '', result)

    # 9. Ellipses entre crochets […] ou [.] -> ...
    result = re.sub(r'\[\s*(?:…|\.{2,3}|\.)\s*\]', '...', result)

    # 10. Crochets éditoriaux ([son], [le ministre – ndlr]) -> contenu sans crochets
    result = re.sub(r'\[([^\]]+)\]', r'\1', result)
    result = re.sub(r'\bndlr\b', 'note de la rédaction', result, flags=re.IGNORECASE)

    # 11. Appels de notes en exposant Unicode après au moins 3 lettres minuscules (épargne m², km²)
    result = re.sub(r'\b([a-zà-ÿ]{3,})[¹²³⁴⁵⁶⁷⁸⁹⁰]+', r'\1', result)

    # 12. Appels de notes collés uniquement après mot tout en minuscules >= 4 lettres (épargne TF1, N3, CO2, G20, MD5, R1...)
    def _strip_footnote_digit(match):
        whole = match.group(0)
        word = match.group(1)
        if whole.lower() in _TECH_WHITELIST:
            return whole
        return word

    result = re.sub(r'\b([a-zà-ÿ]{4,})\d{1,2}(?=[\.,;:!?])', _strip_footnote_digit, result)

    # 13. Réduire les guillemets doublés/triplés et corriger espaces après apostrophes / dans parenthèses
    result = re.sub(r'"{2,}', '"', result)
    result = re.sub(r'\(\s+', '(', result)
    result = re.sub(r'\s+\)', ')', result)
    result = re.sub(
        r"\b(l|d|qu|n|s|j|c|m|t|jusqu|lorsqu|puisqu|aujourd|presqu|quelqu)(['’])\s+(?=[A-Za-zÀ-ÿ])",
        r"\1\2",
        result,
        flags=re.IGNORECASE,
    )

    # 14. Nettoyer les doubles espaces et collisions de ponctuation (en préservant ...)
    result = re.sub(r'\s+', ' ', result)
    result = re.sub(r'\s+([.,;:!?])', r'\1', result)
    result = re.sub(r'([?!])\s*\.+', r'\1', result)
    result = re.sub(r'([,:;])\s*\.+', r'\1', result)
    result = re.sub(r'\.{3}\s*[,:;]', '...', result)
    result = re.sub(r'(?<!\.)\.\s*([,:;])', r'\1', result)
    result = re.sub(r'([?!])\s*,', r'\1', result)
    result = re.sub(r'([,;:!?])\s*\1+', r'\1', result)
    result = re.sub(r'\.\s+\.\.\.', '...', result)
    result = re.sub(r'\.\.\.\s+\.', '...', result)
    result = re.sub(r'\.\s+\.', '.', result)
    result = re.sub(r'\.{4,}', '...', result)
    result = re.sub(r'(?<!\.)\.{2}(?!\.)', '.', result)
    result = re.sub(r'\(\s*\)', '', result)
    result = re.sub(r'\[\s*\]', '', result)

    # 15. Nettoyer les espaces avant ponctuation et dédupliquer phrases consécutives
    result = re.sub(r'\s+\.', '.', result)
    result = re.sub(r'\s+,', ',', result)
    result = _deduplicate_consecutive_sentences(result.strip())

    return result.strip()


def load_pronunciation_dict(path: str = _DEFAULT_PRONUNCIATION_DICT_PATH) -> dict[str, str]:
    """
    Charge un dictionnaire phonétique JSON {terme: prononciation} s'il existe.
    Met en cache le contenu tant que la date de modification du fichier ne change pas.
    """
    global _PRONUNCIATION_CACHE
    if not path or not os.path.exists(path):
        return {}
    try:
        mtime = os.path.getmtime(path)
        if _PRONUNCIATION_CACHE and _PRONUNCIATION_CACHE[0] == path and _PRONUNCIATION_CACHE[1] == mtime:
            return _PRONUNCIATION_CACHE[2]
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return {}
        cleaned = {str(k): str(v) for k, v in raw.items() if str(k).strip()}
        _PRONUNCIATION_CACHE = (path, mtime, cleaned)
        return cleaned
    except Exception as e:
        logger.warning(f"Impossible de charger le dictionnaire phonétique {path} : {e}")
        return {}


def apply_pronunciation_dict(text: str, dictionary: dict[str, str] | None = None) -> str:
    """Remplace les termes du dictionnaire phonétique par leur forme parlée (mots entiers)."""
    mapping = load_pronunciation_dict() if dictionary is None else dictionary
    if not mapping or not text:
        return text
    result = text
    for term in sorted(mapping.keys(), key=len, reverse=True):
        spoken = mapping[term]
        if not term:
            continue
        pattern = rf'(?<![\wÀ-ÿ]){re.escape(term)}(?![\wÀ-ÿ])'
        result = re.sub(pattern, lambda _m, s=spoken: s, result)
    return result


def normalize_all_caps(text: str) -> str:
    """
    Convertit les longues séquences tout en majuscules (>= 4 mots) en casse phrase
    pour éviter une diction hachée, tout en préservant les sigles courants.
    """
    if not text:
        return text

    # Séquence de mots alphabétiques tout en majuscules (incluant élisions et traits d'union)
    word_pat = r"(?:[A-ZÀ-Ÿ]{2,}(?:['’\-][A-ZÀ-Ÿ]+)*|[A-ZÀ-Ÿ]['’][A-ZÀ-Ÿ]+|À)"
    seq_re = re.compile(
        rf"{word_pat}(?:[\s,;:!\?\-–—/]+{word_pat}){{3,}}"
    )

    def _convert_span(match: re.Match) -> str:
        span = match.group(0)
        words = re.findall(r"[A-ZÀ-Ÿ]+", span)
        # Éviter de toucher une liste de sigles courts (ex: "LFI, RN, PS, UE")
        if len(words) < 4 or not any(len(w) >= 5 for w in words):
            return span

        tokens = re.split(r"([A-ZÀ-Ÿ]+)", span)
        out = []
        capitalize_next = True
        for tok in tokens:
            if not tok:
                continue
            if re.fullmatch(r"[A-ZÀ-Ÿ]+", tok):
                if tok in _CAPS_KEEP_ACRONYMS:
                    out.append(tok)
                elif capitalize_next:
                    out.append(tok[0].upper() + tok[1:].lower())
                else:
                    out.append(tok.lower())
                capitalize_next = False
            else:
                out.append(tok)
                if any(ch in tok for ch in ".!?:"):
                    capitalize_next = True
        return "".join(out)

    return seq_re.sub(_convert_span, text)


def format_list_item_for_tts(text: str) -> str:
    """
    Formate un élément de liste <li> pour une intonation naturelle :
    termine par '.' s'il est long (> 80 car.) ou multi-phrases, sinon par ','.
    """
    cleaned = text.strip()
    if not cleaned:
        return ""
    if cleaned[-1] in '.!?;:…':
        return cleaned
    if len(cleaned) > 80 or re.search(r'[.!?]\s+\S', cleaned):
        return f"{cleaned}."
    return f"{cleaned.rstrip('.')},"


def normalize_for_tts(text: str, pronunciation_dict: dict[str, str] | None = None) -> str:
    """
    Normalisations orthophoniques spécifiques pour les voix Neural françaises.
    """
    t = text
    t = re.sub(r'\b49\.3\b', '49 3', t)
    t = re.sub(r'\bn°\s*(\d+)', r'numéro \1', t, flags=re.IGNORECASE)
    t = re.sub(r'\bCO\s+2\b', 'CO2', t)
    t = re.sub(r'\bO\s+2\b', 'O2', t)
    t = re.sub(r'\bH\s+2\s*O\b', 'H2O', t)
    t = re.sub(r'\b(\d+)\s+°', r'\1°', t)
    t = re.sub(r'\bet/ou\b', 'et ou', t, flags=re.IGNORECASE)
    t = re.sub(r'\bav\.\s*J\.-C\.?', 'avant Jésus-Christ', t)
    t = re.sub(r'\bap\.\s*J\.-C\.?', 'après Jésus-Christ', t)
    t = re.sub(r'\bpp\.\s*(\d+(?:\s*[-–à]\s*\d+)?)', r'pages \1', t)
    t = re.sub(r'\bp\.\s*(\d+)', r'page \1', t)
    t = re.sub(r'\bcf\.\s*', 'voir ', t, flags=re.IGNORECASE)
    t = re.sub(r'\bc\.-à-d\.?', "c'est-à-dire", t, flags=re.IGNORECASE)
    t = re.sub(r'\bvol\.\s*(\d+)', r'volume \1', t, flags=re.IGNORECASE)

    def _replace_mde(match):
        num = match.group(1).strip()
        unit = "milliard d'euros" if num == "1" else "milliards d'euros"
        return f"{num} {unit}"

    t = re.sub(r'(\d[\d\s,\.]*)\s*Mds?€', _replace_mde, t)
    t = re.sub(r'(\d[\d\s,\.]*)\s*k€', r'\1 mille euros', t)
    t = apply_pronunciation_dict(t, pronunciation_dict)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def build_article_intro(title: str, author: str = "", media: str = "") -> str:
    """
    Construit une introduction audio propre sans mention 'Unknown' ni répétition média/auteur.
    """
    clean_media = (media or "").strip()
    if not clean_media or clean_media == "Unknown Media":
        clean_media = ""
    elif "|" in clean_media:
        clean_media = clean_media.split("|", 1)[0].strip()

    clean_author = (author or "").strip()
    if not clean_author or clean_author == "Unknown Author":
        clean_author = ""
    elif clean_media and clean_author.lower() == clean_media.lower():
        clean_author = ""

    clean_title = (title or "").strip()
    if not clean_title or clean_title == "Unknown Title":
        clean_title = ""

    parts = []
    if clean_media:
        parts.append(f"Article de {clean_media}... ")
    if clean_title:
        parts.append(f"{clean_title}... ")
    if clean_author:
        parts.append(f"Par {clean_author}... ")
    return "".join(parts)


def strip_leading_duplicate_title(title: str, text_body: str) -> str:
    """
    Retire le titre s'il est répété en tête du corps de l'article.
    """
    if not title or not text_body or title.strip() == "Unknown Title":
        return text_body

    words = re.findall(r'\w+', title, flags=re.UNICODE)
    if len(" ".join(words)) < 10:
        return text_body

    pattern = (
        r'^[\s"«“\'’\(]*'
        + r'[\W_]+'.join(re.escape(w) for w in words)
        + r'(?:[\s"»”\'’\)]*[\.\!\?:;…\-–—]+|[\s"»”\'’\)]*$)'
    )
    m = re.match(pattern, text_body, flags=re.IGNORECASE)
    if not m:
        return text_body

    remainder = text_body[m.end():].strip()
    if len(remainder) >= 30:
        return remainder
    return text_body


def prepare_text_for_tts(text: str) -> str:
    """
    Pipeline complet et unifié de préparation du texte avant envoi au TTS.
    """
    t = re.sub(r'\s+', ' ', text).strip()
    t = clean_text_for_tts(t)
    t = convertir_chiffres_romains(t)
    t = process_inclusive_writing(t)
    t = normalize_all_caps(t)
    t = normalize_for_tts(t)
    return t


def preprocess_for_api(text: str) -> str:
    """
    Nettoie le texte avant envoi à l'API pour améliorer la qualité du résumé.
    """
    t = text

    # 1. Supprimer les guillemets typographiques de section ("Titre..." .. "Sous-titre...")
    t = re.sub(r'^(?:\s*"[^"]{0,300}"\s*\.{0,3}\s*)+', '', t, flags=re.DOTALL)

    # 2. Couper au premier marqueur de section-parasites
    noise_markers = [
        r'"Et vous\s*\?"',
        r'"Voir aussi"',
        r'"Et vous aussi"',
        r'Vous avez lu gratuitement',
        r'Soutenez le club',
        r'en souscrivant un abonnement',
        r'Donnez votre avis',
        r'Réagissez à cet article',
        r'Laisser un commentaire',
    ]
    for marker in noise_markers:
        m = re.search(marker, t, flags=re.IGNORECASE)
        if m:
            t = t[:m.start()]

    # 3. Remplacer les séparateurs TTS « .. » par un espace propre
    t = re.sub(r'\s*\.\.\s*', ' ', t)

    # 4. Supprimer les lignes trop courtes (< 20 chars) qui sont des artefacts
    lines = [l.strip() for l in t.splitlines()]
    lines = [l for l in lines if len(l) >= 20 or l == '']
    t = ' '.join(lines)

    # 5. Normaliser les espaces
    t = re.sub(r'\s+', ' ', t).strip()

    if len(t) < 100:
        logger.debug("Pré-traitement API : texte trop court après nettoyage, utilisation du texte original")
        return text

    logger.debug(
        f"Pré-traitement API : {len(text)} → {len(t)} chars "
        f"({100 * len(t) // len(text)}% conservé)"
    )
    return t


def strip_markdown_for_tts(text: str) -> str:
    """
    Supprime les éléments Markdown du texte pour que le TTS le lise correctement.
    """
    t = text
    t = re.sub(r'\*{2}(.+?)\*{2}', r'\1', t)
    t = re.sub(r'_{2}(.+?)_{2}', r'\1', t)
    t = re.sub(r'\*(.+?)\*', r'\1', t)
    t = re.sub(r'_(.+?)_', r'\1', t)
    t = re.sub(r'`(.+?)`', r'\1', t)
    t = re.sub(r'^#{1,6}\s+', '', t, flags=re.MULTILINE)
    t = re.sub(r'^\s*[\*\-\+]\s+', '', t, flags=re.MULTILINE)
    t = re.sub(r'^\s*\d+\.\s+', '', t, flags=re.MULTILINE)
    t = re.sub(r'\n{2,}', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t
