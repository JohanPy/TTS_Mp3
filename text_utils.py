import re
import logging

logger = logging.getLogger(__name__)

# --- INCLUSIVE WRITING HANDLER ---

# Homophones: mots qui s'écrivent différemment au masculin/féminin mais sonnent pareil
# Le masculin suffit à l'oral
HOMOPHONES_RACINES = {
    # Terminaisons en -é (ami/amie, salarié/salariée)
    "ami", "amie", "salari", "déput", "charg", "employ", "invit", "concern",
    "abonn", "engag", "fatigu", "motiv", "détermin", "passionn", "diplôm",
    "qualifi", "expériment", "intéress", "touch", "affect", "impliqu",
    "préoccup", "inform", "consult", "réuni", "assembl", "group", "rassembl",
    "marqu", "salu", "accompagn", "guid", "orient", "form", "sensibilis",
    "mobilis", "organis", "structur", "coordonn", "délég", "mandaté",
    "autoris", "habilit", "certifi", "agré", "reconnu", "validé",
    # Autres terminaisons muettes
    "auteur", "lecteur", "acteur", "directeur", "professeur"
}

def _sonnent_pareil(masculin: str, feminin: str) -> bool:
    """
    Détermine si le masculin et le féminin sonnent pareil à l'oral.
    Utilise des règles phonétiques françaises + liste d'exceptions.
    """
    masc = masculin.lower().strip()
    fem = feminin.lower().strip()
    
    if masc == fem:
        return True
    
    masc_base = masc.rstrip('s')
    fem_base = fem.rstrip('s')
    
    for racine in HOMOPHONES_RACINES:
        if masc_base.endswith(racine) or masc_base == racine:
            return True
    
    if fem_base.startswith(masc_base):
        suffixe = fem_base[len(masc_base):]
        if suffixe in ['e', 'es', '']:
            if masc_base and masc_base[-1] in 'éèêëiîïuûüoôaàâ':
                return True
    
    if masc.endswith('eur') and fem.endswith('euse'):
        return False
    if masc.endswith('teur') and fem.endswith('trice'):
        return False
    if masc.endswith('if') and fem.endswith('ive'):
        return False
    if masc.endswith('eux') and fem.endswith('euse'):
        return False
    
    return False

def _generer_forme_parlee(masculin: str, feminin: str) -> str:
    """
    Génère la forme parlée d'un mot en écriture inclusive.
    Retourne soit le masculin seul (si homophone), soit "féminin et masculin".
    """
    if _sonnent_pareil(masculin, feminin):
        return masculin
    else:
        return f"{feminin} et {masculin}"

def process_inclusive_writing(text: str) -> str:
    """
    Convertit l'écriture inclusive en forme parlée pour TTS.
    """
    result = text
    
    neologismes = {
        r'\bcelleux\b': 'celles et ceux',
        r'\bceuxlles\b': 'ceux et celles',
        r'\biels\b': 'elles et ils',
        r'\biel\b': 'elle ou il',
        r'\bae\b': 'a ou e',
    }
    for pattern, replacement in neologismes.items():
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    
    def replace_full_pattern(match):
        base = match.group(1)
        suffix1 = match.group(2)
        suffix2 = match.group(3)
        
        if suffix2:
            masculin = base + suffix2
            feminin = base + suffix1 + suffix2
        else:
            masculin = base
            feminin = base + suffix1
        
        return _generer_forme_parlee(masculin, feminin)
    
    separateurs = r'[·\-\.\(\)]'
    pattern_pluriel = rf'(\w+){separateurs}(\w+){separateurs}([s])\b'
    result = re.sub(pattern_pluriel, replace_full_pattern, result)
    
    def replace_short_pattern(match):
        base = match.group(1)
        suffix = match.group(2)
        
        if suffix.endswith('s'):
            masculin = base + 's'
            feminin = base + suffix
        else:
            masculin = base
            feminin = base + suffix
        
        return _generer_forme_parlee(masculin, feminin)
    
    pattern_court = rf'(\w+){separateurs}([eé]s?|ne|rice|euse|ive|se)\b'
    result = re.sub(pattern_court, replace_short_pattern, result, flags=re.IGNORECASE)
    
    result = re.sub(r'·', ' ', result)
    result = re.sub(r'\s+', ' ', result)
    return result

def convertir_chiffres_romains(texte):
    """
    Convertit les chiffres romains (I, V, X) en chiffres arabes dans des contextes spécifiques
    (siècles, arrondissements, noms de souverains) pour faciliter la lecture par le TTS.
    """
    def roman_to_int(s):
        rom_val = {'I': 1, 'V': 5, 'X': 10}
        int_val = 0
        s = s.upper()
        for i in range(len(s)):
            if s[i] not in rom_val:
                continue
            if i > 0 and rom_val[s[i]] > rom_val[s[i - 1]]:
                int_val += rom_val[s[i]] - 2 * rom_val[s[i - 1]]
            else:
                int_val += rom_val[s[i]]
        return int_val

    def replace_siecle(match):
        roman = match.group(1)
        mot_siecle = match.group(3)
        val = roman_to_int(roman)
        if val == 1:
            return f"1er {mot_siecle}"
        return f"{val}ème {mot_siecle}"

    texte = re.sub(r'\b([IVX]+)(e|ème|eme|er)?\s+(siècle|siecles|siècles)\b',
                   replace_siecle, texte, flags=re.IGNORECASE)

    def replace_arrond(match):
        roman = match.group(1)
        mot_arrond = match.group(3)
        val = roman_to_int(roman)
        if val == 1:
            return f"1er {mot_arrond}"
        return f"{val}ème {mot_arrond}"

    texte = re.sub(r'\b([IVX]+)(e|ème|eme|er)?\s+(arrondissement|arrondissements)\b',
                   replace_arrond, texte, flags=re.IGNORECASE)

    def replace_ville_arrond(match):
        ville = match.group(1)
        roman = match.group(2)
        val = roman_to_int(roman)
        return f"{ville} {val}"

    texte = re.sub(r'\b(Paris|Lyon|Marseille)\s+([IVX]+)(e|ème)?\b', replace_ville_arrond, texte)

    def replace_souverain(match):
        nom = match.group(1)
        roman = match.group(2)
        val = roman_to_int(roman)
        if val == 1:
            return f"{nom} 1er"
        return f"{nom} {val}"

    noms_rois = r"(Louis|Charles|Henri|Jean|Philippe|François|Guillaume|Benoît|Paul|Pie|Jean-Paul|Napoléon|Léopold)"
    texte = re.sub(r'\b' + noms_rois + r'\s+([IVX]+)(er|e)?\b', replace_souverain, texte)

    return texte

def clean_text_for_tts(text: str) -> str:
    """
    Nettoie le texte pour la synthèse vocale en supprimant:
    - URLs, DOI, notes de bas de page, bibliographie
    - Sections interactives et boilerplate
    """
    result = text
    
    # 1. Supprimer les URLs (http://, https://, www.)
    result = re.sub(r'https?://[^\s\)]+', '', result)
    result = re.sub(r'www\.[^\s\)]+', '', result)
    
    # 2. Supprimer les DOI
    result = re.sub(r'doi\.org/[^\s\)]+', '', result)
    result = re.sub(r'https?://doi\.org/[^\s]+', '', result)
    result = re.sub(r'\bdoi\s*:\s*[^\s]+', '', result, flags=re.IGNORECASE)
    
    # 3. Supprimer les numéros de notes entre crochets [1], [2], etc.
    result = re.sub(r'\[\d+\]', '', result)
    
    # 4. Supprimer les appels de notes (numéros seuls en exposant ou après un mot)
    result = re.sub(r'(?<=[a-zA-Zà-ÿ])\d{1,2}(?=[\.,;:!?])', '', result)
    
    # 5. Supprimer les références bibliographiques typiques
    result = re.sub(r'\b[A-Z][a-zà-ÿ]+,\s*[A-Z]\.\s*(?:&\s*[A-Z][a-zà-ÿ]+,\s*[A-Z]\.\s*)*\(\d{4}\)\.\s*[^\.]+\.[^\.]*(?:Presses|Éditions|University|Press|Gallimard|Seuil)[^\.]*\.', '', result)
    
    # 6. Supprimer les mentions de licence Creative Commons
    result = re.sub(r'(CC\s+BY[-\w]*|Creative\s+Commons|Tous\s+droits\s+réservés)[^\.]*\.?', '', result, flags=re.IGNORECASE)
    result = re.sub(r'Le texte seul est utilisable sous licence[^\.]+\.', '', result, flags=re.IGNORECASE)
    
    # 7. Supprimer les références électroniques
    result = re.sub(r'Référence électronique[^\.]*\.?', '', result, flags=re.IGNORECASE)
    result = re.sub(r'\[En ligne\][^,]*,', '', result, flags=re.IGNORECASE)
    result = re.sub(r'mis en ligne le[^,\.]+[,\.]', '', result, flags=re.IGNORECASE)
    result = re.sub(r'consulté le \d+[^\.]+\.', '', result, flags=re.IGNORECASE)
    result = re.sub(r'URL\s*:', '', result, flags=re.IGNORECASE)
    
    # 8. Supprimer les mentions "Paru dans..." "Articles du même auteur"
    result = re.sub(r'Paru dans[^\.]+\.', '', result, flags=re.IGNORECASE)
    result = re.sub(r'Articles? du même auteur\.?', '', result, flags=re.IGNORECASE)

    # 9. Supprimer les sections interactives et boilerplate
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
    
    # 10. Supprimer les notes numérotées en début de phrase
    result = re.sub(r'\.\s+\d{1,2}\s+[A-Z][^\.]{10,150}(?:\.\.\.|\.\s)', '. ', result)
    
    # 11. Nettoyer les doubles espaces et ponctuation orpheline
    result = re.sub(r'\s+', ' ', result)
    result = re.sub(r'\s+([.,;:!?])', r'\1', result)
    result = re.sub(r'([.,;:!?])\s*\1+', r'\1', result)
    result = re.sub(r'\(\s*\)', '', result)
    result = re.sub(r'\[\s*\]', '', result)
    
    # 12. Nettoyer les espaces avant ponctuation
    result = re.sub(r'\s+\.', '.', result)
    result = re.sub(r'\s+,', ',', result)
    
    return result.strip()

def preprocess_for_api(text: str) -> str:
    """
    Nettoie le texte avant envoi à l'API pour améliorer la qualité du résumé.
    """
    t = text

    # 1. Supprimer les guillemets typographiques de section ("Titre..." .. "Sous-titre...") 
    t = re.sub(r'^(?:\s*"[^"]{0,300}"\s*\.{0,3}\s*)+', '', t, flags=re.DOTALL)

    # 2. Couper au premier marqueur de section-parasites (mutualisé avec TTS mais peut être plus permissif)
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
